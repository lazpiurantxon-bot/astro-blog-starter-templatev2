"""Lector de STEP Part 21 (ISO 10303-21) sin dependencias externas.

Alcance del MVP: piezas prismáticas con agujeros de eje vertical.
Extrae CARTESIAN_POINT, DIRECTION, AXIS2_PLACEMENT_3D, CYLINDRICAL_SURFACE y
CIRCLE del fichero exportado por el CAD (probado con la estructura que genera
NX / cualquier exportador AP203/AP214) y deduce:

- caja envolvente de la pieza (nube de puntos cartesianos),
- agujeros: superficies cilíndricas con eje paralelo a Z. El diámetro sale del
  radio; la posición, del origen del eje; la profundidad, de la extensión en Z
  de los círculos coaxiales. Si no hay círculos suficientes se asume agujero
  pasante (profundidad = espesor) y se marca verified=False.

No es un kernel B-rep: geometría compleja queda fuera hasta migrar a
OpenCascade manteniendo esta misma interfaz.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..features.model import BoundingBox, Hole, PartModel

# Instancia Part 21: "#12 = ENTITY(args);" (puede ocupar varias líneas).
# No-codicioso: el cierre es el primer ")" seguido de ";", lo que tolera
# paréntesis anidados en los argumentos sin tragarse la entidad siguiente.
_ENTITY_RE = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*?)\)\s*;", re.DOTALL)
_TRIPLE_RE = re.compile(r"\(\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*,\s*([-\d.Ee+]+)\s*\)")
_REF_RE = re.compile(r"#(\d+)")

_AXIS_TOL = 1e-3  # tolerancia para "eje paralelo a Z"
_POS_TOL = 1e-3   # tolerancia para agrupar entidades coaxiales
_RAD_TOL = 1e-3


def _parse_entities(text: str) -> dict[int, tuple[str, str]]:
    """Devuelve {id: (tipo, argumentos_crudos)} de la sección DATA."""
    data = text
    m = re.search(r"\bDATA\s*;(.*)ENDSEC\s*;", text, re.DOTALL)
    if m:
        data = m.group(1)
    entities: dict[int, tuple[str, str]] = {}
    for eid, etype, args in _ENTITY_RE.findall(data):
        entities[int(eid)] = (etype, args)
    return entities


def _triple(args: str) -> tuple[float, float, float] | None:
    m = _TRIPLE_RE.search(args)
    if not m:
        return None
    return tuple(float(v) for v in m.groups())  # type: ignore[return-value]


def _refs(args: str) -> list[int]:
    return [int(r) for r in _REF_RE.findall(args)]


def _last_float(args: str) -> float | None:
    # El radio es el último argumento numérico de CYLINDRICAL_SURFACE / CIRCLE.
    m = re.search(r",\s*([-\d.Ee+]+)\s*$", args.strip())
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def read_step(path: str | Path, material: str = "aluminio") -> PartModel:
    path = Path(path)
    text = path.read_text(errors="replace")
    entities = _parse_entities(text)

    points: dict[int, tuple[float, float, float]] = {}
    directions: dict[int, tuple[float, float, float]] = {}
    placements: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}

    for eid, (etype, args) in entities.items():
        if etype == "CARTESIAN_POINT":
            t = _triple(args)
            if t:
                points[eid] = t
        elif etype == "DIRECTION":
            t = _triple(args)
            if t:
                directions[eid] = t

    for eid, (etype, args) in entities.items():
        if etype != "AXIS2_PLACEMENT_3D":
            continue
        refs = _refs(args)
        origin = next((points[r] for r in refs if r in points), None)
        axis = next((directions[r] for r in refs if r in directions), (0.0, 0.0, 1.0))
        if origin is not None:
            placements[eid] = (origin, axis)

    if not points:
        raise ValueError(f"{path.name}: no se encontraron puntos cartesianos; ¿es un STEP Part 21 válido?")

    xs, ys, zs = zip(*points.values())
    bbox = BoundingBox(min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    # Círculos coaxiales: para medir la extensión en Z de cada cilindro.
    circles: list[tuple[float, float, float, float]] = []  # (x, y, z, radio)
    for eid, (etype, args) in entities.items():
        if etype != "CIRCLE":
            continue
        radius = _last_float(args)
        if radius is None:
            continue
        for r in _refs(args):
            if r in placements:
                (ox, oy, oz), _axis = placements[r]
                circles.append((ox, oy, oz, radius))
                break

    holes: list[Hole] = []
    for eid, (etype, args) in entities.items():
        if etype != "CYLINDRICAL_SURFACE":
            continue
        radius = _last_float(args)
        if radius is None:
            continue
        placement = next((placements[r] for r in _refs(args) if r in placements), None)
        if placement is None:
            continue
        (ox, oy, oz), (ax, ay, az) = placement
        if abs(abs(az) - 1.0) > _AXIS_TOL or abs(ax) > _AXIS_TOL or abs(ay) > _AXIS_TOL:
            continue  # eje no vertical: fuera del alcance del MVP

        coaxial_z = [
            cz for cx, cy, cz, cr in circles
            if abs(cx - ox) <= _POS_TOL and abs(cy - oy) <= _POS_TOL and abs(cr - radius) <= _RAD_TOL
        ]
        if len(coaxial_z) >= 2:
            depth = max(coaxial_z) - min(coaxial_z)
            through = depth >= bbox.dz - _POS_TOL
            verified = True
        else:
            depth = bbox.dz
            through = True
            verified = False

        hole = Hole(x=ox, y=oy, diameter=2 * radius, depth=depth, through=through, verified=verified)
        # El mismo agujero puede aparecer como varias caras cilíndricas: dedupe.
        if not any(
            abs(h.x - hole.x) <= _POS_TOL
            and abs(h.y - hole.y) <= _POS_TOL
            and abs(h.diameter - hole.diameter) <= _RAD_TOL
            for h in holes
        ):
            holes.append(hole)

    holes.sort(key=lambda h: (h.diameter, h.y, h.x))
    return PartModel(name=path.stem, bbox=bbox, material=material, holes=holes)
