# DOCUMENTACIÓN DEL PROYECTO HIGHRISE-BOT

> Documentación técnica de la rama `refactor/bot-structure`, basada en la revisión del código disponible.
>
> **Seguridad:** no almacenar aquí API keys, tokens, cookies, contraseñas, claves SSH ni otros secretos.

## 1. Arquitectura

El proyecto está organizado alrededor de dos bots de Highrise y servicios auxiliares:

- **Zeta / `main-bot`**: bot general de sala.
- **Dj.Z / `music-bot`**: bot dedicado a música y funciones relacionadas.
- **AutoDJ**: servicio de reproducción automática.
- **Icecast**: servidor de streaming continuo.
- **Docker Compose**: orquestación de los servicios.
- **JSON**: persistencia de roles, posiciones, emotes y datos del bot.

El punto de entrada de Zeta es `bots/bot1/main.py`.

## 2. Inicio de Zeta

Al recibir `on_start`, Zeta:

1. obtiene su `bot_id` y el `owner_id` de la sala;
2. marca el bot como activo;
3. anuncia su conexión;
4. restaura la posición guardada;
5. restaura el vestuario;
6. restaura el estado de baile/emote;
7. inicia los anuncios periódicos;
8. inicia el monitor de pista si existe `pista_emotes`;
9. mantiene un endpoint HTTP `/health`.

El puerto del health server procede de `PORT` y tiene `10000` como valor predeterminado.

## 3. Roles

Los roles usados por Zeta son:

- `owner`
- `mod`
- `vip`
- `designer`
- `user`

La ayuda se genera según el rol del usuario.

### Permisos generales

- **user:** funciones públicas.
- **vip:** funciones públicas y acciones de movimiento protegidas, como `!tele` y `!summon`.
- **mod:** funciones de moderación y acciones administrativas protegidas.
- **designer:** funciones de vestuario/color.
- **owner:** administración completa.

## 4. Comandos de Zeta

### Ayuda

| Comando | Descripción |
|---|---|
| `!help` | Muestra la ayuda disponible para el usuario. |
| `!help music` | Pertenece al bot de música; Zeta lo ignora. |

### Emotes

| Comando | Descripción |
|---|---|
| `!random` | Ejecuta emotes aleatorios sobre el usuario. |
| `!stop` | Detiene los emotes activos del usuario. |
| `!<emote>` | Ejecuta un emote definido en `emotes.json`. |
| `!<número>` | Ejecuta un emote por índice. |

`emotes.json` define comando, ID, duración y autorización. Los emotes protegidos requieren los permisos establecidos por el código.

### Diversión

| Comando | Descripción |
|---|---|
| `!fight @usuario` | Interacción de pelea mediante emotes. |
| `!kiss @usuario` | Envía un beso. |
| `!heart @usuario` | Envía un corazón. |
| `!love @usuario` | Calcula/muestra compatibilidad. |
| `!superpunch @usuario` | Ejecuta el efecto de superpunch; los bots no pueden ser objetivo. |

### Movimiento

| Comando | Descripción |
|---|---|
| `!follow` | Zeta sigue al usuario que lo ejecuta. |
| `!follow @Zeta_Bot` | Forma dirigida al bot. |
| `!stopfollow` | Detiene el seguimiento. |
| `!summon @usuario` | Invoca al usuario hasta la posición del ejecutor; requiere acceso VIP/mod/owner. |
| `!tele @usuario` | Teletransporta al ejecutor hasta el usuario; requiere acceso VIP/mod/owner. |

El seguimiento utiliza una tarea asíncrona que consulta periódicamente la posición del objetivo.

### Ubicaciones

| Comando | Descripción |
|---|---|
| `!ubi` | Lista las ubicaciones guardadas. |
| `!ubi nombre` | Guarda la posición actual con ese nombre. |
| `!ubi nombre vip` | Guarda una posición con acceso VIP. |
| `!ubi nombre mod` | Guarda una posición con acceso de moderador. |
| `!u nombre` | Alias para guardar posición. |
| `!removeubi nombre` | Elimina una posición. |
| `!ru nombre` | Alias para eliminar posición. |
| `nombre` / `!nombre` | Teletransporta a una posición guardada cuando el usuario tiene permiso. |

Crear una posición con acceso restringido requiere owner/mod. Eliminar posiciones también requiere owner/mod.

### Propinas

| Comando | Descripción |
|---|---|
| `!top` | Ranking de propinas. |
| `!wallet` | Consulta la billetera del bot. |
| `!get @usuario` | Consulta las propinas de un usuario. |
| `!tipme cantidad` | Envía oro al usuario mediante la función protegida. |
| `!tip @usuario cantidad` | Envía oro a un usuario. |
| `!tipall cantidad` | Envía oro a todos los usuarios elegibles. |
| `!tip all cantidad` | Alias de `!tipall`. |

