# 优化文档汇总

本文汇总与检索、推荐和 Agent 输出优化相关的文档，说明每份文档管什么、目前到了哪一步。本文只做导航和概述，不维护数值和契约：指标、口径和实施细节都以各源文档为准，源文档更新后只需在这里同步状态一句话。（2026-10-24 建立）

**更新规则**：优化有进展时同步本文，规则同时写在 [AGENTS.md](../AGENTS.md)。新增相关文档时加入第 2 节；某项完成或得出不采纳结论时，从第 4 节移到第 3 节；产生新基线时在第 5 节加一行；第 6 节的不一致修正后删除对应条目。

## 1. 优化流程与文档分工

每项优化按同一流程推进，每一步有固定的记录位置：

| 步骤 | 记录位置 |
| --- | --- |
| 提出需求、确定范围 | [总体需求](requirements.md)第 6 节、各阶段需求文档 |
| 建立评测、发现问题 | [召回效果评测](phase1/yuque-ingestion/retrieval-evaluation.md)（历史）、[评测扩充](phase1/evaluation-expansion.md)（当前） |
| 设计改进方案、定采纳条件 | [召回改进方案](phase2/retrieval-improvement-plan.md)、[机型规格库方案](phase3/product-spec-design.md)、[MCP 服务方案](phase3/mcp-server-design.md) |
| 逐项实验、记录取舍 | [召回改进记录](phase2/retrieval-improvement-log.md)、[机型规格库实施记录](phase3/product-spec-log.md) |
| 采纳后更新基线、日常回归 | [维护手册](maintenance.md)第 5～8 节 |
| 新暴露的问题和待办 | [第五阶段待改进清单](phase5/improvement-backlog.md) |

## 2. 文档清单

### 2.1 需求与待办

| 文档 | 内容 | 当前状态 |
| --- | --- | --- |
| [总体需求](requirements.md) | 第 6 节列出 P1 各项（查询预处理、场景策略、检索质量、可选重排、上层接入等）的进度 | 评测、RRF、分词、同义词已采纳；真实提问、按来源召回、型号不符标记、重排未完成 |
| [第二阶段需求](phase2/requirements.md) | 第 3.1 节评测基础（F2-01～F2-03），第 3.2 节检索质量（F2-04～F2-11） | F2-01、F2-02、F2-04～F2-06 已完成；F2-07、F2-08 移入第三阶段并完成；F2-03 待维护者提供，F2-09～F2-11、F2-15 未实施 |
| [第三阶段需求](phase3/requirements.md) | 选购条件改由上层 LLM 识别，规格库与推荐接口 | 已完成；deepseek-flash 同模型重跑待执行 |
| [第四阶段需求](phase4/requirements.md) | 导入能力缺口；F4-03 例行更新，F4-04～F4-07 视失败样本再做 | F4-01、F4-02 已完成，其余未开始或暂缓 |
| [第五阶段待改进清单](phase5/improvement-backlog.md) | 扩充评测暴露的问题 P-01～P-07、任务 I5-01～I5-14、待决策事项 D-01～D-03 | 待实施；已按 v2 Agent 重跑补充，P-01～P-06 均复现。建议先做 I5-01（复合拆装问题的召回实验） |

### 2.2 评测体系

| 文档 | 内容 | 当前状态 |
| --- | --- | --- |
| [召回效果评测](phase1/yuque-ingestion/retrieval-evaluation.md) | 早期评测方案、查询集 v1～v8 与第 9 节逐次运行记录，包括失败模式诊断（9.6）和改进建议（9.7） | 历史文档，旧口径（容量归一化的 P@5／R@10）不能与 strict-v2 比较 |
| [召回与 Agent 输出评测扩充](phase1/evaluation-expansion.md) | 360 题召回、60 题真实 Agent 评测、strict-v2 指标、证据核验和评委规则。第 1～3 轮为 expanded-v1，第 4 轮为 expanded-v2 | **当前评测基准**。v2 召回与 Agent 60 题都已跑完（Agent 40/60，评委 gpt-5.6-sol） |
| [机型规格库方案](phase3/product-spec-design.md)第 8 节 | 推荐评测设计：D 类允许集合核对、软条件排序 nDCG | D 类 29/29 允许集合一致 |
| [评委规则](../eval/agent-judge.md) | Agent 输出评审的冻结规则 | 有误判和漏检记录，见待改进清单 P-07 |

评测脚本都在 [eval/](../eval/)：召回 `recall_eval.py`、对比 `compare_runs.py`、用例校验 `cases.py`、推荐 `recommend_eval.py`、上层工具选择 `llm_eval.py`、真实 Agent `agent_eval.py`。

### 2.3 召回优化

