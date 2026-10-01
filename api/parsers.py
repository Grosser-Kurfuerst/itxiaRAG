from io import BytesIO

from rest_framework.parsers import JSONParser

from contracts.errors import DomainError


class LimitedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        limit = 2 * 1024 * 1024
        body = stream.read(limit + 1)
        if len(body) > limit:
            raise DomainError("INPUT_TOO_LARGE", "请求体超过 2 MiB", 413)
        return super().parse(BytesIO(body), media_type, parser_context)
