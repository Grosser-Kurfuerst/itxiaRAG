"""处理器只接触查询内容；身份、过滤和结果上限留在调用侧。"""
from copy import deepcopy
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Protocol

from contracts.serializers import StrictString


@dataclass(frozen=True)
class QueryInput:
    query: str
    scenario: str | None = None
    confirmed_context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedQuery:
    original_query: str
    retrieval_query: str
    effective_scenario: str
    scenario_source: str
    status: str = "noop"
    processor_id: str = "noop-v1"
    suggested_context: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class QueryProcessor(Protocol):
    def prepare_query(self, input: QueryInput) -> PreparedQuery: ...


class NoOpQueryProcessor:
    def prepare_query(self, input):
        return PreparedQuery(input.query, input.query, input.scenario or "general",
                             "caller" if input.scenario else "default")


def prepare(input, mode, processor, timeout_ms, processor_id="noop-v1", clock=monotonic):
    baseline = NoOpQueryProcessor().prepare_query(input)
    if mode == "bypass":
        return replace(baseline, status="bypassed", processor_id=processor_id)
    start = clock()
    try:
        output = processor.prepare_query(deepcopy(input))
        # 当前同步 NoOp 不阻塞；未来外部适配器须在自身 I/O 设置同一超时。
        if (clock() - start) * 1000 > timeout_ms:
            raise TimeoutError
        if not isinstance(output, PreparedQuery):
            raise ValueError("invalid output")
        query = StrictString(max_length=2000).run_validation(output.retrieval_query)
        if (output.original_query != input.query or output.effective_scenario != "general"
                or output.scenario_source != baseline.scenario_source
                or output.suggested_context != {} or output.status not in ("noop", "applied")
                or output.warnings or (output.status == "noop" and query != input.query)):
            raise ValueError("unsupported or inconsistent output")
        return replace(output, retrieval_query=query, processor_id=processor_id)
    except Exception:
        # 不输出扩展实现异常中的 query／凭据；回退不改变调用方约束。
        return replace(baseline, status="fallback", processor_id=processor_id,
                       warnings=("QUERY_PROCESSING_FALLBACK",))
