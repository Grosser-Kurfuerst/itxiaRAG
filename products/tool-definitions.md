# 工具定义：知识检索与机型推荐

本文给上层系统的开发者使用，对应[机型规格库方案 3.3 节](../docs/phase3/product-spec-design.md#33-工具定义)。上层 LLM 通过两个工具使用检索系统：

- `search_knowledge` 对应 `POST /api/v1/search/`；
- `recommend_laptops` 对应 `POST /api/v1/products/recommend/`。

接口契约以[首期技术设计第 6 节](../docs/phase1/phase1-technical-design.md#6-api-与错误)为准。第 1 节的提示词放进上层系统的系统提示词，第 2、3 节的 JSON 可以直接作为 function calling 的工具定义。JSON 按 OpenAI 的 `{name, description, parameters}` 格式书写，用 Chat Completions 时包成 `{"type": "function", "function": {...}}`；用 Anthropic 接口时，把 `parameters` 改名为 `input_schema`。Schema 含可选字段和 `default`，只适用于非 strict 模式。评测脚本从本文读取提示词和工具定义，所以只有这三个代码块使用 `text`、`json` 标记，示例使用 `jsonc` 标记。

## 1. 提示词

```text
你是 IT 侠知识库助手，回答笔记本选购、电脑使用、软件、网络和维修问题。先调用工具获取资料，再依据资料回答，不要凭记忆编造。

【选择工具】
- 问具体机型的事实、配置、拆机、维修、软件或使用问题，用 search_knowledge。例：“雷神 猎刃S 的内存是板载的吗”“笔记本风扇突然很吵怎么办”。
- 按预算、重量、尺寸、显卡、屏幕、接口、续航、品牌、用途挑机型，用 recommend_laptops。例：“一万五以内的游戏本”“预算 6000 的编程用笔记本”。
- 既要挑机型、又要了解候选机型的细节时，先调用 recommend_laptops，再把感兴趣机型的 review.source.id 放进 search_knowledge 的 filters.source_ids 查细节。例：“一万二左右的轻薄本，哪台散热好、能自己换硬盘”。

【把说法换算成原子条件】recommend_laptops 只接受原子条件，下面是参考口径，可以按语境调整：
- 预算 X：price_min = 0.75X，price_max = 1.1X。
- X 以内：price_max = X；X 左右：0.9X～1.1X；X 多：X～X+999；X 以上：price_min = X。
- 轻薄：weight_max = 1.5。
- 游戏本：is_gaming = true。
- 显卡 N 以上：gpu_in 列出档次不低于 N 的型号。档次由低到高为 RTX 3050 < RTX 5060 < RTX 5070 < RTX 5070Ti < RTX 5080 < RTX 5090。
- 接口丰富：ports = ["usb_a", "usb_c", "video_out"]。能接网线：ports = ["rj45"]。
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

## 2. 知识检索 `search_knowledge`

```json
{
  "name": "search_knowledge",
  "description": "检索 IT 侠知识库（评测、购机指南、教程、知识、工具、排障经验，含校园网、软件与维修），返回完整段落及来源。用于具体机型的事实、配置以及使用、软件、网络、维修问题，不用于按条件挑机型。",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "minLength": 1,
        "maxLength": 2000,
        "description": "检索问题，保留机型名和关键术语，例如“来酷 GT16 内存插槽”。"
      },
      "filters": {
        "type": "object",
        "properties": {
          "source_ids": {
            "type": "array",
            "items": {"type": "string", "format": "uuid"},
            "minItems": 1,
            "maxItems": 50,
            "description": "只在这些来源中检索；可以填写 recommend_laptops 结果中的 review.source.id。省略表示不限来源。"
          }
        },
        "additionalProperties": false
      },
      "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5, "description": "返回的段落数。"}
    },
    "required": ["query"],
    "additionalProperties": false
  }
}
```

## 3. 机型推荐 `recommend_laptops`

```json
{
  "name": "recommend_laptops",
  "description": "按原子条件从已评测的笔记本中筛选机型，并按 preference 在评测正文中排序。返回规格卡、评测结论和与偏好相关的评测段落。口语条件需先按提示词中的参考口径换算。字段没有数据的机型视为不满足该条件。结果为空时返回 diagnostics，系统不会自动放宽条件。",
  "parameters": {
    "type": "object",
    "properties": {
      "conditions": {
        "type": "object",
        "description": "硬条件，全部满足才入选；省略表示不过滤。",
        "properties": {
          "price_min": {"type": "number", "minimum": 0, "description": "价格下限（元）。价格是评测时的价格，不是实时价格。"},
          "price_max": {"type": "number", "minimum": 0, "description": "价格上限（元）。"},
          "weight_max": {"type": "number", "minimum": 0, "description": "重量上限（kg）。"},
          "screen_min": {"type": "number", "minimum": 0, "description": "屏幕尺寸下限（英寸）。"},
          "screen_max": {"type": "number", "minimum": 0, "description": "屏幕尺寸上限（英寸）。"},
          "battery_min": {"type": "number", "minimum": 0, "description": "续航下限（小时），只指评测中“日常应用仿真”的成绩。许多机型没有该数据，没有数据视为不满足。"},
          "gpu_in": {
            "type": "array",
            "items": {"type": "string", "enum": ["RTX 3050", "RTX 5060", "RTX 5070", "RTX 5070Ti", "RTX 5080", "RTX 5090"]},
            "minItems": 1,
            "maxItems": 20,
            "description": "独显型号，满足其中之一即可；没有独显的机型不满足。"
          },
          "has_dgpu": {"type": "boolean", "description": "是否有独立显卡。"},
          "is_gaming": {"type": "boolean", "description": "是否游戏本：有 RTX 独显且定位为游戏本，创作本、全能本、商务本、双屏本除外。"},
          "panel": {"type": "string", "enum": ["oled", "lcd", "miniled"], "description": "屏幕面板类型。"},
          "ports": {
            "type": "array",
            "items": {"type": "string", "enum": ["usb_a", "usb_c", "video_out", "hdmi", "rj45", "card_reader", "thunderbolt", "oculink"]},
            "minItems": 1,
            "maxItems": 8,
            "description": "必须全部具备的接口：usb_a、usb_c；video_out 为任一视频输出（HDMI、DP 或支持 DP 的 USB-C）；hdmi；rj45 网口；card_reader 读卡器；thunderbolt 雷电或 USB4；oculink。"
          },
          "brands": {
            "type": "array",
            "items": {"type": "string", "enum": ["ALIENWARE", "LG", "ROG", "ThinkPad", "七彩虹", "华为", "华硕", "小米", "微星", "微软", "惠普", "机械师", "机械革命", "神舟", "红米", "联想", "苹果", "荣耀", "雷神", "雷蛇"]},
            "minItems": 1,
            "maxItems": 20,
            "description": "品牌，满足其中之一即可。子品牌 ROG、ThinkPad、红米单列，不归入华硕、联想、小米；问母品牌的全部机型时连同子品牌一起列出。"
          }
        },
        "additionalProperties": false
      },
      "preference": {
        "type": "string",
        "maxLength": 500,
        "description": "无法换算成条件的偏好，例如“性能释放强、散热好”。为空时按评测日期由新到旧排序。"
      },
      "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5, "description": "返回的机型数。"}
    },
    "additionalProperties": false
  }
}
```

### 3.1 可选值

`gpu_in` 和 `brands` 的可选值来自规格文件 [bibar.json](specs/bibar.json)。规格文件新增型号或品牌后，用下面的命令重新生成，更新第 3 节的 `enum`；`gpu_in` 的 enum 与第 1 节的档次都要手工按档次由低到高排列（`unique` 按字符排序）。单元测试会检查本文与规格文件、接口字段是否一致。

```sh
jq -c '[.[].gpu | select(.)] | unique' products/specs/bibar.json
jq -c '[.[].brand] | unique' products/specs/bibar.json
```

接口按调用者可见的机型校验可选值。传入不可见或不存在的值会返回 400，错误信息会列出当前可选值，上层可以据此修正后重试。显卡型号会先规范写法，例如 `rtx5070 ti` 会变成 `RTX 5070Ti`。

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
