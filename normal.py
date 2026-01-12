from ortools.sat.python import cp_model
import pandas as pd
import sys
import collections
import statistics
import logging
import math
import json
import os

class StopAfterFirstSolution(cp_model.CpSolverSolutionCallback):
    """在找到第一个可行解时停止搜索的回调类。"""
    def __init__(self):
        cp_model.CpSolverSolutionCallback.__init__(self)

    def on_solution_callback(self):
        self.StopSearch()

logger = logging.getLogger(__name__)

# 绍兴一中默认规则配置 (用于迁移硬编码)
SHAOXING_PRESET_RULES = [
    {
        "name": "语数英上午4下午1",
        "type": "ZONE_COUNT",
        "targets": { "subjects": ["语文", "数学", "英语"] },
        "params": {
            "slots": [[d,p] for d in range(5) for p in range(4)],
            "count": 4, "relation": "=="
        },
        "weight": 100
    },
    {
        "name": "社会上午2下午3",
        "type": "ZONE_COUNT",
        "targets": { "subjects": ["社会"] },
        "params": {
            "slots": [[d,p] for d in range(5) for p in range(4)],
            "count": 2, "relation": "=="
        },
        "weight": 100
    },
    {
        "name": "初一初二科学下午2",
        "type": "ZONE_COUNT",
        "targets": { "subjects": ["科学"], "grades": ["初一", "初二"] },
        "params": {
            "slots": [[d,p] for d in range(5) for p in range(4, 8)],
            "count": 2, "relation": "=="
        },
        "weight": 100
    },
    {
        "name": "初三科学下午1",
        "type": "ZONE_COUNT",
        "targets": { "subjects": ["科学"], "grades": ["初三"] },
        "params": {
            "slots": [[d,p] for d in range(5) for p in range(4, 8)],
            "count": 1, "relation": "=="
        },
        "weight": 100
    },
    {
        "name": "老师四五节不连堂",
        "type": "DAILY_LIMIT",
        "targets": { "tags": ["所有老师"] },
        "params": { "slots_per_day": [3, 4], "limit": 1 },
        "weight": 100
    },
    {
        "name": "语数英科只排1-6节",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["语文", "数学", "英语", "科学"] },
        "params": { "slots": [[d,p] for d in range(5) for p in range(6, 8)] },
        "weight": 100
    },
    {
        "name": "初三社会只排1-6节",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["社会"], "grades": ["初三"] },
        "params": { "slots": [[d,p] for d in range(5) for p in range(6, 8)] },
        "weight": 100
    },
    {
        "name": "体育不排第一节",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["体育"] },
        "params": { "slots": [[d, 0] for d in range(5)] },
        "weight": 100
    },
    {
        "name": "语社英周三教研禁排",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["语文", "社会", "英语"] },
        "params": { "slots": [[2, p] for p in range(4, 8)] },
        "weight": 100
    },
    {
        "name": "数科周四教研禁排",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["数学", "科学"] },
        "params": { "slots": [[3, p] for p in range(4, 8)] },
        "weight": 100
    },
    {
        "name": "体育场地容量限制",
        "type": "GLOBAL_CAPACITY",
        "targets": { "subjects": ["体育"] },
        "params": { "capacity": 15 },  # 60班规模，原来8
        "weight": 100
    },
    {
        "name": "全校周五下午第四节禁排",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "grades": ["初一", "初二", "初三"] },
        "params": { "slots": [[4, 7]] },
        "weight": 100
    },
    {
        "name": "初一特定禁排",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "grades": ["初一"] },
        "params": { "slots": [[3, 7], [4, 6]] },
        "weight": 100
    },
    {
        "name": "初二特定禁排",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "grades": ["初二"] },
        "params": { "slots": [[0, 7], [2, 7], [1, 6]] },
        "weight": 100
    },
    {
        "name": "初三特定禁排",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "grades": ["初三"] },
        "params": { "slots": [[1, 7], [3, 6], [4, 6], [0, 6]] },
        "weight": 100
    },
    {
        "name": "初一体育避开周四",
        "type": "SPECIAL_DAYS",
        "targets": { "subjects": ["体育"], "grades": ["初一"] },
        "params": { "days": [3] },
        "weight": 100
    },
    {
        "name": "初二体育避开一三",
        "type": "SPECIAL_DAYS",
        "targets": { "subjects": ["体育"], "grades": ["初二"] },
        "params": { "days": [0, 2] },
        "weight": 100
    },
    {
        "name": "初三体育避开周二",
        "type": "SPECIAL_DAYS",
        "targets": { "subjects": ["体育"], "grades": ["初三"] },
        "params": { "days": [1] },
        "weight": 100
    },
    {
        "name": "行政领导周五下午不排课",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "names": ["陈安", "谢飞", "叶青峰", "王伟锋", "许敏", "曹峻燕", "寿海峰", "余慧菁", "刘建灿", "王清", "傅佳情", "陈彦羽", "沈黎松", "鲍伟佳"] },
        "params": { "slots": [[4, 4], [4, 5], [4, 6], [4, 7]] },
        "weight": 100
    },
    {
        "name": "黄金时间 (主科上午优先)",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["语文", "数学", "英语", "科学"] },
        "params": { "slots": [[d, p] for d in range(5) for p in range(4, 8)] },
        "weight": 15
    },
    {
        "name": "副课尽量排下午",
        "type": "FORBIDDEN_SLOTS",
        "targets": { "subjects": ["音乐", "美术", "信息", "心理", "课外活动", "拓展课", "政教活动"] },
        "params": { "slots": [[d, p] for d in range(5) for p in range(4)] },
        "weight": 30
    },
    {
        "name": "老师连堂疲劳限制",
        "type": "CONSECUTIVE",
        "targets": { "tags": ["所有老师"] },
        "params": { "mode": "avoid", "max": 2 },
        "weight": 100
    },
    {
        "name": "体育老师连堂奖励",
        "type": "CONSECUTIVE",
        "targets": { "subjects": ["体育"] },
        "params": { "mode": "avoid", "max": 0 },
        "weight": -20
    }
]

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

