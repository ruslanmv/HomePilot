FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY agentic/ /app/agentic/

RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic httpx

EXPOSE 9202
CMD ["python", "-m", "uvicorn", "agentic.integrations.a2a.chief_of_staff_agent:app", "--host", "0.0.0.0", "--port", "9202"]
