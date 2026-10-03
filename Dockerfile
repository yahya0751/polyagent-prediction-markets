FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build deps for any wheels that need them, then drop them
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY agent ./agent
COPY config.yaml ./

RUN pip install --upgrade pip \
 && pip install -e .

# Live trading extras are opt-in: rebuild with --build-arg LIVE=1 to include
ARG LIVE=0
RUN if [ "$LIVE" = "1" ]; then pip install -e ".[live]"; fi

# Runtime data dir (mount a volume here for persistence)
RUN mkdir -p /app/data/logs

ENV DATABASE_URL=sqlite+aiosqlite:////app/data/polyagent.db \
    KILL_SWITCH_FILE=/app/data/KILL_SWITCH

# Default: paper-mode loop. Override with `docker run … polyagent doctor` etc.
ENTRYPOINT ["polyagent"]
CMD ["run"]
