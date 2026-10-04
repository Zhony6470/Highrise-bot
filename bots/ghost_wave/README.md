# Ghost Wave Bot

Bot independiente para administrar oleadas de fantasmas mediante el buzón de Highrise.

## Diseño

Cada sala tiene su propio horario e intervalo. Esto permite que dos salas estén separadas por solo 1 o 2 minutos sin que una configuración interfiera con la otra.

Cada sala guarda:
- hora prevista de la próxima oleada
- hora de activación real anterior
- intervalo en minutos
- estado activo/detenido
- estado esperando confirmación
- enlace y Room ID
- aviso de 5 minutos

## Comandos principales

- `!ghost salas` — muestra todas las salas, estado, próxima hora, aviso e intervalo.
- `!ghost iniciar <sala> HH:MM [min]` — inicia una sala.
- `!ghost hora <sala> HH:MM` — registra la hora real de activación.
- `!ghost intervalo <sala> 75` — cambia el intervalo de una sala.
- `!ghost parar <sala>` — detiene solo esa sala.
- `!ghost reanudar` — detiene todos los horarios y obliga a configurarlos nuevamente.
- `!ghost sala agregar <nombre> <link>` — agrega una sala.
- `!ghost sala editar <nombre> <link>` — actualiza el enlace sin perder su horario.
- `!ghost sala borrar <nombre>` — elimina una sala; si está activa, primero hay que detenerla.
- `!ghost sala principal <nombre>` — marca una sala principal informativa.

## Accesos

- `!ghost permisos` — muestra propietario, administradores y personas que reciben avisos.
- `!ghost usuarios` — alias de permisos.
- `!ghost admin @usuario` — da permiso de configuración.
- `!ghost radmin @usuario` — quita permiso de configuración.
- `!ghost suscribir @usuario` — autoriza avisos por buzón.
- `!ghost quitar-suscripcion @usuario` — quita avisos.

Solo el propietario administra los permisos.

## Salas con poca diferencia de tiempo

No se usa un único contador global. Cada sala tiene un contador independiente.

Ejemplo:
- Sala A: oleada 19:50
- Sala B: oleada 19:52
- Sala C: oleada 19:53

El bot manda cada aviso por separado a los suscriptores y, después de cada oleada, pregunta específicamente por la sala correspondiente.

Si solo hay una sala esperando confirmación, el administrador puede responder únicamente `19:52`. Si hay dos o más salas esperando al mismo tiempo, el bot exige indicar la sala:

`!ghost hora SalaA 19:52`

Esto evita que una hora se aplique accidentalmente a la sala equivocada.
