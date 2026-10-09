# 分阶段实现方案

本文把[技术方案](technical-design.md)拆成 6 个可以独立合并的阶段。每个阶段完成后，系统都能正常启动和运行，已有功能不受影响，新增功能可以通过现有入口实际使用和验收。**当前处于方案阶段，各阶段均未开始。**

## 1. 总体安排

### 1.1 阶段一览

先只用操作教程打通“语雀读取 → 预处理 → 导入 → 检索”的完整链路，确认可用后再扩充知识和工具条目两类。

| 阶段 | 交付的功能 | 新增的可用入口 | 依赖 | 需要语雀 Token |
| --- | --- | --- | --- | --- |
| 1. 语雀 Markdown 解析 | 语雀方言清洗；Markdown 识别图片、引用和提示块 | 原文 API 接受 `text/x-yuque-markdown`，可配合现有 schema 使用 | 无 | 否 |
| 2. 教程流水线 | 章节策略、风险提示、时效提示、检索前缀 | 原文 API 的 `tutorial@1` | 阶段 1 | 否 |
| 3. 导入命令（快照） | 导入清单、类别判定、批量导入与试运行报告；只接入教程 | `import_yuque --snapshot` | 阶段 2 | 否 |
| 4. 语雀读取与教程验收 | 官方 OpenAPI 读取、保存快照；28 篇教程真实导入与检索抽查 | `import_yuque`（直接读取语雀） | 阶段 3 | 是 |
| 5. 知识流水线 | 表格行组、知识参数；15 篇知识导入与抽查 | 原文 API 与导入命令的 `knowledge@1` | 阶段 4 | 否（用阶段 4 保存的快照） |
| 6. 工具条目流水线 | 工具身份、来源日期提示；31 篇工具导入、74 篇整体验收 | 原文 API 与导入命令的 `tool_card@1` | 阶段 4 | 否（同上） |

- **阶段 1～4 是教程闭环**：阶段 4 完成时，28 篇教程已从语雀导入开发环境，可以检索。这是扩充类型前的检查点：方言规则、章节策略、清单、导入命令和读取接口都经过了真实数据检验。
- **阶段 5、6 只扩充类型**：每个阶段只新增一套参数、少量增强步骤、一次 schema 注册和映射表中的一行，不改导入链路。两者互不依赖，顺序可以互换。
- **未接入的类型不会被误导入**：类别映射表只包含已注册的 schema。阶段 3、4 中，清单里的知识和工具条目在报告中显示为“未接入”，阶段 5、6 加入映射后自动变为可导入。
- **Token 延迟时**：阶段 1～3 可以照常完成。阶段 4 的 OpenAPI 客户端需要等 Token；教程的真实样本验收可以先用本机公开文档整理成的快照完成，阶段 5、6 也可以先基于该快照推进，Token 到位后再补 OpenAPI 实测。

### 1.2 OpenAPI 在本方案中的作用

导入命令通过 YuqueClient 读取语雀文档，有两种实现：

| 实现 | 读取来源 | 用途 |
| --- | --- | --- |
| 快照客户端（阶段 3） | 本机目录中的 `toc.json`、`docs.json` 和每篇 `.md` 文件 | 离线试运行、测试、复现某次导入 |
| OpenAPI 客户端（阶段 4） | 语雀官方接口：知识库目录、文档列表、单篇 Markdown 正文 | 正式导入与后续同步 |

快照只是文件，总得有人先从语雀把文档取下来。OpenAPI 客户端就是“取下来”的那一步：

1. **正式数据来源**：前期分析用的是语雀网页的未公开接口和网页导出，只适合一次性分析，接口可能随时变化，也读不到非公开知识库。正式导入需要官方接口，它要求 Token。
2. **获得目录结构和身份信息**：`collection_path`（检索前缀与工具分类的依据）来自目录接口；稳定的文档数字 ID 和最后更新时间来自文档接口。
3. **后续同步**：语雀内容更新后，重新运行命令即可同步，不需要人工导出。
4. **生成快照**：`--save-snapshot` 把读取结果保存到本机，后续试运行、阶段 5、6 的调试都可以离线进行，不必反复请求语雀。
5. **核实方言**：清洗规则是对照网页导出写的，官方接口返回的 Markdown 是否完全一致需要实测，有差异时调整规则。

