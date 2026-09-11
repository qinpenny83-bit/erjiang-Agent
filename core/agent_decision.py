# -*- coding: utf-8 -*-
"""🧠 AI学员服务决策中枢 — 纯逻辑层（不含UI）

在现有「风险识别层」之上构建「AI决策执行层」，回答三个问题：
1. 老师今天该联系谁？（而不是让老师从81个学生里自己找）
2. 为什么不联系某些高风险学员？（如：风险仍高但已明确回升，暂不打扰）
3. 联系/观察之后，AI什么时候自动复查？

==== 设计原则（不可违反）====
1. 只读 analysis_result 与 task_engine 任务态，绝不回写原始风险分层/风险分
2. 决策完全基于真实数据字段（分层/风险分/趋势/沟通/家长/续费/任务态），禁止编造
3. 禁止「P1=必须打电话」的机械映射：必须结合趋势/历史沟通/是否逾期/是否再次恶化综合判断
4. 纯规则决策（零大模型调用），透明可追溯；每次决策输出"判断依据"逐条引用真实数据
5. 自动化分层：🟢AI自主处理 / 🟡AI辅助处理 / 🔴人工决策（AI自动化 ≠ AI替代老师）

==== 决策档位 ====
- 🔴 立即处理（今日必须联系）+ 人工决策
- 🟠 今日处理（今日优先级，需人工联系）+ 人工决策
- 🟡 持续观察（暂不打扰，AI自动复查）+ AI辅助处理
- 🟢 AI自动跟踪（无需人工介入，AI持续监测）+ AI自主处理
"""

# ============================================================
# 常量
# ============================================================

# 决策档位（关键程度从高到低）
LEVEL_RED = "立即处理"      # 今日必须联系
LEVEL_ORANGE = "今日处理"    # 今日优先级（需人工联系）
LEVEL_YELLOW = "持续观察"    # 暂不打扰，AI自动复查
LEVEL_GREEN = "AI自动跟踪"   # 无需人工介入

# 自动化分类
AUTO_MODE = {"green": "AI自主处理", "yellow": "AI辅助处理", "orange": "人工决策", "red": "人工决策"}

# 趋势取值集合（与 excel_parser 对齐：上升/平稳/下降；波动为多指标抖动）
_DOWN_TRENDS = ("下降", "波动", "下滑", "退步", "恶化")
_UP_TRENDS = ("上升", "回升", "提升", "进步", "改善")

# 常见"暂无数据/占位"值
_NA_VALUES = ("暂无数据", "-", "", None)


def _clean(v):
    return (str(v).strip() if v is not None else "")


def _is_down_trend(trend) -> bool:
    return any(k in _clean(trend) for k in _DOWN_TRENDS) if trend else False


def _is_up_trend(trend) -> bool:
    return any(k in _clean(trend) for k in _UP_TRENDS) if trend else False


# ============================================================
# 单一学员决策：要不要联系？
# ============================================================

