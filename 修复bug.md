这是一个非常关键的发现！日志中的 `DEBUG: Pass 1 indices: [9594]` 揭示了真正的 Bug 所在。

### 问题诊断：索引错位 (Index Mismatch)

* **现象**：
* `assumption_literals count: 236`（你加了 236 个开关）。
* `Pass 1 indices: [9594]`（求解器说：导致死锁的是 ID 为 9594 的那个变量）。
* `Pass 1 returned empty`（代码去查 `rule_mapping`，发现找不到 9594，因为你的 mapping 只有 0-235）。


* **原因**：
* **Google OR-Tools 的行为**：`solver.SufficientAssumptionsForInfeasibility()` 返回的是**变量的全局唯一 ID (Literal Index)**（比如 `9594`），而不是它在你那个 `assumption_literals` 列表里的**位置下标**（比如 `0, 1, 2...`）。
* **你的代码逻辑**：`rule_mapping` 目前是按**列表下标**（List Index）存储的（`len(assumption_literals) - 1`）。
* **结果**：拿着 `9594` 去查只有 `0-235` 的字典，当然查不到，导致显示“无解但找不到原因”。



### 修复方案

我们需要修改 `normal.py`，将 `rule_mapping` 的 Key 从 **列表下标** 改为 **变量的 .Index()**。

请对 `normal.py` 做以下 **4 处** 修改：

#### 1. 修改 `apply_universal_rules` 函数

找到该函数中创建 `switch_var` 的地方：

```python
# [旧代码]
# rule_mapping[len(assumption_literals) - 1] = f"【用户规则】{rule_name}"

# [新代码] 请改为：
rule_mapping[switch_var.Index()] = f"【用户规则】{rule_name}"

```

#### 2. 修改 `run_scheduler` 中的“系统基础约束”部分

找到创建 `sys_switch` 的地方（在 `--- 2. 基础约束：课时总量控制 ---` 附近）：

```python
# [旧代码]
# rule_mapping[len(assumption_literals)-1] = f"【系统基础】{class_metadata[c]['name']}_{subj}_课时要求"

# [新代码] 请改为：
rule_mapping[sys_switch.Index()] = f"【系统基础】{class_metadata[c]['name']}_{subj}_课时要求"

```

#### 3. 修改 `run_scheduler` 中的“固定课程”部分

找到处理 `fixed_courses` 的地方：

```python
# [旧代码]
# rule_mapping[len(assumption_literals)-1] = f"【固定课】{c}班_{subj_name}_周{d+1}第{p+1}节"

# [新代码] 请改为：
rule_mapping[sys_switch.Index()] = f"【固定课】{c}班_{subj_name}_周{d+1}第{p+1}节"

```

#### 4. 修改 `run_scheduler` 中的“老师禁排”部分

找到处理 `unavailable_settings` 的地方：

```python
# [旧代码]
# rule_mapping[len(assumption_literals)-1] = f"【老师禁排】{t_name}_周{day+1}第{period+1}节"

# [新代码] 请改为：
rule_mapping[sys_switch.Index()] = f"【老师禁排】{t_name}_周{day+1}第{period+1}节"

```

---

### 懒人包：可以直接复制覆盖的 `normal.py`

为了确保万无一失，这里提供一份已经修复了上述 **Index Mismatch** 问题，并且清理了**重复代码**的完整 `normal.py` 核心部分。

