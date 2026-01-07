import normal
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)

def test_grade_constraints():
    config = {
        "num_classes": 6,
        "grades": {
            "初一": {
                "start_class_id": 1,
                "count": 2,
                "courses": {
                    "语文": 5, "数学": 5, "外语": 5, "科学": 5, "体育": 3, "艺术": 2, "道法": 2, "历史": 2, "综合": 6
                }
            },
            "初三": {
                "start_class_id": 11,
                "count": 2,
                "courses": {
                    "语文": 6, "数学": 6, "外语": 6, "科学": 5, "体育": 3, "道法": 3, "历史": 3, "自习": 3
                }
            }
        },
        "teacher_names": {
            "语文": ["语1", "语2"],
            "数学": ["数1", "数2"],
            "外语": ["外1", "外2"],
            "科学": ["科1", "科2"]
        },
        "optimization": {
            "golden_time": True
        }
    }

    print("开始测试年级差异化排课...")
    result = normal.run_scheduler(config)

    if result['status'] == 'success':
        print("✓ 排课成功！")
        
        solver = result['solver']
        # 验证班级
        classes = result['classes']
        print(f"生成的班级: {classes}")
        
        # 验证初一禁排 (周四下午第 4 节, index (3, 7))
        for c in [1, 2]:
            for s in result['vars_list']:
                if (c, 3, 7, s) in result['vars'] and solver.Value(result['vars'][(c, 3, 7, s)]) > 0.5:
                    print(f"✗ 错误：初一班级 {c} 在周四下午第 4 节排了课！")
                    return
        print("✓ 初一禁排检查通过 (周四下午第 4 节为空)")

        # 验证初三科学课分布 (尽量 4+1)
        for c in [11, 12]:
            am_sci = 0
            pm_sci = 0
            for d in range(5):
                for p in range(4): # 上午
                    if (c, d, p, "科学") in result['vars'] and solver.Value(result['vars'][(c, d, p, "科学")]) > 0.5: am_sci += 1
                for p in range(4, 9): # 下午
                    if (c, d, p, "科学") in result['vars'] and solver.Value(result['vars'][(c, d, p, "科学")]) > 0.5: pm_sci += 1
            
            print(f"初三班级 {c} 科学课分布: 上午 {am_sci}, 下午 {pm_sci}")
        
        # 验证初一科学课分布 (尽量 3+2)
        for c in [1, 2]:
            am_sci = 0
            pm_sci = 0
            for d in range(5):
                for p in range(4): # 上午
                    if (c, d, p, "科学") in result['vars'] and solver.Value(result['vars'][(c, d, p, "科学")]) > 0.5: am_sci += 1
                for p in range(4, 9): # 下午
                    if (c, d, p, "科学") in result['vars'] and solver.Value(result['vars'][(c, d, p, "科学")]) > 0.5: pm_sci += 1
            
            print(f"初一班级 {c} 科学课分布: 上午 {am_sci}, 下午 {pm_sci}")

        print("✓ 测试完成。")
    else:
        print("✗ 排课失败！")

if __name__ == "__main__":
    test_grade_constraints()
