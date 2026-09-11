# -*- coding: utf-8 -*-
"""🎯 AI服务策略选择 + 决策理由 — 纯规则层（零大模型调用）

在「要不要联系」（agent_decision 的决策档位）之上，进一步回答「怎么处理」：
1. 推荐策略（电话跟进/微信轻触达/AI自动观察/继续收集数据/复查后再联系/升级重点处理/人工确认）
2. 推荐原因（引用真实数据）
3. 预计下一次检查时间
4. 不推荐其他策略的原因
并生成结构化「AI决策理由」（为什么TA/为什么现在/为什么这种方式/为什么不是别人）。

==== 设计原则（不可违反）====
1. 只读 student/task/intervention/decision，绝不回写原始分层与风险分
2. 策略必须与决策档位对齐，不能「档位说别打扰、策略却说打电话」
3. 不推荐理由只能描述动作取舍，禁止编造不存在的家长/学员事实
"""

_STRATEGIES = [
    "电话跟进", "微信轻触达", "AI自动观察", "继续收集数据",
    "复查后再联系", "升级重点处理", "人工确认",
]

_STRATEGY_ICON = {
    "电话跟进": "☎️", "微信轻触达": "💬", "AI自动观察": "👀",
    "继续收集数据": "📊", "复查后再联系": "🔄", "升级重点处理": "🚨", "人工确认": "🧑‍💼",
}

_DOWN_TRENDS = ("下降", "波动", "下滑", "退步", "恶化")
_UP_TRENDS = ("上升", "回升", "提升", "进步", "改善")
_NA_VALUES = ("暂无数据", "-", "", None)


def _clean(v):
    return (str(v).strip() if v is not None else "")


def _is_down(trend) -> bool:
    return any(k in _clean(trend) for k in _DOWN_TRENDS) if trend else False


def _is_up(trend) -> bool:
    return any(k in _clean(trend) for k in _UP_TRENDS) if trend else False


def _tier(student):
    t = _clean(student.get("分层")) or "P4"
    return t if t in ("P1", "P2", "P3", "P4") else "P4"


def choose_strategy(student: dict, task: dict = None, intervention: dict = None,
                    decision: dict = None) -> dict:
    """为单个学员推荐服务策略。

    Args:
        student: 学员 dict
        task: 任务对象（可选）
        intervention: compute_intervention_value 输出（可选）
        decision: decide_contact 输出（可选，用于档位对齐）
    Returns:
        {"推荐策略", "策略图标", "推荐原因":[str], "预计检查", "不推荐原因":{策略:原因}, "可选策略":[str]}
    """
    student = student or {}
    task = task or {}
    decision = decision or {}
    intervention = intervention or {}

    tier = _tier(student)
    trend = _clean(student.get("成绩趋势"))
    missing = student.get("缺失维度") or []
    if not isinstance(missing, (list, tuple)):
        missing = []
    decision_level = decision.get("决策档位", "")
    review_time = _clean(decision.get("复查时间"))
    status = _clean(task.get("任务状态"))
    escalated = bool(task.get("升级标记"))

    rec, check, reasons = None, "", []

    # ---- 优先级：逾期/升级 > 数据不足 > 需联系 > 观察 > 自动跟踪 ----
    if status == "已超时" or escalated:
        rec, check = "升级重点处理", "今日"
        reasons = ["任务已超时或已标记重点升级，须升级为最高优先级处理"]
    elif tier in ("P1", "P2") and missing and decision_level in ("立即处理", "今日处理") \
            and not isinstance(student.get("流失风险分"), (int, float)):
        rec, check = "人工确认", "今日"
        reasons = ["风险等级高但关键数据缺失，AI无法可靠判断，须人工确认"]
    elif missing and tier in ("P1", "P2") and decision_level in ("立即处理", "今日处理"):
        rec, check = "继续收集数据", "补齐数据后立即复查"
        reasons = [f"存在 {len(missing)} 项缺失维度且风险较高，先补齐数据再精准决策"]
    elif decision_level in ("立即处理", "今日处理"):
        if tier in ("P1", "P2") or _is_down(trend):
            rec, check = "电话跟进", ("今日" if decision_level == "立即处理" else "今日")
            reasons = []
            if _is_down(trend):
                reasons.append(f"成绩趋势「{trend}」持续恶化，需电话直接介入")
            if tier in ("P1", "P2"):
                reasons.append(f"分层 {tier} 较高，电话沟通比文字更能及时把握家长真实态度")
        else:
            rec, check = "微信轻触达", "今日"
            reasons = ["风险中等且非紧急，微信轻触达即可，避免电话过度打扰"]
    elif decision_level == "持续观察":
        rec, check = "复查后再联系", (review_time or "3天后")
        reasons = ["暂不打扰家长，到点复查最新学习数据后再决定是否升级为联系"]
    elif decision_level == "AI自动跟踪":
        rec, check = "AI自动观察", ""
        reasons = ["低风险或已缓解，AI自主监测即可，无需人工介入"]
    else:
        rec, check = "AI自动观察", ""
        reasons = ["当前无明确人工介入信号，AI持续监测"]

    not_reasons = _alt_reasons(rec, tier, trend)
    return {
        "推荐策略": rec,
        "策略图标": _STRATEGY_ICON.get(rec, "👀"),
        "推荐原因": reasons,
        "预计检查": check or "持续监测",
        "不推荐原因": not_reasons,
        "可选策略": list(_STRATEGIES),
    }


