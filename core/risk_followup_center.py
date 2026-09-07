# -*- coding: utf-8 -*-
"""风险优先处理中心 — 规则层（Tab3专属，零LLM调用）

闭环：风险识别 → 跟进建议 → 沟通方案(AI按需) → 老师联系 → 记录结果 → AI判断下一步 → 数据回流（重新分析快照对比）

==== 边界约定（不可违反）====
1. 只服务Tab3风险处理场景，与Tab2沟通跟进中心(followup_engine)相互独立（仅复用now_cn时间工具）
2. 所有判断只基于真实数据（分析结果 + 已记录跟进信息），禁止编造家长态度/学生情况/沟通内容
3. 不修改风险分/P1-P4算法/TOP10排序，只做跟进状态管理、解释与建议
4. 跟进数据存 data/risk_followups.json（已被.gitignore排除，含真实学员姓名不入库）
5. 数据不足时明确提示，不强行下结论
"""
import os
import json
import random
from datetime import datetime, timedelta

from config import DATA_DIR
from core.followup_engine import now_cn

RISK_FOLLOWUP_FILE = os.path.join(DATA_DIR, "risk_followups.json")

# ====== 跟进状态（4种） ======
STATUS_PENDING = "待联系"            # 🔴
STATUS_CONTACTED = "已联系·待观察"    # 🟡
STATUS_DONE = "已完成跟进"            # 🟢
STATUS_SKIP = "暂不需要跟进"          # 🔵

STATUS_ORDER = [STATUS_PENDING, STATUS_CONTACTED, STATUS_DONE, STATUS_SKIP]

STATUS_META = {
    STATUS_PENDING: {"icon": "🔴", "color": "#C62828"},
    STATUS_CONTACTED: {"icon": "🟡", "color": "#F9A825"},
    STATUS_DONE: {"icon": "🟢", "color": "#2E7D32"},
    STATUS_SKIP: {"icon": "🔵", "color": "#1565C0"},
}

# ====== 跟进表单枚举 ======
FU_METHODS = ["电话", "微信", "其他"]
FU_RESULTS = ["已解决", "部分改善", "暂无改善", "家长暂未接通", "家长需要进一步观察", "其他"]

# 风险类型 → 复查维度（用于跟进判断的下一步建议，全部真实指标名）
RISK_RECHECK_DIMS = {
    "参与度风险": "听课参与",
    "练习执行风险": "练习提交",
    "学习效果风险": "答题与练习得分",
    "趋势变化风险": "各维度指标变化",
    "数据异常/待确认": "问题讲次核实情况",
}


def default_status_for(priority: str) -> str:
    """根据风险等级给出默认跟进状态：P1-P3为风险学员→待联系；P4→暂不需要跟进"""
    return STATUS_SKIP if "P4" in str(priority) else STATUS_PENDING


def status_display(status: str) -> str:
    """状态显示文本（icon + 文本）"""
    meta = STATUS_META.get(status, STATUS_META[STATUS_PENDING])
    return f"{meta['icon']} {status}"


# ============================================================
# 一、跟进状态存储（JSON文件，原子写入，按学员姓名键）
# ============================================================

