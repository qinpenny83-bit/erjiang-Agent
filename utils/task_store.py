# -*- coding: utf-8 -*-
"""今日风险处理中心 — 任务持久化存储（JSON文件级）

目录：data/task_center/（首次运行自动创建，不报错）
文件：tasks_<文件名哈希>.json — 按上传的学情表分组存储，重传同一文件可恢复任务状态

隐私约定：JSON内容含真实学员姓名与学情数据，已在 .gitignore 排除，不进入版本库。
"""
import os
import json
import hashlib
from datetime import datetime

# 存储目录：项目根/data/task_center/
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE_DIR = os.path.join(_BASE_DIR, "data", "task_center")


def ensure_dir():
    """确保存储目录存在（首次运行自动创建）"""
    try:
        os.makedirs(STORE_DIR, exist_ok=True)
        # .gitkeep 让目录结构进入版本库（内容文件仍被 .gitignore 排除）
        gitkeep = os.path.join(STORE_DIR, ".gitkeep")
        if not os.path.exists(gitkeep):
            with open(gitkeep, "w", encoding="utf-8") as f:
                f.write("")
        return True
    except Exception as e:
        print(f"[TaskStore] 目录初始化失败（不影响应用运行，任务将仅保存在会话内）: {e}")
        return False


def _storage_key(file_name: str) -> str:
    """上传文件名 → 稳定存储键（同名文件重传可恢复任务状态）"""
    return hashlib.md5(str(file_name).encode("utf-8")).hexdigest()[:16]


def _task_file(file_name: str) -> str:
    return os.path.join(STORE_DIR, f"tasks_{_storage_key(file_name)}.json")


def load_tasks(file_name: str) -> list:
    """读取某学情表对应的任务列表；无记录/异常时返回空列表"""
    ensure_dir()
    path = _task_file(file_name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # 兼容带元信息的结构
            return data.get("tasks", [])
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"[TaskStore] 读取任务失败（将重新生成）: {e}")
        return []


def save_tasks(file_name: str, tasks: list) -> bool:
    """保存任务列表；失败时静默降级（会话内仍可用）"""
    ensure_dir()
    path = _task_file(file_name)
    try:
        payload = {
            "source_file": str(file_name),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "task_count": len(tasks),
            "tasks": tasks,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)  # 原子替换，避免写一半损坏
        return True
    except Exception as e:
        print(f"[TaskStore] 保存任务失败: {e}")
        return False


def clear_tasks(file_name: str) -> bool:
    """清空某文件的任务记录（谨慎调用）"""
    path = _task_file(file_name)
    try:
        if os.path.exists(path):
            os.remove(path)
        return True
    except Exception as e:
        print(f"[TaskStore] 清空任务失败: {e}")
        return False
