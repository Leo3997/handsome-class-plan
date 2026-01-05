from ortools.sat.python import cp_model
import pandas as pd
import sys
import collections

# 默认配置
DEFAULT_CONFIG = {
    "num_classes": 10,
    "courses": {
        "语文": {"count": 5, "type": "main"}, 
        "数学": {"count": 5, "type": "main"}, 
        "英语": {"count": 5, "type": "main"}, 
        "体育": {"count": 3, "type": "minor"}, 
        "美术": {"count": 2, "type": "minor"}, 
        "音乐": {"count": 2, "type": "minor"}, 
        "科学": {"count": 2, "type": "minor"}, 
        "班会": {"count": 1, "type": "minor"}
    },
    "teacher_names": {} # 新增：存储 {科目: [名字1, 名字2]}
}

def generate_teachers_and_map(num_classes, courses, custom_names=None):
    """
    根据配置生成老师数据和班级映射
    courses: 字典 { '语文': {'count': 5, 'type': 'main'}, ... } 或旧格式 { '语文': 5, ... }
    custom_names: 字典 { '语文': ['张伟', '李娜'], '数学': ['王老师'] }
    """
    teachers_db = []
    class_teacher_map = {}
    
    if custom_names is None: custom_names = {}

    # 为了不破坏传入的原始列表，做个深拷贝
    available_names = {k: v[:] for k, v in custom_names.items()}
    
    # 辅助函数：创建老师
    def create_teacher(subj, idx, course_type):
        tid = f"t_{subj}_{idx}"
        
        # 核心逻辑：优先从用户名单里取名字
        if subj in available_names and available_names[subj]:
            # 取出第一个名字
            name = available_names[subj].pop(0)
        else:
            # 名单用完了，或者没提供，使用自动命名
            name = f"{subj}老师{idx}"
            
        teachers_db.append({"id": tid, "name": name, "subject": subj, "type": course_type})
        return tid

    # 标准化课程配置格式(兼容旧格式)
    normalized_courses = {}
    for subj, config in courses.items():
        if isinstance(config, dict):
            normalized_courses[subj] = config
        else:
            # 旧格式兼容：默认按课时数判断类型
            course_type = "main" if config >= 5 else "minor"
            normalized_courses[subj] = {"count": config, "type": course_type}

    # 差异化负载策略
    teacher_load_policy = {}
    for subj, config in normalized_courses.items():
        course_type = config.get("type", "minor")
        course_count = config.get("count", 0)
        
        if course_type == "main":
            # 主课：每位老师带1-3个班(根据班级数动态调整)
            if num_classes <= 3:
                max_classes = 1
            elif num_classes <= 9:
                max_classes = 2
            else:
                max_classes = 3
        else:
            # 副课：每位老师带3-6个班
            if course_count >= 3:
                max_classes = min(6, max(3, num_classes // 2))
            else:
                max_classes = min(6, num_classes)
        
        teacher_load_policy[subj] = max_classes

    # 分配老师
    for subject, config in normalized_courses.items():
        course_type = config.get("type", "minor")
        max_classes = teacher_load_policy.get(subject, 4)
        current_teacher_idx = 1
        classes_assigned_count = 0
        current_tid = None
        
        for class_id in range(1, num_classes + 1):
            if classes_assigned_count % max_classes == 0:
                current_tid = create_teacher(subject, current_teacher_idx, course_type)
                current_teacher_idx += 1
            
            class_teacher_map[(class_id, subject)] = current_tid
            classes_assigned_count += 1
            
    return teachers_db, class_teacher_map

def run_scheduler(config=None):
    if config is None: config = DEFAULT_CONFIG
    
    NUM_CLASSES = int(config.get('num_classes', 10))
    COURSE_REQUIREMENTS = config.get('courses', DEFAULT_CONFIG['courses'])

    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received config courses type: {type(COURSE_REQUIREMENTS)}")
    if isinstance(COURSE_REQUIREMENTS, list):
         logger.info(f"List content (first 1): {COURSE_REQUIREMENTS[:1]}")

    # 如果传入的是列表（前端新版格式），转换为字典
    if isinstance(COURSE_REQUIREMENTS, list):
        new_courses = {}
        for item in COURSE_REQUIREMENTS:
            name = item.get('name')
            if name:
                new_courses[name] = item
        COURSE_REQUIREMENTS = new_courses
        logger.info(f"Converted courses dict keys: {list(COURSE_REQUIREMENTS.keys())}")

    # 获取自定义名字配置
    TEACHER_NAMES = config.get('teacher_names', {})
    logger.info(f"Teacher Names Config: {TEACHER_NAMES}")
    
    # 标准化课程配置格式(兼容旧格式)
    normalized_courses = {}
    for subj, course_config in COURSE_REQUIREMENTS.items():
        if isinstance(course_config, dict):
            # Ensure count is int
            if 'count' in course_config:
                 course_config['count'] = int(course_config['count'])
            normalized_courses[subj] = course_config
        else:
            # 旧格式兼容
            course_type = "main" if course_config >= 5 else "minor"
            normalized_courses[subj] = {"count": course_config, "type": course_type}
    
    CLASSES = list(range(1, NUM_CLASSES + 1))
    DAYS = 5
    PERIODS = 9 
    SLOTS = [(d, p) for d in range(DAYS) for p in range(PERIODS)]

    # 1. 生成数据 (传入自定义名字)
    TEACHERS_DB, CLASS_TEACHER_MAP = generate_teachers_and_map(NUM_CLASSES, COURSE_REQUIREMENTS, TEACHER_NAMES)
    logger.info(f"Generated {len(TEACHERS_DB)} teachers.")
    # logger.info(f"First 5 teachers: {TEACHERS_DB[:5]}")

    # 2. 建模
    model = cp_model.CpModel()
    schedule = {}
    
    for c in CLASSES:
        for d in range(DAYS):
            for p in range(PERIODS):
                for subj in COURSE_REQUIREMENTS.keys():
                    schedule[(c, d, p, subj)] = model.NewBoolVar(f'c{c}_{d}_{p}_{subj}')

    # --- 约束条件 (包含之前的修复：允许空堂) ---
    
    # 1. 唯一性: 每个格子 <= 1 门课 (修复了之前的 400 错误)
    for c in CLASSES:
        for d, p in SLOTS:
            model.Add(sum(schedule[(c, d, p, s)] for s in COURSE_REQUIREMENTS) <= 1)
    
    # 2. 课时总量
    for c in CLASSES:
        for subj, course_cfg in normalized_courses.items():
            count = course_cfg.get("count", 0)
            model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == count)

    # 3. 老师冲突
    teacher_assignments = collections.defaultdict(list)
    for (c, s), t_id in CLASS_TEACHER_MAP.items():
        teacher_assignments[t_id].append((c, s))
    
    for d, p in SLOTS:
        for t_id, assignments in teacher_assignments.items():
            if assignments:
                model.Add(sum(schedule[(c, d, p, s)] for (c, s) in assignments) <= 1)

    # 4. 每日课程均衡
    for c in CLASSES:
        for subj, course_cfg in normalized_courses.items():
            limit = 2 
            for d in range(DAYS):
                model.Add(sum(schedule[(c, d, p, subj)] for p in range(PERIODS)) <= limit)
    
    # 4.5. 副课每日数量限制 (新增)
    # 每个班级每天副课总数 <= 2节
    minor_subjects = [subj for subj, config in normalized_courses.items() if config.get("type") == "minor"]
    if minor_subjects:
        for c in CLASSES:
            for d in range(DAYS):
                model.Add(sum(schedule[(c, d, p, subj)] 
                             for p in range(PERIODS) 
                             for subj in minor_subjects) <= 2)

    # 5. 高级约束 (New)
    CONSTRAINTS = config.get('constraints', {})
    
    # 构建名字到ID的映射 (name -> List[tid])
    name_to_tids = collections.defaultdict(list)
    for t in TEACHERS_DB:
        name_to_tids[t['name']].append(t['id'])
        
    # 处理老师禁排
    unavailable_settings = CONSTRAINTS.get('teacher_unavailable', {})
    for t_name, slots in unavailable_settings.items():
        tids = name_to_tids.get(t_name, [])
        for tid in tids:
            # 找到该老师教的所有 (班级, 科目)
            assignments = teacher_assignments.get(tid, [])
            for day, period in slots:
                if assignments:
                    model.Add(sum(schedule[(c, day, period, s)] for (c, s) in assignments) == 0)

    # 6. 教室资源约束 (Classroom Constraints)
    # config.resources 格式: [{'name': '音乐教室', 'capacity': 1, 'subjects': ['音乐']}]
    resources = config.get('resources', [])
    for res in resources:
        capacity = int(res.get('capacity', 1))
        # 支持中文逗号分隔或列表
        targets = res.get('subjects', [])
        if isinstance(targets, str):
            targets = [s.strip() for s in targets.replace('，', ',').split(',') if s.strip()]
            
        # 找出当前资源涉及的所有 subject
        res_subjects = [s for s in targets if s in COURSE_REQUIREMENTS]
        
        if res_subjects:
            # 对每个时段，统计所有班级上这些课的总数 <= capacity
            for d in range(DAYS):
                for p in range(PERIODS):
                    model.Add(sum(schedule[(c, d, p, s)] 
                                for c in CLASSES 
                                for s in res_subjects) <= capacity)

    # === 7. 软约束优化 (Core Enhancement) ===
    # 采用最小化惩罚值的方式来寻找最优解
    penalties = []
    
    optimization_config = config.get('optimization', {})
    enable_golden_time = optimization_config.get('golden_time', True) 
    max_consecutive = int(optimization_config.get('max_consecutive', 2))
    
    # [优化目标 1] 黄金时间安排 (语数英优先排在上午前4节)
    # 权重: 每一节下午的主科课惩罚 10 分
    if enable_golden_time:
        main_subjects_list = [subj for subj, config in normalized_courses.items() if config.get("type") == "main"]
        for c in CLASSES:
            for d in range(DAYS):
                for p in range(4, PERIODS): # 下午时段 (第5节及以后)
                    for subj in main_subjects_list:
                        # 如果在该时段排了主科，则惩罚
                        penalties.append(schedule[(c, d, p, subj)] * 10)
    
    # [优化目标 2] 主课老师固定班级 (最小化跨班)
    # 权重: 每个主课老师每多带一个班级惩罚 50 分
    # 注意: 由于老师分配策略已经固定了班级映射,这里主要是作为软约束引导
    # 实际上在generate_teachers_and_map中已经实现了固定分配,这里作为备用优化
    
    # [优化目标 3] 副课老师课时均衡
    # 权重: 最小化副课老师之间的课时差异,每节差异惩罚 5 分
    minor_teachers = [t for t in TEACHERS_DB if t.get('type') == 'minor']
    if len(minor_teachers) > 1:
        # 为每个副课老师创建课时计数变量
        teacher_workload = {}
        for t in minor_teachers:
            tid = t['id']
            assignments = teacher_assignments.get(tid, [])
            if assignments:
                # 计算该老师的总课时
                workload_expr = sum(schedule[(c, d, p, s)] 
                                   for (c, s) in assignments 
                                   for d, p in SLOTS)
                # 创建一个整数变量来存储工作量
                workload_var = model.NewIntVar(0, len(CLASSES) * PERIODS * DAYS, f'workload_{tid}')
                model.Add(workload_var == workload_expr)
                teacher_workload[tid] = workload_var
        
        # 最小化最大工作量和最小工作量的差异
        if teacher_workload:
            max_workload = model.NewIntVar(0, len(CLASSES) * PERIODS * DAYS, 'max_workload')
            min_workload = model.NewIntVar(0, len(CLASSES) * PERIODS * DAYS, 'min_workload')
            
            model.AddMaxEquality(max_workload, list(teacher_workload.values()))
            model.AddMinEquality(min_workload, list(teacher_workload.values()))
            
            # 惩罚工作量差异
            workload_diff = model.NewIntVar(0, len(CLASSES) * PERIODS * DAYS, 'workload_diff')
            model.Add(workload_diff == max_workload - min_workload)
            penalties.append(workload_diff * 5)

    # [优化目标 2] 避免连堂疲劳
    # 规则: 任何老师不应连续上超过 max_consecutive 节课
    # 权重: 违反限制惩罚 100 分 (尽量避免)
    
    # 先整理每个老师的课程变量列表: teacher_id -> [(day, period, var), ...]
    # 注意：这里需要反向查找，知道每个变量对应哪个老师
    
    # 预处理：按天分组，整理每个老师每天的课程变量
    teacher_vars_by_day = {tid: {d: [] for d in range(DAYS)} for tid in teacher_assignments}
    
    for c in CLASSES:
        for d in range(DAYS):
            for p in range(PERIODS):
                for subj in COURSE_REQUIREMENTS:
                    tid = CLASS_TEACHER_MAP.get((c, subj))
                    if tid:
                        teacher_vars_by_day[tid][d].append((p, schedule[(c, d, p, subj)]))
                        
    # 添加连堂约束
    for tid, days_data in teacher_vars_by_day.items():
        for d, day_vars in days_data.items():
            # 按节次排序
            day_vars.sort(key=lambda x: x[0])
            
            # 使用滑动窗口检测
            # 窗口大小 = max_consecutive + 1
            # 如果窗口内排课数量 == 窗口大小，说明连续上了 max_consecutive + 1 节，违规
            window_size = max_consecutive + 1
            period_vars = [v[1] for v in day_vars] # 只有变量，没有节次索引了，假设每天都可能排满
            
            # 由于 periods 是离散的，我们实际上是在检测 0..8 节
            # 为了简单，直接遍历 0 到 PERIODS - window_size
            for i in range(PERIODS - window_size + 1):
                # 获取当前窗口内的课程变量 (第 i, i+1, ..., i+win-1 节)
                # 注意：这里需要准确获取对应节次的变量。上面 teacher_vars_by_day 可能并没有覆盖所有 p (如果某节没课)
                # 所以最稳妥是重新遍历
                pass

    # 重新实现连堂检测 - 更直接的方法
    for tid, assignments in teacher_assignments.items():
        # assignments: list of (class_id, subject)
        for d in range(DAYS):
            # 获取该老师该天每一节课是否在上课的 BoolVar 表达式
            # teacher_active[p] = sum(schedule[c,d,p,s] for c,s in assignments)
            # 因为约束3保证了老师同一时刻只能上一节，所以 sum 结果只能是 0 或 1
            teacher_active = []
            for p in range(PERIODS):
                teacher_active.append(sum(schedule[(c, d, p, s)] for (c, s) in assignments))
            
            # 滑动窗口
            window_size = max_consecutive + 1
            if window_size <= PERIODS:
                for i in range(PERIODS - window_size + 1):
                    # 这是一个线性表达式：sum(窗口内的 active)
                    # 如果 sum >= window_size，说明连续 window_size 节都有课
                    # 创建一个临时 BoolVar 来表示是否违规
                    
                    # 优化：不创建额外变量，直接作为软约束惩罚项
                    # 比如: model.Minimize(sum(schedule))
                    # 但这里我们需要 "如果连续3节都有课，就惩罚"
                    # 也就是 Minimize( (x1 AND x2 AND x3) * penalty )
                    # 在 OR-Tools 中，可以用 model.AddMultiplicationEquality(target, [vars])
                    
                    is_consecutive = model.NewBoolVar(f'fatigue_{tid}_{d}_{i}')
                    current_window_vars = teacher_active[i : i+window_size]
                    
                    # 只有当窗口内所有时段都有课时，is_consecutive 才为 1
                    # 但 teacher_active 里的元素是 SumArray (LinearExpr)，不能直接传给 AddMultiplicationEquality
                    # 所以先要把 LinearExpr 转成 BoolVar (其实本身约束3早已限制它 <= 1)
                    # 不过为了严谨，我们可以用 model.Add(sum(current_window_vars) >= window_size).OnlyEnforceIf(is_consecutive)
                    # model.Add(sum(current_window_vars) < window_size).OnlyEnforceIf(is_consecutive.Not())
                    
                    model.Add(sum(current_window_vars) >= window_size).OnlyEnforceIf(is_consecutive)
                    model.Add(sum(current_window_vars) < window_size).OnlyEnforceIf(is_consecutive.Not())
                    
                    penalties.append(is_consecutive * 100)

    # 设置总目标：最小化惩罚
    if penalties:
        model.Minimize(sum(penalties))

    # 求解
    solver = cp_model.CpSolver()
    # 增加一点求解时间以应对更复杂的优化目标
    solver.parameters.max_time_in_seconds = 20 
    status = solver.Solve(model)
    logger.info(f"Solver status: {solver.StatusName(status)}")

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # === 统计模块 ===
        stats = {}
        t_id_to_name = {t['id']: t['name'] for t in TEACHERS_DB}
        
        # 初始化统计数据
        for t_name in t_id_to_name.values():
            stats[t_name] = {"total": 0, "daily": [0] * 5}
            
        # 遍历排课结果进行统计
        for c in CLASSES:
            for d in range(DAYS):
                for p in range(PERIODS):
                    for subj in COURSE_REQUIREMENTS:
                        if solver.Value(schedule[(c, d, p, subj)]) == 1:
                            tid = CLASS_TEACHER_MAP.get((c, subj))
                            if tid is not None and tid in t_id_to_name:
                                t_name = t_id_to_name[tid]
                                stats[t_name]["total"] += 1
                                stats[t_name]["daily"][d] += 1

        return {
            "status": "success",
            "stats": stats,
            "solver": solver,
            "vars": schedule,
            "teachers_db": TEACHERS_DB,
            "class_teacher_map": CLASS_TEACHER_MAP,
            "classes": CLASSES,
            "days": DAYS,
            "periods": PERIODS,
            "courses": COURSE_REQUIREMENTS,
            "resources": resources  # 使用实际的resources变量
        }
    else:
        return {"status": "fail"}