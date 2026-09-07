"""AI学情风险洞察 — AI层（分层分析策略）

分层设计（性能原则：不为每个学员调用一次大模型）：
- 规则层（risk_insight_engine）：全量学员零AI调用，覆盖风险类型/趋势/问题讲次/不一致检测
- AI层（本模块）：
  1. generate_batch_insights  对TOP学员批量深度分析（5人/次调用，失败自动降级规则版）
  2. generate_risk_report     单个学员「AI学情风险报告」（10模块，3次重试+完整性校验+规则版兜底）

证据边界：所有AI输出必须来自系统真实计算结果；解析后逐学员校验，缺失降级规则版，不编造。
"""
import os
import re
from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from core.prompt_utils import append_constraints

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

BATCH_SIZE = 5          # 每次API调用分析的学员数
MAX_BATCH_RETRY = 2     # 批量洞察重试次数
MAX_REPORT_RETRY = 3    # 报告重试次数

INSIGHT_FIELDS = ["主要风险", "触发指标", "风险解释", "建议关注"]

REPORT_MODULES = [
    "学员整体状态", "5维指标表现", "近期趋势", "风险等级", "主要风险类型",
    "风险原因", "具体问题讲次", "已知事实", "待确认信息", "老师关注建议",
]


def _load_prompt(name: str) -> str:
    prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    with open(os.path.join(prompt_dir, name), "r", encoding="utf-8") as f:
        return append_constraints(f.read())


