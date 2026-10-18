# MCP 服务方案

状态：方案，待确认（2026-10-18）。对应[机型规格库方案](product-spec-design.md) P3 的上层接入。

## 1. 目标与边界

上层问答机器人 kei-plugin-persona 只通过 MCP 使用外部工具。本方案新增一个 MCP 服务，把知识检索和机型推荐作为两个工具提供给它：

| 工具 | 对应接口 | 用途 |
| --- | --- | --- |
| `search_knowledge` | `POST /api/v1/search/` | 具体机型的事实、配置，以及使用、软件、网络、维修问题 |
| `recommend_laptops` | `POST /api/v1/products/recommend/` | 按原子条件挑选机型 |

服务基于官方 Python SDK `mcp` 2.x 的 `MCPServer`（即 1.x 中的 FastMCP，2.x 改了名字）。

同时，参数契约改为只维护一份：用 pydantic 模型定义。`MCPServer` 根据这份定义生成工具 schema，并在调用时按它校验；REST 接口也用同一份模型校验。手写的工具 JSON 和两个 DRF Serializer 都删除。

**不做**：

- 回答生成：仍由上层完成，检索系统不调用对话模型。
- 结果压缩或截断：长度由 persona 的 `tools_result_max_chars` 控制。
- 其他 MCP 能力：不提供 MCP prompts、resources，也不做 OAuth。persona 只消费工具，这些都用不上。
- 其余 Serializer：导入接口和规格文件用的 Serializer（`SourceImportSerializer`、`ProductSpecSerializer` 等）不动，`TextField`、`GpuField`、`FiniteFloatField` 继续供它们使用。

## 2. 结构

```text
persona ── Streamable HTTP（Authorization: Token <key>）──→ mcp 服务（uvicorn, :8001/mcp）
                                                             │ TokenAuthMiddleware → MCPServer
                                                             ↓
上层 HTTP 客户端 ──→ app 服务（gunicorn, :8000/api/v1/…） ──→ api/operations.py ──→ retrieval / products
                                                             ↑
                                                 contracts/ 中的 pydantic 模型（唯一参数定义）
```

| 模块 | 改动 |
| --- | --- |
| `contracts/requests.py`（新增） | 请求模型基类 `RequestModel`、文本校验函数、`empty_if_null`、`parse_model` |
| `contracts/query.py` | `FiltersSerializer`、`QuerySerializer` 换成 `Filters`、`QueryInput` |
| `contracts/products.py` | `ConditionsSerializer`、`RecommendSerializer` 换成 `Conditions`、`RecommendInput`；删除 `_known_options`；新增 `GPUS`、`BRANDS`；`PANELS`、`PORTS` 改为元组 |
| `products/selectors.py` | 删除。其中唯一的 `condition_options` 只用于按可见机型校验可选值，不再需要（3.3） |
| `api/operations.py`（新增） | 检索、推荐的装配代码，REST 和 MCP 共用 |
| `api/views.py` | `SearchView`、`ProductRecommendView` 改用 `parse_model` 和 `api/operations.py`；`validated` 只剩导入接口使用 |
| `mcp_server/`（新增） | `server.py`（`MCPServer` 实例与两个工具）、`auth.py`（Token 认证中间件）、`asgi.py`（ASGI 入口） |
| `eval/recommend_eval.py`、`eval/llm_eval.py` | 推荐评测改用新模型；工具定义改为从 MCP 服务读取 |
| `products/tool-definitions.md` | 删除第 2、3 节的 JSON，保留提示词、结果说明和示例 |

依赖方向不变：`mcp_server` 和 `api` 都依赖 `contracts` 与 `api/operations.py`，业务模块不依赖 `mcp_server`。服务层（`retrieval.service.search`、`products.service.recommend`）仍接收 dict，不修改。

## 3. 参数契约

### 3.1 定义方式

约束、说明和枚举写在 `Annotated` 类型别名和嵌套模型里，只写一次。REST 用的顶层模型（`QueryInput`、`RecommendInput`）和 MCP 工具函数的参数都引用这些别名。

**可选字段与 `null`**：

- 所有请求模型继承 `RequestModel`。它拒绝未知字段，并在校验前去掉值为 `null` 的键，所以显式 `null` 等同于不传。
- 可选标量写成 `Annotated[T, Field(...)] = None`，不写成 `T | None`。pydantic 不校验默认值，不传时就是 `None`。
- `filters`、`conditions` 用 `BeforeValidator(empty_if_null)` 加 `Field(default_factory=...)`。不传和传 `null` 得到的都是空模型。MCP 工具函数的这两个参数也因此能接受 `null`。

不用联合类型（包括 `T | SkipJsonSchema[None]`），原因是校验失败时报错会变乱。用 pydantic 2.14 实测：每个出错字段会多报一条 `Input should be None`，路径里还带 `function-after[…]`、`constrained-float` 等内部标记。上层 LLM 和 REST 调用方都会看到这些报错。

`contracts/requests.py`：

```python
class RequestModel(BaseModel):
    """检索、推荐请求的基类：拒绝未知字段，显式 null 等同于不传。"""
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def drop_nulls(cls, data):
        return {key: value for key, value in data.items() if value is not None} if isinstance(data, dict) else data


def strip_text(value):
    """同 DRF CharField：拒绝空字节，去掉首尾空白。"""


def require_text(value):
    """同 TextField：另外要求能编码为 UTF-8，且去掉首尾空白后非空。"""


def empty_if_null(value):
    return {} if value is None else value


def parse_model(model, data):
    """校验 REST 请求体；失败时转成 DRF ValidationError，由 DRF 默认处理器返回 400。见 3.4。"""
```

