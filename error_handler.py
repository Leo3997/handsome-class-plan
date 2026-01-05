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
    """分析排课失败的可能原因并生成建议
    
    Args:
        config: 排课配置字典
        
    Returns:
        dict: 包含错误类型、消息和建议的字典
    """
    num_classes = config.get('num_classes', 0)
    courses = config.get('courses', {})
    
    total_hours = sum(courses.values())
    max_capacity = 45  # 一周5天x9节课 (修正：原为30)
    
    suggestions = []
    error_type = "unknown"
    message = "排课失败"
    
    # 检查1：总课时是否超载
    if total_hours > max_capacity:
        error_type = "schedule_overload"
        message = f"总课时({total_hours})超过每周容量({max_capacity})"
        
        # 计算需要减少的课时
        excess = total_hours - max_capacity
        suggestions.append(f"需要减少 {excess} 节课时")
        
        # 建议减少课时最多的科目
        sorted_courses = sorted(courses.items(), key=lambda x: x[1], reverse=True)
        for subject, count in sorted_courses[:3]:
            if count > 2:
                suggestions.append(f"可考虑减少「{subject}」从 {count} 节到 {count-1} 节")
                if len(suggestions) >= 4:
                    break
    
    # 检查2：老师数量是否足够
    teacher_names = config.get('teacher_names', {})
    for subject, count in courses.items():
        provided_teachers = len(teacher_names.get(subject, []))
        
        # 简单估算需要的老师数量（假设每个老师最多带3个班级的同一科目）
        if count >= 5:
            max_classes_per_teacher = 2
        elif count >= 3:
            max_classes_per_teacher = 3
        else:
            max_classes_per_teacher = 6
            
        required_teachers = (num_classes + max_classes_per_teacher - 1) // max_classes_per_teacher
        
        # if provided_teachers > 0 and provided_teachers < required_teachers:
        #     error_type = "insufficient_teachers"
        #     message = f"{subject}老师不足"
        #     suggestions.append(f"「{subject}」需要至少 {required_teachers} 位老师，当前只提供了 {provided_teachers} 位")
        pass
    
    # 检查3：每日课程均衡性
    for subject, count in courses.items():
        if count > 10:  # 一周超过10节的科目
            error_type = "unbalanced_schedule"
            message = "课程分布不均衡"
            suggestions.append(f"「{subject}」课时过多({count}节)，可能难以均匀分配到每天")
    
    # 如果没有明确的问题，给出通用建议
    if error_type == "unknown":
        error_type = "constraint_too_tight"
        message = "约束条件过于严格，求解器无法找到可行方案"
        suggestions.extend([
            "尝试减少某些课程的每周节数",
            "增加班级数量或减少必修科目",
            "检查自定义老师配置是否合理"
        ])
    
    return {
        "error_type": error_type,
        "message": message,
        "suggestions": suggestions
    }
