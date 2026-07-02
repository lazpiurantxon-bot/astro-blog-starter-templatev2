"""Datos de corte de partida para brocas HSS.

Valores conservadores de arranque; el taller los ajustará. Vc en m/min,
avance por vuelta proporcional al diámetro.
"""

from __future__ import annotations

import math

# material -> (Vc m/min, factor avance mm/rev por mm de diámetro)
CUTTING_DATA: dict[str, tuple[float, float]] = {
    "aluminio": (80.0, 0.025),
    "acero": (25.0, 0.02),
    "inox": (12.0, 0.015),
    "fundicion": (30.0, 0.02),
    "plastico": (100.0, 0.03),
}

DEFAULT_MATERIAL = "aluminio"


def drilling_params(diameter: float, material: str, max_rpm: int) -> tuple[int, float]:
    """Devuelve (rpm, avance mm/min) para una broca del diámetro dado."""
    vc, f_factor = CUTTING_DATA.get(material, CUTTING_DATA[DEFAULT_MATERIAL])
    rpm = int(min((1000.0 * vc) / (math.pi * diameter), max_rpm))
    feed_per_rev = f_factor * diameter
    feed = round(rpm * feed_per_rev, 1)
    return rpm, feed