`!tipall` excluye al propio bot y a los bots configurados mediante `BOT1_USERNAME` y `DJ_BOT_USERNAME`. Esto evita el error de Highrise `Bots can't tip other bots.`. El comando informa de enviados y fallidos.

### Información

| Comando | Descripción |
|---|---|
| `!userinfo` | Información del usuario que ejecuta el comando. |
| `!userinfo @usuario` | Información de otro usuario. |

### Moderación

| Comando | Descripción |
|---|---|
| `!kick @usuario` | Expulsa al usuario. Requiere moderación. |
| `!tp @usuario x y z` | Teletransporta al usuario a las coordenadas indicadas. Requiere permisos protegidos. |

### Administración

| Comando | Descripción |
|---|---|
| `!set @Zeta_Bot` | Guarda la posición del bot. |
| `!home` | Devuelve Zeta a la posición guardada. |
| `!home @Zeta_Bot` | Forma dirigida. |
| `!reset` | Reinicia el proceso del bot. |
| `!reset @Zeta_Bot` | Forma dirigida. |
| `!role @usuario mod\|vip\|designer` | Asigna un rol. |
| `!role @usuario delete [rol]` | Elimina un rol concreto o los roles correspondientes. |

`!home` y `!reset` requieren owner/mod. Los comandos dirigidos validan el nombre del bot.

### Baile y emote persistente del bot

| Comando | Descripción |
|---|---|
| `!dancebot @Zeta_Bot` | Activa baile aleatorio del bot. |
| `!stopdance @Zeta_Bot` | Detiene el baile. |
| `!botdance @Zeta_Bot` | Alias contemplado por la capa protegida. |
| `!stopbotdance @Zeta_Bot` | Alias contemplado por la capa protegida. |
| `!emote @Zeta_Bot rest` | Inicia emote persistente. |
| `!emote @Zeta_Bot stop` | Detiene el emote persistente. |

El control directo del emote del bot está protegido para owner/mod.

### Vestuario

| Comando | Descripción |
|---|---|
| `!color categoría número` | Cambia el color de una categoría. |
| `!equip nombre`, ID o URL | Equipa una prenda. |
| `!remove categoría` | Elimina una categoría. |
| `!getoutfit` | Muestra el vestuario actual. |

Estas funciones están protegidas y se pueden dirigir al bot correspondiente.

## 5. Comandos exclusivos de Dj.Z

La arquitectura separa los comandos `!mtip` y `!mtipall` de Zeta. Zeta los bloquea al principio de `on_chat` y tampoco los procesa en `command_handler`.

Por tanto:

- `!mtip ...` → Dj.Z.
- `!mtipall ...` → Dj.Z.
- Zeta → no responde a esos comandos.

La documentación de comandos musicales debe mantenerse sincronizada con los módulos reales de `bots/dj` y no debe inventar comandos no implementados.

## 6. Eventos principales

Zeta implementa:

- `on_start`: inicialización.
- `on_chat`: entrada principal de comandos.
- `on_user_join`: aplica roles guardados y envía bienvenida privada a todos los usuarios que entran.
- `on_user_leave`: cancela tareas asociadas y limpia posiciones en memoria.
- `on_tip`: registra/procesa propinas recibidas.

## 7. Persistencia y archivos de configuración

La configuración se obtiene mediante `config.py` y variables de entorno. El bot utiliza JSON para datos persistentes, incluyendo recursos de roles, posiciones, emotes y datos generales.

Los archivos de estado no deben modificarse manualmente sin conocer su esquema.

## 8. AutoDJ e Icecast

La arquitectura de radio separa:

```text
Highrise music-bot
        │
        ▼
      AutoDJ
        │
        ▼
     Icecast
        │
        ▼
      Stream
```

La finalidad es mantener el stream continuo y cambiar la reproducción cuando corresponde, evitando reiniciar innecesariamente el servidor Icecast.

Icecast puede existir como contenedor separado del Compose utilizado para los bots. Por eso no se debe ejecutar un `docker compose up -d` completo sin comprobar primero la topología actual.

## 9. Docker en AWS

Servicios utilizados por el despliegue:

- `main-bot`
- `music-bot`
- `autodj`
- `icecast` cuando está gestionado por separado.

El volumen externo de AutoDJ utilizado por el entorno es:

```text
refactor-test_autodj_data
```

No eliminar este volumen durante una limpieza normal.

