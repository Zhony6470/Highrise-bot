Prueba de concepto de Icecast en Render.

Esto no es una solución estable para producción.
Es una prueba mínima para ver si la arquitectura arranca.

1. Render usa este archivo render.yaml
2. start.sh arranca Icecast y FFmpeg
3. la URL del stream queda en http://127.0.0.1:8000/stream dentro del contenedor
4. si Render no expone ese puerto como esperas, la prueba no será estable

Esto sirve solo para validar la idea, no para una radio verdadera y permanente.
