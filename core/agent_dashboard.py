# -*- coding: utf-8 -*-
"""🏠 AI服务驾驶舱 — 统计逻辑（老板视角，纯计算，不含UI）

在 analysis_result（风险识别层）与 decisions（AI决策层）之上，
计算老板一眼可见的「AI今天替团队做了什么」，全部动态计算、不虚构。

关键指标：
- AI自动化率 = 无需老师人工介入的学员占比（AI自主处理+AI辅助处理）
- 人工介入率 = 需要老师今日人工联系/决策的学员占比
"""

from core import agent_decision as ad

# ============================================================
# 核心统计
# ============================================================

def compute_agent_stats(analysis_result: dict, tasks: list = None, decisions: list = None) -> dict:
    """老板视角运营统计。

    Args:
        analysis_result: 学情分析结果（含 students 与 tier_stats）
        tasks: task_engine 任务列表（可缺省）
        decisions: build_agent_tasks 的决策列表（可缺省，内部自动计算）
    Returns: 统计 dict
    """
    students = (analysis_result or {}).get("students", [])
    total = len(students)

    if decisions is None:
        decisions = ad.build_agent_tasks(analysis_result, tasks)

    buckets = ad.bucket_decisions(decisions)

    require_contact = buckets["立即处理"] + buckets["今日处理"]   # 需人工联系
    observe = buckets["持续观察"]                                  # AI辅助观察
    auto_track = buckets["AI自动跟踪"]                             # AI自主处理

    # 等级分布（来自学生分层，全量，不是任务侧）
    tier_counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    for s in students:
        t = str(s.get("分层", "P4"))
        if t in tier_counts:
            tier_counts[t] += 1

    # 任务侧执行状态
    tasks = tasks or []
    done = sum(1 for t in tasks if t.get("任务状态") in ("已完成", "已关闭"))
    pending = sum(1 for t in tasks if t.get("任务状态") == "待处理")
    overdue = sum(1 for t in tasks if t.get("任务状态") == "已超时")
    escalated = sum(1 for t in tasks if t.get("升级标记") and t.get("任务状态") != "已关闭")

    # 风险缓解：任务已关闭 或 AI复评风险方向==下降
    relieved = sum(
        1 for t in tasks
        if t.get("任务状态") == "已关闭"
        or (t.get("AI复评结果") or {}).get("风险方向") == "下降"
    )
    # 风险升级：AI复评风险方向==上升 或 连续未改善（升级提醒）
    escalated_by_reeval = sum(
        1 for t in tasks
        if (t.get("AI复评结果") or {}).get("风险方向") == "上升"
        or bool(ad.escalation_reason(t))
    )

    # ---- 自动化率 / 人工介入率 ----
    need_count = len(require_contact)
    human_rate = (need_count / total) if total else 0.0
    auto_rate = ((total - need_count) / total) if total else 0.0

    return {
        "总学员数": total,
        "等级分布": tier_counts,
        "风险学员数": tier_counts["P1"] + tier_counts["P2"] + tier_counts["P3"],
        "需人工介入": need_count,
        "立即处理": len(buckets["立即处理"]),
        "今日处理": len(buckets["今日处理"]),
        "持续观察": len(buckets["持续观察"]),
        "AI自动跟踪": len(buckets["AI自动跟踪"]),
        "已完成": done,
        "待处理": pending,
        "已逾期": overdue,
        "重点升级": escalated,
        "风险已缓解": relieved,
        "风险升级": escalated_by_reeval,
        "人工介入率": human_rate,
        "AI自动化率": auto_rate,
        "需要人工关注的决策数": need_count,
    }


def build_ai_actions_checklist(analysis_result: dict, tasks: list = None,
                               decisions: list = None) -> list:
    """「AI今日自动完成」清单（每条只引用真实数字，0 也如实呈现）。

    返回 [(描述, 数字), ...] 列表。
    """
    stats = compute_agent_stats(analysis_result, tasks, decisions)
    tier = stats["等级分布"]
    return [
        ("自动分析学员", stats["总学员数"]),
        ("识别风险学员(P1-P3)", stats["风险学员数"]),
        ("自动生成跟进任务(P1-P3)", tier["P1"] + tier["P2"] + tier["P3"]),
        ("自动生成沟通方案(需人工介入)", stats["需人工介入"]),
        ("已完成跟进", stats["已完成"]),
        ("风险已缓解", stats["风险已缓解"]),
        ("风险升级(需重点关注)", stats["风险升级"]),
    ]


