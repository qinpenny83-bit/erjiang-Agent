# -*- coding: utf-8 -*-
"""今日风险处理中心 — 任务引擎（纯逻辑层，不含UI）

职责：在现有学情分析结果（analyze_students_unified 输出）之上构建"执行层"：
风险识别 → 优先级决策 → 今日任务生成 → 完成跟进 → 规则化复评 → 下一步任务

==== 边界约定（不可违反）====
1. 只读 analysis_result，绝不回写原始分析结果
2. 复评降级只写任务侧字段 task["当前风险等级"]，原始 student["分层"] 保持不变
3. P1-P4 风险判断规则（risk_llm_analyzer）完全不触碰
4. 所有优先原因/风险原因必须来自真实数据字段，无数据则明确标注，禁止编造

==== 状态机 ====
待处理 →(立即处理)→ 处理中 →(完成跟进+结果反馈)→ 已完成 / 待二次跟进
待处理|处理中|待二次跟进 →(超过建议时间)→ 已超时（置顶+重点升级）
任意 →(复评降至P4/风险解除)→ 已关闭

==== 第二阶段预留接口 ====
ai_reevaluate(task, new_context) — 沟通结果AI动态复评（当前为规则化复评，
后续接入LLM时保持相同入参/出参签名即可无缝替换）
"""
import os
import re
from datetime import datetime, timedelta

# ============================================================
# 常量定义
# ============================================================

# 任务处理范围：P1-P3 进入任务化处理，P4 正常维护不占用今日精力
TASK_TIERS = ("P1", "P2", "P3")

# 任务状态
STATUS_PENDING = "待处理"
STATUS_IN_PROGRESS = "处理中"
STATUS_DONE = "已完成"
STATUS_FOLLOWUP = "待二次跟进"
STATUS_OVERDUE = "已超时"
STATUS_CLOSED = "已关闭"

# 活跃状态（可被超时判定）
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_FOLLOWUP)

# 沟通结果枚举（8种，与实际家校沟通场景对齐）
COMM_RESULTS = [
    "已成功沟通",       # 接通并完成本次沟通目标
    "未接通",           # 电话/消息无人应答
    "家长暂时忙碌",     # 家长明确表示稍后再谈
    "家长认可方案",     # 家长接受服务方案，疑虑缓解
    "家长仍存在疑虑",   # 沟通后家长仍有不满/疑虑
    "学生学习问题已明确",  # 已定位到具体学习问题
    "需要进一步跟进",   # 按约定需后续再沟通
    "其他",             # 备注说明
]

# 沟通结果 → 复评规则（等级变化：-1降一级；跟进延迟：生成下一步任务的天数）
# 规则化复评：只调整任务侧"当前风险等级"，不动原始分析分层
RESULT_RULES = {
    "已成功沟通":         {"tier_delta": 0,  "follow_days": 7, "next_action": "7天内常规回访，同步学习近况"},
    "未接通":             {"tier_delta": 0,  "follow_days": 0, "next_action": "今日稍后再次尝试联系"},
    "家长暂时忙碌":       {"tier_delta": 0,  "follow_days": 1, "next_action": "按家长方便的时间改约沟通"},
    "家长认可方案":       {"tier_delta": -1, "follow_days": 3, "next_action": "3天后进行学习效果回访"},
    "家长仍存在疑虑":     {"tier_delta": 0,  "follow_days": 1, "next_action": "24小时内二次跟进，优先化解疑虑", "escalate": True},
    "学生学习问题已明确": {"tier_delta": 0,  "follow_days": 3, "next_action": "3天内同步针对性学习改进方案"},
    "需要进一步跟进":     {"tier_delta": 0,  "follow_days": 3, "next_action": "按约定时间进行二次跟进"},
    "其他":               {"tier_delta": 0,  "follow_days": 3, "next_action": "根据备注情况安排跟进"},
}

# 等级 → 建议完成时限（时间优先原则：P1今日必办，P2三日，P3一周）
TIER_DEADLINE = {
    "P1": 0,   # 今日 21:00 前
    "P2": 3,   # 3天内
    "P3": 7,   # 7天内
}

_TIER_ORDER = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}


# ============================================================
# 内部工具：从学生数据提取真实信息
# ============================================================

