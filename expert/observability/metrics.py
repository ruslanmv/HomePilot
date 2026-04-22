class Metrics:
    def emit(self, name: str, value: float, tags: dict | None = None):
        return {"metric": name, "value": value, "tags": tags or {}}


metrics = Metrics()
