from contracts.types import ContentBlock, ParsedDocument


class PlainTextParser:
    def parse(self, input):
        return ParsedDocument([ContentBlock("text", input.input_text, [input.title], 1,
                                            len(input.input_text.split("\n")))])
