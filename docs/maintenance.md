# 维护手册

本文汇总部署后需要人工维护的内容：库中资料、检索词表与参数、评测集、账号和备份。部署与首次验收见[部署与验收](deployment.md)，下文命令沿用其中定义的 `dc` 函数，从仓库根目录执行。

## 1. 总览

| 维护对象 | 位置 | 什么时候改 | 生效方式 | 改后验证 |
| --- | --- | --- | --- | --- |
| 语雀文档 | 清单 [itxia.toml](../sources/yuque/manifests/itxia.toml) | 新增、改类别、原文更新 | 重新运行导入 | 导入报告；涉及评测答案时跑评测 |
| 公众号评测 | `.runtime/eval/corpus-v1/` 下的清单与采集目录（被忽略） | 新增评测、修正机型名 | 重新运行导入 | 导入报告；评测 |
| 单篇资料 | 标准 JSON 或原文 API | 零散补充 | 提交即生效 | 检索抽查 |
| 领域词典 | [keyword-terms.txt](../retrieval/keyword-terms.txt) | 专有名词被切碎 | 重建 app | 评测 |
| 同义词表 | [keyword-synonyms.txt](../retrieval/keyword-synonyms.txt) | 问法与原文用词对不上 | 重建 app | 评测 |
| 停用词 | [tokenization.py](../retrieval/tokenization.py) 的 `_STOPWORDS` | 问句虚词影响排序 | 改代码、重建 app | 单测与评测 |
| 检索参数 | [settings.py](../config/settings.py)、环境变量门槛 | 评测表明有更优配置 | 重建 app | 评测，写入改进记录 |
| Embedding 模型 | `.env.docker` | 更换模型或 query prefix | **全量重新导入** | 全量评测 |
| 评测集 | [queries.json](../eval/queries.json)、[attributes.json](../eval/attributes.json) | 新增查询、补标、资料变化 | 下次评测 | 评测脚本能加载 |
| 账号与 Token | 数据库 | 新增调用方、Token 泄露 | 立即生效 | 401／403 检查 |

几条通用规则：

- **三种生效方式**：
  - 改资料要重新导入；
  - 改词表、参数和代码要重建应用容器：`dc up -d --build app`；
  - 只有换模型需要全量重新导入。
- **评测不用重建**：评测命令挂载宿主机的 `eval/`、`retrieval/`、`config/`，所以改完可以先评测，确认后再重建上线。
- **先备份**：会删除或覆盖数据的操作（删除来源、全量重导）之前先备份，见第 7 节。
- **不提交原文**：快照、采集目录、正式公众号清单、Token 和评测结果都在被忽略的 `.runtime/` 下，不提交。

## 2. 库中资料

### 2.1 更新机制

同一来源由 `source_type` 与 `canonical_locator` 确定，不同平台的取值如下：

- 语雀是 `doc:<文档 ID>`；
- 公众号是永久链接，没有链接时用采集文件名。

重新导入同一来源时，按内容分两种情况：

- **内容不变**：返回 `reused`，不改数据库。
- **内容有变**：返回 `imported`，整篇替换。key 不变的父段和子块保留 ID，消失的段落会被删除。

**没有删除同步**：清单里删掉某篇或改成 `skip`，不会删除已入库的内容，下线要按 2.4 手动删除。

### 2.2 语雀文档

1. **原文更新**：重跑导入。可以只跑指定文档：

   ```sh
   dc exec app python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
     --only help/install_win10
   ```

   不加 `--only` 时处理清单里所有知识库，未改动的文档都返回 `reused`。
