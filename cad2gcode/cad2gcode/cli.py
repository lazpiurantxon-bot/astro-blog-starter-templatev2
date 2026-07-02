"""CLI: convierte archivos CAD en programas CNC.

    python3 -m cad2gcode convert pieza.step --machine doosan_dnm5700 -o pieza.nc
    python3 -m cad2gcode inspect pieza.step
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .knowledge import list_machines, load_machine
from .planner.rules import plan_with_rules
from .postprocessors.doosan_dnm5700 import postprocess
from .readers.step_reader import read_step


def _read(path: str, material: str):
    suffix = Path(path).suffix.lower()
    if suffix in (".step", ".stp"):
        return read_step(path, material=material)
    raise SystemExit(f"Formato no soportado todavía: {suffix} (MVP: .step/.stp)")


def cmd_inspect(args: argparse.Namespace) -> int:
    part = _read(args.file, args.material)
    print(part.summary())
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    part = _read(args.file, args.material)
    machine = load_machine(args.machine)

    plan = None
    if args.agent:
        try:
            from .planner.agent import plan_with_agent

            plan = plan_with_agent(part, machine)
            errors = plan.validate(machine)
            if errors:
                print("Plan del agente rechazado en validación, usando reglas:", file=sys.stderr)
                for e in errors:
                    print(f"  - {e}", file=sys.stderr)
                plan = None
        except Exception as e:  # sin credenciales, sin SDK, fallo de red...
            print(f"Agente no disponible ({e}); usando planificador por reglas.", file=sys.stderr)

    if plan is None:
        plan = plan_with_rules(part, machine)

    program = postprocess(plan, machine, program_number=args.program_number)

    if args.output:
        Path(args.output).write_text(program)
        print(f"Programa escrito en {args.output}")
        for w in plan.warnings:
            print(f"AVISO: {w}", file=sys.stderr)
    else:
        print(program)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad2gcode", description="CAD -> código máquina")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="muestra las features detectadas en el archivo")
    p_inspect.add_argument("file")
    p_inspect.add_argument("--material", default="aluminio")
    p_inspect.set_defaults(func=cmd_inspect)

    p_convert = sub.add_parser("convert", help="genera el programa CNC")
    p_convert.add_argument("file")
    p_convert.add_argument("--machine", default="doosan_dnm5700", choices=list_machines())
    p_convert.add_argument("--material", default="aluminio")
    p_convert.add_argument("-o", "--output", help="archivo de salida (.nc); por defecto stdout")
    p_convert.add_argument("--program-number", type=int, default=1)
    p_convert.add_argument("--agent", action="store_true", help="usar el planificador agéntico (Claude)")
    p_convert.set_defaults(func=cmd_convert)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