## 10. AWS EC2: procedimiento de despliegue

Ruta de trabajo del servidor:

```bash
~/highrise-bot-refactor
```

### 10.1 Comprobar estado

```bash
cd ~/highrise-bot-refactor
git status
git branch --show-current
git log -1 --oneline
```

La rama de trabajo es:

```text
refactor/bot-structure
```

### 10.2 Actualizar código

```bash
git pull --ff-only origin refactor/bot-structure
```

Usar `--ff-only` para evitar merges accidentales durante el despliegue.

### 10.3 Actualizar Zeta

```bash
docker compose build main-bot
docker compose up -d --no-deps main-bot
docker logs --tail=40 highrise-main-bot
```

`--no-deps` es importante cuando se quiere actualizar únicamente Zeta y evitar tocar otros servicios.

### 10.4 Actualizar otros servicios

Seleccionar explícitamente el servicio modificado y evitar reinicios innecesarios del stack completo.

### 10.5 Diagnóstico de contenedores

```bash
docker ps -a
docker compose ps
docker compose images
```

Logs de Zeta:

```bash
docker logs --tail=100 highrise-main-bot
```

## 11. Copia local → AWS

El flujo de trabajo utilizado contempla preparar los archivos localmente y copiarlos mediante `robocopy`, excluyendo elementos que no deben formar parte del despliegue, como `.venv`, `.github`, cachés, `deploy`, pruebas cuando el procedimiento lo indique y archivos privados.

La lista exacta de exclusiones debe mantenerse en el procedimiento real de despliegue. Nunca copiar secretos innecesariamente.

## 12. Variables de entorno

Variables identificadas directamente en el código de Zeta:

| Variable | Uso |
|---|---|
| `ROOM_ID` | Sala de Highrise. |
| `API_KEY` | Credencial de Highrise. |
| `BOT1_USERNAME` | Nombre configurado de Zeta. |
| `DJ_BOT_USERNAME` | Nombre configurado de Dj.Z. |
| `PORT` | Puerto del health server. |

No guardar valores reales en Git.

La infraestructura de música utiliza además variables propias para sala, API, AutoDJ, tokens y configuración de reproducción; sus valores deben mantenerse fuera de este documento.

## 13. Seguridad

Nunca subir al repositorio:

- API keys;
- tokens de bots;
- cookies de yt-dlp;
- contraseñas de Icecast;
- credenciales AWS;
- claves SSH;
- archivos `.env` con secretos.

Antes de borrar archivos o contenedores, comprobar qué datos persistentes contienen.

## 14. Backups y Git

Existe una rama de respaldo utilizada en la limpieza anterior:

```text
backup/pre-cleanup-2026-09-20
```

Evitar sin verificación previa:

```bash
git reset --hard
git clean -fd
git push --force
```

En AWS, preferir `git pull --ff-only`.

## 15. Health check

Endpoint:

```text
GET /health
```

Respuesta normal:

```text
ok
```

Puerto predeterminado: `10000`, configurable mediante `PORT`.

## 16. Checklist después de desplegar Zeta

- [ ] Contenedor `highrise-main-bot` está `Running`.
- [ ] Los logs muestran conexión correcta a Highrise.
- [ ] Se restaura la posición del bot.
- [ ] `!help` funciona según el rol.
- [ ] `!userinfo` funciona.
- [ ] `!follow` / `!stopfollow` funcionan.
- [ ] `!ubi` funciona.
- [ ] `!wallet`, `!top` y `!get` respetan permisos.
- [ ] `!tipall 1` no intenta enviar oro a Zeta ni Dj.Z.
- [ ] `!mtipall 1` sigue siendo exclusivo de Dj.Z.
- [ ] `!home` funciona.
- [ ] `!reset` funciona sobre el bot solicitado.
- [ ] Vestuario y emotes respetan permisos.
- [ ] Icecast y AutoDJ no fueron reiniciados accidentalmente.

## 17. Mantenimiento de esta documentación

Cada modificación de comandos, permisos, servicios, variables de entorno, volúmenes Docker o procedimientos AWS debe reflejarse aquí en el mismo cambio.

La documentación debe describir el comportamiento real de la rama desplegada y distinguir claramente entre funcionalidades implementadas y funcionalidades planificadas.


---

# ANEXO TÉCNICO — INVENTARIO COMPLETO Y OPERACIÓN DEL STACK

> Este anexo complementa las secciones anteriores. Está basado en los archivos presentes en la rama `refactor/bot-structure` y en el historial de trabajo conocido. Los valores secretos no se documentan. Los puntos que dependen de la configuración real del servidor se marcan como **verificar en AWS**.

