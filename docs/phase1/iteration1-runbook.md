# 迭代一运行与交接手册

适用于 Python 3.12、Django 5.2、PostgreSQL 17 的当前仓库。仅处理人工整理的 `manual + generic_note.v1` 短笔记，一父一子，提供关键词查询；不包含笔吧／语雀读取、Worker、向量、LLM、Agent 或反馈。

## 1. 首次启动

需要 Docker Engine、Compose v2、Make，以及构建时访问镜像／依赖仓库的网络。运行时不访问外部资料或模型。

1. 把 `.env.example` 复制到仓库外，例如 `/tmp/itxiaRAG.env`，填写随机 DJANGO_SECRET_KEY 和 POSTGRES_PASSWORD，执行 `chmod 600 /tmp/itxiaRAG.env`。不要使用示例占位值。
2. 在项目根目录运行：

```sh
make up ITERATION=1
make migrate ITERATION=1
make seed-demo ITERATION=1
make acceptance ITERATION=1
```

`up` 构建应用并启动 app/db；迁移前 live 可用而 ready=503；migrate 完成后 ready=200。服务默认仅监听 `127.0.0.1:18080`，生产 HTTPS 由部署环境另行提供。`seed-demo` 是明确创建合成演示数据的操作，生产资料库不需要运行它。环境文件、项目名和端口可分别用 ENV_FILE、COMPOSE_PROJECT_NAME、APP_PORT 设置。

`acceptance` 默认 S6，运行全量离线、真实 PostgreSQL 集成和真实 HTTP／命令测试；会在当前库创建唯一命名的合成来源及测试账号，因此只对隔离验收项目执行。pytest 集成测试使用单独的 `test_<数据库名>`，需要测试数据库创建权限，不复用生产库。仅执行离线测试用 `make test-unit`；集成测试用 `make test-integration`。

容器命令可用以下 shell helper，后续示例均在项目根目录：

```sh
dc() { docker compose --env-file /tmp/itxiaRAG.env -p itxia-phase1 "$@"; }
```

## 2. 账号与查询

演示命令创建 `itxia-demo-reader`、`itxia-demo-member`、`itxia-demo-maintainer`，分别为普通查询、内部查询、内部维护／复核账号。无登录密码；Token 保存在 app 容器 `/tmp/itxia-demo-tokens/` 的同名 `.token` 文件，权限 0600。普通查询账号只看到 public，维护权不自动代表内部读取权。

通过真实 HTTP 查询，不在终端打印 Token：

```sh
dc exec -T app python - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, urlopen
token = Path('/tmp/itxia-demo-tokens/itxia-demo-reader.token').read_text().strip()
body = json.dumps({'query': '备份', 'preprocess': 'bypass', 'top_k': 5}).encode()
request = Request('http://127.0.0.1:8000/api/v1/search/', data=body,
                  headers={'Authorization': 'Token ' + token, 'Content-Type': 'application/json'})
with urlopen(request, timeout=10) as response:
    print(json.dumps(json.load(response), ensure_ascii=False, indent=2))
PY
```

结果是完整 `contexts[]` 和 citations，不是生成答案。`GET /api/v1/contexts/{context_id}/` 和 `evidence/{evidence_id}/` 可读取当前引用；无权、旧构建、撤回和不存在对象均 404。连续中文为短语，多个关键词用空格分隔。仅 general＋空 confirmed_context 可用；合法 purchase/repair 返回 `CAPABILITY_NOT_AVAILABLE`。`no_result` 是正常无匹配，`insufficient_evidence` 是空结果且降级或预算不足。

部署侧新建／撤销账号：

```sh
dc exec -T app python manage.py kb_account --username maintainer --permissions maintain_source,review_import,read_internal --token-file /tmp/maintainer.token
dc exec -T app python manage.py kb_account --username maintainer --revoke-token
```

Token 不写入 Git、日志或工单。撤销后重新发放需使用新的文件路径。重建 app 不删除数据库 Token，但容器 `/tmp` 文件会消失；演示环境可重跑 seed 导出已有 Token，正式账号可用原命令写到新的受控文件。不要为 `kb-system` 发 Token。

## 3. 导入、报告与人工复核

先确认使用授权、可见范围和脱敏。正文限 UTF-8、规范化后 1–8000 字、最多 200 行，单文件读取限 128 KiB。Markdown 保留有意义的行尾空格和缩进。`domain_metadata` 只能省略或 `{}`，内容知识类型固定 concept。

首次导入元数据参照 `fixtures/iteration1/basic.json`；稳定来源键须唯一。自己的输入文件通过 `dc cp` 复制进容器，命令中的文件路径均是容器内路径。更新已有来源使用 `--source <source-id>`，此时 metadata 只包含内容字段，不能再带来源身份和权限字段。

