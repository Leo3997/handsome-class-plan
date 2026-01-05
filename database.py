import sqlite3
import json
import os
from pathlib import Path
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ScheduleDatabase:
    def __init__(self, db_path="schedule.db", json_dir="saved_schedules"):
        """初始化数据库连接和迁移
        
        Args:
            db_path: SQLite数据库路径
            json_dir: 旧版JSON文件存储目录(用于迁移)
        """
        self.db_path = db_path
        self.json_dir = Path(json_dir)
        self.init_db()
        self.migrate_from_json()

    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """初始化数据表"""
        try:
            with self.get_connection() as conn:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS schedules (
                        name TEXT PRIMARY KEY,
                        created_at TEXT,
                        updated_at TEXT,
                        schedule_data TEXT,
                        teachers_data TEXT,
                        config_data TEXT
                    )
                ''')
        except Exception as e:
            logger.error(f"Failed to init database: {e}")

    def migrate_from_json(self):
        """从旧版JSON文件迁移数据"""
        if not self.json_dir.exists():
            return
        
        migrated_count = 0
        for file_path in self.json_dir.glob("*.json"):
            try:
                # 检查是否已存在于库中 (避免重复迁移)
                name_stem = file_path.stem
                if self.exists(name_stem):
                    continue

                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                name = data.get("name", name_stem)
                created_at = data.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                
                # 构造并保存
                self.save_schedule(
                    name, 
                    {
                        "schedule": data.get("schedule", {}),
                        "teachers": data.get("teachers", [])
                    }, 
                    data.get("config", {}),
                    created_at=created_at # 保留原始创建时间
                )
                migrated_count += 1
            except Exception as e:
                logger.warning(f"Failed to migrate {file_path}: {e}")
        
        if migrated_count > 0:
            logger.info(f"Successfully migrated {migrated_count} schedules from JSON to SQLite.")

    def exists(self, name):
        """检查方案是否存在"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute('SELECT 1 FROM schedules WHERE name = ?', (name,))
                return cursor.fetchone() is not None
        except:
            return False

    def save_schedule(self, name, schedule_data, config=None, created_at=None):
        """保存课表方案"""
        try:
            if not created_at:
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 序列化各字段
            sched_json = json.dumps(schedule_data.get("schedule", {}), ensure_ascii=False)
            teachers_json = json.dumps(schedule_data.get("teachers", []), ensure_ascii=False)
            config_json = json.dumps(config or {}, ensure_ascii=False)

            with self.get_connection() as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO schedules 
                    (name, created_at, updated_at, schedule_data, teachers_data, config_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (name, created_at, updated_at, sched_json, teachers_json, config_json))
            
            return {
                "status": "success",
                "message": f"方案 '{name}' 保存成功"
            }
        except Exception as e:
            logger.error(f"Save schedule error: {e}")
            return {
                "status": "error",
                "message": f"保存失败: {str(e)}"
            }

    def load_schedule(self, name):
        """加载课表方案"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute('SELECT * FROM schedules WHERE name = ?', (name,))
                row = cursor.fetchone()
                
            if not row:
                return {
                    "status": "error",
                    "message": f"方案 '{name}' 不存在"
                }
            
            data = {
                "name": row['name'],
                "created_at": row['created_at'],
                "schedule": json.loads(row['schedule_data']),
                "teachers": json.loads(row['teachers_data']),
                "config": json.loads(row['config_data'])
            }
            
            return {
                "status": "success",
                "data": data
            }
        except Exception as e:
            logger.error(f"Load schedule error: {e}")
            return {
                "status": "error",
                "message": f"加载失败: {str(e)}"
            }

    def list_schedules(self):
        """列出所有方案"""
        try:
            schedules = []
            with self.get_connection() as conn:
                # 按更新时间倒序
                cursor = conn.execute('SELECT name, created_at, schedule_data, teachers_data FROM schedules ORDER BY updated_at DESC')
                for row in cursor:
                    try:
                        # 简单解析以获取统计信息
                        sched = json.loads(row['schedule_data'])
                        teachers = json.loads(row['teachers_data'])
                        
                        schedules.append({
                            "name": row['name'],
                            "created_at": row['created_at'],
                            "num_classes": len(sched),
                            "num_teachers": len(teachers)
                        })
                    except:
                        continue
            
            return {
                "status": "success",
                "schedules": schedules
            }
        except Exception as e:
            logger.error(f"List schedules error: {e}")
            return {
                "status": "error",
                "message": f"列出方案失败: {str(e)}",
                "schedules": []
            }

    def delete_schedule(self, name):
        """删除方案"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute('DELETE FROM schedules WHERE name = ?', (name,))
                if cursor.rowcount == 0:
                     return {
                        "status": "error",
                        "message": f"方案 '{name}' 不存在"
                    }
            
            return {
                "status": "success",
                "message": f"方案 '{name}' 已删除"
            }
        except Exception as e:
            logger.error(f"Delete schedule error: {e}")
            return {
                "status": "error",
                "message": f"删除失败: {str(e)}"
            }