## 18. Inventario de procesos y servicios

| Servicio Compose | Contenedor | Función | Persistencia/configuración importante |
|---|---|---|---|
| `main-bot` | `highrise-main-bot` | Bot principal, conocido como Zeta. Comandos generales, emotes, roles, posiciones, propinas, movimiento y administración. | `.env`, `common/emotes.json`, `roles.json`, archivos de datos del bot. |
| `music-bot` | `highrise-music-bot` | Bot de música, conocido como Dj.Z. Se comunica con AutoDJ y administra solicitudes/funciones musicales. | `.env`, `bots/dj/data/music_bot_data.json`, variables de música. |
| `fun-bot` | `highrise-fun-bot` | Bot de juegos: Bomba, Dados 21, Piedra-Papel-Tijera y Verdad o Reto. | `.env`, `bots/fun/data/data.json`, `bots/fun/data/dados21_wallet.json`, `common/emotes.json`, `roles.json`. |
| `ghost-wave-bot` | `highrise-ghost-wave-bot` | Automatización de eventos Ghost Wave y administración de salas, usuarios y conversaciones. Es independiente del club principal. | `.env`, volumen persistente `./bots/ghost_wave/data:/app/bots/ghost_wave/data`. |
| `autodj` | `highrise-autodj` | API/servicio de reproducción automática y descarga/gestión de medios. | Volumen externo `refactor-test_autodj_data`, carpeta `default_music`, cookies de YouTube montadas desde `services/cookies.txt`. |
| `liquidsoap` | `highrise-liquidsoap` | Procesamiento/continuidad del audio hacia Icecast. | Configuración en `autodj/liquidsoap/radio-test.liq`; volumen compartido `autodj_data`. |
| `icecast` | `highrise-icecast` | Servidor de streaming de audio. Publica el stream en el puerto 8000. | Volúmenes `icecast_config`, `icecast_config_data` e `icecast_logs`; contraseñas en variables de entorno. |

Los nombres de servicio de Compose no son necesariamente iguales a los nombres de contenedor. Usar `docker compose ps` para comprobar la topología efectiva antes de operar.

### 18.1 Red interna

Los servicios están conectados a la red Docker `highrise`. El bot de música usa `AUTODJ_URL=http://autodj:8090`; AutoDJ y Liquidsoap se conectan a Icecast por el nombre de servicio interno `icecast`, puerto 8000. El puerto de Icecast publicado al host es `8000:8000`; AutoDJ usa el puerto interno 8090.

### 18.2 Flujo de música

```text
Usuarios de Highrise
       |
       v
music-bot (Dj.Z) ---- API HTTP ----> autodj:8090
                                      |
                                      v
                                  liquidsoap
                                      |
                                      v
                                  icecast:8000
                                      |
                                      v
                                  URL pública del stream
```

No reiniciar Icecast, AutoDJ o Liquidsoap para publicar un cambio que solo afecte a Zeta o al bot de juegos. En ocasiones anteriores hubo problemas de mount/403 en Icecast; revisar los logs y la configuración del mount antes de cambiar el stack de audio.

## 19. Bot de juegos: comandos y reglas

El punto de entrada es `bots/fun/main.py`. Los módulos de juego se encuentran en `bots/fun/games/`. La ayuda privada `!help` se envía por bloques separados, uno por juego, para que sea más legible. En sala, `!help game` muestra la ayuda de juegos agrupada por juego.

### 19.1 Ayuda

| Comando | Función |
|---|---|
| `!help` | Ayuda de juegos por mensaje privado/inbox. |
| `!help game` | Ayuda de juegos en el chat de sala. |
| `!help bomba` | Ayuda de Bomba. |
| `!help dados` | Ayuda de Dados 21. |
| `!help rps` | Ayuda de Piedra-Papel-Tijera. |
| `!help verdad` | Ayuda de Verdad o Reto. |

### 19.2 Bomba

| Comando/acción | Función |
|---|---|
| `!bomba` | Crear una partida; el creador queda inscrito automáticamente. |
| `jugar` | Entrar a la partida abierta. |
| `salir` | Salir de la partida. |
| `terminar` | El creador detiene la partida. |
| Mensaje de texto | Durante la ronda, enviar una palabra válida de la categoría y letra indicadas. |

Configuración confirmada en el módulo:

