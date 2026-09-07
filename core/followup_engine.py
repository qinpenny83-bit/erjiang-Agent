# -*- coding: utf-8 -*-
"""沟通跟进引擎 — Tab2「沟通跟进中心」（纯逻辑层，不含UI）

职责：围绕Tab2家校沟通场景建立"沟通后的持续跟进"闭环：
记录沟通结果 → AI生成跟进计划 → 加入跟进中心 → 到期提醒 → 完成跟进 →（循环跟进）

==== 边界约定（不可违反）====
1. 只服务于Tab2沟通场景，不与Tab1风险处理中心联动
2. AI生成计划只基于真实输入（家长问题/分析摘要/沟通结果/备注），禁止编造学生情况
3. AI生成失败或字段不完整时，自动降级为规则引擎兜底，绝不输出残缺计划
4. 跟进数据存 data/followups.json（已被 .gitignore 排除，含真实学员姓名不入库）

==== 跟进时间基准规则（规则引擎兜底，AI可微调）====
- 家长仍有疑虑 → 24小时内
- 未接通 → 次日再次联系
- 家长暂时忙碌 → 按约定时间（无约定默认次日）
- 家长认可方案 → 5天后关注执行情况（3~7天区间取中）
- 学习问题已明确 → 3天左右跟进改善情况
- 需要进一步跟进 → 根据备注确定（无备注默认3天）
- 已成功沟通 → 7天后常规回访
- 家长明确拒绝 → 冷却14天关怀跟进（不直接关闭）
- 其他 → 根据备注确定（无备注默认3天）
"""
import os
import re
import json
import random
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, DATA_DIR
from core.prompt_utils import append_constraints

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

FOLLOWUP_FILE = os.path.join(DATA_DIR, "followups.json")

# 北京时间（Streamlit Cloud容器为UTC，必须显式+8h，否则"今日待跟进"边界错位8小时）
_CN_TZ = timezone(timedelta(hours=8))


def now_cn() -> datetime:
    """当前北京时间（naive形式，与本地开发环境一致）"""
    return datetime.now(_CN_TZ).replace(tzinfo=None)


# ============================================================
# 常量：沟通结果枚举（9种）与规则引擎兜底配置
# ============================================================

COMM_RESULTS = [
    "已成功沟通",
    "家长认可方案",
    "家长仍有疑虑",
    "家长暂时忙碌",
    "未接通",
    "学习问题已明确",
    "需要进一步跟进",
    "家长明确拒绝",
    "其他",
]

# 规则引擎兜底：hours优先于days；goal/focus为模板（禁止编造学生情况，只描述动作）
TIME_RULES = {
    "家长仍有疑虑":   {"hours": 24, "priority": "高", "goal": "24小时内二次跟进，优先化解家长疑虑",
                     "focus": "上次沟通中家长未被打消的顾虑点", "reminder": "疑虑未化解前，避免主动提及续费"},
    "未接通":         {"hours": 24, "priority": "高", "goal": "次日换时段再次联系家长",
                     "focus": "确认家长方便接听的时间段", "reminder": "连续未接通时改用文字留言，避免频繁拨打引起反感"},
    "家长暂时忙碌":   {"hours": 24, "priority": "中", "goal": "按约定时间再次沟通",
                     "focus": "家长上次提到的忙碌原因，择机沟通", "reminder": "提前发消息约定时间，避免再次扑空"},
    "家长认可方案":   {"days": 5, "priority": "低", "goal": "跟进方案执行情况，巩固家长信任",
                     "focus": "已认可方案的落实进度与孩子反馈", "reminder": "以正向反馈为主，让家长感知服务在持续"},
    "学习问题已明确": {"days": 3, "priority": "中", "goal": "跟进学习改善情况，同步进展",
                     "focus": "已明确问题的改善迹象", "reminder": "无数据支撑时不做效果承诺，用具体事实说话"},
    "需要进一步跟进": {"days": 3, "priority": "中", "goal": "按约定进行二次跟进",
                     "focus": "上次沟通约定的事项", "reminder": "跟进前先回顾上次沟通结论，避免重复询问"},
    "已成功沟通":     {"days": 7, "priority": "低", "goal": "常规回访，同步学习近况",
                     "focus": "家长对近期服务的感知", "reminder": "保持自然关怀，无需过度推销"},
    "家长明确拒绝":   {"days": 14, "priority": "低", "goal": "冷却期后关怀式跟进，保持联系留出转机",
                     "focus": "记录的拒绝原因，冷却后针对性关怀", "reminder": "不直接关闭跟进，也绝不反复施压"},
    "其他":           {"days": 3, "priority": "中", "goal": "根据备注情况安排跟进",
                     "focus": "备注中提到的待办事项", "reminder": "跟进前确认备注中的关键信息"},
}

