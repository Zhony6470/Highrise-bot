# Ajustes realizados en Botv2

Fecha de documentación: 2026-09-19

Este documento resume los cambios realizados en la carpeta `Botv2` para mejorar la convivencia entre los bots Zeta y DJ, centralizar la lógica común y evitar conflictos entre comandos.

> Nota: estos cambios se aplicaron a `Botv2`. La copia `Botv2-AWS` no se sincronizó automáticamente.

## 1. Comandos dirigidos a un bot

Se añadió una forma explícita de indicar a qué bot pertenece un comando:

```text
!color @Dj.Z hair_front 2
!equip @Zeta_Bot shirt_basic
!home @Dj.Z
```

Los comandos compartidos dejan de ejecutarse accidentalmente en los dos bots. El bot solo procesa la orden si la mención coincide con su nombre configurado.

Archivo principal:

- `common/bot_manager.py`

Funciones principales:

- Normaliza nombres con o sin `@`.
- Lee el usuario mencionado después del comando.
- Comprueba si la orden está dirigida al bot actual.

## 2. Gestores comunes

Se crearon gestores reutilizables para evitar duplicar la misma lógica en Zeta y DJ.

### `common/avatar.py`

Centraliza:

- Obtener el outfit actual.
- Cambiar colores.
- Equipar prendas.
- Quitar categorías de ropa.
- Mostrar el outfit.
- Guardar el outfit después de modificarlo.
- Restaurar el outfit al conectar el bot.

### `common/positions.py`

Centraliza:

- Guardar la posición actual del bot.
- Leer la posición guardada.
- Volver a la posición guardada.
- Separar la posición de cada bot usando una clave propia.

### `common/dance.py`

Centraliza:

- Configurar un emote de baile.
- Activar el baile.
- Detener el baile.
- Guardar el emote y el estado del baile.

### `common/bot_state.py`

Añade persistencia individual para cada bot. Guarda:

- Nombre del bot.
- Outfit serializado.
- Emote de baile.
- Si el baile está activo.
- Token de reinicio.

También incluye una operación para limpiar el estado guardado.

## 3. Persistencia y reinicio

Los bots ahora pueden restaurar su configuración después de reiniciarse:

- DJ restaura posición y outfit al conectarse.
- Zeta restaura el outfit al conectarse.
- Las modificaciones de ropa se guardan automáticamente.
- La configuración del baile se sincroniza con el estado persistente.
- El reinicio del proceso conserva la configuración guardada.

## 4. Mejoras del bot DJ

En `bots/dj/music_bot.py` se realizaron estos cambios:

- Mensaje de conexión más claro y estético.
- Mensaje antes de reiniciar el bot.
- Mensajes de música, cola, errores y permisos con colores y emojis.
- Comandos de outfit protegidos mediante el nombre del bot.
- Uso del gestor común de posiciones.
- Restauración automática del outfit al conectarse.
- Eliminación del sistema local antiguo de posición.
- Eliminación de las funciones duplicadas `load()` y `save()` usadas solo para la posición.
- Eliminación de la escritura global antigua de `bot_position`.

## 5. Integración del bot Zeta

En `bots/bot1/main.py` se realizó lo siguiente:

- Integración de `AvatarManager`.
- Integración de `PositionManagerCommon`.
- Integración de `DanceManager`.
- Integración de `BotStateManager`.
- Restauración del outfit al iniciar.
- Baile dirigido mediante `!dancebot @Zeta_Bot` y `!stopdance @Zeta_Bot`.
- Emotes normales mediante `rest @usuario`.
- Emotes persistentes del bot mediante `!emote @Zeta_Bot <emote>` y `!emote @Zeta_Bot stop`.
- Reinicio dirigido mediante `!reset @Zeta_Bot`.
- Filtrado de comandos compartidos por nombre de bot.
- Conservación del `PositionManager` antiguo para las posiciones nombradas de la sala, que todavía utiliza Zeta para comandos como teletransportes guardados.

## 6. Comandos de outfit actualizados

Se actualizaron estos módulos para delegar en `AvatarManager` cuando está disponible:

- `commands/color.py`
- `commands/equip.py`
- `commands/remove.py`
- `commands/outfit.py`