def generate_teachers_and_map(num_classes, courses, custom_names=None, class_metadata=None, teacher_limits=None, grade_teacher_names=None, high_concurrency_subjects=None):
    """
    根据配置生成老师数据和班级映射
    grade_teacher_names: 字典 { '初一': { '语文': [...] } } 用于年级隔离
    high_concurrency_subjects: 集合，标记需要一对一分配的高并发科目
    """
    teachers_db = []
    class_teacher_map = {}

    def parse_tags(tag_str):
        if not tag_str: return []
        return [t.strip() for t in str(tag_str).replace('，', ',').split(',') if t.strip()]
    
    if custom_names is None: custom_names = {}
    if grade_teacher_names is None: grade_teacher_names = {}
    if high_concurrency_subjects is None: high_concurrency_subjects = set()

    # 1. 建立全局老师注册表 (Name -> ID)
    # 对于主课，ID 必须包含年级信息以隔离。副课则全局共享。
    name_to_id_map = {}
    
    def get_or_create_teacher_id(name, subject, type_, grade_name="Default", subject_tags=None):
        # 核心逻辑：主课老师 ID 包含年级，副课老师 ID 仅包含姓名
        id_key = f"{name}_{grade_name}" if type_ == "main" else name
        
        if id_key not in name_to_id_map:
            tid = f"t_{id_key}"
            name_to_id_map[id_key] = tid
            
            t_tags = []
            if teacher_limits and name in teacher_limits:
                t_tags = parse_tags(teacher_limits[name].get('tags', ''))

            teachers_db.append({
                "id": tid, 
                "name": name, 
                "subject": subject, 
                "type": type_,
                "grade": grade_name if type_ == "main" else "All",
                "tags": t_tags,
                "subject_tags": subject_tags or []
            })
        return name_to_id_map[id_key]  # [关键修复] 必须返回 tid！
    # 2. 按年级处理每个班级的老师分配
    # 建立年级-科目队列，确保持续滚动分配
    grade_subject_queues = {} # {(grade, subject): {"names": [names], "ptr": 0}}

    # 获取班级 ID 列表并按年级排序
    class_ids = sorted(class_metadata.keys()) if class_metadata else range(1, num_classes + 1)
    
    for c_id in class_ids:
        c_info = class_metadata.get(c_id, {"grade": "Default", "requirements": {}})
        grade = c_info.get("grade", "Default")
        requirements = c_info.get("requirements", {})
        
        for subj, cfg in requirements.items():
            count = cfg.get("count", 0) if isinstance(cfg, dict) else cfg
            if count == 0: continue
            
            type_ = cfg.get("type", "minor") if isinstance(cfg, dict) else ("main" if count >= 5 else "minor")
            
            # 获取候选老师名单
            # [核心修复] 高并发科目使用全局队列（不分年级），确保所有班级分配不同老师
            if subj in high_concurrency_subjects:
                queue_key = ("__GLOBAL__", subj)  # 全局队列
            else:
                queue_key = (grade, subj)  # 按年级隔离的队列
                
            if queue_key not in grade_subject_queues:
                # 优先级 1: grade_teacher_names (年级私有) - 仅对非高并发科目有效
                # 优先级 2: custom_names (全校汇总)
                if subj not in high_concurrency_subjects:
                    names = grade_teacher_names.get(grade, {}).get(subj, [])
                else:
                    names = []  # 高并发科目直接使用全局名单
                if not names:
                    names = custom_names.get(subj, [])
                if not names:
                    # 默认老师名格式: 年级+科目+序号
                    names = [f"{grade}{subj}{i+1}" for i in range(30)]
                grade_subject_queues[queue_key] = {"names": list(names), "ptr": 0}
            
            q_info = grade_subject_queues[queue_key]
            names = q_info["names"]
            ptr = q_info["ptr"]
            
            # 轮询获取老师（高并发科目因为使用全局队列，自然实现了一对一分配）
            t_name = names[ptr]
            q_info["ptr"] = (ptr + 1) % len(names)
            
            tid = get_or_create_teacher_id(t_name, subj, type_, grade)
            class_teacher_map[(c_id, subj)] = tid

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


def get_filtered_targets(teachers_db, class_metadata, targets):
    """
    根据组合条件筛选目标
    targets: { tags: [], subjects: [], grades: [] }
    返回: { teacher_ids: [], class_subjects: [(c_id, subj), ...] }
    """
    selected_tids = []
    selected_class_subjects = []
    
    # 1. 筛选老师
    target_tags = set(targets.get('tags', []))
    target_subjs = set(targets.get('subjects', []))
    target_grades = set(targets.get('grades', []))
    
    # 如果没有任何筛选条件，返回空
    if not target_tags and not target_subjs and not target_grades:
        return {"teacher_ids": [], "class_subjects": []}

    # 教师筛选逻辑 (老师必须满足标签或科目标签)
    for t in teachers_db:
        match = False
        if target_tags:
            # 老师自身的标签
            if any(tag in t.get('tags', []) for tag in target_tags):
                match = True
        
        if not match and target_subjs:
            # 老师所教的科目 (兼容 _AUTO_SUB 后缀)
            t_subj = t.get('subject', '')
            clean_subj = t_subj.replace('_AUTO_SUB', '')
            if t_subj in target_subjs or clean_subj in target_subjs:
                match = True

        # [新增] 名字直接匹配 (用于特指某些老师，如领导)
        target_names = targets.get('names', [])
        if not match and target_names:
            if t.get('name') in target_names:
                match = True
        
        if match:
            selected_tids.append(t['id'])

    # 班级-科目 筛选逻辑
    for c_id, meta in class_metadata.items():
        grade_match = not target_grades or meta.get('grade') in target_grades
        if not grade_match: continue
        
        for subj in meta.get('requirements', {}).keys():
            clean_subj = subj.replace('_AUTO_SUB', '')
            subj_match = not target_subjs or (subj in target_subjs or clean_subj in target_subjs)
            if subj_match:
                selected_class_subjects.append((c_id, subj))
                
    return {
        "teacher_ids": list(set(selected_tids)),
        "class_subjects": selected_class_subjects
    }