- Inscripción inicial: `LOBBY_SECONDS = 20` segundos.
- Duración máxima de cada ronda: `ROUND_SECONDS = 30` segundos.
- Pausa entre rondas: `RETURN_SECONDS = 15` segundos en el último cambio documentado.
- Categorías: animales; frutas y verduras; países y ciudades; comidas y bebidas; cosas; nombres propios; colores.
- Se valida que la palabra empiece por la letra indicada, pertenezca al diccionario local y no se haya usado en la ronda.
- La ronda termina antes de los 30 segundos cuando todos los jugadores activos responden correctamente.
- Quien falla no queda eliminado de la partida: se le aplica el efecto de explosión/teletransporte y puede continuar.
- Quien se inscribe en medio de una ronda comienza a responder desde la siguiente.
- El teletransporte se genera dentro de los límites configurados en el código: X 0–20, Y 0–35, Z 0–30.
- El diccionario está en `bots/fun/data/bomba_dictionary.json`.

**Nota de despliegue:** los 15 segundos están confirmados en el cambio de código de GitHub; verificar en AWS que se haya hecho `git pull`, reconstrucción y reinicio de `fun-bot` antes de afirmar que ya corre en producción.

### 19.3 Dados 21

| Comando | Función |
|---|---|
| `!dados21 100` | Entrar apostando 100 G. La apuesta debe estar entre 10 y 100 G en múltiplos de 10. |
| `!tirar` | Tirar un dado durante el turno. |
| `!doble` | Tirar dos dados. |
| `!plantarse` | Terminar las tiradas del jugador. |
| `!saldo` | Consultar el saldo de la cartera; la respuesta se envía por privado. |
| `!depositar cantidad` | Registrar una solicitud de depósito; después hay que enviar la propina exacta al bot. |
| `!retirar cantidad` | Solicitar retirada de saldo, sujeto a las reglas del juego. |
| `!salir` | Salir cuando el estado de partida lo permita. |

Parámetros encontrados en código: inscripción de 15 segundos, límite de 15 segundos por turno, apuesta mínima de 10 G, máxima de 100 G y paso de 10 G. El retiro mínimo definido es 50 G. La cartera se guarda en `bots/fun/data/dados21_wallet.json`, mediante la capa de almacenamiento configurada. El sistema procesa las propinas recibidas para reconocer depósitos; no asumir que el saldo se actualiza sin que el evento de propina se haya procesado correctamente.

**Restricción de partida:** el juego gestiona un estado global de fase/turno; no se debe iniciar otra partida mientras exista una partida en curso.

### 19.4 Piedra, Papel o Tijera (RPS)

| Comando | Función |
|---|---|
| `!rps` | Jugar contra BotJuegos. |
| `!rps @usuario` | Retar a otro jugador. |
| `!rps @usuario 10` | Reto con apuesta, cuando se especifica una cantidad permitida. |
| `!piedra` / `!papel` / `!tijera` | Elegir jugada. También se reconocen las formas sin signo de exclamación. |

Parámetros encontrados: elección con límite de 40 segundos; ventana de apuestas de 60 segundos; pausa entre mensajes de 2 segundos. Las apuestas permitidas en el módulo son 10, 50, 100 y 500 G. Los pagos y reembolsos están definidos en constantes del código y contemplan las comisiones de Highrise. Cada usuario se asocia a una partida activa para impedir que participe simultáneamente en varias.

### 19.5 Verdad o Reto

Comandos anunciados por la ayuda del propio bot:

| Comando | Función |
|---|---|
| `!vd` | Iniciar/jugar en modo individual. |
| `!jugarvd` | Entrar al juego. |
| `!entrarvd` | Alias para entrar. |
| `!iniciarvd` | Iniciar la sesión cuando corresponda. |
| `!verdad` | Elegir verdad. |
| `!reto` | Elegir reto. |
| `!listo` | Confirmar que se está listo, según el estado de la sesión. |
| `!salirvd` | Salir del juego. |

El módulo gestiona eventos de movimiento y salida de usuarios. Revisar `bots/fun/games/verdad_reto.py` antes de modificar reglas, tiempos, categorías o el flujo de entrada/salida.

## 20. Configuración de emotes y baile

El catálogo común se mantiene en `common/emotes.json`. Cada elemento puede contener identificador de emote, nombre/comando, duración y autorización. Los elementos marcados `disabled: true` no se cargan al catálogo activo. El bot principal puede registrar nuevos emotes descubiertos y guardar el catálogo sin reactivar los deshabilitados.

Valores de repetición confirmados en los cambios recientes:

| Emote/grupo | Porcentaje |
|---|---:|
| Emotes generales | 94 % |
| `emote-solo-pumpkindance-left` | 92 % |
| `emote-jumpscared3` | 70 % |