PRIORITIES = ("高", "中", "低")


def _rule_followup_at(comm_result: str, base: datetime = None) -> datetime:
    """规则引擎计算跟进时间（未接通/忙碌约定"次日"语义：次日同时段，并修正到合理联系时段）"""
    base = base or now_cn()
    rule = TIME_RULES.get(comm_result, TIME_RULES["其他"])
    if rule.get("next_day"):
        dt = (base + timedelta(days=1)).replace(hour=19, minute=0)
    elif "hours" in rule:
        dt = base + timedelta(hours=rule["hours"])
    else:
        dt = base + timedelta(days=rule["days"])
    # 修正到合理联系时段：避开深夜/凌晨（8:00-21:00）
    if dt.hour < 8:
        dt = dt.replace(hour=9, minute=0)
    elif dt.hour >= 21:
        dt = (dt + timedelta(days=1)).replace(hour=9, minute=0)
    return dt


# 给规则表补充 next_day 语义标记
TIME_RULES["未接通"]["next_day"] = True
TIME_RULES["家长暂时忙碌"]["next_day"] = True


def _rule_plan(comm_result: str, base: datetime = None) -> dict:
    """规则引擎兜底计划（AI失败/字段不完整时使用）"""
    base = base or now_cn()
    rule = TIME_RULES.get(comm_result, TIME_RULES["其他"])
    return {
        "followup_at": _rule_followup_at(comm_result, base),
        "priority": rule["priority"],
        "goal": rule["goal"],
        "focus": rule["focus"],
        "reminder": rule["reminder"],
        "time_basis": f"规则引擎兜底（{comm_result}基准规则）",
        "source": "rule",
    }


# ============================================================
# 计划时间解析与校验
# ============================================================

def parse_plan_time(text: str, base: datetime = None) -> datetime:
    """从AI输出中解析建议跟进时间；支持完整/仅日期/相对表达（明天、3天后）；失败返回None"""
    base = base or now_cn()
    if not text:
        return None
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?\s*(\d{1,2})[:：时](\d{1,2})?", text)
    if not m:
        m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?", text)
        if not m:
            return _parse_relative_time(text, base)
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 19, 0)
        except ValueError:
            return None
    else:
        hour = int(m.group(4))
        minute = int(m.group(5)) if m.group(5) is not None else 0
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), hour, minute)
        except ValueError:
            return None
    # 时间必须在未来（允许1小时内误差），过去时间视为无效
    if dt < base - timedelta(hours=1):
        return None
    return dt


