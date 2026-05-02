class AnswerValidator:
    def validate(self, text: str) -> bool:
        return bool(text and text.strip())