def _call_llm(prompt: str, temperature: float = 0.2, max_tokens: int = 3500,
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
# 一、批量AI风险洞察（TOP学员）
# ============================================================

def _student_block(ins: dict) -> str:
    """构建单个学员的紧凑数据块（全部真实数据）"""
    lines = [f"【学员】{ins['name']}｜{ins['priority']}｜风险分{ins['risk_score']}"]
    lines.append(f"5维指标：{ins['metrics_brief']}")
    lines.append(f"异常明细：{ins['anomalies_brief']}")
    t = ins["trend"]
    tline = "、".join(f"{d}{t['dims'][d]['symbol']}" for d in t["dims"])
    lines.append(f"近期趋势：{tline}｜结论：{t['conclusion']}")
    if ins["problem_count"] > 0:
        pl = "；".join(
            f"{p['lecture']}（{'、'.join(i['type'] for i in p['issues'])}）"
            for p in ins["problem_lectures"][:6])
        suffix = f"等共{ins['problem_count']}讲" if ins["problem_count"] > 6 else f"共{ins['problem_count']}讲"
        lines.append(f"问题讲次（{suffix}）：{pl}")
    else:
        lines.append("问题讲次：无")
    if ins["inconsistency"].get("inconsistent"):
        lines.append(f"⚠️数据与风险不一致：{ins['inconsistency']['message']}")
    return "\n".join(lines)


def _parse_batch_result(raw: str) -> dict:
    """解析批量AI输出：{姓名: {字段: 内容}}"""
    out = {}
    for block in re.split(r"【学员】", raw)[1:]:
        block = block.strip()
        if not block:
            continue
        m = re.match(r"([^\n｜|【]+)", block)
        if not m:
            continue
        name = m.group(1).strip()
        fields = {}
        others = "|".join(re.escape(f) for f in INSIGHT_FIELDS)
        for field in INSIGHT_FIELDS:
            fm = re.search(
                rf'{re.escape(field)}[：:]\s*(.*?)(?=\n\s*(?:{others})[：:]|\Z)',
                block, re.DOTALL)
            if fm:
                val = fm.group(1).strip()
                # 容错：剥离首尾markdown符号与emoji前缀
                val = re.sub(r'^[\s\-•·*#>【】🟢🔵🟡🔴🟠⚪↗→↘⚠️]+', '', val).strip()
                val = re.sub(r'[\s\-•·*#>】\s]+$', '', val).strip()
                fields[field] = val
        if name:
            out[name] = fields
    return out


def _match_names(parsed: dict, expected: list) -> dict:
    """AI输出姓名与输入姓名匹配（精确→去空格包含），返回按输入名对齐的结果"""
    def _norm(s: str) -> str:
        return re.sub(r"\s+", "", str(s))

    matched = {}
    used = set()
    for name in expected:
        if name in parsed:
            matched[name] = parsed[name]
            used.add(name)
            continue
        nn = _norm(name)
        for pName in parsed:
            if pName in used:
                continue
            pn = _norm(pName)
            if nn in pn or pn in nn:
                matched[name] = parsed[pName]
                used.add(pName)
                break
    return matched


def generate_batch_insights(insights: list, progress_callback=None) -> dict:
    """对TOP学员批量生成AI深度洞察。

    5人/次调用；每次输出校验（4字段齐全），失败重试；仍缺失的学员降级规则版。
    Returns: {姓名: {主要风险/触发指标/风险解释/建议关注, "source": "ai"|"rule"}}
    """
    results = {}
    total = len(insights)
    for start in range(0, total, BATCH_SIZE):
        batch = insights[start:start + BATCH_SIZE]
        names = [b["name"] for b in batch]
        context = "\n\n".join(_student_block(b) for b in batch)
        template = _load_prompt("risk_insight_batch.txt")
        prompt = template.replace("{students_context}", context)

        parsed = {}
        for attempt in range(MAX_BATCH_RETRY):
            try:
                raw = _call_llm(
                    prompt, temperature=0.2, max_tokens=3000,
                    system_msg="你是高途在线教育资深学情风险分析师。严格基于真实数据输出，禁止编造。")
                parsed = _match_names(_parse_batch_result(raw), names)
                complete = all(
                    parsed.get(n) and parsed[n].get("风险解释") and parsed[n].get("主要风险")
                    for n in names)
                if complete:
                    break
                missing = [n for n in names
                           if not (parsed.get(n) and parsed[n].get("风险解释"))]
                print(f"[RiskInsight] 第{attempt + 1}次批量输出不完整，缺: {missing}，重试")
            except Exception as e:
                print(f"[RiskInsight] 批量AI异常(第{attempt + 1}次): {type(e).__name__}: {e}")

        for b in batch:
            p = parsed.get(b["name"])
            if p and p.get("风险解释") and p.get("主要风险"):
                results[b["name"]] = {
                    "主要风险": p.get("主要风险", ""),
                    "触发指标": p.get("触发指标", ""),
                    "风险解释": p.get("风险解释", ""),
                    "建议关注": p.get("建议关注", ""),
                    "source": "ai",
                }
            else:
                # 降级：规则版洞察（同为真实数据，字段一致）
                ri = b["rule_insight"]
                results[b["name"]] = {
                    "主要风险": ri["主要风险"],
                    "触发指标": ri["触发指标"],
                    "风险解释": ri["风险解释"],
                    "建议关注": ri["建议关注"],
                    "source": "rule",
                }
        if progress_callback:
            progress_callback(min(start + BATCH_SIZE, total), total)
    return results


# ============================================================
# 二、单个学员「AI学情风险报告」（10模块）
# ============================================================

def _build_report_context(ins: dict, result: dict) -> str:
    """构建报告输入上下文（全部真实数据）"""
    lines = [f"【学员姓名】{ins['name']}", f"【风险等级】{ins['priority']}（风险分{ins['risk_score']}）"]
    lines.append(f"【5维指标】{ins['metrics_brief']}")
    lines.append(f"【异常汇总】{ins['anomalies_brief']}")

    t = ins["trend"]
    lines.append("【近期趋势明细】")
    for d, td in t["dims"].items():
        lines.append(f"  {d}：{td['trend']}{td['symbol']}（{td['detail']}）")
    lines.append(f"  整体结论：{t['conclusion']}")
    patterns = [k for k, v in t["patterns"].items()
                if v and (not isinstance(v, list) or v)]
    if patterns:
        lines.append(f"  识别模式：{'、'.join(patterns)}")

    if ins["risk_type"]:
        lines.append(f"【主要风险类型】{ins['risk_type']}（触发：{'、'.join(ins['risk_triggers'])}）")
        if ins["secondary_types"]:
            lines.append(f"【次要风险类型】{'、'.join(ins['secondary_types'])}")
    else:
        lines.append("【主要风险类型】暂无明显风险")

    if ins["problem_count"] > 0:
        lines.append("【问题讲次明细】")
        for p in ins["problem_lectures"]:
            issues = "；".join(f"{i['type']}（{i['data']}）" for i in p["issues"])
            title = f"《{p['title']}》" if p["title"] else ""
            lines.append(f"  {p['lecture']}{title}：{issues}")
    else:
        lines.append("【问题讲次明细】无")

    if ins["inconsistency"].get("inconsistent"):
        lines.append(f"【数据与风险不一致提示】{ins['inconsistency']['message']}")

    return "\n".join(lines)


def _report_complete(text: str) -> bool:
    """校验报告10个模块是否齐全"""
    if not text or len(text) < 200:
        return False
    return all(f"【{m}】" in text for m in REPORT_MODULES)


def _fallback_report(ins: dict, result: dict) -> str:
    """规则版报告兜底（零编造，全部来自真实数据）"""
    ri = ins["rule_insight"]
    t = ins["trend"]
    lines = [
        f"【学员整体状态】{ins['name']}当前优先级{ins['priority']}（风险分{ins['risk_score']}），主要风险为{ri['主要风险']}。",
        f"【5维指标表现】{ins['metrics_brief']}。",
        f"【近期趋势】{t['conclusion']}。",
        f"【风险等级】{ins['priority']}，风险分{ins['risk_score']}（系统判定，未修改）。",
        f"【主要风险类型】{ri['主要风险']}。触发指标：{ri['触发指标']}。",
        f"【风险原因】{ri['风险解释']}",
    ]
    if ins["problem_count"] > 0:
        pl = "；".join(
            f"{p['lecture']}：{'、'.join(i['type'] + '（' + i['data'] + '）' for i in p['issues'])}"
            for p in ins["problem_lectures"][:10])
        lines.append(f"【具体问题讲次】共{ins['problem_count']}讲异常。{pl}")
    else:
        lines.append("【具体问题讲次】暂无问题讲次。")
    lines.append(f"【已知事实】🟢 {ins['metrics_brief']}；异常汇总：{ins['anomalies_brief']}。")
    if ins["inconsistency"].get("inconsistent"):
        lines.append(f"【待确认信息】🟡 {ins['inconsistency']['message']}")
    else:
        lines.append("【待确认信息】🟡 暂无待确认信息。")
    lines.append(f"【老师关注建议】{ri['建议关注']}（本报告由规则引擎生成，数据不足时建议进一步核实。）")
    return "\n".join(lines)


def generate_risk_report(ins: dict, result: dict) -> str:
    """生成单个学员「AI学情风险报告」（10模块），3次重试+完整性校验，失败降级规则版。"""
    template = _load_prompt("risk_report.txt")
    prompt = template.replace("{risk_context}", _build_report_context(ins, result))
    for attempt in range(MAX_REPORT_RETRY):
        try:
            raw = _call_llm(
                prompt, temperature=0.2, max_tokens=3500,
                system_msg="你是高途在线教育资深学情分析师。严格基于真实数据撰写报告，禁止编造任何信息。")
            if _report_complete(raw):
                return raw
            missing = [m for m in REPORT_MODULES if f"【{m}】" not in raw]
            print(f"[RiskReport] 第{attempt + 1}次报告不完整（缺{missing}），重试")
        except Exception as e:
            print(f"[RiskReport] 报告AI异常(第{attempt + 1}次): {type(e).__name__}: {e}")
    print("[RiskReport] AI生成失败，使用规则版报告兜底")
    return _fallback_report(ins, result)