def _parse_relative_time(text: str, base: datetime) -> datetime:
    """相对时间解析兜底：明天/次日/后天/大后天/N天后 + 时:分"""
    days = None
    m = re.search(r"(明天|次日|后天|大后天)", text)
    if m:
        days = {"明天": 1, "次日": 1, "后天": 2, "大后天": 3}[m.group(1)]
    else:
        m = re.search(r"(\d{1,2})\s*天[后後]", text)
        if m:
            days = int(m.group(1))
    if days is None:
        return None
    hm = re.search(r"(\d{1,2})[:：时](\d{1,2})?分?", text)
    hour = int(hm.group(1)) if hm else 19
    minute = int(hm.group(2) or 0) if hm else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        hour, minute = 19, 0
    try:
        dt = (base + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None
    if dt < base - timedelta(hours=1):
        return None
    return dt


def _plan_is_valid(plan: dict, base: datetime = None) -> bool:
    """计划完整性校验：时间可解析+优先级合法+四个内容字段非空"""
    base = base or now_cn()
    if not isinstance(plan, dict):
        return False
    dt = plan.get("followup_at")
    if not isinstance(dt, datetime):
        return False
    # 跟进时间不晚于90天，不早于当前-1h
    if dt < base - timedelta(hours=1) or dt > base + timedelta(days=90):
        return False
    if plan.get("priority") not in PRIORITIES:
        return False
    for k in ("goal", "focus", "reminder"):
        v = (plan.get(k) or "").strip()
        if not v or len(v) < 4:
            return False
    return True


# ============================================================
# AI跟进计划生成（v4-flash，3次重试+完整性校验，失败规则兜底）
# ============================================================

def _extract_fields_plan(text: str) -> dict:
    """解析AI输出的字段行（容忍emoji/markdown加粗/列表符号/全角冒号）"""
    fields = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 去掉行首列表符号/序号/markdown符号
        line = re.sub(r"^[\s\-\*·•#>]+", "", line)
        line = re.sub(r"^\d+[\.、）)]\s*", "", line)
        m = re.match(r"^\*{0,2}([^*：:]{2,10})\*{0,2}\s*[：:]\s*(.+)$", line)
        if m:
            key = m.group(1).strip().replace(" ", "").replace("*", "")
            val = m.group(2).strip().strip("*")
            if key:
                fields[key] = val
    return fields


def _call_llm(prompt: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.3,
        max_tokens=900,
        timeout=60,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()


def generate_followup_plan(student_name: str, question: str, analysis_summary: str,
                           stage: str, comm_result: str, note: str) -> dict:
    """生成跟进计划：AI优先（3次重试），失败/不完整自动降级规则引擎。

    返回字段：followup_at(datetime)/priority/goal/focus/reminder/time_basis/source(ai|rule)
    """
    base = now_cn()
    prompt_tpl = _load_prompt()
    prompt = (prompt_tpl
              .replace("{student_name}", student_name or "（未提供）")
              .replace("{question}", question or "（未提供）")
              .replace("{analysis_summary}", analysis_summary or "（无）")
              .replace("{stage}", stage or "未知")
              .replace("{comm_result}", comm_result or "其他")
              .replace("{note}", note.strip() if note and note.strip() else "（无备注）")
              .replace("{now}", base.strftime("%Y-%m-%d %H:%M")))

    for attempt in range(3):
        try:
            raw = _call_llm(prompt)
            fields = _extract_fields_plan(raw)
            dt = parse_plan_time(fields.get("建议跟进时间", ""), base)
            if dt is None:
                print(f"[Followup] 第{attempt + 1}次时间解析失败: {fields.get('建议跟进时间', '')!r}")
                continue
            priority = fields.get("跟进优先级", "").strip()
            if priority not in PRIORITIES:
                # 容错：包含高/中/低字样即可
                priority = next((p for p in PRIORITIES if p in priority), "")
            plan = {
                "followup_at": dt,
                "priority": priority,
                "goal": fields.get("本次跟进目标", ""),
                "focus": fields.get("下一次重点关注内容", ""),
                "reminder": fields.get("跟进提醒", ""),
                "time_basis": fields.get("时间依据", "AI结合沟通情况生成"),
                "source": "ai",
            }
            if _plan_is_valid(plan, base):
                return plan
            print(f"[Followup] 第{attempt + 1}次计划不完整，重试")
        except Exception as e:
            print(f"[Followup] AI生成异常(第{attempt + 1}次): {type(e).__name__}: {e}")

    print("[Followup] AI生成失败，使用规则引擎兜底")
    return _rule_plan(comm_result, base)


_prompt_cache = None


def _load_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "followup_plan.txt")
        with open(path, "r", encoding="utf-8") as f:
            _prompt_cache = append_constraints(f.read())
    return _prompt_cache


def build_analysis_summary(qa_result: dict) -> str:
    """从Tab2六段式结果中提炼紧凑分析摘要（供跟进计划生成复用，仅取真实字段）"""
    if not isinstance(qa_result, dict):
        return ""
    diag = qa_result.get("问题判断", {}) or {}
    parts = []
    for key, label in (("表层问题", "表层问题"), ("核心诉求", "核心诉求"),
                       ("情绪状态", "家长情绪"), ("沟通阶段", "沟通阶段")):
        v = (diag.get(key) or "").strip() if isinstance(diag, dict) else ""
        if v:
            parts.append(f"{label}：{v}")
    facts = diag.get("已知事实") or []
    if facts:
        parts.append("已知事实：" + "；".join(str(f) for f in facts[:3]))
    return "\n".join(parts)


# ============================================================
# 跟进任务存储（JSON文件，原子写入）
# ============================================================

class FollowupStore:
    """跟进任务JSON存储：load/add/complete/delay/delete/import_merge"""

    def __init__(self, path: str = None):
        self.path = path or FOLLOWUP_FILE
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    # ---------- 基础读写 ----------
    def load(self) -> list:
        try:
            if not os.path.exists(self.path):
                return []
            with open(self.path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"[FollowupStore] 读取失败，按空处理: {type(e).__name__}: {e}")
            return []

    def _save(self, tasks: list):
        # 原子写入：先写临时文件再替换，避免写入中断导致数据损坏
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---------- 任务操作 ----------
    def add(self, task: dict) -> str:
        tasks = self.load()
        tasks.append(task)
        self._save(tasks)
        return task["id"]

    def _find(self, tasks: list, task_id: str):
        for i, t in enumerate(tasks):
            if t.get("id") == task_id:
                return i
        return -1

    def update(self, task_id: str, **fields):
        tasks = self.load()
        i = self._find(tasks, task_id)
        if i < 0:
            return False
        tasks[i].update(fields)
        self._save(tasks)
        return True

    def complete(self, task_id: str, record: dict = None):
        """标记完成；record为本次完成时的沟通记录（结果/备注）"""
        tasks = self.load()
        i = self._find(tasks, task_id)
        if i < 0:
            return False
        t = tasks[i]
        t["status"] = "已完成"
        t["completed_at"] = now_cn().strftime("%Y-%m-%d %H:%M")
        if record:
            t.setdefault("history", []).append(record)
        self._save(tasks)
        return True

    def delay(self, task_id: str, new_dt: datetime, reason: str = ""):
        tasks = self.load()
        i = self._find(tasks, task_id)
        if i < 0:
            return False
        t = tasks[i]
        t["followup_at"] = new_dt.strftime("%Y-%m-%d %H:%M")
        t["delayed_count"] = int(t.get("delayed_count", 0)) + 1
        if reason:
            t["history"] = t.get("history", []) + [{
                "time": now_cn().strftime("%Y-%m-%d %H:%M"),
                "result": "延后跟进",
                "note": reason,
            }]
        self._save(tasks)
        return True

    def delete(self, task_id: str):
        tasks = self.load()
        i = self._find(tasks, task_id)
        if i < 0:
            return False
        tasks.pop(i)
        self._save(tasks)
        return True

    def import_merge(self, imported: list) -> int:
        """合并导入备份数据（按id去重），返回新增条数"""
        tasks = self.load()
        existing_ids = {t.get("id") for t in tasks}
        added = 0
        for t in imported:
            if isinstance(t, dict) and t.get("id") and t.get("id") not in existing_ids:
                tasks.append(t)
                existing_ids.add(t.get("id"))
                added += 1
        if added:
            self._save(tasks)
        return added

    def export_data(self) -> str:
        return json.dumps(self.load(), ensure_ascii=False, indent=2)


# ============================================================
# 任务构建与分组
# ============================================================

def new_task(student_name: str, question: str, plan: dict, comm_result: str,
             note: str, stage: str, analysis_summary: str) -> dict:
    """构建跟进任务（plan来自generate_followup_plan）"""
    ts = now_cn().strftime("%Y%m%d_%H%M%S")
    task_id = f"fu_{ts}_{random.randint(1000, 9999)}"
    return {
        "id": task_id,
        "student_name": (student_name or "").strip() or "未命名学员",
        "question": (question or "").strip(),
        "comm_result": comm_result,
        "note": (note or "").strip(),
        "stage": stage or "",
        "analysis_summary": analysis_summary or "",
        "priority": plan.get("priority", "中"),
        "followup_at": plan["followup_at"].strftime("%Y-%m-%d %H:%M"),
        "goal": plan.get("goal", ""),
        "focus": plan.get("focus", ""),
        "reminder": plan.get("reminder", ""),
        "time_basis": plan.get("time_basis", ""),
        "plan_source": plan.get("source", "rule"),
        "status": "待跟进",
        "created_at": now_cn().strftime("%Y-%m-%d %H:%M"),
        "completed_at": None,
        "delayed_count": 0,
        "history": [{
            "time": now_cn().strftime("%Y-%m-%d %H:%M"),
            "result": comm_result,
            "note": (note or "").strip() or "（无备注）",
        }],
    }


def parse_task_time(t: dict) -> datetime:
    try:
        return datetime.strptime(t.get("followup_at", ""), "%Y-%m-%d %H:%M")
    except ValueError:
        return now_cn() + timedelta(days=365)  # 无效时间归入"即将跟进"末尾


def group_tasks(tasks: list, base: datetime = None) -> dict:
    """按状态分组：today(今日含超时)/upcoming(即将)/done(已完成)"""
    base = base or now_cn()
    today, upcoming, done = [], [], []
    for t in tasks:
        if t.get("status") == "已完成":
            done.append(t)
        else:
            dt = parse_task_time(t)
            (today if dt.date() <= base.date() else upcoming).append(t)
    today.sort(key=parse_task_time)
    upcoming.sort(key=parse_task_time)
    done.sort(key=lambda t: t.get("completed_at") or "", reverse=True)
    return {"today": today, "upcoming": upcoming, "done": done}


def task_display_status(t: dict, base: datetime = None) -> str:
    """展示状态：待跟进/已超时/已完成"""
    if t.get("status") == "已完成":
        return "已完成"
    base = base or now_cn()
    return "已超时" if parse_task_time(t) < base else "待跟进"
