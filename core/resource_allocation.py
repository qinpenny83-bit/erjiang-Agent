# -*- coding: utf-8 -*-
"""👥 AI服务资源分配 — 有限人工时间该优先给谁？

一个二讲老师可能服务数百学员，人力有限。本模块把全体学员按 AI 决策自动分为四桶：
🟢 AI自动管理 / 💬 轻量触达 / 🟠 持续观察 / 🔴 重点人工介入

并输出：
- 今日真正需要人工处理的清单（按「AI干预价值」降序）
- 建议优先投入名单
- 预计人工投入时长（透明预估，绝不伪造成真实时长）

==== 设计原则（不可违反）====
1. 只读 analysis_result / tasks / decisions，绝不修改风险分层与风险分
2. 分桶基于真实决策档位与策略，不做无依据的优先级调整
3. 时长仅为「预估」，按可配置的均值计算并明确标注假设；无法估算时如实说明
"""

# 人均沟通时长（分钟）——仅用于预估排班，可配置，明确标注为假设
AVG_CALL_MIN = 15      # 电话跟进
AVG_MSG_MIN = 5        # 微信轻触达


def allocate_resources(analysis_result: dict, tasks: list = None, decisions: list = None) -> dict:
    """把全体学员按 AI 决策分为四档资源池，并给出人工投入预估。

    Args:
        analysis_result: 学情分析结果（含 students）
        tasks: task_engine 任务列表（可选）
        decisions: build_agent_tasks 决策列表（可选，需已带 干预价值/服务策略）
    Returns:
        {"总学员数","重点人工介入","轻量触达","持续观察","AI自动管理",
         "桶":{档位:[]}, "建议优先投入":[姓名], "人工投入估算":{...}}
    """
    from core.agent_decision import build_agent_tasks

    students = (analysis_result or {}).get("students", [])
    total = len(students)

    if decisions is None:
        decisions = build_agent_tasks(analysis_result, tasks)

    buckets = {"重点人工介入": [], "轻量触达": [], "持续观察": [], "AI自动管理": []}
    for d in decisions:
        level = d.get("决策档位", "")
        strat = (d.get("服务策略") or {}).get("推荐策略", "")
        if level in ("立即处理", "今日处理"):
            buckets["重点人工介入"].append(d)
        elif level == "持续观察":
            buckets["持续观察"].append(d)
        else:
            # AI自动跟踪里，策略为「微信轻触达」的进轻量触达，其余 AI自动管理
            if strat == "微信轻触达":
                buckets["轻量触达"].append(d)
            else:
                buckets["AI自动管理"].append(d)

    # 重点人工介入：升级/逾期优先，其次按干预价值降序
    buckets["重点人工介入"].sort(key=_focus_key, reverse=True)
    for k in ("轻量触达", "持续观察", "AI自动管理"):
        buckets[k].sort(key=lambda x: -_ival(x))

    focus = buckets["重点人工介入"]
    light = buckets["轻量触达"]
    top_names = [d.get("学员姓名", "") for d in focus[:5]]

    # 人工投入预估（透明假设，非伪造）
    focus_hours = len(focus) * AVG_CALL_MIN / 60.0
    light_hours = len(light) * AVG_MSG_MIN / 60.0
    est_hours = round(focus_hours + light_hours, 1)

    return {
        "总学员数": total,
        "重点人工介入": len(focus),
        "轻量触达": len(light),
        "持续观察": len(buckets["持续观察"]),
        "AI自动管理": len(buckets["AI自动管理"]),
        "桶": buckets,
        "建议优先投入": top_names,
        "人工投入估算": {
            "可估算": True,
            "小时": est_hours,
            "说明": f"预估按「电话{AVG_CALL_MIN}分钟/人、微信{AVG_MSG_MIN}分钟/人」计算，仅供排班参考",
        },
    }


def _ival(d: dict):
    v = d.get("干预价值")
    return v if isinstance(v, (int, float)) else 0


def _focus_key(d: dict) -> tuple:
    """重点人工介入排序键：升级/逾期优先，其次干预价值。"""
    strat = (d.get("服务策略") or {}).get("推荐策略", "")
    hot = strat == "升级重点处理"
    return (hot, _ival(d))


def estimate_manual_hours(focus_count: int, light_count: int) -> dict:
    """独立的人工投入预估（供 UI 直接调用），返回预估小时与说明。"""
    hours = round(focus_count * AVG_CALL_MIN / 60.0 + light_count * AVG_MSG_MIN / 60.0, 1)
    return {
        "可估算": True,
        "小时": hours,
        "说明": f"预估按「电话{AVG_CALL_MIN}分钟/人、微信{AVG_MSG_MIN}分钟/人」计算，仅供排班参考",
    }