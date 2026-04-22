import uuid


def new_trace_id() -> str:
    return str(uuid.uuid4())
