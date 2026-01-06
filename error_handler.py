"""
错误处理模块
提供自定义异常类型和错误分析功能
"""


class ScheduleError(Exception):
    """排课系统通用异常基类"""
    pass


class ScheduleOverloadError(ScheduleError):
    """课时超载异常"""
    def __init__(self, total_hours, max_hours=30):
        self.total_hours = total_hours
        self.max_hours = max_hours
        super().__init__(f"总课时({total_hours})超过容量({max_hours})")


class ConstraintTooTightError(ScheduleError):
    """约束过紧异常"""
    def __init__(self,message="排课约束太紧，无法找到可行解决方案"):
        super().__init__(message)


class InvalidConfigError(ScheduleError):
    """配置无效异常"""
    pass


def analyze_failure(config):
    """分析排课失败的可能原因并生成建议 (已修复兼容性)"""
    num_classes = config.get('num_classes', 0)
    courses = config.get('courses', {})
    
    # === [修复 1] 正确计算总课时 ===
    total_hours = 0
    for c_data in courses.values():
        if isinstance(c_data, dict):
            # 新格式：从字典取 count
            total_hours += int(c_data.get('count', 0))
        else:
            # 旧格式：直接是数字
            total_hours += int(c_data)

    max_capacity = 45  # 一周5天x9节课
    
    suggestions = []
    error_type = "unknown"
    message = "排课失败"
    
    # 检查1：总课时是否超载
    if total_hours > max_capacity:
        error_type = "schedule_overload"
        message = f"总课时({total_hours})超过每周容量({max_capacity})"
        
        excess = total_hours - max_capacity
        suggestions.append(f"严重警告：每个班级每周只有 {max_capacity} 个格子，但您安排了 {total_hours} 节课！")
        suggestions.append(f"必须减少至少 {excess} 节课才能排课。")
    
    # 检查2：老师资源是否枯竭
    # 比如：数学王军，如果6个班每班7节，总共42节。一周只有45节课。
    # 只要稍微有一点点冲突（比如开会、教研、或者禁排），他就排不出来了。
    teacher_names = config.get('teacher_names', {})
    
    for subject, val in courses.items():
        count = val.get('count', 0) if isinstance(val, dict) else val
        teachers = teacher_names.get(subject, [])
        if not teachers: continue
        
        # 计算该科目总课时需求
        total_subject_lessons = count * num_classes
        # 计算老师总运力 (假设极限是每人每周45节)
        total_teacher_capacity = len(teachers) * 45
        
        if total_subject_lessons > total_teacher_capacity:
             error_type = "teacher_overload"
             message = f"{subject}老师课时超限"
             suggestions.append(f"「{subject}」全校共需 {total_subject_lessons} 节，但老师最大运力只有 {total_teacher_capacity} 节。")
        elif total_subject_lessons > len(teachers) * 40:
             # 警告阈值
             suggestions.append(f"「{subject}」老师平均周课时超过40节，极易导致排课失败。")

    # 通用建议
    if error_type == "unknown":
        error_type = "constraint_too_tight"
        message = "约束条件过于严格，求解器在规定时间内无法找到解"
        suggestions.extend([
            "1. 您的课表是否已满(45/45)? 尝试减少一节非主课。",
            "2. 是否有老师的课时量接近45节? 请增加老师。",
            "3. 检查是否有互斥的'不排课'时间设置。"
        ])
    
    return {
        "error_type": error_type,
        "message": message,
        "suggestions": suggestions
    }