Los porcentajes se aplican en la lógica de repetición de baile; no significan que el emote dure ese porcentaje del tiempo. Los tiempos/duraciones individuales se configuran aparte. Archivos involucrados: `bots/bot1/main.py` y `common/dance.py`.

### 20.1 Comandos principales de Zeta (resumen operativo)

La sección 4 contiene el inventario general. Estos comandos son especialmente relevantes durante las pruebas:

- Ayuda: `!help`.
- Emotes: `!random`, `!stop`, `!randomall` (según permisos), `!<comando-emote>` y comandos por índice.
- Seguimiento: `!follow`, `!stopfollow`.
- Ubicaciones: `!ubi`, `!ubi nombre`, `!removeubi nombre`; alias `!u` y `!ru`.
- Propinas: `!top`, `!wallet`, `!get @usuario`, `!tip @usuario cantidad`, `!tipall cantidad`.
- Moderación: `!kick @usuario`, `!tp @usuario x y z`.
- Roles: `!role @usuario mod|vip|designer` y opciones de eliminación.
- Vestuario: `!color`, `!equip`, `!remove`, `!getoutfit`.
- Control del bot: `!set`, `!home`, `!reset`, `!dancebot`, `!stopdance`, `!emote @Zeta_Bot rest/stop`.

Los permisos varían por rol; no probar comandos administrativos con una cuenta sin autorización. Los nombres de bot usados en menciones deben coincidir con la configuración real de la sala.

## 21. Variables de entorno y secretos

Las variables se cargan desde `.env` por Compose. Este documento describe nombres/función, nunca sus valores reales.

### 21.1 Highrise

| Variable | Uso |
|---|---|
| `ROOM_ID` | Sala del bot principal. |
| `API_KEY` | Credencial del bot principal. |
| `BOT1_USERNAME` | Nombre esperado del bot principal; predeterminado en código: `Zeta_Bot`. |
| `DJ_BOT_USERNAME` | Nombre esperado de Dj.Z para filtros/dirigidos. |
| `BOT3_ROOM_ID` | Sala del bot de juegos. |
| `BOT3_API_KEY` | Credencial del bot de juegos. |
| `BOT3_USERNAME` | Nombre del bot de juegos; predeterminado: `BotJuegos`. |
| `MUSIC_ROOM_ID` | Sala del bot musical; si falta, el código consulta `ROOM_ID`. |
| `MUSIC_API_KEY` | Credencial del bot musical. |
| `PORT` | Puerto del endpoint de salud de Zeta; predeterminado 10000. |

### 21.2 Música/streaming

| Variable | Uso |
|---|---|
| `AUTODJ_URL` | URL interna de AutoDJ; predeterminado en el bot musical `http://autodj:8090`. |
| `AUTODJ_TOKEN` | Token para autorizar llamadas a AutoDJ. |
| `AUTODJ_HOST` / `AUTODJ_PORT` | Interfaz y puerto del servicio AutoDJ; Compose define 0.0.0.0:8090. |
| `YOUTUBE_COOKIES_PATH` | Ruta interna de cookies para yt-dlp; Compose la fija en `/app/cookies.txt`. |
| `ICECAST_HOST` / `ICECAST_PORT` | Host/puerto interno de Icecast para Liquidsoap. |
| `ICECAST_PASSWORD` | Contraseña fuente de Icecast. |
| `ICECAST_ADMIN_PASSWORD` | Contraseña administrativa de Icecast. |
| `ICECAST_PUBLIC_HOST` | Nombre público anunciado a Icecast; valor alternativo en Compose: localhost. |
| `ICECAST_MOUNT` | Mount de streaming; Compose usa `stream` si no se define. |

### 21.3 Ghost Wave

| Variable | Uso |
|---|---|
| `GHOST_WAVE_ROOM_ID` | Sala del bot de eventos. |
| `GHOST_WAVE_API_KEY` | Credencial del bot. |
| `GHOST_WAVE_TIMEZONE` | Zona horaria; el historial de operación indica `America/Caracas` en el servidor. Compose declara UTC como valor alternativo. |
| `GHOST_WAVE_DEFAULT_INTERVAL` | Intervalo por defecto en minutos; Compose usa 75 si no se configura. |
| `GHOST_WAVE_DATA_FILE` | Archivo persistente; Compose lo define en `/app/bots/ghost_wave/data/ghost_wave.json`. |

### 21.4 Supabase

| Variable | Uso |
|---|---|
| `SUPABASE_URL` | URL del proyecto Supabase. |
| `SUPABASE_KEY` | Clave de acceso utilizada por la capa REST. |

