这是对你提供的 `normal.py` 代码的深度逻辑审查。代码结构已经很完整了，包含了数据预处理、OR-Tools 建模、求解和后处理统计。

然而，代码中存在 **3 个致命的逻辑缺陷** 和 **2 个严重的性能隐患**，这会导致排课结果“能跑通但不好用”，或者出现“同一个老师分身乏术”的 Bug。

以下是详细分析：

### 🛑 1. 致命逻辑：优化被强制中断 (The Optimization Killer)

**位置：** `StopAfterFirstSolution` 类 和 `status = solver.Solve(model, solution_callback)`

**问题描述：**
你在第 1232 行精心设置了 `model.Minimize(sum(penalties))`，目的是让求解器寻找“代价最小”（即最符合软规则）的课表。
但是，你在第 1253 行传入了 `StopAfterFirstSolution` 回调。这意味着：**只要求解器找到任何一个“不报错”的课表（哪怕是最差的解），它就会立即停止**。

**后果：**

* 你的所有 `weight < 100` 的规则（如“副课尽量排下午”、“教案尽量均匀”）**完全失效**。
* 求解器根本没有时间去运行优化算法，你设置的 `max_time_in_seconds` (10分钟/5分钟) 也变得毫无意义，因为通常 0.1 秒找到第一个解后程序就退出了。

**✅ 修复方案：**
删除回调，让求解器利用你设置的时间去搜索最优解。

```python
# 修改前
# solution_callback = StopAfterFirstSolution()
# status = solver.Solve(model, solution_callback)

# 修改后
# 不传 callback，让 solver 跑满 max_time_in_seconds 或直到找到最优解
status = solver.Solve(model)

```

---

### 🛑 2. 致命逻辑：老师“分身” Bug (The Doppelgänger Bug)

**位置：** `get_or_create_teacher_id` 与 老师冲突约束

**问题描述：**
在生成 ID 时，你为了按年级隔离主课老师，使用了这样的逻辑：

```python
id_key = f"{name}_{grade_name}" if type_ == "main" else name

```

假设“王老师”既教初一数学（主课），又教初二数学（主课）。系统会生成两个 ID：`t_王老师_初一` 和 `t_王老师_初二`。

在第 1135 行的冲突检测中：

```python
for tid, assignments in teacher_assignments.items():
    # ...model.Add(sum(...) <= 1)

```

你是**按 TID 遍历**的。OR-Tools 认为 `t_王老师_初一` 和 `t_王老师_初二` 是**两个完全不同的人**。

**后果：**
**王老师会被排在同一天的同一节课**（比如周一第一节，初一在上一班，初二在另一班）。这是物理上不可能的。

**✅ 修复方案：**
必须建立“自然人”维度的冲突约束，而不是“Teacher ID”维度。

```python
# 1. 先构建 自然人 -> [所有相关 TID] 的映射
real_person_map = collections.defaultdict(list)
for t in TEACHERS_DB:
    # 假设 name 是唯一标识自然人的键
    real_person_map[t['name']].append(t['id'])

# 2. 修改约束循环 (替换原有的 1135-1148 行)
for name, tids in real_person_map.items():
    # 获取该自然人名下所有 ID 的所有课程变量
    all_assignments = []
    for tid in tids:
         if tid in teacher_assignments:
             all_assignments.extend(teacher_assignments[tid])
    
    if not all_assignments: continue

    # 对每一时刻，约束该自然人的所有分身总和 <= 1
    for d in range(DAYS):
        for p in range(PERIODS):
            # 收集该自然人所有分身在该时刻的变量
            vars_at_slot = [schedule[(c, d, p, s)] for (c, s) in all_assignments]
            model.Add(sum(vars_at_slot) <= 1)

```

---

### ⚠️ 3. 逻辑隐患：评估系统与求解目标脱节

**位置：** `evaluate_quality` vs `apply_universal_rules`

**问题描述：**

* `evaluate_quality` 是用 Python 代码在事后计算分数的（扣分制）。
* `apply_universal_rules` 是向 OR-Tools 添加 Penalty 约束的。
* **脱节点**：例如 `evaluate_quality` 里有“方差计算”（负载均衡），但我在 `apply_universal_rules` 里没有看到对应的 Minimize Variance 建模。

**后果：**
求解器在跑的时候，并不知道你要“负载均衡”（因为它只看模型里的 Penalties）。排出来的课表在 `evaluate_quality` 里评分可能很低，但求解器觉得自己已经尽力了。你必须把 Python 的评分逻辑翻译成 OR-Tools 的约束才能真正生效。

---

### 📉 4. 性能隐患：变量爆炸 (Variable Explosion)

**位置：** 变量定义循环

**问题描述：**

```python
for subj in ALL_SUBJECTS_IN_VARS:
    schedule[(c, d, p, subj)] = model.NewBoolVar(...)

```

你对**每个班级**的**每个时间点**，都创建了**所有科目**的布尔变量。
如果全校有 30 个班，100 个老师（对应 100 个细分科目变量），5天8节。
变量数 =  个布尔变量。
紧接着在 你又强制把绝大多数变量设为 0（因为该班级根本不上这个老师的课）。

**优化建议：**
只为该班级“需要的”科目创建变量。

```python
# 优化思路
for c in CLASSES:
    # 只获取该班级需要的科目列表
    required_subjects = class_metadata[c]['requirements'].keys()
    for d in range(DAYS):
        for p in range(PERIODS):
            for subj in required_subjects:
                schedule[(c, d, p, subj)] = model.NewBoolVar(...)

```

这可以将变量规模减少 90% 以上，极大提升求解速度。

---

### 🛠️ 5. 代码细节错误

* **逻辑错误**：
在循环内部：
```python
for k, v in config.get("teacher_limits", {}).items():
     if k.strip() == t_name.strip() and v.get('max'): limit = int(v['max'])

```


你在最内层的 `d, p` 循环外层计算这个 `limit` 是对的，但在 1111 行这里，你没有 `break`。虽然功能没错，但效率极低（每次都遍历整个字典）。建议在循环外预处理好 `name -> limit` 的字典。
* **绝对值约束滥用**：
```python
model.AddAbsEquality(abs_diff, diff)

```


在 OR-Tools 中，直接对 `diff` 平方或者直接用线性近似通常比 `AddAbsEquality` 更稳定，不过这个问题不大，可以保留。

### 总结建议

你的 `normal.py` 是一个非常典型的 OR-Tools 排课实现，结构很清晰。目前的当务之急是：

1. **删除 `StopAfterFirstSolution**`（让软约束生效）。
2. **重写老师冲突约束**（按 Name 而不是 ID 聚合，解决分身问题）。
3. **优化变量创建**（只创建必要的变量，防止大规模排课时内存溢出）。

解决这三点后，你的系统可用性会有质的飞跃。