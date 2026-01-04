import pandas as pd


class SwapCandidate:
    """课程互换候选方案"""
    def __init__(self, substitute_tid, swap_day, swap_period, 
                 original_class, substitute_class, subject):
        self.substitute_tid = substitute_tid  # 代课老师ID
        self.swap_day = swap_day             # 互换的天
        self.swap_period = swap_period       # 互换的节次
        self.original_class = original_class # 请假老师原课的班级
        self.substitute_class = substitute_class  # 代课老师原课的班级
        self.subject = subject               # 科目
        self.score = 1  # 扰动度（固定为1次互换）
    
    def __repr__(self):
        return (f"SwapCandidate(teacher={self.substitute_tid}, "
                f"swap=({self.swap_day},{self.swap_period}), "
                f"classes={self.original_class}↔{self.substitute_class})")


class SubstitutionSystem:
    def __init__(self, solver_result):
        """
        solver_result: normal.run_scheduler 返回的字典
        """
        self.solver = solver_result['solver']
        self.vars = solver_result['vars']
        self.teachers_db = solver_result['teachers_db']
        self.class_teacher_map = solver_result['class_teacher_map']
        self.classes = solver_result['classes']
        self.days = solver_result['days'] # 5
        self.periods = solver_result['periods'] # 6
        self.courses = solver_result['courses']
        
        self.final_schedule = {} 
        self.teacher_busy = set()
        
        # 辅助字典
        self.id_to_name = {t['id']: t['name'] for t in self.teachers_db}
        self.name_to_id = {t['name']: t['id'] for t in self.teachers_db}
        self.subject_teachers = {}
        for t in self.teachers_db:
            self.subject_teachers.setdefault(t['subject'], []).append(t['id'])

        self._parse_original_schedule()

    def _parse_original_schedule(self):
        for c in self.classes:
            for d in range(self.days):
                for p in range(self.periods):
                    for subj in self.courses:
                        if self.solver.Value(self.vars[(c, d, p, subj)]):
                            tid = self.class_teacher_map.get((c, subj))
                            tname = self.id_to_name.get(tid, "Unknown")
                            
                            self.final_schedule[(c, d, p)] = {
                                "subject": subj,
                                "teacher_id": tid,
                                "teacher_name": tname,
                                "is_sub": False
                            }
                            self.teacher_busy.add((tid, d, p))
                            break

    def process_leaves(self, leave_requests):
        """
        处理请假请求，采用三级代课策略
        
        Level 1: 直接代课（找到空闲的同科目老师）
        Level 2: 课程互换（通过调整课程时间来安排代课）
        Level 3: 标记自习（实在找不到解决方案）
        """
        # 1. 识别请假老师ID
        all_leave_tids = set()
        for req in leave_requests:
            if req['name'] in self.name_to_id:
                all_leave_tids.add(self.name_to_id[req['name']])

        # 统计信息
        stats = {
            'direct': 0,  # 直接代课次数
            'swap': 0,    # 课程互换次数
            'self_study': 0  # 自习次数
        }

        # 2. 遍历查找代课
        slots = list(self.final_schedule.keys())
        for (c, d, p) in slots:
            info = self.final_schedule[(c, d, p)]
            original_tid = info['teacher_id']
            
            # 检查是否请假
            is_on_leave = False
            for req in leave_requests:
                if req['name'] == info['teacher_name'] and d in req['days']:
                    is_on_leave = True
                    break
            
            if is_on_leave:
                # === Level 1: 尝试直接代课 ===
                sub_tid = self._get_substitute(d, p, info['subject'], original_tid, all_leave_tids)
                if sub_tid:
                    self.final_schedule[(c, d, p)]['teacher_id'] = sub_tid
                    self.final_schedule[(c, d, p)]['teacher_name'] = self.id_to_name[sub_tid]
                    self.final_schedule[(c, d, p)]['is_sub'] = True
                    self.teacher_busy.add((sub_tid, d, p))
                    stats['direct'] += 1
                    continue  # 成功，处理下一个
                
                # === Level 2: 尝试课程互换 ===
                swap_candidates = self._find_swap_candidates(
                    d, p, c, info['subject'], original_tid, all_leave_tids
                )
                
                if swap_candidates:
                    best_swap = self._select_best_swap(swap_candidates)
                    self._execute_swap(best_swap, d, p, c, original_tid, all_leave_tids)
                    stats['swap'] += 1
                    print(f"✓ 课程互换: {self.id_to_name[best_swap.substitute_tid]} "
                          f"周{d+1}第{p+1}节去{c}班代课, "
                          f"原课调至周{best_swap.swap_day+1}第{best_swap.swap_period+1}节")
                    continue  # 成功，处理下一个
                
                # === Level 3: 标记自习 ===
                self.final_schedule[(c, d, p)]['teacher_name'] = "【自习】"
                self.final_schedule[(c, d, p)]['is_sub'] = True
                stats['self_study'] += 1
                print(f"✗ 无法安排代课: {c}班 周{d+1}第{p+1}节 标记为自习")
        
        # 输出统计信息
        print(f"\n📊 代课统计:")
        print(f"  - 直接代课: {stats['direct']}次")
        print(f"  - 课程互换: {stats['swap']}次")
        print(f"  - 标记自习: {stats['self_study']}次")
        print(f"  - 总扰动度: {stats['direct'] * 0 + stats['swap'] * 1 + stats['self_study'] * 999}分")
        
        return stats

    def _get_substitute(self, day, period, subject, original_tid, leave_tids):
        """Level 1: 查找完全空闲的代课老师"""
        candidates = self.subject_teachers.get(subject, [])
        for cand_id in candidates:
            if cand_id == original_tid: continue
            if cand_id in leave_tids: continue
            if (cand_id, day, period) in self.teacher_busy: continue
            return cand_id
        return None
    
    def _find_swap_candidates(self, day, period, class_id, subject, 
                              original_tid, leave_tids):
        """
        Level 2: 查找可以通过课程互换的代课方案
        
        Args:
            day: 请假课程的日期
            period: 请假课程的节次
            class_id: 请假课程的班级
            subject: 科目
            original_tid: 请假老师ID
            leave_tids: 所有请假老师ID集合
        
        Returns:
            List[SwapCandidate]: 所有可行的互换方案
        """
        swap_candidates = []
        candidates = self.subject_teachers.get(subject, [])
        
        # 遍历所有同科目老师（包括正在上课的）
        for cand_tid in candidates:
            if cand_tid == original_tid:
                continue
            if cand_tid in leave_tids:
                continue
            
            # 该老师在目标时段有课 - 检查能否互换
            if (cand_tid, day, period) in self.teacher_busy:
                # 找到该老师在这个时段上课的班级
                substitute_class = None
                for (c, d, p), info in self.final_schedule.items():
                    if d == day and p == period and info['teacher_id'] == cand_tid:
                        substitute_class = c
                        break
                
                if substitute_class is None:
                    continue
                
                # 遍历所有可能的互换时间
                for swap_d in range(self.days):
                    for swap_p in range(self.periods):
                        if swap_d == day and swap_p == period:
                            continue  # 跳过原时段
                        
                        # 检查是否可以互换到这个时段
                        if self._can_swap(original_tid, (day, period), (swap_d, swap_p),
                                         class_id, substitute_class,
                                         cand_tid, leave_tids):
                            swap_candidates.append(SwapCandidate(
                                substitute_tid=cand_tid,
                                swap_day=swap_d,
                                swap_period=swap_p,
                                original_class=class_id,
                                substitute_class=substitute_class,
                                subject=subject
                            ))
        
        return swap_candidates
    
    def _can_swap(self, original_tid, from_slot, to_slot, 
                  from_class, to_class, substitute_tid, leave_tids):
        """
        检查是否可以将课程从from_slot调到to_slot
        
        Args:
            original_tid: 请假老师ID
            from_slot: (day, period) 原时段
            to_slot: (swap_day, swap_period) 目标时段
            from_class: 请假老师原课的班级
            to_class: 代课老师原课的班级
            substitute_tid: 代课老师ID
            leave_tids: 所有请假老师ID集合
        
        Returns:
            bool: 是否可以互换
        """
        swap_day, swap_period = to_slot
        
        # 条件1: 请假老师在新时间必须空闲（或也在请假列表中，那也不影响）
        # 如果请假老师本来就在请假，就不用检查他在新时段的情况
        if original_tid not in leave_tids:
            if (original_tid, swap_day, swap_period) in self.teacher_busy:
                return False
        
        # 条件2: 代课老师在新时间必须空闲
        if (substitute_tid, swap_day, swap_period) in self.teacher_busy:
            return False
        
        # 条件3: 请假老师原课的班级在新时间必须空闲
        if (from_class, swap_day, swap_period) in self.final_schedule:
            return False
        
        # 条件4: 代课老师原课的班级在原时间必须空闲（应该已经是空的，因为代课老师要去代课）
        # 这个条件实际上由代课操作保证，不需要额外检查
        
        return True
    
    def _select_best_swap(self, swap_candidates):
        """
        从多个互换方案中选择最优的
        
        优先级：
        1. 同一天内的互换（减少跨天影响）
        2. 相邻节次的互换
        3. 较早的时间slot
        
        Returns:
            SwapCandidate: 最优方案
        """
        if not swap_candidates:
            return None
        
        # 优先选择同一天的互换方案
        # 这里假设所有候选都是针对同一个请假课程的
        # 所以我们可以直接排序
        
        # 按照：同一天 > 相邻节次 > 较早时间排序
        def score_swap(swap):
            same_day_bonus = 0 if swap.swap_day == 0 else 100  # 假设请假是第0天，实际需要传参
            proximity = abs(swap.swap_day * 10 + swap.swap_period)
            return same_day_bonus + proximity
        
        # 简单返回第一个候选（后续可以优化排序逻辑）
        return swap_candidates[0]
    
    def _execute_swap(self, swap, original_day, original_period, 
                     original_class, original_tid, leave_tids):
        """
        执行课程互换
        
        Args:
            swap: SwapCandidate对象
            original_day: 请假课程的日期
            original_period: 请假课程的节次
            original_class: 请假课程的班级
            original_tid: 请假老师ID
            leave_tids: 所有请假老师ID集合
        """
        # 步骤1: 代课老师去原班级上课（代课）
        self.final_schedule[(original_class, original_day, original_period)]['teacher_id'] = swap.substitute_tid
        self.final_schedule[(original_class, original_day, original_period)]['teacher_name'] = self.id_to_name[swap.substitute_tid]
        self.final_schedule[(original_class, original_day, original_period)]['is_sub'] = True
        self.teacher_busy.add((swap.substitute_tid, original_day, original_period))
        
        # 步骤2: 代课老师原课程移到新时段
        # 创建新的课程记录
        self.final_schedule[(swap.substitute_class, swap.swap_day, swap.swap_period)] = {
            "subject": swap.subject,
            "teacher_id": swap.substitute_tid,
            "teacher_name": self.id_to_name[swap.substitute_tid],
            "is_sub": True  # 标记为调整过的课程
        }
        self.teacher_busy.add((swap.substitute_tid, swap.swap_day, swap.swap_period))
        
        # 步骤3: 从原时段移除代课老师的课程
        if (swap.substitute_class, original_day, original_period) in self.final_schedule:
            old_tid = self.final_schedule[(swap.substitute_class, original_day, original_period)]['teacher_id']
            self.teacher_busy.discard((old_tid, original_day, original_period))

    def move_course(self, class_id, from_slot, to_slot):
        """
        手动移动/交换同一班级内的两节课
        
        Args:
            class_id: 班级ID (str)
            from_slot: tuple (day, period) 源位置
            to_slot: tuple (day, period) 目标位置
            
        Returns:
            dict: {"success": bool, "message": str}
        """
        from_day, from_period = from_slot
        to_day, to_period = to_slot
        
        # 0. 验证是否是同一个位置
        if from_slot == to_slot:
            return {"success": False, "message": "源位置和目标位置相同"}
            
        # 1. 获取课程信息
        source_key = (class_id, from_day, from_period)
        target_key = (class_id, to_day, to_period)
        
        source_info = self.final_schedule.get(source_key)
        target_info = self.final_schedule.get(target_key)
        
        if not source_info:
            return {"success": False, "message": "源位置没有课程"}
            
        source_tid = source_info['teacher_id']
        source_tname = source_info['teacher_name']
        
        # 2. 区分移动还是交换
        if not target_info:
            # === 情况A: 移动到空位 ===
            
            # 检查源老师在目标时间是否忙碌
            # 注意：如果源老师在目标时间忙碌，说明他在其他班级有课
            if (source_tid, to_day, to_period) in self.teacher_busy:
                return {"success": False, "message": f"{source_tname}在周{to_day+1}第{to_period+1}节已有其他课"}
                
            # 执行移动
            # 1. 在目标位置添加课程
            self.final_schedule[target_key] = source_info.copy()
            # 标记为调整过
            self.final_schedule[target_key]['is_sub'] = True 
            
            # 2. 从源位置删除课程
            del self.final_schedule[source_key]
            
            # 3. 更新忙碌集合
            self.teacher_busy.discard((source_tid, from_day, from_period))
            self.teacher_busy.add((source_tid, to_day, to_period))
            
            return {"success": True, "message": "移动成功"}
            
        else:
            # === 情况B: 交换两节课 ===
            target_tid = target_info['teacher_id']
            target_tname = target_info['teacher_name']
            
            # 检查冲突
            # 1. 检查源老师 -> 去目标时间 (排除掉目标位置目前的课，因为我们要把那个位置换走)
            # 实际上只要检查老师是否在目标时间*除了本班*以外还有课
            # 但简单起见，我们直接检查teacher_busy，因为teacher_busy肯定包含target_tid在target_time的记录
            # 等等，teacher_busy存的是(tid, day, period)
            
            # 如果源老师和目标老师是同一个人（比如同一门课或者同一个老师教两门课），那么肯定可以交换
            if source_tid == target_tid:
                # 即使是同一个人，也需要更新final_schedule
                self.final_schedule[source_key] = target_info
                self.final_schedule[target_key] = source_info
                return {"success": True, "message": "交换成功(同一老师)"}
            
            # 检查源老师在目标时间是否忙碌（他在其他班级有课吗？）
            if (source_tid, to_day, to_period) in self.teacher_busy:
                return {"success": False, "message": f"{source_tname}在周{to_day+1}第{to_period+1}节已有其他课"}
                
            # 检查目标老师在源时间是否忙碌
            if (target_tid, from_day, from_period) in self.teacher_busy:
                return {"success": False, "message": f"{target_tname}在周{from_day+1}第{from_period+1}节已有其他课"}

            # 执行交换
            self.final_schedule[source_key] = target_info
            self.final_schedule[target_key] = source_info
            
            # 标记调整
            self.final_schedule[source_key]['is_sub'] = True
            self.final_schedule[target_key]['is_sub'] = True
            
            # 更新忙碌集合
            # 源老师: from -> to
            self.teacher_busy.discard((source_tid, from_day, from_period))
            self.teacher_busy.add((source_tid, to_day, to_period))
            
            # 目标老师: to -> from
            self.teacher_busy.discard((target_tid, to_day, to_period))
            self.teacher_busy.add((target_tid, from_day, from_period))
            
            return {"success": True, "message": "交换成功"}

