# -*- coding: utf-8 -*-
"""🧠 服务效果评估 + 策略效果记忆 — 纯规则层（零大模型调用）

职责：
1. 评估「这一次服务有没有效果」（有效/有限/无效/样本不足）
2. 沉淀「风险类型 × 服务策略 → 服务结果」的关联，形成策略效果记忆，
   供下次遇到相似情况时优先推荐更有效的策略。

==== 设计原则（不可违反）====
1. 只基于真实跟进记录（RiskFollowupStore 的 history: 方式/结果 + risk_history: 风险快照）
2. 样本不足时明确标注「样本不足，仅作辅助参考」，绝不声称"已证明有效"
3. 无数据时输出「数据积累中」，禁止编造服务效果/策略有效性
"""

from collections import defaultdict

# 风险类型推导关键词（基于学情分析的风险触发，透明映射到既有风险类型）
_RISK_KW = [
    ("参与度风险", ["参与", "听课", "时长", "缺课", "回放"]),
    ("练习执行风险", ["练习", "提交", "作业", "未交"]),
    ("学习效果风险", ["效果", "正确率", "得分", "答题", "成绩", "进步"]),
    ("趋势变化风险", ["趋势", "下降", "波动", "退步", "恶化", "下滑"]),
    ("数据异常", ["数据", "异常", "待确认", "缺失"]),
]


# ============================================================
# 一、服务动作效果评估
# ============================================================

def evaluate_service_effect(record: dict, current_score=None) -> dict:
    """评估某个学员「这一次服务有没有效果」。

    Args:
        record: RiskFollowupStore.get(name) 记录（history + risk_history）
        current_score: 当前最新风险分（可选）
    Returns: {"效果":"有效|有限|无效|样本不足", "icon", "color", "说明", "证据":[]}
    """
    record = record or {}
    history = record.get("history") or []
    risk_hist = record.get("risk_history") or []

    if not history:
        return {"效果": "样本不足", "icon": "⚪", "color": "#9E9E9E",
                "说明": "尚无跟进记录，待积累数据后评估服务效果", "证据": []}

    last = history[-1] if history else {}
    result = str(last.get("result") or "")
    evidence = [f"最近跟进结果「{result}」"]

    # 风险变化（最早→最新快照）
    delta = None
    if len(risk_hist) >= 2:
        try:
            prev = float(risk_hist[0].get("risk_score", 0))
            cur = current_score if isinstance(current_score, (int, float)) \
                else float(risk_hist[-1].get("risk_score", 0))
            delta = cur - prev
            evidence.append(f"风险分 {prev:.0f} → {cur:.0f}（{delta:+.0f}）")
        except (ValueError, TypeError):
            delta = None

    unimproved = _consecutive_no_improve(history)
    if unimproved >= 2:
        evidence.append(f"已连续 {unimproved} 次跟进暂无改善")

    effective = result == "已解决" or (delta is not None and delta <= -10)
    invalid = unimproved >= 2 or (result == "暂无改善" and (delta is None or delta >= -5))
    limited = result in ("部分改善", "家长需要进一步观察", "家长暂未接通") or \
              (delta is not None and -10 < delta < 0)

    if effective:
        return {"效果": "有效", "icon": "🟢", "color": "#2E7D32",
                "说明": "本次服务后风险明显改善", "证据": evidence}
    if invalid:
        return {"效果": "无效", "icon": "🔴", "color": "#C62828",
                "说明": "当前服务方式改善有限，建议调整策略或升级人工判断", "证据": evidence}
    if limited:
        return {"效果": "有限", "icon": "🟡", "color": "#F9A825",
                "说明": "已有改善迹象但未完全解除，需继续跟进观察", "证据": evidence}
    return {"效果": "有限", "icon": "🟡", "color": "#F9A825",
            "说明": "本次沟通有效果信息有限，待后续数据验证", "证据": evidence}


def _consecutive_no_improve(history: list) -> int:
    n = 0
    for h in reversed(history or []):
        if str(h.get("result") or "") == "暂无改善":
            n += 1
        else:
            break
    return n


# ============================================================
# 二、策略效果记忆
# ============================================================

def _derive_category(student: dict) -> str:
    """从学情分析的风险触发推导风险类型，无匹配用「综合风险」。"""
    student = student or {}
    triggers = student.get("风险触发") or []
    text = "".join(str(x) for x in triggers)
    for cat, kws in _RISK_KW:
        if any(k in text for k in kws):
            return cat
    return "综合风险"


def _conclude(n: int, effective: int, invalid: int, sample_ok: bool) -> str:
    if not sample_ok:
        return "样本不足，仅作辅助参考"
    ratio = effective / n if n else 0.0
    if ratio >= 0.6:
        return "该策略对该类型风险效果较好，可优先推荐"
    if invalid >= 1 and ratio <= 0.3:
        return "该策略效果有限，下次建议尝试其他方式"
    return "效果一般，继续观察"


def build_strategy_memory(records: dict, students_by_name: dict = None) -> dict:
    """从全部跟进记录沉淀「风险类型 × 服务策略 → 结果」的策略效果记忆。

    Args:
        records: RiskFollowupStore.load() 结果 {学员姓名: 记录}
        students_by_name: {学员姓名: 学情分析学员dict}（用于推导风险类型）
    Returns:
        {"总跟进次数", "整体样本状态", "明细":[{风险类型,策略,次数,有效,无效,中性,有效占比,样本充足,结论}],
         "最佳策略建议": {风险类型: 明细}}
    """
    students_by_name = students_by_name or {}
    agg = defaultdict(lambda: {"有效": 0, "无效": 0, "中性": 0})

    total_fu = 0
    for name, rec in (records or {}).items():
        if not isinstance(rec, dict):
            continue
        cat = _derive_category(students_by_name.get(name))
        for h in rec.get("history") or []:
            if not isinstance(h, dict):
                continue
            method = h.get("method") or "未知"
            result = str(h.get("result") or "")
            total_fu += 1
            a = agg[(cat, method)]
            if result == "已解决":
                a["有效"] += 1
            elif result == "暂无改善":
                a["无效"] += 1
            else:
                a["中性"] += 1

    rows = []
    for (cat, method), a in agg.items():
        n = a["有效"] + a["无效"] + a["中性"]
        ratio = a["有效"] / n if n else 0.0
        sample_ok = n >= 3
        rows.append({
            "风险类型": cat, "策略": method, "次数": n,
            "有效": a["有效"], "无效": a["无效"], "中性": a["中性"],
            "有效占比": ratio, "样本充足": sample_ok,
            "结论": _conclude(n, a["有效"], a["无效"], sample_ok),
        })
    rows.sort(key=lambda r: (-r["次数"], r["风险类型"], r["策略"]))

    # 每类风险推荐最优策略（仅样本充足者）
    best_by_cat = {}
    for r in rows:
        if not r["样本充足"]:
            continue
        cur = best_by_cat.get(r["风险类型"])
        if cur is None or r["有效占比"] > cur["有效占比"] or \
                (r["有效占比"] == cur["有效占比"] and r["次数"] > cur["次数"]):
            best_by_cat[r["风险类型"]] = r

    sufficient = sum(1 for r in rows if r["样本充足"])
    return {
        "总跟进次数": total_fu,
        "整体样本状态": "样本充足" if sufficient > 0 else "样本积累中",
        "明细": rows,
        "最佳策略建议": best_by_cat,
    }