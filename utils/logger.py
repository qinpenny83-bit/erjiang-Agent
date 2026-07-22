"""数据采集日志器 — 用于A/B测试数据分析的自动埋点"""
import json
import os
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LOG_DIR


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_event(event_type: str, data: dict):
    """
    记录事件日志，用于A/B测试数据分析

    event_type:
    - "analysis_start": 开始学情分析
    - "analysis_end": 完成学情分析（含duration_s）
    - "qa_start": 开始答疑
    - "qa_end": 完成答疑（含duration_s）
    - "report_start": 开始报告生成
    - "report_end": 完成报告生成（含duration_s）
    - "manual_edit": 老师手动修改了生成内容
    - "export": 导出文件
    """
    ensure_log_dir()
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        **data,
    }
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"events_{date_str}.jsonl")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")


def get_daily_stats(date_str: str = None) -> dict:
    """获取某天的统计数据"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"events_{date_str}.jsonl")

    if not os.path.exists(log_file):
        return {"date": date_str, "total_events": 0}

    stats = {
        "date": date_str,
        "total_events": 0,
        "analysis_count": 0,
        "analysis_total_time_s": 0,
        "qa_count": 0,
        "qa_total_time_s": 0,
        "report_count": 0,
        "report_total_time_s": 0,
        "manual_edits": 0,
        "exports": 0,
    }

    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            stats["total_events"] += 1
            et = entry["event_type"]
            if et == "analysis_end":
                stats["analysis_count"] += 1
                stats["analysis_total_time_s"] += entry.get("duration_s", 0)
            elif et == "qa_end":
                stats["qa_count"] += 1
                stats["qa_total_time_s"] += entry.get("duration_s", 0)
            elif et == "report_end":
                stats["report_count"] += 1
                stats["report_total_time_s"] += entry.get("duration_s", 0)
            elif et == "manual_edit":
                stats["manual_edits"] += 1
            elif et == "export":
                stats["exports"] += 1

    return stats


def get_all_stats() -> list[dict]:
    """获取所有日期的统计数据"""
    ensure_log_dir()
    all_stats = []
    for filename in sorted(os.listdir(LOG_DIR)):
        if filename.startswith("events_") and filename.endswith(".jsonl"):
            date_str = filename.replace("events_", "").replace(".jsonl", "")
            all_stats.append(get_daily_stats(date_str))
    return all_stats
