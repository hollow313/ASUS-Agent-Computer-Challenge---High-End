# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Agent Computer — demo" \
      org.opencontainers.image.description="Minimal agentic loop: objective, tools, verification, deliverable" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTDEMO_DATA_DIR=/data

WORKDIR /app
COPY agentdemo ./agentdemo

RUN mkdir -p /data && useradd --create-home --uid 10001 agent \
    && chown -R agent:agent /app /data
USER agent

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2)"

CMD ["python", "-m", "agentdemo", "serve", "--host", "0.0.0.0", "--port", "8080"]
