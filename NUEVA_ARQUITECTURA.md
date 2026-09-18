# Nueva arquitectura: dos bots + AutoDJ

## Servicios

- **main-bot**: comandos generales, moderación, emotes, propinas, posiciones y vestuario del bot principal.
- **music-bot**: solo música y administración del avatar del bot de música.
- **AutoDJ**: motor de reproducción independiente de Highrise.
- **Icecast**: servidor de streaming público.

```
                         HIGHRISE
                            |
              +-------------+-------------+
              |                           |
         main-bot                    music-bot
       comandos generales       !play !skip !q !review
       avatar/posición          !ap !rp
       !color !equip            !set !home
       !remove !getoutfit       !color !equip
                                 !remove !getoutfit
                                      |
                                      v
                                    AutoDJ
                                      |
                                      v
                                    Icecast
                                      |
                                      v
                              stream /stream
```

## Independencia

AutoDJ no depende de que ningún bot de Highrise esté conectado.

- Si **main-bot** se desconecta: la música continúa.
- Si **music-bot** se desconecta: la música continúa.
- Si ambos se desconectan: AutoDJ e Icecast continúan mientras sus contenedores sigan activos.
- Al reiniciar AutoDJ, la cola de solicitudes se recupera desde `request_queue.json`.

## Prioridad musical

- `!play` agrega una solicitud a la cola.
- Si está sonando una pista de la playlist por defecto, la solicitud activa una transición prioritaria.
- Las solicitudes no interrumpen otra solicitud que ya esté sonando.
- `!skip` detiene la pista actual y AutoDJ selecciona la siguiente solicitud; si no hay solicitudes, vuelve a la playlist por defecto.
- La salida de audio hacia Icecast es un único proceso FFmpeg persistente. No se reinicia por cada canción.

## Estado y archivos

El volumen `autodj_data` contiene:

- `request_queue.json`
- `default_playlist.json`
- caché de audio

Las posiciones de los bots son independientes:

- `data.json` → bot principal.
- `music_bot_data.json` → bot de música.

El vestuario también es independiente porque `!color`, `!equip`, `!remove` y `!getoutfit` se ejecutan contra la sesión Highrise del bot que recibe el comando.

## AWS

En la EC2:

```bash
cd ~/highrise-bot
docker compose up -d --build
docker compose ps
docker compose logs -f autodj
```

Publica en el Security Group únicamente el puerto que realmente necesites:

- **8000/TCP** → Icecast público.
- **8090/TCP** → NO publicar; AutoDJ es interno de Docker.
- Los bots no necesitan puertos públicos para conectarse a Highrise.

Stream:

```
http://TU_IP_PUBLICA:8000/stream
```

## Variables

Usa `.env.example` como plantilla. Las credenciales reales deben permanecer fuera de Git.

Necesitas dos credenciales de bot de Highrise:

- `ROOM_ID` + `API_KEY` para main-bot.
- `MUSIC_ROOM_ID` + `MUSIC_API_KEY` para music-bot.

Y las credenciales de AutoDJ/Icecast:

- `AUTODJ_TOKEN`
- `ICECAST_PASSWORD`
- `ICECAST_SOURCE`
- `ICECAST_MOUNT`

## Seguridad

No subas:

- `.env`
- `cookies.txt`
- claves privadas SSH
- tokens de AutoDJ

Si una clave privada SSH ya fue subida públicamente al repositorio, debe considerarse comprometida y **revocarse/rotarse** antes de continuar usando ese acceso.
