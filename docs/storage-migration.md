# Migración del almacenamiento de bots

## Identificadores nuevos

Los registros de `bot_files` se identifican por la ruta relativa al proyecto, no solo por el nombre del archivo. Por ejemplo:

- Zeta: `bots/bot1/data/data.json`
- BotJuegos: `bots/fun/data/data.json`
- Roles compartidos: `roles.json`

Así, los dos archivos llamados `data.json` dejan de sobrescribirse entre sí. El archivo `roles.json` continúa siendo compartido intencionalmente por los bots.

## Compatibilidad con registros anteriores

Al no encontrar un registro nuevo, el almacenamiento busca una vez el identificador antiguo por nombre:

- `data.json` se copia a los espacios de Zeta y BotJuegos.
- `posiciones.json` se copia al espacio de posiciones de Zeta.

La migración escribe los nuevos registros y conserva los registros antiguos en Supabase. No elimina ni renombra datos antiguos.

**Límite de los datos históricos:** el sistema anterior guardaba ambos bots bajo el mismo registro `data.json`. No existe información suficiente para separar retroactivamente qué propinas o campos históricos pertenecían a cada bot. Para evitar descartar información, el registro compartido se conserva y se copia inicialmente a ambos espacios nuevos. Los datos que se generen después de la migración sí quedan aislados.

Cuando existe un archivo local, sus claves exclusivas se conservan durante la migración y los valores del registro anterior prevalecen en las claves coincidentes.

## Respaldo local

Cuando Supabase no está disponible, `save_json` escribe localmente mediante reemplazo atómico. Zeta utiliza el volumen Docker `zeta_data` para conservar `data.json` y `posiciones.json` aunque se recree su contenedor. BotJuegos conserva sus montajes persistentes actuales.

No eliminar volúmenes durante el despliegue: evitar especialmente `docker compose down -v`.

## Despliegue

Validar primero el Compose y después reconstruir los servicios que comparten `infra/Dockerfile.bot`:

```bash
docker compose config --quiet
docker compose build main-bot fun-bot music-bot ghost-wave-bot
docker compose up -d main-bot fun-bot music-bot ghost-wave-bot
```

Después comprobar:

```bash
docker compose ps
docker compose logs --tail=100 main-bot fun-bot music-bot ghost-wave-bot
docker volume inspect $(docker volume ls -q --filter name=zeta_data)
```

La migración de cada archivo ocurre cuando el bot lo carga por primera vez después del despliegue. Los registros antiguos permanecen disponibles como recuperación.
