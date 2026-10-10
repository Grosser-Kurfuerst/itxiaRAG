"""结构形成后、预算切分前的元数据增强步骤。"""

import re
from dataclasses import replace

from ingestion.preprocessing import PreprocessContext


class CalloutWarningStep:
    input_stage = output_stage = "units"

    def process(self, context: PreprocessContext) -> PreprocessContext:
        first_heading = next((b.ordinal for b in context.blocks if b.kind == "heading"), None)
        for block in context.blocks:
            if block.kind != "callout" or block.metadata.get("level") not in {"warning", "caution"}:
                continue
            warning = block.text[:300]
            if first_heading is None or block.ordinal < first_heading:
                if warning not in context.warnings and warning not in context.raw.metadata.get("warnings", []):
                    context.warnings.append(warning)
            else:
                for unit in context.units:
                    if unit.locator["block_start"] <= block.ordinal <= unit.locator["block_end"]:
                        if warning not in unit.warnings:
                            unit.warnings.append(warning)
                        break
        return context


_TIME_EXPRESSION = re.compile(
    r"(?:目前|截至)\s*(?:[（(]\s*)?(?:19|20)\d{2}\s*"
    r"(?:年(?:初|底|末|中)?|[./-]\d{1,2}(?:[./-]\d{1,2})?)(?:\s*[）)])?"
    r"|[（(]\s*(?:19|20)\d{2}(?:\s*年(?:\s*\d{1,2}\s*月)?|[./-]\d{1,2})?\s*更新\s*[）)]"
)


class TimeExpressionStep:
    input_stage = output_stage = "units"

    def process(self, context: PreprocessContext) -> PreprocessContext:
        for unit in context.units:
            match = _TIME_EXPRESSION.search(unit.body)
            if match:
                warning = f"含时间限定表述‘{match.group()}’，请结合来源日期判断是否仍适用"
                if warning not in unit.warnings:
                    unit.warnings.append(warning)
        return context


class RetrievalPrefixStep:
    input_stage = output_stage = "units"

    def process(self, context: PreprocessContext) -> PreprocessContext:
        parts = [*context.raw.metadata.get("collection_path", []),
                 str(context.raw.metadata.get("title") or "未命名文档")]
        units = []
        for unit in context.units:
            path = unit.metadata.get("section_path", unit.title.split(" > "))
            prefix = " > ".join(part for part in parts if part not in path)
            children = [replace(child, retrieval_prefix="\n".join(
                part for part in (prefix, child.retrieval_prefix) if part
            )) for child in unit.children]
            units.append(replace(unit, children=children))
        context.units = units
        return context


class ToolIdentityStep:
    """把工具名、用途和分类写入父段 metadata，随检索结果返回。"""

    input_stage = output_stage = "units"

    def process(self, context: PreprocessContext) -> PreprocessContext:
        metadata = context.raw.metadata
        if metadata.get("tool_collection"):
            # 合集的工具父段路径为“分类 > 工具名”；文档导语和分类导语只有一段路径，不带工具身份。
            for unit in context.units:
                path = unit.metadata["section_path"]
                if len(path) >= 2:
                    unit.metadata.update(tool_name=path[-1], tool_category=path[-2])
            return context
        # 单工具文档标题形如“用途：工具名”；没有冒号时整个标题即工具名。
        title = str(metadata.get("title") or "")
        purpose, separator, name = title.partition("：")
        identity = {"tool_name": name.strip(), "tool_purpose": purpose.strip()} if separator else {
            "tool_name": title.strip()}
        if metadata.get("collection_path"):
            identity["tool_category"] = metadata["collection_path"][-1]
        for unit in context.units:
            unit.metadata.update(identity)
        return context


class SourceDateNoticeStep:
    """提示工具条目的最后更新日期；只写日期本身，不计算距今多久。"""

    input_stage = output_stage = "units"

    def process(self, context: PreprocessContext) -> PreprocessContext:
        source_date = context.raw.metadata.get("source_date")
        updated = f"最后更新于 {source_date}" if source_date else "更新日期未知"
        warning = f"本条目内容{updated}，软件版本、下载地址和界面可能已变化，请以官网为准"
        if warning not in context.warnings:
            context.warnings.append(warning)
        return context
