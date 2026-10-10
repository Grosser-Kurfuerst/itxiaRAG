# 来源连接器改造方案

状态：已实现。语雀改为实现 SourceConnector，新增公众号本地采集目录连接器与 `import_wechat`，两者通过[通用契约测试](../../tests/unit/test_source_connectors.py)。当前资料准备与提交方式见[来源接入说明](source-ingestion-plan.md)，预处理契约见[文档预处理](preprocessing.md)，语雀现有实现见[语雀技术方案](yuque-ingestion/technical-design.md)。

## 1. 背景

改造前 [SourceConnector](../../contracts/types.py) 只有 `fetch(locator) → RawDocument` 协议，没有任何实现。语雀导入没有使用它，而是在 [sources/yuque](../../sources/yuque/) 中定义了自己的 `YuqueClient.list_docs / read_markdown`，原因是一次导入除了正文还需要：

| 导入需要 | 语雀现状 | `fetch(locator)` 能否表达 |
| --- | --- | --- |
| 有哪些文档、如何遍历 | `list_docs(book)` 返回 `YuqueDocRef` | 不能，调用方必须事先知道 locator |
| 稳定身份 `canonical_locator`、原文链接 | `build_request` 由 doc_id、book、slug 拼出 | 不能，RawDocument 不含 SourceSpec |
| 标题、来源日期、目录路径 | `YuqueDocRef` 与 `clean_title` | 只能放进 metadata，没有约定 |
| 可见性 | 清单 `visibility_for` | 不能，属于治理决策 |
| 类别与流水线 | 清单 `classify` + `CATEGORY_PIPELINES` | 不能，同上 |

另一方面，原 `YuqueImportService.run` 中清单判断、请求组装、校验提交和报告汇总都与语雀无关。改造目标是把这部分抽成通用流程，平台只实现读取。

## 2. 目标与边界

- 新平台只需实现一个 connector、一份清单和一个薄命令入口；清单代码、导入编排、报告和预处理链不改。
- connector 只回答“有哪些文档、原文和身份是什么”；“导不导、算哪类、谁能看”由清单决定。
- 线上读取与离线快照是同一协议的两种实现，测试和开发不依赖网络。
- 不做增量同步、删除同步、任务队列和非文档数据（如维修登记）接入；出现实际需求再扩展。

## 3. 组成

| 部分 | 职责 | 通用／各平台不同 | 位置 |
| --- | --- | --- | --- |
| 协议与 DTO：`SourceConnector`、`SourceRef`、`FetchedSource` | 规定 connector 的输出 | 通用 | [contracts/types.py](../../contracts/types.py) |
| Connector 实现 | 列出文档、读取原文、生成稳定身份与原文链接、清洗标题、整理平台元数据；声明本平台类别集合 | 各平台不同 | `sources/<平台>/`，如 [语雀](../../sources/yuque/connector.py) |
| 清单 Manifest | 导入范围、类别、可见性、逐篇元数据补丁 | 代码通用；每个平台一份 TOML | [sources/manifest.py](../../sources/manifest.py)，TOML 在 `sources/<平台>/manifests/` |
| 导入服务 SourceImportService | 清单分流、组装原文导入请求、校验提交、汇总报告 | 通用 | [sources/importing.py](../../sources/importing.py) |
| 错误约定 | 整批失败与单篇失败分级 | 通用约定，各 connector 按约定抛出 | [contracts/errors.py](../../contracts/errors.py) 与各 connector |
| 命令入口 | 解析参数（目录、清单等）、装配依赖、打印报告 | 基类 [SourceImportCommand](../../sources/commands.py) 负责清单、账号、试运行、提交与报告；平台命令只写参数与装配 | `sources/management/commands/` |
| 预处理链 | 格式解析 → 结构策略 → 增强 → 切分 → 校验 → 入库 | 通用，按 media_type 与 schema 选择 | `ingestion/`、[组合根](../../config/components.py) |
| 　方言解析器 | 平台特有的格式写法 | 可选，按平台提供（如 YuqueMarkdownParser） | `ingestion/` |
| 　结构策略 | 父段与子块组织 | 按内容类型区分，与平台无关 | `ingestion/` |

