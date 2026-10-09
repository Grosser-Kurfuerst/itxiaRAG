# 来源接入：资料准备与后续连接器

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
- **边界与定位**：标准化入口需要调用方明确父段、子块及稳定 key，子块原文必须包含在父段中；原文入口需要保留可识别标题并选择结构策略；单机评测须提供机型名 entity_title，多机型评测通过 entity_headings 指定边界。具体规则见[文档预处理](preprocessing.md#3-内容结构策略)。
- **附加信息**：渠道信息可放文档 metadata，具体机型或条件可放相应父段／子块 metadata。当前不从 metadata 自动生成筛选条件。

选择提交方式：

| 资料状态 | 提交方式 | 谁负责父子分段与模型输入长度 |
| --- | --- | --- |
| 已整理好完整父子关系 | 标准化 JSON，样例见 [basic.json](../../fixtures/iteration1/basic.json) | 调用方；入口只校验，不再清洗或拆段 |
| 已取得 HTML／Markdown／文本原文 | 原文请求，样例见[文档预处理](preprocessing.md#6-原文导入-api) | 注册的结构策略与预算切分器；调用方提供来源、类型与边界提示 |

## 2. 当前提交与更新

```text
维护者获取获准资料、脱敏并保留来源信息
  ├─ 已分段：POST /api/v1/sources/ → ProcessedDocument
  └─ 原文：POST /api/v1/sources/raw/ → 预处理 → ProcessedDocument
      → 公共校验与权限检查 → Embedding → 事务保存
      → POST /api/v1/search/ 返回命中父段
```

同一来源内容更新时重新提交整份标准 JSON 或原文；同 key 段落保留 ID，缺席段落会被删除，现有 ID 指向当前内容。没有任务领取、复核、发布或版本切换步骤。模型配置变化时也须重新导入，维护者应保留整理输入或能够重新取得资料。去重与更新契约统一见[技术设计](phase1-technical-design.md#41-重复与更新)。

原文入口选择 product_review、purchase_guide 或 experience_case，均复用相同导入／检索链。相同原文、元数据、策略版本和预算产生稳定 key；标题、边界或切分配置变化可能改变 key，评测子块按序号生成 key、正文增删也可能改变，重新导入前应检查变化后的父子边界。接口和长度限制以预处理专项文档为准。

## 3. 后续连接器如何接入

```text
未来 SourceConnector.fetch(locator) → RawDocument
  → 按 document_schema + schema_version 选择 DocumentPreprocessor
  → ProcessedDocument → 公共校验 → import_processed
```

平台与内容类型独立：语雀中的经验案例和基础知识可以复用连接器，使用不同结构策略。已实现 HTML/Markdown 解析器、三类分段策略、预算切分及原文 API；新增步骤/类型在组合根显式注册，保存和检索只依赖统一 DTO。具体平台连接器与同步机制仍待开发。语雀的分批导入（类别清单、方言解析、章节策略与导入命令）见[语雀文档导入方案](yuque-ingestion/overview.md)，目前为方案阶段。

SourceConnector 当前只有协议，没有具体平台实现。接入连接器时先用单篇离线样本验收，再扩展读取和同步。验收重点是正文完整性、标题层级、图片补录、表头单位、风险警告、来源日期和稳定身份；预处理输出通过公共校验，并完成[预处理专项与导入检索回归](../unit-testing-guidelines.md)。不能把“成功读取页面”当作“内容处理正确”。

## 4. 官方参考与待验证项

以下平台线索来自 2026-09-28 的调研，当前仅实现离线预处理，没有重新验证平台读取能力：

- [语雀 OpenAPI 定义](https://github.com/yuque/openapi-metadata/blob/master/yuque.tea)、[官方 MCP Server](https://github.com/yuque/yuque-mcp-server) 与[能力范围](https://github.com/yuque/yuque-mcp-server/blob/main/docs/capability-scope.md)：社团 Token、整库导出格式与分页权限尚待实际账号验证。
- [微信发布能力](https://developers.weixin.qq.com/doc/service/guide/product/publish.html) 与[已发布消息列表](https://developers.weixin.qq.com/doc/service/api/public/api_freepublish_batchget.html)：依赖对应账号凭证与权限，不是任意第三方文章库接口。
- 既有单篇页面观察存在图片 `src` 占位、`data-src` 提供真实地址的情况；批量读取、图片处理和 OCR 未验证，应在插件实现时用当前页面复核。
