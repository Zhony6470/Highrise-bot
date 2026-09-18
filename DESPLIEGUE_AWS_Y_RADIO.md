# Despliegue del bot Highrise y radio

Fecha: 2026-09-17

## Servidor AWS

- Region: `us-east-2` (Ohio).
- AMI: Ubuntu Server 24.04 LTS, 64 bits x86.
- Instancia: `i-0faf2b198184fc851`.
- Tipo: `t3.small`.
- Disco raiz: 20 GiB, gp3.
- IP publica inicial: `3.129.11.27`.
- Elastic IP actual: `16.58.84.50`.
- Host interno: `ip-172-31-25-87`.
- IP privada observada: `172.31.25.87`.

La Elastic IP debe permanecer asociada a la instancia. Es la IP para SSH, Radio Browser y oyentes.

## Red y seguridad

- SSH `22`: origen limitado a `Mi IP`.
- TCP personalizado `8000`: origen `0.0.0.0/0`, para Icecast.
- No se publican `8090` ni `10000`; son servicios internos.

Conexion desde PowerShell:

```powershell
ssh -i ".\highrise-radio-key.pem" ubuntu@16.58.84.50
```

El `.pem` es privado y nunca debe subirse al proyecto.

## Software instalado

En Ubuntu se instalaron Docker, Git, FFmpeg e Icecast2. Docker quedo habilitado y el usuario `ubuntu` pertenece al grupo `docker`.

Icecast:

```bash
sudo systemctl enable --now icecast2
sudo systemctl status icecast2 --no-pager
```

Escucha en `0.0.0.0:8000`.

URL publica:

```text
http://16.58.84.50:8000/stream
```

## Proyecto en AWS

Ruta: `/home/ubuntu/highrise-bot`

Archivos principales:

- `main.py`: conexion Highrise, ciclo de vida, comandos y avisos.
- `radio_player.py`: API interna, cola, precarga, FFmpeg e Icecast.
- `config.py`: variables de entorno y rutas.
- `anuncios.py`: anuncios periodicos.
- `diversion.py`: diversion y emotes.
- `tips.py`: propinas y rankings.
- `commands/`: dispatcher y comandos.
- `services/`: radio, YouTube, almacenamiento, roles, posiciones, emotes y pista.
- `data.json`, `roles.json`, `posiciones.json`, `emotes.json`: datos del bot.
- `Dockerfile`, `requirements.txt`: imagen y dependencias.

Excluir del despliegue: `.venv`, `.venv-1`, `tests`, `.github`, `__pycache__`, `*.pyc`, `.pem` y `cookies.txt` dentro de la imagen.

## Docker

El `Dockerfile` usa Python 3.11 slim, FFmpeg, certificados, curl, Deno 2.3.0, `yt-dlp[default]`, `yt-dlp-ejs` y `websockets<10` para compatibilidad con Supabase.

Arranca ambos procesos:

```dockerfile
CMD ["sh", "-c", "python -u radio_player.py & exec python -u main.py"]
```

Elementos usados:

- Imagen: `highrise-bot:latest`.
- Contenedor: `highrise-bot`.
- Volumen: `yt-dlp-cache`, montado en `/app/.cache`.

Operacion:

```bash
docker ps
docker logs --tail 100 highrise-bot
docker logs -f --tail 50 highrise-bot
```

Salir de logs en vivo con `Ctrl+C` no detiene el contenedor.

## Variables de entorno

Archivo privado: `/home/ubuntu/highrise-bot/.env`.

```env
ROOM_ID=...
API_KEY=...
YOUTUBE_API_KEY=...
RADIO_PLAYER_URL=http://127.0.0.1:8090
RADIO_PLAYER_TOKEN=...
SUPABASE_URL=...
SUPABASE_KEY=...
ICECAST_HOST=172.17.0.1
ICECAST_PORT=8000
ICECAST_PASSWORD=...
ICECAST_SOURCE=source
ICECAST_MOUNT=stream
PORT=10000
RADIO_PORT=8090
DEFAULT_MUSIC_DIR=/app/default_music
DEFAULT_CACHE_DIR=/app/default_cache
YOUTUBE_USE_COOKIES=1
YOUTUBE_COOKIES_PATH=/app/cookies.txt
YTDLP_CACHE_DIR=/app/.cache
YTDLP_SLEEP_REQUESTS=0.75
YTDLP_SLEEP_INTERVAL=0
YTDLP_MAX_SLEEP_INTERVAL=0
```

