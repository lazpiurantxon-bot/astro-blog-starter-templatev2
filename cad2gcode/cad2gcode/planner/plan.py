"""Plan de proceso: la salida del planner y la entrada del postprocesador.

El LLM nunca escribe G-code: propone este plan estructurado y el postprocesador
determinista lo convierte en programa. Todo lo que llega aquí se valida contra
la máquina antes de emitir código.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    number: int                # T en máquina
    description: str           # p.ej. "Broca HSS D6.0"
    type: str                  # "center_drill" | "drill"
    diameter: float


@dataclass
class DrillOp:
    """Una operación de taladrado sobre un conjunto de posiciones."""

    tool: Tool
    cycle: str                 # "G81" | "G83"
    points: list[tuple[float, float]]
    z_depth: float             # profundidad final (valor positivo, mm desde Z0)
    retract: float             # plano R (mm sobre la pieza)
    rpm: int
    feed: float                # mm/min
    peck: float | None = None  # Q para G83
    rationale: str = ""        # trazabilidad: por qué esta operación/régimen

    @property
    def comment(self) -> str:
        return f"T{self.tool.number:02d} {self.tool.description}"


@dataclass
class ProcessPlan:
    part_name: str
    machine_id: str
    material: str
    operations: list[DrillOp] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def validate(self, machine: dict[str, Any]) -> list[str]:
        """Comprueba el plan contra la ficha de máquina. Devuelve errores."""
        errors: list[str] = []
        travels = machine["travels_mm"]
        max_rpm = machine["spindle"]["max_rpm"]
        max_feed = machine["max_feed_mm_min"]["cutting"]
        for i, op in enumerate(self.operations, 1):
            if op.rpm <= 0 or op.rpm > max_rpm:
                errors.append(f"Op {i}: S{op.rpm} fuera de rango del husillo (max {max_rpm}).")
            if op.feed <= 0 or op.feed > max_feed:
                errors.append(f"Op {i}: F{op.feed:g} fuera de rango (max {max_feed}).")
            if op.z_depth <= 0:
                errors.append(f"Op {i}: profundidad no positiva.")
            if op.z_depth > travels["z"]:
                errors.append(f"Op {i}: profundidad {op.z_depth:g} supera la carrera Z.")
            if op.cycle not in ("G81", "G83"):
                errors.append(f"Op {i}: ciclo {op.cycle} no soportado.")
            if op.cycle == "G83" and (op.peck is None or op.peck <= 0):
                errors.append(f"Op {i}: G83 sin Q valido.")
            if not op.points:
                errors.append(f"Op {i}: sin posiciones.")
            for x, y in op.points:
                # La pieza se amarra dentro de la carrera; aquí solo se detecta
                # lo groseramente imposible (posiciones fuera del rango XY total).
                if abs(x) > travels["x"] or abs(y) > travels["y"]:
                    errors.append(f"Op {i}: punto X{x:g} Y{y:g} fuera de carreras.")
        return errors
