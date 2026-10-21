# 召回与 Agent 输出评测扩充

## 原始请求与约束

用户在 2026-10-21 明确要求：按照本对话的“360 条基础用例＋其中 60 条 Agent 输出验收”方案执行，完成后汇报结果；显式调用 [implement-plan-iterations](/home/kurfuerst/.agents/skills/implement-plan-iterations/SKILL.md)。每轮遵守 implementation-review-loop，评审修复后创建一次 Conventional Commits 提交。

沿用 A/B/C/D/E/F/T/X/K/U/R/G 十二类，不扩展分类；共享问题和证据，区分组内可替代证据与组间必要需求。精确率按实际返回数、召回率按完整相关集合计算，移除容量归一化。评测保持简洁，不修改业务检索和 MCP 接口，不提交凭据、完整私有文章或真实维修记录；语料导出和运行结果只写忽略的 `.runtime/`。

完整方案来自本对话上一条回复，关键验收如下。配额顺序为 A/B/C/D/E/F/T/X/K/U/R/G：基础题 30/25/25/30/20/25/35/20/40/40/45/25，共 360；Agent 题 3/3/3/10/6/4/5/8/4/4/4/6，共 60。基础 dev/test=300/60；Agent dev/test=40/20，其中 10 段多轮。170 个原有 id 保留，新增 190 题，旧标签允许基于证据修正。现有 11 条工具调用及 8 条偏好排序样例单独统计。

## 迭代与验收

1. **20 题校准**：建立证据标注、离线校验、真实 persona 执行记录和 LLM 评审。覆盖十二类，保存真实工具消息和最终发送答案。复核至少 15 题。用户指定的“人工复核”由实施者逐题检查替代，不能称为独立人工标注或已证明评委可靠。暂不扩全 360，不提前变更召回指标。
2. **360 题基础集**：新增 190 题、审核旧标签，完成分组划分、必要证据匹配、修正指标，运行召回和推荐基线。D 类单独报告；G 类不计算空分母召回率；相关集合未穷举的题不汇总完整 Recall@10。依赖第 1 轮。
3. **60 题 Agent 验收**：补齐答案标注和 10 段多轮，运行全部真实 Agent、LLM 评审及回归，输出按分类、dev/test、旧/新增题分层报告。依赖第 2 轮。只用 dev 校准提示词，test 用于最终验收。

每轮均先实现、运行受影响和全量检查，再调用只读 reviewer，修复有效阻塞问题并复核，最多五轮；无阻塞后单独提交。真实模型/网络错误单列，不冒充质量得分；运行记录保留模型、提示词、schema、用例和语料哈希。真实宿主接口或依赖无法使用时明确记录，不用模拟工具循环替代真实 persona 验收。

## 证据与判分

`needs` 每项为一个必要需求，`answer` 是语义验收要点；`evidence` 内多个 `{ref, quote}` 为可替代证据。`ref` 引用现有 aliases，quote 必须出现在实际父段正文中。分组以事实主题为单位，简称和口语变体不跨 dev/test。无答案题以固定语料快照和工具能力为边界，不把相似候选当成正确答案。

召回主指标为 Hit@1、必要需求全部覆盖@5、返回结果精确率、Recall@10。正文证据匹配不以标题或命中子块代替；Agent 层另核验实际序列化、截断后可见的工具消息。输出评审分别检查要点、事实/条件及证据支持；主指标为按题平均的要点覆盖和任务通过率，不使用模糊总分。

## 实施记录

开始时工作树干净。已核实正式 Docker 数据库、API、MCP 服务存在；评测模型端点以最小请求验证成功。语料只读导出至 `.runtime/eval/expanded-v1/corpus.json`。运行宿主为 persona 的 kei mock 适配器，生产聊天平台不在本轮验收范围内。

### 第 1 轮结果

已完成 20 题、37 个必要要点及原文证据的标注与核验，覆盖十二类；主集仍为 170 题，尚未扩到 360。执行器、评审提示词和离线校验器已实现。GT16 噪音问题接受日常环境 55.4dB 或消声室 49.2dB 的有依据回答，要求说明测量场景，避免把一种合法答案误判为缺失。

验证：新增离线单测 14 项通过；隔离 Docker 全量测试 617 项通过（12.24 秒）；Python 编译与 `git diff --check` 通过。全量验证命令：

```sh
DB_PORT=25432 docker compose --env-file .env.docker -p itxia-tests --profile test run --rm \
  -v "$PWD:/app:ro" test python -m pytest -q
```

首轮 reviewer 指出的超时串题、评委错误污染质量指标分母、重评丢失原执行来源问题均已修复，并增加验证。第二轮未发现新增代码阻塞，当时因真实运行未获授权而给出 `NEEDS_FIX`。授权后进行第三轮只读评审，最终为 `NO_BLOCKING_ISSUES`，本轮完成。