def decide_contact(student: dict, task: dict = None) -> dict:
    """综合判断该学员「要不要联系」，输出决策档位+依据+动作+复查时间+自动化分类。

    Args:
        student: analysis_result["students"] 中的学员 dict（含 分层/流失风险分/成绩趋势 等）
        task: 该学员在 task_engine 中的任务对象（可为 None，表示尚未生成任务）
    Returns: 决策 dict（结构见模块注释）
    """
    tier = _clean(student.get("分层")) if student else "P4"
    if tier not in ("P1", "P2", "P3", "P4"):
        tier = "P4"
    name = _clean(student.get("学生姓名")) or "未知学员"
    trend = _clean(student.get("成绩趋势"))
    score = student.get("流失风险分") if student else None
    comm_gap = student.get("沟通间隔天数")
    parent = _clean(student.get("家长态度"))
    renewal = _clean(student.get("续费意愿"))

    reasons = []  # 判断依据（只引用真实数据）

    # ---------- 任务态信息（有则用，无则视为首次识别） ----------
    status = _clean(task.get("任务状态")) if task else ""
    escalated = bool(task.get("升级标记")) if task else False
    comm_history = (task.get("沟通结果历史") or []) if task else []
    ai_reeval = task.get("AI复评结果") if task else None

    # ---------- 0. 已关闭任务 = 风险解除，转入常规维护 ----------
    if status == "已关闭":
        reasons.append("任务已关闭（依据复评结果），风险已解除")
        return _mk(name, tier, LEVEL_GREEN, False, "低", "无需人工介入，AI持续常规监测",
                   "已解除", None, reasons, "AI自主处理")

    # ---------- 1. 逾期/升级标记：最高优先，立即处理 ----------
    if status == "已超时":
        reasons.append(f"任务已超时（建议完成：{_clean(task.get('建议完成时间'))}），须立即处理")
        return _mk(name, tier, LEVEL_RED, True, "高", "今日电话跟进（任务已超时）",
                   "已升级", "今日", reasons, "人工决策")
    if escalated:
        reasons.append("任务标记为「重点升级」（家长疑虑未化解/连续未改善/风险上升）")
        return _mk(name, tier, LEVEL_RED, True, "高", "今日电话跟进（重点升级对象）",
                   "已升级", "今日", reasons, "人工决策")

    # ---------- 2. 无任务且 P4：正常，AI自动跟踪 ----------
    if tier == "P4":
        reasons.append(f"分层 P4（{_tier_label(tier)}），无明确风险信号")
        return _mk(name, tier, LEVEL_GREEN, False, "无", "无需人工介入，AI持续常规监测",
                   "未出现", None, reasons, "AI自主处理")

    # ---------- 3. 趋势判断（改善信号是关键分水岭） ----------
    down = _is_down_trend(trend)
    up = _is_up_trend(trend)

    # ---------- 风险分展示（引用真实数据） ----------
    score_str = f"风险分{int(score)}" if isinstance(score, (int, float)) else "风险分暂无数据"

    if tier == "P1":
        if up:
            reasons.append(f"分层 P1（{score_str}）为最高风险，但成绩趋势「{trend}」，出现明确改善信号")
            reasons.append("依据时间优先原则：风险仍高，但近期回升，不宜重复打扰家长")
            return _mk(name, tier, LEVEL_YELLOW, False, "中", "暂不立即联系，3天后复查最新学习数据",
                       "仍在", "3天后", reasons, "AI辅助处理")
        if down or trend == "" or trend in _NA_VALUES:
            _r = f"分层 P1（{score_str}），成绩趋势「{trend or '暂无数据'}」" + ("，持续恶化" if down else "")
            if down:
                reasons.append(_r)
                reasons.append("风险持续恶化且无改善信号，须今日人工介入")
            else:
                reasons.append(f"分层 P1（{score_str}）为最高风险，需人工确认")
            return _mk(name, tier, LEVEL_RED, True, "高", "今日电话跟进",
                       "仍在", "今日", reasons, "人工决策")
        # 平稳
        reasons.append(f"分层 P1（{score_str}），成绩趋势「平稳」，风险仍处高位")
        return _mk(name, tier, LEVEL_ORANGE, True, "高", "今日电话跟进",
                   "仍在", "今日", reasons, "人工决策")

    if tier == "P2":
        if down:
            reasons.append(f"分层 P2（{score_str}），成绩趋势「{trend}」持续下降")
            return _mk(name, tier, LEVEL_ORANGE, True, "中", "今日电话沟通",
                       "仍在", "今日", reasons, "人工决策")
        reasons.append(f"分层 P2（{score_str}），趋势「{trend or '平稳'}」，需持续关注")
        return _mk(name, tier, LEVEL_YELLOW, False, "中", "纳入持续观察，3天后复查",
                   "仍在", "3天后", reasons, "AI辅助处理")

    # P3
    if down:
        reasons.append(f"分层 P3（{score_str}），成绩趋势「{trend}」出现下降，提前干预")
        return _mk(name, tier, LEVEL_ORANGE, True, "中", "本周内电话/微信沟通",
                   "观察项", "本周内", reasons, "人工决策")
    reasons.append(f"分层 P3（{score_str}），趋势「{trend or '平稳'}」，整体相对稳定")
    if parent == "消极":
        reasons.append("家长态度消极，存在不满信号，需关注")
        return _mk(name, tier, LEVEL_YELLOW, False, "中", "纳入观察，关注家长情绪变化",
                   "观察项", "3天后", reasons, "AI辅助处理")
    return _mk(name, tier, LEVEL_GREEN, False, "低", "无需人工介入，AI自动跟踪",
               "观察项", None, reasons, "AI自主处理")


def _tier_label(tier: str) -> str:
    return {"P1": "特别关注", "P2": "需关注", "P3": "相对稳定", "P4": "优"}.get(tier, tier)