```sh
dc exec -T app python manage.py kb_import --file fixtures/iteration1/basic.txt --metadata fixtures/iteration1/basic.json --actor itxia-demo-maintainer
dc exec -T app python manage.py kb_job --id <job-id> --actor itxia-demo-maintainer --report /tmp/job-report.md
```

普通合格配置自动放行并发布；JSON 结果中的 `is_current=true` 表示当前指针，不替代来源状态和查询权限。HTTP 同步提交统一为 200，仍需检查 status、review_status、is_current、error_code。命令 0=成功发布，2=输入非法，3=任务失败或发布冲突，4=待人工处理，5=依赖不可用。

`require_manual_review=true` 或处理配置未登记资格时保留候选。报告含固定输入、父子正文／定位和质量原因；核对内容完整、出处、授权脱敏声明及父子边界后决定：

```sh
dc exec -T app python manage.py kb_job --id <job-id> --actor itxia-demo-maintainer --review approved --note '核对完整原文与定位'
dc exec -T app python manage.py kb_publish --id <job-id> --actor itxia-demo-maintainer
```

批准不会隐式发布；也可随后 resume 完成发布。拒绝使用 `--review rejected` 加说明；拒绝后须修订内容，不能用 retry 或 resume 绕过。报告文件权限 0600，拒绝覆盖已有文件，重新导出用新路径。自动资格依据见 [合成样本核对记录](generic-note-sample-qualification.md)，不等同于证明观点正确。

## 4. 故障恢复与撤回

| 任务／问题 | 操作与预期 |
| --- | --- |
| pending，中断尚未完成构建 | `kb_job --id ... --actor ... --resume`；同步继续构建 |
| succeeded，放行／发布中断 | 同样 resume，复用原父子 ID，重新检查资格与当前构建 |
| failed | 先查看 error_code 和报告，修复依赖／实现后 `--retry`；原输入和配置不变，内容修改走新导入 |
| 人工 pending | 查看 review_reasons，人工复核或等待新配置完成样本验收；resume 不取消人工要求 |
| BUILD_CONFLICT | 已有别的新稿先发布；基于当前版本重新提交，不强行覆盖当前指针 |
| AUTO_RELEASE_NOT_QUALIFIED | 尚未发布的自动批准任务失去资格；核对清单，恢复已验收资格后 resume，不跳过硬校验 |
| RELEASE_POLICY_UNAVAILABLE | 检查部署 PROFILE_DIR 下 auto-release.json 是否有效；修复后 resume |
| SYSTEM_ACCOUNT_UNAVAILABLE | 检查系统账号是否被改变，受控执行 kb_init 恢复最小权限；不为系统账号发凭据 |
| 数据库／审计故障 | 返回 503，已提交步骤保留；恢复依赖后查看报告再 resume。数据库不可用期间不能保证错误已落库 |

撤回不删除原文和审计，也不清空指针；立即停止后续查询和详情读取：

```sh
dc exec -T app python manage.py kb_withdraw --source <source-id> --actor itxia-demo-maintainer
```

临时停用用来源 PATCH `{"status":"disabled"}`；授权仍 confirmed 时可恢复 active。public 可以收紧为 internal；internal 不能直接改 public，需另建脱敏、已获公开授权的来源。withdrawn 是终态，seed 重跑不会复活它。

## 5. 升级、维护与验收报告

升级保留 PostgreSQL 卷，执行 `make up` 和 `make migrate`；不使用 `down -v` 处理要保留的数据。S0～S6 累积迁移兼容，S4 以后已发布资料无需重新导入即可查询。`kb_init` 不覆盖不同活动配置；处理算法改变后的索引升级属于后续迭代，不能只改 hash。

设置仓库外 env 的 `KB_MAINTENANCE=true` 并重建 app 配置后，查询／详情、新导入、retry/resume、publish 返回 503，任务报告、停用和撤回仍可用，live=200。恢复 false 并重新 up 后检查 ready。普通 down/up 保留数据。

报告在 app 容器 `/tmp/itxia-acceptance/S6.xml` 和 `S6-environment.json`，记录源码摘要、实际版本与配置 hash。可用 `dc cp app:/tmp/itxia-acceptance /tmp/itxia-acceptance-export` 导出到仓库外；报告与 Token 文件不同，不应混存。

`dc exec -T app python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml` 验证并导出真实 OpenAPI；维护 Token 可读 `/api/schema/`。逐项证据见 [验收矩阵](iteration1-acceptance-report.md)。交接时另一位维护者依次执行初始化、导入、报告、待审／失败恢复、发布和撤回；自动测试不能代替对真实资料的人工内容核对。
