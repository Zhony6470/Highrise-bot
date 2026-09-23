from pathlib import Path
import importlib.util


path = Path(importlib.util.find_spec("highrise.models_webapi").origin)
text = path.read_text(encoding="utf-8")

if 'MYTHICAL = "mythical"' not in text:
    marker = '    LEGENDARY = "legendary"'
    if marker not in text:
        raise SystemExit("No se encontró el enum Rarity esperado en Highrise SDK")
    text = text.replace(
        marker,
        marker + '\n    MYTHICAL = "mythical"',
        1,
    )
    path.write_text(text, encoding="utf-8")
    print(f"Highrise SDK patched: {path}")
else:
    print("Highrise SDK ya contiene MYTHICAL")
