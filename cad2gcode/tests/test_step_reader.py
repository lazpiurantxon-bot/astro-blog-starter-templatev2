import unittest
from pathlib import Path

from cad2gcode.readers.step_reader import read_step

EXAMPLE = Path(__file__).parent.parent / "examples" / "placa_4_agujeros.step"


class TestStepReader(unittest.TestCase):
    def setUp(self):
        self.part = read_step(EXAMPLE, material="aluminio")

    def test_bounding_box(self):
        bbox = self.part.bbox
        self.assertAlmostEqual(bbox.dx, 100.0)
        self.assertAlmostEqual(bbox.dy, 80.0)
        self.assertAlmostEqual(bbox.dz, 15.0)

    def test_detects_four_holes(self):
        self.assertEqual(len(self.part.holes), 4)
        positions = {(h.x, h.y) for h in self.part.holes}
        self.assertEqual(positions, {(20.0, 20.0), (80.0, 20.0), (20.0, 60.0), (80.0, 60.0)})

    def test_hole_geometry(self):
        for hole in self.part.holes:
            self.assertAlmostEqual(hole.diameter, 6.0)
            self.assertAlmostEqual(hole.depth, 15.0)
            self.assertTrue(hole.through)
            self.assertTrue(hole.verified)

    def test_rejects_non_step_content(self):
        bogus = Path(__file__).parent / "_bogus.step"
        bogus.write_text("esto no es un step")
        try:
            with self.assertRaises(ValueError):
                read_step(bogus)
        finally:
            bogus.unlink()


if __name__ == "__main__":
    unittest.main()