def apply_universal_rules(model, schedule, rules, teachers_db, class_metadata, TID_TO_ASSIGNMENTS, ALL_SUBJECTS_IN_VARS, SLOTS, penalties, assumption_literals, rule_mapping):
    """
    规则工厂：分发解析并应用通用规则
    """
    if not rules: return
    
    for idx, rule in enumerate(rules):
        r_type = rule.get('type')
        targets = rule.get('targets', {})
        params = rule.get('params', {})
        weight = rule.get('weight', 100) 
        rule_name = rule.get('name', f'Rule_{idx}')
        
        # [核心] 为每条硬规则创建一个开关
        switch_var = None
        if weight >= 100:
            switch_var = model.NewBoolVar(f'switch_rule_{idx}_{r_type}')
            assumption_literals.append(switch_var)
            rule_mapping[switch_var.Index()] = f"【用户规则】{rule_name}" 
        
        filtered = get_filtered_targets(teachers_db, class_metadata, targets)
        tids = filtered['teacher_ids']
        class_subjects = filtered['class_subjects']
        
        if r_type == 'FORBIDDEN_SLOTS':
            # 性能优化：按时段收集所有受限变量
            slots = params.get('slots', [])
            for d, p in slots:
                vars_to_block = []
                # 老师禁排
                for tid in tids:
                    if tid in TID_TO_ASSIGNMENTS:
                        vars_to_block.extend([schedule[(c, d, p, s)] for (c, s) in TID_TO_ASSIGNMENTS[tid] if (c, d, p, s) in schedule])
                # 班级-科目禁排
                for c_id, subj in class_subjects:
                    if (c_id, d, p, subj) in schedule:
                        vars_to_block.append(schedule[(c_id, d, p, subj)])
                
                if vars_to_block:
                    if weight >= 100:
                        model.Add(sum(vars_to_block) == 0).OnlyEnforceIf(switch_var)
                    else:
                        # 软约束：如果是负数，则为奖励(尽量排)，正数为惩罚(尽量不排)
                        for v in vars_to_block:
                            penalties.append(v * weight)

        elif r_type == 'ZONE_COUNT':
            zone_slots = params.get('slots', [])
            count = params.get('count', 0)
            rel = params.get('relation', '==')
            
            for c_id, subj in class_subjects:
                relevant_vars = [schedule[(c_id, d, p, subj)] for d, p in zone_slots if (c_id, d, p, subj) in schedule]
                if relevant_vars:
                    if weight >= 100:
                        if rel == '==': model.Add(sum(relevant_vars) == count).OnlyEnforceIf(switch_var)
                        elif rel == '<=': model.Add(sum(relevant_vars) <= count).OnlyEnforceIf(switch_var)
                        elif rel == '>=': model.Add(sum(relevant_vars) >= count).OnlyEnforceIf(switch_var)
                    else:
                        # 软约束：惩罚偏离度
                        diff = model.NewIntVar(-10, 10, f'zone_diff_{c_id}_{subj}_{rule.get("name","")}')
                        model.Add(diff == sum(relevant_vars) - count)
                        abs_diff = model.NewIntVar(0, 10, f'zone_abs_diff_{c_id}_{subj}')
                        model.AddAbsEquality(abs_diff, diff)
                        penalties.append(abs_diff * abs(weight))

        elif r_type == 'DAILY_LIMIT':
            slots_in_day = params.get('slots_per_day', [])
            limit = params.get('limit', 1)
            is_all_teachers = (targets.get('tags') == ['所有老师'])
            
            # 对老师生效
            target_tids = tids or (TID_TO_ASSIGNMENTS.keys() if is_all_teachers else [])
            for tid in target_tids:
                if tid in TID_TO_ASSIGNMENTS:
                    assignments = TID_TO_ASSIGNMENTS[tid]
                    for d in range(5):
                        daily_vars = [schedule[(c, d, p, s)] for (c, s) in assignments for p in slots_in_day if (c, d, p, s) in schedule]
                        if daily_vars:
                            if weight >= 100:
                                model.Add(sum(daily_vars) <= limit).OnlyEnforceIf(switch_var)
                            else:
                                model.Add(sum(daily_vars) <= limit)
                            
            # 对班级生效 (如有需要)
            for c_id, subj in class_subjects:
                for d in range(5):
                    daily_vars = [schedule[(c_id, d, p, subj)] for p in slots_in_day if (c_id, d, p, subj) in schedule]
                    if daily_vars:
                        if weight >= 100:
                            model.Add(sum(daily_vars) <= limit).OnlyEnforceIf(switch_var)
                        else:
                            model.Add(sum(daily_vars) <= limit)

        elif r_type == 'SPECIAL_DAYS':
            days = params.get('days', [])
            for d in days:
                for p in range(8):
                    vars_to_block = []
                    for tid in tids:
                        if tid in TID_TO_ASSIGNMENTS:
                            vars_to_block.extend([schedule[(c, d, p, s)] for (c, s) in TID_TO_ASSIGNMENTS[tid] if (c, d, p, s) in schedule])
                    for c_id, subj in class_subjects:
                        if (c_id, d, p, subj) in schedule:
                            vars_to_block.append(schedule[(c_id, d, p, subj)])
                    
                    if vars_to_block:
                        if weight >= 100:
                            model.Add(sum(vars_to_block) == 0).OnlyEnforceIf(switch_var)
                        else:
                            model.Add(sum(vars_to_block) == 0)

        elif r_type == 'CONSECUTIVE':
            mode = params.get('mode', 'avoid') 
            limit = params.get('max', 1)
            
            if mode == 'avoid':
                # 对班级-科目生效
                for c_id, subj in class_subjects:
                    for d in range(5):
                        for p in range(8 - limit):
                            window_vars = [schedule[(c_id, d, p+i, subj)] for i in range(limit + 1) if (c_id, d, p+i, subj) in schedule]
                            if len(window_vars) > limit:
                                if weight >= 100:
                                    model.Add(sum(window_vars) <= limit).OnlyEnforceIf(switch_var)
                                else:
                                    is_cons = model.NewBoolVar(f'cons_{c_id}_{d}_{p}_{subj}')
                                    model.Add(sum(window_vars) >= limit + 1).OnlyEnforceIf(is_cons)
                                    model.Add(sum(window_vars) <= limit).OnlyEnforceIf(is_cons.Not())
                                    penalties.append(is_cons * weight)
                
                # 对老师生效
                target_tids = tids or (TID_TO_ASSIGNMENTS.keys() if targets.get('tags') == ['所有老师'] else [])
                for tid in target_tids:
                    if tid in TID_TO_ASSIGNMENTS:
                        assignments = TID_TO_ASSIGNMENTS[tid]
                        for d in range(5):
                            for p in range(8 - limit):
                                window_vars = []
                                for i in range(limit + 1):
                                    window_vars.extend([schedule[(c, d, p+i, s)] for (c, s) in assignments if (c, d, p+i, s) in schedule])
                                if window_vars:
                                    if weight >= 100:
                                        model.Add(sum(window_vars) <= limit).OnlyEnforceIf(switch_var)
                                    else:
                                        is_cons = model.NewBoolVar(f'cons_tid_{tid}_{d}_{p}')
                                        model.Add(sum(window_vars) >= limit + 1).OnlyEnforceIf(is_cons)
                                        model.Add(sum(window_vars) <= limit).OnlyEnforceIf(is_cons.Not())
                                        penalties.append(is_cons * weight)
            elif mode == 'force' and weight >= 100:
                pass

        elif r_type == 'FIXED_SLOTS':
            slots = params.get('slots', [])
            for c_id, subj in class_subjects:
                # [修复] 收集该班级该科目在固定时段的所有变量
                fixed_slot_vars = []
                non_fixed_slot_vars = []
                for d, p in SLOTS:
                    if (c_id, d, p, subj) in schedule:
                        if [d, p] in slots or (d, p) in slots:
                            fixed_slot_vars.append(schedule[(c_id, d, p, subj)])
                        else:
                            non_fixed_slot_vars.append(schedule[(c_id, d, p, subj)])
                
                if fixed_slot_vars:
                    if weight >= 100:
                        # 非固定时段用高惩罚软约束
                        if non_fixed_slot_vars:
                            for v in non_fixed_slot_vars:
                                penalties.append(v * 1000)
                        
                        # [核心修复] 获取该班级该科目的周课时数
                        subj_count = 0
                        if c_id in class_metadata and subj in class_metadata[c_id].get('requirements', {}):
                            req = class_metadata[c_id]['requirements'][subj]
                            subj_count = req.get('count', 0) if isinstance(req, dict) else req
                        
                        num_fixed_slots = len(slots)
                        
                        # 当固定时段数 == 课时数时，强制每个时段都排1节
                        if num_fixed_slots > 0 and subj_count == num_fixed_slots:
                            for fv in fixed_slot_vars:
                                if weight >= 100:
                                    model.Add(fv == 1).OnlyEnforceIf(switch_var)
                                else:
                                    model.Add(fv == 1)
                        else:
                            # 否则只要求在固定时段内至少排一节
                            if weight >= 100:
                                model.Add(sum(fixed_slot_vars) >= 1).OnlyEnforceIf(switch_var)
                            else:
                                model.Add(sum(fixed_slot_vars) >= 1)
                    else:
                        # 软约束：奖励排在固定时段
                        for v in fixed_slot_vars:
                            penalties.append(v * -weight)

        elif r_type == 'GLOBAL_CAPACITY':
            capacity = params.get('capacity', 1)
            subjects = targets.get('subjects', [])
            for d in range(5):
                for p in range(8):
                    slot_vars = [schedule[(c, d, p, s)] for c in class_metadata for s in subjects if (c, d, p, s) in schedule]
                    if slot_vars:
                        if weight >= 100:
                            model.Add(sum(slot_vars) <= capacity).OnlyEnforceIf(switch_var)
                        else:
                            # 溢出惩罚
                            excess = model.NewIntVar(0, len(class_metadata), f'excess_{d}_{p}_{idx}')
                            model.Add(excess >= sum(slot_vars) - capacity)
                            penalties.append(excess * weight)



