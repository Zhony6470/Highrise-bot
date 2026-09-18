# Arquitectura nueva

main-bot = comandos generales y su propio avatar/posición.
music-bot = !play !skip !q !review !ap !rp + !set !home !color !equip !remove !getoutfit.
autodj = reproductor independiente; mantiene la cola y una salida FFmpeg persistente hacia Icecast.
icecast = streaming público.

La música no depende de la conexión de ninguno de los bots de Highrise. Si music-bot se desconecta, AutoDJ sigue reproduciendo. Si main-bot se desconecta, la música tampoco se detiene.