Los valores reales no deben escribirse en esta documentacion.

```bash
chmod 600 ~/highrise-bot/.env
chmod 600 ~/highrise-bot/cookies.txt
```

## Flujo de musica

```text
!play en Highrise
  -> YouTube Data API busca el video
  -> el bot envia video_id y metadatos a radio_player.py
  -> yt-dlp extrae el audio
  -> Deno ejecuta retos JavaScript de yt-dlp
  -> FFmpeg decodifica a PCM s16le, 44.1 kHz, estereo
  -> FFmpeg codifica MP3 a 128 kbps
  -> Icecast publica /stream:8000
```

Componentes:

- `yt-dlp`: extraccion del audio.
- `yt-dlp-ejs`: componentes JavaScript para soporte moderno de YouTube.
- Deno: aparece en logs como `[jsc:deno]`.
- FFmpeg: decodificacion, normalizacion y codificacion MP3.
- Icecast2: servidor publico de streaming.
- Cookies Netscape: se montan como `/app/cookies.txt` cuando `YOUTUBE_USE_COOKIES=1`; pueden caducar o invalidarse.

Las cookies no se incluyen en la imagen:

```bash
-v "$PWD/cookies.txt:/app/cookies.txt:ro"
```

## Cola y comandos de radio

- `!play nombre`: busca, confirma que la musica fue encontrada y la anade.
- `!q`: muestra pista actual y pendientes.
- `!skip`: solicita salto; solo dueno/moderadores. La version nueva mantiene la pista actual hasta que la siguiente esta lista para evitar silencio.
- `!reviw`: muestra cancion actual, tiempo transcurrido y duracion total.
- `!review`: alias de `!reviw`.

API interna autenticada por `RADIO_PLAYER_TOKEN`:

- `POST /play`: anadir pista.
- `GET /status`: consultar pista actual y cola.
- `POST /skip`: solicitar salto.

La siguiente pista se precarga durante la actual. Si falla, vuelve a la cola.

Las canciones de `playlist.json` se descargan una sola vez en `/app/default_cache`. Las siguientes reproducciones usan ese archivo local y no vuelven a consultar YouTube. El cache debe persistirse con un volumen Docker.

## Playlist de respaldo

La carpeta `default_music/` contiene la playlist local que suena cuando no hay solicitudes. Debe contener archivos de audio con permiso de retransmision (`.mp3`, `.wav`, `.ogg`, `.m4a`, `.flac` o `.aac`). Tambien contiene `playlist.json`, que guarda las canciones agregadas con `!addplay`.

En AWS se monta fuera de la imagen para poder cambiar la playlist sin reconstruir Docker:

```bash
-v "$PWD/default_music:/app/default_music"
```

El reproductor selecciona las pistas de respaldo en orden y evita repetir la ultima. Las solicitudes de `!play` tienen prioridad sobre la siguiente pista de respaldo disponible. `!addplay` y `!ap` agregan una cancion buscando su titulo; `!removeplay` y `!rp` la eliminan. Estos comandos requieren permisos de dueño o moderador. La cola pendiente de `!play` se guarda en `request_queue.json` para recuperarse tras reinicios. La carpeta se creo vacia con `.gitkeep`; hay que copiar canciones autorizadas a `/home/ubuntu/highrise-bot/default_music/`.

## Supabase

AWS sustituyo a Render como servidor, pero Supabase sigue siendo la persistencia. `services/storage.py` usa Supabase si existen `SUPABASE_URL` y `SUPABASE_KEY`; usa la tabla `bot_files` para `data.json`, `roles.json` y `posiciones.json`. Sin esas variables, usa JSON local.

## Mensajes conocidos

- `Emote is not free or owned by target user`: un emote de `emotes.json` no esta disponible; no afecta a la radio.
- `file_cache is only supported...`: aviso de una dependencia Google, no fallo.
- `Broken pipe`: cierre de FFmpeg/Icecast durante un salto o cambio; la logica nueva mantiene/reencola pistas.
- `Sign in to confirm you're not a bot`: bloqueo de YouTube. Deno/EJS ayudan, pero no garantizan evitarlo; las cookies pueden necesitar renovacion.

## Despliegue de cambios

PowerShell local, en la carpeta del proyecto:

