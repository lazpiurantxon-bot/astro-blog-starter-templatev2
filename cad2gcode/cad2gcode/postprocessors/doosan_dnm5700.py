"""Postprocesador Doosan DNM 5700 (control FANUC i Plus).

Convierte un ProcessPlan validado en un programa Fanuc. Es la única capa que
escribe G-code; el planner (reglas o agente) nunca lo hace directamente.

Convenciones:
- G54 en la esquina definida por el amarre, Z0 en cara superior de pieza.
- Cota de seguridad Z 25.0 con G43 en cada cambio de herramienta.
- Ciclos fijos G81/G83 con retorno a plano inicial (G98).
"""

from __future__ import annotations

from typing import Any

from ..planner.plan import DrillOp, ProcessPlan

SAFE_Z = 25.0


def _fmt(v: float) -> str:
    """Formato Fanuc: sin ceros sobrantes, con punto decimal explícito."""
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if "." in s else s + "."


def _comment(text: str, width: int = 68) -> str:
    """Comentario Fanuc seguro: sin paréntesis anidados ni caracteres no ASCII.

    Un ')' dentro del comentario cerraría el comentario y el resto de la línea
    se ejecutaría como código: se sustituyen por corchetes.
    """
    clean = text.upper().replace("(", "[").replace(")", "]")
    clean = clean.replace("Ø", "D").replace("→", "->").replace("≤", "<=").replace("≥", ">=")
    clean = clean.encode("ascii", errors="replace").decode("ascii").replace("?", " ")
    return f"({clean[:width].rstrip()})"


def postprocess(plan: ProcessPlan, machine: dict[str, Any], program_number: int = 1) -> str:
    errors = plan.validate(machine)
    if errors:
        raise ValueError("Plan invalido para " + machine["name"] + ":\n- " + "\n- ".join(errors))

    n = 0

    def line(code: str) -> str:
        nonlocal n
        n += 10
        return f"N{n} {code}"

    out: list[str] = []
    out.append("%")
    out.append(f"O{program_number:04d} " + _comment(f"{plan.part_name[:24]} - {machine['name']}"))
    out.append(_comment(f"{plan.material} - GENERADO POR CAD2GCODE - REVISAR ANTES DE EJECUTAR"))
    for w in plan.warnings:
        out.append(_comment(f"AVISO: {w}"))

    out.append(line("G90 G17 G21 G40 G49 G80"))

    for op in plan.operations:
        out.append("")
        out.append(_comment(op.comment))
        out.append(_comment(op.rationale) if op.rationale else "")
        out.append(line(f"T{op.tool.number:02d} M06"))
        out.append(line("G54"))
        out.append(line(f"S{op.rpm} M03"))
        x0, y0 = op.points[0]
        out.append(line(f"G00 X{_fmt(x0)} Y{_fmt(y0)}"))
        out.append(line(f"G43 H{op.tool.number:02d} Z{_fmt(SAFE_Z)} M08"))

        cycle = f"G98 {op.cycle} Z-{_fmt(op.z_depth)} R{_fmt(op.retract)}"
        if op.cycle == "G83" and op.peck:
            cycle += f" Q{_fmt(op.peck)}"
        cycle += f" F{_fmt(op.feed)}"
        out.append(line(cycle))
        for x, y in op.points[1:]:
            out.append(line(f"X{_fmt(x)} Y{_fmt(y)}"))
        out.append(line("G80"))
        out.append(line("M09"))
        out.append(line("G91 G28 Z0."))
        out.append(line("G90"))

    out.append("")
    out.append(line("M05"))
    out.append(line("G91 G28 Y0."))
    out.append(line("G90"))
    out.append(line("M30"))
    out.append("%")
    return "\n".join(filter(None, out)) + "\n"
