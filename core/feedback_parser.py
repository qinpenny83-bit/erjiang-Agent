# -*- coding: utf-8 -*-
"""🤖 AI自动理解老师输入 — 家长反馈结构化解析

老师完成沟通后，只需把家长原话（如"家长说孩子最近作业多，练习时间少，
但课程还是认可的，让我们先观察一下"）粘贴进来，本模块自动提取：

家长态度 / 当前问题 / 风险是否解除 / 改善可能性 / 建议动作 / 下一动作

==== 设计原则（不可违反）====
1. 只能从老师输入的原文中提取关键词，禁止补造家长没说过的话
2. 规则引擎优先（零大模型调用，透明可追溯）；AI增强失败时自动兜底规则结果
3. 无法判断的字段明确输出「未明确」/「暂无数据」，不得强行下结论
4. 所有结论可回指原文关键词，供UI展示"依据"
"""
import json
import re

from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME

_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# ============================================================
# 规则引擎：关键词 → 结构化字段
# ============================================================

_ATTITUDE_RULES = [
    ("认可", ["认可", "满意", "不错", "挺好", "支持", "信任", "觉得好", "反馈好", "肯定", "夸"]),
    ("疑虑", ["疑虑", "担心", "顾虑", "怀疑", "不信", "犹豫", "观望", "再看看", "考虑考虑"]),
    ("消极", ["不满", "抱怨", "生气", "失望", "质疑", "投诉", "不满意", "没效果", "白花钱"]),
    ("时间不足", ["作业多", "时间少", "没时间", "太忙", "顾不上", "精力有限", "任务重"]),
]

_PROBLEM_RULES = [
    ("时间不足", ["作业多", "时间少", "没时间", "太忙", "顾不上", "精力有限", "任务重", "课业重"]),
    ("学习效果不明显", ["没效果", "效果不明显", "提升不明显", "进步小", "没进步", "没变化", "白学"]),
    ("练习执行不足", ["练习少", "没练", "不练", "作业没做", "没提交", "不做练习"]),
    ("听课时长不足", ["听课少", "没听课", "不看回放", "补课", "时长不够", "缺课"]),
    ("成绩下滑", ["成绩下降", "退步", "考得不好", "分数降", "下滑"]),
    ("家庭配合不足", ["家长忙", "没人管", "没陪", "顾不上辅导", "老人带"]),
]

_RISK_RESOLVED_RULES = [
    ("已解除", ["解决了", "没问题了", "放心了", "达成一致", "完全理解", "接受了", "已解决", "沟通好了"]),
    ("部分缓解", ["部分", "好一些", "有所改善", "先观察", "再观察", "再看看", "试试看", "先这样", "有所缓解"]),
    ("未解除", ["仍有", "还是有", "未解决", "没有解决", "没解决", "依然", "一直", "仍不", "继续存在"]),
]

_IMPROVEMENT_RULES = [
    ("高", ["认可", "配合", "愿意", "会配合", "会调整", "会督促", "积极", "主动", "理解"]),
    ("低", ["拒绝", "不考虑", "不理", "没兴趣", "不配合", "不会改", "敷衍"]),
]

_NEXT_ACTION_RULES = [
    ("进入观察", ["观察", "再看", "先看", "观望", "看看情况"]),
    ("立即再次联系", ["马上", "尽快", "今天", "稍后", "再联系", "再沟通", "回电", "明天联系"]),
    ("安排复查", ["复查", "过几天", "几天后", "下周", "月底", "下次"]),
]


def _match(text: str, rules: list) -> str:
    """返回命中的第一条规则名；无命中返回 ''"""
    if not text:
        return ""
    for label, kws in rules:
        for kw in kws:
            if kw in text:
                return label
    return ""


def _match_all(text: str, rules: list) -> list:
    """返回所有命中的规则名（去重）。"""
    hits = []
    if not text:
        return hits
    for label, kws in rules:
        for kw in kws:
            if kw in text and label not in hits:
                hits.append(label)
    return hits


