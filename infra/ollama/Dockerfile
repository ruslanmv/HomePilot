# infra/ollama/Dockerfile
FROM ollama/ollama:latest

# Optional: preload models during build (commented out by default)
# RUN ollama serve & sleep 2 && \
#     ollama pull llama3.1 && \
#     ollama pull nomic-embed-text && \
#     pkill ollama || true

EXPOSE 11434

# Make sure Ollama listens on all interfaces inside container
ENV OLLAMA_HOST=0.0.0.0:11434

# Persist models in /root/.ollama
VOLUME ["/root/.ollama"]

CMD ["ollama", "serve"]