def _alt_reasons(chosen: str, tier: str, trend: str) -> dict:
    """生成「未选择的其他策略」的不推荐原因（只描述动作取舍，不编造事实）。"""
    base = {
        "电话跟进": "高风险且需直接沟通时首选，当前场景不必电话打扰家长",
        "微信轻触达": "中等风险轻量触达时使用",
        "AI自动观察": "低风险或已缓解者用观察即可",
        "继续收集数据": "仅数据缺失时才选，当前数据可支撑判断",
        "复查后再联系": "暂不打扰、到点复查时使用",
        "升级重点处理": "仅连续未改善或高风险未解时才升级",
        "人工确认": "仅AI无法可靠判断时才需人工确认",
    }
    if chosen == "电话跟进":
        base["微信轻触达"] = "风险明确且紧急，微信触达力度不足，需电话直接沟通"
        base["AI自动观察"] = "仅观察会延误介入时机"
        base["复查后再联系"] = "当前不宜推迟到复查后再处理"
    elif chosen == "微信轻触达":
        base["电话跟进"] = "风险中等且非紧急，电话会过度打扰，轻触达更合适"
    elif chosen in ("复查后再联系", "AI自动观察"):
        base["电话跟进"] = "已出现改善或风险尚稳，重复电话会打扰家长"
        base["升级重点处理"] = "未出现连续恶化，暂不需要升级"
    elif chosen == "继续收集数据":
        base["电话跟进"] = "数据未补齐前贸然电话，可能针对错误方向沟通"
        base["AI自动观察"] = "仅观察不补数据，无法精准判断"
    elif chosen == "人工确认":
        base["AI自动观察"] = "AI无法判断时不能自动观察，须人工把关"
    return {k: v for k, v in base.items() if k != chosen}


# ============================================================
# AI决策理由（可解释、可追溯）
# ============================================================

def build_decision_reason(student: dict, task: dict = None, decision: dict = None,
                          strategy: dict = None, intervention: dict = None,
                          auto_count: int = 0) -> dict:
    """生成结构化「AI决策理由」：为什么 TA / 为什么现在 / 为什么这种方式 / 为什么不是别人。"""
    student = student or {}
    decision = decision or {}
    strategy = strategy or {}
    intervention = intervention or {}

    tier = _tier(student)
    level = decision.get("决策档位", "")

    # 为什么 TA
    why_this = [f"分层 {tier}"]
    score = student.get("流失风险分")
    if isinstance(score, (int, float)):
        why_this.append(f"风险分 {int(score)}")
    iv = intervention.get("价值分")
    if isinstance(iv, (int, float)):
        why_this.append(f"AI干预价值 {int(iv)} 分（{intervention.get('价值等级', '')}）")
    why_this += list((decision.get("判断依据") or [])[:2])

    # 为什么现在
    if level in ("立即处理", "今日处理"):
        why_now = [f"AI判定为「{level}」，需今日处理"]
    elif level == "持续观察":
        why_now = ["暂非今日必须处理，AI将到点自动复查"]
    else:
        why_now = ["当前无需处理，AI持续监测等新数据"]

    # 为什么这种方式
    why_way = list((strategy.get("推荐原因") or []))
    if not why_way:
        why_way = ["当前策略与风险状态匹配，无需人工介入"]

    # 为什么不是别人
    why_others = [f"其余学员已由AI自动观察/管理（{auto_count} 人）或暂无需人工，把老师时间留给最关键学员"]

    return {
        "为什么TA": why_this,
        "为什么现在": why_now,
        "为什么这种方式": why_way,
        "为什么不是别人": why_others,
    }