中文报错统一用 `PydanticCustomError(类型, 消息)` 抛出。直接 `raise ValueError` 的话，消息前会多出 `Value error, `。

`contracts/query.py`：

```python
QueryText = Annotated[str, Field(max_length=2000, description="检索问题，保留机型名和关键术语，例如“来酷 GT16 内存插槽”。"),
                      AfterValidator(require_text)]
SearchTopK = Annotated[int, Field(ge=1, le=20, description="返回的段落数。")]


class Filters(RequestModel):
    source_ids: Annotated[list[UUID], Field(min_length=1, max_length=50, description="只在这些来源中检索；…")] = None


FiltersArg = Annotated[Filters, BeforeValidator(empty_if_null),
                       Field(default_factory=Filters, description="检索范围；省略表示不限来源。")]


class QueryInput(RequestModel):
    query: QueryText
    filters: FiltersArg
    top_k: SearchTopK = 5
```

`contracts/products.py`：

```python
PANELS = ("oled", "lcd", "miniled")
PORTS = ("usb_a", "usb_c", "video_out", "hdmi", "rj45", "card_reader", "thunderbolt", "oculink")
GPUS = ("RTX 3050", "RTX 5060", "RTX 5070", "RTX 5070Ti", "RTX 5080", "RTX 5090")  # 按档次由低到高，与提示词一致
BRANDS = ("ALIENWARE", "LG", "ROG", ...)  # 规格文件中的全部品牌，共 20 个，单测检查


def normalize_gpu_input(value):
    return normalize_gpu(value) if isinstance(value, str) else value  # 非字符串交给 Literal 报类型错误


Gpu = Annotated[Literal[GPUS], BeforeValidator(normalize_gpu_input)]  # rtx5070 ti → RTX 5070Ti
Amount = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Preference = Annotated[str, Field(max_length=500, description="…"), AfterValidator(strip_text)]
RecommendTopK = Annotated[int, Field(ge=1, le=20, description="…")]


class Conditions(RequestModel):
    """只接受原子条件（方案 6.1 节）；“轻薄”“预算左右”等派生概念由上层换算。"""
    price_min: Annotated[Amount, Field(description="价格下限（元）。价格是评测时的价格，不是实时价格。")] = None
    price_max: Annotated[Amount, Field(description="…")] = None
    weight_max: Annotated[Amount, Field(description="…")] = None
    screen_min: Annotated[Amount, Field(description="…")] = None
    screen_max: Annotated[Amount, Field(description="…")] = None
    battery_min: Annotated[Amount, Field(description="…")] = None
    gpu_in: Annotated[list[Gpu], Field(min_length=1, max_length=20, description="…")] = None
    has_dgpu: Annotated[bool, Field(description="…")] = None
    is_gaming: Annotated[bool, Field(description="…")] = None
    panel: Annotated[Literal[PANELS], Field(description="屏幕面板类型。")] = None
    ports: Annotated[list[Literal[PORTS]], Field(min_length=1, max_length=len(PORTS), description="…")] = None
    brands: Annotated[list[Literal[BRANDS]], Field(min_length=1, max_length=20, description="…")] = None

    @model_validator(mode="after")
    def check_ranges(self):
        for low, high in [("price_min", "price_max"), ("screen_min", "screen_max")]:
            ...  # 下限大于上限时 raise PydanticCustomError("range", "{low} 不能大于 {high}", {...})
        return self


ConditionsArg = Annotated[Conditions, BeforeValidator(empty_if_null),
                          Field(default_factory=Conditions, description="硬条件，全部满足才入选；省略表示不过滤。")]


class RecommendInput(RequestModel):
    conditions: ConditionsArg
    preference: Preference = ""
    top_k: RecommendTopK = 5
```

- 字段与现有 `ConditionsSerializer` 一一对应，单测检查它们与 [conditions.py](../../products/conditions.py) 的 `CONDITIONS` 一致。
- 字段和工具的说明文字从现有 [tool-definitions.md](../../products/tool-definitions.md) 第 2、3 节原样搬过来。
- `PANELS`、`PORTS` 改为元组后，`ProductSpecSerializer` 的 `ChoiceField` 和 `dict.fromkeys(PORTS, …)` 照常可用。

### 3.2 与现有 Serializer 的对应

| Serializer 现有行为 | pydantic 写法 |
| --- | --- |
| `StrictSerializer` 拒绝未知字段 | `RequestModel` 的 `extra="forbid"`；MCP 顶层除外，见 5.6 |
| `TextField` 拒绝空字节、非法 UTF-8 和空白文本，去掉首尾空白 | `AfterValidator(require_text)` |
| `CharField`（`preference`）拒绝空字节，去掉首尾空白 | `AfterValidator(strip_text)` |
| `FiniteFloatField` 拒绝 `nan`、`inf` | `allow_inf_nan=False` |
| `GpuField` 规范显卡写法 | `BeforeValidator(normalize_gpu_input)` |
| `ChoiceField(PANELS/PORTS)` | `Literal[...]` |
| 下限 ≤ 上限 | `model_validator(mode="after")` |
| `default=dict` / `default=""` / `default=5` | `default_factory` / 字段默认值 |
| 显式 `null` 报 400 | 等同于不传 |
| `validate_gpu_in` / `validate_brands` 按可见机型检查 | 不保留，只按静态枚举校验，见 3.3 |

