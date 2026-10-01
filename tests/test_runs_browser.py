"""运行浏览器的数据层和 HTTP 层测试。"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from harness.config import HarnessConfig
from harness.runs_index import (
    STATE_FILENAME,
    SUMMARY_FILENAME,
    RunNotFound,
    build_summary,
    list_runs,
    load_run,
)
from harness.server import serve


def write_run(
    runs_dir: Path,
    run_id: str,
    *,
    goal: str = "测试任务",
    session_id: str | None = None,
    usage: dict | None = None,
    spans: list | None = None,
    transcript: list | None = None,
) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    payload = {
        "goal": goal,
        "session_id": session_id,
        "final_output": "done",
        "last_agent": "supervisor",
        "duration_s": 1.5,
        "model_calls": 2,
        "transcript": transcript if transcript is not None else [],
        "spans": spans if spans is not None else [],
    }
    if usage is not None:
        payload["usage"] = usage
    (run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir


def test_list_runs_on_missing_dir_is_empty(tmp_path):
    assert list_runs(tmp_path / "nope") == []


def test_list_runs_sorts_newest_first(tmp_path):
    write_run(tmp_path, "20260101-090000", goal="早")
    write_run(tmp_path, "20260101-120000", goal="晚")
    write_run(tmp_path, "20260101-110000", goal="中")

    assert [r.goal for r in list_runs(tmp_path)] == ["晚", "中", "早"]


def test_list_runs_uses_stored_usage(tmp_path):
    write_run(
        tmp_path,
        "20260101-090000",
        usage={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
    )

    summary = list_runs(tmp_path)[0]

    assert summary.total_tokens == 120
    assert summary.input_tokens == 100


def test_list_runs_falls_back_to_spans_for_old_records(tmp_path):
    """最早的记录写在 usage 字段存在之前，要从 span 现算。"""
    spans = [
        {
            "type": "generation",
            "usage": {"input_tokens": 30, "output_tokens": 5, "total_tokens": 35},
        }
    ]
    write_run(tmp_path, "20260101-090000", spans=spans)

    summary = list_runs(tmp_path)[0]

    # usage 从 span 现算
    assert summary.total_tokens == 35
    assert summary.input_tokens == 30
    # model_calls 仍以存储值为准（老记录里本来就有这个字段）
    assert summary.model_calls == 2


def test_usage_stored_as_string_is_recovered(tmp_path):
    """老记录的 usage 被存成了 dict 的字符串形式，应该能解析回来。"""
    spans = [
        {
            "type": "generation",
            "usage": "{'requests': 1, 'input_tokens': 865, "
            "'output_tokens': 422, 'total_tokens': 1287}",
        }
    ]
    write_run(tmp_path, "20260101-090000", spans=spans)

    summary = list_runs(tmp_path)[0]

    assert summary.input_tokens == 865
    assert summary.output_tokens == 422
    assert summary.total_tokens == 1287


def test_unparseable_usage_string_does_not_crash(tmp_path):
    spans = [{"type": "generation", "usage": "这不是 dict"}]
    write_run(tmp_path, "20260101-090000", spans=spans)

    summary = list_runs(tmp_path)[0]

    assert summary.total_tokens == 0


def test_list_runs_skips_corrupt_directories(tmp_path):
    write_run(tmp_path, "20260101-090000", goal="好的")
    broken = tmp_path / "20260101-100000"
    broken.mkdir()
    (broken / "run.json").write_text("{ 不是合法 json", encoding="utf-8")
    (tmp_path / "不是运行记录").mkdir()

    goals = [r.goal for r in list_runs(tmp_path)]

    assert goals == ["好的"]


def test_display_time_formats_run_id():
    from harness.runs_index import RunSummary

    summary = RunSummary("20261001-144004", "", "", 0, 0, 0, 0, 0, 0, 0)

    assert summary.display_time == "10-01 14:40:04"


@pytest.mark.parametrize(
    "bad_id",
    ["../../etc", "..", "20260101-090000/../..", "", "not-a-run-id", "20260101"],
)
def test_load_run_rejects_unsafe_ids(tmp_path, bad_id):
    write_run(tmp_path, "20260101-090000")

    with pytest.raises(RunNotFound):
        load_run(tmp_path, bad_id)


def test_load_run_returns_full_payload(tmp_path):
    write_run(
        tmp_path,
        "20260101-090000",
        goal="看这里",
        transcript=[{"kind": "ToolCallItem", "tool": "coder"}],
    )

    data = load_run(tmp_path, "20260101-090000")

    assert data["summary"]["goal"] == "看这里"
    assert data["transcript"][0]["tool"] == "coder"


def _start_server(runs_dir: Path):
    config = HarnessConfig(runs_dir=runs_dir, workspace=runs_dir / "_ws")
    httpd = serve(config, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return httpd, f"http://{host}:{port}"


def test_server_serves_page_and_api(tmp_path):
    write_run(tmp_path, "20260101-090000", goal="从网页看")
    httpd, base = _start_server(tmp_path)
    try:
        page = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8")
        assert "Harness Runs" in page

        listing = json.loads(urllib.request.urlopen(base + "/api/runs", timeout=10).read())
        assert listing["runs"][0]["goal"] == "从网页看"

        detail = json.loads(
            urllib.request.urlopen(base + "/api/runs/20260101-090000", timeout=10).read()
        )
        assert detail["summary"]["goal"] == "从网页看"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_returns_404_for_bad_run_id(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(base + "/api/runs/..%2F..%2Fetc", timeout=10)
        assert excinfo.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_server_exposes_sessions(tmp_path):
    write_run(tmp_path, "20260101-090000", goal="第一轮", session_id="alpha")
    write_run(tmp_path, "20260101-100000", goal="第二轮", session_id="alpha")
    write_run(tmp_path, "20260101-110000", goal="不带会话")

    httpd, base = _start_server(tmp_path)
    try:
        payload = json.loads(
            urllib.request.urlopen(base + "/api/sessions", timeout=10).read()
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert len(payload["sessions"]) == 1
    assert payload["sessions"][0]["session_id"] == "alpha"
    assert payload["sessions"][0]["run_count"] == 2


def test_run_summary_reports_session_id(tmp_path):
    write_run(tmp_path, "20260101-090000", session_id="alpha")

    assert list_runs(tmp_path)[0].session_id == "alpha"


def test_list_runs_prefers_the_small_summary_file(tmp_path):
    """列表优先读 summary.json —— 完整 run.json 里 spans 占了九成以上。"""
    run_dir = write_run(tmp_path, "20260101-090000", goal="来自完整记录")
    (run_dir / SUMMARY_FILENAME).write_text(
        json.dumps({"goal": "来自摘要", "model_calls": 7}), encoding="utf-8"
    )

    summary = list_runs(tmp_path)[0]

    assert summary.goal == "来自摘要"
    assert summary.model_calls == 7


def test_corrupt_summary_falls_back_to_full_record(tmp_path):
    run_dir = write_run(tmp_path, "20260101-090000", goal="完整记录")
    (run_dir / SUMMARY_FILENAME).write_text("{ 这不是 json", encoding="utf-8")

    assert list_runs(tmp_path)[0].goal == "完整记录"


def test_missing_summary_falls_back_to_full_record(tmp_path):
    """老记录没有 summary.json，必须照样能读出来。"""
    run_dir = write_run(tmp_path, "20260101-090000", goal="老记录")
    assert not (run_dir / SUMMARY_FILENAME).exists()

    assert list_runs(tmp_path)[0].goal == "老记录"


def test_build_summary_resolves_usage_instead_of_copying_it():
    """摘要必须把 usage 算好再存。

    摘要里没有 spans，一旦直接复制顶层那个可能缺失/被字符串化的 usage，
    数字就永久丢了 —— 这个 bug 真的发生过。
    """
    data = {
        "goal": "老记录",
        "spans": [
            {
                "type": "generation",
                "usage": "{'input_tokens': 865, 'output_tokens': 422, "
                "'total_tokens': 1287}",
            }
        ],
    }

    summary = build_summary(data)

    assert summary["usage"]["input_tokens"] == 865
    assert summary["usage"]["total_tokens"] == 1287


def test_summary_round_trip_keeps_the_token_numbers(tmp_path):
    """写摘要再读回来，数字不能变。"""
    spans = [
        {
            "type": "generation",
            "usage": "{'input_tokens': 865, 'output_tokens': 422, "
            "'total_tokens': 1287}",
        }
    ]
    run_dir = write_run(tmp_path, "20260101-090000", spans=spans)
    full = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    (run_dir / SUMMARY_FILENAME).write_text(
        json.dumps(build_summary(full)), encoding="utf-8"
    )

    summary = list_runs(tmp_path)[0]

    assert summary.input_tokens == 865
    assert summary.total_tokens == 1287


# ---- 写操作（批准 / 拒绝）----


class _FakeOutcome:
    run_id = "20260101-090001"
    status = "completed"
    final_output = "完成"
    pending: list = []


def _post(url: str, headers: dict | None = None):
    request = urllib.request.Request(
        url, data=b"", method="POST", headers=headers or {}
    )
    return urllib.request.urlopen(request, timeout=10)


def _seed_pending(run_dir: Path) -> None:
    """造出「有待处理状态」的痕迹，让服务认为这次运行可以续跑。"""
    (run_dir / STATE_FILENAME).write_text("{}", encoding="utf-8")


def _wait_for_task(base: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = urllib.request.urlopen(base + "/api/tasks", timeout=5).read()
        task = json.loads(raw)["task"]
        if task is None or task["finished"]:
            return task
        time.sleep(0.05)
    raise AssertionError("任务没在预期时间内结束")


def test_action_requires_the_custom_header(tmp_path):
    """本地服务唯一的写操作必须有 CSRF 防护。

    跨域请求带自定义头会先发预检，而服务不响应预检 —— 浏览器会把
    恶意页面发起的请求挡住。
    """
    write_run(tmp_path, "20260101-090000")
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(base + "/api/runs/20260101-090000/approve")
        assert excinfo.value.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_approve_reaches_the_resume_path(tmp_path, monkeypatch):
    run_dir = write_run(tmp_path, "20260101-090000")
    _seed_pending(run_dir)
    seen: list = []

    def fake_resume(config, run_id, approve, cancel_token=None):
        seen.append((run_id, approve))
        return _FakeOutcome()

    monkeypatch.setattr("harness.server._resume_run", fake_resume)
    httpd, base = _start_server(tmp_path)
    try:
        started = json.loads(
            _post(
                base + "/api/runs/20260101-090000/approve",
                {"X-Harness-Action": "1"},
            ).read()
        )
        # 服务立刻返回，不等任务跑完
        assert started["started"] is True
        task = _wait_for_task(base)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert task["outcome_run_id"] == "20260101-090001"
    assert task["error"] is None
    assert seen == [("20260101-090000", True)]


def test_reject_passes_approve_false(tmp_path, monkeypatch):
    run_dir = write_run(tmp_path, "20260101-090000")
    _seed_pending(run_dir)
    seen: list = []

    def fake_resume(config, run_id, approve, cancel_token=None):
        seen.append((run_id, approve))
        return _FakeOutcome()

    monkeypatch.setattr("harness.server._resume_run", fake_resume)
    httpd, base = _start_server(tmp_path)
    try:
        _post(
            base + "/api/runs/20260101-090000/reject", {"X-Harness-Action": "1"}
        ).read()
        _wait_for_task(base)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert seen == [("20260101-090000", False)]


def test_tasks_endpoint_is_empty_when_idle(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        payload = json.loads(
            urllib.request.urlopen(base + "/api/tasks", timeout=5).read()
        )
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert payload["task"] is None


def test_cancel_without_a_running_task_is_conflict(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(base + "/api/tasks/cancel", {"X-Harness-Action": "1"})
        assert excinfo.value.code == 409
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---- 从网页发起任务 ----


def _post_json(url: str, payload: dict):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"X-Harness-Action": "1", "Content-Type": "application/json"},
    )
    return urllib.request.urlopen(request, timeout=10)


def test_start_a_run_from_the_web(tmp_path, monkeypatch):
    seen: list = []

    def fake_new_run(config, goal, session_id, cancel_token):
        seen.append((goal, session_id))
        return _FakeOutcome()

    monkeypatch.setattr("harness.server._new_run", fake_new_run)
    httpd, base = _start_server(tmp_path)
    try:
        started = json.loads(
            _post_json(base + "/api/runs", {"goal": "写个 README"}).read()
        )
        assert started["started"] is True
        task = _wait_for_task(base)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert task["outcome_run_id"] == "20260101-090001"
    assert seen == [("写个 README", None)]


def test_start_a_run_with_a_session(tmp_path, monkeypatch):
    seen: list = []

    def fake_new_run(config, goal, session_id, cancel_token):
        seen.append(session_id)
        return _FakeOutcome()

    monkeypatch.setattr("harness.server._new_run", fake_new_run)
    httpd, base = _start_server(tmp_path)
    try:
        _post_json(base + "/api/runs", {"goal": "继续", "session_id": "demo"}).read()
        _wait_for_task(base)
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert seen == ["demo"]


def test_empty_goal_is_rejected(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post_json(base + "/api/runs", {"goal": "   "})
        assert excinfo.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_invalid_session_id_is_rejected(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post_json(base + "/api/runs", {"goal": "任务", "session_id": "../坏"})
        assert excinfo.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_malformed_body_is_rejected(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        request = urllib.request.Request(
            base + "/api/runs",
            data="{ 不是 json".encode("utf-8"),
            method="POST",
            headers={"X-Harness-Action": "1", "Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=10)
        assert excinfo.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_start_run_requires_the_custom_header(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        request = urllib.request.Request(
            base + "/api/runs",
            data=json.dumps({"goal": "任务"}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=10)
        assert excinfo.value.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_second_action_while_busy_is_conflict(tmp_path, monkeypatch):
    """同一时刻只允许一个任务 —— 追踪状态是进程级全局的。"""
    release = threading.Event()

    def slow_resume(config, run_id, approve, cancel_token=None):
        release.wait(timeout=5)
        return _FakeOutcome()

    monkeypatch.setattr("harness.server._resume_run", slow_resume)
    run_dir = write_run(tmp_path, "20260101-090000")
    _seed_pending(run_dir)
    httpd, base = _start_server(tmp_path)
    try:
        _post(
            base + "/api/runs/20260101-090000/approve", {"X-Harness-Action": "1"}
        ).read()
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(
                base + "/api/runs/20260101-090000/approve",
                {"X-Harness-Action": "1"},
            )
        assert excinfo.value.code == 409
    finally:
        release.set()
        _wait_for_task(base)
        httpd.shutdown()
        httpd.server_close()


def test_action_on_a_non_pending_run_returns_conflict(tmp_path):
    """已经处理过的运行不该被当成成功。"""
    write_run(tmp_path, "20260101-090000")  # 没有 state.json
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(
                base + "/api/runs/20260101-090000/approve",
                {"X-Harness-Action": "1"},
            )
        assert excinfo.value.code == 409
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_action_with_unsafe_run_id_is_404(tmp_path):
    httpd, base = _start_server(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            _post(
                base + "/api/runs/..%2F..%2Fetc/approve",
                {"X-Harness-Action": "1"},
            )
        assert excinfo.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
