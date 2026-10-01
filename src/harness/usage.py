"""token 消耗统计。

独立成模块是为了让「写入方」（runner）和「读取方」（runs_index）都能引用，
而不产生循环依赖；顺带让只读的运行浏览器不必加载整个 agents SDK。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TokenUsage:
    """从 generation span 汇总出来的真实消耗。"""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0

    def render(self) -> str:
        parts = [
            f"{self.calls} 次调用",
            f"输入 {self.input_tokens}",
            f"输出 {self.output_tokens}",
        ]
        if self.reasoning_tokens:
            parts.append(f"其中思维链 {self.reasoning_tokens}")
        if self.cached_tokens:
            parts.append(f"缓存命中 {self.cached_tokens}")
        parts.append(f"合计 {self.total_tokens} tokens")
        return "，".join(parts)


def summarize_usage(spans: list[dict[str, Any]]) -> TokenUsage:
    usage = TokenUsage()
    for span in spans:
        if span.get("type") != "generation":
            continue
        # 有 generation span 就算一次模型调用，哪怕服务端没返回 usage
        usage.calls += 1
        raw = span.get("usage")
        if not isinstance(raw, dict):
            continue
        details_in = raw.get("input_tokens_details")
        details_out = raw.get("output_tokens_details")
        usage.input_tokens += raw.get("input_tokens", 0) or 0
        usage.output_tokens += raw.get("output_tokens", 0) or 0
        usage.total_tokens += raw.get("total_tokens", 0) or 0
        if isinstance(details_in, dict):
            usage.cached_tokens += details_in.get("cached_tokens", 0) or 0
        if isinstance(details_out, dict):
            usage.reasoning_tokens += details_out.get("reasoning_tokens", 0) or 0
    return usage


__all__ = ["TokenUsage", "summarize_usage"]
