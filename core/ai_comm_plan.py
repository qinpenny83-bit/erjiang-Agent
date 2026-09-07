# -*- coding: utf-8 -*-
"""风险优先处理中心 — AI层（按需调用，规则兜底）

职责（只在老师点击按钮时调用，不为每学员自动调用）：
1. generate_comm_plan        生成沟通方案（开场/核心沟通/家长可能反馈/老师应对/收尾，5模块）
2. generate_followup_judgment AI深度跟进判断（当前状态/AI判断/下一步，3模块）

证据边界：输入上下文全部来自系统真实计算结果与老师真实录入；输出校验模块完整性，
失败重试，仍失败自动降级规则版（零编造），绝不输出残缺方案。
"""
import os
import re
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from core.prompt_utils import append_constraints
from core.risk_followup_center import rule_followup_judgment, suggest_next_action

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

MAX_RETRY = 3
PLAN_MODULES = ["开场", "核心沟通", "家长可能反馈", "老师应对", "收尾"]
JUDGMENT_MODULES = ["当前状态", "AI判断", "下一步"]


def _load_prompt(name: str) -> str:
    prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    with open(os.path.join(prompt_dir, name), "r", encoding="utf-8") as f:
        return append_constraints(f.read())


def _call_llm(prompt: str, temperature: float = 0.4, max_tokens: int = 2200,
              system_msg: str = "") -> str:
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=90,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


# ============================================================
# 上下文构建（全部真实数据）
# ============================================================

def _build_risk_context(ins: dict) -> str:
    """学员真实学情数据块（与规则引擎同源）"""
    lines = [f"学员：{ins['name']}｜{ins['priority']}｜风险分{ins['risk_score']}"]
    lines.append(f"5维指标：{ins['metrics_brief']}")
    lines.append(f"异常汇总：{ins['anomalies_brief']}")
    t = ins["trend"]
    for d, td in t["dims"].items():
        lines.append(f"  {d}：{td['symbol']}{td['trend']}（{td['detail']}）")
    lines.append(f"趋势结论：{t['conclusion']}")
    if ins.get("risk_type"):
        lines.append(f"主要风险类型：{ins['risk_type']}（触发：{'、'.join(ins['risk_triggers'])}）")
    if ins["problem_count"] > 0:
        lines.append(f"问题讲次明细（共{ins['problem_count']}项异常，最多列6讲）：")
        for p in ins["problem_lectures"][:6]:
            issues = "；".join(f"{i['type']}（{i['data']}）" for i in p["issues"])
            title = f"《{p['title']}》" if p.get("title") else ""
            lines.append(f"  {p['lecture']}{title}：{issues}")
        if ins["problem_count"] > 6:
            lines.append(f"  ……其余{ins['problem_count'] - 6}项略")
    if ins["inconsistency"].get("inconsistent"):
        lines.append(f"数据与风险不一致提示：{ins['inconsistency']['message']}")
    return "\n".join(lines)


def _build_followup_context(record: dict = None) -> str:
    """已有跟进记录（真实录入，无记录时明确说明）"""
    if not record or not record.get("history"):
        return "当前跟进状态：首次跟进，暂无历史沟通记录。"
    lines = [f"当前跟进状态：{record.get('status', '待联系')}"]
    if record.get("next_followup_date"):
        lines.append(f"计划下次跟进：{record['next_followup_date']}")
    hist = record["history"]
    last = hist[-1]
    lines.append(f"最近一次跟进：{last.get('time')}，方式{last.get('method')}，"
                 f"结果「{last.get('result')}」"
                 + (f"，家长反馈：{last.get('feedback')}" if last.get("feedback") else ""))
    for h in hist[-3:-1]:
        lines.append(f"更早跟进 {h.get('time')}：{h.get('method')}，{h.get('result')}"
                     + (f"，反馈：{h.get('feedback')}" if h.get("feedback") else ""))
    return "\n".join(lines)