def extract_days(text: str):
    """从文本提取复查天数（如 3天后/一周后），返回 int 或 None。"""
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s*天", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(一|两|三|四|五|六|七)\s*天", text)
    if m:
        z = {"一": 1, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
        return z.get(m.group(1))
    if "一周" in text or "星期" in text or "下周" in text:
        return 7
    if "48小时" in text or "两天" in text:
        return 2
    return None


def parse_parent_feedback_rule(text: str) -> dict:
    """规则引擎结构化解析（零大模型调用）。所有字段基于原文关键词命中，未命中标「未明确」。"""
    t = (text or "").strip()
    if not t:
        return {
            "家长态度": "暂无数据", "当前问题": "暂无数据",
            "风险是否解除": "暂无数据", "改善可能性": "未明确",
            "建议动作": "未明确", "下一动作": "未明确",
            "复查天数": None, "依据": [], "来源": "规则引擎",
        }

    attitude = _match(t, _ATTITUDE_RULES)
    problems = _match_all(t, _PROBLEM_RULES)
    resolved = _match(t, _RISK_RESOLVED_RULES)
    improvement = _match(t, _IMPROVEMENT_RULES)
    action = _match(t, _NEXT_ACTION_RULES)
    days = extract_days(t)

    # 依据（引用原文关键词，供UI展示）
    basis = []
    basis += ([f"家长态度关键词：{attitude}"] if attitude else [])
    basis += ([f"问题关键词：{'、'.join(problems)}"] if problems else [])
    basis += ([f"风险状态关键词：{resolved}"] if resolved else [])
    basis += ([f"改善信号关键词：{improvement}"] if improvement else [])

    # 下一动作兜底：按风险解除状态推导复查节奏（不引用未说的话，只基于状态）
    if not action:
        if resolved == "已解除":
            action = "进入观察"
        elif resolved == "部分缓解":
            action = "安排复查"
        elif resolved == "未解除":
            action = "立即再次联系"

    if days is None and action in ("安排复查", "进入观察"):
        days = 3  # 默认3天复查（规则语义，非编造家长原话）

    return {
        "家长态度": attitude or "未明确",
        "当前问题": "、".join(problems) if problems else ("未明确" if t else "暂无数据"),
        "风险是否解除": resolved or "未明确",
        "改善可能性": improvement or "未明确",
        "建议动作": action or "进入观察",
        "下一动作": _format_next_action(action, days),
        "复查天数": days,
        "依据": basis,
        "来源": "规则引擎",
    }


def _format_next_action(action: str, days) -> str:
    if action == "安排复查" and days:
        return f"{days}天后复查"
    if action == "立即再次联系":
        return "48小时内再次联系"
    if action == "进入观察":
        return "进入观察，等待最新学情数据"
    return action


# ============================================================
# AI增强（可选）：LLM结构化提取，失败自动兜底规则引擎
# ============================================================

_AI_SYSTEM = (
    "你是高途二讲团队的服务复盘助手。老师刚完成一次家长沟通，会贴出家长的真实反馈原话。"
    "请你严格基于原话提取结构化信息，禁止编造家长没说的内容，无法判断就写「未明确」。"
)

_AI_TEMPLATE = """请从下方家长反馈原话中提取结构化信息，只输出JSON，不要任何其他文字与markdown围栏：
{text}

输出字段（均为字符串；无法判断填"未明确"）：
{{
  "家长态度": "认可|疑虑|消极|时间不足|未明确",
  "当前问题": "简短概括家长提到的问题，多个用顿号分隔，无则填未明确",
  "风险是否解除": "已解除|部分缓解|未解除|未明确",
  "改善可能性": "高|中|低|未明确",
  "建议动作": "进入观察|立即再次联系|安排复查|未明确",
  "下一动作": "具体可执行动作（如3天后复查练习提交情况）",
  "复查天数": 数字或null
}}"""


def _extract_json(text: str) -> dict:
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text).strip()
    try:
        o = json.loads(t)
        return o if isinstance(o, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[^{}]*\}", t, re.DOTALL)
    if m:
        try:
            o = json.loads(m.group(0))
            return o if isinstance(o, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_parent_feedback(text: str, use_ai: bool = False, max_retry: int = 2) -> dict:
    """家长反馈结构化入口：AI增强（可选，默认关闭以省成本）+ 规则兜底。

    默认 use_ai=False 走纯规则引擎（轻量、零成本、可追溯）；
    需要更细粒度理解时置 use_ai=True，AI失败自动回退规则结果。
    """
    rule = parse_parent_feedback_rule(text)
    if not use_ai or not (text or "").strip():
        return rule

    prompt = _AI_TEMPLATE.format(text=text.strip())
    for _ in range(max_retry):
        try:
            resp = _client.chat.completions.create(
                model=MODEL_NAME, temperature=0.1, max_tokens=600, timeout=40,
                messages=[
                    {"role": "system", "content": _AI_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            )
            obj = _extract_json(resp.choices[0].message.content or "")
            if obj and isinstance(obj, dict):
                merged = {**rule, **{k: (v if v not in (None, "") else rule.get(k)) for k, v in obj.items()}}
                merged["来源"] = "AI增强"
                merged.setdefault("依据", rule.get("依据", []))
                if not merged.get("复查天数") and isinstance(obj.get("复查天数"), int):
                    merged["复查天数"] = obj["复查天数"]
                return merged
        except Exception as e:
            print(f"[FeedbackParser] AI增强异常: {type(e).__name__}: {e}")

    print("[FeedbackParser] AI增强失败，使用规则引擎兜底")
    return rule