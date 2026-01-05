from flask import Flask, jsonify, request, render_template, send_file
from flask_cors import CORS
import logging
import normal
import substitution
from storage import ScheduleStorage
from export_excel import ExcelExporter
from error_handler import analyze_failure

# 配置日志系统
logging.basicConfig(
    filename='schedule_system.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# 初始化存储模块
storage = ScheduleStorage()
# 初始化Excel导出模块
exporter = ExcelExporter()

global_result = None
global_system = None

def serialize_schedule(system):
    formatted_data = {}
    for c_id in system.classes:
        formatted_data[c_id] = {}
        for p in range(system.periods):
            formatted_data[c_id][p] = {}
            for d in range(system.days):
                info = system.final_schedule.get((c_id, d, p))
                if info:
                    cell_data = {
                        "subject": info['subject'],
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
                    teacher_data[p][d] = {
                        "class_id": str(c_id),
                        "subject": info['subject'],
                        "is_sub": info['is_sub']
                    }
    
    return teacher_data

@app.route('/')
def index():
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
            # 分析失败原因
            error_analysis = analyze_failure(config)
            
            logger.warning(f"排课失败 - {error_analysis['error_type']}: {error_analysis['message']}")
            
            return jsonify({
                "status": "error",
                "error_type": error_analysis['error_type'],
                "message": error_analysis['message'],
                "suggestions": error_analysis['suggestions']
            }), 400
            
        global_result = result
        global_system = substitution.SubstitutionSystem(result)
        
        teacher_list = sorted([{
            "id": t['id'], 
            "name": t['name'],
            "subject": t.get('subject', ''),
            "type": t.get('type', 'minor')
        } for t in result['teachers_db']], key=lambda x: x['name'])
        
        logger.info(f"排课成功 - 生成 {len(global_system.classes)} 个班级的课表,共 {len(teacher_list)} 位老师")
        
        return jsonify({
            "status": "success", 
            "teachers": teacher_list,
            "schedule": serialize_schedule(global_system),
            "stats": result.get('stats', {})
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

@app.route('/api/substitute', methods=['POST'])
def apply_substitute():
    global global_result, global_system
    if not global_result:
        return jsonify({"status": "error", "message": "请先生成课表"}), 400
    
    data = request.json
    leave_requests_raw = data.get('leaves', [])
    
    day_map = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4}
    processed_requests = []
    for req in leave_requests_raw:
        processed_requests.append({
            "name": req['name'],
            "days": [day_map[d] for d in req['days']]
        })
        
    try:
        global_system = substitution.SubstitutionSystem(global_result)
        
        # 捕获process_leaves的返回值（统计信息）
        stats = global_system.process_leaves(processed_requests)
        
        # 构建日志信息
        logs = []
        
        # 遍历课表，找出所有代课和调整的课程
        for (c, d, p), info in sorted(global_system.final_schedule.items()):
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
        
        return jsonify({
            "status": "success",
            "schedule": serialize_schedule(global_system),
            "stats": stats,
            "logs": logs
        })
    except Exception as e:
        logger.error(f"代课处理异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/schedule/move', methods=['POST'])
def move_course():
    """手动移动/交换课程"""
    global global_result, global_system
    if not global_result:
        return jsonify({"status": "error", "message": "请先生成课表"}), 400
        
    try:
        # 如果还没初始化system对象，先初始化
        if global_system is None:
            global_system = substitution.SubstitutionSystem(global_result)
            
        data = request.json
        
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
    global global_system
    
    if not global_system:
        return jsonify({"status": "error", "message": "系统未初始化"}), 400
        
    try:
        data = request.json
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
    global global_result, global_system
    
    if not global_result or not global_system:
        return jsonify({"status": "error", "message": "没有可保存的课表"}), 400
    
    data = request.json
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
        # 恢复全局状态
        # 注意: 这里我们需要重建 global_result 和 global_system
        # 但 storage 保存的是序列化后的数据，不是原始 Solver 变量
        # 所以我们只能恢复用于显示的数据，无法恢复 Solver 状态继续排课
        # 如果需要继续排课，用户需要基于加载的配置重新点击"初始化排课"
        
        # 临时构建一个模拟的 global_result 用于显示
        # 真正重要的是返回给前端的 schedule 和 config
        
        return jsonify({
            "status": "success",
            "message": f"方案 '{name}' 加载成功",
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
    global global_system
    
    if not global_system:
        return jsonify({"status": "error", "message": "没有可导出的课表"}), 400
    
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
    global global_system
    
    if not global_system:
        return jsonify({"status": "error", "message": "没有可导出的课表"}), 400
    
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
    global global_system, global_result
    
    if not global_system or not global_result:
        return jsonify({"status": "error", "message": "没有可导出的课表"}), 400
    
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
    global global_system
    
    if not global_system:
        return jsonify({"status": "error", "message": "没有可用的课表"}), 400
    
    data = request.json
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
    app.run(debug=True, port=5000)
    