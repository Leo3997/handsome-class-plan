from ortools.sat.python import cp_model
import pandas as pd
import sys
import collections
import statistics

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
    # 1. 建立全局老师注册表 (Name -> ID)
    # 只要名字一样，ID就一样，这样求解器就知道是同一个人
    name_to_id_map = {}
    
    def get_or_create_teacher_id(name, subject, type_):
        if name not in name_to_id_map:
            # 如果是第一次出现，生成新ID并存入DB
            tid = f"t_{name}" # 使用名字作为ID的一部分
            name_to_id_map[name] = tid
            teachers_db.append({
                "id": tid, 
                "name": name, 
                "subject": subject, 
                "type": type_
            })
        return name_to_id_map[name]

    # 标准化课程配置格式(兼容旧格式)
    normalized_courses = {}
    for subj, config in courses.items():
        if isinstance(config, dict):
            normalized_courses[subj] = config
        else:
            # 旧格式兼容
            course_type = "main" if config >= 5 else "minor"
            normalized_courses[subj] = {"count": config, "type": course_type}

    # 2. 准备每科的候选老师队列
    subject_teacher_queues = {}
    
    for subj, config in normalized_courses.items():
        course_type = config.get("type", "minor")
        
        # 获取该科目配置的老师名单
        # 先做个拷贝避免影响原数据
        names_list = custom_names.get(subj, [])[:]
        
        # 如果没配置名单，我们自动生成虚拟老师
        # 逻辑：根据班级数估算需要几个虚拟老师
        if not names_list:
            # 简单估算：假设每人带3个班
            needed = max(1, (num_classes + 2) // 3)
            names_list = [f"{subj}老师{i+1}" for i in range(needed)]
            
        subject_teacher_queues[subj] = {
            "names": names_list,
            "type": course_type,
            "ptr": 0 # 轮询指针
        }

    # 3. 分配老师给班级 (轮询分配)
    for class_id in range(1, num_classes + 1):
        for subj, queue_data in subject_teacher_queues.items():
            names = queue_data["names"]
            ptr = queue_data["ptr"]
            
            # 取出名字
            teacher_name = names[ptr]
            
            # 获取唯一ID (关键步骤)
            tid = get_or_create_teacher_id(teacher_name, subj, queue_data["type"])
            
            # 绑定映射
            class_teacher_map[(class_id, subj)] = tid
            
            # 移动指针 (轮询)
            queue_data["ptr"] = (ptr + 1) % len(names)
            
    return teachers_db, class_teacher_map

def evaluate_quality(schedule_vars, solver, classes, days, periods, course_requirements, class_teacher_map, teachers_db):
    """
    对生成的课表进行多维度打分 (满分100)
    """
    score = 100
    logs = []
    
    # 辅助数据准备
    schedule_data = {} # (c, d, p) -> subj
    teacher_schedule = {t['id']: [] for t in teachers_db} # tid -> [(d, p)]
    
    for c in classes:
        for d in range(days):
            for p in range(periods):
                for subj in course_requirements:
                    if solver.Value(schedule_vars[(c, d, p, subj)]):
                        schedule_data[(c, d, p)] = subj
                        tid = class_teacher_map.get((c, subj))
                        if tid:
                            teacher_schedule[tid].append((d, p))

    # 1. 黄金时间评估 (Main subjects should be in p <= 3)
    # 权重：每发现一节主课在下午(p>=4)，扣 1 分
    main_subjects = [s for s, conf in course_requirements.items() if conf.get('type') == 'main']
    bad_time_count = 0
    for (c, d, p), subj in schedule_data.items():
        if subj in main_subjects and p >= 4:
            bad_time_count += 1
            score -= 1 # 扣分
    if bad_time_count > 0:
        logs.append(f"黄金时间: 发现 {bad_time_count} 节主课被排在了下午")

    # 2. 教师连堂评估 (Consecutive > 2)
    # 权重：每发现一次连堂超过2节，扣 5 分
    fatigue_count = 0
    for tid, slots in teacher_schedule.items():
        # 按天分组
        daily_slots = {d: [] for d in range(days)}
        for (d, p) in slots:
            daily_slots[d].append(p)
        
        for d, periods_list in daily_slots.items():
            periods_list.sort()
            consecutive = 1
            for i in range(len(periods_list) - 1):
                if periods_list[i+1] == periods_list[i] + 1:
                    consecutive += 1
                else:
                    if consecutive > 2:
                        fatigue_count += 1
                        score -= 5
                    consecutive = 1
            if consecutive > 2: # Check last run
                fatigue_count += 1
                score -= 5
    if fatigue_count > 0:
        logs.append(f"教师疲劳: 发现 {fatigue_count} 人次连续上课超过 2 节")

    # 3. 教师负载均衡评估 (Variance)
    # 权重：根据方差扣分
    minor_teachers = [t['id'] for t in teachers_db if t.get('type') == 'minor']
    if len(minor_teachers) > 1:
        workloads = [len(teacher_schedule[tid]) for tid in minor_teachers]
        if workloads:
            stdev = statistics.stdev(workloads) if len(workloads) > 1 else 0
            if stdev > 2:
                deduction = int(stdev * 2)
                score -= deduction
                logs.append(f"负载均衡: 副科老师课时方差较大 ({stdev:.1f})，扣 {deduction} 分")

    # 4. 班级课时总数一致性 (Check Consistency)
    # 权重：如果有班级总课时不对，大幅扣分
    for c in classes:
        total = sum(1 for d in range(days) for p in range(periods) if (c, d, p) in schedule_data)
        expected = sum(conf.get('count', 0) for conf in course_requirements.values())
        if total != expected:
            score -= 10
            logs.append(f"课时异常: {c}班 排课总数({total})与预期({expected})不符")

    # 保底分数 0
    score = max(0, score)
    
    return {
        "score": score,
        "details": logs
    }


def run_scheduler(config=None):
    if config is None: config = DEFAULT_CONFIG
    
    NUM_CLASSES = int(config.get('num_classes', 10))
    original_courses = config.get('courses', DEFAULT_CONFIG['courses'])
    teacher_names_config = config.get('teacher_names', {})
    teacher_limits = config.get("teacher_limits", {})

    # Debug logging
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Received config courses type: {type(original_courses)}")

    # -------------------------------------------------------------------------
    # [架构升级] 智能分片层 Pro (Smart Sharding Layer - Full Scan)
    # 逻辑：扫描所有任课老师，只要有一人有限制，就触发全局拆分，并对齐老师名单。
    # -------------------------------------------------------------------------
    
    # 1. 预处理课程格式
    COURSE_REQUIREMENTS_BASE = {}
    if isinstance(original_courses, list):
        for item in original_courses:
            if item.get('name'): COURSE_REQUIREMENTS_BASE[item['name']] = item
    else:
        COURSE_REQUIREMENTS_BASE = original_courses.copy()

    # 2. 自动拆分与名单重构
    final_courses = {}
    final_teacher_names = {}
    sharding_report = [] # [新增] 用于存储替换详情
    
    # 辅助函数：获取老师的最大限制
    def get_teacher_max_limit(t_name):
        clean_name = t_name.strip()
        for k, v in teacher_limits.items():
            if k.strip() == clean_name and v.get('max') is not None and str(v['max']).strip() != "":
                return int(v['max'])
        return 999 # 没有限制则默认无穷大

    for subj, info in COURSE_REQUIREMENTS_BASE.items():
        # 标准化 info
        if not isinstance(info, dict): 
            course_type = "main" if int(info) >= 5 else "minor"
            info = {"count": int(info), "type": course_type}
        else:
            info = info.copy()
            info['count'] = int(info['count'])
            
        total_count = info['count']
        assigned_teachers = teacher_names_config.get(subj, [])
        
        # [步骤 A] 扫描该科目所有老师，寻找“短板”（限制最严格的那个数）
        min_limit_found = 999
        limited_teachers = set() # 记录哪些老师受限
        
        if assigned_teachers:
            for t_name in assigned_teachers:
                limit = get_teacher_max_limit(t_name)
                if limit < total_count:
                    min_limit_found = min(min_limit_found, limit)
                    limited_teachers.add(t_name)
        
        # [步骤 B] 判断是否需要拆分
        if limited_teachers and min_limit_found < total_count:
            # 需要拆分！
            main_count = min_limit_found
            overflow_count = total_count - main_count
            
            # 1. 创建“本体”课程 (所有人都要上)
            final_courses[subj] = info.copy()
            final_courses[subj]['count'] = main_count
            final_teacher_names[subj] = assigned_teachers # 所有人名单保持不变
            
            # 2. 创建“分身”课程 (溢出部分)
            sub_name = f"{subj}_AUTO_SUB"
            final_courses[sub_name] = info.copy()
            final_courses[sub_name]['count'] = overflow_count
            
            # [关键步骤] 构建分身课的老师名单 (List Alignment)
            sub_teacher_list = []
            
            # 尝试找一个“默认替补”：优先找名单里没受限的人，找不到就用【自习】
            default_sub = "【自习】"
            for t in assigned_teachers:
                if t not in limited_teachers:
                    default_sub = t 
                    break
            
            for idx, t in enumerate(assigned_teachers):
                if t in limited_teachers:
                    # 这是一个受限老师，他上不了分身课，给替补
                    sub_teacher_list.append(default_sub)
                    # [新增] 记录替换详情：哪个班(轮询决定) 的 哪个老师 被 谁 替了
                    # 注意：轮询逻辑在 generate_teachers_and_map 里，
                    # 班级 C 的老师索引是 (C-1) % len(assigned_teachers)
                    for c_idx in range(NUM_CLASSES):
                        if (c_idx % len(assigned_teachers)) == idx:
                            sharding_report.append({
                                "class_id": c_idx + 1,
                                "subject": subj,
                                "original": t,
                                "substitute": default_sub,
                                "count": overflow_count
                            })
                else:
                    # 这是一个普通老师，他自己上分身课
                    sub_teacher_list.append(t)
            
            final_teacher_names[sub_name] = sub_teacher_list
            logger.info(f"Course {subj} split: {main_count} + {overflow_count} (AUTO_SUB teachers: {sub_teacher_list})")
        else:
            # 不需要拆分，保持原样
            final_courses[subj] = info
            if assigned_teachers:
                final_teacher_names[subj] = assigned_teachers

    # 覆盖供后续使用的变量
    COURSE_REQUIREMENTS = final_courses
    TEACHER_NAMES = final_teacher_names
    
    # 标准化课程配置格式供预检逻辑使用
    normalized_courses = COURSE_REQUIREMENTS 
    
    # -------------------------------------------------------------------------
    # [架构升级结束] 接回原有流程
    # -------------------------------------------------------------------------

    CLASSES = list(range(1, NUM_CLASSES + 1))
    DAYS = 5
    PERIODS = 9 
    SLOTS = [(d, p) for d in range(DAYS) for p in range(PERIODS)]

    # 1. 生成数据 (传入处理后的 COURSE_REQUIREMENTS 和 TEACHER_NAMES)
    TEACHERS_DB, CLASS_TEACHER_MAP = generate_teachers_and_map(NUM_CLASSES, COURSE_REQUIREMENTS, TEACHER_NAMES)
    logger.info(f"Generated {len(TEACHERS_DB)} teachers after sharding.")

    # ================= [新增] 限制条件预检逻辑 (Pre-check) =================
    # 原因：如果分配给老师的课时已经超过了Max限制，求解器会直接无解。
    # 我们需要在建模前拦截这种情况，并给出明确提示。
    
    teacher_limits = config.get("teacher_limits", {})
    if teacher_limits:
        # 1. 计算每位老师被分配的实际总课时
        # 建立 tid -> assigned_count
        actual_workload = collections.defaultdict(int)
        
        # 遍历所有班级和科目的映射关系
        # CLASS_TEACHER_MAP: {(class_id, subject): tid}
        for (class_id, subject), tid in CLASS_TEACHER_MAP.items():
            # 获取该科目的周课时数
            course_cfg = normalized_courses.get(subject, {})
            count = course_cfg.get("count", 0)
            actual_workload[tid] += count
            
        # 2. 对比限制条件
        # 建立 name -> tid 的映射 (注意去除空格，增强容错)
        name_to_tid = {t['name'].strip(): t['id'] for t in TEACHERS_DB}
        
        for limit_name, limit_cfg in teacher_limits.items():
            clean_name = limit_name.strip() # 清理输入的姓名空格
            
            # ================= [修改开始] 严格校验姓名 =================
            if clean_name not in name_to_tid:
                # 之前是 continue (忽略)，现在改为直接报错返回
                available_teachers = list(name_to_tid.keys())
                # 只显示前5个老师名字作为提示
                hint_teachers = ", ".join(available_teachers[:5]) + ("..." if len(available_teachers) > 5 else "")
                
                return {
                    "status": "error", # 让前端识别为错误
                    "error_type": "invalid_name",
                    "message": f"【配置错误】在“教师特殊限制”中输入的姓名“{clean_name}”不存在！",
                    "suggestions": [
                        f"1. 请检查有没有错别字或多余空格。",
                        f"2. 请确认“{clean_name}”是否已经出现在上方的【科目设置-固定老师】名单中。",
                        f"3. 当前识别到的老师有：{hint_teachers}"
                    ]
                }
            # ================= [修改结束] =================
                
            tid = name_to_tid[clean_name]
            current_load = actual_workload.get(tid, 0)
            max_limit = limit_cfg.get("max")
            
            # 检查最大课时 (保持不变，但确保类型转换安全)
            if max_limit is not None and str(max_limit).strip() != "":
                max_val = int(max_limit)
                if current_load > max_val:
                    return {
                        "status": "fail", # 排课失败状态
                        "error_type": "constraint_conflict",
                        "message": f"【排课冲突】教师【{clean_name}】被分配了 {current_load} 节课，但您设置的最大限制为 {max_val} 节。",
                        "suggestions": [
                            f"1. 请在「科目设置」中，为提示的【{clean_name}】老师任教的科目增加其他老师名字（用逗号分隔），系统会自动分摊课时。",
                            f"2. 调高【{clean_name}】的最大课时限制。",
                            f"3. 减少该科目的每周节数。"
                        ]
                    }
    # ====================================================================

    # 2. 建模
    model = cp_model.CpModel()
    schedule = {}
    
    for c in CLASSES:
        for d in range(DAYS):
            for p in range(PERIODS):
                for subj in COURSE_REQUIREMENTS.keys():
                    schedule[(c, d, p, subj)] = model.NewBoolVar(f'c{c}_{d}_{p}_{subj}')

    # === [新增] 特定老师的课时约束 ===
    # [修改版] 更健壮的名字匹配
    teacher_limits = config.get("teacher_limits", {})
    name_to_tid = {t['name'].strip(): t['id'] for t in TEACHERS_DB} # 这里的 Key 去除空格
    
    teacher_assignments = collections.defaultdict(list)
    for (c, s), t_id in CLASS_TEACHER_MAP.items():
        teacher_assignments[t_id].append((c, s))

    for t_name, limits in teacher_limits.items():
        clean_name = t_name.strip() # 输入的名字也去除空格
        
        if clean_name not in name_to_tid:
            continue
            
        tid = name_to_tid[clean_name]
        assignments = teacher_assignments.get(tid, [])
        if not assignments: continue
        
        # 计算该老师的总排课量 (Expression)
        total_workload = sum(schedule[(c, d, p, s)] 
                             for (c, s) in assignments 
                             for d, p in SLOTS)
        
        # 添加最小课时约束
        if "min" in limits and str(limits["min"]).strip().isdigit():
            model.Add(total_workload >= int(limits["min"]))
            
        # 添加最大课时约束
        if "max" in limits and str(limits["max"]).strip().isdigit():
            model.Add(total_workload <= int(limits["max"]))
    # =================================

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
    fixed_courses = CONSTRAINTS.get('fixed_courses', {})

    # [新增] 约束：固定课程 (Fixed Courses / Pre-scheduling)
    # 格式: fixed_courses = { "1": { "0_0": "语文" } }
    if fixed_courses:
        logger.info(f"Fixed Course Constraints: {len(fixed_courses)} classes")
        for c_str, fixes in fixed_courses.items():
            try:
                c = int(c_str)
            except:
                continue
            if c not in CLASSES: continue
            
            for slot_key, subj_name in fixes.items():
                if subj_name not in COURSE_REQUIREMENTS: continue
                try:
                    d_str, p_str = slot_key.split('_')
                    d, p = int(d_str), int(p_str)
                    if 0 <= d < DAYS and 0 <= p < PERIODS:
                        model.Add(schedule[(c, d, p, subj_name)] == 1)
                except Exception as e:
                     pass

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
    # [新增] 读取禁止连排配置
    avoid_consecutive_subjects = optimization_config.get('avoid_consecutive_subjects', False)

    max_consecutive = int(optimization_config.get('max_consecutive', 2))
    
    # [新增] 插入这段逻辑：禁止科目连排
    if avoid_consecutive_subjects:
        logger.info("启用约束: 禁止科目连排 (Avoid Consecutive Subjects)")
        for c in CLASSES:
            for d in range(DAYS):
                for subj in COURSE_REQUIREMENTS:
                    # 遍历每天的节次，检查相邻两节 (p, p+1)
                    for p in range(PERIODS - 1):
                        # 逻辑：如果 第p节是subj AND 第p+1节也是subj => 惩罚
                        
                        # 定义一个布尔变量表示 "是否连堂"
                        is_consecutive = model.NewBoolVar(f'cons_subj_{c}_{d}_{p}_{subj}')
                        
                        # 只有当两节课都排了该科目，is_consecutive 才为 True
                        model.AddBoolAnd([
                            schedule[(c, d, p, subj)], 
                            schedule[(c, d, p+1, subj)]
                        ]).OnlyEnforceIf(is_consecutive)
                        
                        # 只要有一节没排，is_consecutive 就为 False (这一步其实在Minimize中非必须，但为了严谨加上)
                        model.AddBoolOr([
                            schedule[(c, d, p, subj)].Not(), 
                            schedule[(c, d, p+1, subj)].Not()
                        ]).OnlyEnforceIf(is_consecutive.Not())
                        
                        # 增加惩罚权重 (权重设大一点，比如 500分，保证尽量不发生)
                        penalties.append(is_consecutive * 500)

    # [优化目标 1] 黄金时间安排 (语数英优先排在上午前4节)
    # 权重: 每一节下午的主科课惩罚 15 分 (提高权重)
    if enable_golden_time:
        main_subjects_list = [subj for subj, config in normalized_courses.items() if config.get("type") == "main"]
        for c in CLASSES:
            for d in range(DAYS):
                for p in range(4, PERIODS): # 下午时段 (第5节及以后)
                    for subj in main_subjects_list:
                        # 如果在该时段排了主科，则惩罚
                        penalties.append(schedule[(c, d, p, subj)] * 15)
    
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
    solver.parameters.num_search_workers = 8 # 启用多线程求解
    solver.parameters.randomize_search = True # [新增] 启用随机搜索，每次生成不同结果 
    solver.parameters.num_search_workers = 8 # 启用多线程求解 
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

        # [新增] 调用评估函数
        evaluation = evaluate_quality(
            schedule, solver, CLASSES, DAYS, PERIODS, 
            COURSE_REQUIREMENTS, CLASS_TEACHER_MAP, TEACHERS_DB
        )

        return {
            "status": "success",
            "sharding_info": sharding_report, # [新增] 向前端传递替换详情
            "stats": stats,
            "evaluation": evaluation,
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