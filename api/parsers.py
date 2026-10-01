from io import BytesIO

from rest_framework.parsers import JSONParser

from contracts.errors import DomainError


class LimitedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        body = stream.read(131073)
        if len(body) > 131072:
            raise DomainError("INPUT_TOO_LARGE", "请求体超过 128 KiB", 413)
        return super().parse(BytesIO(body), media_type, parser_context)
