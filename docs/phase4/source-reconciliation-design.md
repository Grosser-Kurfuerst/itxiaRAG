# 来源对账与下线方案

状态：已实现（2026-10-14）。对应[第四阶段需求](requirements.md#21-必做来源下线与对账) F4-01、F4-02。

## 1. 目标与边界

- **F4-01 对账**：批量导入结束时，报告库中存在但这次不该保留的来源。只报告，不删除。
- **F4-02 下线**：提供命令，按来源类型和定位符删除来源，父段、子块随之删除。

不做：自动删除、软删除或回收站、删除历史、跨 `source_type` 对账、交互式确认。误删靠删除前的备份恢复（[维护手册 9.2](../maintenance.md#92-备份与恢复)）。

## 2. F4-01 过期来源对账

### 2.1 判定规则

批量导入的列表阶段已为每篇文档生成 `SourceRef`，其中带有入库时使用的 `canonical_locator`（语雀为 `doc:<文档 ID>`，公众号为永久链接或采集文件名）。导入主循环会为每个 `SourceRef` 生成一行报告。对账把库中同一 `source_type` 的来源逐个对照：

| 库中来源的情况 | 是否过期 | 报告原因 |
| --- | --- | --- |
| 本次列表中没有对应的 `SourceRef` | 是 | `不在本次列表中` |
| 对应行为 `skipped` | 是 | `skipped: <清单原因或“未接入”>` |
| 对应行为 `unregistered` | 是 | `unregistered: ...` |
| 对应行为 `imported`、`reused`、`failed` | 否 | — |

“不在本次列表中”包括：语雀文章已删除或移出已登记的库、库已从清单中删除、采集目录中没有该文件。`failed` 不算过期，因为读取或预处理失败不代表来源已经下线。

### 2.2 何时对账

只在不带 `--only` 的正式导入时对账：

- 带 `--only` 时只处理部分文档，对照会把其余文档都误报为过期。
- 试运行不装配保存适配器，也不访问数据库，保持这一现有约定；单测中的试运行命令也不会因此访问数据库。

对账依据的是本次列表。用 `--snapshot` 导入时列表来自快照，快照之后新导入的文档会报“不在本次列表中”，维护手册中注明即可，不做特殊处理。

原文 API 导入的来源应使用独立的 `source_type`（如 `manual`），不会进入语雀或公众号的对账。

### 2.3 代码改动

**保存适配器**：[catalog/storage.py](../../catalog/storage.py) 的 `DjangoDocumentStore` 增加只读方法，并在 [contracts/types.py](../../contracts/types.py) 的 `DocumentStore` 协议中声明：

```python
def existing_sources(self, source_type):
    """返回该类型已入库来源的 {canonical_locator: title}，供批量导入对账。"""
    return dict(KnowledgeSource.objects.filter(source_type=source_type)
                .values_list("canonical_locator", "title"))
```

**导入服务**：[sources/importing.py](../../sources/importing.py)

```python
@dataclass(frozen=True)
class StaleSource:
    locator: str
    title: str
    reason: str


def find_stale(refs, rows, existing):
    """库中来源对照本次列表：不在列表中、清单已 skip 或未登记的视为过期。"""
    keys = {ref.canonical_locator: ref.key for ref in refs}
    rows = {row.doc: row for row in rows}
    stale = []
    for locator, title in sorted(existing.items()):
        row = rows.get(keys.get(locator))
        if row is None:
            stale.append(StaleSource(locator, title, "不在本次列表中"))
        elif row.status in ("skipped", "unregistered"):
            stale.append(StaleSource(locator, title, f"{row.status}: {row.detail}"))
    return stale
```

- `ImportReport` 增加 `stale: list[StaleSource] | None = None`，`None` 表示本次未对账。
- `SourceImportService.run` 增加参数 `existing: Mapping[str, str] | None = None`；不为 `None` 时，在主循环结束后执行 `report.stale = find_stale(refs, report.rows, existing)`。是否对账由命令决定，服务不重复判断 `--only`。
- `ImportReport.format()` 在警告之后逐行输出 `stale: <定位符>  <标题>  <原因>`，汇总行末尾追加 `stale=<条数>`；未对账时两者都不输出。`summary` 字典不变，过期来源不影响退出码。

**命令**：[sources/commands.py](../../sources/commands.py) 的 `SourceImportCommand.run` 在调用导入服务前取库中来源：

```python
existing = None if dry_run or only else store.existing_sources(self.source_type)
...
report = SourceImportService(...).run(refs, only=only, read_errors=read_errors, existing=existing)
```

试运行时 `store` 本来就是 `None`，条件与之一致。语雀和公众号命令都继承这个基类，不需要分别修改。

报告示例：

```text
stale: doc:12345  旧版激活教程  skipped: 已废弃
stale: doc:67890  校园网旧客户端  不在本次列表中
summary: imported=1 reused=86 preprocessed=0 skipped=33 unregistered=0 failed=0 stale=2
```

## 3. F4-02 下线命令

### 3.1 用法

命令放在 `catalog/management/commands/delete_source.py`，因为来源的保存与删除都属于 `catalog`：

```sh
dc exec app python manage.py delete_source --source-type yuque --locator doc:12345 --locator doc:67890 --dry-run
dc exec app python manage.py delete_source --source-type yuque --locator doc:12345 --locator doc:67890
```

- `--locator` 可以重复，直接复制对账报告中的定位符。
- 只要有一个定位符在库中不存在，就报错退出，不删除任何来源，避免拼错时只删掉一部分。
- 先逐行输出将删除的来源：`<定位符>  <标题>  parents=<父段数> children=<子块数>`。试运行到此结束；正式删除后再输出 `deleted=<来源数>`。
- 不做交互确认，用试运行代替。

### 3.2 实现

```python
class Command(KBCommand):
    help = "按来源类型和定位符删除来源及其父段、子块；先用 --dry-run 核对"

    def add_arguments(self, parser):
        parser.add_argument("--source-type", required=True)
        parser.add_argument("--locator", action="append", required=True)
        parser.add_argument("--dry-run", action="store_true")

    def run(self, *args, **options):
        locators = set(options["locator"])
        sources = list(KnowledgeSource.objects
                       .filter(source_type=options["source_type"], canonical_locator__in=locators)
                       .annotate(parents=Count("contexts", distinct=True), children=Count("contexts__children"))
                       .order_by("canonical_locator"))
        missing = locators - {source.canonical_locator for source in sources}
        if missing:
            raise CommandError(f"库中没有这些来源：{', '.join(sorted(missing))}")
        for source in sources:
            self.stdout.write(f"{source.canonical_locator}  {source.title}  "
                              f"parents={source.parents} children={source.children}")
        if options["dry_run"]:
            return
        KnowledgeSource.objects.filter(pk__in=[source.pk for source in sources]).delete()
        self.stdout.write(f"deleted={len(sources)}")
```

父段、子块通过外键 `on_delete=CASCADE` 删除。Django 的 `QuerySet.delete()` 在一个事务内完成级联删除，不需要另加事务。机型规格通过 `review_context` 关联评测父段（`on_delete=SET_NULL`），删除评测后关联置空，该机型不再参与推荐；规格记录仍按维护手册的步骤从规格文件中删除后重新导入。

## 4. 测试

单测不访问数据库，删除命令和对账查询放在集成测试中验证。

| 测试 | 内容 |
| --- | --- |
| [test_yuque_importer.py](../../tests/unit/test_yuque_importer.py) 单测 | `find_stale` 覆盖三种过期原因，以及 `imported`、`reused`、`failed` 不算过期；`format()` 在对账时输出 `stale` 行和计数，未对账时不输出；带 `--only` 和试运行时不调用 `existing_sources`。已有正式导入单测中的 `Mock` 保存适配器补上 `existing_sources.return_value = {}` |
| [test_yuque_ingestion.py](../../tests/integration/test_yuque_ingestion.py) 集成测试 | 用合成快照正式导入；把一篇改为 `skip`、从快照中删除另一篇后重导，报告这两篇过期，其余不报；对这两篇执行 `delete_source --dry-run` 后数据不变，正式执行后来源、父段、子块都被删除；定位符不存在时报错且不删除 |

## 5. 文档同步

| 文档 | 内容 |
| --- | --- |
| [维护手册](../maintenance.md) | 2.2 节报告说明增加 `stale`，说明对账条件和快照导入的注意事项；2.6 节改为“看对账报告 → 备份 → `delete_source` 试运行 → 正式删除”，保留同步清单、查询集和规格文件的步骤 |
| [来源连接器设计](../phase1/source-connector-design.md) | 第 6 节导入服务与报告：增加对账 |
| [第四阶段需求](requirements.md) | F4-01、F4-02 的状态 |

## 6. 实施顺序

1. F4-02 下线命令及其集成测试，同步维护手册 2.6 节。
2. F4-01 对账：保存适配器方法、导入服务、命令接线和测试，同步维护手册 2.2 节与来源连接器设计。

两项可以分开提交。预计生产代码约 60 行。
