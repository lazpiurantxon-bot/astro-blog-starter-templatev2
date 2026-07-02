"""Planificador agéntico sobre la API de Claude.

El agente recibe las features de la pieza y la máquina destino, consulta datos
de corte y la ficha de máquina mediante herramientas, y entrega el plan con la
herramienta `submit_plan`. El plan entregado se convierte al mismo esquema
`ProcessPlan` que produce el planificador por reglas y pasa por la misma
validación antes de postprocesar: el LLM nunca escribe G-code.

Requiere `pip install anthropic` y credenciales (ANTHROPIC_API_KEY o perfil
`ant auth login`). Si algo falla, el llamador debe degradar a plan_with_rules.
"""

from __future__ import annotations

import json
from typing import Any

from ..features.model import PartModel
from .cutting_data import CUTTING_DATA, drilling_params
from .plan import DrillOp, ProcessPlan, Tool

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
Eres un programador CNC senior especializado en centros de mecanizado verticales.
Recibes las features de fabricación de una pieza y debes producir un plan de
proceso de TALADRADO para la máquina indicada.

Reglas:
- Consulta la ficha de la máquina y los datos de corte con las herramientas antes de decidir regímenes.
- Agrupa agujeros por herramienta para minimizar cambios; puntea antes de taladrar.
- Usa ciclo G81 para profundidades <= 3xD y G83 con Q (rotura de viruta) para más profundas.
- En agujeros pasantes añade sobrepasada (aprox. 1 mm + 0.3xD por la punta de la broca).
- No superes las rpm del husillo ni el avance máximo de la máquina.
- Justifica cada operación en su campo "rationale" (breve, en español).
- Cuando el plan esté completo, entrégalo con la herramienta submit_plan. No escribas G-code.
"""

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tool_number": {"type": "integer"},
                    "tool_description": {"type": "string"},
                    "tool_type": {"type": "string", "enum": ["center_drill", "drill"]},
                    "tool_diameter": {"type": "number"},
                    "cycle": {"type": "string", "enum": ["G81", "G83"]},
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "z_depth": {"type": "number"},
                    "retract": {"type": "number"},
                    "rpm": {"type": "integer"},
                    "feed": {"type": "number"},
                    "peck": {"type": ["number", "null"]},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "tool_number", "tool_description", "tool_type", "tool_diameter",
                    "cycle", "points", "z_depth", "retract", "rpm", "feed", "rationale",
                ],
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["operations"],
}


def _part_as_json(part: PartModel) -> str:
    return json.dumps(
        {
            "nombre": part.name,
            "material": part.material,
            "dimensiones_mm": {"x": part.bbox.dx, "y": part.bbox.dy, "z": part.bbox.dz},
            "agujeros": [
                {
                    "x": h.x, "y": h.y, "diametro": h.diameter, "profundidad": h.depth,
                    "pasante": h.through, "profundidad_verificada": h.verified,
                }
                for h in part.holes
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _plan_from_payload(payload: dict[str, Any], part: PartModel, machine: dict[str, Any]) -> ProcessPlan:
    plan = ProcessPlan(part_name=part.name, machine_id=machine["id"], material=part.material)
    plan.warnings = list(payload.get("warnings", []))
    for op in payload["operations"]:
        tool = Tool(
            number=int(op["tool_number"]),
            description=str(op["tool_description"]),
            type=str(op["tool_type"]),
            diameter=float(op["tool_diameter"]),
        )
        plan.operations.append(
            DrillOp(
                tool=tool,
                cycle=str(op["cycle"]),
                points=[(float(p[0]), float(p[1])) for p in op["points"]],
                z_depth=float(op["z_depth"]),
                retract=float(op["retract"]),
                rpm=int(op["rpm"]),
                feed=float(op["feed"]),
                peck=None if op.get("peck") is None else float(op["peck"]),
                rationale=str(op.get("rationale", "")),
            )
        )
    return plan


def plan_with_agent(part: PartModel, machine: dict[str, Any]) -> ProcessPlan:
    from anthropic import Anthropic, beta_tool

    client = Anthropic()
    submitted: list[dict[str, Any]] = []

    @beta_tool
    def get_machine_spec() -> str:
        """Devuelve la ficha técnica completa de la máquina destino (carreras, husillo, control, notas del post)."""
        return json.dumps(machine, ensure_ascii=False)

    @beta_tool
    def get_cutting_data(material: str, diameter: float) -> str:
        """Datos de corte recomendados para broca HSS: rpm y avance (mm/min) para un material y diámetro dados.

        Args:
            material: uno de: aluminio, acero, inox, fundicion, plastico.
            diameter: diámetro de la broca en mm.
        """
        if material not in CUTTING_DATA:
            return json.dumps({"error": f"material desconocido; usa uno de {sorted(CUTTING_DATA)}"})
        rpm, feed = drilling_params(diameter, material, machine["spindle"]["max_rpm"])
        return json.dumps({"material": material, "diametro": diameter, "rpm": rpm, "avance_mm_min": feed})

    @beta_tool
    def submit_plan(plan_json: str) -> str:
        """Entrega el plan de proceso final como JSON conforme al esquema acordado.

        Args:
            plan_json: JSON con {"operations": [...], "warnings": [...]}.
        """
        try:
            payload = json.loads(plan_json)
        except json.JSONDecodeError as e:
            return f"JSON invalido: {e}"
        if "operations" not in payload or not payload["operations"]:
            return "El plan debe contener al menos una operacion en 'operations'."
        submitted.append(payload)
        return "Plan recibido."

    user_message = (
        "Máquina destino: "
        + machine["name"]
        + "\n\nEsquema del plan que debes entregar en submit_plan:\n"
        + json.dumps(PLAN_SCHEMA)
        + "\n\nFeatures de la pieza:\n"
        + _part_as_json(part)
    )

    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        tools=[get_machine_spec, get_cutting_data, submit_plan],
        messages=[{"role": "user", "content": user_message}],
    )
    runner.until_done()

    if not submitted:
        raise RuntimeError("El agente no entregó ningún plan via submit_plan.")

    plan = _plan_from_payload(submitted[-1], part, machine)
    plan.warnings.append("Plan generado por agente Claude: validado contra máquina, revisar igualmente.")
    return plan