`api/operations.py` 用 `model_dump(exclude_none=True)` 转成服务层现有的入参形状，例如 `{"conditions": {"gpu_in": ["RTX 5070"]}, "preference": "", "top_k": 5}`：

- `conditions` 只含传入的条件，没有条件时为 `{}`；
- `has_dgpu: false` 不是 `None`，会保留；
- `source_ids` 是 `UUID` 列表，与原来的 `UUIDField` 相同。

### 3.3 显卡与品牌的可选值

`gpu_in`、`brands` 只按静态枚举校验，参数校验完全由 schema 完成：

- `GPUS`、`BRANDS` 写在 `contracts/products.py`，生成 schema 时成为 `enum`，MCP 和 REST 都按它校验。
- 规格文件新增型号或品牌后要改这两个常量，单测检查常量与 [bibar.json](../../products/specs/bibar.json) 是否一致。这取代原来 tool-definitions.md 3.1 节"用 jq 生成后手工更新 JSON"的做法。

原来还会按调用者能看到的机型收窄可选值，这一步现在去掉。原因是：

- SDK 校验参数时拿不到调用者，要保留就得在 schema 之外再检查一次；
- 现有来源清单（[itxia.toml](../../sources/yuque/manifests/itxia.toml)、[bibar.toml](../../sources/wechat/manifests/bibar.toml)）全部是 `public`，规格库中没有内部机型，收窄实际上不起作用。

去掉之后，可见范围仍然决定推荐的候选机型，内部资料不会泄露。行为变化如下：

- 只读账号选了只有内部机型才有的品牌，返回 `no_result`，而不是 400；
- 显卡或品牌在常量里、但库中已没有对应机型，同样返回 `no_result`。

上层 LLM 按提示词查看 `diagnostics` 放宽条件即可。

### 3.4 校验报错

**REST**：`parse_model(model, data)` 调用 `model.model_validate(data)`，把 pydantic 的 `ValidationError` 转成 DRF 的 `ValidationError`：

- 键是用点号连接的出错路径，列表元素带下标；整个请求体出错时（如请求体不是对象）用 DRF 惯用的 `non_field_errors`；
- 值是该路径下的报错列表，取 pydantic 的 `msg`。

```json
{"conditions.price_max": ["Input should be greater than or equal to 0"],
 "conditions.brands.0": ["Input should be 'ALIENWARE', 'LG', … or '雷蛇'"]}
{"conditions": ["price_min 不能大于 price_max"]}
```

转成 DRF `ValidationError` 后仍由 DRF 默认处理器返回 400，与导入接口一致。

**MCP**：参数校验由 SDK 完成，失败时返回 `isError: true`，正文是 pydantic 的报错，例如：

```text
Error executing tool search_knowledge: 1 validation error for search_knowledgeArguments
top_k
  Input should be less than or equal to 20 [type=less_than_equal, input_value=50, input_type=int]
    For further information visit https://errors.pydantic.dev/2.14/v/less_than_equal
```

### 3.5 生成的 schema 与原手写版的差异

以下差异以 mcp 2.3.0 实际生成的结果为准。约束本身（长度、范围、枚举、`uuid` 格式）不变，变化在结构上：

| | 原手写版 | 生成版 |
| --- | --- | --- |
| 嵌套对象 `filters`、`conditions` | 写在 `properties` 内 | 放进 `$defs`，用 `$ref` 引用，旁边带 `description` |
| 可选字段 | 不写进 `required` | 不写进 `required`；标量另加 `"default": null`，类型中没有 `null` 分支 |
| `title` | 没有 | 每个字段都有，如 `"Top K"`；顶层是 `search_knowledgeArguments` |
| 顶层多余参数 | `additionalProperties: false` | 不声明；嵌套模型有 `additionalProperties: false` |
| 篇幅 | 紧凑 | 更长 |

结构变了，原来的评测基线不能直接沿用，需要重跑评测（第 6 节）。

## 4. REST 接口

`api/operations.py` 收拢 [views.py:43-62](../../api/views.py) 中的装配代码，REST 和 MCP 共用：

```python
def run_search(args: QueryInput, user):
    embedder = components.embedding_provider()
    return search(args.model_dump(exclude_none=True), visible_scopes(user),
                  collector=components.recall_collector(embedder), pipeline=components.post_recall_pipeline(),
                  reader=components.context_reader(), embedding_space=embedder.space_id,
                  candidate_limit=settings.RETRIEVAL_CANDIDATE_LIMIT)


def run_recommend(args: RecommendInput, user):
    embedder = components.embedding_provider()
    return recommend(args.model_dump(exclude_none=True), visible_scopes(user),
                     collector=components.recall_collector(embedder), pipeline=components.post_recall_pipeline(),
                     embedding_space=embedder.space_id, candidate_limit=settings.RETRIEVAL_CANDIDATE_LIMIT)
```

View 只负责解析请求：

```python
class SearchView(APIView):
    def post(self, request):
        return Response(run_search(parse_model(QueryInput, request.data), request.user))
```