| 文档 | 内容 | 当前状态 |
| --- | --- | --- |
| [召回改进方案](phase2/retrieval-improvement-plan.md) | 问题与证据表、各改进项（RRF、分词、同义词、条件解析、按来源召回、重排、型号不符标记）的做法和采纳条件、实施顺序、暂不做的事 | 2.1、2.2、3.1～3.3 已实现；3.4 移入第三阶段；3.5～3.7 未实施 |
| [召回改进记录](phase2/retrieval-improvement-log.md) | 每项实验的参数、结果和是否采纳，以及基线版本总览 | 登记到 R3 和 v19 基线；expanded 系列基线记在评测扩充文档 |
| [首期技术设计](phase1/phase1-technical-design.md)第 5.2～5.5 节 | 路线门槛、可编排后处理流水线、重排接入位置等检索契约 | 重排只保留接入位置 |
| [技术选型](technology-selection.md)第 2～4 节 | 可借鉴的开源方案、保留的论文线索、何时重新选型（pgvector、数据库 BM25、reranker 等） | 参考资料；pgvector 与持久化倒排索引等子块数量达到约 5000 时再考虑 |

### 2.4 推荐与上层 LLM 优化

| 文档 | 内容 | 当前状态 |
| --- | --- | --- |
| [机型规格库方案](phase3/product-spec-design.md) | 用结构化规格库和推荐接口替代检索回答 D 类，分阶段计划 | 已实施 |
| [机型规格库实施记录](phase3/product-spec-log.md) | 推荐评测、软条件排序（按偏好 0.612，只按日期 0.257）、上层 LLM 模拟评测、gpt-5.6-terra 基线、persona 接入验证 | 工具选择 169/170，条件换算 16/18 |
| [MCP 服务方案](phase3/mcp-server-design.md) | 工具 schema 由 pydantic 生成，第 6 节为评测与工具定义文档的改动 | 已实现；只在 mock 宿主上验证过 |
| [工具定义](../products/tool-definitions.md) | 上层 LLM 的提示词、参数口径和示例 | 待补拆装安全、时效、型号与适用范围边界和复合检索规则（I5-04） |

### 2.5 操作手册

[维护手册](maintenance.md)中与优化相关的是第 5 节检索词表、第 6 节检索参数、第 7 节评测集格式与版本、第 8 节评测与回归（运行命令、按改动类型回归、补标与新基线）。

## 3. 已完成的优化