La capa `services/storage.py` usa la tabla `bot_files` con columnas `file_name` y `content`. Si la conexión o consulta remota falla, intenta usar el archivo local y valores predeterminados. Debe confirmarse el esquema exacto y las políticas de acceso directamente en el proyecto Supabase; no se incluyen credenciales aquí.

**Seguridad:** no pegar el contenido de `.env`, cookies o claves privadas en chats, issues, commits o capturas. Si una clave se expone, rotarla.

## 22. Estructura del repositorio

La estructura observada y los módulos más importantes son:

```text
Highrise-bot/
├── bots/
│   ├── bot1/
│   │   ├── main.py                 # Zeta: punto de entrada principal
│   │   ├── services/               # Seguimiento, anuncios, propinas, diversión
│   │   └── data/                   # Datos/posiciones persistentes
│   ├── dj/
│   │   ├── music_bot.py            # Dj.Z
│   │   ├── services/youtube.py     # Búsqueda/metadata de YouTube
│   │   └── data/                   # Datos del bot musical
│   ├── fun/
│   │   ├── main.py                 # BotJuegos
│   │   ├── games/
│   │   │   ├── bomba.py
│   │   │   ├── dados21.py
│   │   │   ├── rps.py
│   │   │   ├── verdad_reto.py
│   │   │   └── chat_queue.py
│   │   └── data/                   # Datos del juego y cartera
│   └── ghost_wave/                 # Bot de eventos Ghost Wave
├── commands/                       # Despacho de comandos comunes
├── common/                         # Estado, baile, emotes, avatar, posiciones, filtros
├── services/                       # Roles, almacenamiento, pacing y tickets musicales
├── autodj/
│   ├── autodj.py
│   ├── liquidsoap_controller.py
│   └── liquidsoap/radio-test.liq
├── infra/
│   ├── Dockerfile.bot
│   ├── Dockerfile.autodj
│   ├── Dockerfile.liquidsoap
│   └── patch_highrise_sdk.py
├── default_music/                  # Música local opcional
├── common/emotes.json              # Catálogo común de emotes
├── roles.json                      # Roles/permisos persistentes
├── config.py                       # Rutas y variables del bot principal
├── docker-compose.yml              # Servicios de producción/despliegue
└── DOCUMENTACION_BOT.md            # Este documento
```

La lista es un mapa de los módulos principales, no un inventario exhaustivo de cada archivo. Antes de borrar o renombrar rutas, revisar imports y volúmenes declarados en Compose.

## 23. AWS EC2: rutina segura de operación

Directorio conocido del proyecto en el servidor: `~/highrise-bot-refactor`. Rama de despliegue: `refactor/bot-structure`.

### 23.1 Comprobar estado antes de cambiar nada

```bash
cd ~/highrise-bot-refactor
git status --short
git branch --show-current
git log -1 --oneline
docker compose ps
```

Si hay cambios locales sin confirmar, no sobrescribirlos a ciegas. Investigar antes de ejecutar `git pull`.

### 23.2 Actualizar solo Zeta/emotes

```bash
git pull --ff-only origin refactor/bot-structure
python -m compileall -q bots/bot1 common
docker compose build main-bot
docker compose up -d --no-deps main-bot
docker compose logs --tail=100 main-bot
```

### 23.3 Actualizar solo el bot de juegos

```bash
git pull --ff-only origin refactor/bot-structure
python -m compileall -q bots/fun
docker compose build fun-bot
docker compose up -d --no-deps fun-bot
docker compose logs --tail=100 fun-bot
```

### 23.4 Actualizar ambos después de un mismo pull

```bash
cd ~/highrise-bot-refactor
git pull --ff-only origin refactor/bot-structure
python -m compileall -q bots/fun bots/bot1 common
docker compose build fun-bot main-bot
docker compose up -d --no-deps fun-bot main-bot
docker compose logs --tail=100 fun-bot main-bot
```

### 23.5 Diagnóstico y reinicio

```bash
docker compose ps
docker logs --tail=100 highrise-main-bot
docker logs --tail=100 highrise-fun-bot
docker logs --tail=100 highrise-music-bot
docker logs --tail=100 highrise-ghost-wave-bot
docker logs --tail=100 highrise-autodj
docker logs --tail=100 highrise-icecast
```

Para reiniciar un servicio sin reconstruir imagen:

```bash
docker compose restart main-bot
# o:
docker compose restart fun-bot
```

Para actualizar código Python, normalmente se necesita reconstruir la imagen del servicio antes de recrearlo. No usar `docker compose down -v`: podría eliminar datos persistentes. No borrar `refactor-test_autodj_data`, datos de Ghost Wave, carteras, cookies o configuraciones sin una copia verificada.