**REST 接口的行为变化**：

| 项 | 变化前 | 变化后 |
| --- | --- | --- |
| 400 正文 | DRF 嵌套字段，如 `{"conditions": {"price_max": ["…"]}}`，中文 | 点号路径，如 `{"conditions.price_max": ["…"]}`；类型、范围、枚举错误为英文，文本和下限大于上限的错误仍为中文 |
| `gpu_in`、`brands` 的可选值 | 按调用者可见的机型校验，不在其中的报 400"未知…；可选：…" | 只按静态枚举校验：不在枚举中的由 pydantic 拒绝，并列出全部枚举值；在枚举中但没有可见机型的返回 `no_result` |
| 显式传 `null` | 400 | 等同于不传 |
| 200 响应、401、403、领域错误、500 | — | 不变 |

## 5. MCP 服务

### 5.1 实例

`mcp_server/server.py`：

```python
mcp = MCPServer("itxia-kb")


def http_app():
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,           # 不保存会话，每个 POST 独立
        json_response=True,            # 返回 JSON，不用 SSE
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[*settings.ALLOWED_HOSTS, *(f"{host}:*" for host in settings.ALLOWED_HOSTS)],
        ),
    )
```

**主机校验**：

- `transport_security` 必须显式传入。`streamable_http_app` 的默认 host 是 `127.0.0.1`，这时 SDK 会自动开启 DNS 重绑定防护，只放行 `127.0.0.1`、`localhost`、`[::1]`，Host 不符时返回 421。
- persona 如果用 compose 服务名或内网地址访问会被拒绝，因此改为沿用 Django 的 `ALLOWED_HOSTS`。
- SDK 只支持精确主机名和 `主机:*`，不认 Django 的 `*`、`.example.com` 写法。部署时 `ALLOWED_HOSTS` 要写具体主机名，现有默认值 `127.0.0.1,localhost` 满足要求。

**lifespan**：`streamable_http_app` 返回的 Starlette 应用在 lifespan 中启动会话管理器，没有启动时请求会报 `Task group is not initialized`。还有两点：

- 每次调用 `http_app()` 都会新建一个会话管理器，而同一个管理器的 `run()` 只能调用一次。
- 生产环境由 uvicorn 触发 lifespan，`asgi.py` 只调用一次 `http_app()`。测试中每个用例各调用一次 `http_app()`，再执行 `async with mcp.session_manager.run()`（见第 8 节）。

**协议版本**：由 SDK 协商，服务端不写死版本。依赖为 `mcp>=2.3,<3`，支持的版本如下：

| 版本 | 方式 | 说明 |
| --- | --- | --- |
| `2024-11-05`、`2025-03-26`、`2025-06-18`、`2025-11-25` | `initialize` 握手 | 客户端请求的版本受支持时原样返回，否则返回 `2025-11-25`。persona 现在固定用 `2025-11-25` |
| `2026-07-28` | 每个请求独立，不握手、不使用会话 | persona 以后升级到最新协议时，服务端不需要修改 |

已用 2.3.0 实测过：

- `2025-11-25` 和 `2025-06-18` 的握手、`tools/list` 和 `tools/call`。
- 用 persona 自己的 Go 客户端（`mcp.go`）连接 2.3.0 的无状态 JSON 服务端，完整走了一遍：
  - 初始化通过了它的版本检查和 `tools` 能力检查；
  - 两个工具通过了名称与 schema 检查；
  - 成功、参数错误和 `ToolError` 的结果都能正确转换；
  - 未带 Token 时得到 401。

`2026-07-28` 只根据 SDK 源码确认，没有实测，由集成测试覆盖。

### 5.2 工具函数

```python
@mcp.tool(description=SEARCH_DESCRIPTION, structured_output=False)
async def search_knowledge(query: QueryText, filters: FiltersArg, top_k: SearchTopK = 5,
                           ctx: Context = None) -> str:
    return await call_tool(run_search, QueryInput(query=query, filters=filters, top_k=top_k), ctx)


@mcp.tool(description=RECOMMEND_DESCRIPTION, structured_output=False)
async def recommend_laptops(conditions: ConditionsArg, preference: Preference = "",
                            top_k: RecommendTopK = 5, ctx: Context = None) -> str:
    return await call_tool(run_recommend, RecommendInput(conditions=conditions, preference=preference, top_k=top_k), ctx)
```

- **工具描述**：`SEARCH_DESCRIPTION`、`RECOMMEND_DESCRIPTION` 从 tool-definitions.md 原样搬到 `mcp_server/server.py`。函数名就是工具名。
- **可选参数**：`filters`、`conditions` 的默认值来自 `Field(default_factory=…)`，因此函数签名中不写 `= None`。SDK 生成 schema 时不把它们列入 `required`（2.3.0 实测）。
- **`ctx`**：由 SDK 注入，不会出现在 schema 中。
- **两份参数列表**：工具函数的参数和 `QueryInput`、`RecommendInput` 的字段各列一次，但用的是同一组类型别名，约束和说明仍然只有一份。单测检查两者生成的 `properties` 与 `required` 完全相同，防止只改了一边。
- **`structured_output=False`**：返回值只作为文本块返回。否则 `-> str` 会让 SDK 再生成一个 `{"result": ...}` 的 `structuredContent`，同样的内容会传两遍。