def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _score_sequence(student: dict) -> list:
    """从学生画像原始数据提取按时间排序的成绩序列 [(排序键, 分数)]（仅用真实数据）"""
    profile = student.get("_profile")
    if not profile or not hasattr(profile, "learning"):
        return []
    raw_cols = getattr(profile.learning, "raw_columns", None)
    if not raw_cols:
        return []
    from utils.excel_parser import _parse_score_column_time
    scored = []
    for col, val in raw_cols.items():
        v = None
        try:
            if isinstance(val, (int, float)):
                v = float(val)
        except (ValueError, TypeError):
            pass
        if v is None:
            text_val = str(val).strip() if val is not None else ""
            m = re.search(r'〖(\d+(?:\.\d+)?)〗', text_val)
            if m:
                v = float(m.group(1))
        if v is not None:
            scored.append((_parse_score_column_time(col), v))
    scored.sort(key=lambda x: x[0])
    return scored


def _trend_desc(student: dict) -> str:
    """基于最近两次真实成绩的变化描述（无数据则返回空，不编造）"""
    seq = _score_sequence(student)
    if len(seq) < 2:
        return ""
    latest, prev = seq[-1][1], seq[-2][1]
    diff = latest - prev
    if diff < -5:
        return f"最近两次成绩{prev:g}→{latest:g}分，下降{abs(diff):g}分"
    if diff < 0:
        return f"最近两次成绩{prev:g}→{latest:g}分，略降{abs(diff):g}分"
    if diff > 5:
        return f"最近两次成绩{prev:g}→{latest:g}分，提升{diff:g}分"
    return f"最近两次成绩{prev:g}→{latest:g}分，基本持平"


# ============================================================
# 优先原因构建（AI为什么让我先处理他？— 只引用真实数据）
# ============================================================

def build_priority_reason(student: dict, task: dict) -> list:
    """构建优先处理原因清单，逐条对应真实数据；无数据支持的条目不输出"""
    reasons = []
    tier = student.get("分层", "P3")

    # ① 成绩趋势（真实两次成绩对比）
    trend_desc = _trend_desc(student)
    trend = student.get("成绩趋势")
    if trend == "下降":
        reasons.append(trend_desc if trend_desc else "成绩呈下降趋势")
    elif trend_desc:
        reasons.append(trend_desc)

    # ② 沟通周期超期
    comm_gap = student.get("沟通间隔天数")
    if comm_gap and comm_gap > 30:
        reasons.append(f"距上次沟通已{comm_gap}天，超过正常沟通周期")

    # ③ 家长风险信号
    parent = student.get("家长态度")
    signals = [s for s in (student.get("家长信号") or [])
               if isinstance(s, str) and s and s not in ("暂无数据", "-")]
    if parent == "消极":
        reasons.append("家长态度消极，存在不满信号")
    elif signals:
        reasons.append(f"家长信号：{'、'.join(signals[:2])}")

    # ④ 续费风险
    renewal = student.get("续费意愿", "")
    if renewal and renewal not in ("自然续费", "已续费", ""):
        reasons.append(f"续费状态异常（{renewal}）")

    # ⑤ 学习表现
    performance = student.get("学习表现")
    if performance == "消极":
        reasons.append("学生学习态度消极")

    # ⑥ AI风险证据兜底（来自现有风险分析的真实输出）
    if not reasons:
        evidence = [e for e in (student.get("风险触发") or []) if e][:2]
        if evidence:
            reasons.extend(evidence)
        elif tier == "P1":
            reasons.append("AI综合评估为高风险，建议今日优先处理")
        else:
            reasons.append("AI综合评估存在需关注的风险信号")

    # 编号 ①②③④ 最多4条
    marks = "①②③④⑤⑥"
    return [f"{marks[i]} {r}" for i, r in enumerate(reasons[:4])]


# ============================================================
# 今日动作构建（AI今日应该做什么 — 基于真实风险数据）
# ============================================================

