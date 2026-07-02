from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MACHINES_DIR = Path(__file__).parent / "machines"


def load_machine(machine_id: str) -> dict[str, Any]:
    path = _MACHINES_DIR / f"{machine_id}.json"
    if not path.exists():
        available = ", ".join(p.stem for p in _MACHINES_DIR.glob("*.json"))
        raise ValueError(f"Maquina desconocida '{machine_id}'. Disponibles: {available}")
    return json.loads(path.read_text())


def list_machines() -> list[str]:
    return sorted(p.stem for p in _MACHINES_DIR.glob("*.json"))