### 5.3 线程与数据库连接

SDK 会在事件循环里直接调用同步工具函数，不会放进线程池。所以工具函数写成 `async`，Django ORM 和 Embedding 调用通过 `anyio.to_thread.run_sync` 放进工作线程，并在执行前后调用 `close_old_connections()`：

```python
def in_worker(operation, args, user):
    close_old_connections()
    try:
        return operation(args, user)
    finally:
        close_old_connections()
```

不用 `sync_to_async`：它默认 `thread_sensitive=True`，所有调用都会排到同一个线程里串行执行。

### 5.4 错误与返回值

SDK 对 `ToolError` 会把异常信息返回给客户端。对其他异常，它只返回 `Error executing tool <名称>`，不带异常信息，并在服务端记录日志。参数校验已由 SDK 完成，因此 `call_tool` 只需要把 `DomainError` 转成 `ToolError`，其他异常交给 SDK：

```python
def current_user(ctx):
    return ctx.request_context.request.scope["user"]  # 由 TokenAuthMiddleware 写入


async def call_tool(operation, args, ctx):
    try:
        result = await anyio.to_thread.run_sync(in_worker, operation, args, current_user(ctx))
    except DomainError as error:
        raise ToolError(json.dumps({"error": {"code": error.code, "message": error.message}}, ensure_ascii=False)) from None
    return json.dumps(result, cls=JSONEncoder, ensure_ascii=False)
```

| 异常 | 返回给 persona（`isError: true`） |
| --- | --- |
| 参数校验失败 | SDK 返回 pydantic 报错，见 3.4 |
| `DomainError`（Embedding 未配置或不可用等） | `{"error": {"code", "message"}}`，与 REST 一致 |
| 其他异常 | `Error executing tool <名称>`，不带内部信息 |

成功时用 DRF 的 `JSONEncoder` 序列化后作为文本返回。这样日期、UUID 的格式和 REST 一致，结果字段也和 REST 完全相同。

`current_user` 单独成函数，是因为 SDK 的进程内测试客户端不经过 HTTP，`ctx.request_context.request` 为 `None`（2.3.0 实测）。单测替换这个函数即可。

### 5.5 认证

`mcp_server/auth.py` 的 ASGI 中间件 `TokenAuthMiddleware` 包在 `http_app()` 外面：

- 读取 `Authorization: Token <key>`，也接受 `Bearer <key>`；
- 在工作线程中调用 DRF 的 `TokenAuthentication().authenticate_credentials(key)`，前后同样调用 `close_old_connections()`。它与 REST 共用 Token 表，并检查账号是否停用；
- 失败时直接返回 401 `{"error": {"code": "NOT_AUTHENTICATED", "message": "认证失败"}}`；
- 成功时写入 `scope["user"]`；
- `lifespan` 请求直接放行，不做认证。SDK 在 lifespan 里启动会话管理器，拦下它服务就起不来。

工具函数通过 `current_user(ctx)` 取到用户，再由 `visible_scopes` 决定能看到的范围，规则与 REST 相同。

### 5.6 与 REST 的行为差异

两处差异都来自 SDK 根据函数签名生成的参数模型。这个模型不继承 `RequestModel`，接受这两处差异，不为它们覆盖 SDK 的内部校验：

| 情形 | REST | MCP |
| --- | --- | --- |
| 顶层未知参数，如把 `price_max` 平铺在顶层 | 400 | 静默丢弃，按"没有条件"推荐（2.3.0 实测）；生成的 schema 顶层也不声明 `additionalProperties: false` |
| 顶层 `top_k`、`preference` 传 `null` | 等同于不传 | 报类型错误 |

嵌套对象 `filters`、`conditions` 里的未知字段和 `null` 两边处理一致。persona 把 schema 原样交给 LLM，模型按 schema 嵌套传参即可。重跑评测时 `recommend_with` 仍会统计平铺参数的次数（它按 REST 规则报"未知字段"），出现较多时再处理。

### 5.7 运行

`mcp_server/asgi.py`：

```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from mcp_server.auth import TokenAuthMiddleware  # noqa: E402  需在 django.setup() 之后导入
from mcp_server.server import http_app  # noqa: E402

app = TokenAuthMiddleware(http_app())
```

用 `uvicorn mcp_server.asgi:app --host 0.0.0.0 --port 8001` 启动，端点为 `http://<host>:8001/mcp`。uvicorn 是 mcp 的依赖，不需要单独添加。

## 6. 评测与工具定义文档

| 项 | 改动 |
| --- | --- |
| [recommend_eval.py](../../eval/recommend_eval.py) `Recommender` | `keys` 改用 `parse_model(RecommendInput, …)` 和 `model_dump(exclude_none=True)`，删除 `self.options` 和对 `condition_options` 的导入。报错仍是 DRF `ValidationError`，`llm_eval.recommend_with` 的异常处理不变 |
| [llm_eval.py](../../eval/llm_eval.py) `load_tools` | 提示词仍取自 tool-definitions.md 的 `text` 代码块；工具定义改为 `asyncio.run(mcp.list_tools())`，转成 `{"type": "function", "function": {"name", "description", "parameters": tool.input_schema}}`。2.x 的 `Tool` 字段名是 `input_schema`，序列化成 JSON 时才是 `inputSchema`。`tools_sha256` 照常记录 |
| [tool-definitions.md](../../products/tool-definitions.md) | 见下文 |
| 重跑评测 | 用与上次相同的模型（deepseek-flash）重跑 `llm_eval`，结果写入[实施记录](product-spec-log.md)新的一节。对照基线是第 4 节的 llm-v2（查询集 v19），验收线见第 10 节阶段 3 |

