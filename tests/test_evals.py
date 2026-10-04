"""评估框架自己的测试。

一个量别人的框架，自己没测试说不过去。这里只测不依赖模型的部分 ——
runner 的纯函数、fixture 校验、置信区间。
"""

from __future__ import annotations

import json
from pathlib import Path

from evals import runner as runner_module
from evals.compare import wilson
from evals.runner import Report, TaskResult, _snapshot, _specs, list_tasks, write_report

TASKS = Path(__file__).resolve().parent.parent / "evals" / "tasks"


# ---- 用例集的完整性 ----


def test_every_task_has_meta_and_workspace():
    tasks = list_tasks(TASKS)
    assert tasks, "一个用例都没找到"

    for meta in tasks:
        assert meta.get("id"), f"{meta['dir']} 缺 id"
        assert meta.get("goal"), f"{meta['id']} 缺 goal"
        assert meta.get("category"), f"{meta['id']} 缺 category"
        assert (Path(meta["dir"]) / "workspace").is_dir()


def test_every_task_ships_at_least_one_hidden_test():
    """没有隐藏测试的用例等于没有防作弊能力。"""
    for meta in list_tasks(TASKS):
        hidden = list((Path(meta["dir"]) / "verify").rglob("*.py"))
        assert hidden, f"{meta['id']} 没写隐藏测试"


def test_task_ids_are_unique():
    ids = [meta["id"] for meta in list_tasks(TASKS)]
    assert len(ids) == len(set(ids))


# ---- runner 的纯函数 ----


def test_specs_picks_up_docstrings(tmp_path):
    (tmp_path / "mod.py").write_text(
        '"""Module doc."""\n\n\ndef f():\n    """Function doc."""\n',
        encoding="utf-8",
    )

    specs = _specs(tmp_path)

    assert "mod.py" in specs
    assert "Module doc." in specs["mod.py"]
    assert "Function doc." in specs["mod.py"]


def test_specs_ignores_test_files(tmp_path):
    """测试文件的 docstring 改动不算改规格。"""
    (tmp_path / "test_x.py").write_text('"""Tests."""\n', encoding="utf-8")

    assert _specs(tmp_path) == {}


def test_specs_survives_a_syntax_error(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n", encoding="utf-8")

    assert _specs(tmp_path) == {}


def test_snapshot_reads_only_python_files(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me\n", encoding="utf-8")

    snapshot = _snapshot(tmp_path)

    assert list(snapshot) == ["a.py"]


def test_write_report_can_checkpoint_partial_results(tmp_path):
    report = Report(results=[TaskResult(task_id="demo", passed=True, tokens=12)])
    target = tmp_path / "nested" / "report.json"

    write_report(target, report)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["passed"] == 1
    assert payload["total"] == 1
    assert payload["results"][0]["task_id"] == "demo"
    assert payload["results"][0]["tokens"] == 12


def test_run_all_sequential_path(monkeypatch):
    seen = []

    def fake_run_task(meta, *, model=None):
        seen.append((meta["id"], model))
        return TaskResult(task_id=meta["id"], passed=True)

    monkeypatch.setattr(runner_module, "run_task", fake_run_task)

    results = runner_module.run_all(
        [{"id": "a"}, {"id": "b"}], model="test-model", workers=1
    )

    assert [result.task_id for result in results] == ["a", "b"]
    assert seen == [("a", "test-model"), ("b", "test-model")]


# ---- 置信区间 ----


def test_wilson_interval_brackets_the_estimate():
    low, high = wilson(5, 6)
    assert low < 5 / 6 < high


def test_wilson_interval_is_wide_for_small_samples():
    """6 个样本算出来的区间必须很宽 —— 这是它存在的意义。"""
    low, high = wilson(5, 6)
    assert high - low > 0.3


def test_wilson_interval_narrows_as_samples_grow():
    small = wilson(5, 6)
    big = wilson(50, 60)
    assert (big[1] - big[0]) < (small[1] - small[0])


def test_wilson_handles_no_samples():
    assert wilson(0, 0) == (0.0, 0.0)
