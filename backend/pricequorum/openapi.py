"""Writes the API contract to shared/openapi.json at the repository root.

python -m pricequorum.openapi          writes the file
python -m pricequorum.openapi --check  exits 1 when the committed file differs from the code
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pricequorum.api.app import create_app
from pricequorum.config import Settings

OUT = Path(__file__).resolve().parents[2] / "shared" / "openapi.json"


def render() -> str:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        current = OUT.read_text() if OUT.exists() else ""
        if current != rendered:
            print(f"{OUT} is out of date. Run: uv run python -m pricequorum.openapi")
            return 1
        print(f"{OUT} matches the code.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
