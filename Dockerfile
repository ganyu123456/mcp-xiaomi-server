FROM python:3.11-slim AS builder

WORKDIR /app

# python-miio pulls in C-extension deps (e.g. netifaces); build them here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Self-contained, statically linked ffmpeg (multi-arch) for the camera RTSP tools.
# Copying a single ~40MB binary avoids apt-installing the full ffmpeg codec chain
# (~250MB of transitive deps), and camera.py never calls ffprobe.
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM python:3.11-slim

WORKDIR /app

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Runtime deps are already installed above; add the package to the import path
# directly instead of a second pip install (avoids duplicating dependencies).
COPY src/ ./src/
ENV PYTHONPATH=/app/src

ENV MCP_TRANSPORT=sse
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8092
ENV MCP_XIAOMI_DEVICES=/app/config/devices.json
ENV MCP_XIAOMI_TIMEOUT=5

RUN mkdir -p /app/config

EXPOSE 8092

VOLUME ["/app/config"]

ENTRYPOINT ["python", "-m", "mcp_xiaomi_server.server"]