用户于本对话明确回复“允许”，授权使用当前 `codex.kurfuerst.top` 端点发送本次评测问题、检索正文、工具结果和回答。已运行全部 20 题真实 persona，执行模型与评委均为 `gpt-5.6-terra`；临时宿主与 MCP 共享容器网络，正式服务不变。原始记录在 `.runtime/eval/expanded-v1/pilot.json`，校准后重评汇总在 `pilot-calibrated.json`。

初次评审有 4 条引用改写导致的 `judge_error`。调整连续原文引用规则、禁止额外必答条件，并只将实际工具消息交给评委后，重评为 20/20 可评分、12/20 通过（60%），接口/评审错误为 0。没有重新生成答案。K01 原标注遗漏资料中的历史资费，已补证据，并要求以当前门户为准；原快照 `pilot-cases.json` 保留。重评器允许传入原标注快照，核验原哈希且禁止改变实际问题和追问。

实施者逐题复核 15 题，记录在 `pilot-manual-review.json`；与 LLM 通过结论一致 12/15（80%）。A01 的噪音听感判断、E01 已限定测试场景却仍被要求补免责声明、T12 启动转换助理步骤的证据支持存在分歧。该比较不属于独立人工标注或评委可靠性的证明；后续保持评委规则冻结，报告原始判分及分歧，不将 LLM 分数视为绝对真值。

T12 的争议还需要确认实施者对可见证据边界的判断，不能直接认定为评委误判。X01 的工具消息没有安装教程，评委也未完整识别所有安装步骤缺少支持的情况，虽该题最终仍判失败，说明证据支持检查仍需抽查。第三轮引入多轮时必须记录每轮工具证据边界，防止后续取得的资料反向证明先前回答。

稳定发现的问题包括：X01/X02 均遗漏断开内置电池，且实际工具内容未包含安装教程；D15 把 3120×2080 屏幕称为 2.8K；K01 未保留历史资费口径。D 类沿用已有预算换算标签，例如“预算7000”的区间上限为 7700 元，属于既有模糊预算约定，不代表严格 7000 元以内；显式“以内”仍按硬上限计算。本轮仅校准评测，不修改 Agent 或检索业务实现。

## 执行命令与宿主

离线核验不需要 Django、数据库或模型：

```sh
.venv/bin/python eval/cases.py eval/queries.json --corpus .runtime/eval/expanded-v1/corpus.json
```

语料 JSON 每条含 `title`、`body`、`source`，source 含 schema/metadata/url 等；从正式库只读导出，不提交。`--full` 另核验最终配额、dev/test 和多轮数量。

使用 persona 文档中的最小 kei mock 宿主，HTTP `/inject` 和 `/sent` 在回环地址开放，private_policy=open，reply_dedupe=false。当前接入基线保持 reply_max_chars=500、tools_result_max_chars=12000、tools_call_timeout=15s、默认两轮工具预算；配置内容和 MCP 凭据不提交。更新人格提示词时从 `products/tool-definitions.md` 读取并加上真实工具名称的 `mcp__` 前缀。

将宿主 `llm_base_url` 指向 `http://127.0.0.1:19091/v1`。本地代理由评测器运行期间启动，宿主仍使用实际模型名，但不需要模型密钥；评测器通过 EVAL_LLM_* 转发请求，模型请求/响应只保留正文，不保存 Authorization。

```sh
# 启动宿主，使用本地配置（不要提交）
/path/to/persona-host .runtime/eval/expanded-v1/persona.yaml

# 在另一终端加载已授权的 EVAL_LLM_* 后执行；逐题写入，接口错误单列
.venv/bin/python eval/agent_eval.py eval/queries.json .runtime/eval/expanded-v1/agent.json \
  --corpus .runtime/eval/expanded-v1/corpus.json \
  --runtime-config .runtime/eval/expanded-v1/persona.yaml
```

`--ids A01 X01` 选择小样本，`--split dev` 限定调试集。`--recorded <旧报告>` 使用原始真实执行重新评审，默认要求用例、语料、规格哈希都一致，不重新调用 Agent。修订标签时加 `--recorded-spec <原用例快照>`，核验原快照哈希且实际问题和追问不得改变，保留执行用例哈希并另记当前标注哈希。EVAL_JUDGE_BASE_URL/MODEL/API_KEY 可单独指定评委；未指定时复用 EVAL_LLM_*，报告中明确记录两个模型身份。复用同一模型不代表评审可靠性已得到独立验证。

执行异常后停止当批真实生成，其余题标为 `not_run`，避免未取消的宿主后续请求串入下一题。需要先重启宿主、确认无在途请求后再重跑。评委错误标为 `judge_error`，不进入 Agent 质量通过率的分母：`task_pass_rate` 的分母为 `scored` 数；`effective_pass_rate` 的分母为本批请求题数，同时反映模型/执行/评审可用性。重评继承原执行模型、宿主配置哈希和预算，只更新本次评委元数据。
