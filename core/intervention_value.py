# -*- coding: utf-8 -*-
"""🎯 AI干预价值 — 判断「这个学员现在是否值得占用老师的人工服务时间」

新增 AI 内部决策指标「干预价值」（0-100），不再机械等于 P1-P4。
综合：风险等级 + 风险分 + 趋势 + 沟通间隔 + 最近沟通结果 + 历史跟进效果
    + 任务状态/逾期/升级 + 数据完整度。

==== 设计原则（不可违反）====
1. 纯规则打分（零大模型调用），透明可追溯，每一条加减分都引用真实数据
2. 只读 student / task 数据，绝不回写原始风险分层/风险分
3. 无数据时不加减分，并在依据中明确标注，禁止编造
4. 数据不完整（存在缺失维度）时给干预价值打折：先补齐数据再谈人工投入
"""

# 趋势取值集合（与 agent_decision 保持一致，本模块自包含避免循环依赖）
_DOWN_TRENDS = ("下降", "波动", "下滑", "退步", "恶化")
_UP_TRENDS = ("上升", "回升", "提升", "进步", "改善")
_NA_VALUES = ("暂无数据", "-", "", None)

# 分层基准分（P1 最高，P4 无干预价值）
_TIER_POINTS = {"P1": 40, "P2": 28, "P3": 16, "P4": 0}


def _clean(v):
    return (str(v).strip() if v is not None else "")


def _is_down(trend) -> bool:
    return any(k in _clean(trend) for k in _DOWN_TRENDS) if trend else False


def _is_up(trend) -> bool:
    return any(k in _clean(trend) for k in _UP_TRENDS) if trend else False


def compute_intervention_value(student: dict, task: dict = None) -> dict:
    """计算单一学员的「AI干预价值」。

    Args:
        student: analysis_result["students"] 中的学员 dict（分层/流失风险分/成绩趋势/沟通间隔天数/缺失维度）
        task: task_engine 任务对象（可选，含 任务状态/升级标记/沟通结果历史）
    Returns:
        {"价值分": int(0-100), "价值等级": "高|中|低", "依据": [str]}
    """
    student = student or {}
    task = task or {}

    tier = _clean(student.get("分层")) or "P4"
    if tier not in _TIER_POINTS:
        tier = "P4"
    score = student.get("流失风险分")
    trend = _clean(student.get("成绩趋势"))
    comm_gap = student.get("沟通间隔天数")
    missing = student.get("缺失维度") or []
    if not isinstance(missing, (list, tuple)):
        missing = []

    value = 0
    basis = []

    # 1. 风险等级
    tier_pt = _TIER_POINTS[tier]
    value += tier_pt
    basis.append(f"风险等级 {tier}（+{tier_pt}）")

    # 2. 风险分（0-20，按比例）
    if isinstance(score, (int, float)):
        sp = round(min(max(float(score), 0.0), 100.0) / 100.0 * 20)
        value += sp
        basis.append(f"风险分 {int(score)}（+{sp}）")
    else:
        basis.append("风险分暂无数据（不加减分）")

    # 3. 趋势
    down, up = _is_down(trend), _is_up(trend)
    if down:
        value += 12
        basis.append(f"成绩趋势「{trend}」持续恶化（+12）")
    elif up:
        value -= 8
        basis.append(f"成绩趋势「{trend}」已回升（-8）")
    elif trend and trend not in _NA_VALUES:
        basis.append(f"成绩趋势「{trend}」平稳（不加分）")

    # 4. 沟通间隔（长时间未沟通 → 更值得投入）
    if comm_gap is None:
        basis.append("沟通间隔暂无数据（不加分）")
    elif isinstance(comm_gap, (int, float)) and comm_gap >= 15:
        value += 6
        basis.append(f"已 {int(comm_gap)} 天未有效沟通（+6）")
    elif isinstance(comm_gap, (int, float)) and comm_gap >= 8:
        value += 3
        basis.append(f"已 {int(comm_gap)} 天未沟通（+3）")
    else:
        basis.append(f"沟通间隔 {_clean(comm_gap)} 天，近期有沟通（不加分）")

    # 5. 任务态：逾期/升级加分；最近沟通结果修正
    status = _clean(task.get("任务状态"))
    escalated = bool(task.get("升级标记"))
    if status == "已超时" or escalated:
        value += 8
        basis.append("任务已超时或已重点升级（+8）")
    comm_history = task.get("沟通结果历史") or []
    last_result = _clean(comm_history[-1].get("结果")) if comm_history else ""
    if last_result in ("暂无改善", "未接通", "家长仍存在疑虑"):
        value += 6
        basis.append(f"最近跟进结果「{last_result}」，问题未解决（+6）")
    elif last_result in ("已解决", "已成功沟通"):
        value -= 8
        basis.append(f"最近跟进结果「{last_result}」已解决（-8）")

    # 6. 数据完整度（缺数据 → 干预价值打折，先收集数据）
    if missing:
        value -= 6
        basis.append(f"存在 {len(missing)} 项缺失维度，数据不完整（-6）")

    value = max(0, min(100, value))
    level = "高" if value >= 70 else ("中" if value >= 40 else "低")
    basis.append(f"综合干预价值 {value} 分（{level}）")

    return {"价值分": value, "价值等级": level, "依据": basis}