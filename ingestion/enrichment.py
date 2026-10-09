"""结构形成后、预算切分前的教程元数据增强步骤。"""

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