依赖方向保持不变：`sources` 依赖 `contracts` 与 `ingestion`，`ingestion`、`catalog`、`api` 不依赖 `sources`。

## 4. 协议与 DTO

```python
@dataclass(frozen=True)
class SourceRef:
    """列表阶段的轻量引用：不含正文，用于清单匹配、报告和读取。"""
    collection: str                         # 清单登记的集合：语雀知识库、公众号账号等
    key: str                                # 清单与报告用的可读键“集合/条目”，如 help/install_win10
    canonical_locator: str                  # 稳定身份，如 doc:55035323；改名不变
    title: str
    collection_path: tuple[str, ...] = ()   # 集合内的目录路径（不含集合本身），供清单路径规则匹配
    updated_at: datetime | None = None
    extra: dict = field(default_factory=dict)  # 平台私有字段


@dataclass(frozen=True)
class FetchedSource:
    ref: SourceRef
    raw: RawDocument
    source_url: str | None = None


class SourceConnector(Protocol):
    source_type: str
    def list(self) -> Iterable[SourceRef]: ...
    def fetch(self, ref: SourceRef) -> FetchedSource: ...
```

- **列出与读取分离**：清单匹配、跳过和 `--only` 过滤在读取正文前完成。
- **身份归 connector**：`canonical_locator` 与 `source_url` 的生成规则只有平台知道。身份必须在改名、重新采集后保持不变；取不到稳定标识时退回人工稳定键（如公众号的采集键），不能用会过期的链接。无法识别的标识应在列出阶段报错，不能静默降级，否则重新采集会产生无法删除的重复来源。
- **范围放构造参数**：`list()` 不带参数，读取范围（知识库、目录、账号）由构造参数传入，协议不随平台概念增加参数。
- **元数据约定**：`RawDocument.metadata` 的公共键为 `title`、`source_date`、`collection_path`；平台私有字段放在 `metadata[source_type]` 下（语雀现为 `metadata["yuque"]`）。导入服务在该命名空间中写入 `classified_by`，因此语雀请求与改造前完全一致，已导入文档的内容哈希不变。

## 5. 清单

由语雀清单泛化（`version = 2`）：

- 根表声明 `source_type`，载入时必须与命令一致；`[connector]` 表放平台参数（如语雀的 `group`、公众号的下载列表），由平台命令解释。
- 文档键使用 `ref.key`，`books` 改为 `collections`，路径规则用 `collection` 指定集合，按 `ref.collection_path` 最长前缀匹配，单篇条目优先。
- 允许的类别由各平台声明（如语雀的 `CATEGORIES`），已接入的流水线由组合根的 `<平台>_CATEGORY_PIPELINES` 决定；清单中已声明但未接入的类别仍报告 `skipped`（未接入）。
- 单篇条目可带 `metadata` 补丁，用于平台无法提供、预处理需要的字段，例如评测的 `entity_title`、`entity_headings`。补丁只能用于有 `category` 的条目，不能包含平台命名空间；来源身份和可见性不在 metadata 中，补丁无法覆盖。

```toml
version = 2
source_type = "wechat"

[collections."笔吧评测室"]
visibility = "public"

[docs."笔吧评测室/2026-09-28-laike-gt16"]
category = "product_review"
metadata = { entity_title = "联想 来酷GT 16 酷睿版" }

[docs."笔吧评测室/2026-09-30-reprint"]
skip = "reprint"                # 转载评测不收录
```

## 6. 导入服务与错误

`SourceImportService(connector, manifest, category_pipelines, submit)` 由现有 `YuqueImportService.run` 迁移而来，`ImportReport` 与 imported／reused／preprocessed／skipped／unregistered／failed 六种状态沿用。请求组装：

