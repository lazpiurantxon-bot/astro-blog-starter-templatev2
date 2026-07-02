import unittest

from cad2gcode.features.model import BoundingBox, Hole, PartModel
from cad2gcode.knowledge import load_machine
from cad2gcode.planner.plan import DrillOp, ProcessPlan, Tool
from cad2gcode.planner.rules import plan_with_rules
from cad2gcode.postprocessors.doosan_dnm5700 import postprocess


class TestDoosanPostprocessor(unittest.TestCase):
    def setUp(self):
        self.machine = load_machine("doosan_dnm5700")
        self.part = PartModel(
            name="placa",
            bbox=BoundingBox(0, 0, 0, 100, 80, 15),
            material="aluminio",
            holes=[Hole(20, 20, 6.0, 15.0), Hole(80, 60, 6.0, 15.0)],
        )
        self.plan = plan_with_rules(self.part, self.machine)

    def test_program_structure(self):
        program = postprocess(self.plan, self.machine, program_number=12)
        lines = program.strip().splitlines()
        self.assertEqual(lines[0], "%")
        self.assertEqual(lines[-1], "%")
        self.assertIn("O0012", lines[1])
        self.assertIn("M30", program)
        self.assertIn("G90 G17 G21 G40 G49 G80", program)

    def test_tool_changes_and_cycles(self):
        program = postprocess(self.plan, self.machine)
        self.assertIn("T01 M06", program)
        self.assertIn("T02 M06", program)
        self.assertIn("G98 G81", program)
        self.assertIn("G80", program)
        self.assertIn("G43 H01", program)
        self.assertIn("G43 H02", program)

    def test_hole_coordinates_present(self):
        program = postprocess(self.plan, self.machine)
        self.assertIn("X20. Y20.", program)
        self.assertIn("X80. Y60.", program)

    def test_deep_hole_emits_peck(self):
        part = PartModel(
            name="bloque",
            bbox=BoundingBox(0, 0, 0, 100, 80, 50),
            material="acero",
            holes=[Hole(50, 40, 5.0, 40.0, through=False)],
        )
        plan = plan_with_rules(part, self.machine)
        program = postprocess(plan, self.machine)
        self.assertIn("G83", program)
        self.assertIn("Q2.5", program)

    def test_comments_have_no_nested_parens_or_non_ascii(self):
        program = postprocess(self.plan, self.machine)
        for line in program.splitlines():
            line.encode("ascii")  # todo el programa debe ser ASCII
            if "(" in line:
                comment = line[line.index("("):]
                inner = comment[1:-1]
                self.assertNotIn("(", inner, f"parentesis anidado en: {line}")
                self.assertNotIn(")", inner, f"parentesis anidado en: {line}")

    def test_invalid_plan_rejected(self):
        bad = ProcessPlan(part_name="mala", machine_id="doosan_dnm5700", material="aluminio")
        bad.operations.append(
            DrillOp(
                tool=Tool(number=1, description="Broca D6", type="drill", diameter=6.0),
                cycle="G81",
                points=[(20.0, 20.0)],
                z_depth=15.0,
                retract=2.0,
                rpm=99999,  # supera el husillo
                feed=500.0,
            )
        )
        with self.assertRaises(ValueError):
            postprocess(bad, self.machine)


if __name__ == "__main__":
    unittest.main()
