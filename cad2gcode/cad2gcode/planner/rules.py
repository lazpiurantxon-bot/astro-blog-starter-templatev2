"""Planificador determinista por reglas (línea base y red de seguridad).

Estrategia MVP de taladrado:
- centrado previo de todas las posiciones con broca de puntear,
- una operación por diámetro de broca (agrupando agujeros),
- G81 para profundidad <= 3xD; G83 con rotura de viruta (Q = D/2) si es más profundo,
- regímenes de corte de la tabla por material, limitados por el husillo.
"""

from __future__ import annotations

from typing import Any

from ..features.model import PartModel
from .cutting_data import drilling_params
from .plan import DrillOp, ProcessPlan, Tool

RETRACT_MM = 2.0            # plano R sobre la pieza
CENTER_DRILL_DEPTH = 3.0    # profundidad de punteado
BREAKTHROUGH_MM = 1.0       # sobrepasada en agujeros pasantes (punta de broca aparte)


def plan_with_rules(part: PartModel, machine: dict[str, Any]) -> ProcessPlan:
    plan = ProcessPlan(part_name=part.name, machine_id=machine["id"], material=part.material)
    if not part.holes:
        plan.warnings.append("No se detectaron agujeros: plan vacío.")
        return plan

    max_rpm = machine["spindle"]["max_rpm"]
    tool_no = 1

    # Punteado de todas las posiciones.
    all_points = [(h.x, h.y) for h in part.holes]
    rpm, feed = drilling_params(3.0, part.material, max_rpm)
    center_tool = Tool(number=tool_no, description="Broca de puntear D3.0 90deg", type="center_drill", diameter=3.0)
    plan.operations.append(
        DrillOp(
            tool=center_tool,
            cycle="G81",
            points=all_points,
            z_depth=CENTER_DRILL_DEPTH,
            retract=RETRACT_MM,
            rpm=rpm,
            feed=feed,
            rationale="Punteado previo para posicionar la broca en todas las posiciones.",
        )
    )

    # Taladrado agrupado por diámetro.
    by_diameter: dict[float, list] = {}
    for h in part.holes:
        by_diameter.setdefault(round(h.diameter, 3), []).append(h)

    for diameter in sorted(by_diameter):
        holes = by_diameter[diameter]
        tool_no += 1
        tool = Tool(number=tool_no, description=f"Broca HSS D{diameter:g}", type="drill", diameter=diameter)
        max_depth = max(h.depth for h in holes)
        through = any(h.through for h in holes)
        z_depth = max_depth + (BREAKTHROUGH_MM + 0.3 * diameter if through else 0.0)
        rpm, feed = drilling_params(diameter, part.material, max_rpm)

        deep = max_depth > 3 * diameter
        op = DrillOp(
            tool=tool,
            cycle="G83" if deep else "G81",
            points=[(h.x, h.y) for h in holes],
            z_depth=round(z_depth, 2),
            retract=RETRACT_MM,
            rpm=rpm,
            feed=feed,
            peck=round(diameter / 2, 2) if deep else None,
            rationale=(
                f"{len(holes)} agujero(s) D{diameter:g}, profundidad {max_depth:g} "
                f"({'>' if deep else '<='} 3xD → {'G83 con rotura de viruta' if deep else 'G81'})."
            ),
        )
        plan.operations.append(op)

        for h in holes:
            if not h.verified:
                plan.warnings.append(
                    f"Profundidad ASUMIDA (pasante) en agujero D{diameter:g} X{h.x:g} Y{h.y:g}: verificar contra plano."
                )

    return plan
