"""知识检索请求契约；同时用于 REST 校验与 MCP 工具参数。"""
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BeforeValidator, Field

from contracts.requests import RequestModel, empty_if_null, require_text

QueryText = Annotated[
    str,
    Field(max_length=2000, description="检索问题，保留机型名和关键术语，例如“来酷 GT16 内存插槽”。"),
    AfterValidator(require_text),
]
SearchTopK = Annotated[int, Field(ge=1, le=20, description="返回的段落数。")]


class Filters(RequestModel):
    source_ids: Annotated[
        list[UUID],
        Field(min_length=1, max_length=50,
              description="只在这些来源中检索；可以填写 recommend_laptops 结果中的 review.source.id。省略表示不限来源。"),
    ] = None


FiltersArg = Annotated[
    Filters,
    BeforeValidator(empty_if_null),
    Field(default_factory=Filters, description="检索范围；省略表示不限来源。"),
]


class QueryInput(RequestModel):
    query: QueryText
    filters: FiltersArg
    top_k: SearchTopK = 5
