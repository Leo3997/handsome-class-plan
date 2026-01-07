import unittest
import sys
import os

# Ensure we can import modules from the parent directory
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import normal

class TestTeacherLimits(unittest.TestCase):
    def test_invalid_name_interception(self):
        # 构造一个姓名不存在的配置：教师特殊限制里写了“张三丰”，但科目里没有。
        config = {
            "num_classes": 1,
            "courses": {
                "数学": {"count": 1, "type": "main"}
            },
            "teacher_names": {
                "数学": ["王军"]
            },
            "teacher_limits": {
                "张三丰": {"max": 5}
            }
        }
        
        result = normal.run_scheduler(config)
        
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'invalid_name')
        self.assertIn("输入的姓名“张三丰”不存在", result['message'])
        self.assertTrue(any("当前识别到的老师有" in s for s in result['suggestions']))

    def test_pre_check_interception(self):
        # 构造一个冲突配置：数学王军带3个班，每班5节课，共15节课。
        # 设置王军的最大限制为10节。
        config = {
            "num_classes": 3,
            "courses": {
                "数学": {"count": 5, "type": "main"}
            },
            "teacher_names": {
                "数学": ["王军"]
            },
            "teacher_limits": {
                "王军": {"max": 10}
            }
        }
        
        result = normal.run_scheduler(config)
        
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['error_type'], 'constraint_conflict')
        self.assertIn("教师【王军】被分配了 15 节课，但您设置的最大限制为 10 节", result['message'])
        self.assertTrue(len(result['suggestions']) > 0)
        self.assertIn("提示的【王军】老师", result['suggestions'][0])

    def test_soft_constraint_ok(self):
        # 构造一个合法配置：数学王军带2个班，每班5节课，共10节课。
        # 设置最大限制为10节。
        config = {
            "num_classes": 2,
            "courses": {
                "数学": {"count": 5, "type": "main"}
            },
            "teacher_names": {
                "数学": ["王军"]
            },
            "teacher_limits": {
                "王军": {"max": 10}
            }
        }
        
        result = normal.run_scheduler(config)
        self.assertEqual(result['status'], 'success')

if __name__ == '__main__':
    unittest.main()