### 1.3 每个阶段的完成标准

每个阶段合并前都要满足以下条件，这也是“系统可运行”的具体含义：

1. **自动测试全部通过**：`make test-unit`，以及在隔离 PostgreSQL 上运行的 `make test-integration` 和 `make test`，环境准备见[项目测试规则](../../unit-testing-guidelines.md#环境准备与分层运行)。另需通过[预处理专项验证](../../unit-testing-guidelines.md#预处理专项验证)。
2. **服务可启动、无新迁移**：

   ```sh
   .venv/bin/python manage.py check
   .venv/bin/python manage.py makemigrations --check --dry-run
   ```

3. **已有功能不变**：按[原文导入验收](../deployment.md#35-验收原文预处理导入)提交原有合成评测并检索，结果与改动前一致；`product_review`、`purchase_guide`、`experience_case` 的已有用例不改断言即通过。从阶段 4 起，已导入的教程重新运行导入命令应全部为 `reused`，确认后续阶段没有改变教程的处理结果。
4. **本阶段新功能经实际入口验收**：按各阶段“验收”一节操作，通过原文 API 或导入命令，而不是只跑单测。
5. **文档同步**：更新各阶段列出的文档，并在[概览](overview.md)中更新阶段状态。
6. **提交**：每个阶段单独提交，使用 Conventional Commits，例如 `feat(ingestion): 增加语雀 Markdown 方言解析`。快照、真实原文和 Token 不提交。

### 1.4 通用手动验收手段

阶段 1、2 没有导入命令，可以用下面的方式只预处理、不编码、不保存，查看一篇 Markdown 被分成什么样。需要先按 README 加载 `.env.local`，但不需要 Embedding 服务：

```sh
SAMPLE=.runtime/samples/sample.md SCHEMA=tutorial .venv/bin/python manage.py shell -c '
import os
from pathlib import Path
from config import components
from contracts.types import RawDocument
path, schema = os.environ["SAMPLE"], os.environ["SCHEMA"]
raw = RawDocument(Path(path).read_bytes(), "text/x-yuque-markdown",
                  {"title": Path(path).stem, "source_date": "2025-11-23", "collection_path": ["合成目录"]})
doc = components.preprocessors().process(raw, schema, 1)
print("文档警告:", doc.warnings)
for c in doc.contexts:
    print(f"\n## {c.title}  正文 {len(c.body)} 字，子块 {len(c.children)} 个，警告 {c.warnings}")
    for e in c.children:
        print("  -", e.retrieval_prefix.replace("\n", " / "), "|", e.body[:40].replace("\n", " "))
'
```

- 样本放在被忽略的 `.runtime/samples/`。可以是手写的合成样本，也可以是本机的公开文档导出；不提交。
- 阶段 1 只注册了解析器，可把 `SCHEMA` 换成 `experience_case` 查看解析效果；从阶段 2 起使用新的 schema。
- 这种方式绕过 API 的请求校验，只用于查看分段效果；字段校验以原文 API 为准。
- 阶段 3 起改用导入命令的 `--dry-run`，效果相同且能批量查看。

端到端验收使用原文 API 和检索 API，账号与 Token 文件的准备见[部署与验收第 3.1 节](../deployment.md#31-创建维护者和普通调用账号)。

## 2. 阶段 1：语雀 Markdown 解析

### 2.1 实现内容

| 文件 | 内容 |
| --- | --- |
| [ingestion/parsers.py](../../../ingestion/parsers.py) | MarkdownParser：图片块与占位、引用块、GitHub 提示块转为 `callout`、忽略空标题、`pseudo_heading` 参数（默认 `level2`，行为不变） |
| `ingestion/yuque_markdown.py` | `normalize_yuque` 行规则与 YuqueMarkdownParser，规则见[技术方案 4.2](technical-design.md#42-规范化规则) |
| [config/components.py](../../../config/components.py) | `parsers.register("text/x-yuque-markdown", YuqueMarkdownParser())` |

### 2.2 完成后的系统状态

- 原文 API 可以提交 `media_type=text/x-yuque-markdown`，搭配任一现有 schema，例如用 `experience_case` 按标题分段导入语雀文档。
- 所有 Markdown 输入（含 `text/plain`）中的图片和引用会变成独立的内容块，图片占位与 HTML 输入一致。这是有意的行为变化，需在[文档预处理](../preprocessing.md)记录。
- 还没有自适应的章节分段，语雀文档的父段划分仍取决于所选的现有 schema。

### 2.3 验收

自动测试：

| 用例 | 检查 |
| --- | --- |
| `tests/unit/test_yuque_markdown.py`（新增） | 每条方言规则；行号与原文一致；代码块内不处理；`<你的用户名>` 等占位符保留；折叠块；表格内换行 |
| `tests/unit/test_preprocessing_parsers.py`（扩充） | 图片块与占位、引用与提示块、空标题、`pseudo_heading` 两种取值；已有用例不改 |
| `tests/integration/test_raw_ingestion.py`（扩充） | 一篇合成语雀 Markdown 以 `experience_case` 经原文 API 导入，检索结果正文不含样式标签和图片地址 |

手动验收：

1. 用 1.4 的方式预处理一篇含 `<font>`、`:::warning`、语雀图片和表格内 `<br/>` 的样本，schema 用 `experience_case`。检查：
   - 正文没有 `<font`、`:::`、`cdn.nlark.com`。
   - 提示块变为以【警告】开头的段落。
   - 表格行内的换行变为“；”，表格仍为一行一条。
   - 文档警告包含图片缺少说明的提示。
2. 通过原文 API 提交同一样本，检索样本中的一句话，命中的父段正文满足上面几条。
3. 提交一个 `media_type` 为 `text/x-unknown` 的请求，仍返回原有的“不支持的格式”错误。

### 2.4 文档同步

[文档预处理](../preprocessing.md)第 2 节：新媒体类型、图片与引用的新文本形式、`pseudo_heading` 参数。

## 3. 阶段 2：教程流水线

### 3.1 实现内容

| 文件 | 内容 |
| --- | --- |
| `ingestion/sections.py` | SectionProfile、SectionNode、`build_tree`、`plan_parents`、`merge_blocks`、SectionedDocumentStrategy；TUTORIAL 参数。表格整体参与合并，行组拆分留到阶段 5 |
| `ingestion/enrichment.py` | CalloutWarningStep、TimeExpressionStep、RetrievalPrefixStep |
| [ingestion/preprocessing.py](../../../ingestion/preprocessing.py) | ParseStep 的图片警告文案可配置，默认不变 |
| [contracts/serializers.py](../../../contracts/serializers.py) | `raw.metadata.collection_path` 校验 |
| [config/components.py](../../../config/components.py) | `pipeline()` 增加增强步骤参数；注册 `tutorial@1` |

### 3.2 完成后的系统状态

- 原文 API 可以用 `tutorial` 处理任意 HTML、Markdown 或语雀 Markdown，父段按章节自适应划分，标题带章节路径。
- 语雀教程已经可以手工逐篇导入：维护者提交 Markdown，填写标题、日期和 `collection_path`。

### 3.3 验收

自动测试：

| 用例 | 检查 |
| --- | --- |
| `tests/unit/test_sections.py`（新增） | 自适应顶层、包裹标题下降、超长下钻与导语父段、过短父段合并、无标题文档、子块相连规则（引导句、列表、编号、提示块）、key 稳定、标题截断、图片计数 |
| `tests/unit/test_enrichment_steps.py`（新增） | 提示块进入父段或文档 warnings；时效表述；检索前缀；增强步骤插入流水线后阶段校验通过 |
| `tests/unit/test_raw_import.py`（扩充） | `collection_path` 的类型、条数与长度校验 |
| `tests/integration/test_yuque_ingestion.py`（新增） | 合成教程经原文 API 导入：父段标题带章节路径、warnings 正确、重复导入返回 `reused`、internal 文档对普通账号不可见 |

手动验收：

1. 用 1.4 的方式预处理 2～3 篇较长的教程，最好是本机的公开文档导出，例如 Windows 安装教程。对照[技术方案 6.4](technical-design.md#64-产出示例)检查：
   - 父段标题是章节路径，没有“一、准备工作”这类章节名被当成文档标题。
   - 编号步骤和其后的说明在同一个子块里，提示块跟在所属步骤后面。
   - 原文中的警告提示出现在对应父段的警告里。
2. 通过原文 API 导入一篇合成教程：

   ```sh
   curl -sS --fail-with-body -w '\nHTTP %{http_code}\n' \
     -H "Authorization: Token $(cat "$TOKEN_FILE")" \
     -H 'Content-Type: application/json' \
     --data-binary @- http://127.0.0.1:8000/api/v1/sources/raw/ <<'JSON'
   {
     "source": {"source_type": "yuque", "canonical_locator": "synthetic:yuque-tutorial", "visibility": "public"},
     "preprocess": {"schema": "tutorial", "version": 1},
     "raw": {
       "content": "# 合成安装教程\n\n## 准备篇\n\n准备一个 8GB 以上的 U 盘，并备份 C 盘中的个人文件。下载官方镜像后使用写盘工具制作启动盘，写盘会清空 U 盘中原有的数据。\n\n## 安装篇\n\n### 一、进入装机盘\n\n开机时连续按 F12，在启动菜单中选择 U 盘。\n\n### 二、开始安装\n\n:::warning\n删除分区前确认已经备份数据。\n:::\n\n选择自定义安装，截至 2025 年该选项仍位于第二页。",
       "media_type": "text/x-yuque-markdown",
       "metadata": {"title": "合成安装教程", "source_date": "2025-11-23", "collection_path": ["合成目录"]}
     }
   }
   JSON
   ```

   然后检索“开机按什么键选择 U 盘”，检查：
   - 返回的 `document_schema` 为 `tutorial`。
   - 命中父段的标题是章节名“安装篇”，而不是文档标题或“二、开始安装”。样本很短，各章节不会下钻，带“ > ”的章节路径由第 1 步的长文档和集成测试验证。
   - 警告包含“删除分区前确认已经备份数据”和“截至 2025 年”的时效提示。
   - 重复提交返回 `reused=true`。

### 3.4 文档同步

- [文档预处理](../preprocessing.md)第 3～6 节：`tutorial` schema、章节策略规则、增强步骤、`collection_path`。
- [首期技术设计](../phase1-technical-design.md) 3.2 的 schema 注册列表。

## 4. 阶段 3：导入命令（快照）

### 4.1 实现内容

| 文件 | 内容 |
| --- | --- |
| `sources/`、[config/settings.py](../../../config/settings.py) | 新建无模型的 Django 应用并加入 `INSTALLED_APPS` |
| `sources/yuque/client.py` | YuqueDocRef、YuqueClient 协议、YuqueSnapshotClient |
| `sources/yuque/manifest.py` | 清单读取、校验与 `classify` |
| `sources/yuque/importer.py` | 标题清洗、`build_request`、YuqueImportService、报告 |
| `sources/management/commands/import_yuque.py` | `--manifest`、`--snapshot`、`--only`、`--dry-run`、`--username`。本阶段 `--snapshot` 必填，缺省时提示“OpenAPI 读取尚未实现” |
| [config/components.py](../../../config/components.py) | `CATEGORY_PIPELINES`，本阶段只有 `tutorial` |
| `sources/yuque/manifests/itxia.toml` | 第一批 74 篇的清单初稿：原型生成后人工复核，只含知识库、slug、类别、跳过原因和可见性。三类都登记，知识和工具暂为“未接入” |

快照目录格式见[技术方案 7.1](technical-design.md#71-平台读取)。

### 4.2 完成后的系统状态

- 维护者可以用一条命令把快照目录中的教程按清单批量导入，或只做试运行查看报告。
- 每篇文档的类别、状态和失败原因都在报告中可查。未登记的文档不导入；知识和工具条目显示为“未接入”，也不导入。
- 读取仍依赖本机快照，不能直接连语雀。

### 4.3 验收

自动测试：

| 用例 | 检查 |
| --- | --- |
| `tests/unit/test_yuque_manifest.py`（新增） | 单篇条目优先于目录规则、最长路径前缀、未登记、跳过、未接入类别；未知字段、未知类别、`category` 与 `skip` 同时出现、`canonical` 指向不存在条目时报错 |
| `tests/unit/test_yuque_importer.py`（新增） | 合成快照加假提交函数：试运行不编码；单篇失败不中断其余文档；各种状态写入报告；标题清洗；`canonical_locator`、`source_url`、`source_date`（北京时间）、`collection_path` 与可见性正确 |
| `tests/integration/test_yuque_ingestion.py`（扩充） | 用 `call_command` 对测试中生成的合成快照执行导入，模型替身从组合根替换；数据库中出现对应来源，再次执行全部为 `reused` |

手动验收：

1. 在 `.runtime/yuque-snapshot/` 准备快照：沿用清单中已有的 slug，正文写合成内容，至少覆盖清单登记的教程、清单跳过、未登记、一篇知识或工具条目（未接入）各一篇，并包含一篇 `textbook` 知识库的教程。有本机公开文档导出时，也可以整理成快照格式，对 28 篇教程试运行。
2. 试运行：

   ```sh
   .venv/bin/python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
     --snapshot .runtime/yuque-snapshot --dry-run
   ```

   检查报告中每篇文档都有状态，判定依据（manifest、path_rule）正确，知识和工具显示“未接入”，汇总行数字与篇数一致。未配置 Embedding 时也能运行。
3. 正式导入：去掉 `--dry-run`，加 `--username maintainer`。检查命令退出码为 0；检索 API 能查到导入的教程，且 `source_type` 为 `yuque`、`source_url` 指向语雀原文。
4. 再执行一次，所有导入的文档为 `reused`。
5. 用普通账号检索 `textbook` 中的教程，查不到；用带 `read_internal` 的账号能查到。
6. 故意在清单中写一个未知类别，命令启动即失败，不处理任何文档。

### 4.4 文档同步

- [README](../../../README.md)：导入命令说明。
- [概览](overview.md)与本目录：清单位置与维护方式。
- [项目测试规则](../../unit-testing-guidelines.md)：语雀相关测试文件。

## 5. 阶段 4：语雀读取与教程验收

### 5.1 实现内容

| 文件 | 内容 |
| --- | --- |
| `sources/yuque/client.py` | YuqueOpenApiClient：读取目录、文档列表和单篇正文，`X-Auth-Token` 请求头，固定请求间隔；401／403 终止整批，429 和网络错误记为当前篇失败 |
| `sources/management/commands/import_yuque.py` | 无 `--snapshot` 时使用 OpenAPI；新增 `--save-snapshot` |
| [config/settings.py](../../../config/settings.py)、`.env.example` | `YUQUE_TOKEN`、`YUQUE_API_BASE`，示例中只留空值 |
| `ingestion/yuque_markdown.py` | 按 OpenAPI 与网页导出的实测差异调整规则（如有） |
| `sources/yuque/manifests/itxia.toml` | 根据真实目录核对 slug，教程部分定稿 |

### 5.2 完成后的系统状态

- `import_yuque` 可以直接从语雀读取并导入，也可以把读取结果保存为快照。
- 28 篇教程已导入开发环境并可检索，教程链路完整可用。
- 保存的快照覆盖第一批全部 74 篇，阶段 5、6 可以离线基于它开发和验收。

### 5.3 验收

自动测试：

| 用例 | 检查 |
| --- | --- |
| `tests/integration/test_yuque_openapi.py`（新增） | 本地临时 HTTP 服务模拟语雀接口，不访问真实网络：请求路径与 `X-Auth-Token` 头、目录路径计算、401 终止、429 记为单篇失败、`--save-snapshot` 生成的快照可被快照模式读取、日志和报告中不出现 Token |

手动验收需要 Token，结果注明日期记录在概览中，快照不提交：

1. **接口实测**：读取三个知识库的目录和 5 篇文档（含 3 篇教程），把 `body` 与网页导出逐篇对比；有差异时调整方言规则，并补对应单测。
2. **保存快照并试运行**：用 `--save-snapshot` 把三个知识库保存到 `.runtime/yuque-snapshot/`，在快照上试运行。28 篇教程 0 失败；跳过、未登记、未接入与清单一致；教程的父段与子块规模与[技术方案 5.2](technical-design.md#52-父段规划) 的估算同量级；被预算切分的代码块逐一检查。
3. **人工抽查 3 篇教程**：`install_win10`、`hello_my_pc`、`change_win_account_name`。检查正文无样式标签和图片地址、占位符保留、章节路径正确、步骤未断开、warnings 完整。
4. **开发环境导入与检索抽查**：配置真实 Embedding 模型导入 28 篇教程，执行教程相关查询，记录期望文档是否出现在前 5 个父段：

   | 查询 | 期望命中 |
   | --- | --- |
   | Windows 怎么改用户名 | Windows 更改用户名教程 |
   | 新电脑开机怎么跳过联网 | 新笔记本验机／设置指南 5.1 |
   | 重装系统前要准备什么 | Windows 安装教程的准备篇 |

   结果用于校准教程参数，不作为自动化通过标准；需要调整参数时注册新版本。确认教程效果可以接受后，再进入阶段 5、6。

### 5.4 文档同步

- [概览](overview.md)：教程链路已可用，记录真实样本验收的日期与结果。
- [来源接入说明](../source-ingestion-plan.md)：语雀读取已实现，Token 与权限的实际情况。
- [部署与验收](../deployment.md)：语雀导入的操作步骤。
- [README](../../../README.md)：`YUQUE_TOKEN` 配置说明。

## 6. 阶段 5：知识流水线

### 6.1 实现内容

| 文件 | 内容 |
| --- | --- |
| `ingestion/sections.py` | `table_rows_as_children`：长表格按行组拆成子块，表头写入检索前缀；KNOWLEDGE 参数 |
| [config/components.py](../../../config/components.py) | 注册 `knowledge@1`（复用 CalloutWarning、TimeExpression、RetrievalPrefix 三个步骤），映射表加入 `knowledge` |
| `sources/yuque/manifests/itxia.toml` | 知识部分定稿 |

### 6.2 完成后的系统状态

- 原文 API 和导入命令都能处理知识类文档，速查表、比较表的每个行组可以被单独命中。
- 报告中的知识类文档从“未接入”变为可导入。

### 6.3 验收

自动测试：

| 用例 | 检查 |
| --- | --- |
| `tests/unit/test_sections.py`（扩充） | 表格行组：行组连续、表头进入前缀、短表格不拆；KNOWLEDGE 参数下过碎小节合并 |
| `tests/unit/test_enrichment_steps.py`（扩充） | 检索前缀与表头前缀以换行组合 |
| `tests/integration/test_yuque_ingestion.py`（扩充） | 合成速查表导入后，检索表中某一行的术语命中对应行组，检索文本带表头 |

手动验收（基于阶段 4 保存的快照）：

1. 对 15 篇知识试运行，0 失败，规模与估算同量级。
2. 人工抽查 `win10_activation`、`windows_short_commands`、`slang`：包裹全文的单一标题已下降一级；速查表按行组拆分且每组带表头；术语小节没有碎成一两句话的子块。
3. 导入开发环境，执行知识相关查询：

   | 查询 | 期望命中 |
   | --- | --- |
   | 重置 Winsock 的命令 | Windows系统功能快速查阅表对应行组 |
   | 数字权利激活是什么 | Windows 10/11 的版本与激活详解 |
   | ProgramData 文件夹是干什么的 | C盘文件夹的功能与分布 |
   | 独显和核显有什么区别 | 黑话指南或笔记本核心硬件科普 |

4. 重新运行导入命令，已导入的教程全部为 `reused`。

### 6.4 文档同步

[文档预处理](../preprocessing.md)：`knowledge` schema 与表格行组规则；首期技术设计的注册列表；概览状态。

## 7. 阶段 6：工具条目流水线

### 7.1 实现内容

| 文件 | 内容 |
| --- | --- |
| `ingestion/enrichment.py` | ToolIdentityStep、SourceDateNoticeStep |
| `ingestion/sections.py` | TOOL_CARD 参数 |
| [config/components.py](../../../config/components.py) | 注册 `tool_card@1`，映射表加入 `tool_card` |
| `sources/yuque/manifests/itxia.toml` | 工具部分与整份清单定稿 |

### 7.2 完成后的系统状态

- 原文 API 和导入命令都能处理工具条目：单工具文档一个父段，工具合集按分类成父段、每个工具一个子块。
- 检索结果的父段 metadata 带 `tool_name`、`tool_purpose`、`tool_category`，文档警告带最后更新日期。
- 第一批三类共 74 篇全部可导入，第一批完成。

### 7.3 验收

自动测试：

| 用例 | 检查 |
| --- | --- |
| `tests/unit/test_enrichment_steps.py`（扩充） | “用途：工具名”标题解析；合集文档取章节末段为工具名；目录末段为工具分类；来源日期提示的文案与日期缺失时的提示 |
| `tests/unit/test_sections.py`（扩充） | TOOL_CARD 参数下工具小节不合并、每个工具单独成子块 |
| `tests/integration/test_yuque_ingestion.py`（扩充） | 工具条目经原文 API 导入，检索结果带工具 metadata 和日期提示 |

手动验收：

1. 通过原文 API 提交一篇合成单工具文档，格式同阶段 2 的 curl：标题“文件占用查看：合成工具”，正文 `## 简介\n\n合成工具按文件夹大小直观显示磁盘占用。\n\n官网：https://example.com`，`schema` 改为 `tool_card`，`source_date` 为 `2020-03-27`，`collection_path` 为 `["常用工具大全", "文件占用和系统清理"]`。检索“查看文件夹占用空间用什么软件”，检查：
   - 父段 metadata 中 `tool_name` 为“合成工具”、`tool_purpose` 为“文件占用查看”、`tool_category` 为“文件占用和系统清理”。
   - 文档警告为“本条目内容最后更新于 2020-03-27，软件版本、下载地址和界面可能已变化，请以官网为准”。
   - 去掉 `source_date` 重新提交，警告变为“更新日期未知”。
2. 基于快照对 74 篇整体试运行：0 失败，跳过和未登记与清单一致，没有“未接入”的第一批文档。
3. 人工抽查 `sdi-driver`、`giq7z502ohos1d3u`、`recommended_tools`：工具名、用途、分类正确，合集中每个工具单独成子块，SDI 的 Alps 警告和官网地址保留。
4. 导入开发环境，执行工具相关查询：

   | 查询 | 期望命中 |
   | --- | --- |
   | 查看哪个文件夹占空间大 | WizTree／SpaceSniffer／TreeSize |
   | SDI 装驱动要注意什么 | Snappy Driver Installer（含 Alps 警告） |

5. 重新运行导入命令，已导入的教程和知识全部为 `reused`。

### 7.4 文档同步

- [文档预处理](../preprocessing.md)：`tool_card` schema 与两个增强步骤；首期技术设计的注册列表。
- [概览](overview.md)：状态改为第一批已实现，记录整体验收日期与结果。
- [README](../../../README.md)：去掉导航中的“方案阶段，未实现”字样。
