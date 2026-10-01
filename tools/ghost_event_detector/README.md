# Highrise Ghost Event Detector

Herramienta local para detectar los fantasmas del evento en la pantalla de Highrise.

## Estado actual

- Captura de pantalla en tiempo real.
- Modo prueba: detecta y dibuja las detecciones sin hacer clic.
- Preparada para variantes por color y tamaño.
- El clic automático queda separado del detector para poder validar primero las detecciones.
- No forma parte de los contenedores/bots de Highrise: se ejecuta localmente en el PC donde está abierto el juego.

## Instalación

Desde esta carpeta:

```bash
pip install -r requirements.txt
```

## Primer uso

```bash
python ghost_hunter.py --debug
```

Pulsa `q` sobre la ventana de depuración para salir.

## Próximo paso

Cuando tengamos capturas completas del juego con las variantes pequeñas y grandes, se añadirán las plantillas y se calibrará la región de búsqueda, tamaño y umbrales.

**Importante:** el modo de clic automático no se habilita todavía hasta validar la detección visual.