def verify_rules(schedule_map, rules, class_metadata, teachers_db, class_teacher_map, days, periods):
    """
    独立验算模块：不依赖求解器逻辑，直接检查结果字典
    schedule_map: {(class_id, day, period): {"subject": "xxx", "teacher_name": "xxx", ...}}
    """
    report = []
    
    # 辅助：构建更易查询的数据结构
    # 1. 按班级查询: class_schedule[c][d][p] = subj
    class_schedule = collections.defaultdict(lambda: {})
    # 2. 按老师查询: teacher_schedule[tid][(d,p)] = class_id
    teacher_schedule = collections.defaultdict(list)
    
    # 填充辅助结构
    for (c, d, p), info in schedule_map.items():
        subj = info['subject']
        # 去除自动分片的后缀，还原由原始科目名，以便规则匹配
        clean_subj = subj.replace('_AUTO_SUB', '')
        # 如果是分身(例如 语文A)，也应该被视为 语文
        if clean_subj[-1:].isalpha() and clean_subj[:-1] in class_metadata.get(c, {}).get('requirements', {}):
             clean_subj = clean_subj[:-1]
             
        class_schedule[c][(d, p)] = clean_subj
        
        tid = class_teacher_map.get((c, subj)) # 注意这里用原始 subj 查 tid
        if tid:
            teacher_schedule[tid].append((d, p))

    # 开始逐条验证规则
    for rule in rules:
        rule_name = rule.get('name', '未命名规则')
        r_type = rule.get('type')
        targets = rule.get('targets', {})
        params = rule.get('params', {})
        weight = rule.get('weight', 0)
        
        # 筛选目标 (复用之前的 get_filtered_targets，但需要只拿 ID/Name)
        filtered = get_filtered_targets(teachers_db, class_metadata, targets)
        target_tids = filtered['teacher_ids']
        target_class_subjs = filtered['class_subjects'] # [(c_id, subj), ...]

        violation_details = []
        is_hard = weight >= 100
        
        # --- 1. 时段禁排 / 固定时段 验证 ---
        if r_type == 'FORBIDDEN_SLOTS' or r_type == 'FIXED_SLOTS':
            check_slots = params.get('slots', [])
            
            # 检查班级-科目
            for c_id, subj in target_class_subjs:
                clean_target_subj = subj.replace('_AUTO_SUB', '')
                
                # 找出该班级该科目所有的排课时间
                actual_slots = []
                for (d, p), s_name in class_schedule[c_id].items():
                    # 模糊匹配：课表里的名字包含规则目标名字 (例如 "语文A" 包含 "语文")
                    if s_name == clean_target_subj or clean_target_subj in s_name:
                        actual_slots.append([d, p])
                
                if r_type == 'FORBIDDEN_SLOTS':
                    # 禁排：actual_slots 里不能有 check_slots
                    for d, p in check_slots:
                        if [d, p] in actual_slots or (d, p) in actual_slots:
                            violation_details.append(f"班级{c_id} {subj} 违规排在 周{d+1}第{p+1}节")
                            
                elif r_type == 'FIXED_SLOTS':
                     # 固定：check_slots 必须都在 actual_slots 里
                     for d, p in check_slots:
                        if [d, p] not in actual_slots and (d, p) not in actual_slots:
                             violation_details.append(f"班级{c_id} {subj} 未排在固定位置 周{d+1}第{p+1}节")

            # 检查老师 (仅禁排)
            if r_type == 'FORBIDDEN_SLOTS':
                for tid in target_tids:
                    t_name = next((t['name'] for t in teachers_db if t['id'] == tid), tid)
                    t_slots = teacher_schedule.get(tid, [])
                    for d, p in check_slots:
                        if (d, p) in t_slots or [d, p] in t_slots:
                             violation_details.append(f"老师 {t_name} 违规排在 周{d+1}第{p+1}节")

        # --- 2. 区域课时 (ZONE_COUNT) 验证 ---
        elif r_type == 'ZONE_COUNT':
            zone_slots = params.get('slots', [])
            expected = params.get('count', 0)
            
            for c_id, subj in target_class_subjs:
                clean_target_subj = subj.replace('_AUTO_SUB', '')
                actual_count = 0
                for d, p in zone_slots:
                    s_name = class_schedule[c_id].get((d, p))
                    if s_name and (s_name == clean_target_subj or clean_target_subj in s_name):
                        actual_count += 1
                
                if actual_count != expected:
                     violation_details.append(f"班级{c_id} {subj} 区域内实排 {actual_count} 节 (要求 {expected} 节)")

        # --- 3. 连堂限制 (CONSECUTIVE) ---
        elif r_type == 'CONSECUTIVE':
            limit = params.get('max', 2)
            # 检查老师
            for tid in target_tids:
                t_name = next((t['name'] for t in teachers_db if t['id'] == tid), tid)
                t_slots = sorted(teacher_schedule.get(tid, []))
                # 按天分组
                daily = collections.defaultdict(list)
                for d, p in t_slots: daily[d].append(p)
                
                for d, periods in daily.items():
                    periods.sort()
                    cons = 1
                    for i in range(len(periods)-1):
                        if periods[i+1] == periods[i] + 1:
                            cons += 1
                        else:
                            if cons > limit:
                                violation_details.append(f"老师 {t_name} 周{d+1} 连续上课 {cons} 节 (上限 {limit})")
                            cons = 1
                    if cons > limit:
                         violation_details.append(f"老师 {t_name} 周{d+1} 连续上课 {cons} 节 (上限 {limit})")

        # --- 4. 汇总结果 ---
        status = "success"
        if violation_details:
            status = "failed" if is_hard else "warning" # 硬约束失败为failed，软约束为warning
            
        report.append({
            "name": rule_name,
            "type": r_type,
            "weight": weight,
            "is_hard": is_hard,
            "status": status,
            "violations": violation_details,
            "violation_count": len(violation_details)
        })
        
    return report

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
    high_concurrency_subjects = set()  # [新增] 记录需要一对一分配的高并发科目
    
    # 收集全局科目信息 (取 class_metadata 中 requirements 的并集)
    global_course_requirements = {}
    for c_id in class_metadata:
        for s_name, s_cfg in class_metadata[c_id]["requirements"].items():
            if s_name not in global_course_requirements:
                global_course_requirements[s_name] = s_cfg

    # [核心重构] 实现全量学科自动补齐：遍历所有出现在课位中的科目
    all_subjects_in_system = set(global_course_requirements.keys()) | set(teacher_names_config.keys())
    
    for subj in all_subjects_in_system:
        assigned_teachers = teacher_names_config.get(subj, [])
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
        # 语数英科由于 Rule 1 (上午4节)，上限设为 2 班 (确保上午仅排 8 节，留出 12 个空位避开教研/领导假)
        # 社会由于 Rule 3 (上午2节)，上限设为 2 班
        # 其他副课 (体育/音美信心)，上限设为 10 班 (符合一周 15 节左右的工作量)
        class_limit_per_teacher = 15
        if subj in ["语文", "数学", "英语", "科学", "社会"]:
            class_limit_per_teacher = 2
        elif subj == "体育":
            class_limit_per_teacher = 6 # 降低体育老师上限，确保 20 人均分 60 班
        elif subj in ["音乐", "美术", "信息", "心理"]:
            class_limit_per_teacher = 10 
        
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
        
        # [并发感知] 检查规则引发的全校聚合峰值需求
        slot_concurrency_demands = collections.defaultdict(int)
        all_rules = config.get('rules', [])
        if subj == "政教活动":
             logger.info(f"Checking Sharding for {subj}: Total Rules in Config: {len(all_rules)}")
        
        for rule in all_rules:
            if rule.get('type') == 'FIXED_SLOTS':
                r_targets = rule.get('targets', {})
                if subj in r_targets.get('subjects', []):
                    f_slots = rule.get('params', {}).get('slots', [])
                    if f_slots:
                        # 统计受此规则影响的班级总数
                        r_grades = r_targets.get('grades', [])
                        affected_classes = [c_id for c_id, meta in class_metadata.items() if (not r_grades or meta.get('grade') in r_grades) and subj in meta.get('requirements')]
                        
                        if subj == "政教活动":
                             logger.info(f"  -> Found FIXED_SLOTS rule for {subj}. Slots: {f_slots}, Affected Classes: {len(affected_classes)}")
                        
                        # [核心修复] 检查课时数是否等于固定时段数
                        # 如果相等，说明每个班在每个固定时段都要排1节课
                        if affected_classes:
                            sample_req = class_metadata.get(affected_classes[0], {}).get('requirements', {})
                            subj_weekly_count = sample_req.get(subj, {}).get('count', 1) if isinstance(sample_req.get(subj), dict) else 1
                            
                            if len(f_slots) == subj_weekly_count:
                                # 每个班在每个固定时段都排1节，并发需求等于班级数
                                for s in f_slots:
                                    slot_concurrency_demands[tuple(s)] += len(affected_classes)
                            else:
                                # 原有逻辑：班级平摊到多个时段
                                for s in f_slots:
                                    slot_concurrency_demands[tuple(s)] += math.ceil(len(affected_classes) / len(f_slots))
        
        # [新增] 扫描「手动预排」(Constraints) 产生的并发需求
        fixed_constraints = config.get('constraints', {}).get('fixed_courses', {})
        for cid_str, slots_data in fixed_constraints.items():
            # slots_data 格式: {"0_4": "语文", "4_7": "政教活动"}
            for slot_key, fixed_subj in slots_data.items():
                if fixed_subj == subj:
                    try:
                        d, p = map(int, slot_key.split('_'))
                        slot_concurrency_demands[(d, p)] += 1
                        if subj == "政教活动" and d == 4 and p == 7:
                             logger.debug(f"  -> Manual placement for {subj} detected in Class {cid_str} at slot {slot_key}")
                    except:
                        continue

        concurrency_demand = max(slot_concurrency_demands.values()) if slot_concurrency_demands else 1
        if concurrency_demand > 1:
            logger.info(f"Subject {subj} Peak Concurrency Demand: {concurrency_demand}")

        # 3. 综合判断分片系数
        base_count = len(assigned_teachers) if assigned_teachers else 1
        # 分片系数取 (总负荷需求) 和 (峰值并发需求) 的最大值
        split_factor_by_load = math.ceil(avg_classes / class_limit_per_teacher)
        split_factor_by_concurrency = math.ceil(concurrency_demand / base_count)
        num_splits = max(split_factor_by_load, split_factor_by_concurrency)

        if num_splits > 1:
            needs_sharding = True
        
        # [性能优化] 活动类科目不需要真实老师资源，使用虚拟老师池
        # 这些科目一个老师可以同时带多个班级，不产生老师冲突
        ACTIVITY_SUBJECTS = {'政教活动', '课外活动', '拓展课'}
        is_activity_subject = subj in ACTIVITY_SUBJECTS
        
        # [核心修复] 如果并发需求超过了可用老师数，标记为需要一对一分配
        # 条件：concurrency > base_count（活动类科目除外）
        is_high_concurrency = concurrency_demand > base_count and concurrency_demand > 1 and not is_activity_subject
            
        if needs_sharding:
            logger.info(f"Subject {subj} triggers Smart Sharding Pro. (Total: {total_assigned_classes}, Load Factor: {split_factor_by_load}, Concurrency Factor: {split_factor_by_concurrency})")
            
            # [性能优化] 活动类科目使用虚拟老师池，不需要真实分片
            if is_activity_subject:
                # [核心修复] 虚拟老师名额必须覆盖全校班级并发需求
                # 之前固定为 10，导致 60 班量级在固定活动课时会出现 INFEASIBLE
                total_classes = len(class_metadata)
                final_teacher_names[subj] = [f"v_{subj}{i+1}" for i in range(total_classes + 10)]
                logger.info(f"  -> [Activity] {subj} uses virtual teacher pool (size: {total_classes + 10})")
                continue  # 跳过后续的高并发分片逻辑
            
            # [升级逻辑] 动态扩充老师名单
            expanded_names = []
            if not assigned_teachers:
                # 默认老师名格式: 科目+序号 (全校共用)
                # [核心调整] 体育老师默认生成 20 人以降低负载
                default_count = 20 if subj == "体育" else 10
                assigned_teachers = [f"{subj}{i+1}" for i in range(default_count)]
            
            # [核心修复] 对于高并发科目，确保分片数 >= 班级总数
            if is_high_concurrency:
                # 确保生成的老师身份数 >= max(峰值并发, 班级总数)
                # 这样每个班级都能分配到独立老师
                required_identities = max(concurrency_demand, total_assigned_classes)
                # 计算需要多少轮分片才能产生足够的身份
                num_splits = math.ceil(required_identities / len(assigned_teachers))
                high_concurrency_subjects.add(subj)
                logger.info(f"  -> [High Concurrency] {subj} marked for 1:1 allocation. Required identities: {required_identities}")
            
            for t_base in assigned_teachers:
                for i in range(num_splits):
                    suffix = chr(ord('A') + i)
                    expanded_names.append(f"{t_base}{suffix}")
            
            final_teacher_names[subj] = expanded_names
            
            # [诊断]
            logger.info(f"  -> Generated {len(expanded_names)} sharded identities for {subj}")
        else:
            if assigned_teachers:
                final_teacher_names[subj] = assigned_teachers
            else:
                final_teacher_names[subj] = [f"{subj}老师"]
            logger.info(f"  -> {subj} uses original pool: {len(final_teacher_names[subj])} teachers")

    logger.info("Subject Sharding Report Complete.")
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

    grade_teacher_names = config.get('grade_teacher_names', {})
    # 1. 生成数据
    TEACHERS_DB, CLASS_TEACHER_MAP = generate_teachers_and_map(num_classes_actual, None, TEACHER_NAMES, class_metadata, teacher_limits, grade_teacher_names, high_concurrency_subjects)
    
    # [诊断] 检查高并发科目的分配是否实现了一对一
    if high_concurrency_subjects:
        for subj in high_concurrency_subjects:
            assigned_tids = set()
            for (c_id, s), tid in CLASS_TEACHER_MAP.items():
                if s == subj:
                    if tid in assigned_tids:
                        logger.warning(f"[一对一分配失败] {subj}: 老师 {tid} 被重复分配！")
                    assigned_tids.add(tid)
            logger.info(f"[高并发诊断] {subj}: {len(assigned_tids)} 个独立老师被分配")
    
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
            # 获取该科目的周课时数 (从 class_metadata 中获取)
            c_reqs = class_metadata.get(class_id, {}).get("requirements", {})
            course_cfg = c_reqs.get(subject, {})
            count = course_cfg.get("count", 0) if isinstance(course_cfg, dict) else int(course_cfg)
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
    # 2. 建模
    model = cp_model.CpModel()
    schedule = {}
    penalties = []
    
    # [核心新增] 全局冲突诊断映射表
    assumption_literals = []
    rule_mapping = {}
    schedule = {}
    penalties = [] # [移动到此处] 确保全局可用
    
    # [核心新增] 全局冲突诊断映射表
    assumption_literals = []
    rule_mapping = {}

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
    
    # 2. 差异化课时总量控制 (硬约束，不需要诊断开关)
    # [性能优化] 移除了为每个(班级,科目)创建诊断开关的逻辑
    # 系统基础约束本身不会冲突，直接使用硬约束提升求解速度
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in ALL_SUBJECTS_IN_VARS:

            if "_AUTO_SUB" in subj:
                base_subj = subj.replace("_AUTO_SUB", "")
                if base_subj in c_reqs:
                    t_id = CLASS_TEACHER_MAP.get((c, base_subj))
                    t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == t_id), "")
                    limit = 999 
                    for k, v in config.get("teacher_limits", {}).items():
                         if k.strip() == t_name.strip() and v.get('max'): limit = int(v['max'])
                    
                    total_needed = c_reqs[base_subj]["count"]
                    if total_needed > limit:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == (total_needed - limit))
                    else:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0)
                else:
                    model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0)
            else:
                if subj in c_reqs:
                    t_id = CLASS_TEACHER_MAP.get((c, subj))
                    t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == t_id), "")
                    limit = 999
                    for k, v in config.get("teacher_limits", {}).items():
                         if k.strip() == t_name.strip() and v.get('max'): limit = int(v['max'])
                    
                    total_needed = c_reqs[subj]["count"]
                    model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == min(total_needed, limit))
                else:
                    if "_AUTO_SUB" not in subj:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0)


    # 3. 老师冲突约束 (核心约束：同一老师同一时刻只能在一个班级上课)
    # [性能优化] 活动类科目使用虚拟老师，跳过冲突约束
    ACTIVITY_SUBJECTS = {'政教活动', '课外活动', '拓展课'}
    
    for tid, assignments in teacher_assignments.items():
        # assignments: list of (class_id, subject)
        if len(assignments) <= 1:
            continue  # 只教一个班级的老师不需要冲突约束
        
        # [性能优化] 检查这个老师是否只教活动类科目
        taught_subjects = set(s for (c, s) in assignments)
        if taught_subjects.issubset(ACTIVITY_SUBJECTS):
            continue  # 活动类科目的虚拟老师不需要冲突约束
            
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
    # 4. 规则引擎集成 (New Rule Engine)
    # ====================================================================
    rules = config.get('rules', [])
    
    # [诊断] 打印收到的所有规则
    logger.info(f"[规则诊断] 收到 {len(rules)} 条规则:")
    for i, r in enumerate(rules):
        r_name = r.get('name', '无名规则')
        r_type = r.get('type', 'UNKNOWN')
        r_targets = r.get('targets', {})
        r_subjects = r_targets.get('subjects', [])
        logger.info(f"  [{i+1}] {r_type}: {r_subjects or r_targets.get('names', []) or r_targets.get('grades', ['全校'])}")
    
    # 兼容性逻辑：如果开启了 legacy 模式且没有显式规则，则注入绍兴预设规则
    use_legacy_rules = config.get('use_legacy_rules', True)
    if use_legacy_rules and not rules:
        rules = SHAOXING_PRESET_RULES
        logger.info("Using SHAOXING_PRESET_RULES because rules list is empty and legacy mode is enabled.")

    # 注入通用规则
    apply_universal_rules(model, schedule, rules, TEACHERS_DB, class_metadata, teacher_assignments, ALL_SUBJECTS_IN_VARS, SLOTS, penalties, assumption_literals, rule_mapping)

    # --- 6. 教室资源约束 (Classroom Constraints) ---
        

    # --- 5. 高级约束 (Legacy Constraints) ---
    CONSTRAINTS = config.get('constraints', {})
    
    # 构建名字到ID的映射 (name -> List[tid])
    name_to_tids = collections.defaultdict(list)
    for t in TEACHERS_DB:
        name_to_tids[t['name']].append(t['id'])

    # (Legacy constraints logic moved to switch-controlled section below)

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

    # 处理老师禁排与固定课程
    unavailable_settings = CONSTRAINTS.get('teacher_unavailable', {})
    fixed_courses = CONSTRAINTS.get('fixed_courses', {})

    if fixed_courses:
        for c_str, fixes in fixed_courses.items():
            try: c = int(c_str)
            except: continue
            if c not in CLASSES: continue
            
            for slot_key, subj_name in fixes.items():
                if subj_name not in ALL_SUBJECTS_IN_VARS: continue
                try:
                    d_str, p_str = slot_key.split('_')
                    d, p = int(d_str), int(p_str)
                    
                    # 创建开关
                    sys_switch = model.NewBoolVar(f'sys_fixed_{c}_{d}_{p}')
                    assumption_literals.append(sys_switch)
                    rule_mapping[sys_switch.Index()] = f"【系统预排】{c}班_{subj_name}_固定({d},{p})"
                    
                    model.Add(schedule[(c, d, p, subj_name)] == 1).OnlyEnforceIf(sys_switch)
                except: pass

    for t_name, slots in unavailable_settings.items():
        tids = name_to_tids.get(t_name, [])
        for tid in tids:
            assignments = teacher_assignments.get(tid, [])
            if not assignments: continue
            for day, period in slots:
                 if 0 <= day < DAYS and 0 <= period < PERIODS:
                    sys_switch = model.NewBoolVar(f'sys_unavail_{t_name}_{day}_{period}')
                    assumption_literals.append(sys_switch)
                    rule_mapping[sys_switch.Index()] = f"【老师禁排】{t_name}_周{day+1}第{period+1}节"
                    model.Add(sum(schedule[(c, day, period, s)] for (c, s) in assignments) == 0).OnlyEnforceIf(sys_switch)


    # 设置总目标：最小化惩罚
    if penalties:
        model.Minimize(sum(penalties))

    # 激活所有开关
    logger.info(f"DEBUG: assumption_literals count: {len(assumption_literals)}")
    if assumption_literals:
        model.AddAssumptions(assumption_literals)

    # 求解
    solver = cp_model.CpSolver()
    # 根据班级数动态调整求解时间
    if NUM_CLASSES >= 100:
        solver.parameters.max_time_in_seconds = 600.0  # 10分钟
        solver.parameters.num_search_workers = 24  # 最大线程
        logger.info(f"Large scale mode: 100+ classes, solver timeout 10min, 24 threads")
    elif NUM_CLASSES >= 60:
        solver.parameters.max_time_in_seconds = 300.0  # 5分钟
        solver.parameters.num_search_workers = 16
    else:
        solver.parameters.max_time_in_seconds = 180.0  # 3分钟
        solver.parameters.num_search_workers = 12
    solver.parameters.randomize_search = True 
    solver.parameters.log_search_progress = True
    
    # 增加首解停止逻辑
    solution_callback = StopAfterFirstSolution()
    status = solver.Solve(model, solution_callback)
    
    logger.info(f"Solver status: {solver.StatusName(status)}")

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # === 统计模块 ===
        stats = {}
        t_id_to_name = {t['id']: t['name'] for t in TEACHERS_DB}
        
        # 初始化统计数据
        for t_name in t_id_to_name.values():
            stats[t_name] = {"total": 0, "daily": [0] * 5}
            
        # 遍历排课结果进行统计并构建结果字典
        formatted_schedule = {}
        for c in CLASSES:
            for d in range(DAYS):
                for p in range(PERIODS):
                    for subj in global_course_requirements:
                        if solver.Value(schedule[(c, d, p, subj)]) == 1:
                            # 1. 统计老师课时
                            tid = CLASS_TEACHER_MAP.get((c, subj))
                            if tid is not None and tid in t_id_to_name:
                                t_name = t_id_to_name[tid]
                                stats[t_name]["total"] += 1
                                stats[t_name]["daily"][d] += 1
                            
                            # 2. 存入结果字典
                            tid = CLASS_TEACHER_MAP.get((c, subj))
                            t_name = ""
                            if tid: t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == tid), "")
                            formatted_schedule[(c, d, p)] = {
                                "subject": subj,
                                "teacher_name": t_name,
                                "teacher_id": tid
                            }
                            break

        # [新增] 调用规则验算报告
        rule_report = verify_rules(
            formatted_schedule, rules, class_metadata, TEACHERS_DB, CLASS_TEACHER_MAP, DAYS, PERIODS
        )

        # [新增] 调用评估函数
        evaluation = evaluate_quality(
            schedule, solver, CLASSES, DAYS, PERIODS, 
            global_course_requirements, CLASS_TEACHER_MAP, TEACHERS_DB
        )

        return {
            "status": "success",
            "rule_report": rule_report,  # <--- 将报告返回给前端
            "sharding_info": sharding_report, # [新增] 向前端传递替换详情
            "stats": stats,
            "evaluation": evaluation,
            "solver": solver,
            "schedule": formatted_schedule,
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
        # === INFEASIBLE 诊断模块 ===
        suggestions = ["尝试减少课时需求", "检查是否有老师课时超限", "移除部分固定课程"]
        error_msg = "无法找到满足所有硬性约束的课表 (INFEASIBLE)"
        
        if status == cp_model.INFEASIBLE and assumption_literals:
            logger.info("DEBUG: Triggering SufficientAssumptionsForInfeasibility (Pass 1)...")
            conflict_indices = solver.SufficientAssumptionsForInfeasibility()
            logger.info(f"DEBUG: Pass 1 indices: {conflict_indices}")
            conflict_rules = [rule_mapping[i] for i in conflict_indices if i in rule_mapping]
            
            if not conflict_rules:
                logger.info("DEBUG: Pass 1 returned empty. Retrying with Presolve=False...")
                solver_diag = cp_model.CpSolver()
                solver_diag.parameters.cp_model_presolve = False
                solver_diag.parameters.max_time_in_seconds = 10.0
                status_diag = solver_diag.Solve(model)
                
                if status_diag == cp_model.INFEASIBLE:
                    conflict_indices = solver_diag.SufficientAssumptionsForInfeasibility()
                    conflict_rules = [rule_mapping[i] for i in conflict_indices if i in rule_mapping]
            
            if conflict_rules:
                error_msg = f"排课失败: 检测到 {len(conflict_rules)} 个约束发生冲突"
                suggestions = [f"冲突核心: {', '.join(conflict_rules)}"]
                suggestions.append("建议: 尝试放宽约束")
                suggestions.append("建议: 减少一键生成中的硬约束数量")
                suggestions.append("建议: 减少固定课程设置")
            else:
                 suggestions.append("【严重】可能是老师资源物理不足（同一时段需要上课的班级数 > 老师人数）。")

        return {
            "status": "error",
            "error_type": "infeasible", 
            "message": error_msg,
            "suggestions": suggestions
        }