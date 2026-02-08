FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY agentic/ /app/agentic/

RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic

EXPOSE 9103
CMD ["python", "-m", "uvicorn", "agentic.integrations.mcp.decision_copilot_server:app", "--host", "0.0.0.0", "--port", "9103"]
