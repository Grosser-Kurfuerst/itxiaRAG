# 维护手册

本文写给维护知识库的人或 LLM 代理，覆盖资料导入与分类、新增类别、评测与回归、账号与备份。部署与首次验收见[部署与验收](deployment.md)。

## 0. 操作约定

所有命令在仓库根目录执行，先定义 `dc` 函数：

```sh
ITXIA_ENV="$PWD/.env.docker"
dc() { docker compose --env-file "$ITXIA_ENV" -p itxia "$@"; }
dc ps    # 应有 app（API，127.0.0.1:8000）、db（PostgreSQL，15432）、embedding（Ollama）在运行
```

规则：

- 不打印、不提交 `.env.docker`、`.env.local` 的内容。
- 不提交 `.runtime/`：快照、采集原文、正式公众号清单、Token、备份和评测结果都在其中。
- 用 `git add <文件>` 按文件名暂存，提交信息用 Conventional Commits，如 `chore(sources): 登记语雀新增文档`。
- 删除来源、全量重导、换模型前先备份（9.2）。
- 批量导入先加 `--dry-run`，`failed` 为 0 再正式导入。

## 1. 总览

| 维护对象 | 位置 | 生效方式 | 改后验证 |
| --- | --- | --- | --- |
| 语雀文档 | 清单 [itxia.toml](../sources/yuque/manifests/itxia.toml) | 重建 app 后运行 `import_yuque` | 导入报告；清单单测；评测 |
| 公众号评测 | `.runtime/eval/corpus-v1/` 下的正式清单与采集目录 | 运行 `import_wechat` | 导入报告；评测 |
| 单篇资料 | 原文 API 或标准 API | 提交即生效 | 检索抽查 |
| 文档类别 | 组合根 [components.py](../config/components.py) 等 | 改代码、重建 app、导入 | 全量测试；评测 |
| 领域词典、同义词表 | [keyword-terms.txt](../retrieval/keyword-terms.txt)、[keyword-synonyms.txt](../retrieval/keyword-synonyms.txt) | 重建 app | 评测 |
| 停用词 | [tokenization.py](../retrieval/tokenization.py) 的 `_STOPWORDS` | 改代码、重建 app | 单测与评测 |
| 检索参数 | [settings.py](../config/settings.py)、环境变量门槛 | 重建 app | 评测，写入改进记录 |
| Embedding 模型 | `.env.docker` | **全量重新导入** | 全量评测 |
| 机型规格 | [bibar.json](../products/specs/bibar.json) | 重建 app 后运行 `import_specs` | 导入报告；评测 |
| 评测集 | [queries.json](../eval/queries.json)、[recommend-queries.json](../eval/recommend-queries.json)、[llm-queries.json](../eval/llm-queries.json) | 下次评测 | 评测脚本能加载 |
| 账号与 Token | 数据库 | 立即生效 | 401／403 检查 |

- 改清单、词表、参数和代码都要重建：`dc up -d --build app`。`dc exec app` 用的是镜像里的清单和代码，改了清单不重建，导入用的还是旧清单。
- 评测命令挂载宿主机的 `eval/`、`retrieval/`、`config/`，检索改动可以先评测，确认后再重建上线。

## 2. 导入资料

### 2.1 选择导入方式

**系统不能直接接收链接**：没有按语雀或公众号链接自动抓取的接口或命令，原文 API 也不接受 URL。

| 资料 | 方式 | 命令或接口 |
| --- | --- | --- |
| IT 侠语雀公开文档 | 链接换成清单键，登记类别后批量导入 | `import_yuque` |
| 公众号评测推文 | 下载或人工保存网页，登记清单后批量导入 | `fetch_wechat`（可选）、`import_wechat` |
| 其他零散资料 | 保存正文后提交原文 | `POST /api/v1/sources/raw/` |
| 已切好父段和子块的 JSON | 提交 `ProcessedDocument` | `POST /api/v1/sources/` |

- 批量命令不校验账号；两个 API 需要有 `maintain_source` 权限的 Token（9.1）。
- 评测答案按 `entity_title`（评测）或语雀 `库/slug` 定位，经 API 导入的非评测资料不能作为评测答案。需要长期维护、参与评测的资料都走清单。

### 2.2 更新机制与导入报告

同一来源由 `source_type` 与 `canonical_locator` 确定：语雀是 `doc:<文档 ID>`（改 slug、移动目录不影响）；公众号是永久链接，没有链接时用采集文件名；API 来源由提交的值决定。

- 内容不变返回 `reused`：仍会读取原文、预处理，但不调用 Embedding、不写库；内容有变返回 `imported`，整篇替换，key 不变的父段和子块保留 ID。
- **没有删除同步**：清单删掉某篇或改成 `skip`，已入库内容不会删除，下线按 2.6。
- **没有变更通知**：定期全量重跑 `import_yuque`，有改动的自动更新。

| 报告状态 | 含义与处理 |
| --- | --- |
| `preprocessed` | 试运行成功，可以正式导入 |
| `imported`／`reused` | 已写入／内容不变 |
| `skipped` | 清单写了 `skip`，或类别没有接入流水线；确认是预期结果 |
| `unregistered` | 清单里没有这篇，按第 3 节登记类别或 `skip` |
| `failed` | 读取、预处理或保存失败；按原因修正后重跑，批次以非零状态退出 |

### 2.3 语雀文档

链接 `https://www.yuque.com/itxia/<库>/<slug>` 对应清单键 `<库>/<slug>`，去掉末尾的 `#锚点`、`?参数`。例如 `https://www.yuque.com/itxia/help/install_win10` 是 `help/install_win10`。命令匿名读取公开网页，不需要语雀 Token，只要 app 容器能访问 `www.yuque.com`；非公开文档返回 401／403 会终止整批。

**新增文档**：

1. （可选）对整个清单试运行，报告中的 `unregistered` 就是还没登记的文档：

   ```sh
   dc exec app python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml --dry-run
   ```

2. 按第 3 节判断类别，在 [itxia.toml](../sources/yuque/manifests/itxia.toml) 加条目，并同步开头注释中的篇数；所在库未登记时先加 `[collections.<库>]`：

   ```toml
   [docs."help/new_slug"]
   category = "tutorial"
   ```

3. 更新清单单测：[test_source_manifest.py](../tests/unit/test_source_manifest.py) 断言了 `len(manifest.docs) == 91` 和 `manifest.collections` 列表。`[docs]` 条目数（含 `skip`）或集合变化时同步修改；由 `path_rules` 覆盖的文档不计入条目数。

   ```sh
   .venv/bin/python -m pytest tests/unit/test_source_manifest.py -q
   ```

4. 重建 app 后试运行，`--only` 可重复：

   ```sh
   dc up -d --build app
   dc exec app python manage.py import_yuque --manifest sources/yuque/manifests/itxia.toml \
     --only help/new_slug --only article/another --dry-run
   ```

   状态应为 `preprocessed`，父段、子块数合理，警告（截图、风险、时效）符合原文。
5. 去掉 `--dry-run` 正式导入，应为 `imported`；再跑一次应为 `reused`。
6. 用新文档能回答的问题抽查检索（命令见 2.5 末尾），再按第 7、8 节评测：语料版本加 1，确认原有查询没有回归，新主题没有查询覆盖时补充查询。
7. 提交清单与单测。

