# 文档预处理

## 流水线与扩展点

`ingestion/preprocessing.py` 实现 `DocumentPreprocessor` 协议的顺序流水线，最终输出公共 `ProcessedDocument`，复用导入校验与保存流程。

```text
RawDocument → ParseStep → StructureStep → ChunkStep → BuildDocumentStep → ValidateStep
阶段：raw      blocks       units          chunked         document          validated
```

流程由有序步骤列表配置。新增能力实现 `PreprocessStep.process(context)` 并声明 `input_stage/output_stage`；兼容阶段的步骤可以增删、调序。例如两个 `blocks → blocks` 的清洗步骤可自由调整先后顺序，结构划分必须在解析之后，校验必须在构建之后。不允许 HTTP 请求加载 Python 路径或自行指定代码。

构造时检查阶段连接和最终 `validated` 阶段；运行时检查步骤返回类型、实际输出阶段及最终文档，错误直接传播，不生成半成品文档。步骤由应用代码显式注册，不构成不可信代码沙箱。

| 通用部分 | 可替换部分 |
| --- | --- |
| Pipeline 的执行与阶段检查 | ParseStep 注入 Parser，适配 HTML、Markdown 等格式 |
| 内部 ContentBlock、SemanticContext、SemanticEvidence | StructureStep 注入 StructureStrategy，决定不同类型的父子边界 |
| ChunkStep 的调用接口 | 注入 Chunker，按当前模型预算控制长度 |
| 公共 DTO 构建与校验 | 组合根选择 schema、version 及具体步骤列表 |

内部对象不落表，且不改变现有 ContextDraft/EvidenceDraft 契约。通过 Protocol 和组合实现 Pipeline、Strategy、Adapter 模式，避免深层继承。

## 实施状态

已实现通用流水线、步骤协议、内存对象与公共 DTO 构建/校验；具体解析器、分段策略和原文 API 在后续功能提交中接入。当前标准化 JSON API 行为保持不变。
