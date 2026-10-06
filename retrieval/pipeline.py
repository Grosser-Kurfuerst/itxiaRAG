"""按组合根提供的顺序执行步骤，检查阶段与批次类型。"""

from contracts.types import (
    ContextBatch,
    EvidenceBatch,
    RouteBatch,
    SearchBatch,
    SearchRequest,
    SearchStep,
)


_BATCH_STAGES = {
    RouteBatch: "routes",
    EvidenceBatch: "evidence",
    ContextBatch: "contexts",
}


def _stage(batch: SearchBatch):
    for batch_type, stage in _BATCH_STAGES.items():
        if isinstance(batch, batch_type):
            return stage
    raise TypeError(f"不支持的检索批次类型: {type(batch).__name__}")


class PostRecallPipeline:
    """有序步骤列表；不动态加载代码，也不吞掉步骤异常。"""

    def __init__(self, steps: list[SearchStep]):
        self.steps = tuple(steps)
        self._validate_steps()

    def _validate_steps(self):
        expected = "routes"
        for step in self.steps:
            if step.output_stage not in _BATCH_STAGES.values():
                raise ValueError(f"步骤 {type(step).__name__} 声明了未知输出阶段")
            if step.input_stage != expected:
                raise ValueError(
                    f"步骤 {type(step).__name__} 的输入阶段为 {step.input_stage}，"
                    f"预期为 {expected}")
            expected = step.output_stage
        if expected != "contexts":
            raise ValueError("召回后处理流水线必须以 contexts 阶段结束")

    def run(self, request: SearchRequest, routes: RouteBatch) -> ContextBatch:
        batch: SearchBatch = routes
        for step in self.steps:
            if _stage(batch) != step.input_stage:
                raise TypeError(f"步骤 {type(step).__name__} 收到错误批次阶段")
            batch = step.process(request, batch)
            if _stage(batch) != step.output_stage:
                raise TypeError(f"步骤 {type(step).__name__} 返回了错误批次阶段")
        if not isinstance(batch, ContextBatch):
            raise TypeError("流水线未返回 ContextBatch")
        # 自定义父段步骤也不能突破请求约定的数量上限。
        return ContextBatch(batch.contexts[:request.top_k])
