# Highrise Ghost Event Detector

Herramienta local para detectar los fantasmas del evento en la pantalla de Highrise.

## Estado actual

- Captura de pantalla en tiempo real.
- Overlay transparente directamente sobre la ventana/pantalla de Highrise.
- Los cuadros son **click-through**: el overlay no bloquea el mouse del juego.
- El overlay se oculta durante la captura para no contaminar la detección con sus propios cuadros.
- Modo calibración: **no hace clic** en ningún fantasma.
- La zona de captura se puede seleccionar con el mouse y queda guardada en config.json.
- No forma parte de los contenedores/bots de Highrise: se ejecuta localmente en el PC donde está abierto el juego.

## Instalación

Desde esta carpeta:

```bash
pip install -r requirements.txt
```

No se necesita instalar una librería adicional para el overlay: utiliza Tkinter + API de Windows.

## Primera prueba

Desde tools\\ghost_event_detector:

```powershell
.\\.venv\\Scripts\\Activate.ps1
py ghost_hunter.py --select-region
```

1. Aparecerá una pantalla temporal para seleccionar el rectángulo exacto donde está Highrise.
2. Arrastra desde una esquina hasta la esquina opuesta.
3. Pulsa ENTER.
4. La ventana de selección desaparecerá.
5. Los cuadros del detector aparecerán **directamente sobre Highrise**.
6. Para detenerlo, pulsa Ctrl+C en la terminal.

Si la zona ya está guardada, en las siguientes pruebas basta con:

```powershell
py ghost_hunter.py
```

Para ejecutar sin overlay:

```powershell
py ghost_hunter.py --console-only
```

## Qué significan los cuadros

- **Amarillo:** candidato clasificado provisionalmente como small.
- **Verde:** candidato clasificado provisionalmente como large.
- Estos colores **todavía no significan "fantasma confirmado"**. La detección actual sigue siendo una fase de calibración y puede marcar objetos del escenario.

## Seguridad durante las pruebas

click_enabled debe permanecer en false.

El programa no ejecutará clics automáticos en esta fase. Primero se validará que los cuadros coincidan con los fantasmas reales y se reducirán los falsos positivos.

## Siguiente fase

Con las pruebas sobre el juego abierto se ajustarán:

- filtros de forma;
- colores de las variantes;
- tamaños pequeños/grandes;
- detección de ojos y silueta;
- reducción de falsos positivos;
- y finalmente el punto exacto de clic.

El clic automático se habilitará solamente después de validar visualmente la detección.
