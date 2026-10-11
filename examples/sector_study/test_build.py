"""Checks spatial feasibility of this authored study, including rejection of blockage."""
import unittest
from build import design, routes, merge_checked
from mcbuild.dsl.sandbox import run_blueprint
from mcbuild.voxel import VoxelGrid
from mcbuild.palette import get_block
class StudyTests(unittest.TestCase):
    def test_all_designs_and_blocked_destinations(self):
        for kind in ('well','canyon','shaft'):
            with self.subTest(kind=kind):
                grid=VoxelGrid(); run_blueprint(design(kind),grid,max_seconds=60,max_lines=5000000)
                self.assertFalse(grid.palette_warnings)
                self.assertEqual(grid.bounds[0],(0,0,0))
                self.assertLessEqual(grid.bounds[1][1],63)
                self.assertEqual((grid.bounds[1][0],grid.bounds[1][2]),(95,95))
                merged,_,_=merge_checked(grid,kind)
                report=routes(merged)
                for target in report['targets'].values():
                    grid.set(*target['foot_position'],get_block('stone').index)
                with self.assertRaises(AssertionError): routes(grid)
if __name__=='__main__': unittest.main()
