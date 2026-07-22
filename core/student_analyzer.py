"""学生分析器 — 整合分层、排序、话术生成的完整流程"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.excel_parser import df_to_profiles, parse_uploaded_excel
from core.script_generator import batch_generate_scripts


def analyze_students(df) -> dict:
    """
    完整学情分析流程：
    1. 解析数据 → 2. 计算分层 → 3. 排序 → 4. 返回结构化结果
    """
    profiles = df_to_profiles(df)

    # 按优先级排序
    profiles.sort(key=lambda p: p.priority)

    # 分层统计
    tier_stats = {"S": 0, "A": 0, "B": 0, "C": 0}
    for p in profiles:
        tier_stats[p.tier] += 1

    # 转为字典列表
    profile_dicts = [p.to_dict() for p in profiles]

    return {
        "tier_stats": tier_stats,
        "total": len(profiles),
        "students": profile_dicts,
    }


def analyze_and_generate_scripts(df, generate: bool = True, progress_callback=None) -> dict:
    """
    学情分析 + 话术生成（可选）
    generate=False 时只做分层分析，不调用LLM（节省成本用于测试）
    """
    result = analyze_students(df)

    if generate:
        scripts = batch_generate_scripts(result["students"], progress_callback=progress_callback)
        # 将话术合并回学生数据
        script_map = {s["学生姓名"]: s["生成话术"] for s in scripts}
        for student in result["students"]:
            student["沟通话术"] = script_map.get(student["学生姓名"], "生成失败")

    return result
