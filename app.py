from flask import Flask, jsonify, request, render_template, send_file, session, redirect, url_for
from flask_cors import CORS
import logging
import json
import os
import normal
import substitution
from database import ScheduleDatabase
from export_excel import ExcelExporter
from error_handler import analyze_failure
from openai import OpenAI

# 从环境变量获取 API Key (安全性优化)
_dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "sk-6946f8148ef84f95afeb03ae7a4aa0b1")

# 配置 Qwen 客户端 (阿里云 DashScope)
qwen_client = OpenAI(
    api_key=_dashscope_api_key, 
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 配置日志系统
logging.basicConfig(
    filename='schedule_system.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'delushan_schedule_system_secret_key' # 生产环境请修改
CORS(app)

# 初始化存储模块 (SQLite)
storage = ScheduleDatabase()
# 初始化Excel导出模块
exporter = ExcelExporter()

import uuid

# 初始化存储模块 (SQLite)
storage = ScheduleDatabase()
# 初始化Excel导出模块
exporter = ExcelExporter()

# 会话存储: { schedule_id: { 'system': ..., 'result': ... } }
SCHEDULE_SESSIONS = {}

def serialize_schedule(system):
    formatted_data = {}
    for c_id in system.classes:
        formatted_data[c_id] = {}
        for p in range(system.periods):
            formatted_data[c_id][p] = {}
            for d in range(system.days):
                info = system.final_schedule.get((c_id, d, p))
                if info:
                    # === [核心修复] 移除内部后缀 ===
                    display_subject = info['subject'].replace('_AUTO_SUB', '')
                    # ============================
                    
                    cell_data = {
                        "subject": display_subject, # 使用处理后的名字
                        "teacher_name": info['teacher_name'],
                        "teacher_id": info.get('teacher_id'),
                        "is_sub": info['is_sub'],
                        "course_type": info.get('course_type', 'minor')
                    }
                    if 'room' in info:
                        cell_data['room'] = info['room']
                else:
                    cell_data = None
                formatted_data[c_id][p][d] = cell_data
    return formatted_data

def serialize_teacher_schedule(system, teacher_name):
    """按老师视角序列化课表"""
    # 构建老师课表矩阵：periods x days
    teacher_data = {}
    for p in range(system.periods):
        teacher_data[p] = {}
        for d in range(system.days):
            teacher_data[p][d] = None
    
    # 遍历所有班级的所有时段
    for c_id in system.classes:
        for p in range(system.periods):
            for d in range(system.days):
                info = system.final_schedule.get((c_id, d, p))
                if info and info['teacher_name'] == teacher_name:
                    # === [核心修复] 移除内部后缀 ===
                    display_subject = info['subject'].replace('_AUTO_SUB', '')
                    # ============================
                    
                    teacher_data[p][d] = {
                        "class_id": str(c_id),
                        "subject": display_subject, # 使用处理后的名字
                        "is_sub": info['is_sub']
                    }
    
    return teacher_data


@app.route('/login')
def login_page():
    if 'user' in session:
        return redirect('/')
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        # 简单模拟验证 (生产环境应查询数据库)
        if username == 'admin' and password == 'admin':
            session['user'] = {'id': 1, 'name': '管理员'}
            session.permanent = True
            return jsonify({
                "status": "success",
                "message": "登录成功",
                "user": {"id": 1, "name": "管理员"}
            })
        else:
            return jsonify({
                "status": "error", 
                "message": "账号或密码错误"
            }), 401
            
    except Exception as e:
        logger.error(f"登录异常: {str(e)}")
        return jsonify({"status": "error", "message": "服务器内部错误"}), 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/login')

@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    return render_template('index.html')

@app.route('/api/init', methods=['POST'])
def init_schedule():
    global global_result, global_system
    
    # 接收完整配置
    # 格式: { "num_classes": 10, "courses": {...}, "teacher_names": {"语文": ["张三"], ...} }
    config = request.json if request.json else {}
    
    logger.info(f"接收到排课请求 - 班级数: {config.get('num_classes')}, 科目数: {len(config.get('courses', {}))}")
    logger.info(f"自定义老师科目: {list(config.get('teacher_names', {}).keys())}")

    try:
        result = normal.run_scheduler(config)
        
        if result['status'] != 'success':
            # 如果 result 已经包含了具体的错误信息(由 normal.py 预检逻辑返回)
            if 'error_type' in result:
                logger.warning(f"排课拦截 - {result['error_type']}: {result['message']}")
                return jsonify({
                    "status": "error",
                    "error_type": result['error_type'],
                    "message": result['message'],
                    "suggestions": result.get('suggestions', [])
                }), 400
                
            # 否则执行通用故障分析
            error_analysis = analyze_failure(config)
            logger.warning(f"排课失败 - {error_analysis['error_type']}: {error_analysis['message']}")
            
            return jsonify({
                "status": "error",
                "error_type": error_analysis['error_type'],
                "message": error_analysis['message'],
                "suggestions": error_analysis['suggestions']
            }), 400
            
        schedule_id = str(uuid.uuid4())
        
        # 创建系统实例
        system_instance = substitution.SubstitutionSystem(result)
        
        # 存入会话
        SCHEDULE_SESSIONS[schedule_id] = {
            'result': result,
            'system': system_instance
        }
        
        teacher_list = sorted([{
            "id": t['id'], 
            "name": t['name'],
            "subject": t.get('subject', ''),
            "type": t.get('type', 'minor')
        } for t in result['teachers_db']], key=lambda x: x['name'])
        
        logger.info(f"排课成功 [{schedule_id}] - 生成 {len(system_instance.classes)} 个班级的课表")
        
        return jsonify({
            "status": "success", 
            "schedule_id": schedule_id,
            "teachers": teacher_list,
            "schedule": serialize_schedule(system_instance),
            "stats": result.get('stats', {}),
            "class_names": result.get('class_names', {}), # [新增]
            "sharding_info": result.get('sharding_info', []), # [新增]
            "evaluation": result.get('evaluation', {'score': 100, 'details': []})
        })
    except Exception as e:
        logger.error(f"排课异常: {str(e)}", exc_info=True)
        
        # 尝试分析错误
        error_analysis = analyze_failure(config)
        
        return jsonify({
            "status": "error",
            "error_type": "system_error",
            "message": f"系统错误: {str(e)}",
            "suggestions": error_analysis['suggestions']
        }), 500


@app.route('/api/schedule/move', methods=['POST'])
def move_course():
    """手动移动/交换课程"""
    data = request.json
    schedule_id = data.get('schedule_id')
    
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    if not session_data:
        return jsonify({"status": "error", "message": "会话无效或已过期"}), 400
        
    global_system = session_data['system']

    try:
        
        # =========== 🔴 核心修复开始 ===========
        raw_class_id = data.get('class_id')
        try:
            # 尝试将 ID 转为整数 (因为 normal.py 生成的是 int: 1, 2, 3...)
            class_id = int(raw_class_id)
        except (ValueError, TypeError):
            # 如果转换失败（比如本来就是"HighSchool-1"这种字符串），则保持原样
            class_id = str(raw_class_id)
        # =========== 🔴 核心修复结束 ===========

        from_slot = tuple(data.get('from_slot'))
        to_slot = tuple(data.get('to_slot'))
        
        result = global_system.move_course(class_id, from_slot, to_slot)
        
        if result['success']:
            return jsonify({
                "status": "success",
                "message": result['message'],
                "schedule": serialize_schedule(global_system)
            })
        else:
            return jsonify({
                "status": "error",
                "message": result['message']
            }), 400
            
    except Exception as e:
        logger.error(f"调课异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/restore', methods=['POST'])
def restore_schedule():
    """恢复课表状态 (用于前端 Undo/Redo)"""
    data = request.json
    schedule_id = data.get('schedule_id')

    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    if not session_data:
        return jsonify({"status": "error", "message": "会话无效或已过期"}), 400
        
    global_system = session_data['system']

    try:
        schedule_data = data.get('schedule')
        
        if not schedule_data:
            return jsonify({"status": "error", "message": "无效的课表数据"}), 400
            
        # 重建 final_schedule
        # 前端格式: class_id -> p -> d -> info
        new_final = {}
        # =========== 🔴 核心修复：遍历 JSON 键时转为 int ===========
        for c_id_raw, periods in schedule_data.items():
            # JSON 的键永远是字符串，这里必须尝试转回 int
            # 因为 normal.py 里的 classes 是 int (1, 2, 3...)
            try:
                c_id = int(c_id_raw)
            except (ValueError, TypeError):
                c_id = c_id_raw # 如果原本就是字符串（如"高一1班"），保持原样

            for p_str, days in periods.items():
                p = int(p_str)
                for d_str, info in days.items():
                    d = int(d_str)
                    if info:
                        # 确保 info 里面也有 teacher_id (依赖 serialize_schedule 的正确性)
                        new_final[(c_id, d, p)] = info
        # ========================================================
        
        global_system.final_schedule = new_final
        
        # === 重建 teacher_busy 索引 ===
        global_system.teacher_busy = set()
        for (key, info) in new_final.items():
            # key 是 (class_id, day, period)
            c, d, p = key
            tid = info.get('teacher_id')
            if tid:
                global_system.teacher_busy.add((tid, d, p))
        
        return jsonify({"status": "success", "message": "状态已恢复"})
        
    except Exception as e:
        logger.error(f"恢复状态异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# ============ 数据持久化接口 ============

@app.route('/api/save', methods=['POST'])
def save_schedule():
    """保存当前课表方案"""
    data = request.json
    schedule_id = data.get('schedule_id')
    
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    if not session_data:
        return jsonify({"status": "error", "message": "没有可保存的课表(会话过期)"}), 400
        
    global_system = session_data['system']
    global_result = session_data['result']
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({"status": "error", "message": "请提供方案名称"}), 400
    
    # 准备保存数据
    schedule_data = {
        "schedule": serialize_schedule(global_system),
        "teachers": sorted([{"id": t['id'], "name": t['name']} for t in global_result['teachers_db']], 
                          key=lambda x: x['name'])
    }
    
    config = data.get('config', {})
    
    result = storage.save_schedule(name, schedule_data, config)
    return jsonify(result)

@app.route('/api/load/<name>', methods=['GET'])
def load_schedule(name):
    """加载课表方案"""
    global global_result, global_system
    
    result = storage.load_schedule(name)
    
    if result['status'] == 'success':
        data = result['data']
        
        # 每次加载都创建一个新的隔离会话，用于导出或查看
        # 注意：这里我们只能创建一个"空壳"或"伪造"的 context，因为没有 Solver 状态
        # 但为了 API 兼容 (如 export 需要 system 对象), 我们尽力而为
        
        schedule_id = str(uuid.uuid4())
        # 这里比较棘手，因为 Serialization 丢失了 model 对象。
        # 如果只是为了由 load -> export，我们可以构造一个 Dummy System
        # 目前先存一个空的 system，如果后续操作需要 full system 可能会报错
        # 但前端通常加载后是看，或者点击"初始化"重新排。
        
        # 不过，为了让前端拿到 ID，我们还是生成一个
        # 将被加载的数据作为 Payload
        
        return jsonify({
            "status": "success",
            "message": f"方案 '{name}' 加载成功",
            "schedule_id": schedule_id, # 虽然是个空壳ID，但前端需要
            "schedule": data.get("schedule", {}),
            "config": data.get("config", {})
        })
    else:
        return jsonify(result), 400
    


@app.route('/api/list', methods=['GET'])
def list_schedules():
    """列出所有已保存的课表方案"""
    result = storage.list_schedules()
    return jsonify(result)



@app.route('/api/delete', methods=['POST'])
def delete_schedule():
    """删除指定的课表方案 - 增强版"""
    try:
        # 1. 安全获取 JSON 数据
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"status": "error", "message": "请求数据格式错误(Expecting JSON)"}), 400
            
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({"status": "error", "message": "请提供方案名称"}), 400
        
        # 2. 调用存储模块
        result = storage.delete_schedule(name)
        
        # 3. 根据结果返回状态码
        if result["status"] == "success":
            return jsonify(result), 200
        else:
            # 如果文件不存在，也可以算作 404，或者 400
            return jsonify(result), 400
            
    except Exception as e:
        # 4. 捕获所有未预料的错误，防止服务器崩溃返回 HTML
        logger.error(f"删除方案接口异常: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error", 
            "message": f"服务器内部错误: {str(e)}"
        }), 500

# ============ Excel导出接口 ============

@app.route('/api/export/class/<class_id>', methods=['GET'])
def export_class(class_id):
    """导出指定班级的课表为Excel"""
    schedule_id = request.args.get('schedule_id')
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    
    if not session_data:
        return jsonify({"status": "error", "message": "会话无效或已过期"}), 400
        
    global_system = session_data['system']
    
    try:
        schedule_data = serialize_schedule(global_system)
        excel_file = exporter.export_class_schedule(schedule_data, class_id)
        
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{class_id}班课表.xlsx'
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/export/all_classes', methods=['GET'])
def export_all_classes():
    """导出所有班级的课表为Excel（多sheet）"""
    schedule_id = request.args.get('schedule_id')
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    
    if not session_data:
        return jsonify({"status": "error", "message": "会话无效或已过期"}), 400
        
    global_system = session_data['system']
    
    try:
        schedule_data = serialize_schedule(global_system)
        excel_file = exporter.export_all_classes(schedule_data)
        
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='全部班级课表.xlsx'
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/export/teacher/<teacher_name>', methods=['GET'])
def export_teacher(teacher_name):
    """导出指定老师的课表为Excel"""
    schedule_id = request.args.get('schedule_id')
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    
    if not session_data:
        return jsonify({"status": "error", "message": "会话无效或已过期"}), 400
    
    global_system = session_data['system']
    global_result = session_data['result']
    
    try:
        schedule_data = serialize_schedule(global_system)
        teachers_db = global_result['teachers_db']
        excel_file = exporter.export_teacher_schedule(schedule_data, teachers_db, teacher_name)
        
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'{teacher_name}的课表.xlsx'
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ============ 老师视图接口 ============

@app.route('/api/teacher_view', methods=['POST'])
def get_teacher_view():
    """获取指定老师的课表视图"""
    data = request.json
    schedule_id = data.get('schedule_id')
    
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    if not session_data:
        # 特殊情况：如果只是查看，允许没有 session (可能)
        # 但为了统一，还是报错
        return jsonify({"status": "error", "message": "会话无效或已过期"}), 400
    
    global_system = session_data['system']
    teacher_name = data.get('teacher_name', '').strip()
    
    if not teacher_name:
        return jsonify({"status": "error", "message": "请提供老师姓名"}), 400
    
    try:
        teacher_schedule = serialize_teacher_schedule(global_system, teacher_name)
        
        return jsonify({
            "status": "success",
            "teacher_name": teacher_name,
            "schedule": teacher_schedule
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/substitute', methods=['POST'])
def apply_substitute():
    # 1. 获取请求数据
    data = request.json
    schedule_id = data.get('schedule_id')
    
    # 2. 从会话中获取数据 (完全替代 global)
    session_data = SCHEDULE_SESSIONS.get(schedule_id)
    if not session_data:
        return jsonify({"status": "error", "message": "会话已过期，请重新点击'一键生成'或'加载'。"}), 400
        
    current_system = session_data.get('system')
    current_result = session_data.get('result')

    # 前端发来的请假数据
    leave_requests = data.get('leaves', [])
        
    try:
        # 如果 system 对象还没初始化 (可能是从文件加载的情况)，尝试重建
        if current_system is None and current_result:
            current_system = substitution.SubstitutionSystem(current_result)
            session_data['system'] = current_system # 更新回去
        
        if not current_system:
             return jsonify({"status": "error", "message": "系统状态异常，请重新排课"}), 400

        # 3. 调用代课逻辑
        stats = current_system.process_leaves(leave_requests)
        
        # 4. 构建日志信息
        logs = []
        for (c, d, p), info in sorted(current_system.final_schedule.items()):
            if info.get('is_sub'):
                day_name = ["周一", "周二", "周三", "周四", "周五"][d]
                if info['teacher_name'] == "【自习】":
                    logs.append({
                        "type": "self_study",
                        "message": f"✗ {c}班 {day_name}第{p+1}节 标记为自习"
                    })
                else:
                    logs.append({
                        "type": "substitute",
                        "message": f"✓ {c}班 {day_name}第{p+1}节 {info['teacher_name']}代课"
                    })
        
        logger.info(f"代课处理完成 - 直接代课:{stats['direct']}次, 互换:{stats['swap']}次, 自习:{stats['self_study']}次")
        
        # === [修改] 重新构建老师列表，防止前端下拉框消失 ===
        # 从 current_result 中获取原始老师数据
        teacher_list = []
        if current_result and 'teachers_db' in current_result:
            teacher_list = sorted([{
                "id": t['id'], 
                "name": t['name'],
                "subject": t.get('subject', ''),
                "type": t.get('type', 'minor')
            } for t in current_result['teachers_db']], key=lambda x: x['name'])
        # =================================================

        return jsonify({
            "status": "success",
            "schedule": serialize_schedule(current_system),
            "stats": stats,
            "logs": logs,
            "teachers": teacher_list
        })
    except Exception as e:
        logger.error(f"代课处理异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"服务器错误: {str(e)}"}), 500

# ============ AI 规则生成接口 ============
@app.route('/api/ai_rule_gen', methods=['POST'])
def ai_generate_rule():
    """使用 Qwen AI 将自然语言转换为排课规则 JSON (支持多条规则)"""
    try:
        data = request.json
        user_input = data.get('prompt')
        
        if not user_input:
            return jsonify({"status": "error", "message": "请输入描述"}), 400
        
        # 获取上下文信息（防止AI幻觉）
        current_context = data.get('context', {})
        subjects = current_context.get('subjects', [])
        grades = current_context.get('grades', [])
        teachers = current_context.get('teachers', [])  # 新增老师名单
        
        # --- 核心 Prompt 设计 (优化版：支持多规则) ---
        system_prompt = f"""
你是一个排课规则解析专家。请分析用户的自然语言需求，提取出一条或多条排课规则。

### 上下文信息
- 现有科目: {", ".join(subjects) if subjects else "语文, 数学, 英语, 物理, 化学等"}
- 现有年级: {", ".join(grades) if grades else "初一, 初二, 初三"}
- 现有老师: {", ".join(teachers[:20]) if teachers else "无"}
- 时间定义: 
  - 周一到周五对应 day: 0, 1, 2, 3, 4
  - 第1节到第8节对应 period: 0 到 7 (其中0-3为上午, 4-7为下午)

### 支持的规则类型 (type)
1. FORBIDDEN_SLOTS - 时段禁排 (某人/某课在特定时间不能排)
2. ZONE_COUNT - 区域课时 (某课在某时段区域内必须排多少节)
3. SPECIAL_DAYS - 特定日禁排 (某人/某课某几天完全不排)
4. CONSECUTIVE - 连堂限制 (不要连堂)

### 你的任务
请返回一个 JSON 数组 (Array)，数组中包含一个或多个规则对象。
不要包含 Markdown 格式 (如 ```json)。
如果用户提到"上午"，slots需包含该日 period 0,1,2,3。
如果用户提到"下午"，slots需包含该日 period 4,5,6,7。
权重 (weight) 默认设为 100。

### 输出示例
用户输入: "语文上午排，体育不要排第一节"
你的输出:
[
  {{"type": "ZONE_COUNT", "targets": {{"subjects": ["语文"]}}, "params": {{"slots": [[0,0],[0,1],[0,2],[0,3],[1,0],[1,1],[1,2],[1,3],[2,0],[2,1],[2,2],[2,3],[3,0],[3,1],[3,2],[3,3],[4,0],[4,1],[4,2],[4,3]], "count": 5, "relation": ">="}}, "weight": 80}},
  {{"type": "FORBIDDEN_SLOTS", "targets": {{"subjects": ["体育"]}}, "params": {{"slots": [[0,0], [1,0], [2,0], [3,0], [4,0]]}}, "weight": 100}}
]
"""

        # 调用 Qwen-Plus
        completion = qwen_client.chat.completions.create(
            model="qwen-plus", 
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_input}
            ],
            temperature=0.1
        )
        
        # 解析返回内容
        ai_content = completion.choices[0].message.content
        # 清理可能存在的 Markdown 格式
        ai_content = ai_content.replace('```json', '').replace('```', '').strip()
        
        result_data = json.loads(ai_content)
        
        # 兼容性处理：如果 AI 返回单个对象，包装成数组
        if isinstance(result_data, dict):
            rules_list = [result_data]
        elif isinstance(result_data, list):
            rules_list = result_data
        else:
            raise ValueError("AI 返回格式既不是字典也不是列表")
        
        logger.info(f"AI 生成规则成功，共 {len(rules_list)} 条: {rules_list}")
        
        return jsonify({
            "status": "success",
            "rules": rules_list  # 返回数组
        })

    except json.JSONDecodeError as e:
        logger.error(f"AI 返回的 JSON 解析失败: {str(e)}")
        return jsonify({"status": "error", "message": f"AI 返回格式错误，请重试"}), 500
    except Exception as e:
        logger.error(f"AI 生成规则失败: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"解析失败: {str(e)}"}), 500

@app.route('/api/import_config', methods=['POST'])
def import_config():
    """导入Excel配置"""
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "未上传文件"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "文件名为空"}), 400
    
    try:
        import pandas as pd
        df = pd.read_excel(file)
        
        # 预期列名: 科目, 每周节数, 课程类型, 老师名单, 教室限制
        courses = {}
        resources = []
        
        # 归一化列名 (去除空格)
        df.columns = [str(c).strip() for c in df.columns]
        
        for _, row in df.iterrows():
            subject = str(row.get('科目', '')).strip()
            # 跳过空行或 'nan'
            if not subject or subject.lower() == 'nan': continue
            
            try:
                # 支持 float 类型的 "2.0"
                count = int(float(row.get('每周节数', 0)))
            except:
                count = 0
                
            c_type_raw = str(row.get('课程类型', 'main')).strip().lower()
            c_type = 'minor' if c_type_raw in ['副科', 'minor'] else 'main'
            
            teachers_str = str(row.get('老师名单', '')).strip()
            if teachers_str.lower() == 'nan': teachers_str = ''
            teachers = [t.strip() for t in teachers_str.replace('，', ',').split(',') if t.strip()]
            
            room = str(row.get('教室限制', '')).strip()
            if room.lower() == 'nan': room = ''
            
            courses[subject] = {
                "count": count,
                "type": c_type,
                "teachers": teachers
            }
            
            if room:
                exists = False
                for r in resources:
                    if r['name'] == room:
                        if subject not in r['subjects']:
                            r['subjects'].append(subject)
                        exists = True
                        break
                if not exists:
                    resources.append({
                        "name": room,
                        "capacity": 1,
                        "subjects": [subject]
                    })
                    
        return jsonify({
            "status": "success", 
            "message": f"成功导入 {len(courses)} 个科目配置",
            "courses": courses,
            "resources": resources
        })
        
    except Exception as e:
        logger.error(f"导入配置异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=8015)
    