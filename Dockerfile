FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates curl ffmpeg unzip \
	&& curl -fsSL https://deno.land/install.sh | sh -s v2.3.0 \
	&& ln -s /root/.deno/bin/deno /usr/local/bin/deno \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "python -u radio_player.py & exec python -u main.py"]
