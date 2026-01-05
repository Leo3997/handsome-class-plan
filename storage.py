"""
课表数据存储模块
提供课表的保存、加载、列出和删除功能
"""
import json
import os
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ScheduleStorage:
    def __init__(self, storage_dir="saved_schedules"):
        """初始化存储模块
        
        Args:
            storage_dir: 存储目录路径，默认为 saved_schedules
        """
        self.storage_dir = Path(storage_dir)
        self._ensure_storage_dir()
    
    def _ensure_storage_dir(self):
        """确保存储目录存在"""
        if not self.storage_dir.exists():
            self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_file_path(self, name):
        """获取安全的文件路径
        
        Args:
            name: 方案名称
            
        Returns:
            Path对象
        """
        # 清理文件名，防止路径注入
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_', '中', '文')).strip()
        if not safe_name:
            safe_name = "unnamed"
        return self.storage_dir / f"{safe_name}.json"
    
    def save_schedule(self, name, schedule_data, config=None):
        """保存课表方案
        
        Args:
            name: 方案名称
            schedule_data: 课表数据字典
            config: 配置信息（可选）
            
        Returns:
            dict: 包含状态和消息的字典
        """
        try:
            file_path = self._get_file_path(name)
            
            # 构造保存数据
            save_data = {
                "name": name,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "schedule": schedule_data.get("schedule", {}),
                "teachers": schedule_data.get("teachers", []),
                "config": config or {}
            }
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=2)
            
            return {
                "status": "success",
                "message": f"课表方案 '{name}' 保存成功",
                "file_path": str(file_path)
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"保存失败: {str(e)}"
            }
    
    def load_schedule(self, name):
        """加载课表方案
        
        Args:
            name: 方案名称
            
        Returns:
            dict: 课表数据字典或错误信息
        """
        try:
            file_path = self._get_file_path(name)
            
            if not file_path.exists():
                return {
                    "status": "error",
                    "message": f"方案 '{name}' 不存在"
                }
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return {
                "status": "success",
                "data": data
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"加载失败: {str(e)}"
            }
    
    def list_schedules(self):
        """列出所有已保存的课表方案
        
        Returns:
            list: 方案信息列表
        """
        try:
            schedules = []
            
            for file_path in self.storage_dir.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    schedules.append({
                        "name": data.get("name", file_path.stem),
                        "created_at": data.get("created_at", "未知"),
                        "num_classes": len(data.get("schedule", {})),
                        "num_teachers": len(data.get("teachers", []))
                    })
                except Exception as e:
                    # 跳过损坏的文件
                    logger.warning(f"跳过损坏的文件 {file_path}: {e}")
                    continue
            
            # 按创建时间倒序排列
            schedules.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            
            return {
                "status": "success",
                "schedules": schedules
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"列出方案失败: {str(e)}",
                "schedules": []
            }
    
    def delete_schedule(self, name):
        """删除指定的课表方案
        
        Args:
            name: 方案名称
            
        Returns:
            dict: 包含状态和消息的字典
        """
        try:
            file_path = self._get_file_path(name)
            
            if not file_path.exists():
                return {
                    "status": "error",
                    "message": f"方案 '{name}' 不存在"
                }
            
            file_path.unlink()
            
            return {
                "status": "success",
                "message": f"方案 '{name}' 已删除"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"删除失败: {str(e)}"
            }