def build_today_action(student: dict) -> dict:
    """生成今日建议动作 + 沟通目标/重点/完成标准"""
    tier = student.get("分层", "P3")
    comm_gap = student.get("沟通间隔天数")
    parent = student.get("家长态度")
    renewal = student.get("续费意愿", "")
    trend = student.get("成绩趋势")
    score = student.get("最近成绩")

    # --- 动作 ---
    if comm_gap and comm_gap > 30:
        action = "今日优先电话沟通（恢复联系）"
    elif parent == "消极":
        action = "今日优先电话沟通（化解家长不满）"
    elif tier == "P1":
        action = "今日优先电话沟通"
    elif tier == "P2":
        action = "今日电话沟通"
    else:
        action = "本周内电话/微信沟通"

    # --- 沟通目标 ---
    if parent == "消极" or any(
        s for s in (student.get("家长信号") or []) if s and s != "暂无数据"
    ):
        goal = "先化解家长情绪，确认核心不满点，再同步改进方案"
    elif trend == "下降":
        goal = "确认近期学习状态和成绩下降原因"
    elif comm_gap and comm_gap > 30:
        goal = "恢复联系，全面了解近期学习与家庭配合情况"
    elif renewal and renewal not in ("自然续费", "已续费", ""):
        goal = "了解续费犹豫点，同步学习价值与服务方案"
    else:
        goal = "同步学习近况，确认家长当前关注点"

    # --- 沟通重点 ---
    focus_points = []
    if trend == "下降":
        focus_points.append("不回避成绩下降，先讲原因再讲改进计划")
    if parent == "消极":
        focus_points.append("先倾听后解释，不直接进入续费话题")
    if renewal and renewal not in ("自然续费", "已续费", ""):
        focus_points.append("用学习效果数据回应续费疑虑，不强推")
    if score is not None:
        try:
            if float(score) < 75:
                focus_points.append("给出具体薄弱点和针对性提升方案")
        except (ValueError, TypeError):
            pass
    if not focus_points:
        focus_points.append("以学习反馈为主，确认孩子近况与家长期望")
    focus = "；".join(focus_points[:2])

    # --- 完成标准 ---
    if tier == "P1":
        standard = "明确家长核心问题，当场确定下一步服务动作与时间"
    elif tier == "P2":
        standard = "确认家长关注点，约定下次跟进时间"
    else:
        standard = "完成学习反馈，记录家长反馈要点"

    return {"动作": action, "沟通目标": goal, "沟通重点": focus, "完成标准": standard}


# ============================================================
# 任务生成与同步
# ============================================================

