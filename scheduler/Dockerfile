FROM python:3.12-slim
# docker.io on this base only pulls in dockerd (the daemon), not the CLI —
# docker-cli + docker-compose give the `docker` binary and `docker compose`
# (v2 subcommand syntax), both of which crawler.py's subprocess call needs.
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli docker-compose && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
