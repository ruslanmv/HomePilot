def render_template(template: str, **kwargs) -> str:
    out = template
    for key, value in kwargs.items():
        out = out.replace(f"{{{{{key}}}}}", str(value))
    return out