```python
fetched = connector.fetch(ref)
request = {
    "source": {
        "source_type": connector.source_type,
        "canonical_locator": ref.canonical_locator,
        "source_url": fetched.source_url,
        "visibility": manifest.visibility_for(ref),
    },
    "preprocess": {"schema": schema, "version": version},
    "raw": {
        "content": ..., "media_type": fetched.raw.media_type,
        "metadata": {**fetched.raw.metadata, **manifest.metadata_for(ref)},
    },
}
```

请求仍经 `RawSourceImportSerializer` 校验后提交，与原文 API 共用同一契约。

错误分两级，沿用语雀已有做法：

- `list()` 在导入服务开始前调用，其中任何错误（列表文件缺失、旁注非法等）都终止整批，不处理任何正文。
- `fetch()` 抛 `SourceAccessError`（凭据失效、无权限，如 `YuqueAuthenticationError`）时终止整批，命令转为 CommandError。
- `fetch()` 抛 `DomainError`（单篇读取或格式错误）时，该篇报告 `failed` 后继续。

## 7. 平台差异

| 维度 | 语雀 | 笔吧公众号 |
| --- | --- | --- |
| 获取方式 | 匿名读取公开网页或快照 | `fetch_wechat` 下载或人工采集的本地目录 `<dir>/<账号目录>/<条目>.html`，加同名 `.json` 旁注：`title`（必填）、`url`、`date`（YYYY-MM-DD）、`author`、`account`（显示名，缺省用目录名），不允许其他字段 |
| `list()` 范围 | 清单登记的知识库 | 清单登记的账号目录 |
| `canonical_locator` | `doc:<doc_id>` | 永久链接为 `mp:<__biz>:<mid>:<idx>`，短链接为 `mp:s:<id>`，两者不互通，采集应统一使用永久链接；旁注没有 `url` 时为 `wechat-capture:<账号目录>/<条目>`，此时采集文件不能改名。同一身份在本次列出的账号中出现两次时报错，要求人工去重 |
| `source_url` | `https://www.yuque.com/<group>/<book>/<slug>` | 规范化后的永久链接（只保留 `__biz`、`mid`、`idx`、`sn`，`&amp;` 转义会先还原）或短链接；带 `timestamp`／`signature` 的临时链接或其他无法识别的链接在列出阶段报错，需换成永久链接或删除 `url` |
| `media_type` | `text/x-yuque-markdown` | `text/html` |
| 方言解析器 | YuqueMarkdownParser（已有） | 视预处理质量决定是否增加微信 HTML 方言解析 |
| 平台元数据 | `metadata["yuque"]`：doc_id、book、slug 等 | `metadata["wechat"]`：账号、作者；发布日期写入公共键 `source_date` |
| 类别与流水线 | `tutorial` 等五类，已接入 `tutorial@1`、`knowledge@1`、`tool_card@1` | `product_review`、`purchase_guide`，分别接入 `product_review@1`、`purchase_guide@1` |
| 清单写法 | 目录规则为主，单篇覆盖为辅 | 逐篇登记为主：类别、`entity_title`、`entity_headings` |
| 凭据 | 无 | 无 |
| 实现 | [YuqueConnector](../../sources/yuque/connector.py)、[import_yuque](../../sources/management/commands/import_yuque.py) | [WechatCaptureConnector](../../sources/wechat/connector.py)、[import_wechat](../../sources/management/commands/import_wechat.py)；下载见 [fetch_wechat](../../sources/management/commands/fetch_wechat.py) |

笔吧推文的额外注意事项：