```powershell
Remove-Item -Recurse -Force .\deploy -ErrorAction SilentlyContinue
robocopy . .\deploy /E /XD .venv .venv-1 tests .github __pycache__ deploy /XF *.pyc *.pem cookies.txt playlist.json request_queue.json
scp -r -i ".\highrise-radio-key.pem" .\deploy\* ubuntu@16.58.84.50:/home/ubuntu/highrise-bot/
```

AWS:

```bash
cd ~/highrise-bot
docker build -t highrise-bot .
docker rm -f highrise-bot 2>/dev/null || true
docker run -d --name highrise-bot --restart unless-stopped \
  --env-file .env \
  -v yt-dlp-cache:/app/.cache \
  -v default-audio-cache:/app/default_cache \
  -v "$PWD/default_music:/app/default_music" \
  -v "$PWD/cookies.txt:/app/cookies.txt:ro" \
  highrise-bot
```

Comprobacion:

```bash
docker ps
docker logs --tail 100 highrise-bot
curl -s http://127.0.0.1:8000/status-json.xsl
```

## Radio Browser

URL de stream:

```text
http://16.58.84.50:8000/stream
```

Datos sugeridos:

- Nombre: `Highrise Radio`.
- Codec: MP3.
- Bitrate: 128.
- Pais: Spain.
- Idioma: Spanish.
- Tags: `highrise`, `music`, `spanish`, `gaming`.

`status-json.xsl` puede mostrar solo `icestats` cuando no hay cancion. Cuando hay fuente activa debe aparecer `source`.

## Pendientes

- Desplegar la ultima version de `radio_player.py` con precarga real.
- Probar varias canciones, `!q`, `!reviw` y `!skip`.
- Confirmar cambio sin silencio cuando la siguiente pista este lista.
- Retirar emotes no disponibles.
- Considerar musica o streams con permiso de retransmision para una radio publica estable.

## Limpieza del proyecto para revision

### Necesario para ejecutar y revisar

- `main.py`, `config.py`, `radio_player.py`.
- `anuncios.py`, `diversion.py`, `tips.py`.
- `commands/` completa.
- `services/` completa.
- `Dockerfile` y `requirements.txt`.
- `data.json`, `roles.json`, `posiciones.json` y `emotes.json`.
- `.gitignore` y `.dockerignore`.
- `DESPLIEGUE_AWS_Y_RADIO.md`.
- `tests/` es recomendable conservarla para revisar regresiones, aunque no se necesita en la imagen de produccion.

### No necesario para desplegar ni revisar el codigo

- `.venv/` y `.venv-1/`: entornos virtuales locales; se recrean con `requirements.txt`.
- `__pycache__/` y archivos `*.pyc`: cache generada por Python.
- `deploy/`: copia temporal para subir a AWS; no debe contener otra carpeta `deploy`.
- `.github/agents/`: instrucciones locales de VS Code/Copilot, no codigo de ejecucion.
- `startbot.bat`: solo sirve para iniciar el bot en Windows; Docker usa el `CMD` del `Dockerfile`.
- `cookies.txt`: secreto de sesion; se monta en AWS aparte y nunca se versiona.
- `.env`: secretos y configuracion del servidor; debe existir solo en AWS o en un gestor de secretos.
- `highrise-radio-key.pem`: clave privada SSH; nunca se copia al servidor ni se sube al repositorio.
- Logs, dumps, archivos temporales, `.coverage` y directorios generados por herramientas.

### Reglas para dejar el repositorio limpio

1. Mantener el codigo fuente, configuracion no secreta, JSON de datos necesarios, pruebas y documentacion.
2. Mantener secretos fuera de Git: `.env`, `cookies.txt`, `.pem` y cualquier archivo con API keys.
3. Mantener dependencias declaradas en `requirements.txt` y el sistema en `Dockerfile`; no subir dependencias instaladas.
4. Revisar `git status` antes de publicar y buscar accidentalmente claves o tokens.
5. Crear `deploy/` solo como copia temporal y borrarla despues de subirla.

Comandos de limpieza local:

```powershell
Remove-Item -Recurse -Force .\deploy, .\.venv, .\.venv-1 -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Force -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -File -Force -Include *.pyc,*.pyo | Remove-Item -Force
```

La limpieza no debe borrar los JSON funcionales ni las carpetas `commands/` y `services/`.

## Seguridad

Nunca guardar aqui API keys, contrasenas, `RADIO_PLAYER_TOKEN`, `SUPABASE_KEY`, `cookies.txt` ni el `.pem`. La IP publica no es un secreto, pero debe actualizarse si cambia la Elastic IP.