2. **新增文档**：导入报告把清单里没有的文档列为 `unregistered`。在清单中登记：

   ```toml
   [docs."help/new_slug"]
   category = "tutorial"        # tutorial、knowledge、tool_card、troubleshooting、case

   [docs."help/old_note"]
   skip = "过时内容"            # 不导入时必须写原因
   ```

   新知识库还要在清单中加 `[collections.<库名>]` 和 `visibility`；工具大全这类按目录统一分类的，可以用 `[[path_rules]]`。清单格式见[来源连接器方案](phase1/source-connector-design.md#5-清单)。
3. **先试运行**：加 `--dry-run` 检查父段、子块数和警告，无失败后再正式导入。
4. **需要可复现时用快照**：用 `--save-snapshot` 保存快照，再用 `--snapshot` 离线导入，见[部署与验收 3.7](deployment.md#37-语雀网页与快照导入)。清单改动要提交，快照不提交。

### 2.3 公众号评测

1. **采集**：把获准文章保存到采集目录，格式是 `<账号>/<条目>.html` 加同名 `.json` 旁注。可以用 `fetch_wechat` 下载，也可以人工保存。规则见 [README](../README.md#公众号采集导入)。
2. **登记清单**：在正式清单中登记 `category`。评测必须填 `metadata.entity_title`，也就是完整机型名：
   - 不能与已有评测重名；
   - 同系列不同配置要加区分后缀，如“RTX 5070 Ti 版”。
3. **试运行后导入**：用一次性容器挂载 `.runtime/eval/corpus-v1/`，命令见[部署与验收 3.8](deployment.md#38-公众号采集导入)。
4. **D 类属性（可选）**：新评测要参与按条件找机器（D 类）评测时，在 [attributes.json](../eval/attributes.json) 中补价格、重量、接口等属性，键为 `entity_title`。

### 2.4 下线或删除来源

目前没有删除命令。确实需要下线时，先备份，再按标题或定位查出来源，确认后删除。删除来源会级联删除它的父段和子块：

```sh
dc exec app python manage.py shell -c "
from catalog.models import KnowledgeSource as S
qs = S.objects.filter(source_type='yuque', title='要下线的标题')
print(list(qs.values_list('id', 'canonical_locator', 'title')))
# 确认无误后：print(qs.delete())
"
```

删除后要同步两处：

- 把清单中对应条目改为 `skip` 并注明原因，以免下次批量导入又导进来；
- 检查 [queries.json](../eval/queries.json) 中有没有答案指向它（见第 5 节）。

### 2.5 更换 Embedding 模型

地址、模型、维度、revision 或 query prefix 任何一项改变，旧向量都不能再用，按以下步骤处理：

1. 备份数据库。
2. 修改 `.env.docker`，然后重建 app。
3. 按 2.2、2.3 全量重新导入。
4. 跑全量评测，并在评测文档中把语料版本号加 1。

## 3. 检索词表

三个词表都只作用于关键词路，查询时实时分词，所以改动不需要重新导入。

### 3.1 先判断问题类型

先看问题和原文分别被切成什么词：

```bash
.venv/bin/python -c "from retrieval.tokenization import tokenize, tokenize_for_search; print(tokenize('问题原文')); print(tokenize_for_search('文档中的说法'))"
```

再按现象处理：

| 现象 | 处理 |
| --- | --- |
| 两边已有相同的词 | 不用改，问题在别处（排序、标注） |
| 专有名词被切成单字（品牌、系列名） | 加进领域词典 |
| 两边是完全不同的说法 | 加进同义词表 |
| 问句里的虚词干扰排序 | 调停用词 |

评测结果里每条都记了 `keyword_terms`（关键词路实际检索的词），可以直接和原文对照。

### 3.2 领域词典

- **格式**：每行一个词。
- **收什么**：jieba 默认会切成单字的品牌、系列名和术语，如“拯救者”“灵耀”。
- **不收什么**：能切成有意义词语的词，如“游戏本”。如果收了，问“游戏”就匹配不到“游戏本”。
- 新机型系列可以从公众号清单的 `entity_title` 中找。

### 3.3 同义词表

**格式**：每行一组可以互换的说法，用空格分开；`#` 后写注释，注明来源查询：

```
流氓软件 垃圾软件  # U09：问题说“流氓软件”，SoftCnKiller 工具条目写“垃圾软件”
```

**收录规则**：

- **有来源**：只收评测或真实提问中实际遇到、分词解决不了的错配。
- **双向等价**：问题含组里任何一个词，其余词都会被追加，所以不放上下位关系，如“软件 / 流氓软件”。
- **不太短、不太通用**：按子串匹配，“内存”在“内存条”里也会触发；“电脑 / 笔记本”这类会给大量查询加噪声，不收。
- **每个词至少两个字**：程序启动时检查，单测 `test_bundled_synonym_table_is_valid` 也会检查。
- **规模**：控制在几十条以内。

### 3.4 停用词

停用词写在代码里，改动属于代码修改：要补单测，并跑全量测试和评测。现在会移除“能”“用”“多久”等词，删减前要确认不会影响“能加内存吗”“续航多久”这类问题。

### 3.5 验证与上线

1. 可以攒几条改动再验证，不必每加一个词跑一次。
2. 按第 6 节跑评测并对比当前基线，检查三点：
   - 目标查询有没有改善；
   - 有没有其他查询因误触发而变差；
   - 新进前 5 的父段要不要补标。
3. 在[召回改进记录](phase2/retrieval-improvement-log.md)中记录改动、效果和是否保留。
4. 提交后重建 app：`dc up -d --build app`。

## 4. 检索参数

| 参数 | 位置 | 当前值 |
| --- | --- | --- |
| `RETRIEVAL_RRF_K` | settings.py | 20 |
| `RETRIEVAL_RRF_WEIGHTS` | settings.py | `{}`（不加权） |
| `RETRIEVAL_KEYWORD_SEARCH_MODE` | settings.py | `document` |
| `RETRIEVAL_KEYWORD_SYNONYMS` | settings.py | `True` |
| `RETRIEVAL_MIN_COSINE`、`RETRIEVAL_MIN_BM25` | 环境变量 | 不过滤、0 |

调整流程：

1. 先用评测参数试，不改配置。可用参数有 `--rrf-k`、`--vector-weight`、`--search-mode`、`--synonyms`。
2. 按[改进方案](phase2/retrieval-improvement-plan.md)中的采纳条件筛选，通用底线见[改进记录第 1 节](phase2/retrieval-improvement-log.md#1-记录规则)。
3. 通过后再改默认值。
4. 同步[改进记录](phase2/retrieval-improvement-log.md)和[技术设计 5.1](phase1/phase1-technical-design.md)。
5. 重建 app。

## 5. 评测集

[queries.json](../eval/queries.json) 由四部分组成：

| 部分 | 内容 |
| --- | --- |
| `scopes` | 检索范围，即范围名对应的 `document_schema` 列表 |
| `aliases` | 答案别名，可写两种形式：评测的 `entity_title`；或语雀的 `{"doc": "库/slug", "titles": [父段标题...]}`，不写 `titles` 时表示整篇 |
| `attributes` | D 类属性表文件名 |
| `queries` | 查询，字段有 `id`、`cat`、`q`、`rel`（答案别名）和 `facts` |

日常维护有四种情况：

- **资料变化后**：评测器加载时会检查每个别名都能唯一对应到父段。如果语雀小节改了标题、评测改了机型名或来源被删除，评测会直接报断言错误，需要按新标题更新 `aliases`。
- **新增查询**：
  - 先写问题，再去原文找答案；
  - 编号按类别续写，类别含义见[评测 9.3](phase1/yuque-ingestion/retrieval-evaluation.md#93-查询集与标注)；
  - 真实提问要先脱敏，再加 `"origin": "real"`；不提交未脱敏的原文。
- **补标**：
  - 对比脚本会列出“新进前5未标注”的父段，逐条看原文判断；
  - 只有直接回答问题的父段才补进答案，只有背景介绍、链接或其他型号的不补；
  - 补标后要重跑基线，对比脚本拒绝把标注不同的结果放在一起比。
- **版本**：查询集或语料变化时升级版本号，并记在评测文档第 9 节或改进记录中。不同版本的结果不直接比较。

## 6. 运行召回评测

评测只读正式库，不改数据。镜像里已有 `eval/`，但用一次性容器挂载宿主机的 `eval/`、`retrieval/`、`config/`，可以在不重建镜像的情况下评测最新改动。每次全量约需 3～6 分钟：

```sh
mkdir -p .runtime/eval/corpus-v3
dc run --rm --no-deps -v "$PWD/eval:/app/eval:ro" -v "$PWD/retrieval:/app/retrieval:ro" \
  -v "$PWD/config:/app/config:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app app \
  python eval/recall_eval.py eval/queries.json /data/corpus-v3/results-v10.json \
  > .runtime/eval/corpus-v3/report-v10.txt
```

使用说明：

- 不传参数时用 settings 的当前配置，跑全部范围；`--scope all` 只跑指定范围。
- 与基线对比在宿主机上运行，只读结果文件：

  ```sh
  .venv/bin/python eval/compare_runs.py .runtime/eval/corpus-v3/results-v9.json \
    .runtime/eval/corpus-v3/results-v10.json --scope all
  ```

- 当前基线是语料 v4 上的 `.runtime/eval/corpus-v4/results-v15.json`（查询集 v5、k=20、文档端搜索模式、开启同义词），见[排障与案例方案 8.4](phase2/troubleshooting-and-case-design.md#84-维修类评测f2-142026-10-11)。

## 7. 账号、备份与例行检查

### 7.1 账号与 Token

账号只用于 HTTP 接口：导入接口要求 `maintain_source`，检索时有 `read_internal` 才能看到 internal 来源。命令行导入不需要账号。用 `kb_account` 管理账号，命令见[部署与验收 3.1](deployment.md#31-创建维护者和普通调用账号)：

- **新增账号**：同时传 `--permissions` 和 `--token-file`，账号不存在时创建，并写出 Token。
- **取回 Token**：对已有账号只传 `--token-file`，写出的是现有 Token，不会生成新的。
- **更换 Token（如泄露）**：先用 `--revoke-token` 吊销，旧 Token 立即失效；再用 `--token-file` 生成新的。
- **权限不能修改**：已有账号再传不同的 `--permissions` 会报 `ACCOUNT_PERMISSION_CONFLICT`，不会覆盖。需要不同权限时新建账号，再吊销旧账号的 Token。

Token 文件放在 `.runtime/` 下，权限设为 600。

### 7.2 备份与恢复

删除来源、全量重新导入或升级数据库前，先备份：

```sh
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > .runtime/backup/itxia-$(date +%F).sql
```

恢复时停掉 app，把备份导入一个空库，再启动。不要对正式项目执行 `down -v`，它会删除数据卷。

### 7.3 每次维护后的检查

1. 导入报告中 `failed` 为 0，`unregistered` 都已处理（登记类别或标 `skip`）。
2. 改了词表、参数或资料的，评测没有回归，结果已记录。
3. 改了代码或打包文件的，全量测试已通过，命令见[部署与验收第 4 节](deployment.md#4-在-docker-中运行自动测试)。
4. app 已重建，抽查一两条查询。
5. 清单、词表、查询集已提交；`.runtime/` 下的内容没有被提交。
