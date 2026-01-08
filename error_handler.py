import collections
import math


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
    """分析排课失败的可能原因并生成建议 (兼容 grades 新格式)"""
    
    # === [修复] 兼容新旧两种数据格式 ===
    # 新格式：config.grades = {"初一": {"count": 6, "courses": {...}}, ...}
    # 旧格式：config.courses = {"语文": {"count": 7}, ...}
    
    grades = config.get('grades', {})
    courses = config.get('courses', {})
    
    # 计算班级数和总课时
    num_classes = 0
    total_hours = 0
    all_courses = {}  # 统一格式：{科目名: {count, ...}}
    
    if grades and isinstance(grades, dict):
        # 新格式：从 grades 中提取
        # 注意：每个年级的课表是独立的，应该检查单个年级的课时是否超限
        max_grade_hours = 0
        for grade_name, grade_data in grades.items():
            if isinstance(grade_data, dict):
                num_classes += grade_data.get('count', 0)
                grade_courses = grade_data.get('courses', {})
                grade_hours = 0
                if isinstance(grade_courses, dict):
                    for c_name, c_data in grade_courses.items():
                        if isinstance(c_data, dict):
                            grade_hours += int(c_data.get('count', 0))
                            all_courses[c_name] = c_data
                max_grade_hours = max(max_grade_hours, grade_hours)
        total_hours = max_grade_hours  # 取最大的单年级课时
    elif courses:
        # 旧格式
        num_classes = config.get('num_classes', 0)
        if isinstance(courses, dict):
            for c_name, c_data in courses.items():
                if isinstance(c_data, dict):
                    total_hours += int(c_data.get('count', 0))
                    all_courses[c_name] = c_data
                else:
                    total_hours += int(c_data)
                    all_courses[c_name] = {'count': c_data}
        elif isinstance(courses, list):
            # 如果是列表格式
            for c in courses:
                if isinstance(c, dict):
                    total_hours += int(c.get('count', 0))
                    all_courses[c.get('name', 'unknown')] = c

    max_capacity = 40  # 一周5天x8节课
    
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
    teacher_names = config.get('teacher_names', {})
    
    # 统计每个科目的全校总课时 (支持年级隔离统计)
    # 结构：{(科目, 年级): 总课时} - 主课带年级，副课年级为 "All"
    subject_grade_lessons = collections.defaultdict(int)
    
    if grades and isinstance(grades, dict):
        for g_name, g_data in grades.items():
            if isinstance(g_data, dict):
                g_count = g_data.get('count', 0)
                g_courses = g_data.get('courses', {})
                if isinstance(g_courses, dict):
                    for c_name, c_data in g_courses.items():
                        c_vol = c_data.get('count', 0) if isinstance(c_data, dict) else c_data
                        c_type = c_data.get('type', 'minor') if isinstance(c_data, dict) else ('main' if int(c_vol) >= 5 else 'minor')
                        
                        # 核心逻辑同步：主课按年级统计，副课合并统计
                        target_key = (c_name, g_name) if c_type == "main" else (c_name, "All")
                        subject_grade_lessons[target_key] += (int(c_vol) * g_count)
    else:
        # 旧格式兼容
        for subj, val in all_courses.items():
            count = val.get('count', 0) if isinstance(val, dict) else val
            subject_grade_lessons[(subj, "All")] = int(count) * max(num_classes, 1)

    # 老师名单也需要按年级隔离处理
    grade_teacher_names = config.get('grade_teacher_names', {})

    for (subject, grade_key), total_needed in subject_grade_lessons.items():
        # 获取该科目在该层级的老师名单
        if grade_key != "All" and grade_key in grade_teacher_names:
            teachers = grade_teacher_names[grade_key].get(subject, [])
        else:
            teachers = teacher_names.get(subject, [])
            
        num_teachers = len(teachers) if teachers else 1
        max_per_teacher = 40
        total_teacher_capacity = num_teachers * max_per_teacher
        
        # [强化逻辑] 全量学科开启自动补齐
        auto_shard_subjects = list(all_courses.keys())
        
        display_name = f"「{grade_key}-{subject}」" if grade_key != "All" else f"「{subject}」"
        
        if total_needed > total_teacher_capacity:
            if subject in auto_shard_subjects:
                suggestions.append(f"提示：科目{display_name}总需求 {total_needed} 节超过了现有老师负荷({total_teacher_capacity}节)。后台已自动启用“全学科智能补齐”，已为您动态扩充老师名额。")
            else:
                error_type = "teacher_overload"
                message = f"{subject}老师课时超限"
                suggestions.append(f"{display_name}需求 {total_needed} 节，但最大容量只有 {total_teacher_capacity} 节。")
        elif total_needed > num_teachers * 30:
             suggestions.append(f"注意：{display_name}平均周课时已达 {total_needed/num_teachers:.1f} 节。")

    # 通用建议
    if error_type == "unknown":
        error_type = "constraint_too_tight"
        message = "约束条件过于严格，求解器在规定时间内无法找到解"
        suggestions.extend([
            "1. 您的课表是否已满(45/45)? 尝试减少一节非主课。",
            "2. 是否有老师的课时量接近45节? 请增加老师。",
            "3. 检查是否有互斥的'不排课'时间设置。"
        ])
    
    # === [新增] 重建 class_metadata 供后续冲突检查使用 ===
    class_metadata = {}
    if grades and isinstance(grades, dict):
        global_class_index = 1
        for grade_name, grade_data in grades.items():
            count = grade_data.get('count', 0)
            start_num = grade_data.get('start_class_id', 1)
            g_courses = grade_data.get('courses', {})
            for i in range(count):
                class_metadata[global_class_index] = {
                    "grade": grade_name,
                    "requirements": g_courses
                }
                global_class_index += 1
    else:
        num_classes = config.get('num_classes', 0)
        for i in range(1, num_classes + 1):
            class_metadata[i] = {
                "grade": "Default",
                "requirements": all_courses
            }

    # 检查3：禁排冲突与课时饱和度 (Pigeonhole Principle)
    rules = config.get('rules', [])
    for g_p in grades.keys() if grades else ["Default"]:
        g_name = g_p
        # 寻找该年级的代表性班级需求
        total_g_hours = 0
        if grades and g_name in grades:
             g_courses = grades[g_name].get('courses', {})
             total_g_hours = sum(int(c.get('count', 0)) if isinstance(c, dict) else int(c) for c in g_courses.values())
        else:
             total_g_hours = total_hours

        # 计算该年级的禁排时段数 (针对所有科目的禁排)
        grade_forbidden_slots = set()
        for rule in rules:
            if rule.get('type') == 'FORBIDDEN_SLOTS':
                targets = rule.get('targets', {})
                # 如果禁排规则的目标包含该年级，且没有指定特定科目或老师（即针对全班）
                if (g_name in targets.get('grades', []) or not targets.get('grades')) and not targets.get('subjects') and not targets.get('names'):
                    slots = rule.get('params', {}).get('slots', [])
                    for s in slots:
                        grade_forbidden_slots.add(tuple(s))
        
        forbidden_count = len(grade_forbidden_slots)
        available_slots = 40 - forbidden_count
        
        if total_g_hours > available_slots:
            error_type = "pigeonhole_conflict"
            message = f"{g_name}课时饱和冲突"
            suggestions.append(f"【致命冲突】「{g_name}」总课时为 {total_g_hours} 节，但由于禁排规则限制，该年级每周仅剩 {available_slots} 个可用时段。")
            suggestions.append(f"建议：对于周五下午等“活动课”时间，请不要将其设为【年级禁排】，而应将“政教活动”等科目使用【固定时段】规则强制排入。")

    # 检查4：FIXED_SLOTS 引发的并发老师不足
    for rule in rules:
        if rule.get('type') == 'FIXED_SLOTS':
            targets = rule.get('targets', {})
            fixed_subjs = targets.get('subjects', [])
            fixed_slots = rule.get('params', {}).get('slots', [])
            if not fixed_subjs or not fixed_slots: continue
            
            for s_name in fixed_subjs:
                # 计算受此规则影响的班级总数
                r_grades = targets.get('grades', [])
                affected_classes_ids = []
                for cid, meta in class_metadata.items():
                    if (not r_grades or meta.get('grade') in r_grades) and s_name in meta.get('requirements'):
                        affected_classes_ids.append(cid)
                
                if not affected_classes_ids: continue
                
                needed_teachers_per_slot = math.ceil(len(affected_classes_ids) / len(fixed_slots))
                
                # 获取该科目可用老师总数
                teachers = teacher_names.get(s_name, [])
                t_count = len(teachers) if teachers else 1
                
                if needed_teachers_per_slot > t_count:
                    suggestions.append(f"【并发风险】科目「{s_name}」在指定固定时段并发需求为 {needed_teachers_per_slot} 名老师，但您只配置了 {t_count} 名。")
                    suggestions.append(f"说明：虽然系统会通过“智慧分片”尝试解决，但在 100% 满课环境下，实名老师过少会大幅增加冲突概率，建议至少补充至 {needed_teachers_per_slot} 人。")

    # 检查5：资源（实验室/操场）物理极限检查
    resources = config.get('resources', [])
    if resources:
        # 统计每个科目对特定资源的总需求课时
        resource_subject_demand = collections.defaultdict(int)
        for cid, meta in class_metadata.items():
            reqs = meta.get('requirements', {})
            for s_name, s_info in reqs.items():
                count = s_info.get('count', 0) if isinstance(s_info, dict) else int(s_info)
                resource_subject_demand[s_name] += count
        
        # 统计资源的总承载能力
        # 一个资源在 40 个时段内的承载力 = capacity * 40
        for res in resources:
            r_name = res.get('name')
            r_cap = res.get('capacity', 1)
            r_subjs = res.get('subjects', '')
            if not r_subjs: continue
            
            # 一个资源可能支持多个科目，这里简化处理：统计所有匹配科目的总需求
            match_subjs = [s.strip() for s in r_subjs.split(',')]
            total_res_demand = sum(resource_subject_demand.get(s, 0) for s in match_subjs)
            total_res_capacity = r_cap * 40
            
            if total_res_demand > total_res_capacity:
                error_type = "resource_overflow"
                message = f"资源「{r_name}」物理容量不足"
                suggestions.append(f"【物理瓶颈】资源「{r_name}」(容量:{r_cap}) 每周最大承载 {total_res_capacity} 课时。")
                suggestions.append(f"但匹配科目（{r_subjs}）的全校总需求为 {total_res_demand} 课时。")
                suggestions.append(f"建议：增加资源“{r_name}”的容量至 {math.ceil(total_res_demand / 40)} 或减少相关科目的课时。")

    # 通用建议
    if error_type == "unknown":
        message = "未知约束冲突"
        suggestions.append("求解器在规定时间内未锁定具体冲突点。请尝试降低部分软约束权重，或检查是否有互相排斥的硬约束（如：两名核心老师在同一时间都要求禁排）。")

    return {
        "status": "error",
        "error_type": error_type,
        "message": message,
        "suggestions": suggestions
    }
