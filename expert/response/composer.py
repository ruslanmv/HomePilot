from expert.response.formatter import Formatter
from expert.response.citation_inserter import CitationInserter
from expert.response.answer_validator import AnswerValidator


class ResponseComposer:
    def __init__(self):
        self.formatter = Formatter()
        self.citation_inserter = CitationInserter()
        self.validator = AnswerValidator()

    def compose(self, draft: str, tool_results: list) -> str:
        answer = draft + self.formatter.format_tool_section(tool_results)
        answer = self.citation_inserter.insert(answer, tool_results)
        if not self.validator.validate(answer):
            return "I could not produce a reliable answer."
        return answer