class RiskFollowupStore:
    """风险跟进状态存储：load/get/record_followup/update_status/snapshot_risk/导入导出"""

    def __init__(self, path: str = None):
        self.path = path or RISK_FOLLOWUP_FILE
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    # ---------- 基础读写 ----------
    def load(self) -> dict:
        """返回 {学员姓名: 记录dict}"""
        try:
            if not os.path.exists(self.path):
                return {}
            with open(self.path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return {}
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[RiskFollowupStore] 读取失败，按空处理: {type(e).__name__}: {e}")
            return {}

    def _save(self, data: dict):
        # 原子写入：先写临时文件再替换，避免写入中断导致数据损坏
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get(self, name: str) -> dict:
        return self.load().get((name or "").strip())

    # ---------- 跟进操作 ----------
    def record_followup(self, name: str, method: str, result: str, feedback: str,
                        note: str, next_date: str, risk_score, priority,
                        new_status: str = None) -> dict:
        """记录一次跟进：更新状态/时间/方式/结果，并追加历史"""
        name = (name or "").strip()
        data = self.load()
        ts = now_cn().strftime("%Y-%m-%d %H:%M")
        rec = data.get(name)
        if rec is None:
            rec = self._new_record(name, priority, ts)
        rec.update({
            "status": new_status if new_status in STATUS_ORDER else rec.get("status", STATUS_PENDING),
            "last_followup_at": ts,
            "followup_method": method,
            "followup_result": result,
            "parent_feedback": (feedback or "").strip(),
            "teacher_note": (note or "").strip(),
            "next_followup_date": next_date or None,
            "updated_at": ts,
        })
        rec.setdefault("history", []).append({
            "time": ts,
            "method": method,
            "result": result,
            "feedback": (feedback or "").strip(),
            "note": (note or "").strip(),
            "next_date": next_date or None,
            "risk_score": risk_score,
            "priority": priority,
        })
        data[name] = rec
        self._save(data)
        return rec

    def update_status(self, name: str, status: str) -> bool:
        """手动更新跟进状态"""
        if status not in STATUS_ORDER:
            return False
        name = (name or "").strip()
        data = self.load()
        rec = data.get(name)
        if rec is None:
            return False
        rec["status"] = status
        rec["updated_at"] = now_cn().strftime("%Y-%m-%d %H:%M")
        data[name] = rec
        self._save(data)
        return True

    # ---------- 数据回流：风险快照 ----------
    def snapshot_risk(self, results: list, ts: str = None) -> int:
        """分析完成时记录风险快照（数据回流入口）：
        - 无记录的学员按默认状态建档（P1-P3待联系 / P4暂不需要跟进）
        - 追加 {ts, risk_score, priority} 到 risk_history（同分钟内幂等，防重复点击）
        返回新建档人数。
        """
        ts = ts or now_cn().strftime("%Y-%m-%d %H:%M")
        data = self.load()
        added = 0
        for r in results:
            name = str(r.get("学员姓名", "")).strip()
            if not name:
                continue
            rec = data.get(name)
            if rec is None:
                rec = self._new_record(name, r.get("优先级", ""), ts)
                data[name] = rec
                added += 1
            hist = rec.setdefault("risk_history", [])
            if not hist or hist[-1].get("ts") != ts:
                hist.append({"ts": ts, "risk_score": r.get("风险分", 0),
                             "priority": r.get("优先级", "")})
                rec["updated_at"] = ts
        self._save(data)
        return added

    def _new_record(self, name: str, priority: str, ts: str) -> dict:
        return {
            "student_name": name,
            "status": default_status_for(priority),
            "last_followup_at": None,
            "followup_method": None,
            "followup_result": None,
            "parent_feedback": "",
            "teacher_note": "",
            "next_followup_date": None,
            "history": [],
            "risk_history": [],
            "created_at": ts,
            "updated_at": ts,
        }

    # ---------- 备份/恢复 ----------
    def export_data(self) -> str:
        return json.dumps(self.load(), ensure_ascii=False, indent=2)

    def import_merge(self, imported: dict) -> int:
        """合并导入备份数据（按学员姓名合并历史，不覆盖已有记录），返回新增人数"""
        if not isinstance(imported, dict):
            return 0
        data = self.load()
        added = 0
        for name, rec in imported.items():
            name = (name or "").strip()
            if not name or not isinstance(rec, dict):
                continue
            if name in data:
                # 合并历史（按时间戳去重）
                exist_ts = {h.get("time") for h in data[name].get("history", [])}
                for h in rec.get("history", []):
                    if h.get("time") not in exist_ts:
                        data[name].setdefault("history", []).append(h)
                snap_ts = {x.get("ts") for x in data[name].get("risk_history", [])}
                for x in rec.get("risk_history", []):
                    if x.get("ts") not in snap_ts:
                        data[name].setdefault("risk_history", []).append(x)
                data[name]["history"].sort(key=lambda h: h.get("time", ""))
                data[name]["risk_history"].sort(key=lambda x: x.get("ts", ""))
            else:
                data[name] = rec
                added += 1
        self._save(data)
        return added


# ============================================================
# 二、AI建议下一步动作（规则版，零LLM）
# ============================================================

# 风险类型 → 建议重点（真实动作描述，不编造学生情况）
_FOCUS_BY_TYPE = {
    "参与度风险": ["了解近期课程参与情况，确认听课异常的具体原因",
                "与家长同步具体哪些讲次听课无效，约定补看回放安排",
                "确认孩子近期在家学习的状态与时间安排"],
    "练习执行风险": ["了解练习未提交的具体原因（难度、时间还是意愿）",
                  "与孩子约定每周练习完成的时间节点",
                  "同步练习提交对课程效果巩固的重要性"],
    "学习效果风险": ["同步具体讲次的答题正确率与练习得分数据",
                  "了解孩子在哪些知识点上感觉吃力",
                  "约定错题订正与薄弱点讲解安排"],
    "趋势变化风险": ["同步近期指标变化的具体数据（哪些维度、变化幅度）",
                  "了解近期状态变化可能的原因（只询问，不预设）",
                  "确认是否需要调整当前学习安排"],
    "数据异常/待确认": ["先核实具体问题讲次的真实情况再判断",
                     "确认数据记录是否存在缺漏或延迟"],
}


def suggest_next_action(insight: dict, record: dict = None) -> dict:
    """根据风险等级/类型/趋势/跟进历史给出建议跟进动作（纯规则，全部真实数据依据）。

    Returns: {action, urgency, urgency_color, focus_points[], basis}
    """
    if not insight:
        return {"action": "暂无数据，无法判断", "urgency": "低", "urgency_color": "#9E9E9E",
                "focus_points": ["当前无有效学情数据，建议人工确认"], "basis": "无数据"}
    priority = str(insight.get("priority", ""))
    risk_type = insight.get("risk_type")
    trend = insight.get("trend") or {}
    t_symbol = trend.get("summary_symbol", "？")
    t_patterns = trend.get("patterns", {}) or {}

    record = record or {}
    status = record.get("status") or default_status_for(priority)
    next_date = record.get("next_followup_date")
    last_result = record.get("followup_result")
    today = now_cn().strftime("%Y-%m-%d")

    # ---- 紧急度 ----
    if "P1" in priority:
        urgency, u_color = "高", "#E53935"
    elif "P2" in priority:
        urgency, u_color = ("高", "#E53935") if t_symbol == "↘" else ("中", "#F57C00")
    elif "P3" in priority:
        urgency, u_color = "中", "#F57C00"
    else:
        urgency, u_color = "低", "#43A047"
    # 超时/到点提升紧急度
    if status == STATUS_CONTACTED and next_date and next_date <= today:
        urgency, u_color = "高", "#E53935"

    # ---- 建议动作 ----
    if status == STATUS_SKIP:
        action = "暂不需要跟进（保持常规关注）"
    elif last_result == "家长暂未接通" and status == STATUS_PENDING:
        action = "今日换时段再次电话（上次未接通）"
        urgency, u_color = "高", "#E53935"
    elif status == STATUS_CONTACTED:
        # 数据回流后已缓解 → 收敛为常规关注
        if risk_change_label(record, insight.get("risk_score", 0))["key"] == "relieved":
            action = "风险已缓解，保持常规关注即可"
            urgency, u_color = "低", "#43A047"
        elif next_date:
            if next_date <= today:
                action = "今日复查：观察期已到点"
            else:
                try:
                    datetime.strptime(next_date, "%Y-%m-%d")
                    action = f"观察期内，{next_date} 复查学习数据"
                except ValueError:
                    action = f"观察期内，{next_date} 复查学习数据"
        else:
            action = "观察期内，3天内复查学习数据"
    elif status == STATUS_DONE:
        chg = risk_change_label(record, insight.get("risk_score", 0))
        if chg["key"] == "relieved":
            action = "风险已缓解，保持常规关注即可"
            urgency, u_color = "低", "#43A047"
        else:
            action = "复查最新学习数据，确认改善是否持续"
    else:  # 待联系
        if "P1" in priority:
            action = "今日电话跟进"
        elif "P2" in priority:
            action = "48小时内电话/微信跟进"
        elif "P3" in priority:
            action = "本周内微信跟进"
        else:
            action = "暂不需要跟进（保持常规关注）"

    # ---- 建议重点（风险类型 + 趋势 + 不一致 + 跟进历史修正） ----
    focus = list(_FOCUS_BY_TYPE.get(risk_type, [])) if risk_type else []
    if not focus:
        focus = ["当前5维指标未触发风险规则，保持常规关注即可"]
    if insight.get("inconsistency", {}).get("inconsistent"):
        focus = [f"汇总指标较好但存在{insight['inconsistency'].get('problem_count', 0)}个问题讲次，"
                 "先核实情况，暂不作为持续性风险沟通"]
    if t_patterns.get("持续下降") or t_patterns.get("多维同步下降"):
        focus.append("确认指标下降的具体原因，判断当前回升/下降是否持续")
    elif t_symbol == "↗":
        focus.append("确认当前回升是否稳定，避免单次波动误判")
    if record.get("history"):
        focus.append("回顾上次沟通约定事项，避免重复询问")

    basis_parts = [priority or "未知等级"]
    if risk_type:
        basis_parts.append(risk_type)
    if t_symbol and t_symbol != "？":
        basis_parts.append(f"趋势{t_symbol}")
    if record.get("history"):
        basis_parts.append(f"已跟进{len(record['history'])}次")
    return {
        "action": action,
        "urgency": urgency,
        "urgency_color": u_color,
        "focus_points": focus[:4],
        "basis": " + ".join(basis_parts),
    }


# ============================================================
# 三、风险状态变化判断（跟进前 → 重新分析后）
# ============================================================

def risk_change_label(record: dict, current_score) -> dict:
    """对比上次分析快照与当前风险分，判断风险变化。

    Returns: {key, label, icon, color, detail}
      key: first(首次)/relieved(缓解)/worse(再次升高)/escalate(建议升级)/unresolved(未解除)/flat(持平)
    """
    current_score = float(current_score or 0)
    hist = (record or {}).get("risk_history", [])
    if len(hist) < 2:
        return {"key": "first", "label": "首次分析，暂无对比数据", "icon": "？", "color": "#9E9E9E",
                "detail": "上传最新行课数据并重新分析后，将自动对比风险变化"}

    # 最新快照即本次分析结果；若不匹配（旧数据渲染），取最后一条作为上次
    if float(hist[-1]["risk_score"]) == current_score:
        prev = float(hist[-2]["risk_score"])
    else:
        prev = float(hist[-1]["risk_score"])
    delta = current_score - prev

    # 连续未改善次数（从最近一次往前数"暂无改善"）
    unimproved = 0
    for h in reversed((record or {}).get("history", [])):
        if h.get("result") == "暂无改善":
            unimproved += 1
        else:
            break

    if delta <= -10:
        return {"key": "relieved", "label": f"风险已缓解（{prev:.0f}→{current_score:.0f}）",
                "icon": "🟢", "color": "#2E7D32",
                "detail": "风险分较上次分析明显下降，当前处理措施见效，进入观察状态"}
    if delta >= 5:
        return {"key": "worse", "label": f"风险再次升高（{prev:.0f}→{current_score:.0f}）",
                "icon": "🔴", "color": "#C62828",
                "detail": "风险分较上次分析上升，建议优先处理"}
    if unimproved >= 2:
        return {"key": "escalate", "label": "风险未解除，连续多次跟进未改善",
                "icon": "⚠️", "color": "#E65100",
                "detail": f"已连续{unimproved}次跟进暂无改善且风险分持平，建议升级处理（如调整学习方案/引入主讲或班主任）"}
    if abs(delta) < 5:
        return {"key": "unresolved", "label": f"风险未解除（{prev:.0f}→{current_score:.0f}，基本持平）",
                "icon": "🔴", "color": "#C62828",
                "detail": "跟进后风险分未见明显变化，继续按计划跟进"}
    return {"key": "flat", "label": f"风险分小幅变化（{prev:.0f}→{current_score:.0f}）",
            "icon": "🟡", "color": "#F9A825",
            "detail": "风险分小幅波动，持续观察"}


# ============================================================
# 四、今日待处理任务列表
# ============================================================

def build_task_list(results: list, insights: list, states: dict, today: str = None,
                    limit: int = 12) -> list:
    """构建今日待处理任务（按优先级排序）。

    分类（按紧急度排序）：
      0-已超时未跟进 / 0-风险再次升高 / 1-今日必须联系(P1待联系) / 1-今日复查(到点) /
      2-48小时内联系(P2待联系) / 3-本周内联系(P3待联系) / 4-待观察学员

    Returns: [{name, label, tag, tag_color, sort_key}]
    """
    today = today or now_cn().strftime("%Y-%m-%d")
    insight_map = {i["name"]: i for i in (insights or [])}
    tasks = []

    for r in results or []:
        name = r.get("学员姓名", "")
        priority = str(r.get("优先级", ""))
        if "P4" in priority:
            continue  # P4不进入待处理
        rec = (states or {}).get(name) or {}
        status = rec.get("status") or STATUS_PENDING
        next_date = rec.get("next_followup_date")
        score = r.get("风险分", 0)
        entry = None

        if status == STATUS_CONTACTED and next_date and next_date < today:
            overdue_days = _days_between(next_date, today)
            if risk_change_label(rec, score)["key"] == "escalate":
                entry = ("多次未改善·建议升级", "#E65100", 0)
            else:
                entry = ("已超时未跟进" + (f"{overdue_days}天" if overdue_days and overdue_days > 1 else ""),
                         "#C62828", 0)
        elif status == STATUS_CONTACTED and next_date == today:
            entry = ("今日复查", "#E65100", 1)
        elif status == STATUS_PENDING:
            chg = risk_change_label(rec, score)
            if chg["key"] == "worse":
                entry = ("风险再次升高", "#C62828", 0)
            elif "P1" in priority:
                entry = ("今日必须联系", "#C62828", 1)
            elif "P2" in priority:
                entry = ("48小时内联系", "#E65100", 2)
            else:
                entry = ("本周内联系", "#F9A825", 3)
        elif status == STATUS_CONTACTED:
            entry = ("待观察", "#F9A825", 4)
        # 已完成跟进/暂不需要跟进：不进任务列表

        if entry:
            tag, color, rank = entry
            tasks.append({
                "name": name,
                "label": f"{name}｜{tag}",
                "tag": tag,
                "tag_color": color,
                "sort_key": (rank, -float(score or 0)),
            })

    tasks.sort(key=lambda t: t["sort_key"])
    return tasks[:limit]


def _days_between(d1: str, d2: str):
    try:
        return (datetime.strptime(d2, "%Y-%m-%d") - datetime.strptime(d1, "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return None


# ============================================================
# 五、今日风险处理漏斗
# ============================================================

def compute_funnel(results: list, states: dict) -> dict:
    """今日风险处理漏斗（P1-P3占状态桶；P4中已闭环缓解的学员计入"风险缓解"）。

    Returns: {待联系, 已联系·待观察, 已完成跟进, 暂不需要跟进, 风险缓解}
      风险缓解 = 风险分较上次分析下降≥10 或 最近跟进结果为已解决
    """
    counts = {STATUS_PENDING: 0, STATUS_CONTACTED: 0, STATUS_DONE: 0, STATUS_SKIP: 0, "风险缓解": 0}
    for r in results or []:
        priority = str(r.get("优先级", ""))
        name = r.get("学员姓名", "")
        rec = (states or {}).get(name) or {}
        chg = risk_change_label(rec, r.get("风险分", 0))
        relieved = chg["key"] == "relieved" or rec.get("followup_result") == "已解决"

        if "P4" in priority:
            # P4不占状态桶；但"P1跟进后改善为P4"的闭环成果仍计入风险缓解
            if relieved and (rec.get("history") or len(rec.get("risk_history", [])) >= 2):
                counts["风险缓解"] += 1
            continue
        status = rec.get("status") or default_status_for(priority)
        if status in counts:
            counts[status] += 1
        if relieved:
            counts["风险缓解"] += 1
    return counts


# ============================================================
# 六、跟进后即时判断（规则版，零LLM；AI深度判断见 ai_comm_plan）
# ============================================================

def _trend_worsening(insight: dict) -> bool:
    t = (insight or {}).get("trend") or {}
    return t.get("summary_symbol") == "↘" or bool(
        t.get("patterns", {}).get("持续下降") or t.get("patterns", {}).get("多维同步下降"))


def rule_followup_judgment(method: str, result: str, feedback: str, note: str,
                           insight: dict = None) -> dict:
    """记录跟进后立即生成的判断（纯规则，基于跟进结果 + 真实学情数据）。

    Returns: {state_label, judgment, next_step, suggest_next_date, new_status, recheck_dim}
    """
    insight = insight or {}
    risk_type = insight.get("risk_type")
    recheck = RISK_RECHECK_DIMS.get(risk_type, "学习数据")
    trend_conclusion = (insight.get("trend") or {}).get("conclusion", "")
    trend_ref = f"结合当前学情趋势（{trend_conclusion}）" if trend_conclusion else "结合当前学情数据"
    today = now_cn()

    if result == "已解决":
        state = "🟢 风险信号缓解"
        judgment = (f"根据本次跟进反馈，核心问题已解决。{trend_ref}，当前不建议升级处理，"
                    "保持常规关注即可。")
        next_step = f"建议7天后复查{recheck}，确认改善持续。"
        days, new_status = 7, STATUS_DONE
    elif result == "部分改善":
        worsening = _trend_worsening(insight)
        state = "🟡 风险仍存在，但已有改善信号"
        if worsening:
            judgment = (f"本次跟进反馈已有改善迹象，但学情指标仍呈下降趋势（{trend_conclusion}），"
                        "改善尚不稳定，需持续关注。")
        else:
            judgment = f"根据本次跟进反馈已有改善迹象，{trend_ref}，当前不建议立即升级处理。"
        next_step = f"3天后重新查看{recheck}情况。"
        days, new_status = 3, STATUS_CONTACTED
    elif result == "暂无改善":
        worsening = _trend_worsening(insight)
        if worsening:
            state = "🔴 风险持续，且学情呈下降趋势"
            judgment = (f"本次跟进暂无改善，且学情指标呈下降趋势（{trend_conclusion}），"
                        "风险持续，建议升级为重点跟进对象。")
        else:
            state = "🔴 风险仍存在，暂未见改善"
            judgment = f"本次跟进暂无改善，{trend_ref}，当前未见明显恶化，建议调整沟通方式后再次跟进。"
        next_step = "建议48小时内结合最新学习数据再次联系。"
        days, new_status = 2, STATUS_CONTACTED
    elif result == "家长暂未接通":
        state = "⚪ 暂未联系上家长"
        judgment = "本次跟进未接通，暂无法判断家长反馈，学情风险维持当前判断。"
        next_step = "明日换时段再次电话，或先微信留言约定方便的时间。"
        days, new_status = 1, STATUS_PENDING
    elif result == "家长需要进一步观察":
        state = "🟡 观察期，待进一步确认"
        judgment = (f"家长需要进一步观察，{trend_ref}，建议按观察重点同步客观数据，"
                    "不做无依据的效果承诺。")
        next_step = f"按约定时间复查{recheck}，用具体数据向家长同步。"
        days, new_status = 3, STATUS_CONTACTED
    else:  # 其他
        state = "🟡 已完成本次跟进，情况待确认"
        judgment = f"已记录本次跟进结果，{trend_ref}，持续关注后续变化。"
        next_step = "建议3天内跟进确认情况。"
        days, new_status = 3, STATUS_CONTACTED

    return {
        "state_label": state,
        "judgment": judgment,
        "next_step": next_step,
        "suggest_next_date": (today + timedelta(days=days)).strftime("%Y-%m-%d"),
        "new_status": new_status,
        "recheck_dim": recheck,
    }


def gen_task_id() -> str:
    return f"rfu_{now_cn().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