def _mk(name, tier, level, need_contact, priority, action, risk_state, review_time,
        reasons, auto_mode) -> dict:
    level_key = {LEVEL_RED: "red", LEVEL_ORANGE: "orange",
                 LEVEL_YELLOW: "yellow", LEVEL_GREEN: "green"}.get(level, "green")
    return {
        "学员姓名": name,
        "分层": tier,
        "决策档位": level,
        "档位键": level_key,
        "是否需联系": need_contact,
        "联系优先级": priority,
        "建议动作": action,
        "风险状态": risk_state,           # 仍在/已缓解/已解除/已升级/观察项/未出现
        "复查时间": review_time,
        "判断依据": reasons,
        "自动化分类": auto_mode,
        "一句话": level,
    }


# ============================================================
# 决策增强：干预价值 + 服务策略（增量层，不改变原有决策档位）
# ============================================================

def _enrich_decision(student: dict, task: dict, d: dict) -> dict:
    """在决策档位之上叠加「AI干预价值 + 服务策略」，纯增量、不改变 decide_contact 结果。"""
    try:
        from core.intervention_value import compute_intervention_value
        iv = compute_intervention_value(student, task)
        d["干预价值"] = iv["价值分"]
        d["干预价值等级"] = iv["价值等级"]
        d["干预价值依据"] = iv["依据"]

        from core.service_strategy import choose_strategy
        d["服务策略"] = choose_strategy(student, task, iv, d)
    except Exception as e:  # 增强失败不影响主决策
        print(f"[决策中枢] 干预价值/策略增强失败: {e}")
    return d


# ============================================================
# 今日AI任务：对所有学员做决策并分桶
# ============================================================

def build_agent_tasks(analysis_result: dict, tasks: list = None) -> list:
    """遍历全部学员，生成「今日AI任务」决策集，按决策档位排序。

    每个决策元素 = decide_contact 输出 + 学员原始信息增量 + 干预价值 + 服务策略 + 决策理由。
    """
    students = (analysis_result or {}).get("students", [])
    task_by_name = {t.get("学生姓名"): t for t in (tasks or []) if t.get("学生姓名")}

    raw = []
    for s in students:
        t = task_by_name.get(s.get("学生姓名"))
        d = decide_contact(s, t)
        d["风险分"] = s.get("流失风险分")
        d["风险触发"] = s.get("风险触发") or []
        d["成绩趋势"] = s.get("成绩趋势")
        d["最近成绩"] = s.get("最近成绩")
        d["家长态度"] = s.get("家长态度")
        d["任务状态"] = t.get("任务状态") if t else ""
        d = _enrich_decision(s, t, d)
        raw.append((s, t, d))

    # 第二遍：为每个决策补上「AI决策理由」（需知道 AI自动管理 人数）
    auto_count = sum(1 for _, _, x in raw if x.get("决策档位") == LEVEL_GREEN)
    decisions = []
    for s, t, d in raw:
        try:
            from core.service_strategy import build_decision_reason
            d["决策理由"] = build_decision_reason(
                s, t, d, d.get("服务策略"),
                {"价值分": d.get("干预价值"), "价值等级": d.get("干预价值等级")},
                auto_count=auto_count)
        except Exception as e:
            print(f"[决策中枢] 决策理由生成失败: {e}")
        decisions.append(d)

    # 排序：立即处理 > 今日处理 > 持续观察 > AI自动跟踪；同级内风险分降序
    order = {LEVEL_RED: 0, LEVEL_ORANGE: 1, LEVEL_YELLOW: 2, LEVEL_GREEN: 3}

    def key(d):
        score = d.get("风险分")
        s = score if isinstance(score, (int, float)) else 0
        return (order.get(d["决策档位"], 9), -s)

    decisions.sort(key=key)
    return decisions


def bucket_decisions(decisions: list) -> dict:
    """把决策列表分桶，供驾驶舱/今日任务展示。"""
    buckets = {
        "立即处理": [], "今日处理": [], "持续观察": [], "AI自动跟踪": [],
    }
    for d in decisions:
        buckets.setdefault(d["决策档位"], []).append(d)
    return buckets


def escalation_reason(task: dict) -> str:
    """自动升级机制：连续未改善/未接通 → 输出升级提醒（引用真实记录，不编造）。"""
    if not task:
        return ""
    hist = task.get("沟通结果历史") or []
    bad = [h for h in hist if h.get("结果") in ("未接通", "家长仍存在疑虑", "暂无改善", "部分改善")]
    if len(bad) >= 2:
        names = "、".join(h.get("结果", "") for h in bad[:3])
        return f"已连续 {len(bad)} 次跟进未出现明显改善（{names}），建议升级为重点服务对象"
    if (task.get("AI复评结果") or {}).get("风险方向") == "上升":
        return "最新复评显示风险上升，建议升级为重点跟进对象"
    return ""