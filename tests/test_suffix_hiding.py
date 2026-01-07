import unittest
import normal
import app
import substitution

class TestSuffixHiding(unittest.TestCase):
    def test_serialize_hides_suffix(self):
        # 构造一个触发 sharding 的场景
        config = {
            "num_classes": 1,
            "courses": {
                "语文": {"count": 6, "type": "main"}
            },
            "teacher_names": {
                "语文": ["王荣"]
            },
            "teacher_limits": {
                "王荣": {"max": 3}
            }
        }
        
        result = normal.run_scheduler(config)
        self.assertEqual(result['status'], 'success')
        
        # 验证内部 courses 确实包含后缀
        self.assertIn('语文_AUTO_SUB', result['courses'])
        
        # 使用 app 中的序列化逻辑
        system = substitution.SubstitutionSystem(result)
        formatted = app.serialize_schedule(system)
        
        # 检查序列化后的数据
        # 遍历所有格子，确保没有 _AUTO_SUB
        found_subject = False
        for p in formatted[1]:
            for d in formatted[1][p]:
                cell = formatted[1][p][d]
                if cell:
                    self.assertNotIn('_AUTO_SUB', cell['subject'])
                    if cell['subject'] == '语文':
                        found_subject = True
        
        self.assertTrue(found_subject, "应该能找到名为 '语文' 的科目")

if __name__ == '__main__':
    unittest.main()