# ============================================================
# 一、沟通方案（5模块）
# ============================================================

def _plan_complete(text: str) -> bool:
    if not text or len(text) < 300:
        return False
    return all(f"【{m}】" in text for m in PLAN_MODULES)


def _rule_comm_plan(ins: dict, record: dict = None) -> str:
    """规则版沟通方案兜底（零编造，全部真实数据模板化）"""
    name = ins["name"]
    t = ins["trend"]
    risk_type = ins.get("risk_type")

    # 开场：带具体数据切入
    if ins["problem_lectures"]:
        p = ins["problem_lectures"][0]
        issue_str = "、".join(i["type"] for i in p["issues"])
        opening = (f"「{name}家长您好，我是孩子的二讲老师。看了下最近的行课数据，"
                   f"{p['lecture']}（{issue_str}）这块有点情况，想跟您同步一下。」")
    else:
        opening = f"「{name}家长您好，我是孩子的二讲老师。想跟您同步一下孩子最近的学习数据。」"

    # 核心沟通：真实数据翻译
    core = (f"「从数据上看：{ins['anomalies_brief']}。整体情况：{ins['metrics_brief']}。"
            f"趋势方面，{t['conclusion']}。」")

    # 家长可能反馈（标注可能方向）
    feedback = ("1. 觉得是近期状态波动，过阵子就好（可能方向，以家长真实反馈为准）\n"
                "2. 反映孩子时间安排紧张或课程有难度（可能方向，以家长真实反馈为准）\n"
                "3. 反馈孩子在家的实际听课/作业情况与数据不符（可能方向，以家长真实反馈为准）")

    # 老师应对（分方向）
    if risk_type == "参与度风险":
        response = ("1. 若是状态波动：跟孩子约定本周补看回放的具体时间，3天后我复查听课数据；\n"
                    "2. 若是时间紧张：帮孩子排一个可执行的听课计划，优先保证直播；\n"
                    "3. 若与数据不符：请家长帮忙确认孩子实际听课环境，我这边同步核实数据。")
        closing_topic = "补看计划"
    elif risk_type == "练习执行风险":
        response = ("1. 若是状态波动：约定本周把未提交练习补上，每天固定时间完成；\n"
                    "2. 若是难度问题：我整理对应讲次的讲解回放和基础题，先做基础巩固；\n"
                    "3. 若与数据不符：请家长确认孩子作业提交渠道是否正常，我这边排查。")
        closing_topic = "练习补交计划"
    elif risk_type == "学习效果风险":
        response = ("1. 若是知识点没吃透：我安排错题订正+对应讲次重听，针对薄弱点讲解；\n"
                    "2. 若是练习不认真：跟孩子约定做题规范，先保证正确率再提速；\n"
                    "3. 若家长有其他判断：我们一起看具体讲次的数据再定方案。")
        closing_topic = "错题订正安排"
    elif risk_type == "数据异常/待确认":
        response = ("1. 先跟家长同步具体问题讲次的情况，确认孩子当时的实际状态；\n"
                    "2. 若数据确实异常：我这边核实数据记录，避免误判；\n"
                    "3. 若确有问题：我们再一起商定针对性安排。")
        closing_topic = "情况核实"
    else:
        response = ("1. 跟家长同步近期指标变化的具体数据，一起分析可能原因；\n"
                    "2. 约定本周重点关注1-2项指标，我定期同步数据；\n"
                    "3. 若家长有补充信息，我们再调整安排。")
        closing_topic = "重点关注安排"

    closing = f"「那咱们先按{closing_topic}来，我3天后把孩子这边的最新数据再同步给您。」"

    return (f"【开场】\n{opening}\n\n"
            f"【核心沟通】\n{core}\n\n"
            f"【家长可能反馈】\n{feedback}\n\n"
            f"【老师应对】\n{response}\n\n"
            f"【收尾】\n{closing}\n\n"
            "（本方案由规则引擎基于真实数据生成，可点击重新生成AI版本）")