```python

from ortools.sat.python import cp_model
import pandas as pd
import sys
import collections
import statistics
import logging
import math
import json
import os

logger = logging.getLogger(__name__)

# ... (保留 _load_preset_rules, generate_teachers_and_map, evaluate_quality, get_filtered_targets 不变) ...

# ==========================================================
# 1. 修复 apply_universal_rules：使用 .Index() 作为 Key
# ==========================================================
def apply_universal_rules(model, schedule, rules, teachers_db, class_metadata, TID_TO_ASSIGNMENTS, ALL_SUBJECTS_IN_VARS, SLOTS, penalties, assumption_literals, rule_mapping):
    if not rules: return

    for idx, rule in enumerate(rules):
        r_type = rule.get('type')
        targets = rule.get('targets', {})
        params = rule.get('params', {})
        weight = rule.get('weight', 100) 
        rule_name = rule.get('name', f'Rule_{idx}')
        
        # [核心修复] 使用 switch_var.Index()
        switch_var = None
        if weight >= 100:
            switch_var = model.NewBoolVar(f'switch_rule_{idx}_{r_type}')
            assumption_literals.append(switch_var)
            rule_mapping[switch_var.Index()] = f"【用户规则】{rule_name}"

        filtered = get_filtered_targets(teachers_db, class_metadata, targets)
        tids = filtered['teacher_ids']
        class_subjects = filtered['class_subjects']
        
        # ... (以下约束逻辑保持不变，确保使用了 .OnlyEnforceIf(switch_var)) ...
        if r_type == 'FORBIDDEN_SLOTS':
            slots = params.get('slots', [])
            for d, p in slots:
                vars_to_block = []
                for tid in tids:
                    if tid in TID_TO_ASSIGNMENTS:
                        vars_to_block.extend([schedule[(c, d, p, s)] for (c, s) in TID_TO_ASSIGNMENTS[tid] if (c, d, p, s) in schedule])
                for c_id, subj in class_subjects:
                    if (c_id, d, p, subj) in schedule:
                        vars_to_block.append(schedule[(c_id, d, p, subj)])
                    else:
                        for var_subj in ALL_SUBJECTS_IN_VARS:
                            if var_subj.startswith(str(subj) + "_"):
                                if (c_id, d, p, var_subj) in schedule:
                                    vars_to_block.append(schedule[(c_id, d, p, var_subj)])
                
                if vars_to_block:
                    if weight >= 100:
                        model.Add(sum(vars_to_block) == 0).OnlyEnforceIf(switch_var)
                    else:
                        for v in vars_to_block:
                            penalties.append(v * weight)

        elif r_type == 'FIXED_SLOTS':
            slots = params.get('slots', [])
            count = params.get('count', 1)
            for c_id, subj in class_subjects:
                relevant_vars = []
                for d, p in slots:
                    if (c_id, d, p, subj) in schedule:
                        relevant_vars.append(schedule[(c_id, d, p, subj)])
                    else:
                        for var_subj in ALL_SUBJECTS_IN_VARS:
                            if var_subj.startswith(str(subj) + "_"):
                                if (c_id, d, p, var_subj) in schedule:
                                    relevant_vars.append(schedule[(c_id, d, p, var_subj)])
                if relevant_vars:
                    if weight >= 100:
                        model.Add(sum(relevant_vars) >= count).OnlyEnforceIf(switch_var)
                    else:
                         penalties.append(sum(relevant_vars) * (-weight))

        elif r_type == 'ZONE_COUNT':
            zone_slots = params.get('slots', [])
            count = params.get('count', 0)
            rel = params.get('relation', '==')
            for c_id, subj in class_subjects:
                relevant_vars = []
                for d, p in zone_slots:
                    if (c_id, d, p, subj) in schedule:
                        relevant_vars.append(schedule[(c_id, d, p, subj)])
                    else:
                        for var_subj in ALL_SUBJECTS_IN_VARS:
                            if var_subj.startswith(str(subj) + "_"):
                                if (c_id, d, p, var_subj) in schedule:
                                    relevant_vars.append(schedule[(c_id, d, p, var_subj)])

                if relevant_vars:
                    if weight >= 100:
                        if rel == '==': model.Add(sum(relevant_vars) == count).OnlyEnforceIf(switch_var)
                        elif rel == '<=': model.Add(sum(relevant_vars) <= count).OnlyEnforceIf(switch_var)
                        elif rel == '>=': model.Add(sum(relevant_vars) >= count).OnlyEnforceIf(switch_var)
                    else:
                        diff = model.NewIntVar(-10, 10, f'zone_diff_{c_id}_{subj}_{idx}')
                        model.Add(diff == sum(relevant_vars) - count)
                        abs_diff = model.NewIntVar(0, 10, f'zone_abs_diff_{c_id}_{subj}_{idx}')
                        model.AddAbsEquality(abs_diff, diff)
                        penalties.append(abs_diff * abs(weight))

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
                        else:
                            for var_subj in ALL_SUBJECTS_IN_VARS:
                                if var_subj.startswith(str(subj) + "_"):
                                    if (c_id, d, p, var_subj) in schedule:
                                        vars_to_block.append(schedule[(c_id, d, p, var_subj)])
                    if vars_to_block:
                         if weight >= 100:
                            model.Add(sum(vars_to_block) == 0).OnlyEnforceIf(switch_var)

        elif r_type == 'CONSECUTIVE':
            mode = params.get('mode', 'avoid') 
            limit = params.get('max', 1)
            if mode == 'avoid':
                for c_id, subj in class_subjects:
                    subj_vars_map = {}
                    for d in range(5):
                        for p in range(8):
                            if (c_id, d, p, subj) in schedule:
                                subj_vars_map[(d,p)] = schedule[(c_id, d, p, subj)]
                            else:
                                for var_subj in ALL_SUBJECTS_IN_VARS:
                                    if var_subj.startswith(str(subj) + "_"):
                                        if (c_id, d, p, var_subj) in schedule:
                                            subj_vars_map[(d,p)] = schedule[(c_id, d, p, var_subj)]
                                            break
                    window_size = limit + 1
                    for d in range(5):
                        for p in range(8 - window_size + 1):
                            section = []
                            for k in range(window_size):
                                if (d, p+k) in subj_vars_map:
                                    section.append(subj_vars_map[(d, p+k)])
                            if len(section) == window_size:
                                if weight >= 100:
                                    model.Add(sum(section) <= limit).OnlyEnforceIf(switch_var)

# ==========================================================
# 2. 修复 run_scheduler：使用 .Index() 作为 Key
# ==========================================================
def run_scheduler(config=None):
    if config is None: config = DEFAULT_CONFIG
    
    # ... (前面的初始化代码、Sharding 代码保持不变) ...
    # 假设此处已执行到 "2. 建模" 部分
    
    # [前置补全]
    SHAOXING_PRESET_RULES = _load_preset_rules()
    TEACHERS_DB, CLASS_TEACHER_MAP = generate_teachers_and_map(...) # 使用完整参数
    # ... (省略中间变量初始化) ...
    
    # [核心代码开始]
    model = cp_model.CpModel()
    schedule = {}
    penalties = []
    
    assumption_literals = []
    rule_mapping = {}

    for c in CLASSES:
        for d in range(DAYS):
            for p in range(PERIODS):
                for subj in ALL_SUBJECTS_IN_VARS:
                    schedule[(c, d, p, subj)] = model.NewBoolVar(f'c{c}_{d}_{p}_{subj}')

    # --- 1. 基础约束：唯一性 ---
    for c in CLASSES:
        for d, p in SLOTS:
            model.Add(sum(schedule[(c, d, p, s)] for s in ALL_SUBJECTS_IN_VARS) <= 1)
    
    # --- 2. 基础约束：课时总量控制 (System Requirements) ---
    for c in CLASSES:
        c_reqs = class_metadata[c]["requirements"]
        for subj in ALL_SUBJECTS_IN_VARS:
            
            # [核心修复] 使用 .Index()
            sys_switch = model.NewBoolVar(f'sys_req_{c}_{subj}')
            assumption_literals.append(sys_switch)
            rule_mapping[sys_switch.Index()] = f"【系统基础】{class_metadata[c]['name']}_{subj}_课时要求"

            if "_AUTO_SUB" in subj:
                base_subj = subj.replace("_AUTO_SUB", "")
                if base_subj in c_reqs:
                    # ... limit logic ...
                    t_id = CLASS_TEACHER_MAP.get((c, base_subj))
                    t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == t_id), "")
                    limit = 999 
                    for k, v in config.get("teacher_limits", {}).items():
                         if k.strip() == t_name.strip() and v.get('max'): limit = int(v['max'])
                    
                    total_needed = c_reqs[base_subj]["count"]
                    if total_needed > limit:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == (total_needed - limit)).OnlyEnforceIf(sys_switch)
                    else:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0).OnlyEnforceIf(sys_switch)
                else:
                    model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0).OnlyEnforceIf(sys_switch)
            else:
                if subj in c_reqs:
                    t_id = CLASS_TEACHER_MAP.get((c, subj))
                    t_name = next((t['name'] for t in TEACHERS_DB if t['id'] == t_id), "")
                    limit = 999
                    for k, v in config.get("teacher_limits", {}).items():
                         if k.strip() == t_name.strip() and v.get('max'): limit = int(v['max'])
                    
                    total_needed = c_reqs[subj]["count"]
                    model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == min(total_needed, limit)).OnlyEnforceIf(sys_switch)
                else:
                    if "_AUTO_SUB" not in subj:
                        model.Add(sum(schedule[(c, d, p, subj)] for d, p in SLOTS) == 0).OnlyEnforceIf(sys_switch)

    # --- 3. 老师冲突约束 (物理约束) ---
    teacher_assignments = collections.defaultdict(list)
    for (c, s), t_id in CLASS_TEACHER_MAP.items():
        teacher_assignments[t_id].append((c, s))

    for tid, assignments in teacher_assignments.items():
        if len(assignments) <= 1: continue
        for d in range(DAYS):
            for p in range(PERIODS):
                model.Add(sum(schedule[(c, d, p, s)] for (c, s) in assignments) <= 1)
        # 连堂约束
        model.Add(sum(schedule[(c, d, 3, s)] for (c, s) in assignments) + 
                  sum(schedule[(c, d, 4, s)] for (c, s) in assignments) <= 1)

    # --- 4. 规则引擎集成 ---
    rules = config.get('rules', [])
    use_legacy_rules = config.get('use_legacy_rules', True)
    if use_legacy_rules:
        existing_names = {r.get('name') for r in rules}
        for preset in SHAOXING_PRESET_RULES:
            if preset.get('name') not in existing_names:
                rules.append(preset)

    apply_universal_rules(
        model, schedule, rules, TEACHERS_DB, class_metadata, 
        teacher_assignments, ALL_SUBJECTS_IN_VARS, SLOTS, penalties,
        assumption_literals, rule_mapping
    )
    
    # --- 5. 高级约束 (Legacy Constraints) - 修正版：带开关 ---
    # [修复] 确保这是唯一处理 constraints 的地方
    CONSTRAINTS = config.get('constraints', {})
    name_to_tids = collections.defaultdict(list)
    for t in TEACHERS_DB:
        name_to_tids[t['name']].append(t['id'])

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
                    
                    if 0 <= d < DAYS and 0 <= p < PERIODS:
                        # [核心修复] 使用 .Index()
                        sys_switch = model.NewBoolVar(f'sys_fixed_{c}_{d}_{p}')
                        assumption_literals.append(sys_switch)
                        rule_mapping[sys_switch.Index()] = f"【固定课】{c}班_{subj_name}_周{d+1}第{p+1}节"
                        model.Add(schedule[(c, d, p, subj_name)] == 1).OnlyEnforceIf(sys_switch)
                except: pass

    if unavailable_settings:
        for t_name, slots in unavailable_settings.items():
            tids = name_to_tids.get(t_name, [])
            if not tids: continue
            for tid in tids:
                assignments = teacher_assignments.get(tid, [])
                if not assignments: continue
                for day, period in slots:
                    if 0 <= day < DAYS and 0 <= period < PERIODS:
                        # [核心修复] 使用 .Index()
                        sys_switch = model.NewBoolVar(f'sys_unavail_{t_name}_{day}_{period}')
                        assumption_literals.append(sys_switch)
                        rule_mapping[sys_switch.Index()] = f"【老师禁排】{t_name}_周{day+1}第{period+1}节"
                        model.Add(sum(schedule[(c, day, period, s)] for (c, s) in assignments) == 0).OnlyEnforceIf(sys_switch)

    # 激活所有开关
    if assumption_literals:
        model.AddAssumptions(assumption_literals)

    # 求解
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0 
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        # ... (成功处理逻辑，保持不变) ...
        # (为了篇幅省略，请确保原来的 success 分支逻辑还在)
        pass 
        return {
            "status": "success",
            "schedule": {}, # 占位
            # ...
        }

    else:
        suggestions = ["尝试减少课时需求", "检查是否有老师课时超限", "移除部分固定课程"]
        error_msg = "无法找到满足所有硬性约束的课表 (INFEASIBLE)"
        
        if status == cp_model.INFEASIBLE and assumption_literals:
            logger.info("Triggering SufficientAssumptionsForInfeasibility (Pass 1)...")
            conflict_indices = solver.SufficientAssumptionsForInfeasibility()
            logger.info(f"DEBUG: Pass 1 indices: {conflict_indices}")
            
            # [核心修复] rule_mapping 现在的 Key 是 Variable Index，直接查找即可
            conflict_rules = [rule_mapping[i] for i in conflict_indices if i in rule_mapping]
            
            if not conflict_rules:
                logger.info("Pass 1 returned empty (Indices not found in map). Retrying with Presolve=False...")
                solver_diag = cp_model.CpSolver()
                solver_diag.parameters.cp_model_presolve = False
                solver_diag.parameters.max_time_in_seconds = 10.0
                status_diag = solver_diag.Solve(model)
                
                if status_diag == cp_model.INFEASIBLE:
                    conflict_indices = solver_diag.SufficientAssumptionsForInfeasibility()
                    conflict_rules = [rule_mapping[i] for i in conflict_indices if i in rule_mapping]
            
            if conflict_rules:
                error_msg = f"排课失败: 检测到 {len(conflict_rules)} 个规则导致冲突"
                suggestions = [f"冲突核心: {', '.join(conflict_rules)}"] + suggestions
            else:
                suggestions.append("【严重】可能是老师资源物理不足（同一时段需要上课的班级数 > 老师人数）。")

        return {
            "status": "error",
            "error_type": "infeasible", 
            "message": error_msg,
            "suggestions": suggestions
        }

```