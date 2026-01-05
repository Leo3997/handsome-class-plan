import unittest
import sys
import os

# Ensure we can import modules from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import normal

class TestNormalScheduler(unittest.TestCase):
    def setUp(self):
        self.config = {
            "num_classes": 3,
            "courses": {
                "语文": {"count": 2, "type": "main"},
                "数学": {"count": 2, "type": "main"}
            },
            "teacher_names": {
                "语文": ["张三"],
                "数学": ["李四"]
            }
        }

    def test_generate_teachers_and_map(self):
        teachers, teacher_map = normal.generate_teachers_and_map(
            self.config['num_classes'], 
            self.config['courses'], 
            self.config['teacher_names']
        )
        
        # Check if teachers are generated
        self.assertTrue(len(teachers) > 0)
        
        # Check if map covers all classes and subjects
        expected_coverage = self.config['num_classes'] * len(self.config['courses'])
        self.assertEqual(len(teacher_map), expected_coverage)
        
        # Check if names are correctly assigned
        names = [t['name'] for t in teachers]
        self.assertIn("张三", names)
        self.assertIn("李四", names)

    def test_run_scheduler_success(self):
        result = normal.run_scheduler(self.config)
        self.assertEqual(result['status'], 'success')
        self.assertIn('stats', result)
        self.assertIn('vars', result)

    def test_run_scheduler_overload(self):
        # Create an impossible configuration (too many courses per day)
        overload_config = {
            "num_classes": 1,
            "courses": {
                "语文": {"count": 50, "type": "main"}  # Impossible to fit in one week
            }
        }
        # The scheduler currently returns status='fail' or maybe 'infeasible' status from solver which maps to fail
        # Note: normal.py returns {"status": "fail"} if not optimal/feasible
        result = normal.run_scheduler(overload_config)
        self.assertEqual(result['status'], 'fail')

    def test_run_scheduler_with_list_courses(self):
        # Regression test: Ensure list input for courses is handled correctly
        config_with_list = {
            "num_classes": 2,
            "courses": [
                {"name": "语文", "count": 2, "type": "main"},
                {"name": "数学", "count": 2, "type": "main"}
            ]
        }
        
        result = normal.run_scheduler(config_with_list)
        self.assertEqual(result['status'], 'success')


if __name__ == '__main__':
    unittest.main()