- **获取**：公众号官方接口只能读取自有账号，不能全量读取第三方账号，因此采用“下载或人工采集 + 离线导入”，没有在线同步。下载与导入共用清单，`[connector]` 写法如下；[fetch_wechat](../../sources/management/commands/fetch_wechat.py) 只写采集目录，不访问数据库，导入仍由 `import_wechat` 离线完成，因此临时链接过期、验证码中断都不影响重跑导入。

  ```toml
  [connector.accounts]
  bibar = "笔吧评测室"            # 集合 → 搜狗结果中的公众号名
  [connector.articles]            # 键须在 docs 中登记
  "bibar/2026-09-28-laiku-gt16" = { title = "未来已来！聊一款新上市的主流游戏本", date = "2026-09-28" }
  ```

  [搜狗客户端](../../sources/wechat/sogou.py)依赖非公开页面格式：搜索结果取标题、账号与发布时间，跳转页拼出临时链接，文章页取 `biz/mid/idx/ct/nickname` 并去掉 script、style。只有账号、标题与日期都一致才下载；搜狗不支持匿名按时间筛选，每期同名文章往往搜不到最新一期，需人工采集。验证码属于整批失败（`SourceAccessError`），未找到、多篇一致和页面改版属于单篇失败。
- **元数据**：类别（评测、选购指南、转载评测、不收录）和机型名无法从页面可靠推断，需要逐篇登记。
- **身份稳定**：入库后不要再更换链接形式或采集文件名，否则会生成新的来源，旧来源目前没有删除入口。重复采集在列出阶段拦截，因此清单的 `skip`／`canonical` 不用于公众号去重；分批或用 `--only` 跨账号导入时，跨账号重复无法拦截，后导入的会覆盖同身份来源。
- **内容质量属于 ingestion**：真实文章预处理测试发现，整句加粗被识别为标题导致散热条件与结果分离，接口子块混入噪音与价格，泛化图片说明（alt 为“图片”）没有警告。这些需在解析器和评测策略中改进，connector 不负责。

## 8. 迁移步骤

1. 在 `contracts/types.py` 定义新协议与 DTO，替换旧 `SourceConnector`，同步[首期技术设计](phase1-technical-design.md)与[来源接入说明](source-ingestion-plan.md)。
2. 将清单、导入服务、报告从 `sources/yuque` 迁到 `sources/` 公共模块；`books` 改名 `collections`，类别集合改为由各平台声明，并支持单篇 `metadata` 补丁。
3. 语雀改为实现 SourceConnector：`YuqueDocRef` 映射为 `SourceRef`（doc_id、book、slug 放 `extra`），`build_request` 中身份、链接、标题清洗和平台元数据移入 `fetch`；OpenAPI 与快照仍是两种实现，`--save-snapshot` 保留在语雀命令中。现有语雀单元与集成测试作为回归。
4. 新增笔吧本地目录 connector 与清单，命令入口只负责参数与装配。
5. 补充通用 connector 契约测试 [test_source_connectors.py](../../tests/unit/test_source_connectors.py)，新增平台在其中登记合成数据构造函数，所有实现必须通过：
   - `list()` 的 `key` 与 `canonical_locator` 不重复，重复调用结果稳定；
   - `fetch()` 结果组装的请求能通过 `RawSourceImportSerializer`；
   - metadata 含 `title`，`source_date` 格式合法；
   - 列表失败在 `list()` 中抛出；凭据失败抛 `SourceAccessError`，单篇失败抛 `DomainError`。

## 9. 实施顺序与待定事项

建议先用 3～5 篇获准的笔吧原文调整微信 HTML 预处理质量（解析与评测分段），再实施本方案的 connector 与通用清单；否则批量导入只会得到质量不足的子块。两项工作互不依赖，可分开提交。

待定事项：

- 旁注字段已按第 7 节实现；永久链接的获取方式以实际采集方法为准，取不到时使用采集键。
- `sources` 应用名与 API 路径 `/api/v1/sources/` 同名但含义不同，是否改名为 `connectors` 在实施时决定。
- 是否需要单篇 `fetch` 入口（例如 API 按链接导入单篇），出现需求时再增加 `resolve(locator) → SourceRef`。