Los comandos mantienen sus nombres y sintaxis, pero ahora comparten la misma lógica de avatar y persistencia.

## 7. Almacenamiento opcional con Supabase

En `services/storage.py`:

- Supabase continúa utilizándose cuando están definidas `SUPABASE_URL` y `SUPABASE_KEY`.
- Si la librería `supabase` no está instalada, el proyecto utiliza almacenamiento local sin fallar durante la importación.
- Se corrigió la anotación de tipos para que ese fallback funcione realmente en tiempo de ejecución.

## 8. Código duplicado eliminado

Se eliminó el archivo:

- `common/bot_targets.py`

Motivo:

- No tenía imports ni usos en el proyecto.
- Repetía la responsabilidad de `common/bot_manager.py`.
- La búsqueda confirmó que no quedaron referencias a `BotTargetResolver`.

## 9. Correcciones posteriores a la primera revisión

- La posición común usa siempre el nombre estable del bot, por ejemplo `bot_position_zeta_bot` o `bot_position_dj.z`.
- La restauración de posición de Zeta usa el mismo `PositionManagerCommon` que `!set` y `!home`.
- El estado persistido es la única fuente de verdad para `dance_enabled`.
- `BotState` separa `dance_enabled`, `bot_emote_enabled`, `bot_emote` y `active_mode`.
- `active_mode` determina si el bot restaura el baile aleatorio o el emote específico.
- Se eliminaron `dance_config`, `dance_emote`, `position` y `reset_token` del estado duplicado que ya no tenía uso.
- `!emote stop @Bot` fue eliminado; la sintaxis válida es `!emote @Bot stop`.
- Los emotes normales no pueden dirigirse a ninguno de los bots.
- El baile ya no se inicia automáticamente al conectar si no estaba activado.
- Las solicitudes de AutoDJ permanecen en `request_queue.json` hasta terminar su reproducción.
- Se eliminaron los fallbacks de outfit que llamaban directamente a Highrise.
- Se corrigió el reinicio `!restart` del DJ y se eliminó `reset_state()` sin referencias.
- Se corrigió la excepción duplicada del gestor de baile y se reforzó el estado al detener modos.

## 10. Mapa actual de persistencia

- `data.json`, `posiciones.json` y `roles.json` usan `services/storage.py` y pueden persistirse en la tabla Supabase `bot_files`.
- `music_bot_data.json` del DJ se gestiona directamente como archivo local montado por Docker.
- La cola, playlist y caché de AutoDJ se mantienen en el volumen local de AutoDJ.
- `common/emotes.json` es configuración estática y no se guarda en Supabase.

## 11. Archivos nuevos

- `common/avatar.py`
- `common/bot_manager.py`
- `common/bot_state.py`
- `common/dance.py`
- `common/positions.py`

## 12. Archivos modificados

- `bots/dj/music_bot.py`
- `bots/bot1/main.py`
- `commands/color.py`
- `commands/equip.py`
- `commands/outfit.py`
- `commands/remove.py`
- `services/storage.py`

## 13. Validaciones realizadas

Se ejecutaron comprobaciones de sintaxis sobre los módulos modificados y nuevos:

```bash
python -m py_compile services/storage.py common/bot_state.py common/avatar.py common/positions.py common/dance.py bots/dj/music_bot.py bots/bot1/main.py
```

También se ejecutó una compilación completa:

```bash
python -m compileall -q .
```

Se probó la lectura y escritura real del estado persistente con un archivo temporal y el resultado fue:

```text
state persistence ok
```

Finalmente se comprobó que no quedan referencias al módulo eliminado:

```text
bot_targets removed and no references remain
```

## 14. Pendiente de probar en producción

La validación local confirma sintaxis, imports y persistencia de archivos. Todavía hace falta probar en una sala real de Highrise:

- Conexión simultánea de ambos bots.
- Comandos dirigidos con los nombres reales.
- Restauración real de outfit y posición.
- Reinicio desde `!reset` o `!restart`.
- Funcionamiento con Supabase configurado.
- Rotación de la clave SSH histórica y de las credenciales de Icecast/AWS si fueron expuestas.