def generate_comm_plan(ins: dict, record: dict = None, ai_insight: dict = None) -> str:
    """生成沟通方案：AI优先（3次重试+5模块完整性校验），失败自动降级规则版。"""
    if not ins:
        return "暂无学员数据，无法生成沟通方案。"
    try:
        next_act = suggest_next_action(ins, record)
        next_str = f"{next_act['action']}（优先级{next_act['urgency']}）"
    except Exception:
        next_str = "（建议动作生成失败，见风险处理卡）"

    # AI洞察若存在则附加（同样为真实数据校验后的输出）
    ai_extra = ""
    if ai_insight and ai_insight.get("风险解释"):
        ai_extra = (f"\nAI风险洞察参考（真实数据校验版）：主要风险{ai_insight.get('主要风险', '')}；"
                    f"风险解释：{ai_insight.get('风险解释', '')}")

    template = _load_prompt("risk_comm_plan.txt")
    prompt = (template
              .replace("{risk_context}", _build_risk_context(ins) + ai_extra)
              .replace("{followup_context}", _build_followup_context(record))
              .replace("{next_action}", next_str))

    for attempt in range(MAX_RETRY):
        try:
            raw = _call_llm(
                prompt, temperature=0.4, max_tokens=2200,
                system_msg="你是一位有5年经验的高途二讲老师。严格基于真实数据写沟通方案，"
                           "真人沟通感，禁止AI腔和模板套话，禁止编造。")
            if _plan_complete(raw):
                return raw
            missing = [m for m in PLAN_MODULES if f"【{m}】" not in raw]
            print(f"[CommPlan] 第{attempt + 1}次方案不完整（缺{missing}），重试")
        except Exception as e:
            print(f"[CommPlan] AI异常(第{attempt + 1}次): {type(e).__name__}: {e}")

    print("[CommPlan] AI生成失败，使用规则版方案兜底")
    return _rule_comm_plan(ins, record)


# ============================================================
# 二、AI深度跟进判断（3模块，规则版即时判断之外的增强）
# ============================================================

def _judgment_complete(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    return all(f"【{m}】" in text for m in JUDGMENT_MODULES)


def _format_rule_judgment(rule_j: dict) -> str:
    return (f"【当前状态】\n{rule_j['state_label']}\n\n"
            f"【AI判断】\n{rule_j['judgment']}\n\n"
            f"【下一步】\n{rule_j['next_step']}")


def generate_followup_judgment(method: str, result: str, feedback: str, note: str,
                               ins: dict, record: dict = None) -> str:
    """AI深度跟进判断：3次重试+模块校验，失败降级规则版（即时判断同源）。"""
    rule_j = rule_followup_judgment(method, result, feedback, note, ins)
    if not ins:
        return _format_rule_judgment(rule_j)

    template = _load_prompt("followup_judgment.txt")
    prompt = (template
              .replace("{risk_context}", _build_risk_context(ins))
              .replace("{method}", method or "未填写")
              .replace("{result}", result or "未填写")
              .replace("{feedback}", (feedback or "").strip() or "（本次未记录家长反馈）")
              .replace("{note}", (note or "").strip() or "（无）"))

    for attempt in range(MAX_RETRY):
        try:
            raw = _call_llm(
                prompt, temperature=0.3, max_tokens=800,
                system_msg="你是高途在线教育资深学情风险分析师。严格基于真实数据判断，"
                           "禁止编造家长心理与学生情况。")
            if _judgment_complete(raw):
                return raw
            missing = [m for m in JUDGMENT_MODULES if f"【{m}】" not in raw]
            print(f"[FuJudge] 第{attempt + 1}次判断不完整（缺{missing}），重试")
        except Exception as e:
            print(f"[FuJudge] AI异常(第{attempt + 1}次): {type(e).__name__}: {e}")

    print("[FuJudge] AI生成失败，使用规则版判断兜底")
    return _format_rule_judgment(rule_j)
