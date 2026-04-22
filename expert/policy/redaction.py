import re


class Redactor:
    def redact(self, text: str) -> str:
        text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', "[REDACTED_EMAIL]", text)
        text = re.sub(r'(?i)api[_-]?key\s*[:=]\s*\S+', "api_key=[REDACTED]", text)
        return text
