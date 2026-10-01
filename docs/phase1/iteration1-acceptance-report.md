# 迭代一验收报告

验收版本：S6（`config.release.IMPLEMENTED_STEP=6`）
环境：Python 3.12.14、Django 5.2.17、PostgreSQL 17；Docker Compose 隔离项目；配置 hash 见 S6-environment.json。
范围：`manual + generic_note.v1` 短笔记、同步导入、自动／人工放行、关键词查询、父子引用和来源生命周期。

## 命令结果

以下结果在真实容器中取得：

- `make test-unit`：76 passed（unit + contract）。
- `make test-integration`：55 passed（真实 PostgreSQL；包含 S6 验收矩阵）。
- `make acceptance ITERATION=1`：138 passed（全量单元／契约、集成和真实 HTTP／命令）。
- 独立空库 `up/migrate/seed-demo/acceptance`：138 passed；演示重跑、撤回保留和权限查询通过。
- S5 数据 `up/migrate` 升级、S6 同版本重启和重复迁移：前后摘要一致，来源／任务／父子／指针／Token／配置／审计均保留；重启后全量验收再次 138 passed。
- `manage.py spectacular --validate --fail-on-warn`、`makemigrations --check --dry-run`、`manage.py check`：S6 严格复核通过。

`make acceptance` 生成的 JUnit 报告位于 app 容器 `/tmp/itxia-acceptance/S6.xml`；环境与源码摘要在同目录的 `S6-environment.json`。报告含合成账号和资料 ID，不复制真实正文或凭据，导出后存放在仓库外。

S6 第 1 轮独立只读评审结论为 `NO_BLOCKING_ISSUES`，reviewer 在 fresh 项目独立重跑全量验收 138 passed。

## I1-A01～I1-A18

| 编号 | 验收结论 | 主要证据 |
| --- | --- | --- |
| I1-A01 | 通过 | S6 空库迁移；五张业务表、真实 hash，无 vector/PGroonga/Worker/模型依赖 |
| I1-A02 | 通过 | 自动导入一父一子、concept、发布并可检索 |
| I1-A03 | 通过 | 稳定键／正文去重；标题、正文、日期变化生成候选；来源元数据冲突 409 |
| I1-A04 | 通过 | `require_manual_review` 待审；date_unknown 可自动放行 |
| I1-A05 | 通过 | 未登记配置待审；人工 review/publish 可上线 |
| I1-A06 | 通过 | 未授权、未脱敏、wechat/product_review 均拒绝且不保存正文 |
| I1-A07 | 通过 | T2 回滚、pending resume、failed retry、T3 中断恢复；拒绝不可绕过 |
| I1-A08 | 通过 | 并发／过时候选只有一个发布者，旧指针和产物完整 |
| I1-A09 | 通过 | 数据库排序后 LIMIT、稳定 ID 破平局、按父段去重，top_k 计父段 |
| I1-A10 | 通过 | NoOp、bypass、改写、超时／异常 fallback；保留原查询与范围 |
| I1-A11 | 通过 | 严格未知键、类型、null 和能力错误；purchase/repair 不静默忽略 |
| I1-A12 | 通过 | public/internal、候选、旧 ID 和 source filter 的权限隔离 |
| I1-A13 | 通过 | withdraw、disabled、授权撤销和返回前状态变化立即生效 |
| I1-A14 | 通过 | 输入大小限制；响应预算整父段跳过，不截断正文；正文指令只作数据 |
| I1-A15 | 通过 | domain_metadata 仅空对象；固定 concept；无冲突投影或标记 |
| I1-A16 | 通过 | PostgreSQL／配置／系统账号／审计故障返回 503，不伪装为空 |
| I1-A17 | 通过 | feedback 端点 404，查询不落表；报告含父子、定位、状态 |
| I1-A18 | 通过 | BOM／CRLF 和首尾空白行规范化；Markdown 行尾空格、缩进和中间空行保留 |

## 独立交接与运行故障验证

- 实际停止主验收项目 db 后 live=200、ready=503，携带有效 Token 的 search=503/DEPENDENCY_UNAVAILABLE；启动 db 后 ready/search=200。
- 独立只读评审智能体在 fresh 项目以唯一前缀运行 migrate/init、seed、TXT 导入、报告、pending resume、人工批准／发布、引用、撤回和重复 seed；报告权限为 0600，未输出 Token。人工要求保持，撤回后引用 404、检索移除。
- 这次独立操作由评审智能体完成，未宣称另一位真实社团维护者已试用。failed retry 的故障注入由 PostgreSQL 集成测试验证；交接操作未人为破坏部署数据。

## 用例定位

- 初始化、状态完整性和自动恢复：`tests/integration/test_initialization.py`、`test_import.py`、`test_auto_release.py`、两个 `test_*_concurrency.py`。
- 查询契约、字段错误、处理器回退：`tests/contract/test_query.py`；保真规范化：`tests/unit/test_ingestion.py`。
- 排序、预算、权限和返回前变更：`tests/integration/test_search.py`、`test_acceptance_matrix.py`。
- 实际入口与重复 seed：`tests/e2e/iteration1/` 的全部 7 个验收用例。

## 交付边界与剩余限制

本报告不宣称笔吧评测室、语雀或微信公众号已接入，也不宣称向量、LLM、Agent、图谱、Worker、三类场景条件匹配或反馈已实现。自动资格记录只说明合成短笔记处理器的机械验收；真实资料仍须维护者确认授权、脱敏、内容正确性和适用范围。后续接入新 Schema 时应使用新的解析处理器和新的资格记录，不修改 `generic_note` 以承载平台专用逻辑。
