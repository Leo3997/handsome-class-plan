from ortools.sat.python import cp_model
import pandas as pd
import sys
import collections
import statistics
import logging
import math

logger = logging.getLogger(__name__)

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

def generate_teachers_and_map(num_classes, courses, custom_names=None, class_metadata=None):
    """
    根据配置生成老师数据和班级映射
    courses: 字典 { '语文': {'count': 5, 'type': 'main'}, ... } 或旧格式 { '语文': 5, ... }
    custom_names: 字典 { '语文': ['张伟', '李娜'], '数学': ['王老师'] }
    class_metadata: 字典 { class_id: { "requirements": {...} } } 用于处理班级差异化需求
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
    normalized_all_courses = {}
    
    # 如果有 class_metadata，取所有班级需求的并集
    if class_metadata:
        for c_id, info in class_metadata.items():
            for subj, cfg in info.get("requirements", {}).items():
                if subj not in normalized_all_courses:
                    if isinstance(cfg, dict):
                        normalized_all_courses[subj] = cfg
                    else:
                        course_type = "main" if cfg >= 5 else "minor"
                        normalized_all_courses[subj] = {"count": cfg, "type": course_type}
    else:
        # 回退到全局 courses
        for subj, config in courses.items():
            if isinstance(config, dict):
                normalized_all_courses[subj] = config
            else:
                course_type = "main" if config >= 5 else "minor"
                normalized_all_courses[subj] = {"count": config, "type": course_type}

    # 2. 准备每科的候选老师队列
    subject_teacher_queues = {}
    
    for subj, config in normalized_all_courses.items():
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
    classes_to_assign = class_metadata.keys() if class_metadata else range(1, num_classes + 1)
    
    for class_id in classes_to_assign:
        # 获取该班级需要的科目
        needed_subjects = class_metadata[class_id]["requirements"].keys() if class_metadata else normalized_all_courses.keys()
        
        for subj in needed_subjects:
            if subj not in subject_teacher_queues: continue
            
            queue_data = subject_teacher_queues[subj]
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

    # 辅助函数：获取老师的最大限制
    def get_teacher_max_limit(t_name):
        clean_name = t_name.strip()
        # nonlocal teacher_limits # nonlocal 不适用于函数内部定义的同名变量
        for k, v in teacher_limits.items():
            if k.strip() == clean_name and v.get('max') is not None and str(v['max']).strip() != "":
                return int(v['max'])
        return 999 # 没有限制则默认无穷大

    logger.info(f"Received config courses type: {type(original_courses)}")

    # -------------------------------------------------------------------------
    # [架构升级] 智能分片层 Pro (Smart Sharding Layer - Full Scan)
    # 逻辑：扫描所有任课老师，只要有一人有限制，就触发全局拆分，并对齐老师名单。
    # -------------------------------------------------------------------------
    
    # -------------------------------------------------------------------------
    # [架构升级] 引入年级与班级元数据 (Grade & Class Metadata)
    # -------------------------------------------------------------------------
    class_metadata = {}
    global_courses = set()
    grades_config = config.get('grades', {})
    
    if grades_config:
        all_class_ids = []
        global_class_index = 1
        for grade_name, info in grades_config.items():
            start_num = info.get('start_class_id', 1)
            count = info.get('count', 0)
            grade_courses = info.get('courses', {})
            
            # 标准化该年级的课程
            normalized_grade_courses = {}
            for s, c in grade_courses.items():
                if isinstance(c, dict):
                    normalized_grade_courses[s] = c
                else:
                    course_type = "main" if int(c) >= 5 else "minor"
                    normalized_grade_courses[s] = {"count": int(c), "type": course_type}
                global_courses.add(s)
            
            for i in range(count):
                real_id = global_class_index
                global_class_index += 1
                all_class_ids.append(real_id)
                class_metadata[real_id] = {
                    "grade": grade_name,
                    "name": f"{grade_name}({start_num + i})班",
                    "requirements": normalized_grade_courses,
                    "constraints": info.get('constraints', {})
                }
        CLASSES = all_class_ids
        num_classes_actual = len(CLASSES)
    else:
        # 回退到原有扁平结构
        CLASSES = list(range(1, NUM_CLASSES + 1))
        num_classes_actual = NUM_CLASSES
        # 兼容旧 courses 格式
        curr_courses = original_courses if isinstance(original_courses, dict) else {item['name']: item for item in original_courses if item.get('name')}
        normalized_base_courses = {}
        for s, c in curr_courses.items():
            if isinstance(c, dict):
                normalized_base_courses[s] = c
            else:
                course_type = "main" if int(c) >= 5 else "minor"
                normalized_base_courses[s] = {"count": int(c), "type": course_type}
            global_courses.add(s)
            
        for c in CLASSES:
            class_metadata[c] = {
                "grade": "Default",
                "name": f"{c}班",
                "requirements": normalized_base_courses,
                "constraints": {}
            }

    # 2. 自动拆分与名单重构 (智能分片层升级)
    # 此处逻辑需要适配 class_metadata 中的 requirements
    final_teacher_names = {}
    sharding_report = []
    
    # 收集全局科目信息 (取 class_metadata 中 requirements 的并集)
    global_course_requirements = {}
    for c_id in class_metadata:
        for s_name, s_cfg in class_metadata[c_id]["requirements"].items():
            if s_name not in global_course_requirements:
                global_course_requirements[s_name] = s_cfg

    for subj, assigned_teachers in teacher_names_config.items():
        # 获取该科目在所有班级中的总班级数和总课时
        total_assigned_classes = 0
        max_single_class_count = 0
        for c_id in class_metadata:
            if subj in class_metadata[c_id]["requirements"]:
                total_assigned_classes += 1
                max_single_class_count = max(max_single_class_count, class_metadata[c_id]["requirements"][subj]["count"])
        
        if total_assigned_classes == 0:
            continue

        # 确定每个老师理想的班级数上限
        # 语数英科由于 Rule 2 (上午4节)，上限设为 4 班 (原本5班在教研禁排下会无解)
        # 社会由于 Rule 2 (下午3节)，上限设为 4 班
        # 其他副课 (体育/音美信心)，上限设为 12 班 (留出弹性空间)
        class_limit_per_teacher = 15
        if subj in ["语文", "数学", "英语", "科学", "社会"]:
            class_limit_per_teacher = 4
        elif subj == "体育":
            class_limit_per_teacher = 10 # 场地有限
        
        # 计算当前名单是否足够支撑总班级数
        num_names = len(assigned_teachers) if assigned_teachers else 1
        avg_classes = total_assigned_classes / num_names
        
        # 触发分片的条件：1. 单班超限；2. 总班级数超限
        needs_sharding = False
        
        # 1. 检查是否存在单名老师限制过低
        if assigned_teachers:
            for t_name in assigned_teachers:
                limit = get_teacher_max_limit(t_name)
                if limit < max_single_class_count:
                    needs_sharding = True
                    break
        
        # 2. 检查总班级数压力 (均摊后是否超过老师负荷)
        if avg_classes > class_limit_per_teacher:
            needs_sharding = True
            
        if needs_sharding:
            logger.info(f"Subject {subj} triggers Smart Sharding Pro. (Total Classes: {total_assigned_classes}, Limit: {class_limit_per_teacher})")
            
            # [升级逻辑] 动态扩充老师名单
            expanded_names = []
            if not assigned_teachers:
                assigned_teachers = [f"{subj}老师"]
            
            for t_base in assigned_teachers:
                # 每个人的历史负荷我们假定是均衡的，这里我们直接根据比例拆分
                # 一个 base 拆成多少个？
                num_splits = math.ceil(avg_classes / class_limit_per_teacher)
                if num_splits <= 1:
                    expanded_names.append(t_base)
                else:
                    for i in range(num_splits):
                        suffix = chr(ord('A') + i)
                        expanded_names.append(f"{t_base}{suffix}")
            
            final_teacher_names[subj] = expanded_names
            
            # 如果是因为单班超限 (limit < count)，还需要处理 AUTO_SUB (保持原有逻辑)
            # 这里简化处理：如果是超大班额老师，直接在 mapping 阶段轮询。
        else:
            if assigned_teachers:
                final_teacher_names[subj] = assigned_teachers
            else:
                # 即使没配老师，也至少保证有一个
                final_teacher_names[subj] = [f"{subj}老师"]


    TEACHER_NAMES = final_teacher_names
    DAYS = 5
    PERIODS = 8  # 每天8节 (上午4节 + 下午4节)
    SLOTS = [(d, p) for d in range(DAYS) for p in range(PERIODS)]

    # [诊断日志] 输出关键参数
    total_slots = DAYS * PERIODS  # 每班每周可用时段
    logger.info(f"===== 排课诊断信息 =====")
    logger.info(f"班级数: {len(CLASSES)}, 科目数: {len(global_courses)}")
    logger.info(f"每周可用时段: {total_slots} (5天 x {PERIODS}节)")
    
    # 计算总课时需求
    sample_class_id = CLASSES[0] if CLASSES else None
    if sample_class_id and sample_class_id in class_metadata:
        sample_reqs = class_metadata[sample_class_id]["requirements"]
        total_hours = sum(r.get("count", 0) for r in sample_reqs.values())
        logger.info(f"样本班级 ({sample_class_id}) 课时需求: {total_hours} 节")
        if total_hours > total_slots:
            logger.warning(f"[警告] 课时需求 ({total_hours}) 超过可用时段 ({total_slots})，求解必然失败！")
    logger.info(f"=========================")

    # 1. 生成数据
    TEACHERS_DB, CLASS_TEACHER_MAP = generate_teachers_and_map(num_classes_actual, None, TEACHER_NAMES, class_metadata)
    
    # 获取并集后的所有科目 (包含自动拆分的)
    ALL_SUBJECTS_IN_VARS = list(TEACHER_NAMES.keys())
    # 确保原始科目也在里面
    for s in global_courses:
        if s not in ALL_SUBJECTS_IN_VARS: ALL_SUBJECTS_IN_VARS.append(s)

    logger.info(f"Generated {len(TEACHERS_DB)} teachers after sharding. Total subjects in model: {len(ALL_SUBJECTS_IN_VARS)}")

    # [诊断日志] 分析老师资源分配
    teacher_assignments_preview = collections.defaultdict(list)
    for (c, s), t_id in CLASS_TEACHER_MAP.items():
        teacher_assignments_preview[t_id].append((c, s))
    
    # 找出最繁忙的老师
    max_load_teacher = None
    max_load = 0
    for tid, assignments in teacher_assignments_preview.items():
        total_weekly = 0
        for (c, subj) in assignments:
            if c in class_metadata and subj in class_metadata[c]["requirements"]:
                total_weekly += class_metadata[c]["requirements"][subj].get("count", 0)
        if total_weekly > max_load:
            max_load = total_weekly
            max_load_teacher = tid
    
    if max_load_teacher:
        t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == max_load_teacher), "Unknown")
        num_classes_assigned = len(teacher_assignments_preview[max_load_teacher])
        logger.info(f"最繁忙老师: {t_name}, 周课时: {max_load}, 分配班级数: {num_classes_assigned}")
        if max_load > DAYS * PERIODS:
            logger.warning(f"[警告] 老师 {t_name} 周课时 ({max_load}) 超过可用时段 ({DAYS * PERIODS})，求解必然失败！")

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
    penalties = [] # [移动到此处] 确保全局可用
    
    for c in CLASSES:
        for d in range(DAYS):
            for p in range(PERIODS):
                for subj in ALL_SUBJECTS_IN_VARS:
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
    
    # 1. 唯一性: 每个格子 <= 1 门课
    for c in CLASSES:
        for d, p in SLOTS:
            model.Add(sum(schedule[(c, d, p, s)] for s in ALL_SUBJECTS_IN_VARS) <= 1)
    
    # 2. 差异化课时总量控制
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        # 处理原始科目和自动拆分科目
        for subj in ALL_SUBJECTS_IN_VARS:
            # 如果是自动拆分科目 (SUB)
            if "_AUTO_SUB" in subj:
                base_subj = subj.replace("_AUTO_SUB", "")
                if base_subj in c_reqs:
                    # 检查该老师在该科目的最大限制
                    t_id = CLASS_TEACHER_MAP.get((c, base_subj))
                    t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == t_id), "")
                    limit = get_teacher_max_limit(t_name)
                    total_needed = c_reqs[base_subj]["count"]
                    
                    if total_needed > limit:
                        # 分身课课时 = 总需 - 限制
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == (total_needed - limit))
                    else:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0)
                else:
                    model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0)
            else:
                # 原始科目 (本体)
                if subj in c_reqs:
                    t_id = CLASS_TEACHER_MAP.get((c, subj))
                    t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == t_id), "")
                    limit = get_teacher_max_limit(t_name)
                    total_needed = c_reqs[subj]["count"]
                    # 本体课时 = min(总需, 限制)
                    model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == min(total_needed, limit))
                else:
                    # 如果该班根本不上这门课，且它不是 SUB 课，则为 0
                    if "_AUTO_SUB" not in subj:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0)

    # 3. 老师冲突约束 (核心约束：同一老师同一时刻只能在一个班级上课)
    for tid, assignments in teacher_assignments.items():
        # assignments: list of (class_id, subject)
        if len(assignments) <= 1:
            continue  # 只教一个班级的老师不需要冲突约束
            
        for d in range(DAYS):
            for p in range(PERIODS):
                # 该老师在这个时段的所有可能排课变量
                teacher_slot_vars = [schedule[(c, d, p, s)] for (c, s) in assignments]
                # 约束：同一时刻最多只能上一节课
                model.Add(sum(teacher_slot_vars) <= 1)
            
            # --- [绍兴一中补全] 4.4.3 老师四五节不连堂 (硬约束) ---
            # 规则：上午最后一节 (p=3) 和下午第一节 (p=4) 不连堂
            model.Add(sum(schedule[(c, d, 3, s)] for (c, s) in assignments) + 
                      sum(schedule[(c, d, 4, s)] for (c, s) in assignments) <= 1)

    # ====================================================================
    # 4. 绍兴一中专用规则 (Shaoxing No.1 Middle School Rules)
    # ====================================================================
    
    for c in CLASSES:
        grade = class_metadata[c]['grade']
        c_reqs = class_metadata[c]["requirements"]
        
        # 定义时段
        am_slots = [(d, p) for d in range(DAYS) for p in range(4)]      # 上午 0-3节
        pm_slots = [(d, p) for d in range(DAYS) for p in range(4, PERIODS)]  # 下午 4-7节
        first_6_periods = [(d, p) for d in range(DAYS) for p in range(6)]    # 1-6节 (p=0-5)
        last_2_periods = [(d, p) for d in range(DAYS) for p in range(6, PERIODS)]  # 7-8节 (p=6-7)
        
        # --- 4.1 AM/PM 课时分布约束 (绍兴一中规则) ---
        
        # 语数英: 上午4节，下午1节
        for subj in ["语文", "数学", "英语"]:
            if subj in c_reqs:
                subj_vars_am = [schedule[(c, d, p, subj)] for d, p in am_slots]
                subj_vars_pm = [schedule[(c, d, p, subj)] for d, p in pm_slots]
                model.Add(sum(subj_vars_am) == 4)
                model.Add(sum(subj_vars_pm) == 1)
        
        # 科学: 初一初二 上午3+下午2，初三 上午4+下午1
        if "科学" in c_reqs:
            subj_vars_am = [schedule[(c, d, p, "科学")] for d, p in am_slots]
            subj_vars_pm = [schedule[(c, d, p, "科学")] for d, p in pm_slots]
            if grade == "初三":
                model.Add(sum(subj_vars_am) == 4)
                model.Add(sum(subj_vars_pm) == 1)
            else:  # 初一、初二
                model.Add(sum(subj_vars_am) == 3)
                model.Add(sum(subj_vars_pm) == 2)
        
        # 社会: 上午2节，下午3节
        if "社会" in c_reqs:
            subj_vars_am = [schedule[(c, d, p, "社会")] for d, p in am_slots]
            subj_vars_pm = [schedule[(c, d, p, "社会")] for d, p in pm_slots]
            model.Add(sum(subj_vars_am) == 2)
            model.Add(sum(subj_vars_pm) == 3)
        
        # --- 4.2 主课节次限制 (语数英科只排1-6节，不排7-8节) ---
        for subj in ["语文", "数学", "英语", "科学"]:
            if subj in c_reqs:
                for d, p in last_2_periods:
                    model.Add(schedule[(c, d, p, subj)] == 0)
        
        # 初三社会只排1-6节
        if grade == "初三" and "社会" in c_reqs:
            for d, p in last_2_periods:
                model.Add(schedule[(c, d, p, "社会")] == 0)
        
        # --- 4.3 体育不排上午第一节 (p=0) ---
        if "体育" in c_reqs:
            for d in range(DAYS):
                model.Add(schedule[(c, d, 0, "体育")] == 0)
        
        # --- 4.4 年级特殊禁排 ---
        # 初三周一下午第三节不排课 (d=0, p=6)
        if grade == "初三":
            for subj in c_reqs:
                model.Add(schedule[(c, 0, 6, subj)] == 0)

        # --- [绍兴一中补全] 4.4.1 固定活动课禁排 (硬约束) ---
        # 规则来源：优化.md 1.6-1.7
        forbidden_slots = []
        # 全校周五下午第四节 (d=4, p=7)
        forbidden_slots.append((4, 7))
        
        if grade == "初一":
            forbidden_slots += [(3, 7), (4, 6)] # 周四p8, 周五p7
        elif grade == "初二":
            forbidden_slots += [(0, 7), (2, 7), (1, 6)] # 周一p8, 周三p8, 周二p7
        elif grade == "初三":
            forbidden_slots += [(1, 7), (3, 6), (4, 6)] # 周二p8, 周四p7, 周五p7
            
        for d, p in forbidden_slots:
            for subj in c_reqs:
                model.Add(schedule[(c, d, p, subj)] == 0)

        # --- [绍兴一中补全] 4.4.2 活动课当天禁排体育 (硬约束) ---
        # 规则：有课外活动课的年段当天不排体育课
        pe_forbidden_days = []
        if grade == "初一":
            pe_forbidden_days = [3] # 周四
        elif grade == "初二":
            pe_forbidden_days = [0, 2] # 周一, 周三
        elif grade == "初三":
            pe_forbidden_days = [1] # 周二 (注: 周四下午第三节是课外活动, 但周二下午第四节也是)
            
        for d in pe_forbidden_days:
            if "体育" in c_reqs:
                for p in range(PERIODS):
                    model.Add(schedule[(c, d, p, "体育")] == 0)

    # --- 4.5 教研活动禁排 (硬约束) ---
    # 语社英：周三(d=2)下午(p=4~7)不排
    wed_pm_slots = [(2, p) for p in range(4, PERIODS)]
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in ["语文", "社会", "英语"]:
            if subj in c_reqs:
                for d, p in wed_pm_slots:
                    model.Add(schedule[(c, d, p, subj)] == 0)
    
    # 数学科学：周四(d=3)下午(p=4~7)不排
    thu_pm_slots = [(3, p) for p in range(4, PERIODS)]
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in ["数学", "科学"]:
            if subj in c_reqs:
                for d, p in thu_pm_slots:
                    model.Add(schedule[(c, d, p, subj)] == 0)

    # --- 4.6 体育场地约束 (同一节次最多8个班上体育) ---
    if "体育" in global_course_requirements:
        for d in range(DAYS):
            for p in range(PERIODS):
                model.Add(sum(schedule[(c, d, p, "体育")] for c in CLASSES) <= 8)

    # TODO: 确认问题后可恢复此约束，但可能需要调整 limit 值
    '''
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in c_reqs:
            limit = 2 
            # 如果某科一天要上很多节（罕见），需调高
            for d in range(DAYS):
                # 本体 + 可能的分身
                daily_vars = [schedule[(c, d, p, subj)] for p in range(PERIODS)]
                sub_name = f"{subj}_AUTO_SUB"
                if sub_name in ALL_SUBJECTS_IN_VARS:
                    daily_vars += [schedule[(c, d, p, sub_name)] for p in range(PERIODS)]
                model.Add(sum(daily_vars) <= limit)
    '''
    
    # 6. 副课每日数量限制 (暂时禁用以测试)
    '''
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        minor_subjects = [s for s, cfg in c_reqs.items() if cfg.get("type") == "minor"]
        if minor_subjects:
            for d in range(DAYS):
                daily_minor_vars = []
                for s in minor_subjects:
                    daily_minor_vars.append(sum(schedule[(c, d, p, s)] for p in range(PERIODS)))
                    sub_name = f"{s}_AUTO_SUB"
                    if sub_name in ALL_SUBJECTS_IN_VARS:
                        daily_minor_vars.append(sum(schedule[(c, d, p, sub_name)] for p in range(PERIODS)))
                model.Add(sum(daily_minor_vars) <= 4)
    '''

    # 5. 高级约束 (New)
    CONSTRAINTS = config.get('constraints', {})
    
    # 构建名字到ID的映射 (name -> List[tid])
    name_to_tids = collections.defaultdict(list)
    for t in TEACHERS_DB:
        name_to_tids[t['name']].append(t['id'])
    
    # --- 5.1 行政领导周五下午不排课 ---
    # 领导名单：陈安、谢飞、叶青峰、王伟锋、许敏、曹峻燕、寿海峰、余慧菁、刘建灿、王清、傅佳情、陈彦羽、沈黎松、鲍伟佳
    admin_leaders = ["陈安", "谢飞", "叶青峰", "王伟锋", "许敏", "曹峻燕", "寿海峰", 
                     "余慧菁", "刘建灿", "王清", "傅佳情", "陈彦羽", "沈黎松", "鲍伟佳"]
    fri_pm_slots = [(4, p) for p in range(4, PERIODS)]  # 周五(d=4)下午
    
    for leader_name in admin_leaders:
        tids = name_to_tids.get(leader_name, [])
        for tid in tids:
            assignments = teacher_assignments.get(tid, [])
            if assignments:
                for d, p in fri_pm_slots:
                    model.Add(sum(schedule[(c, d, p, s)] for (c, s) in assignments) == 0)
    
    # --- 5.2 拓展课软约束 ---
    # 初一周五下午第三节 (d=4, p=6) 尽量不排音体美信息
    for c in CLASSES:
        grade = class_metadata[c]['grade']
        c_reqs = class_metadata[c]["requirements"]
        
        if grade == "初一":
            for subj in ["音乐", "体育", "美术", "信息"]:
                if subj in c_reqs:
                    penalties.append(schedule[(c, 4, 6, subj)] * 100)
        
        # 初二周二下午第三节 (d=1, p=6) 尽量不排音体美信息
        if grade == "初二":
            for subj in ["音乐", "体育", "美术", "信息"]:
                if subj in c_reqs:
                    penalties.append(schedule[(c, 1, 6, subj)] * 100)
        

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
                if subj_name not in global_course_requirements: continue
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

    # 6. 教室资源约束 (Classroom Constraints) - 暂时禁用以测试
    # config.resources 格式: [{'name': '音乐教室', 'capacity': 1, 'subjects': ['音乐']}]
    '''
    resources = config.get('resources', [])
    for res in resources:
        capacity = int(res.get('capacity', 1))
        # 支持中文逗号分隔或列表
        targets = res.get('subjects', [])
        if isinstance(targets, str):
            targets = [s.strip() for s in targets.replace('，', ',').split(',') if s.strip()]
            
        # 找出当前资源涉及的所有 subject
        res_subjects = [s for s in targets if s in global_course_requirements]
        
        if res_subjects:
            # 对每个时段，统计所有班级上这些课的总数 <= capacity
            for d in range(DAYS):
                for p in range(PERIODS):
                    model.Add(sum(schedule[(c, d, p, s)] 
                                for c in CLASSES 
                                for s in res_subjects) <= capacity)
    '''

    # === 7. 软约束优化 (Core Enhancement) ===
    # 采用最小化惩罚值的方式来寻找最优解 (penalties 列表已在建模初期定义)
    
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
                for subj in global_course_requirements:
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
        for c in CLASSES:
            grade = class_metadata[c]['grade']
            weight_factor = 1
            if grade == "初三":
                weight_factor = 100
            elif grade == "初二":
                weight_factor = 10
            
            c_reqs = class_metadata[c]["requirements"]
            main_subjects_list = [s for s, cfg in c_reqs.items() if cfg.get("type") == "main"]
            
            for d in range(DAYS):
                for p in range(4, PERIODS):
                    for subj in main_subjects_list:
                        # 本体
                        penalties.append(schedule[(c, d, p, subj)] * 15 * weight_factor)
                        # 如果有分身且也是主课类型
                        sub_name = f"{subj}_AUTO_SUB"
                        if sub_name in ALL_SUBJECTS_IN_VARS:
                            penalties.append(schedule[(c, d, p, sub_name)] * 15 * weight_factor)

    # ====================================================================
    # [绍兴一中软约束] - Shaoxing No.1 Middle School Soft Constraints
    # ====================================================================
    
    # [软约束 A] 鼓励语数英科连堂（上午或下午连续排课给予奖励）
    # 规则：语数英一般都连堂，要么上午要么下午，初三科学也是如此
    for c in CLASSES:
        grade = class_metadata[c]['grade']
        c_reqs = class_metadata[c]["requirements"]
        
        # 确定需要连堂的科目
        conn_subjects = ["语文", "数学", "英语"]
        if grade == "初三":
            conn_subjects.append("科学")
        
        for subj in conn_subjects:
            if subj not in c_reqs:
                continue
            for d in range(DAYS):
                # 上午连堂：1-2节 或 3-4节
                for start_p in [0, 2]:  # p=0,1 或 p=2,3
                    is_conn = model.NewBoolVar(f'conn_{c}_{d}_{start_p}_{subj}')
                    model.AddBoolAnd([
                        schedule[(c, d, start_p, subj)],
                        schedule[(c, d, start_p + 1, subj)]
                    ]).OnlyEnforceIf(is_conn)
                    model.AddBoolOr([
                        schedule[(c, d, start_p, subj)].Not(),
                        schedule[(c, d, start_p + 1, subj)].Not()
                    ]).OnlyEnforceIf(is_conn.Not())
                    # 奖励连堂（负惩罚 = 奖励）
                    penalties.append(is_conn * -50)
    
    # [软约束 B] 副课尽量排下午（含第7节）
    # 规则：音体美信息心理尽可能排下午
    minor_for_pm = ["音乐", "美术", "信息", "心理"]
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in minor_for_pm:
            if subj not in c_reqs:
                continue
            for d in range(DAYS):
                for p in range(4):  # 上午 p=0~3
                    # 排在上午给予惩罚
                    penalties.append(schedule[(c, d, p, subj)] * 30)
    
    # [软约束 C] 教研软禁排 (规则 8 尽量部分)
    # 音乐周三下午尽量不排 (d=2, p=4~7)
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        if "音乐" in c_reqs:
            for p in range(4, PERIODS):
                penalties.append(schedule[(c, 2, p, "音乐")] * 30)
    
    # 美术周四下午尽量不排 (d=3, p=4~7)
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        if "美术" in c_reqs:
            for p in range(4, PERIODS):
                penalties.append(schedule[(c, 3, p, "美术")] * 30)
    
    # 体育周四上午尽量不排 (d=3, p=0~3)
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        if "体育" in c_reqs:
            for p in range(4):
                penalties.append(schedule[(c, 3, p, "体育")] * 30)
    
    # 信息周四上午尽量不排 (d=3, p=0~3)
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        if "信息" in c_reqs:
            for p in range(4):
                penalties.append(schedule[(c, 3, p, "信息")] * 30)

    # [软约束 D] 语数英科上午时段分布均衡 (规则 7)
    # 规则：上午的课尽量两次一二节 (p=0,1)，两次三四节 (p=2,3)
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in ["语文", "数学", "英语", "科学"]:
            if subj in c_reqs:
                # 统计一周内该科目在 1-2 节和 3-4 节出现的次数
                count_p12 = sum(schedule[(c, d, p, subj)] for d in range(DAYS) for p in [0, 1])
                count_p34 = sum(schedule[(c, d, p, subj)] for d in range(DAYS) for p in [2, 3])
                
                # 理想情况是各 2 次。我们惩罚偏离 2 的情况
                # 使用辅助变量表示绝对值偏离
                diff12 = model.NewIntVar(-5, 5, f'diff12_{c}_{subj}')
                model.Add(diff12 == count_p12 - 2)
                abs_diff12 = model.NewIntVar(0, 5, f'abs_diff12_{c}_{subj}')
                model.AddAbsEquality(abs_diff12, diff12)
                penalties.append(abs_diff12 * 40)
                
                diff34 = model.NewIntVar(-5, 5, f'diff34_{c}_{subj}')
                model.Add(diff34 == count_p34 - 2)
                abs_diff34 = model.NewIntVar(0, 5, f'abs_diff34_{c}_{subj}')
                model.AddAbsEquality(abs_diff34, diff34)
                penalties.append(abs_diff34 * 40)

    # [软约束 E] 体育老师连堂优化 (规则 4)
    # 规则：同一个体育老师尽可能连堂，最多不超过三节连堂
    pe_teachers = [t for t in TEACHERS_DB if "体育" in t.get('subjects', [])]
    for pt in pe_teachers:
        tid = pt['id']
        assignments = teacher_assignments.get(tid, [])
        if not assignments: continue
        
        for d in range(DAYS):
            # 1. 鼓励连堂 (p, p+1)
            for p in range(PERIODS - 1):
                is_conn = model.NewBoolVar(f'pe_conn_{tid}_{d}_{p}')
                # 该老师在 p 和 p+1 都有课
                t_vars_p = [schedule[(c, d, p, s)] for (c, s) in assignments]
                t_vars_p1 = [schedule[(c, d, p+1, s)] for (c, s) in assignments]
                
                v_p = sum(t_vars_p)
                v_p1 = sum(t_vars_p1)
                
                model.Add(v_p + v_p1 >= 2).OnlyEnforceIf(is_conn)
                model.Add(v_p + v_p1 < 2).OnlyEnforceIf(is_conn.Not())
                # 奖励体育老师连堂
                penalties.append(is_conn * -20)
            
            # 2. 强制限制连堂不超过3节 (硬约束)
            for p in range(PERIODS - 3):
                # 连续4节变量之和 <= 3
                window_vars = []
                for wp in range(p, p + 4):
                    window_vars.extend([schedule[(c, d, wp, s)] for (c, s) in assignments])
                model.Add(sum(window_vars) <= 3)

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
                for subj in global_course_requirements:
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
                    
                    is_consecutive = model.NewBoolVar(f'fatigue_{tid}_d{d}_w{i}')
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
    # 增加求解时间以应对 60 班级的复杂优化目标和大规模变量
    solver.parameters.max_time_in_seconds = 60.0 
    solver.parameters.num_search_workers = 12 # 启用更多多线程求解
    solver.parameters.randomize_search = True 
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
                    for subj in global_course_requirements:
                        if solver.Value(schedule[(c, d, p, subj)]) == 1:
                            tid = CLASS_TEACHER_MAP.get((c, subj))
                            if tid is not None and tid in t_id_to_name:
                                t_name = t_id_to_name[tid]
                                stats[t_name]["total"] += 1
                                stats[t_name]["daily"][d] += 1

        # [新增] 调用评估函数
        evaluation = evaluate_quality(
            schedule, solver, CLASSES, DAYS, PERIODS, 
            global_course_requirements, CLASS_TEACHER_MAP, TEACHERS_DB
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
            "courses": global_course_requirements,
            "vars_list": ALL_SUBJECTS_IN_VARS,
            "class_names": {c: class_metadata[c]['name'] for c in CLASSES}, # [新增] 返回包含年级前缀的完整班级名
            "resources": config.get('resources', [])  # 使用配置中的resources
        }
    else:
        return {"status": "fail"}