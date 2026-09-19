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

### @Bot1

Su código vive en `bots/bot1/`.

Incluye comandos y funciones propias del bot general: moderación, propinas, diversión, anuncios, pista de emotes y sus datos/posición.

### @Dj

Su código vive en `bots/dj/`.

Incluye música, integración con AutoDJ, búsqueda de YouTube y sus datos/posición.

### Código compartido

`commands/` y `services/` contienen funciones que pueden reutilizar varios bots. La configuración general está en la raíz.

### AutoDJ e Icecast

AutoDJ e Icecast siguen siendo independientes de los bots de Highrise:

```text
HIGHRISE
  ├── @Bot1 ───────────┐
  └── @Dj ─────────────┤
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
!set @Bot1
!set @Dj

!home @Bot1
!home @Dj

!color @Bot1 ...
!color @Dj ...

!equip @Bot1 ...
!equip @Dj ...

!remove @Bot1
!remove @Dj

!getoutfit @Bot1
!getoutfit @Dj
```

Los comandos de baile conservarán sus funciones existentes:

- `!dancebot @usuario` → baile aleatorio.
- `!stopdance @usuario` → detiene el baile aleatorio.
- `!emote @usuario <emote>` → emote específico en bucle.
- `!emote stop @usuario` → detiene el emote específico.

El estado persistente de estos comandos se implementará sobre los archivos de datos individuales de cada bot, sin compartir accidentalmente el estado entre @Bot1 y @Dj.

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
