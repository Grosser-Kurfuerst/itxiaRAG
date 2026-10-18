# 工具定义：知识检索与机型推荐

本文给上层系统的开发者使用，对应[机型规格库方案 3.3 节](../docs/phase3/product-spec-design.md#33-工具定义)。上层 LLM 通过 MCP 服务提供的两个工具使用检索系统：

- `search_knowledge` 对应 `POST /api/v1/search/`；
- `recommend_laptops` 对应 `POST /api/v1/products/recommend/`。

接口契约以[首期技术设计第 6 节](../docs/phase1/phase1-technical-design.md#6-api-与错误)为准。工具定义由 MCP 服务根据 [mcp_server/server.py](../mcp_server/server.py) 的函数签名和 [contracts/](../contracts/) 中的 pydantic 模型生成，不再在本文手写 JSON。第 1 节提示词放进 persona 的系统提示词，工具名相应改为 `mcp__search_knowledge`、`mcp__recommend_laptops`；MCP 接入方式见[MCP 服务方案](../docs/phase3/mcp-server-design.md)。评测脚本从本文读取提示词，并从 MCP 服务读取工具 schema。本文只有提示词使用 `text` 代码块，调用示例使用 `jsonc` 标记。

## 1. 提示词

```text
你是 IT 侠知识库助手，回答笔记本选购、电脑使用、软件、网络和维修问题。先调用工具获取资料，再依据资料回答，不要凭记忆编造。

【选择工具】
- 问具体机型的事实、配置、拆机、维修、软件或使用问题，用 search_knowledge。例：“雷神 猎刃S 的内存是板载的吗”“笔记本风扇突然很吵怎么办”。
- 按预算、重量、尺寸、显卡、屏幕、接口、续航、品牌、用途挑机型，用 recommend_laptops。例：“一万五以内的游戏本”“预算 6000 的编程用笔记本”。
- 既要挑机型、又要了解候选机型的细节时，先调用 recommend_laptops，再把感兴趣机型的 review.source.id 放进 search_knowledge 的 filters.source_ids 查细节。例：“一万二左右的轻薄本，哪台散热好、能自己换硬盘”。

【把说法换算成原子条件】recommend_laptops 只接受原子条件，下面是参考口径，可以按语境调整：
- 预算 X：price_min = 0.75X，price_max = 1.1X；和其他条件一起出现时也这样换算，“预算 X”不等于“X 以内”。
- X 以内：price_max = X；X 左右：0.9X～1.1X；X 多：X～X+999；X 以上：price_min = X。“预算”后面带这些说法时按这一行换算，例如“预算一万左右”为 9000～11000。
- 轻薄：weight_max = 1.5；轻薄游戏本：weight_max = 2。
- 游戏本：is_gaming = true。
- 显卡 N 以上：gpu_in 列出档次不低于 N 的型号。档次由低到高为 RTX 3050 < RTX 5060 < RTX 5070 < RTX 5070Ti < RTX 5080 < RTX 5090。
- 接口丰富：ports = ["usb_a", "usb_c", "video_out"]。能接网线：ports = ["rj45"]。TGX 接口即 OCuLink：ports = ["oculink"]。
- OLED 屏：panel = "oled"。
- 续航 N 小时以上：battery_min = N。
- “性能释放强”“散热好”“屏幕素质好”等无法换算成条件的诉求，写进 preference。
- 用户没提到的条件不要添加。多轮对话中，用户没有撤销的条件要沿用。
- 只说“推荐个电脑”这类没有任何条件的请求，先问预算和用途。

【使用推荐结果】
- result_status 为 no_result 时，查看 diagnostics.satisfied：数值最小的条件最严格。优先放宽它，并告诉用户放宽了什么；不要擅自放宽预算上限，除非用户同意。
- unknown 表示有多少台机型只因某个字段没有数据而落选（例如很多机型没有续航成绩）。数量较多时应告诉用户。
- 价格是评测时的价格（口径见 spec.price_kind），不是实时价格。
- review.highlights 只说明评测中有相关段落，不代表一定满足偏好。回答时引用 conclusions 和 highlights 的原文，附上评测链接 review.source.url，不要编造规格。
```

## 2. 工具定义

工具 schema 由 MCP 服务生成，persona 通过 Streamable HTTP 直接读取，不需要再从本文复制。需要检查或保存当前定义时执行：

```sh
python manage.py shell -c "import asyncio, json; from mcp_server.server import mcp; \
print(json.dumps([t.model_dump(by_alias=True, include={'name', 'description', 'input_schema'}) for t in asyncio.run(mcp.list_tools())], ensure_ascii=False, indent=2))"
```

`search_knowledge` 的顶层参数是 `query`、`filters`、`top_k`，只有 `query` 必填；`recommend_laptops` 的顶层参数是 `conditions`、`preference`、`top_k`，都可省略。字段约束和说明维护在 `contracts/query.py`、`contracts/products.py`，REST 与 MCP 共用。

## 3. 参数说明

### 3.1 可选值

`gpu_in` 和 `brands` 的可选值来自 [contracts/products.py](../contracts/products.py) 中的 `GPUS`、`BRANDS`，接口只按这两个常量校验。规格文件 [bibar.json](specs/bibar.json) 新增型号或品牌后，需要同步更新常量；单元测试会检查常量与规格文件一致。显卡型号会先规范写法，例如 `rtx5070 ti` 会变成 `RTX 5070Ti`。

不在常量中的值返回 400，错误信息会列出全部可选值。常量中有的值如果调用者没有可见机型，或库中已经没有对应机型，推荐返回 `no_result`，由上层查看 `diagnostics` 后放宽条件。

## 4. 结果说明

推荐结果 `products[]` 每项为 `{key, spec, review}`，字段说明见[首期技术设计第 6 节](../docs/phase1/phase1-technical-design.md#6-api-与错误)。回答时主要用到以下字段：

| 字段 | 含义 |
| --- | --- |
| `spec` | 规格卡。字段为 `null` 表示没有数据，不表示没有该配置 |
| `review.conclusions` | 评测结论栏目的子块，最多 3 个；没有结论栏目时取最后一个子块 |
| `review.highlights` | `preference` 在该评测中的命中子块，最多 2 个。`score` 是 RRF 分数，只用于排序；向量路没有相似度门槛，命中不代表一定满足偏好 |
| `review.source.id` | 评测来源 ID，可以作为 `search_knowledge` 的 `filters.source_ids` |
| `unknown` | 只因该字段没有数据而落选的机型数，键是规格字段名，例如 `battery_hours` |
| `diagnostics` | 结果为空时给出 `{total, satisfied}`，`satisfied` 是单独满足每个条件的机型数；有结果时为 `null` |

数据覆盖（2026-10-13 统计，示例中的数字同此）：规格文件共 78 台，均有价格，其中 31 台没有续航成绩。CPU、内存容量、内存扩展方式和硬盘容量已按评测补齐，目前用于规格展示，不作为推荐条件。

## 5. 调用示例

只有硬条件：

```jsonc
// 用户：一万五以内，显卡要 5080 以上的游戏本
{"name": "recommend_laptops", "arguments": {"conditions": {
  "price_max": 15000, "is_gaming": true, "gpu_in": ["RTX 5080", "RTX 5090"]}}}
```

硬条件加偏好：

```jsonc
// 用户：一万以内的 16 寸本，屏幕要好
{"name": "recommend_laptops", "arguments": {
  "conditions": {"price_max": 10000, "screen_min": 16}, "preference": "屏幕素质好"}}
```

具体机型的问题：

```jsonc
// 用户：雷神 猎刃S 的内存是板载的吗
{"name": "search_knowledge", "arguments": {"query": "雷神 猎刃S 内存 板载 插槽"}}
```

先推荐、再查细节：

```jsonc
// 用户：一万二左右的轻薄本，哪台散热好、能自己换硬盘
{"name": "recommend_laptops", "arguments": {
  "conditions": {"price_min": 10800, "price_max": 13200, "weight_max": 1.5}, "preference": "散热好"}}
// 再对感兴趣的机型查询，source_ids 取上一步结果中的 review.source.id
{"name": "search_knowledge", "arguments": {"query": "硬盘 M.2 插槽 更换",
  "filters": {"source_ids": ["<review.source.id>"]}}}
```

结果为空后放宽条件：

```jsonc
// 用户：6000 以内的 OLED 轻薄本，续航 12 小时以上
{"name": "recommend_laptops", "arguments": {"conditions": {
  "price_max": 6000, "panel": "oled", "weight_max": 1.5, "battery_min": 12}}}
// 响应
{"result_status": "no_result", "products": [], "unknown": {},
 "diagnostics": {"total": 78, "satisfied": {"price_max": 11, "panel": 29, "weight_max": 29, "battery_min": 19}}}
// 预算是用户的硬约束，先放宽续航，并告诉用户：没有续航超过 12 小时的，以下机型的续航接近
{"name": "recommend_laptops", "arguments": {"conditions": {
  "price_max": 6000, "panel": "oled", "weight_max": 1.5}, "preference": "续航长"}}
```
