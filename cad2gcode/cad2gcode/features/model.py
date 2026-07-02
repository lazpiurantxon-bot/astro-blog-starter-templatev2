"""Modelo intermedio de features de fabricación.

Desacopla los readers (STEP, DXF, PDF...) de los planners y postprocesadores.
Unidades: milímetros. Sistema de coordenadas: Z+ = eje de la herramienta,
Z=0 en la cara superior de la pieza (convención del MVP).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BoundingBox:
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def dx(self) -> float:
        return self.xmax - self.xmin

    @property
    def dy(self) -> float:
        return self.ymax - self.ymin

    @property
    def dz(self) -> float:
        return self.zmax - self.zmin


@dataclass
class Hole:
    """Agujero de eje vertical (paralelo a Z)."""

    x: float
    y: float
    diameter: float
    depth: float
    through: bool = True
    # False cuando la profundidad se ha asumido (p.ej. pasante = espesor de pieza)
    # en vez de medirse en la geometría: requiere revisión humana.
    verified: bool = True

    def __str__(self) -> str:
        kind = "pasante" if self.through else "ciego"
        note = "" if self.verified else " [ASUMIDO — revisar]"
        return (
            f"Agujero Ø{self.diameter:g} x{self.depth:g} ({kind}) "
            f"en X{self.x:g} Y{self.y:g}{note}"
        )


@dataclass
class Pocket:
    """Cajera 2.5D. Definida para el roadmap; sin detección en el MVP."""

    boundary: list[tuple[float, float]]
    depth: float


@dataclass
class Contour:
    """Perfil exterior 2.5D. Definido para el roadmap; sin detección en el MVP."""

    boundary: list[tuple[float, float]]
    depth: float


@dataclass
class PartModel:
    name: str
    bbox: BoundingBox
    material: str = "aluminio"
    holes: list[Hole] = field(default_factory=list)
    pockets: list[Pocket] = field(default_factory=list)
    contours: list[Contour] = field(default_factory=list)

    @property
    def thickness(self) -> float:
        return self.bbox.dz

    def summary(self) -> str:
        lines = [
            f"Pieza: {self.name}",
            f"Material: {self.material}",
            f"Dimensiones: {self.bbox.dx:g} x {self.bbox.dy:g} x {self.bbox.dz:g} mm",
            f"Agujeros: {len(self.holes)}",
        ]
        lines.extend(f"  - {h}" for h in self.holes)
        return "\n".join(lines)
