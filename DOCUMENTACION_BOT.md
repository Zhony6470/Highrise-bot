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
