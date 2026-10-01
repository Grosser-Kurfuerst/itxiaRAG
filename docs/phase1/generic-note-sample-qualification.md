# generic_note.v1 处理配置验收

本记录仅确认受限短笔记处理配置的机械正确性，不证明真实资料的授权、脱敏或观点正确。合成样本由 Codex 依据本仓库契约核对，并随 S5 代码只读评审；不是社团真实文档的人工审核。

- 配置：`profiles/iteration1/index.json`，SHA-256 `0a770afd84ba87d3ca03aefa34aeb0353d69c5687e6ddb6a447fc2a505541db1`。
- 处理器：`generic-note` 1.0.0；TXT／Markdown 使用 `plain-text` 1.0.0。
- 范围：manual、generic_note/1、1–8000 字且至多 200 行、一个父段和一个子块、concept、空 domain_metadata。
- 样本：`fixtures/iteration1/basic.*`、`tests/unit/test_ingestion.py`、`tests/integration/test_import.py`、`tests/integration/test_auto_release.py` 中的合成文本。
- 核对项：全文和行定位一致，Markdown 行尾空格／缩进／中间空行保留，规范化与 hash 稳定，知识类型固定，空元数据不投影，硬错误拒绝，不会执行正文里的指令。public/internal 隔离、人工要求与普通日期警告分别处理。
- 验证命令：`make test-unit`、`make test-integration`、`make acceptance STEP=S5`。实际执行结果与评审结论见 [实施记录](implementation-progress.md#s5)。

清单只控制新导入或显式 resume 的自动资格，不扫描历史待审任务、不改变 index hash。修改算法或 Schema 后，先用新配置重新验收，再登记对应 hash；未登记时正常构建但保持人工待审。删除资格不会撤回已经发布的内容；如需停止传播，使用来源停用／撤回入口。尚未发布的 auto-approved 任务重新检查清单，资格失效时返回 `AUTO_RELEASE_NOT_QUALIFIED`。