| 优化 | 做法 | 结论 | 记录 |
| --- | --- | --- | --- |
| 评测可复现 | 同分排序改用稳定键；评测器区分召回失败与排序失败 | 已采纳 | [召回评测 9.7](phase1/yuque-ingestion/retrieval-evaluation.md#97-改进建议) |
| 分词 | 关键词路文档端用 jieba 搜索模式，查询端保持精确模式 | 保留文档端；两端都用搜索模式不采纳 | [改进记录 R1](phase2/retrieval-improvement-log.md#4-r1-jieba-搜索模式2026-10-11) |
| 同义扩展 | 查询端小词表 | 保留 | [改进记录 R2](phase2/retrieval-improvement-log.md#5-r2-查询端同义词表2026-10-11) |
| 融合参数 | RRF k 与路线加权 | 采纳 k=20、不加权 | [改进记录 R3](phase2/retrieval-improvement-log.md#7-r3-rrf-k-与路线加权2026-10-11) |
| 标注完整性 | 三路前 10 池化补标 | 新基线 v16 | [召回评测 9.11](phase1/yuque-ingestion/retrieval-evaluation.md#911-池化补标与新基线f2-012026-10-12) |
| 按条件选机型 | 规格库加推荐接口，由上层 LLM 换算条件 | D 类允许集合全部一致 | [机型规格库实施记录](phase3/product-spec-log.md) |
| 工具接入 | MCP 服务，工具 schema 自动生成 | gpt-5.6-terra 基线达标 | [实施记录第 5 节](phase3/product-spec-log.md#5-mcp-工具定义与-gpt-56-terra-基线2026-10-18) |
| 评测扩充 | 360 题、按事实分组的 dev/test、strict-v2、真实 Agent 评测 | expanded-v1 | [评测扩充第 1～3 轮](phase1/evaluation-expansion.md) |
| 评测去模板 | 题面去原文术语，B 改为名称噪声、C 改为场景口语，X 改为跨文档，G 细分，召回汇总不含 D | expanded-v2 | [评测扩充第 4 轮](phase1/evaluation-expansion.md#第-4-轮题面去模板与分类口径调整expanded-v2) |
| 无答案识别（否定结论） | 扫描余弦和 BM25 分数门槛 | 不可行，负例最高分高于正例最低分 | [召回改进方案 3.7](phase2/retrieval-improvement-plan.md#37-型号不符标记) |

## 4. 未完成的优化

| 项 | 解决的问题 | 状态与依赖 | 记录 |
| --- | --- | --- | --- |
| 按来源召回或降权其他机型评测（F2-10 / I5-01） | 带机型名的复合问题召回不到通用教程，X 类需求全覆盖只有 7/20 | P0，未实施 | [方案 3.5](phase2/retrieval-improvement-plan.md#35-按来源分别召回)、[待改进 P-01](phase5/improvement-backlog.md) |
| 教程补检索前缀（I5-02） | 教程用词与用户提问对不上 | 等待决策 D-01 | [待改进清单](phase5/improvement-backlog.md) |
| 精简 MCP 检索输出（I5-03） | 工具结果被元数据占满后截断 | P0 | 同上，P-05 |
| 工具定义补规则（I5-04）、D 类回答规范（I5-05） | 漏掉安全步骤；时效、型号和适用范围不清（v2 新增 X11、T12）；推荐缺少依据 | P0；I5-05 等待决策 D-02 | 同上，P-02～P-04 |
| 拆分无据断言口径（I5-06）、评委复核（I5-09） | 判分过严，评委误判 | 等待决策 D-03；v2 重跑（sol 评委）尚未人工抽查 | 同上，P-06、P-07 |
| 型号不符标记（F2-09 / I5-07） | 相近型号的无答案问题，召回第 1 名就是相近机型；v2 Agent 相近机型 0/2 | P1 | [方案 3.7](phase2/retrieval-improvement-plan.md#37-型号不符标记) |
| 本地重排（F2-11 / I5-08） | 主题相近但不回答问题的段落排在前面 | P1，I5-01 效果不够时再做 | [方案 3.6](phase2/retrieval-improvement-plan.md#36-重排) |
| 真实提问（F2-03 / I5-11） | 评测题都是自拟的 | 依赖维护者提供 | [第二阶段需求](phase2/requirements.md) |
| 维修场景偏好（F2-15 / I5-10） | — | 收益很小，计划记录“不做”后关闭 | [待改进清单](phase5/improvement-backlog.md) |
| 文档维护（近似重复、过时内容） | 资料增多后结果互相矛盾或过时 | 尚无失败样本 | [方案第 6 节](phase2/retrieval-improvement-plan.md#6-后续考虑文档维护) |

## 5. 评测基线演变

不同版本的题目和口径不同，各行之间不能直接比较，只用于了解演变过程。

| 基线 | 题目与口径 | 混合检索主要结果 | 记录 |
| --- | --- | --- | --- |
| R0 | 查询集 v4（135 条有答案），语料 v3，旧口径 | Hit@1／Hit@5／MRR@10 = 0.733／0.896／0.816 | [改进记录](phase2/retrieval-improvement-log.md#2-总览) |
| v16 | 池化补标后，查询集 v6（164 条有答案） | 0.77／0.95／0.851 | 同上 |
| v19 | 查询集 v8（170 条），维护手册中的“当前基线” | 0.78／0.95／0.857 | 同上 |
| expanded-v1 | 360 题，strict-v2，“全部”含 D | Hit@1 82.4%、Hit@5 95.8%，需求全覆盖 273/300；Agent 42/60 | [评测扩充第 2、3 轮](phase1/evaluation-expansion.md#第-2-轮基线与验收) |
| expanded-v2 | 360 题去模板，“全部”不含 D | Hit@1 86.6%、Hit@5 97.7%，需求全覆盖 276/300，X 类 7/20；Agent 40/60（评委换成 gpt-5.6-sol，与 v1 的 42/60 不可直接比较） | [评测扩充第 4 轮](phase1/evaluation-expansion.md#第-4-轮题面去模板与分类口径调整expanded-v2) |

## 6. 文档间待同步的不一致

评测切换到 strict-v2 和 expanded-v2 后，以下文档仍是旧描述，后续应同步（前两项已列为待改进 I5-14）：

- [总体需求](requirements.md)第 4 节、[第二阶段需求](phase2/requirements.md) F2-03 仍写“查询集 v8 共 170 条、v19 基线”。
- [维护手册](maintenance.md)第 7.4 节和 8.1 节的版本与“当前基线”仍是 v8／v19。8.1、8.2 的对比输出和通用底线仍按“奇偶分半”和“D 类 Hit@5 不下降”，而 strict-v2 已改用固定 dev/test，expanded-v2 的召回汇总不含 D。
- [召回改进记录](phase2/retrieval-improvement-log.md)的总览止于 v19，没有登记 expanded 系列基线。
