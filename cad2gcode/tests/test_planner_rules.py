import unittest

from cad2gcode.features.model import BoundingBox, Hole, PartModel
from cad2gcode.knowledge import load_machine
from cad2gcode.planner.rules import plan_with_rules


def make_part(holes):
    return PartModel(
        name="test",
        bbox=BoundingBox(0, 0, 0, 100, 80, 15),
        material="aluminio",
        holes=holes,
    )


class TestRulesPlanner(unittest.TestCase):
    def setUp(self):
        self.machine = load_machine("doosan_dnm5700")

    def test_center_drill_then_drill_per_diameter(self):
        part = make_part([
            Hole(20, 20, 6.0, 15.0),
            Hole(80, 20, 6.0, 15.0),
            Hole(50, 40, 10.0, 15.0),
        ])
        plan = plan_with_rules(part, self.machine)

        self.assertEqual(len(plan.operations), 3)  # puntear + D6 + D10
        self.assertEqual(plan.operations[0].tool.type, "center_drill")
        self.assertEqual(len(plan.operations[0].points), 3)
        self.assertEqual(plan.operations[1].tool.diameter, 6.0)
        self.assertEqual(len(plan.operations[1].points), 2)
        self.assertEqual(plan.operations[2].tool.diameter, 10.0)
        self.assertEqual(plan.validate(self.machine), [])

    def test_shallow_hole_uses_g81(self):
        part = make_part([Hole(20, 20, 6.0, 15.0)])  # 15 <= 3x6
        plan = plan_with_rules(part, self.machine)
        drill_op = plan.operations[1]
        self.assertEqual(drill_op.cycle, "G81")
        self.assertIsNone(drill_op.peck)

    def test_deep_hole_uses_g83_with_peck(self):
        part = make_part([Hole(20, 20, 5.0, 40.0, through=False)])  # 40 > 3x5
        plan = plan_with_rules(part, self.machine)
        drill_op = plan.operations[1]
        self.assertEqual(drill_op.cycle, "G83")
        self.assertAlmostEqual(drill_op.peck, 2.5)
        # ciego: sin sobrepasada
        self.assertAlmostEqual(drill_op.z_depth, 40.0)

    def test_through_hole_adds_breakthrough(self):
        part = make_part([Hole(20, 20, 6.0, 15.0, through=True)])
        plan = plan_with_rules(part, self.machine)
        # 15 + 1.0 + 0.3*6 = 17.8
        self.assertAlmostEqual(plan.operations[1].z_depth, 17.8)

    def test_unverified_depth_generates_warning(self):
        part = make_part([Hole(20, 20, 6.0, 15.0, verified=False)])
        plan = plan_with_rules(part, self.machine)
        self.assertTrue(any("ASUMIDA" in w for w in plan.warnings))

    def test_rpm_capped_by_spindle(self):
        part = make_part([Hole(20, 20, 1.0, 5.0)])  # D1 en aluminio pediría >12000 rpm
        plan = plan_with_rules(part, self.machine)
        for op in plan.operations:
            self.assertLessEqual(op.rpm, self.machine["spindle"]["max_rpm"])


if __name__ == "__main__":
    unittest.main()
