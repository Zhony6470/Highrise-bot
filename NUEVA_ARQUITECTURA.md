# Arquitectura del proyecto

## Estructura

```text
highrise-bot/
├── bots/
│   ├── zeta/
│   │   ├── main.py
│   │   ├── data/
│   │   │   ├── data.json
│   │   │   └── posiciones.json
│   │   └── services/
│   │       ├── anuncios.py
│   │       ├── diversion.py
│   │       ├── tips.py
│   │       └── track.py
│   │
│   └── djz/
│       ├── music_bot.py
│       ├── data/
│       │   └── music_bot_data.json
│       └── services/
│           └── youtube.py
│
├── common/
│   └── emotes.json
│
├── commands/          # comandos compartidos/generalizados
├── services/          # servicios compartidos
├── autodj/
│   └── autodj.py
├── infra/
│   ├── Dockerfile.bot
│   └── Dockerfile.autodj
├── default_music/
├── docker-compose.yml
├── config.py
└── .env
```

## Responsabilidades

### @Zeta_Bot

Su código vive en `bots/bot1/`.

Incluye comandos y funciones propias del bot general: moderación, propinas, diversión, anuncios, pista de emotes y sus datos/posición.

### @Dj.Z

Su código vive en `bots/dj/`.

Incluye música, integración con AutoDJ, búsqueda de YouTube y sus datos/posición.

### Código compartido

`commands/` y `services/` contienen funciones que pueden reutilizar varios bots. La configuración general está en la raíz.

### AutoDJ e Icecast

AutoDJ e Icecast siguen siendo independientes de los bots de Highrise:

```text
HIGHRISE
  ├── @Zeta_Bot ───────┐
  └── @Dj.Z ───────────┤
                        ↓
                      AutoDJ
                        ↓
                      Icecast
                        ↓
                  /stream :8000
```

Si uno o ambos bots se desconectan, AutoDJ e Icecast pueden continuar reproduciendo la radio.

## Estado de avatar

La siguiente fase del sistema de avatar usará el usuario objetivo del propio bot para evitar choques entre bots:

```text
!set @Zeta_Bot
!set @Dj.Z

!home @Zeta_Bot
!home @Dj.Z

!color @Zeta_Bot ...
!color @Dj.Z ...

!equip @Zeta_Bot ...
!equip @Dj.Z ...

!remove @Zeta_Bot
!remove @Dj.Z

!getoutfit @Zeta_Bot
!getoutfit @Dj.Z
```

Los comandos de baile conservarán sus funciones existentes:

- `!dancebot @Zeta_Bot` → baile aleatorio.
- `!stopdance @Zeta_Bot` → detiene el baile aleatorio.
- `!emote @usuario <emote>` → emote específico en bucle.
- `rest @usuario` → emote específico para un usuario.
- `!emote @Zeta_Bot <emote>` → emote persistente del bot.
- `!emote @Zeta_Bot stop` → detiene el emote persistente del bot.

El estado persistente de estos comandos se implementará sobre los archivos de datos individuales de cada bot, sin compartir accidentalmente el estado entre @Zeta_Bot y @Dj.Z.

## Despliegue

Docker Compose continúa siendo el punto de entrada:

```bash
docker-compose up -d --build
docker-compose ps
```

Servicios:

- `main-bot` → `bots/bot1/main.py`
- `music-bot` → `bots/dj/music_bot.py`
- `autodj` → `autodj/autodj.py`
- `icecast` → servidor de streaming

No se deben subir al repositorio `.env`, cookies, tokens ni claves privadas.