def _deadline_for(tier: str) -> str:
    """按等级生成建议完成时间（时间优先原则）"""
    days = TIER_DEADLINE.get(tier, 7)
    if days == 0:
        return datetime.now().replace(hour=21, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")


def _create_task(student: dict, seq: int, source_file: str = "") -> dict:
    """从学生分析结果创建一条任务（只读，不回写）"""
    tier = student.get("分层", "P3")
    name = student.get("学生姓名", "未知")
    action = build_today_action(student)
    comm_gap = student.get("沟通间隔天数")

    # 风险原因：取优先原因的纯文本（不含编号）
    reason_items = [r[2:] if len(r) > 2 and r[1] == " " else r
                    for r in build_priority_reason(student, {})]
    risk_reason = "；".join(reason_items)

    # 最近沟通时间描述（有数据才写，无数据明确标注）
    if comm_gap is not None:
        last_contact = f"{comm_gap}天前" if comm_gap > 0 else "今日"
    else:
        last_contact = "暂无数据"

    return {
        "task_id": f"T{datetime.now().strftime('%Y%m%d%H%M%S')}_{seq:03d}_{name}",
        "学生姓名": name,
        "年级": student.get("年级", "未知"),
        "原风险等级": tier,               # 首次生成时的AI分层（不变）
        "当前风险等级": tier,              # 任务侧复评等级（可变化，不影响原始分析）
        "风险原因": risk_reason,
        "最近成绩": student.get("最近成绩"),
        "成绩趋势": student.get("成绩趋势"),
        "成绩变化": _trend_desc(student),
        "最近沟通时间": last_contact,
        "沟通间隔天数": comm_gap,
        "家长态度": student.get("家长态度"),
        "续费意愿": student.get("续费意愿", ""),
        "当前风险状态": "存在明确风险，需优先处理" if tier == "P1" else (
                        "存在需关注的风险信号" if tier == "P2" else "存在轻微观察项"),
        "今日建议动作": action["动作"],
        "建议完成时间": _deadline_for(tier),
        "任务状态": STATUS_PENDING,
        "下一步动作": action["动作"],
        "优先原因": build_priority_reason(student, {}),
        "今日动作详情": action,
        "升级标记": False,               # 家长仍存疑虑等场景置True → 重点升级处理队列
        "沟通结果历史": [],
        "时间线": [
            {"时间": _now_str(), "事件": f"AI识别为{tier}风险", "详情": risk_reason},
            {"时间": _now_str(), "事件": "自动生成今日任务", "详情": action["动作"]},
        ],
        "创建时间": _now_str(),
        "更新时间": _now_str(),
        "数据源文件": str(source_file),
        "is_demo": False,
    }


def sync_tasks_from_analysis(analysis_result: dict, source_file: str, stored_tasks: list = None) -> list:
    """分析结果 → 今日任务集

    - 新进入P1-P3的学生：生成新任务
    - 已有任务的学生：保留状态/时间线（执行进度是核心资产），仅刷新风险数据字段
    - 不再属于P1-P3的学生：未关闭的任务自动关闭（依据最新分析，非编造）
    """
    students = analysis_result.get("students", []) if analysis_result else []
    in_range = {}
    for s in students:
        if s.get("分层") in TASK_TIERS:
            in_range[s.get("学生姓名")] = s

    existing = {t.get("学生姓名"): t for t in (stored_tasks or []) if t.get("学生姓名")}
    tasks = []
    seq = 0
    now = _now_str()

    for name, student in in_range.items():
        seq += 1
        old = existing.get(name)
        if old:
            # 保留执行状态，仅刷新风险数据（只读student，不回写）
            old["最近成绩"] = student.get("最近成绩")
            old["成绩趋势"] = student.get("成绩趋势")
            old["成绩变化"] = _trend_desc(student)
            old["沟通间隔天数"] = student.get("沟通间隔天数")
            old["家长态度"] = student.get("家长态度")
            old["续费意愿"] = student.get("续费意愿", "")
            old["风险原因"] = old.get("风险原因") or "；".join(
                r[2:] for r in build_priority_reason(student, {}))
            old["优先原因"] = old.get("优先原因") or build_priority_reason(student, {})
            old["更新时间"] = now
            tasks.append(old)
        else:
            tasks.append(_create_task(student, seq, source_file))

    # 已不在P1-P3范围且未关闭的任务 → 自动关闭
    for name, old in existing.items():
        if name not in in_range and old.get("任务状态") != STATUS_CLOSED:
            old["任务状态"] = STATUS_CLOSED
            old["更新时间"] = now
            old["时间线"].append({
                "时间": now, "事件": "任务自动关闭",
                "详情": "最新学情分析中该学生已不在P1-P3风险范围，风险解除",
            })
            tasks.append(old)
        elif name not in in_range:
            tasks.append(old)  # 已关闭的历史任务保留

    return tasks


# ============================================================
# 排序（AI优先级决策：超时 > 等级 > 紧迫度 > 时间）
# ============================================================

def _urgency_score(task: dict) -> float:
    """紧迫度评分：全部基于任务内真实数据字段"""
    score = 0.0
    # 超时最高优先（重点升级处理）
    if task.get("任务状态") == STATUS_OVERDUE:
        score += 100
    # 升级标记（家长仍存疑虑等）
    if task.get("升级标记"):
        score += 30
    # 风险等级
    score += {"P1": 60, "P2": 30, "P3": 10}.get(task.get("当前风险等级"), 10)
    # 成绩连续下降
    if task.get("成绩趋势") == "下降":
        score += 15
    # 长期未沟通
    gap = task.get("沟通间隔天数")
    if gap:
        if gap > 90:
            score += 15
        elif gap > 30:
            score += 8
    # 家长消极
    if task.get("家长态度") == "消极":
        score += 10
    # 续费异常
    if task.get("续费意愿") and task.get("续费意愿") not in ("自然续费", "已续费", ""):
        score += 5
    # 待二次跟进且已到时间
    if task.get("任务状态") == STATUS_FOLLOWUP:
        score += 6
    return score


def sort_tasks(tasks: list) -> list:
    """排序：紧迫度降序，同分按建议完成时间升序（越紧迫越靠前）"""
    def key(t):
        dl = t.get("建议完成时间") or "9999-12-31 23:59"
        return (-_urgency_score(t), dl)
    return sorted(tasks, key=key)


def check_overdue(tasks: list) -> list:
    """超时判定：活跃任务超过建议完成时间 → 已超时（动态计算，写入持久化）"""
    now = datetime.now()
    for t in tasks:
        if t.get("任务状态") not in ACTIVE_STATUSES:
            continue
        dl_str = t.get("建议完成时间")
        if not dl_str:
            continue
        try:
            dl = datetime.strptime(dl_str, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if now > dl and t.get("任务状态") != STATUS_OVERDUE:
            t["任务状态"] = STATUS_OVERDUE
            t["时间线"].append({
                "时间": _now_str(), "事件": "⚠️ 任务超时",
                "详情": f"超过建议完成时间{dl_str}仍未完成，已进入重点升级处理队列",
            })
            t["升级标记"] = True
            t["更新时间"] = _now_str()
    return tasks


# ============================================================
# 状态流转动作
# ============================================================

def _find(tasks: list, task_id: str) -> dict:
    for t in tasks:
        if t.get("task_id") == task_id:
            return t
    return None


def start_task(tasks: list, task_id: str) -> list:
    """【立即处理】：待处理/已超时/待二次跟进 → 处理中"""
    t = _find(tasks, task_id)
    if not t:
        return tasks
    if t["任务状态"] in (STATUS_PENDING, STATUS_OVERDUE, STATUS_FOLLOWUP):
        prev = t["任务状态"]
        t["任务状态"] = STATUS_IN_PROGRESS
        t["更新时间"] = _now_str()
        t["时间线"].append({
            "时间": _now_str(), "事件": "老师开始处理",
            "详情": f"任务由「{prev}」进入处理中" + ("（原任务已超时，优先处理）" if prev == STATUS_OVERDUE else ""),
        })
    return tasks


def downgrade_tier(tier: str) -> str:
    """等级降一级（仅任务侧）：P1→P2→P3→P4"""
    order = ["P1", "P2", "P3", "P4"]
    try:
        i = order.index(tier)
        return order[min(i + 1, 3)]
    except ValueError:
        return tier


def complete_task(tasks: list, task_id: str, comm_result: str, teacher_note: str = "") -> list:
    """【完成跟进】+ 沟通结果反馈 → 规则化复评 → 下一步任务

    闭环逻辑（当前规则化，第二阶段可换 ai_reevaluate 同签名替换）：
    1. 记录沟通结果 + 时间线
    2. 按结果规则调整任务侧等级（家长认可→降级；P3降至P4→风险解除关闭）
    3. 自动生成下一步动作（二次跟进任务/超时升级标记）
    """
    t = _find(tasks, task_id)
    if not t or comm_result not in RESULT_RULES:
        return tasks
    now = _now_str()
    rule = RESULT_RULES[comm_result]

    # 1. 记录沟通结果
    entry = {"时间": now, "结果": comm_result}
    if teacher_note:
        entry["备注"] = teacher_note
    t["沟通结果历史"].append(entry)
    t["时间线"].append({
        "时间": now, "事件": "老师完成沟通",
        "详情": comm_result + (f"（备注：{teacher_note}）" if teacher_note else ""),
    })

    # 2. 规则化复评（只改任务侧等级）
    old_tier = t["当前风险等级"]
    if rule["tier_delta"] < 0:
        new_tier = downgrade_tier(old_tier)
        t["当前风险等级"] = new_tier
        t["时间线"].append({"时间": now, "事件": "AI重新评估风险", "详情": f"风险等级由{old_tier}调整为{new_tier}"})

        # 降至P4 → 风险解除，任务关闭
        if new_tier == "P4":
            t["任务状态"] = STATUS_CLOSED
            t["下一步动作"] = "风险解除，转入常规维护"
            t["时间线"].append({"时间": now, "事件": "任务关闭", "详情": "复评后风险解除（P4），转入常规维护"})
            t["更新时间"] = now
            return tasks

    # 3. 升级标记（家长仍存疑虑）
    if rule.get("escalate"):
        t["升级标记"] = True
        t["时间线"].append({
            "时间": now, "事件": "⚠️ 进入重点升级处理",
            "详情": "家长仍存在疑虑，任务标记为重点升级，需24小时内二次跟进",
        })

    # 4. 生成下一步：本任务进入待二次跟进，刷新建议完成时间与下一步动作
    days = rule["follow_days"]
    if days == 0:
        # 未接通→今日再试：白天(9-19点)约定今日21:00前；夜间则约定次日上午10:00（避免凌晨打扰）
        now = datetime.now()
        if 9 <= now.hour < 19:
            deadline = now.replace(hour=21, minute=0, second=0, microsecond=0)
        else:
            deadline = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    else:
        deadline = datetime.now() + timedelta(days=days)
    t["任务状态"] = STATUS_FOLLOWUP
    t["建议完成时间"] = deadline.strftime("%Y-%m-%d %H:%M")
    t["下一步动作"] = rule["next_action"]
    t["时间线"].append({
        "时间": now, "事件": "自动生成下一步任务",
        "详情": f"{rule['next_action']}（建议完成：{t['建议完成时间']}）",
    })
    t["更新时间"] = now
    return tasks


def finish_task(tasks: list, task_id: str) -> list:
    """【完成跟进】后老师确认服务闭环结束：待二次跟进/处理中 → 已完成"""
    t = _find(tasks, task_id)
    if not t:
        return tasks
    t["任务状态"] = STATUS_DONE
    t["更新时间"] = _now_str()
    t["时间线"].append({"时间": _now_str(), "事件": "服务闭环完成", "详情": "本轮风险服务已完成"})
    return tasks


def schedule_followup(tasks: list, task_id: str, days: int, note: str = "") -> list:
    """【安排二次跟进】：手动设定跟进时间"""
    t = _find(tasks, task_id)
    if not t:
        return tasks
    deadline = datetime.now() + timedelta(days=max(0, int(days)))
    t["任务状态"] = STATUS_FOLLOWUP
    t["建议完成时间"] = deadline.strftime("%Y-%m-%d %H:%M")
    t["下一步动作"] = f"{days}天后进行二次跟进"
    t["时间线"].append({
        "时间": _now_str(), "事件": "老师安排二次跟进",
        "详情": f"约定{t['建议完成时间']}跟进" + (f"（{note}）" if note else ""),
    })
    t["更新时间"] = _now_str()
    return tasks


def close_task(tasks: list, task_id: str, reason: str = "") -> list:
    """【关闭任务】：风险解除或当前无需跟进"""
    t = _find(tasks, task_id)
    if not t:
        return tasks
    t["任务状态"] = STATUS_CLOSED
    t["更新时间"] = _now_str()
    t["时间线"].append({
        "时间": _now_str(), "事件": "任务关闭",
        "详情": reason or "风险已解除或当前无需继续跟进",
    })
    return tasks


# ============================================================
# 第二阶段预留接口：AI动态复评（当前规则化实现，签名保持不变）
# ============================================================

def ai_reevaluate(task: dict, comm_result: str, teacher_note: str = "") -> dict:
    """沟通结果 → 新风险评估。

    当前：调用规则化复评（RESULT_RULES）
    第二阶段：接入LLM，综合新学情/新成绩/沟通记录动态复评。
    返回签名保持：{"当前风险等级": str, "下一步动作": str, "升级标记": bool}
    """
    rule = RESULT_RULES.get(comm_result, RESULT_RULES["其他"])
    new_tier = task.get("当前风险等级")
    if rule["tier_delta"] < 0:
        new_tier = downgrade_tier(new_tier)
    return {
        "当前风险等级": new_tier,
        "下一步动作": rule["next_action"],
        "升级标记": bool(rule.get("escalate", False)) or bool(task.get("升级标记")),
    }


# ============================================================
# 驾驶舱统计（全部动态计算，不虚构）
# ============================================================

def get_dashboard_stats(tasks: list) -> dict:
    """今日风险总览：人数/等级分布/处理进度/超时/待二次跟进/闭环率"""
    total = len(tasks)
    open_tasks = [t for t in tasks if t["任务状态"] != STATUS_CLOSED]
    p_counts = {"P1": 0, "P2": 0, "P3": 0}
    for t in open_tasks:
        tier = t.get("当前风险等级")
        if tier in p_counts:
            p_counts[tier] += 1

    done = sum(1 for t in tasks if t["任务状态"] in (STATUS_DONE, STATUS_CLOSED))
    progress = (done / total) if total else 0.0

    overdue = sum(1 for t in tasks if t["任务状态"] == STATUS_OVERDUE)
    followup = sum(1 for t in tasks if t["任务状态"] == STATUS_FOLLOWUP)
    escalated = sum(1 for t in tasks if t.get("升级标记") and t["任务状态"] in ACTIVE_STATUSES)

    # 风险闭环率 = 已走完「识别→任务→处理→结果反馈」÷ 应处理
    # 判定标准：任务产生过沟通结果反馈（沟通结果历史非空）
    loop_closed = sum(1 for t in tasks if t.get("沟通结果历史"))
    closure_rate = (loop_closed / total) if total else 0.0

    # 预留指标（有完整数据后启用）
    on_time_done = sum(
        1 for t in tasks
        if t.get("沟通结果历史") and t.get("任务状态") in (STATUS_DONE, STATUS_FOLLOWUP, STATUS_CLOSED)
    )
    timely_rate = (on_time_done / total) if total else 0.0

    return {
        "今日风险人数": len(open_tasks),
        "P1": p_counts["P1"], "P2": p_counts["P2"], "P3": p_counts["P3"],
        "已完成": done,
        "总数": total,
        "处理进度": progress,
        "超时风险": overdue,
        "待二次跟进": followup,
        "重点升级": escalated,
        "风险闭环率": closure_rate,
        "服务及时率(预留)": timely_rate,
    }


# ============================================================
# Demo演示数据（明确标注，非真实学员）
# ============================================================

def get_demo_tasks() -> list:
    """构造带完整状态机演示的Demo任务（全部标注 is_demo=True，非真实数据）"""
    now = datetime.now()
    n = lambda: now.strftime("%Y-%m-%d %H:%M")

    def demo_task(seq, name, tier, status, reason, trend_desc, comm_gap, action,
                  deadline_offset_h, priority, timeline=None, results=None, escalated=False,
                  cur_tier=None):
        return {
            "task_id": f"DEMO_{seq:03d}_{name}",
            "学生姓名": name,
            "年级": "五年级",
            "原风险等级": tier,
            "当前风险等级": cur_tier or tier,
            "风险原因": reason,
            "最近成绩": 62 if seq <= 2 else (71 if seq <= 4 else 83),
            "成绩趋势": "下降" if seq <= 2 else ("波动" if seq <= 4 else "平稳"),
            "成绩变化": trend_desc,
            "最近沟通时间": f"{comm_gap}天前" if comm_gap else "暂无数据",
            "沟通间隔天数": comm_gap,
            "家长态度": "消极" if seq == 1 else ("一般" if seq <= 3 else "积极"),
            "续费意愿": "犹豫中" if seq in (1, 2) else "自然续费",
            "当前风险状态": "存在明确风险，需优先处理" if (cur_tier or tier) == "P1" else "存在需关注的风险信号",
            "今日建议动作": action,
            "建议完成时间": (now + timedelta(hours=deadline_offset_h)).strftime("%Y-%m-%d %H:%M"),
            "任务状态": status,
            "下一步动作": action,
            "优先原因": priority,
            "今日动作详情": {
                "动作": action,
                "沟通目标": "确认近期学习状态和成绩下降原因" if seq <= 2 else "同步学习近况，确认家长关注点",
                "沟通重点": "先倾听后解释，不直接进入续费话题" if seq == 1 else "以学习反馈为主，确认孩子近况",
                "完成标准": "明确家长核心问题，确定下一步服务动作" if seq <= 2 else "完成学习反馈，记录家长反馈要点",
            },
            "升级标记": escalated,
            "沟通结果历史": results or [],
            "时间线": timeline or [],
            "创建时间": n(),
            "更新时间": n(),
            "数据源文件": "Demo演示数据",
            "is_demo": True,
        }

    return [
        demo_task(
            1, "示例·张同学", "P1", STATUS_OVERDUE,
            "最近两次成绩85→62分，下降23分；距上次沟通45天，超过正常沟通周期；家长态度消极",
            "最近两次成绩85→62分，下降23分",
            45, "今日优先电话沟通（化解家长不满）", -26,
            ["① 最近两次成绩85→62分，下降23分", "② 距上次沟通已45天，超过正常沟通周期", "③ 家长态度消极，存在不满信号", "④ 续费状态异常（犹豫中）"],
            [{"时间": n(), "事件": "AI识别为P1风险", "详情": "成绩连续下降+家长消极+超期未沟通"},
             {"时间": n(), "事件": "自动生成今日任务", "详情": "今日优先电话沟通"},
             {"时间": n(), "事件": "⚠️ 任务超时", "详情": "超过建议完成时间仍未处理，已进入重点升级处理队列"}],
            escalated=True,
        ),
        demo_task(
            2, "示例·李同学", "P1", STATUS_PENDING,
            "最近两次成绩78→66分，下降12分；续费状态异常（犹豫中）",
            "最近两次成绩78→66分，下降12分",
            12, "今日优先电话沟通", 5,
            ["① 最近两次成绩78→66分，下降12分", "② 续费状态异常（犹豫中）", "③ 家长信号：反馈效果不明显"],
        ),
        demo_task(
            3, "示例·王同学", "P2", STATUS_IN_PROGRESS,
            "成绩波动较大，稳定性不足；距上次沟通32天",
            "最近两次成绩80→74分，下降6分",
            32, "今日电话沟通", 20,
            ["① 成绩波动较大，稳定性不足", "② 距上次沟通已32天，超过正常沟通周期"],
            [{"时间": n(), "事件": "AI识别为P2风险", "详情": "成绩波动+沟通超期"},
             {"时间": n(), "事件": "自动生成今日任务", "详情": "今日电话沟通"},
             {"时间": n(), "事件": "老师开始处理", "详情": "任务由「待处理」进入处理中"}],
        ),
        demo_task(
            4, "示例·赵同学", "P1", STATUS_FOLLOWUP,
            "已完成首次沟通，家长认可方案，待效果回访",
            "最近两次成绩75→69分，下降6分",
            3, "3天后进行学习效果回访", 60,
            ["① 家长认可方案，风险由P1降至P2", "② 待进行学习效果回访"],
            [{"时间": n(), "事件": "AI识别为P1风险", "详情": "成绩下降+家长疑虑"},
             {"时间": n(), "事件": "自动生成今日任务", "详情": "今日优先电话沟通"},
             {"时间": n(), "事件": "老师完成沟通", "详情": "家长认可方案"},
             {"时间": n(), "事件": "AI重新评估风险", "详情": "风险等级由P1调整为P2"},
             {"时间": n(), "事件": "自动生成下一步任务", "详情": "3天后进行学习效果回访"}],
            results=[{"时间": n(), "结果": "家长认可方案", "备注": "家长同意先按改进方案执行一个月"}],
            cur_tier="P2",
        ),
        demo_task(
            5, "示例·孙同学", "P3", STATUS_PENDING,
            "成绩平稳但作业完成率偏低，需观察",
            "最近两次成绩83→83分，基本持平",
            20, "本周内电话/微信沟通", 100,
            ["① 作业完成率偏低（65%）", "② 整体成绩平稳，属观察项"],
        ),
        demo_task(
            6, "示例·周同学", "P2", STATUS_CLOSED,
            "风险已解除：沟通后家长认可方案，复评降至P4",
            "最近两次成绩88→90分，提升2分",
            1, "风险解除，转入常规维护", 200,
            ["① 复评后风险解除（P4），转入常规维护"],
            [{"时间": n(), "事件": "AI识别为P2风险", "详情": "家长反馈效果不明显"},
             {"时间": n(), "事件": "老师完成沟通", "详情": "家长认可方案（备注：同步了阶段学习成果）"},
             {"时间": n(), "事件": "AI重新评估风险", "详情": "风险等级由P2调整为P3"},
             {"时间": n(), "事件": "任务关闭", "详情": "复评后风险解除（P4），转入常规维护"}],
            results=[{"时间": n(), "结果": "家长认可方案", "备注": "同步了阶段学习成果，家长满意"}],
            cur_tier="P4",
        ),
    ]
