# 后续批次技术方案：排障指南与单案例记录

本文给出语雀排障指南（`troubleshooting`，10 篇）与单案例记录（`case`，9 篇）的接入方案，对应[二期需求](requirements.md) F2-12、F2-13，评测对应 F2-14。逐篇名单见[需求分析附录](../phase1/yuque-ingestion/requirements-analysis.md#附录后续批次与不导入清单)。解析、章节树、父段规划和子块生成沿用[第一批技术方案](../phase1/yuque-ingestion/technical-design.md)第 4、5 节，本文只写差异。**状态：已实现，19 篇已导入开发环境并完成抽查和维修类评测（2026-10-11），结果见第 8 节。**

## 1. 结论

| 类别 | 处理方式 | schema | 依据 |
| --- | --- | --- | --- |
| 单案例记录 | 整篇一个父段，小标题只作子块断点 | 新增 `experience_case@2` | 按标题切分会把现象和解决方案拆进不同父段，用现象检索拿不到解决方案；整篇最长约 3700 字，可以容纳 |
| 排障指南 | 沿用教程的章节树、合并规则和参数（父段上限 3000 字） | 新增 `troubleshooting@1` | 一个排障步骤或一个问答基本对应一个父段；下调上限会把章节导语中的风险层级与其步骤拆开 |

已确定不做的事：

- 不改 `experience_case@1`。它是原文 API 已公开的按 `##` 切分的版本，按 schema 版本规则另注册 `@2`，`@1` 保留。
- 排障不新增导读或风险层级的专用步骤。风险层级随章节留在同一父段，见 3.2。
- 暂不提取正文中加粗的“警告：／注意：”。它们仍在父段正文中，只是不进 warnings 字段，不影响召回。
- 排障的前置知识（如“1、前置知识”）不带到后续步骤，留到回答生成阶段处理。
- 不处理 `windows_problem_cheatsheet` 的“标题带 * 表示有风险”约定，只有这一篇使用。

## 2. 样本分析

样本为 2026-10-08 快照中的 19 篇正文，使用提交 `89a9968` 的代码离线试切，不写库。字数为不计空白的正文长度。

### 2.1 单案例记录

现有教程规则切出 29 个父段，例如 `ghrq7ikst4cce451` 切成“症状 162 字／解决方案 67 字／方案来源 110 字”三段。整篇一个父段的试算：

| slug | 主题 | 正文字数 | 子块数 |
| --- | --- | --- | --- |
| ghrq7ikst4cce451 | 开机出现 EARLY EXIT ON FAILURE | 315 | 1 |
| mogtov | Dell 机型麦克风失效 | 451 | 3 |
| vegchy | 安装程序提示缺少介质驱动 | 487 | 2 |
| syr9fw | 老电脑的驱动问题（无标题） | 617 | 2 |
| geve3g | 官方维修点也需小心 | 773 | 3 |
| yhsqeg | ms-settings 问题 | 983 | 4 |
| fqhg6o | UWP 应用报错 0x8007007e | 1278 | 5 |
| ggwbb1 | 一类 U 盘病毒的处理方法 | 2424 | 9 |
| rzqnsh | Python import 不是有效的 Win32 程序 | 3746 | 5 |

- 父段标题为文档标题（清洗后），多为症状描述；子块检索文本由父段标题和子块正文组成，见 [evidence_input](../../contracts/types.py)，后段子块也带症状。
- `rzqnsh` 大半是报错 traceback，拆成两个约 1500 字的子块；报错原文正好能被关键词检索命中，保留。
- 不足 120 字的短子块并入前一个子块，例如 `vegchy` 的“解决方案”并入“问题现象”子块。父段是整篇，返回内容不受影响。
- 9 篇写于 2019～2023 年，需要来源日期提示。

### 2.2 排障指南

按现有教程规则（上限 3000、导语阈值 150、空节点阈值 30）切出 49 个父段：

| slug | 父段数 | 父段正文字数 |
| --- | --- | --- |
| find_vendor | 7 | 63～652 |
| kbg5vc | 4 | 139～438 |
| cam_mic_not_work | 8 | 230～1586 |
| ms_office_problems | 3 | 82～625 |
| network_alter | 4 | 42～354 |
| network_problem | 2 | 357～1782 |
| nju_network | 3 | 225～881 |
| nju_wlan_qa_pro_plus_max_ultra | 6 | 87～3111 |
| o365_qa | 5 | 88～900 |
| windows_problem_cheatsheet | 7 | 407～2919 |

- 问答型文档的短问题单独成父段，例如 `o365_qa` 的五个问题；只有约 15 字的玩笑回答“四”并入“三”。
- `nju_wlan_qa_pro_plus_max_ultra` 的“零、想一想自己到底会不会上校园网”含 5 个“问：”，正文不计标题时略低于 3000 字，整节一个父段；子块仍按问题断开。
- 父段上限的对比（10 篇合计父段数）：

  | 上限 | 父段数 | 主要变化 |
  | --- | --- | --- |
  | 3000 | 49 | 各章完整 |
  | 2500 | 57 | 拆开 nju_wlan“零”的问答、cheatsheet 第 2 章 |
  | 2000 | 61 | 另拆开 cheatsheet 第 4 章 |
  | 1500 | 70 | 另拆开 cam_mic“2、系统应用检查”的 6 个检查项 |

  cheatsheet 每章导语写有“工作环境恢复耗时／问题恶化可能性／问题分析维修耗时”。上限 2000 时第 4 章拆成 4.1～4.4，“4.3 *收集蓝屏信息”与“问题恶化可能性：蓝屏循环，但可逆”分到不同父段，违反 F2-13“高风险警告与对应步骤在同一父段”，因此保持 3000。
- 警告：`:::warning` 提示块已由 CalloutWarningStep 提取，位于第一个标题前的成为文档警告（如 `find_vendor`），其余成为所在父段警告（如 `nju_network`）。正文加粗的“警告：／注意：”共 5 处（cheatsheet 4、ms_office_problems 1），按第 1 节暂不提取。

## 3. 设计

### 3.1 单案例：`experience_case@2`

- 把 [ToolCardStrategy](../../ingestion/sections.py) 中“全部内容作为虚拟根导语”的逻辑提为 `WholeDocumentStrategy(SectionedDocumentStrategy)`：`_tree` 返回 `SectionNode(None, 0, blocks)`，规划结果为一个父段，标题与 `section_path` 为文档标题，图片占位过滤、子块生成与定位沿用基类。
- `ToolCardStrategy` 改为继承 `WholeDocumentStrategy`，只在 `tool_collection` 时改用 `build_tree`，行为不变。
- 新增参数 `CASE = SectionProfile("experience_case", 0, 0, 500, 120)`：父段上限与合并阈值不起作用；子块目标 500 字、短子块阈值 120 字，与教程相同。
- [SourceDateNoticeStep](../../ingestion/enrichment.py) 的文案参数化，默认值保持工具条目现有文案；案例使用“本案例最后更新于 {日期}，系统版本、软件界面与处理办法可能已变化”。
- 流水线：

  ```text
  experience_case@2 : Parse → Structure(WholeDocument[CASE]) → CalloutWarning → TimeExpression → SourceDateNotice → RetrievalPrefix → Chunk → Build → Validate
  ```

  使用截图提示文案“原文含未转写的截图，操作界面以原文链接为准”。与其他 schema 一样支持 `text/html`、`text/markdown` 和 `text/x-yuque-markdown`。

### 3.2 排障指南：`troubleshooting@1`

- 参数 `TROUBLESHOOTING = replace(TUTORIAL, content_type="troubleshooting")`，表达“规则与教程相同，内容类型不同”。内容类型与 schema 名用于 F2-15 按 `document_schema` 识别维修类父段。
- 策略为 `SectionedDocumentStrategy(TROUBLESHOOTING)`，增强步骤与教程相同：

  ```text
  troubleshooting@1 : Parse → Structure(Sectioned[TROUBLESHOOTING]) → CalloutWarning → TimeExpression → RetrievalPrefix → Chunk → Build → Validate
  ```

- 全局导读：第一个标题前的内容按现有规则处理，150 字以上单独成父段（如 cheatsheet 的导读），其中的 `:::warning` 进入文档警告。
- 风险层级：不新增步骤。章节导语与其小节在上限 3000 内同属一个父段。

### 3.3 组合根与类别映射

[config/components.py](../../config/components.py)：

```python
YUQUE_CATEGORY_PIPELINES = {
    "tutorial": ("tutorial", 1), "knowledge": ("knowledge", 1), "tool_card": ("tool_card", 1),
    "troubleshooting": ("troubleshooting", 1), "case": ("experience_case", 2),
}
```

- `troubleshooting@1` 加入教程、知识的注册循环。
- `experience_case@2` 单独注册，`experience_case@1` 不变。组合根的 `pipeline()` 增加 `version` 参数，传给 BuildDocumentStep，使输出的 schema 版本与注册项一致。
- 清单已登记 19 篇的类别，不需要修改；接入后报告不再出现“未接入”。

## 4. 契约变化

| 项 | 变化 | 兼容性 |
| --- | --- | --- |
| 预处理 schema | 新增 `troubleshooting@1`、`experience_case@2` | 新增；`experience_case@1` 行为不变 |
| `content_type` | 新增 `troubleshooting`；`experience_case` 新增整篇一父段的来源 | 新增 |
| ToolCardStrategy | 改为继承 WholeDocumentStrategy | 行为不变，第一批工具条目重新导入应全部 `reused` |
| SourceDateNoticeStep | 文案可配置 | 默认文案不变 |
| 存储、检索、原文 API 接口 | 无 | — |

## 5. 测试与验收

- 单元测试：
  - 整篇一个父段：多级标题只作子块断点，标题与 `section_path` 为文档标题；无标题文档同样一个父段。
  - 工具合集仍按叶子章节成父段（回归）。
  - 日期提示的默认文案与案例文案。
  - 排障：短问答单独成父段，章节导语与小节在上限内同一父段，`:::warning` 落在对应父段。
  - 组合根注册了两个新 schema，语雀类别映射指向它们。
- 集成测试：用合成的排障与案例语雀快照各导入一篇，经原文 API 链保存，验证父段数、schema 和警告。
- 真实样本验收：
  1. 用 `import_yuque --save-snapshot --dry-run` 重新保存快照，确认包含 19 篇正文。
  2. 试运行：19 篇 `preprocessed`，0 失败；已导入的 74 篇父段不变。
  3. 正式导入开发库，预计新增排障约 49 个父段、案例 9 个父段；随后重跑应全部 `reused`。
  4. 抽查 `windows_problem_cheatsheet`（风险层级与警告）、`nju_wlan_qa_pro_plus_max_ultra`、`fqhg6o`、`rzqnsh`。
- 评测（F2-14）：
  1. 先不看检索结果，为每篇至少写 1 条维修类问题，约 19 条，再查原文标注。
  2. 全量评测，确认现有 T、K 类不因新语料退步。结果写回评测文档。

  实际结果（见 8.4）：原有查询 Hit@5 不变，T、K、U 类 MRR 下降，属于相近主题的正常竞争，分析见[评测 9.6](../phase1/yuque-ingestion/retrieval-evaluation.md#96-结论与遗留问题)。结果已写回[评测文档](../phase1/yuque-ingestion/retrieval-evaluation.md)第 9.1～9.5 节。

## 6. 实施步骤

1. 案例流水线：WholeDocumentStrategy、CASE、日期提示文案、`experience_case@2` 与映射，补测试并同步文档。
2. 排障流水线：TROUBLESHOOTING、`troubleshooting@1` 与映射，补测试并同步文档。
3. 重新保存快照、试运行、正式导入并抽查，结果写入本文第 8 节，概览只记摘要。
4. F2-14 维修类评测，结果写入本文 8.4。

每步完成后单独提交。步骤 1、2 的测试互相依赖（导入测试中两类同时由“未接入”变为可导入），合并为一次提交。

## 7. 风险与已知限制

- 样本分析基于 2026-10-08 快照，正式导入前以重新保存的快照试运行为准。
- `nju_wlan_qa_pro_plus_max_ultra`“零”节约 3000 字、含 5 个问答，父段偏长。
- 正文加粗警告不进入 warnings 字段；前置知识不随后续步骤返回。
- 新语料与现有查询的答案竞争：Hit@5 不变，T、K、U 类 MRR 下降，见 8.4。

## 8. 实施与验收结果

### 8.1 实现

提交 `a451c24` 按第 3 节实现：

- [WholeDocumentStrategy](../../ingestion/sections.py)、`CASE`、`TROUBLESHOOTING`，ToolCardStrategy 改为继承 WholeDocumentStrategy；
- [SourceDateNoticeStep](../../ingestion/enrichment.py) 文案模板可配置；
- [组合根](../../config/components.py) 注册 `troubleshooting@1`、`experience_case@2` 并加入语雀类别映射。

全量测试 509 条通过。

### 8.2 试运行与正式导入（2026-10-11）

1. 重新保存快照：`import_yuque --save-snapshot --dry-run` 得到 preprocessed=93、skipped=26、unregistered=0、failed=0，共保存 93 篇正文。19 篇正文与 2026-10-08 分析快照逐字节一致。
2. 用该快照在开发环境正式导入：imported=19、reused=74、failed=0。第一批 74 篇全部 `reused`，说明 ToolCardStrategy 重构与新映射不影响已有文档。立即重跑，结果为 reused=93。
3. 库中新增规模与第 2 节的试切结果一致：

   | schema | 来源 | 父段 | 子块 |
   | --- | --- | --- | --- |
   | `troubleshooting@1` | 10 | 49 | 105 |
   | `experience_case@2` | 9 | 9 | 34 |

   语雀来源合计 93 篇：父段 364、子块 864。

### 8.3 抽查

| 文档 | 结果 |
| --- | --- |
| `windows_problem_cheatsheet` | 共 7 个父段：导读和第 0～5 章各 1 个。每章的“工作环境恢复耗时／问题恶化可能性／问题分析维修耗时”都与本章步骤在同一父段。“4.3 *收集蓝屏信息”与“问题恶化可能性：蓝屏循环，但可逆”同在第 4 章（2322 字）。第 5 章的加粗“警告：重置过程会清除部分数据”留在正文中，不进 warnings，与第 1 节的决定一致 |
| `nju_wlan_qa_pro_plus_max_ultra` | 6 个父段。“零”节 3111 字、7 个子块，带该节 `:::warning`；“三、问一问信息化中心”只有 87 字，但有标题，单独成父段 |
| `fqhg6o` | 整篇 1 个父段（1284 字）、5 个子块：导语与“背景补充：UWP”合为 1 个；“正文”拆为 2 个，短的 Solution A 并入后一个；Solution B、C 各 1 个。文档警告为截图提示和“本案例最后更新于 2019-10-14…” |
| `rzqnsh` | 整篇 1 个父段（3748 字）、5 个子块。traceback 拆成两个约 1500 字的子块，问题原因、解决方法和参考资料各成一个子块 |

用无权限账号和真实 Embedding 检索抽查。这些查询是对照原文写的，只用来验证接入，不计入评测：

| 查询 | 结果 |
| --- | --- |
| 电脑蓝屏怎么用WinDbg分析 | 第 1 为 cheatsheet > 4、WinDbg定位蓝屏问题，前 5 中另有 3 个 cheatsheet 章节 |
| 爱剪辑导致浏览器没有声音 | 第 1 为 UWP应用报错0x8007007e问题详解（案例） |
| Python import 提示不是有效的Win32程序 | 第 1 为对应案例 |
| 校园网连上了但是打不开网页 | 前 5 全部为排障指南，第 1、2 为南京大学校园网使用异常修复指南 |
| U盘里文件变成快捷方式 | 第 2 为一类U盘病毒的处理方法，第 1 为知识 FAQ 的输入／输出章节 |
| 安装Windows时提示缺少介质驱动程序 | 第 1 为对应案例 |

### 8.4 维修类评测（F2-14，2026-10-11）

**查询集 v5**：在 v4（142 条）上新增维修类问题 28 条，并把 G06 改为 R29，R 类共 29 条。查询集合计 170 条，其中 164 条有答案、6 条无答案。每条问题先按用户口吻写出，再对照原文标注答案父段。19 篇排障指南和案例记录都至少有 1 条查询；答案也可以是教程或知识父段。

- 评测脚本：`all` 范围加入 `troubleshooting`、`experience_case`；对比表增加 R 列。
- 前缀约定：新别名与已有别名一样用“语雀:”前缀；“排障:”“案例:”只用于报告中未标注的父段。
- G06“打印机驱动怎么装”改为 R29。`kbg5vc` 第三节给出了从 `.inf` 安装打印机驱动的方法，这条查询在新语料中已经有答案。
- G09“笔记本键盘进水了怎么办”仍为无答案。第 1 名 `geve3g` 记录的是售后不当处理，只顺带提到“进水应先清理主板再开机”，不算处理指南。

**语料 v4**：语料 v3 加 19 篇维修类文档，共 172 个来源、480 个父段、1552 个子块。默认配置不变（k=20、不加权、搜索模式只用于文档端、同义扩展开启）。

**补标**：首轮（v13）后按三路前 10 复核，修正如下：

| 查询 | 修正 |
| --- | --- |
| R14 世纪互联版 Office 365 怎么登录 | `o365_qa` 第五节只有一个外链，不算答案，改为 `double_o365`“一、网页端” |
| R06、R11 | 补入知识“网络常见问题”，它有“QQ/微信能上网、浏览器打不开”和硬件故障临时联网的处理 |
| R12、R15、R18、R19、R27 | 分别补入麦克风硬件检查、`double_o365` OneDrive 冲突、`find_vendor` 驱动安装注意事项、`find_vendor` 观察包装、售后注意事项 |
| K08 连上校园网 WiFi 但打不开校外网站 | 补入 `nju_wlan` 零节和 `network_problem` 第 2 节，二者都有逐步排查 |

其他旧查询新进前 5 的维修父段多为外链（如 T16 报修、U20 的 Office 卸载）或顺带提及（如 K01 资费），没有补标。

**结果**（v15，`all` 范围，混合检索，Hit@1／Hit@5／MRR@10）：

| 类别 | 混合 | 关键词 | 向量 |
| --- | --- | --- | --- |
| R（29 条） | 0.90／1.00／0.937 | 0.79／0.93／0.862 | 0.86／1.00／0.917 |
| 全部（164 条） | 0.76／0.95／0.844 | 0.68／0.88／0.770 | 0.78／0.91／0.840 |

R 类没有第 1 名的只有 3 条：

- R01（蓝屏排查顺序）第 3，前两名是同篇的 WinDbg 和事件查看器章节；
- R14 第 3，第 1 名是只有外链的 `o365_qa` 第五节；
- R19 第 2，第 1 名是 `find_vendor` 中只提出问题的“二、尝试连接”。

R06 的排障答案第 9，靠知识父段进入前 5，所以仍列在分来源排序失败中。

**原有查询**：v15 与 v12（语料 v3）对比。两份结果都去掉 R 类、G06 和 K08，其余 140 条标注相同。对比工具要求两份结果的查询集一致，所以先过滤再对比：

| 运行 | 全部 H@5／MRR | A～F H@5／MRR | D MRR | T MRR | K MRR | U MRR |
| --- | --- | --- | --- | --- | --- | --- |
| v12 | 0.933／0.841 | 0.865／0.780 | 0.451 | 0.921 | 0.940 | 0.829 |
| v15 | 0.933／0.822 | 0.865／0.778 | 0.446 | 0.909 | 0.905 | 0.788 |

- Hit@5 各类均不变，`reviews` 范围逐条一致。
- 8 条名次下降，没有查询跌出前 5。其中 4 条丢失第 1 名：K29、K30、U06、U20 降到第 2 或第 3，排在前面的是蓝屏、系统文件修复、Office 版本等维修父段。
- 负例 top1 余弦最大值仍为 0.674（G08）。

K、U 类 MRR 分别下降约 0.035、0.041，原因是新语料参与竞争，检索配置没有变化。此后检索改进以 v15 为基线。下降的 5 条带维修词，维修类偏好（F2-15）只会让它们排得更低，应作为 F2-15 不能退步的对照，见[评测 9.6](../phase1/yuque-ingestion/retrieval-evaluation.md#96-结论与遗留问题)。

结果在 `.runtime/eval/corpus-v4/`：`results-v13～15.json`、`report-v13～15.txt`，原有查询的对比在 `compare-old-v12-v15.txt`。过滤后的结果是 `results-v12-old-queries.json` 和 `results-v15-old-queries.json`。v13 是补标前的结果，v14 是 G06 转为 R29、R 类补标后的结果，v15 是 K08 补标、别名改用“语雀:”前缀后的结果。v13、v14 使用改名前的别名，不能直接与 v15 对比。
