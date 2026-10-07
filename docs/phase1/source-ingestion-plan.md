# 来源接入：资料准备与后续插件

当前系统接收标准化 JSON，也可以经原文 API 对 HTML/Markdown/文本进行可编排预处理。没有 URL 抓取、二进制文件上传、OCR 或导入 Worker。本文维护资料准备与后续连接器方向；预处理接口和策略见[文档预处理](preprocessing.md)，DTO 与验收见[首期技术设计](phase1-technical-design.md)，运行命令见 [README](../../README.md)。

## 1. 当前如何准备资料

| 来源 | 获取与准备方式 | 后续连接器方向 |
| --- | --- | --- |
| 社团语雀 | 获授权成员读取/导出文档，保留标题、表格和日期，提交 Markdown/HTML 或标准 JSON | 用获准 Token 调用官方 API，或读取稳定导出格式；实际账号能力待验证 |
| 笔吧评测室推文 | 使用获准单篇文章/文件，核对账号、日期、机型和测试条件，提交 HTML/Markdown 或标准 JSON | 单篇读取／文件接入先行；官方公众号 API 需要对应账号权限，不能假定能全量读取第三方公众号 |
| 社团维修记录 | 成员先脱敏，区分现象、检查、措施、结果和未确认项，再整理成标准 JSON | 读取登记系统或文本；与其他来源共用导入和检索服务 |

原站可以阅读不自动代表允许复制、公开或发送给外部模型。维护者确认使用范围，并在 SourceSpec 中设置 `visibility`；正文和日志不带个人信息或凭据。

准备时保留以下信息：

- **稳定身份**：`source_type`、`canonical_locator` 与 `source_url` 分开。语雀可用已核验的知识库／文档 ID，微信可用文章标识；ID 不可得时用人工稳定键，不随意删除链接参数或虚构永久地址。
- **内容与日期**：标题、真实来源日期、表头、单位、配置、测试条件和原有警告。未知日期留空，不用导入日期替代；图片关键参数人工补录为文字并注明依据。
- **父子与定位**：明确父段、子块及稳定 key，子块原文必须包含在父段中。首个笔记本评测策略按“一台笔记本一个父段，多台分开”；其他内容类型独立确定边界。
- **附加信息**：渠道信息可放文档 metadata，具体机型或条件可放相应父段／子块 metadata。当前不从 metadata 自动生成筛选条件。

标准化请求见 [basic.json](../../fixtures/iteration1/basic.json)，该入口不再清洗/拆段。原文请求见[文档预处理](preprocessing.md)，按所选类型策略生成父子段落，保留 Markdown 有意义空格并控制 Evidence 输入长度。

## 2. 当前提交与更新

```text
维护者获取资料、脱敏并整理父子段落
  → {source: SourceSpec, document: ProcessedDocument}
  → POST /api/v1/sources/
  → 校验与权限检查 → Embedding → 事务保存
  → POST /api/v1/search/ 返回命中父段
```

同一来源内容更新时重新提交整份标准 JSON，保留未变段落的 key；缺席段落会被删除，现有 ID 指向当前内容。没有任务领取、复核、发布或版本切换步骤。模型配置变化时也须重新导入，维护者应保留整理输入或能够重新取得资料。

原文提交为 `{source, preprocess: {schema, version}, raw: {content, media_type, metadata}} → POST /api/v1/sources/raw/`。选择 product_review、purchase_guide 或 experience_case，预处理产物复用相同导入/检索链。相同原文产生稳定 key，正文修改可更新已有父子行；标题或边界策略变化后 key 可能变化，应重新导入整份原文。

## 3. 后续插件如何接入

```text
SourceConnector.fetch(locator) → RawDocument
  → 按 document_schema + schema_version 选择 DocumentPreprocessor
  → ProcessedDocument → 公共校验 → import_processed
```

平台与内容类型独立：语雀中的经验案例和基础知识可以复用连接器，使用不同结构策略。已实现 HTML/Markdown 解析器、三类分段策略、预算切分及原文 API；新增步骤/类型在组合根显式注册，保存和检索只依赖统一 DTO。具体平台连接器与同步机制仍待开发。

首个插件先用单篇离线样本验收，再扩展读取和同步。验收重点是单／多机型边界、正文覆盖、图片补录、表头单位、风险警告、来源日期、稳定 key 与定位；插件输出通过公共校验，现有导入及检索回归通过。不能把“成功读取页面”当作“内容处理正确”。

## 4. 官方参考与待验证项

以下平台线索来自 2026-09-28 的调研，本次实现离线预处理，没有重新验证平台读取能力：

- [语雀 OpenAPI 定义](https://github.com/yuque/openapi-metadata/blob/master/yuque.tea)、[官方 MCP Server](https://github.com/yuque/yuque-mcp-server) 与[能力范围](https://github.com/yuque/yuque-mcp-server/blob/main/docs/capability-scope.md)：社团 Token、整库导出格式与分页权限尚待实际账号验证。
- [微信发布能力](https://developers.weixin.qq.com/doc/service/guide/product/publish.html) 与[已发布消息列表](https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_batchget.html)：依赖对应账号凭证与权限，不是任意第三方文章库接口。
- 既有单篇页面观察存在图片 `src` 占位、`data-src` 提供真实地址的情况；批量读取、图片处理和 OCR 未验证，应在插件实现时用当前页面复核。
