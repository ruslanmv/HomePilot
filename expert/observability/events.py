class Events:
    def emit(self, event_type: str, payload: dict):
        return {"event_type": event_type, "payload": payload}


events = Events()
