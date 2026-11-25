"""Render sample achievement cards into a folder (to eyeball the design): python scripts/preview_cards.py OUT_DIR"""

import sys
from pathlib import Path

from bot.cards import CardSpec, render

out = Path(sys.argv[1] if len(sys.argv) > 1 else "card-preview")
out.mkdir(parents=True, exist_ok=True)
for spec in [
    CardSpec("streak", 7, "ru", "it"),
    CardSpec("words", 25, "uz", "en"),
    CardSpec("streak", 3, "en", "ko"),
    CardSpec("streak", 14, "ru", "en", "story"),
]:
    path = out / f"{spec.kind}-{spec.n}-{spec.lang}-{spec.fmt}.jpg"
    path.write_bytes(render(spec))
    print(path)
