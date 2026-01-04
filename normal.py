from ortools.sat.python import cp_model
import pandas as pd
import sys
import collections

# 默认配置
DEFAULT_CONFIG = {
    "num_classes": 10,
    "courses": {"语文": 5, "数学": 5, "英语": 5, "体育": 3, "美术": 2, "音乐": 2, "科学": 2, "班会": 1},
    "teacher_names": {} # 新增：存储 {科目: [名字1, 名字2]}
}

def generate_teachers_and_map(num_classes, courses, custom_names=None):
    """
    根据配置生成老师数据和班级映射
    custom_names: 字典 { '语文': ['张伟', '李娜'], '数学': ['王老师'] }
    """
    teachers_db = []
    class_teacher_map = {}
    
    if custom_names is None: custom_names = {}

    # 为了不破坏传入的原始列表，做个深拷贝
    available_names = {k: v[:] for k, v in custom_names.items()}
    
    # 辅助函数：创建老师
    def create_teacher(subj, idx):
        tid = f"t_{subj}_{idx}"
        
        # 核心逻辑：优先从用户名单里取名字
        if subj in available_names and available_names[subj]:
            # 取出第一个名字
            name = available_names[subj].pop(0)
        else:
            # 名单用完了，或者没提供，使用自动命名
            name = f"{subj}老师{idx}"
            
        teachers_db.append({"id": tid, "name": name, "subject": subj})
        return tid

    # 简单的负载策略
    teacher_load_policy = {}
    for subj in courses:
        if courses[subj] >= 5: teacher_load_policy[subj] = 2
        elif courses[subj] >= 3: teacher_load_policy[subj] = 3
        else: teacher_load_policy[subj] = 6

    # 分配老师
    for subject in courses.keys():
        max_classes = teacher_load_policy.get(subject, 4)
        current_teacher_idx = 1
        classes_assigned_count = 0
        current_tid = None
        
        for class_id in range(1, num_classes + 1):
            if classes_assigned_count % max_classes == 0:
                current_tid = create_teacher(subject, current_teacher_idx)
                current_teacher_idx += 1
            
            class_teacher_map[(class_id, subject)] = current_tid
            classes_assigned_count += 1
            
    return teachers_db, class_teacher_map

def run_scheduler(config=None):
    if config is None: config = DEFAULT_CONFIG
    
    NUM_CLASSES = int(config.get('num_classes', 10))
    COURSE_REQUIREMENTS = config.get('courses', DEFAULT_CONFIG['courses'])
    # 获取自定义名字配置
    TEACHER_NAMES = config.get('teacher_names', {})
    
    CLASSES = list(range(1, NUM_CLASSES + 1))
    DAYS = 5
    PERIODS = 9 
    SLOTS = [(d, p) for d in range(DAYS) for p in range(PERIODS)]

    # 1. 生成数据 (传入自定义名字)
    TEACHERS_DB, CLASS_TEACHER_MAP = generate_teachers_and_map(NUM_CLASSES, COURSE_REQUIREMENTS, TEACHER_NAMES)

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
        for subj, count in COURSE_REQUIREMENTS.items():
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
        for subj, count in COURSE_REQUIREMENTS.items():
            limit = 2 
            for d in range(DAYS):
                model.Add(sum(schedule[(c, d, p, subj)] for p in range(PERIODS)) <= limit)

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
                # 约束：该老师在此时段的所有可能课程变量必须为0
                # 即：sum(schedule[c, d, p, s]) == 0
                if assignments:
                    model.Add(sum(schedule[(c, day, period, s)] for (c, s) in assignments) == 0)

    # 求解
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15
    status = solver.Solve(model)

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
            "courses": COURSE_REQUIREMENTS
        }
    else:
        return {"status": "fail"}