tool-definitions.md 的改动：

- 删除第 2、3 节的 JSON，改为说明工具定义由 MCP 服务生成，附上下面的打印命令。
- 3.1 节可选值改为"更新 `contracts/products.py` 的 `GPUS`、`BRANDS`"。删除"按调用者可见的机型校验可选值"一段，改为说明不可见或已无机型的值返回 `no_result`。
- 开头关于 OpenAI、Anthropic 格式和 strict 模式的说明改为 MCP 接入说明。
- 第 1 节提示词、第 4 节结果说明、第 5 节示例保留。

打印工具定义的命令：

```sh
python manage.py shell -c "import asyncio, json; from mcp_server.server import mcp; \
print(json.dumps([t.model_dump(by_alias=True, include={'name', 'description', 'input_schema'}) for t in asyncio.run(mcp.list_tools())], ensure_ascii=False, indent=2))"
```

## 7. 部署与 persona 配置

### 7.1 itxiaRAG

| 文件 | 改动 |
| --- | --- |
| [requirements.in](../../requirements.in) | 增加 `pydantic>=2.12,<3`（`contracts` 直接依赖；mcp 2.3 要求不低于 2.12）和 `mcp>=2.3,<3` |
| `requirements.txt`、`requirements-dev.txt` | 按文件头注释中的 `uv pip compile` 命令重新生成。首次引入新包时要去掉 `--offline` |
| `pyproject.toml`、`uv.lock` | `dependencies` 同步加上这两项，执行 `uv lock` |
| [compose.yaml](../../compose.yaml) | app 的环境变量提取为 YAML 锚点 `x-app-env`；新增 `mcp` 服务：同一镜像，依赖 db，执行 `uvicorn mcp_server.asgi:app --host 0.0.0.0 --port 8001`，端口为 `${MCP_BIND_ADDRESS:-127.0.0.1}:${MCP_PORT:-8001}:8001`。数据库迁移仍由 app 执行 |
| [.dockerignore](../../.dockerignore) | 白名单增加 `!mcp_server/` |
| [Makefile](../../Makefile) | 增加 `run-mcp`：`$(PYTHON) -m uvicorn mcp_server.asgi:app --host 127.0.0.1 --port 8001` |

mcp 2.3 依赖 `httpx2`（不是 `httpx`）、starlette、uvicorn、anyio 等，集成测试直接使用其中的 `httpx2`，不新增开发依赖。

persona 部署在其他主机或容器时，要相应调整 `MCP_BIND_ADDRESS`，并把 persona 访问时用的主机名加进 `ALLOWED_HOSTS`。

### 7.2 账号

