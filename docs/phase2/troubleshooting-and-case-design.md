# 后续批次技术方案：排障指南与单案例记录

本文给出语雀排障指南（`troubleshooting`，10 篇）与单案例记录（`case`，9 篇）的接入方案，对应[二期需求](requirements.md) F2-12、F2-13，评测对应 F2-14。逐篇名单见[需求分析附录](../phase1/yuque-ingestion/requirements-analysis.md#附录后续批次与不导入清单)。解析、章节树、父段规划和子块生成沿用[第一批技术方案](../phase1/yuque-ingestion/technical-design.md)第 4、5 节，本文只写差异。**状态：方案已确定，未实现。**

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
- `experience_case@2` 单独注册，`experience_case@1` 不变。
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

## 6. 实施步骤

1. 案例流水线：WholeDocumentStrategy、CASE、日期提示文案、`experience_case@2` 与映射，补测试并同步文档。
2. 排障流水线：TROUBLESHOOTING、`troubleshooting@1` 与映射，补测试并同步文档。
3. 重新保存快照、试运行、正式导入并抽查，结果写入[概览](../phase1/yuque-ingestion/overview.md)。
4. F2-14 维修类评测。

每步完成后单独提交。

## 7. 风险与已知限制

- 样本分析基于 2026-10-08 快照，正式导入前以重新保存的快照试运行为准。
- `nju_wlan_qa_pro_plus_max_ultra`“零”节约 3000 字、含 5 个问答，父段偏长。
- 正文加粗警告不进入 warnings 字段；前置知识不随后续步骤返回。
- 新语料会与现有校园网、激活等查询的答案竞争，可能改变 T、K 类名次，需按第 5 节评测确认。