### 23.6 Confirmar qué versión está ejecutándose

```bash
git log -1 --oneline
docker compose ps
docker inspect -f '{{.Image}} {{.State.Status}} {{.RestartCount}}' highrise-main-bot
docker inspect -f '{{.Image}} {{.State.Status}} {{.RestartCount}}' highrise-fun-bot
```

Un commit en GitHub no significa que AWS ya lo esté ejecutando. Registrar el SHA desplegado después de cada actualización y confirmar en logs que el proceso se conectó correctamente a Highrise.

## 24. Copias de seguridad y recuperación

Antes de tocar datos persistentes:

1. Guardar una copia fechada de los JSON y de la configuración relevante, excluyendo secretos de cualquier commit.
2. Comprobar que el archivo de respaldo tiene contenido y puede leerse.
3. Confirmar qué volumen monta cada servicio.
4. No asumir que un archivo local es la fuente principal: `services/storage.py` puede usar Supabase si `SUPABASE_URL` y `SUPABASE_KEY` están definidos.
5. Tras restaurar, comprobar conteos de salas/usuarios/conversaciones y revisar logs.

Historial de operación conocido: Ghost Wave recuperó un archivo `ghost_wave.json` con 8 salas, 5 administradores, 13 suscriptores, 15 conversaciones y 15 nombres. Es una referencia histórica, no garantía de que los conteos actuales sean los mismos.

## 25. Incidencias conocidas y verificaciones pendientes

- **Ghost Wave/Compose:** anteriormente apareció el aviso de Compose `The "code" variable is not set`. Verificar si sigue presente; puede indicar una interpolación accidental de `$code` dentro de un comando Compose. En servicios con shell, las variables destinadas al shell deben escaparse como `$$code` en YAML de Compose.
- **Audio/Icecast:** hubo incidencias anteriores de conflicto de mount y respuestas HTTP 403. Antes de cambiar el mount, comprobar `ICECAST_MOUNT`, contraseña fuente, estado de Icecast y configuración de Liquidsoap.
- **Supabase:** comprobar tabla `bot_files`, acceso REST, clave utilizada y comportamiento de respaldo local.
- **Ghost Wave:** la persistencia debe quedar en el volumen montado `bots/ghost_wave/data`; verificar que el contenedor use la ruta y zona horaria esperadas.
- **AWS:** no se puede inferir desde un commit que el servicio haya sido reconstruido/reiniciado. Confirmar con `git log`, `docker compose ps` y logs.
- **Variables completas de producción:** validar en el servidor los nombres realmente presentes en `.env`; no exportar sus valores a la documentación.
- **URL pública del stream, URL/IP de EC2, reglas de firewall/seguridad, DNS y método de acceso SSH:** no quedan fijados aquí porque deben verificarse en la configuración actual de AWS y no conviene publicar datos sensibles.

## 26. Checklist general de aceptación

- [ ] `git pull --ff-only` termina sin conflictos.
- [ ] La compilación de los módulos afectados termina sin errores.
- [ ] Los servicios previstos se reconstruyen y arrancan sin reiniciar servicios ajenos al cambio.
- [ ] Los logs muestran conexión de cada bot a la sala correcta.
- [ ] Zeta: probar ayuda, permisos, emotes y porcentajes de repetición.
- [ ] BotJuegos: probar `!help game`, Bomba, Dados 21, RPS y Verdad o Reto.
- [ ] Bomba: confirmar inscripción de 20 s, rondas de hasta 30 s y pausa de 15 s entre rondas.
- [ ] Dados 21: comprobar cartera, depósitos por propina, saldo y límites de apuesta.
- [ ] Música: verificar petición/reproducción, API de AutoDJ y stream de Icecast sin duplicar mounts.
- [ ] Ghost Wave: comprobar zona horaria, intervalo y persistencia de salas/usuarios.
- [ ] Confirmar que los servicios no relacionados siguen activos.
- [ ] Anotar el SHA de GitHub desplegado y la fecha de validación.

## 27. Alcance y límites de esta documentación

Este documento describe arquitectura, comandos conocidos, parámetros identificados en el código y procedimientos seguros. No contiene los valores secretos ni pretende sustituir la verificación de la instancia EC2. Los detalles que dependen de valores actuales de `.env`, consola AWS, reglas de red, URL pública, configuración de la cuenta de Highrise o esquema de Supabase deben validarse en su fuente correspondiente.

Cuando se agregue, quite o cambie un comando, permiso, tiempo de juego, variable, volumen o servicio, actualizar esta documentación junto con el código y registrar si el cambio quedó solo en GitHub o también fue desplegado y probado en AWS.
