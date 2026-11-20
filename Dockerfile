# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Vigie — agentic demo" \
      org.opencontainers.image.description="Minimal agentic loop: objective, tools, verification, deliverable" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.url="https://github.com/hollow313/ASUS-Agent-Computer-Challenge---High-End"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AGENTDEMO_DATA_DIR=/data

WORKDIR /app
COPY agentdemo ./agentdemo

# UID/GID 568 : identifiant des applications sur TrueNAS SCALE (et des volumes
# partagés sur la plupart des NAS). Les fichiers écrits restent donc accessibles
# depuis l'hôte sans jouer avec les permissions.
RUN groupadd --gid 568 agent \
    && useradd --uid 568 --gid 568 --home-dir /home/agent --create-home --shell /usr/sbin/nologin agent \
    && mkdir -p /data \
    && chown -R 568:568 /app /data /home/agent

USER 568:568

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2)"

CMD ["python", "-m", "agentdemo", "serve", "--host", "0.0.0.0", "--port", "8080"]
