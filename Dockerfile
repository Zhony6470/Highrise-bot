FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates curl ffmpeg liquidsoap unzip \
	&& curl -fsSL https://deno.land/install.sh | sh -s v2.3.0 \
	&& ln -s /root/.deno/bin/deno /usr/local/bin/deno \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir --upgrade "yt-dlp[default]"

COPY . .

CMD ["sh", "-c", "set -e; echo 'Validando configuración de Liquidsoap...' ; liquidsoap --check /app/radio.liq; echo 'Iniciando radio_player y Liquidsoap...' ; python -u radio_player.py & RADIO_PID=$!; liquidsoap /app/radio.liq & LIQUIDSOAP_PID=$!; trap 'kill $RADIO_PID $LIQUIDSOAP_PID 2>/dev/null || true' TERM INT EXIT; exec python -u main.py"]