def build_funnel(analysis_result: dict, tasks: list = None, decisions: list = None) -> list:
    """今日风险处理漏斗（待联系→已联系→待观察→风险缓解），供闭环进度展示。"""
    stats = compute_agent_stats(analysis_result, tasks, decisions)
    tasks = tasks or []
    contacted = sum(1 for t in tasks if t.get("沟通结果历史"))
    return [
        ("待联系", stats["需人工介入"], "#C62828"),
        ("已联系", contacted, "#F9A825"),
        ("待观察", stats["持续观察"], "#EF6C00"),
        ("风险缓解", stats["风险已缓解"], "#1565C0"),
    ]


# ============================================================
# AI资源决策 / 服务效果 / 服务复盘（本次升级新增，纯增量）
# ============================================================

def compute_resource_allocation(analysis_result: dict, tasks: list = None,
                                decisions: list = None) -> dict:
    """AI资源决策：把全体学员分为「重点人工介入/轻量触达/持续观察/AI自动管理」四类。"""
    from core.resource_allocation import allocate_resources
    return allocate_resources(analysis_result, tasks, decisions)


def compute_service_effect(records: dict, tasks: list = None) -> dict:
    """AI服务效果：基于真实跟进记录计算若干可直接统计的效果指标。

    无数据可支撑的指标返回字符串「待积累数据」，不虚构数值。
    """
    from core.service_memory import evaluate_service_effect

    records = records or {}
    fu = {k: v for k, v in records.items() if isinstance(v, dict) and (v.get("history") or [])}
    n_fu = len(fu)

    effects = {k: evaluate_service_effect(v) for k, v in fu.items()}
    relieved = sum(1 for e in effects.values() if e["效果"] == "有效")
    improved = sum(1 for e in effects.values() if e["效果"] in ("有效", "有限"))
    repeated = sum(1 for v in fu.values() if len(v.get("history") or []) >= 2)
    escalated = sum(1 for e in effects.values() if e["效果"] == "无效")

    def _rate(numer):
        return round(numer / n_fu, 3) if n_fu else "待积累数据"

    # 任务及时处理率（来自 task_engine，与跟进记录独立）
    tasks = tasks or []
    done = sum(1 for t in tasks if t.get("任务状态") == "已完成")
    overdue = sum(1 for t in tasks if t.get("任务状态") == "已超时")
    ontime = done / (done + overdue) if (done + overdue) else "待积累数据"
    if ontime != "待积累数据":
        ontime = round(ontime, 3)

    return {
        "已跟进人数": n_fu,
        "风险缓解率": _rate(relieved),
        "跟进后改善率": _rate(improved),
        "重复跟进率": _rate(repeated),
        "风险升级率": _rate(escalated),
        "任务及时处理率": ontime,
    }


def compute_service_review(records: dict, students: list, tasks: list = None,
                           decisions: list = None) -> dict:
    """AI服务复盘：本周（本批数据）发现/观察/介入/改善/升级/无明显变化的运营总账，
    以及「哪类策略效果最好/哪类风险最适合观察」等结论（样本不足则如实标注）。"""
    from core.service_memory import build_strategy_memory, evaluate_service_effect

    students = students or []
    decisions = decisions or []
    records = records or {}

    risky = [s for s in students if str(s.get("分层")) in ("P1", "P2", "P3")]
    students_by_name = {s.get("学生姓名"): s for s in students}

    # 分桶统计
    auto = sum(1 for d in decisions if d.get("决策档位") in ("持续观察", "AI自动跟踪"))
    manual = sum(1 for d in decisions if d.get("决策档位") in ("立即处理", "今日处理"))

    fu = {k: v for k, v in records.items() if isinstance(v, dict) and (v.get("history") or [])}
    effects = {k: evaluate_service_effect(v) for k, v in fu.items()}
    improved = sum(1 for e in effects.values() if e["效果"] == "有效")
    escalated = sum(1 for e in effects.values() if e["效果"] == "无效")
    flat = sum(1 for e in effects.values() if e["效果"] == "有限")

    # 策略记忆 → 结论（样本不足时只给「数据积累中」）
    memory = build_strategy_memory(records, students_by_name)
    best_by_cat = memory.get("最佳策略建议") or {}
    insights = []
    if best_by_cat:
        for cat, r in best_by_cat.items():
            insights.append(
                f"「{cat}」样本中，{r['策略']} 有效占比最高（{r['次数']}次，有效{int(r['有效占比']*100)}%），可优先推荐")
    else:
        insights.append("策略效果记忆样本不足，数据积累中，暂不输出分类结论")

    return {
        "发现风险": len(risky),
        "AI自动观察": auto,
        "人工介入": manual,
        "风险改善": improved,
        "风险升级": escalated,
        "无明显变化": flat,
        "已跟进人数": len(fu),
        "策略洞察": insights,
        "样本状态": memory.get("整体样本状态", "样本积累中"),
    }