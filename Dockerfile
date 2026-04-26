FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install deps for cryptography wheels + ssh + wg-quick (for local reload mode)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libssl-dev libffi-dev \
        openssh-client iproute2 wireguard-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY vpn_bot ./vpn_bot

VOLUME ["/data"]
ENV DB_PATH=/data/vpn-bot.db
EXPOSE 8081

CMD ["python", "-m", "vpn_bot"]