**其他情况**：

- **原文更新**：直接重跑，可加 `--only 库/slug`；清单没改就不用重建。
- **改类别**：改 `category` 后按第 4、5 步执行，因流水线变化会返回 `imported`。
- **快照**：需要可复现的离线导入时，用 `--save-snapshot` 保存、`--snapshot` 导入（两者互斥），见[部署与验收 3.7](deployment.md#37-语雀网页与快照导入)。旧快照没有新登记的文档，需重新保存；快照含正文，不提交。

### 2.4 公众号评测

公众号文章不能在线批量读取，先把网页保存到本地采集目录，再离线导入。正式清单是 `.runtime/eval/corpus-v1/wechat-manifest.toml`（78 篇 `product_review`），采集目录是 `.runtime/eval/corpus-v1/capture/bibar/`，每篇一个 `<条目>.html` 加同名 `.json`。仓库中的 [bibar.toml](../sources/wechat/manifests/bibar.toml) 只是格式样例，不写正式条目。

1. **定条目名并登记**：条目名用 `<发布日期>-<简短英文名>`，入库后不要改（没有链接时它就是身份）。`entity_title` 必填，格式为“品牌 系列型号 区分后缀”，不能与已有评测重名（`grep entity_title` 正式清单核对），同系列不同配置加“酷睿版”“RTX 5070 Ti 版”等后缀：

   ```toml
   [docs."bibar/2026-09-28-laiku-gt16"]
   category = "product_review"
   metadata = { entity_title = "联想 来酷GT 16 酷睿版" }
   ```

2. **保存网页**，二选一：
   - **自动下载**：在正式清单登记账号和文章的标题、日期（条目须已在 `docs` 中），用 `fetch_wechat` 经搜狗微信搜索下载：

     ```toml
     [connector.accounts]
     bibar = "笔吧评测室"

     [connector.articles]
     "bibar/2026-09-28-laiku-gt16" = { title = "未来已来！聊一款新上市的主流游戏本", date = "2026-09-28" }
     ```

     ```sh
     dc run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD/.runtime/eval/corpus-v1:/import" app \
       python manage.py fetch_wechat --manifest /import/wechat-manifest.toml --capture /import/capture \
       --only bibar/2026-09-28-laiku-gt16
     ```

     `--user` 让文件归当前用户。账号、标题（忽略全角半角）、日期都一致才算找到，找不到或多篇一致记为失败；已下载的跳过，`--force` 重下；遇到验证码整批终止，稍后重跑续传。下载结果的链接缺少 `sn`，打不开但身份稳定。每期同名的文章通常搜不到，需人工保存。
   - **人工保存**：浏览器保存完整网页为 `capture/bibar/<条目>.html`，再写同名 `.json` 旁注：

     ```json
     {"title": "未来已来！聊一款新上市的主流游戏本", "url": "https://mp.weixin.qq.com/s?__biz=xxxx&mid=2654664745&idx=1", "date": "2026-09-28", "author": "作者", "account": "笔吧评测室"}
     ```

     `title` 必填。`url` 用含 `__biz`、`mid`、`idx` 的永久链接，或短链接 `https://mp.weixin.qq.com/s/xxxx`，两种身份不互通，同一篇不要换用；只有 `timestamp`、`signature` 的临时链接会报错；没有合适链接就不写，以文件名作身份。
3. **试运行与导入**：

   ```sh
   # 试运行；去掉 --dry-run 即正式导入，不加 --only 时处理全部条目
   dc run --rm --no-deps -v "$PWD/.runtime/eval/corpus-v1:/import:ro" app \
     python manage.py import_wechat --manifest /import/wechat-manifest.toml --capture /import/capture \
     --only bibar/2026-09-28-laiku-gt16 --dry-run
   ```

   `ENTITY_TITLE_REQUIRED` 表示漏了 `entity_title`。
4. **补规格**：按下方[规格填写](#规格填写)在规格文件中补一条记录并导入。机型推荐只返回有规格的机型，D 类答案也由规格文件按规则生成，不补就不会被推荐、不会计为答案。[attributes.json](../eval/attributes.json) 已冻结，不再更新。
5. **评测**：语料版本加 1，核对 D、G 类并跑回归（第 7、8 节）。

#### 规格填写

本节可以整节交给有仓库和 Docker 执行权限的 LLM 代理（如 Claude Code、Codex）：由它导出、填写、合并、校验，经维护者确认后导入并提交。没有执行权限的聊天模型只能做第 2 步，其余步骤由维护者执行。代理先读第 0 节的操作约定。

维护者给出以下一种任务：

- **新增机型**：为库中有评测、规格文件中还没有 `key` 的机型各补一条完整记录，通常在导入新评测之后。
- **补字段**：为已有记录补指定的空字段，如 `cpu`、`ram_gb`、`ram_upgradable`、`storage_gb`。只写值为 `null` 的指定字段及其 `evidence`，不改已有的非空值；发现已有值与原文不符时列入核对清单，由维护者决定是否修改。

边界：只读本节、规格文件、[工具定义](../products/tool-definitions.md)和第 1 步导出的评测正文，不读语雀内部文档、`.runtime/` 中的其他内容和 env 文件；不改代码和 [attributes.json](../eval/attributes.json)。

**1. 导出评测正文。** 评测正文是公众号文章预处理后存入库中的评测父段，父段标题就是 `entity_title`。导入规格时按这份正文校验引用，所以只根据它填写，不用网页原文。导出后每行一篇，`key` 为机型，`date` 为评测日期：

```sh
mkdir -p .runtime/specs
dc exec -T app python manage.py shell --no-imports -c "
import json
from catalog.models import ContextUnit
for c in ContextUnit.objects.filter(source__document_schema='product_review').select_related('source'):
    print(json.dumps({'key': c.title, 'date': str(c.source.source_date), 'body': c.body}, ensure_ascii=False))
" > .runtime/specs/reviews.jsonl
```

**2. 填写。** 一次处理一台：读完该机型的整篇正文，按下面的规则填写，不凭记忆补值。

填写规则：

- 一台机器一条记录。`key` 与清单中的 `entity_title` 完全一致，`brand` 取它的第一个词；子品牌 ROG、ThinkPad、红米单列（如“联想 ThinkPad X14”记为 ThinkPad，“小米 REDMI Book”记为红米），以便按品牌筛选时不漏机。只有这三个子品牌，ThinkBook、拯救者等系列仍记为联想。
- 先从评测原文取值；原文有多个配置时只取评测机。
- 原文缺失的字段，可以联网搜索补充，优先官网参数页，其次电商官方旗舰店详情页、其他评测媒体，配置必须与评测机一致。价格只补官方首发价或建议零售价，`price_date` 写该价格的日期；续航不从别处补，见下表。查不到的填 `null`，不推算。
- 规格字段在 `evidence` 中附引用，键为字段名，一句话能证明几个相关字段时写在其中一个下即可。引用逐字复制，不改写、不拼接：
  - 来自评测原文的，值直接写引用，如 `"weight_kg": "重量 2.23kg"`。导入时会自动检查它确实出现在评测正文中。
  - 联网补充的，写成 `{"source": "网页链接", "quote": "网页上的原文"}`。导入时只检查格式，内容由人点开链接核对。

| 字段 | 口径 |
| --- | --- |
| `price_cny`、`price_kind`、`price_date` | 单位元。取配置表的“参考售价”，`price_kind` 为 `reference`：这是笔吧给出的参考到手价，可能已含国补、平台补贴或券，照取不改。配置表没有参考售价时按正文取，`price_kind` 为 `launch`（首发）、`reference`（售价、建议零售）或 `subsidy`（只有补贴价）；尚未开售时，原文给出预测价或区间才填（区间取下限，`predicted`），只说“至少××元”填 `null`。首发价等其他价格写进 `note`。日期原文没写时用评测日期 |
| `weight_kg` | 机身重量，不含适配器。二合一的重量和价格都按评测机的实际形态（含键盘的套装）取，裸机数据写进 `note` |
| `screen_inch`、`panel` | 英寸；`panel` 为 `oled`、`lcd`（IPS 等液晶屏）或 `miniled` |
| `cpu` | 完整型号，不写品牌，如 `Core Ultra 9 275HX`、`Ryzen 7 H 255`、`Apple M4`；原文只写“Ultra 9 386H”时补上 `Core` |
| `has_dgpu`、`gpu` | 只有核显时为 `false`、`null`；独显写成 `RTX 5060`、`RTX 5070Ti`，Ti 紧跟数字 |
| `ram_gb`、`ram_upgradable` | 单位 GB；有内存插槽或可更换模块（如 LPCAMM2）为 `slots`，板载为 `soldered` |
| `storage_gb` | 单位 GB，1TB 记为 1024 |
| `battery_hours` | 只取笔吧“日常应用仿真”的成绩，单位小时，分钟除以 60 后四舍五入保留两位小数（8 小时 29 分钟记为 8.48）。只认这个测试项名称，“中高负载仿真”等其他项填 `null`。官网续航和其他测试的口径不同，不能用来补 |
| `is_gaming` | 有 RTX 独显时默认为 `true`；原文或厂商定位为创作本（设计师本）、全能本、商务本或双屏本时为 `false`；没有独显为 `false` |
| `ports` | 8 个布尔值，接口介绍里没提到的为 `false`：`usb_a`；`usb_c`（含雷电、USB4）；`video_out`（有 HDMI、DP 或支持视频输出的 USB-C）；`hdmi`；`rj45`；`card_reader`（SD 或 microSD）；`thunderbolt`（雷电或 USB4）；`oculink`（联想 TGX 接口即 OCuLink） |
| `ports_text` | 原文介绍接口的段落，逐字复制；评测没有介绍接口时，复制补充来源中的接口说明 |
| `extra` | 可选，只用 `refresh_hz`、`resolution`、`battery_wh` 三个键 |
| `note` | 计价、称重口径等说明，没有就写空字符串 |

示例（联想 来酷GT 16 酷睿版，评测日期 2026-09-28）。原文只有参考售价和国补价，没有日常应用仿真续航：

```json
{
  "key": "联想 来酷GT 16 酷睿版", "brand": "联想",
  "price_cny": 5999, "price_kind": "reference", "price_date": "2026-09-28",
  "weight_kg": 2.23, "screen_inch": 16.0, "panel": "lcd",
  "cpu": "Core 5 205H", "has_dgpu": true, "gpu": "RTX 3050",
  "ram_gb": 16, "ram_upgradable": "slots", "storage_gb": 512,
  "battery_hours": null, "is_gaming": true,
  "ports": {"usb_a": true, "usb_c": true, "video_out": true, "hdmi": true,
            "rj45": true, "card_reader": false, "thunderbolt": false, "oculink": false},
  "ports_text": "接口方面，机身左侧有两个USB-A 5Gbps以及一个3.5mm音频接口；机身右侧有两个USB-A 5Gbps接口；机身后侧有一个USB-C 10Gbps（支持100W PD充电和DP1.4独显视频输出）、HDMI2.1 FRL（独显输出）、电源接口以及RJ45网口（1GbE）。",
  "extra": {"refresh_hz": 165, "resolution": "1920x1200"},
  "evidence": {
    "price_cny": "参考售价5999元",
    "weight_kg": "重量 2.23kg",
    "screen_inch": "16英寸 1920×1200分辨率 100%sRGB色域 165Hz刷新率 IPS雾面屏",
    "cpu": "Core 5 205H 处理器",
    "gpu": "RTX 3050 4GB 独立显卡（95W）",
    "ram_gb": "16GB DDR4 3200MT/s 内存",
    "ram_upgradable": "机器有两个内存插槽",
    "storage_gb": "512GB 固态硬盘",
    "is_gaming": "正式成为新时代的主流价位游戏本"
  },
  "note": "原文另有国补后到手价5099.15元"
}
```

**3. 合并。** 把记录写入 [products/specs/bibar.json](../products/specs/bibar.json)：新增的记录插入列表，补字段只改对应记录的指定字段和 `evidence`，不动其他记录。文件按 `key` 排序，字段顺序同示例，格式与 `json.dumps(records, ensure_ascii=False, indent=1)` 加末尾换行一致。出现规格文件中没有的显卡型号或品牌时，按[工具定义 3.1 节](../products/tool-definitions.md#31-可选值)更新可选值与显卡档次。

**4. 校验。** 以下都通过才进入下一步：

```sh
.venv/bin/python -m pytest tests/unit/test_products.py -q   # 字段格式、key 唯一、工具定义与规格文件一致
dc up -d --build app                                        # import_specs 读取镜像中的规格文件
dc exec app python manage.py import_specs --file products/specs/bibar.json --dry-run
```

试运行报告应为 `failed=0`、`unlinked=0`，`created`／`updated` 恰好是本次处理的机型，其余为 `unchanged`。有任何一条字段或引用校验不通过，整个文件都不写库：引用不在正文中时回到正文重新逐字复制；“失去关联”表示找不到 `key` 对应的评测，通常是 `key` 与 `entity_title` 拼写不一致。

再逐台自查：价格是否取自配置表的参考售价，续航是否来自日常应用仿真，`ports` 与 `ports_text` 是否一致，`is_gaming` 是否符合原文定位。

**5. 交维护者确认。** 合入规格文件即视为已审核，代理在此停下，向维护者提交核对清单：每台机型填了哪些字段；拿不准的取值及理由；联网补充的字段及链接；已有值与原文不符之处。维护者确认或指出修改后再继续。

**6. 导入与提交。** 去掉 `--dry-run` 正式导入。改了价格、重量、尺寸、显卡、续航、面板、接口、品牌等推荐条件用到的字段时，按 8.2 节“规格文件、推荐逻辑”一行跑回归；只补 CPU、内存、硬盘时不影响评测，可以跳过。最后按文件名暂存规格文件（以及改过的工具定义）并提交，如 `chore(products): 补充 5 台机型规格`。

规则试填记录（2026-10-13）：选 10 台覆盖预测价、无价格、国补价、双屏、有独显的全能本、二合一、无续航成绩、OCuLink 与网口的机型，由只看本节和评测原文的 LLM 盲填（不联网），与规格文件比对。品牌、尺寸、面板、独显、显卡、续航、接口 10/10 一致；价格 6/10、价格口径 7/10、重量 9/10、游戏本 9/10。差异来自规则未写明的口径：配置表“参考售价”常为国补或券后价（星耀14、战66、MacBook Air 13），“至少××元”的预估价（枪神10 Plus），二合一裸机与套装（Surface Pro 11），“专业性能轻薄本”是否算游戏本（幻14 Air）。上表已按规格文件的既有口径补写这些规则，并补充 CPU 写法、LPCAMM2、TGX 与续航换算；现有数据无需修改。试填由与维护者同类的模型完成，换用其他模型时宜再抽查几台。

### 2.5 单篇资料（API）

适合不在语雀、也不是笔吧评测的零散资料。先把正文存成本地文件，用脚本生成请求体以免手工转义，再提交：

```sh
TOKEN_FILE="$PWD/.runtime/maintainer.token"
mkdir -p .runtime/manual
python3 - <<'PY' > .runtime/manual/request.json
import json, pathlib
content = pathlib.Path(".runtime/manual/article.md").read_text(encoding="utf-8")
print(json.dumps({
    "source": {"source_type": "manual", "canonical_locator": "manual:win11-skip-network",
               "visibility": "public", "source_url": "https://example.com/original"},
    "preprocess": {"schema": "tutorial", "version": 1},
    "raw": {"content": content, "media_type": "text/markdown",
            "metadata": {"title": "Win11 跳过联网激活", "source_date": "2026-09-01",
                         "collection_path": ["系统安装"]}},
}, ensure_ascii=False))
PY
curl -sS --fail-with-body -w '\nHTTP %{http_code}\n' \
  -H "Authorization: Token $(cat "$TOKEN_FILE")" -H 'Content-Type: application/json' \
  --data-binary @.runtime/manual/request.json http://127.0.0.1:8000/api/v1/sources/raw/
```

| 字段 | 规则 |
| --- | --- |
| `source.source_type` | 小写字母开头，可含数字和下划线，如 `manual` |
| `source.canonical_locator` | 唯一标识，最多 200 字；以后更新必须用同一个值，否则变成两份，建议记在 `.runtime/manual/` |
| `source.visibility` | `public` 或 `internal`（只有 `read_internal` 账号能检索到） |
| `preprocess` | `{schema, version}`，取值见 3.1 |
| `raw.media_type` | `text/html`、`text/markdown`、`text/plain`、`text/x-yuque-markdown`；UTF-8，请求不超过 2 MiB |
| `raw.metadata` | `title`；`source_date`（`YYYY-MM-DD`，未知不填）；评测必填 `entity_title`，多机型填 `entity_headings`；可选 `collection_path`（最多 10 项，拼进检索前缀） |

返回 `{source_id, context_ids, reused}`。`ENTITY_TITLE_REQUIRED` 是评测缺机型名，`SEMANTIC_UNIT_TOO_LARGE` 是某节超预算、需在原文补小标题，`503` 是模型未配置。详见[文档预处理第 6 节](phase1/preprocessing.md#6-原文导入-api)。

标准 API 的格式见样例 [basic.json](../fixtures/iteration1/basic.json) 和[部署与验收 3.3](deployment.md#33-导入标准化合成样本)，日常很少用到。

**检索抽查**（通用）：

```sh
curl -sS --fail-with-body \
  -H "Authorization: Token $(cat "$TOKEN_FILE")" -H 'Content-Type: application/json' \
  -d '{"query":"Win11 安装时怎么跳过联网","top_k":5}' http://127.0.0.1:8000/api/v1/search/ \
  | python3 -c "import json,sys; [print(c['title']) for c in json.load(sys.stdin)['contexts']]"
```

### 2.6 下线或删除来源

没有删除命令。先备份，再查出来源，确认后删除；父段和子块级联删除：

```sh
dc exec app python manage.py shell -c "
from catalog.models import KnowledgeSource as S
qs = S.objects.filter(source_type='yuque', title='要下线的标题')
print(list(qs.values_list('id', 'canonical_locator', 'title')))
# 确认无误后：print(qs.delete())
"
```

删除后同步：清单条目改为 `skip` 并写原因；修正 [queries.json](../eval/queries.json) 中指向它的答案；删除的是评测时，从规格文件删除该机型并重新导入规格（`import_specs` 会删除文件中没有的机型）。

### 2.7 更换 Embedding 模型

地址、模型、维度、revision 或 query prefix 任一改变，旧向量都不能用：备份 → 改 `.env.docker` 并重建 app → 按 2.3、2.4 不加 `--only` 全量重导 → 全量评测，语料版本加 1。

## 3. 分类与清单

### 3.1 现有类别

清单的 `category` 决定预处理流水线，映射在 [components.py](../config/components.py) 的 `YUQUE_CATEGORY_PIPELINES`、`WECHAT_CATEGORY_PIPELINES`：

| 平台 | 类别 | schema@版本 | 父段切法 | 判定标准与典型文档 |
| --- | --- | --- | --- | --- |
| 语雀 | `tutorial` | `tutorial@1` | 按章节树，超长下钻、过短合并 | 按步骤完成一件**已知要做**的事：装系统、改用户名、连校园网 |
| 语雀 | `knowledge` | `knowledge@1` | 同上 | 解释概念、比较、速查表、FAQ：激活详解、C 盘文件夹、硬件科普 |
| 语雀 | `tool_card` | `tool_card@1` | 单工具整篇一个父段；合集按工具小节 | 介绍软件的用途、下载、注意事项，标题多为“用途：工具名” |
| 语雀 | `troubleshooting` | `troubleshooting@1` | 同教程 | 从**故障现象**出发逐步排查，常带风险分级：蓝屏排查、网络问题 |
| 语雀 | `case` | `experience_case@2` | 整篇一个父段 | 记录**一次具体事件**的现象、原因、解决 |
| 公众号 | `product_review` | `product_review@1` | 一台机型一个父段 | 一篇评测一台机器（多机型需 `entity_headings`） |
| 公众号 | `purchase_guide` | `purchase_guide@1` | 预算段与推荐卡 | 选购指南；2026-10-12 已从库中删除，当前不导入 |

`experience_case@1`（按 `##` 切分）只供原文 API 使用。策略细节见[文档预处理第 3 节](phase1/preprocessing.md#3-内容结构策略)。

### 3.2 如何判断类别

按顺序判断，命中即停：

1. **不导入**：写 `skip` 和原因。已有原因：`索引导航`、`已废弃`、`仅含链接或附件`、`说明或前言`、`内容过少`、`内容过时`、`非维修参考主题`；重复副本写 `duplicate` 并用 `canonical` 指向保留的那篇。
2. **工具**：主体是介绍软件本身 → `tool_card`。
3. **案例**：只讲一次具体的事，有明确机型、时间或经历 → `case`。
4. **排障**：从“出了什么问题”出发定位原因 → `troubleshooting`。
5. **知识**：以解释、比较、查表为主，没有贯穿全文的操作流程 → `knowledge`。
6. **教程**：主体是操作步骤 → `tutorial`。

易混情况：标题含“指南”的，目标明确是教程、从故障出发是排障；【日常维修】前缀讲通用方法的是排障（如 `article/kbg5vc`）；一篇只能有一个类别，按主体判断，评测标注可以跨类别。拿不准时选最接近的类别并在提交说明写理由，不要为此新建类别。逐篇依据见[第一批需求分析附录](phase1/yuque-ingestion/requirements-analysis.md#附录第一批文档清单初稿)。

### 3.3 清单语法

清单是 TOML，由 [manifest.py](../sources/manifest.py) 校验，写错时命令启动即失败并指出字段：

```toml
version = 2                    # 固定为 2
source_type = "yuque"          # 公众号清单为 wechat

[connector]
group = "itxia"                # 语雀团队标识，必须且只能有这一项

[collections.help]             # 库名即链接中 itxia/ 后面那段；公众号为账号目录
visibility = "public"          # public 或 internal，库内文档默认继承

[[path_rules]]                 # 可选，按语雀目录统一分类
collection = "help"
path_prefix = ["IT侠常用工具大全"]   # 1～10 项
category = "tool_card"

[docs."help/install_win10"]    # 单篇登记，键为 <库>/<slug>
category = "tutorial"
visibility = "internal"        # 可选，覆盖库的可见性

[docs."article/partition-resize"]
skip = "duplicate"             # 不导入必须写原因
canonical = "help/partition-resize"   # 只用于 skip

[docs."bibar/2026-09-28-laiku-gt16"]   # 公众号清单
category = "product_review"
metadata = { entity_title = "联想 来酷GT 16 酷睿版" }   # 只用于 category 条目
```

- `[docs]` 优先于 `path_rules`，多条规则匹配时取最长前缀。
- 每个 `[docs]` 条目必须且只能写 `category` 或 `skip`；`category` 必须在 [yuque/connector.py](../sources/yuque/connector.py) 或 [wechat/connector.py](../sources/wechat/connector.py) 的 `CATEGORIES` 中；键中的库必须已登记。
- `metadata` 只能是文本、数字、布尔、数组和表，日期写成文本，不能覆盖 `yuque`、`wechat` 平台字段。
- 新增库要同步清单单测的集合列表（2.3 第 3 步）。

## 4. 新增文档类别

### 4.1 是否需要

| 情况 | 做法 |
| --- | --- |
| 结构与现有某类相同，只是主题不同 | 不加类别 |
| 想单独统计，但切分方式与现有某类相同 | 新增清单类别并映射到现有 schema，如 `"faq": ("knowledge", 1)`，只做 4.2 第 1、2 步 |
| 现有切分会拆开完整答案或混入无关内容 | 新增 schema，做 4.2 全部步骤 |
| 改变已有 schema 的切分结果 | 注册新版本（如 `experience_case@2`），映射改指向新版本，旧版本不改 |

先用现有类别试运行几篇样本，看父段是否完整、长度是否合适再决定。完整先例见[排障与案例方案](phase2/troubleshooting-and-case-design.md)：样本分析（第 2 节）、设计（第 3 节）、测试与实施（第 5、6 节）、验收（第 8 节）。

### 4.2 代码改动

以语雀类别 `<cat>`、schema `<schema>@1` 为例：

1. 把 `<cat>` 加入 [yuque/connector.py](../sources/yuque/connector.py) 的 `CATEGORIES`（公众号改 [wechat/connector.py](../sources/wechat/connector.py)）。
2. 在 [components.py](../config/components.py) 的 `YUQUE_CATEGORY_PIPELINES` 加 `"<cat>": ("<schema>", 1)`。映射到未注册的 schema 时导入报 `skipped`。
3. 结构策略优先复用，见[文档预处理第 5 节](phase1/preprocessing.md#5-扩展与步骤编排)：只调父段上限、合并规则时，在 [sections.py](../ingestion/sections.py) 新增 profile（参考 `TUTORIAL`、`TROUBLESHOOTING`、`CASE`）传给 `SectionedDocumentStrategy` 或 `WholeDocumentStrategy`；结构确实不同时实现新策略 `build(blocks, raw) -> list[SemanticContext]`，不调用模型。
4. 在 `components.preprocessors()` 注册：`registry.register("<schema>", 1, pipeline("<schema>", 策略, [增强步骤...], image_warning=screenshot_warning))`。增强步骤从 `CalloutWarningStep`、`TimeExpressionStep`、`SourceDateNoticeStep`、`ToolIdentityStep`、`RetrievalPrefixStep` 中选；版本不是 1 时传 `version=`。
5. 评测报告：[metrics.py](../eval/metrics.py) 的 `SCHEMA_NAMES` 加中文简称，[recall_eval.py](../eval/recall_eval.py) 的 `LABEL_PREFIXES` 加报告前缀。文档不来自语雀或公众号时，`resolve_alias` 无法定位答案，需另行扩展。

### 4.3 测试

单测不能访问真实数据库、网络或模型。参照排障与案例补齐：

- 策略单测（[test_sections.py](../tests/unit/test_sections.py) 或 [test_preprocessing_strategies.py](../tests/unit/test_preprocessing_strategies.py)）：合成 Markdown 验证父段边界、标题、长度上限、警告位置。
- 组合根单测（参考 [test_enrichment_steps.py](../tests/unit/test_enrichment_steps.py) 的 `test_yuque_later_categories_map_to_registered_repair_schemas`）：新类别映射到已注册的 schema。
- 清单单测：按 2.3 第 3 步更新条目数。
- 集成测试（参考 [test_yuque_ingestion.py](../tests/integration/test_yuque_ingestion.py)）：合成快照导入一篇，验证父段数、schema 和警告。
- 全量测试，命令见 8.4。

### 4.4 导入验收

1. 登记文档、重建 app、试运行：新文档全部 `preprocessed`，其他文档父段数不变。
2. 正式导入，再跑一次全部 `reused`。
3. 抽查 2～4 篇：父段是否完整回答一个问题，标题和章节路径是否正确，警告是否落在对应父段。列出某篇的父段：

   ```sh
   dc exec -T app python manage.py shell -c "
   from catalog.models import ContextUnit
   for c in ContextUnit.objects.filter(source__metadata__yuque__book='help', source__metadata__yuque__slug='new_slug').order_by('ordinal'):
       print(c.ordinal, repr(c.title), len(c.body), c.warnings)
   "
   ```

4. 结果写进本次方案文档（参照排障与案例方案第 8 节）。

### 4.5 扩充评测集

1. 把新 schema 加入 [queries.json](../eval/queries.json) 的 `scopes.all`。
2. 问题风格与现有类别不同时新增类别字母（已用 A～G、T、X、K、U、R，见 7.1），并加入 [compare_runs.py](../eval/compare_runs.py) 的 `CAT_COLUMNS`，对比表才有这一列。
3. 每篇新文档至少写 1 条查询（7.3）。
4. 重新核对旧标注：G 类负例可能有了答案；新文档能回答的已有问题要补进 `rel`。
5. 按第 8 节运行、补标，并在[召回评测第 9 节](phase1/yuque-ingestion/retrieval-evaluation.md#9-初步评测执行记录)记录语料与查询集版本、新类别结果、原有类别的变化与原因。

### 4.6 文档同步与提交

| 文档 | 要改的内容 |
| --- | --- |
| [文档预处理](phase1/preprocessing.md) | 第 3 节策略表、第 5 节流水线顺序、第 6 节已注册 schema |
| [README](../README.md) | 语雀导入一节的类别说明 |
| 本文 | 3.1 类别表、3.2 判定顺序、7.1 类别字母 |
| [召回评测](phase1/yuque-ingestion/retrieval-evaluation.md) | 9.2 语料、9.3 查询集与类别、新的执行记录 |
| [召回改进记录](phase2/retrieval-improvement-log.md) | 第 1 节基线说明 |
| 阶段需求 | 对应功能状态，如[第二阶段需求](phase2/requirements.md) |

建议分三次提交：`feat(ingestion)` 流水线代码、测试与预处理文档；`chore(sources)` 清单与清单单测；`test(eval)` 查询集、评测脚本与评测文档。

## 5. 检索词表

三个词表只作用于关键词路，查询时实时分词，改动不需要重新导入。先看问题和原文被切成什么词：

```bash
.venv/bin/python -c "from retrieval.tokenization import tokenize, tokenize_for_search; print(tokenize('问题原文')); print(tokenize_for_search('文档中的说法'))"
```

| 现象 | 处理 |
| --- | --- |
| 两边已有相同的词 | 不用改，问题在排序或标注 |
| 品牌、系列名被切成单字 | 加进领域词典 |
| 两边是完全不同的说法 | 加进同义词表 |
| 问句虚词干扰排序 | 调停用词 |

评测结果每条都有 `keyword_terms`（关键词路实际检索的词），可直接和原文对照。

- **领域词典**：每行一个词。只收 jieba 会切成单字的品牌、系列名和术语（如“拯救者”“灵耀”）；不收能切成有意义词语的词（如收了“游戏本”，问“游戏”就匹配不到）。新系列可从公众号清单的 `entity_title` 中找。
- **同义词表**：每行一组可互换的说法，空格分开，`#` 后注明来源查询，如 `流氓软件 垃圾软件  # U09：…`。只收评测或真实提问中遇到、分词解决不了的错配；组内双向等价，不放上下位关系；按子串匹配，太短太通用的（“电脑 / 笔记本”）不收；每个词至少两个字（启动和单测 `test_bundled_synonym_table_is_valid` 都会检查）；控制在几十条以内。
- **停用词**：写在代码里，改动要补单测、跑全量测试和评测。现在会移除“能”“用”“多久”等，删减前确认不影响“能加内存吗”“续航多久”这类问题。

上线：可以攒几条改动一起，按第 8 节对比基线，看目标查询是否改善、其他查询是否因误触发变差、新进前 5 的父段是否要补标；在[召回改进记录](phase2/retrieval-improvement-log.md)记录改动、效果和是否保留；提交后重建 app。

## 6. 检索参数

| 参数 | 位置 | 当前值 |
| --- | --- | --- |
| `RETRIEVAL_RRF_K` | settings.py | 20 |
| `RETRIEVAL_RRF_WEIGHTS` | settings.py | `{}`（不加权） |
| `RETRIEVAL_KEYWORD_SEARCH_MODE` | settings.py | `document` |
| `RETRIEVAL_KEYWORD_SYNONYMS` | settings.py | `True` |
| `RETRIEVAL_MIN_COSINE`、`RETRIEVAL_MIN_BM25` | 环境变量 | 不过滤、0 |

先用评测参数 `--rrf-k`、`--vector-weight`、`--search-mode`、`--synonyms` 试，不改配置；满足[改进方案](phase2/retrieval-improvement-plan.md)的采纳条件和 8.2 的底线后再改默认值，同步[改进记录](phase2/retrieval-improvement-log.md)和[技术设计 5.1](phase1/phase1-technical-design.md)，重建 app。

## 7. 评测集

[queries.json](../eval/queries.json) 含 `scopes`（范围名 → `document_schema` 列表，`reviews` 只含评测，`all` 含全部）、`aliases`（答案别名）、`specs`（D 类标注用的规格文件，相对查询集的路径）和 `queries`。用脚本修改时保持原格式，避免无关差异：

```python
json.dump(spec, f, ensure_ascii=False, indent=1); f.write("\n")
```

### 7.1 类别字母

| 字母 | 含义 | 字母 | 含义 |
| --- | --- | --- | --- |
| A | 型号 + 属性，如“GT 16 噪音多大” | G | 无答案（负例），`rel` 为空 |
| B | 简写、别名，如“7000P 噪音” | T | 语雀教程 |
| C | 口语，不用原文用词 | X | 跨来源：带机型名，答案在教程或评测 + 教程 |
| D | 按条件找机器，答案由属性表生成 | K | 语雀知识 |
| E | 两台对比，两个答案都要进前 5 | U | 语雀工具条目 |
| F | 同名区分：同系列不同配置或相近型号 | R | 维修：排障与案例 |

A～F 的答案在评测中。各版本数量与例子见[召回评测 9.3](phase1/yuque-ingestion/retrieval-evaluation.md#93-查询集与标注)。

### 7.2 查询与别名格式

```json
{"id": "R01", "cat": "R", "q": "电脑经常死机蓝屏，应该按什么顺序排查", "rel": ["语雀:蓝屏排查顺序"], "facts": [], "origin": "manual"}
```

| 字段 | 说明 |
| --- | --- |
| `id` | 类别字母 + 两位序号，按类别续写，不重用已删除的编号 |
| `q` | 用户口吻的问题 |
| `rel` | 答案别名列表；G 类为空 |
| `facts` | 答案子块须包含的原文片段，如 `["55.4dB"]`，用于统计答案子块名次 |
| `origin` | `manual` 或 `real`（真实提问脱敏后） |
| `pair` | E 类写 `true` |
| `constraints` | D 类写条件，不写 `rel`；可用键见 [recall_eval.py](../eval/recall_eval.py) 的 `CONSTRAINTS` |

别名有两种：

- **评测**：短名 → `entity_title`，如 `"GT16": "联想 来酷GT 16 酷睿版"`。
- **语雀**：以 `语雀:` 开头，值为 `{"doc": "库/slug", "titles": [父段标题...]}`。省略 `titles` 表示整篇；标题须与库中父段标题完全一致，含 ` > ` 拼接的章节路径，可用 4.4 的命令列出。“教程:”“排障:”等前缀只用于报告中未标注的父段，别名不要用。

评测器加载时检查每个别名都能唯一定位父段；小节改标题、机型改名或来源被删除时会报断言错误，按提示更新别名。

### 7.3 新增查询与标注核对

1. 先不看检索结果，按用户口吻写问题，避免照抄原文。
2. 在原文中找能直接回答的父段，可按关键词搜全库：

   ```sh
   dc exec -T app python manage.py shell -c "
   from catalog.models import ContextUnit
   for c in ContextUnit.objects.filter(body__icontains='关键词').select_related('source'):
       y = c.source.metadata.get('yuque') or {}
       print(c.source.document_schema, y.get('book'), y.get('slug'), repr(c.title))
   "
   ```

3. 直接回答问题的父段算答案，可以有多个、可以跨类别；只有背景、只有外链、只在列表中顺带提及、讲其他型号的不算。G 类负例要用上面的命令确认确实没有答案。
4. 真实提问先脱敏，再标 `"origin": "real"`，不提交未脱敏原文。
5. 校验 JSON 合法、编号不重复：

   ```sh
   python3 -c "import json,collections; d=json.load(open('eval/queries.json')); c=collections.Counter(q['id'] for q in d['queries']); print(len(d['queries']), [k for k,v in c.items() if v>1])"
   ```

**资料变化后**：每次扩充语料都要重新核对 D、G 类（新评测补属性表，负例可能有了答案）；新资料能回答已有问题时要补标，否则计为排序下降；资料删除或改标题时按报错修正别名。

### 7.4 版本

| 对象 | 何时加 1 | 当前 |
| --- | --- | --- |
| 语料版本 | 资料增删、分段规则或模型变化 | v5：171 个来源、442 个父段、1514 个子块 |
| 查询集版本 | 查询或标注变化（含补标；D 类标注随规格文件变化） | v7：170 条，164 条有答案 |
| 结果编号 | 每次产生新的基线或实验结果 | 基线 v18，下一个 v19 |

版本号记录在[召回评测第 9 节](phase1/yuque-ingestion/retrieval-evaluation.md#9-初步评测执行记录)和[改进记录第 1 节](phase2/retrieval-improvement-log.md#1-记录规则)，不写在 `queries.json` 中。不同查询集或语料版本的结果不直接比较。

## 8. 评测与回归

### 8.1 运行与对比

评测只读正式库，全量约 3～6 分钟，结果放在 `.runtime/eval/corpus-v<语料版本>/`：

```sh
mkdir -p .runtime/eval/corpus-v5
dc run --rm --no-deps -v "$PWD/eval:/app/eval:ro" -v "$PWD/retrieval:/app/retrieval:ro" \
  -v "$PWD/config:/app/config:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app app \
  python eval/recall_eval.py eval/queries.json /data/corpus-v5/results-v19.json \
  > .runtime/eval/corpus-v5/report-v19.txt
.venv/bin/python eval/compare_runs.py .runtime/eval/corpus-v5/results-v18.json \
  .runtime/eval/corpus-v5/results-v19.json --scope all
```

- 不传参数时用 settings 的配置跑全部范围；`--scope all` 只跑指定范围。
- 报告第一行是检索配置和语料规模，核对规模与预期一致才能确认导入完整。
- 挂载只覆盖检索代码；改了预处理、切分代码要先重建 app 并重新导入。D 类标注读镜像中的规格文件，改了规格文件也要先重建。
- 对比输出汇总表（全部、A～F、D、T、X、K、U、R 的混合指标，召回／排序失败条数，奇偶分半 MRR 变化）和逐条变化（名次变化的查询、“新进前5未标注”的父段）。两份结果的查询或标注不同时拒绝对比。
- 改了规格文件、条件判定或推荐服务时，另跑推荐评测（镜像中的 `products/` 要先重建），输出 D 类链路集合核对与 P@5、软条件排序 nDCG@5 和结论附带率，方法见[评测 9.13](phase1/yuque-ingestion/retrieval-evaluation.md#913-d-类改读规格文件与推荐接口评测p152026-10-12)：

  ```sh
  dc run --rm --no-deps -v "$PWD/eval:/app/eval:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app app \
    python eval/recommend_eval.py eval/queries.json eval/recommend-queries.json /data/corpus-v5/recommend-v3.json
  ```

- 改了[工具定义](../products/tool-definitions.md)时，用对话模型跑上层 LLM 模拟评测（镜像中的 `products/` 要先重建），输出工具选择、条件换算差异和端到端 P@5，方法见[评测 9.14](phase1/yuque-ingestion/retrieval-evaluation.md#914-上层-llm-模拟评测p322026-10-13)。模型通过 `EVAL_LLM_BASE_URL`、`EVAL_LLM_MODEL`、`EVAL_LLM_API_KEY` 配置，只在当前 shell 设置，不写入 env 文件：

  ```sh
  dc run --rm --no-deps -v "$PWD/eval:/app/eval:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app \
    -e EVAL_LLM_BASE_URL -e EVAL_LLM_MODEL -e EVAL_LLM_API_KEY app \
    python eval/llm_eval.py eval/queries.json eval/llm-queries.json /data/corpus-v5/llm-v1.json
  ```

**当前基线** `.runtime/eval/corpus-v5/results-v18.json`：查询集 v7、语料 v5（2026-10-12 重导），k=20、不加权、文档端搜索模式、开启同义词；`all` 范围混合 Hit@1／Hit@5／MRR@10 为 0.77／0.95／0.852，见[评测 9.12](phase1/yuque-ingestion/retrieval-evaluation.md#912-评测子块记录栏目名后重导p112026-10-12)与 [9.15](phase1/yuque-ingestion/retrieval-evaluation.md#915-规格文件补齐-cpu内存与硬盘p232026-10-13)。重新编码会使向量有细微差异（9.12），比较时注意区分。

### 8.2 按改动类型回归

| 改动 | 做法 | 通过条件 |
| --- | --- | --- |
| 词表、停用词、检索参数或代码 | 同一查询集、同一语料对比基线 | 通用底线，加[改进方案](phase2/retrieval-improvement-plan.md)中该项的条件 |
| 新增或更新资料 | 先用旧查询集在新语料上跑，对比基线 | 有答案查询 Hit@5 不下降、不新增召回失败；MRR 下降逐条解释（多为新资料竞争，能回答的补标） |
| 新增类别 | 先按上一行，再加新查询建立新基线 | 同上；新类别每篇至少一条查询，结果写入评测文档 |
| 更换模型 | 全量重导后全量评测 | 与旧模型对比，结论写入评测文档 |
| 只改评测集 | 重跑当前配置作为新基线 | 评测器能加载，变化都来自标注 |
| 规格文件、推荐逻辑 | 召回评测对比基线（D 类标注变化时按“只改评测集”重跑作为新基线），再跑推荐评测 | D 类链路集合全部相同；软条件排序与结论附带率不下降，变化写入评测文档 |

**通用底线**（[改进记录第 1 节](phase2/retrieval-improvement-log.md#1-记录规则)）：全部 MRR@10 提升至少 0.01；A～F 类 Hit@5、MRR@10 下降不超过 0.02；D 类 Hit@5 不下降、MRR@10 下降不超过 0.02；按编号奇偶分两半，MRR@10 都提升。每次只改一个变量。

### 8.3 补标与新基线

对比脚本只比较标注相同的结果，所以先在旧标注下对比得出结论，再更新标注重跑：

1. 逐条看“新进前5未标注”的父段，按 7.3 判断，是答案就加进 `rel`，需要时新增别名。
2. 语料或类别变化较大时，按三路前 10 池化复核（方法见[评测 9.11](phase1/yuque-ingestion/retrieval-evaluation.md#911-池化补标与新基线f2-012026-10-12)，脚本见附录）。
3. 用新标注重跑，查询集版本和结果编号各加 1。
4. 在评测文档第 9 节写方法、补标清单和新旧指标；更新[改进记录第 1 节](phase2/retrieval-improvement-log.md#1-记录规则)和本文 8.1 的基线。
5. 提交 `queries.json`、规格文件和文档，结果文件不提交。

### 8.4 测试

只改资料、清单、查询集时跑清单单测即可；改了代码要跑全量测试（[部署与验收第 4 节](deployment.md#4-在-docker-中运行自动测试)）：

```sh
.venv/bin/python -m pytest tests/unit -q     # 离线单测，不需要数据库和模型
dct() { DB_PORT=25432 docker compose --env-file "$ITXIA_ENV" -p itxia-tests --profile test "$@"; }
dct run --build --rm test && dct down -v     # Docker 中的全量测试
```

已有本地测试库时也可以用 `make test`，见[项目测试规则](unit-testing-guidelines.md)。

## 9. 账号、备份与例行检查

### 9.1 账号与 Token

账号只用于 HTTP 接口，命令行导入不需要。`maintain_source` 允许调用两个导入接口；`read_internal` 允许检索 internal 来源，没有时只能看到 public。

账号用 `kb_account` 管理，输出只有 `account_id=<编号> token_revoked=<True/False>`，不打印 Token。Token 先写到容器内，再复制到宿主机 `.runtime/`；复制后要删除容器中的副本，否则下次写同名文件会因内容不同报 `TOKEN_FILE_CONFLICT`。先定义：

```sh
NAME=maintainer   # 账号名：字母、数字和 @.+-_，最多 150 字
fetch_token() {
  dc cp "app:/tmp/$NAME.token" ".runtime/$NAME.token" && dc exec app rm "/tmp/$NAME.token" \
    && chmod 600 ".runtime/$NAME.token"
}
```

| 操作 | 命令 |
| --- | --- |
| 新建账号 | `dc exec app python manage.py kb_account --username "$NAME" --permissions maintain_source,read_internal --token-file "/tmp/$NAME.token" && fetch_token` |
| 取回现有 Token | `dc exec app python manage.py kb_account --username "$NAME" --token-file "/tmp/$NAME.token" && fetch_token` |
| 吊销（停用） | `dc exec app python manage.py kb_account --username "$NAME" --revoke-token` |
| 更换 | 先吊销，再执行“取回”，会生成新 Token |

- `--permissions` 写法：维护者 `maintain_source,read_internal`，只检索公开资料 `''`，能检索内部资料 `read_internal`。
- 取回时如果账号不存在，会新建一个没有权限的账号，先核对账号名。
- 吊销后旧 Token 立即失效（401）；不再发放即为停用。
- **权限不能修改**：给已有账号传不同的 `--permissions` 会报 `ACCOUNT_PERMISSION_CONFLICT`。需要不同权限时，用新账号名新建、把新 Token 交给调用方，再吊销旧账号。

查看现有账号：

```sh
dc exec -T app python manage.py shell -c "
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
for u in get_user_model().objects.order_by('username'):
    print(u.username, sorted(u.user_permissions.values_list('codename', flat=True)), '有 Token' if Token.objects.filter(user=u).exists() else '无 Token')
"
```

验证：

```sh
TOKEN_FILE="$PWD/.runtime/$NAME.token"
# 不带 Token：401
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' \
  -d '{"query":"续航"}' http://127.0.0.1:8000/api/v1/search/
# 带 Token 检索：200
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Token $(cat "$TOKEN_FILE")" \
  -H 'Content-Type: application/json' -d '{"query":"续航"}' http://127.0.0.1:8000/api/v1/search/
# 提交空请求体：有 maintain_source 返回 400，无权限 403，已吊销 401
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Token $(cat "$TOKEN_FILE")" \
  -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:8000/api/v1/sources/
```

Token 文件只放在 `.runtime/` 下、权限 600，不要粘贴到提交、文档或对话中。

### 9.2 备份与恢复

```sh
mkdir -p .runtime/backup
dc exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > .runtime/backup/itxia-$(date +%F).sql
```

恢复时停掉 app，把备份导入空库再启动。不要对正式项目执行 `down -v`，它会删除数据卷。

### 9.3 每次维护后的检查

1. 导入报告 `failed` 为 0，`unregistered` 都已登记类别或标 `skip`。
2. 改了清单的，清单单测通过、app 已重建。
3. 改了资料、词表或参数的，评测没有回归，结果和版本号已记录。
4. 改了代码的，全量测试通过。
5. 抽查一两条查询。
6. 清单、词表、查询集、属性表和文档已提交，`.runtime/` 没有被提交。

## 附录：池化候选清单脚本

列出每条查询在混合、关键词、向量三路前 10 中尚未标为答案的父段，供人工判断。脚本不在仓库中，需要时保存为被忽略的 `.runtime/eval/pool.py`：

```python
"""列出每条查询三路前 10 个父段中尚未标为答案的候选。参数：查询集 输出文件 [类别,类别]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app/eval")
import recall_eval as ev  # noqa: E402  导入时完成 Django 初始化
from config import components  # noqa: E402
from contracts.types import SearchRequest  # noqa: E402

POOL = 10
spec_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
cats = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
spec = json.loads(spec_path.read_text(encoding="utf-8"))
corpus = ev.load_corpus(spec, spec_path.parent)
embedder = components.embedding_provider()
collector = components.recall_collector(embedder)
pipeline = components.post_recall_pipeline()

lines = []
for item in spec["queries"]:
    if "constraints" in item or (cats and item["cat"] not in cats):
        continue  # D 类按属性表生成标注，不池化
    scopes = ["all", "reviews"] if item["cat"] in "ABCEFG" else ["all"]
    pool = {}
    for name in scopes:
        scope = ev.build_scope(spec["scopes"][name], embedder.space_id)
        routes = collector.collect(item["q"], scope, ev.CANDIDATES_PER_ROUTE)
        fused = pipeline.run(SearchRequest(item["q"], scope, ev.TOP_PARENTS), routes)
        orders = {"H": [c.context_id for c in fused.contexts],
                  "K": ev.parent_order(routes.routes.get("keyword", [])),
                  "V": ev.parent_order(routes.routes.get("vector", []))}
        for route, order in orders.items():
            for rank, cid in enumerate(order[:POOL], 1):
                pool.setdefault(cid, {}).setdefault(f"{name[0]}{route}", rank)
    rel_ids = {cid for alias in item.get("rel", []) for cid in corpus.alias_ctx[alias]}
    lines.append(f"\n## {item['id']} [{item['cat']}] {item['q']}  rel={item.get('rel', [])}")
    for cid, ranks in sorted(pool.items(), key=lambda kv: min(kv[1].values())):
        if cid in rel_ids:
            continue
        c = corpus.contexts[cid]
        rank_text = " ".join(f"{k}{v}" for k, v in sorted(ranks.items()))
        lines.append(f"- [{c.source.document_schema}] {ev.yuque_doc(c) or ''} | {c.title} | {rank_text} | "
                     + " ".join(c.body.split())[:160])
out_path.write_text("\n".join(lines), encoding="utf-8")
```

运行方式与评测相同，最后一个参数可选部分类别：

```sh
dc run --rm --no-deps -v "$PWD/eval:/app/eval:ro" -v "$PWD/retrieval:/app/retrieval:ro" \
  -v "$PWD/config:/app/config:ro" -v "$PWD/.runtime/eval:/data" -e PYTHONPATH=/app app \
  python /data/pool.py eval/queries.json /data/corpus-v5/pool-v16.md R,K
```

名次标记如 `aH3`：首字母是范围（`a` 为 all，`r` 为 reviews），第二个字母是路线（`H` 混合、`K` 关键词、`V` 向量），数字是名次。