按[部署文档 3.1 节](../deployment.md#31-创建维护者和普通调用账号)为 persona 单独建一个只读账号（`--permissions ''`），不给 `read_internal`。Token 文件放在被忽略的 `.runtime/`，不写进日志，也不提交：

```sh
dc exec app python manage.py kb_account --username persona --permissions '' --token-file /tmp/persona.token
```

### 7.3 persona

persona 的配置文件含 Token，不提交。`mcp_extra_headers` 是 map，不能用环境变量覆盖，只能写在配置文件里：

```yaml
plugins:
  persona:
    mcp_url: http://127.0.0.1:8001/mcp
    mcp_extra_headers:
      Authorization: "Token <persona 账号的 Token>"
    tools_call_timeout: 15s        # 推荐带 preference 时要调用 Embedding，默认 8s 偏紧
    tools_result_max_chars: 12000  # 检索结果包含完整父段，按需调整
    personas:
      itxia:
        prompt: <tool-definitions.md 第 1 节，工具名改为 mcp__search_knowledge、mcp__recommend_laptops>
        tools: [mcp__search_knowledge, mcp__recommend_laptops]
```

persona 会给工具名加上 `mcp__` 前缀，所以提示词中的工具名要相应修改。服务端改了工具后，在 persona 中执行 `/persona tools reload` 刷新工具目录。

## 8. 测试

**单测**不访问数据库、网络和模型：

- MCP 工具用 SDK 的进程内客户端 `mcp.Client(mcp_server.server.mcp)` 调用，并替换 `mcp_server.server` 中的 `current_user`、`run_search`、`run_recommend`。
- `in_worker` 中的 `close_old_connections()` 不会打开连接，单测里可以照常执行。
- 认证中间件直接以 ASGI 方式调用，替换 `TokenAuthentication.authenticate_credentials`。

**集成测试**：

- 用 `httpx2.ASGITransport` 访问 `TokenAuthMiddleware(http_app())`，每个用例新建应用，并在 `async with mcp.session_manager.run()` 中发请求。
- 工具和认证在工作线程中使用各自的数据库连接，看不到普通 `django_db` 用例中未提交的数据，所以 MCP 集成测试用 `pytest.mark.django_db(transaction=True)`。
- 用例本身写成同步函数，在里面调用 `anyio.run(...)`，不引入异步测试插件。

| 测试 | 内容 |
| --- | --- |
| [test_products.py](../../tests/unit/test_products.py) 单测（修改） | 推荐请求改用 `RecommendInput`：默认值为 `{"conditions": {}, "preference": "", "top_k": 5}`；显卡规范化；显式 `null` 等同于不传；非法值（未知条件、下限大于上限、未知接口、空 `gpu_in`、`nan`、`top_k` 超限、顶层未知字段、不在枚举中的显卡和品牌）被拒绝。`GPUS` 与规格文件的显卡集合相同，`" < ".join(GPUS)` 出现在提示词中；`BRANDS` 与规格文件的品牌集合相同。阶段 1 中 md 的 JSON 字段改为对照 pydantic 模型，阶段 3 删除 JSON 后去掉这部分对照 |
| [test_contracts.py](../../tests/unit/test_contracts.py)、[test_product_conditions.py](../../tests/unit/test_product_conditions.py) 单测（修改） | `filters` 中的已删除字段（`knowledge_types`）被 `QueryInput` 拒绝；`Conditions.model_fields` 与 `CONDITIONS` 一致 |
| `test_requests.py` 单测（新增） | `parse_model` 的报错键：嵌套路径、列表下标、`non_field_errors`；`require_text`、`strip_text` 与原 `TextField`、`CharField` 行为一致（空字节、空白、去首尾空白） |
| `test_mcp_server.py` 单测（新增） | 工具名、描述以及顶层参数与 `QueryInput`、`RecommendInput` 生成的 `properties`、`required` 一致；schema 中没有 `null` 分支；参数校验失败、`DomainError` 和意外异常都转成 `isError`，`DomainError` 的正文与 REST 相同，意外异常的正文不含异常信息；成功结果为 JSON 文本，没有 `structuredContent`；认证中间件对缺少、格式错误和无效的 Token 返回 401，接受 `Token` 与 `Bearer` 两种写法，并放行 lifespan |
| [test_rag.py](../../tests/integration/test_rag.py)、[test_product_recommend.py](../../tests/integration/test_product_recommend.py) 集成测试（修改） | `query` 辅助函数改用 `QueryInput`；400 断言按新格式调整；"普通账号不能选内部机型的品牌"改为：普通账号选雷蛇返回 200 和 `no_result`，带 `read_internal` 的账号能推荐到"雷蛇 内部样机"；不在枚举中的 `RTX 4090` 仍返回 400，且报错列出 `RTX 5070` |
| `test_mcp_integration.py` 集成测试（新增） | 用 `2025-11-25` 走 `initialize` → `tools/list` → 两个工具的 `tools/call`，结果与同参数的 REST 响应相同；用 `2026-07-28` 不握手直接调用 `tools/list`；只读账号检索不到 `internal` 来源，带 `read_internal` 的账号可以；未带 Token 返回 401；Host 不在 `ALLOWED_HOSTS` 中时返回 421 |

回归命令：`make test`。另外按第 6 节重跑 `recommend_eval` 和 `llm_eval`。

## 9. 文档同步

| 文档 | 内容 | 阶段 |
| --- | --- | --- |
| [首期技术设计第 6 节](../phase1/phase1-technical-design.md#6-api-与错误) | 校验依据改为 pydantic 模型；400 的正文格式；`gpu_in`、`brands` 改为按静态枚举校验，没有可见机型的值返回 `no_result`；显式 `null` 等同于不传 | 1 |
| [工具定义](../../products/tool-definitions.md) 3.1 节 | 可选值的维护方式与 `no_result` 说明 | 1 |
| [工具定义](../../products/tool-definitions.md) 其余部分 | 见第 6 节 | 3 |
| [首期技术设计第 6 节](../phase1/phase1-technical-design.md#6-api-与错误) | 增加 MCP 入口一行 | 2 |
| [部署文档](../deployment.md) | `mcp` 服务的启动与冒烟检查：未带 Token 返回 401，带 Token 能 `initialize` | 2 |
| [机型规格库方案](product-spec-design.md)、[第三阶段需求](requirements.md) | P3 的接入方式改为 MCP，并链接本文；本文状态改为已实施 | 3 |
| [README](../../README.md) | 文档导航增加本文；补充 MCP 运行方式 | 2 |
| [AGENTS.md](../../AGENTS.md) | 项目结构增加 `mcp_server/`；`contracts/` 的描述改为"pydantic 模型与 Serializer" | 2 |

## 10. 分阶段实施与验收

每个阶段单独提交，提交前 `make test` 全部通过。阶段 1、2 不改工具的提示词和说明文字，评测结果只受 schema 结构影响，留到阶段 3 统一重跑。

### 阶段 1：参数模型与 REST 改造

**改动**：

- 依赖增加 `pydantic`；
- `contracts/requests.py`、`contracts/query.py`、`contracts/products.py` 按第 3 节修改；
- 新增 `api/operations.py`，修改 `api/views.py`；
- 删除 `products/selectors.py`；
- `eval/recommend_eval.py` 改用新模型。它导入了被删除的 Serializer 和 `condition_options`，必须同一阶段修改；
- 第 8 节中除 MCP 外的测试；
- 第 9 节标为阶段 1 的文档。

**验收**：

1. `make test` 全部通过，第 8 节阶段 1 涉及的测试均已按表中内容修改或新增。
2. 在 `api/`、`contracts/`、`products/`、`eval/`、`tests/` 中搜索 `QuerySerializer`、`FiltersSerializer`、`RecommendSerializer`、`ConditionsSerializer`、`condition_options`、`_known_options`，没有结果。
3. 集成测试中的 REST 行为符合第 4 节变化表：
   - `{"conditions": {"price_min": 9000, "price_max": 8000}}` 返回 400 `{"conditions": ["price_min 不能大于 price_max"]}`；
   - `{"conditions": null, "top_k": null}` 与 `{}` 结果相同；
   - 普通账号选雷蛇返回 200 和 `no_result`；
   - `RTX 4090` 返回 400。
4. 原有 200 响应的断言（字段结构、排序、`diagnostics`、`unknown`）不修改也能通过。
5. 用正式库运行 `recommend_eval`，结果与 recommend-v3 相同：链路集合 18/18 相同，P@5 1.000，nDCG@5 0.915；软条件排序 0.257／0.612；结论附带 78/78。这一步不调用对话模型。

**提交**：`refactor(contracts): 检索与推荐请求改用 pydantic 模型`

### 阶段 2：MCP 服务

**改动**：

- 依赖增加 `mcp`；
- 新增 `mcp_server/` 的三个模块；
- 修改 compose、`.dockerignore`、Makefile；
- 新增 `test_mcp_server.py`、`test_mcp_integration.py`；
- 第 9 节标为阶段 2 的文档。

**验收**：

1. `make test` 全部通过，两个新测试文件覆盖第 8 节表中列出的全部情形。
2. 第 6 节的打印命令输出两个工具；`inputSchema` 中没有 `"null"`；顶层参数分别是 `query`、`filters`、`top_k` 和 `conditions`、`preference`、`top_k`，`required` 只有 `query`。
3. 本机执行 `make run-mcp` 后：
   - 未带 Token 的 POST 返回 401；
   - 带只读账号 Token、请求版本 `2025-11-25` 的 `initialize` 返回 200，`protocolVersion` 为 `2025-11-25`；
   - 随后的 `tools/list` 返回两个工具，`tools/call` 调用 `search_knowledge` 返回 JSON 文本结果。
4. `docker compose up -d mcp` 后，用同样的请求得到同样的结果。uvicorn 的访问日志中没有 Token。
5. REST 接口不受影响：阶段 1 的集成测试照常通过。

**提交**：`feat(mcp): 新增 MCP 服务提供知识检索与机型推荐工具`

### 阶段 3：评测与工具定义文档

**改动**：

- `llm_eval.load_tools` 改为从 MCP 服务读取；
- tool-definitions.md 按第 6 节修改；
- `test_products.py` 去掉对照 md JSON 的部分；
- 重跑 `llm_eval` 并写入实施记录；
- 第 9 节标为阶段 3 的文档。

**验收**：

1. `make test` 全部通过；tool-definitions.md 中不再有 `json` 代码块，提示词仍是唯一的 `text` 代码块。
2. `llm_eval` 跑完 170 条查询和补充样例，结果写入实施记录，并附 `tools_sha256`、平铺参数的次数和逐条差异。
3. 与 llm-v2 相比：
   - 工具选择不低于 164/170；
   - 条件换算一致不低于 15/18；
   - D 类 19 条 P@5 不低于 0.95，nDCG@5 不低于 0.87；
   - 补充样例的工具选择不低于 10/11。

   达不到时按第 6 节修订字段说明后重跑，修订内容和前后结果都写入记录。允许小幅波动，是因为温度为 0 时模型输出仍会略有变化。
4. 平铺参数（5.6）的次数不超过 2 次；超过时在记录中写明，再决定是否处理。

**提交**：`docs(products): 工具定义改由 MCP 服务生成并重跑上层 LLM 评测`

### 阶段 4：persona 接入验证

**改动**：只改配置，不改代码。按第 7.2 节建账号，按第 7.3 节配置 persona，配置文件不提交。

**验收**：

1. `/persona tools` 中能看到 `mcp__search_knowledge` 和 `mcp__recommend_laptops`。
2. 在 itxia 人设下：
   - 问一个具体机型的配置问题，触发 `mcp__search_knowledge`，回答引用了检索结果；
   - 问一个带预算和用途的选购问题，触发 `mcp__recommend_laptops`，回答中的机型来自推荐结果。
3. 把 Token 改错后执行 `/persona tools reload`，persona 报告工具不可用或认证失败。改回后恢复正常。
4. `git status` 中没有 Token、persona 配置或 `.runtime/` 下的文件。
5. 结果写入实施记录。

预计生产代码新增约 300 行，删除约 80 行（两个 Serializer、`products/selectors.py` 和 md 中的 JSON）。

## 11. 风险

| 风险 | 应对 |
| --- | --- |
| 生成的 schema 让上层 LLM 的工具选择或条件换算变差 | 阶段 3 重跑评测，对照 llm-v2；不达标时先修订字段说明 |
| MCP 与 REST 的两处差异（5.6） | 已接受；评测中出现平铺参数时再评估 |
| mcp SDK 升级改变 schema 生成或握手方式 | 依赖锁定在 `<3`；单测断言 schema 的关键形状，集成测试断言协议版本 |
| REST 的 400 正文变化影响现有调用方 | 仓库内只有评测脚本和测试解析 400 正文，已在本方案中一并修改；有外部调用方时需提前通知 |
