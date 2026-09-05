# -*- coding: utf-8 -*-
"""AI动态复评模块（第二阶段核心）

替代第一阶段的规则化复评：老师完成沟通后，由LLM综合
【原始学情分析 + 当前风险等级 + 历史沟通记录 + 本次沟通结果 + 老师备注 + 成绩变化】
动态判断风险方向、建议等级、下一步行动与跟进时间。

==== 设计原则 ====
1. 不机械映射：'家长认可方案'≠必然降级，AI必须结合备注与学情综合判断
2. 真实优先：判断依据只能引用输入数据，数据不足时输出"信息不足，建议人工复核"
3. 兜底机制：LLM异常/解析失败/输出非法时返回 None，由 task_engine 降级到规则复评
4. 原始分层永不修改：本模块只返回建议，写不写入由 task_engine 控制（且只写任务侧）

统一返回结构（与规则复评一致，供 _apply_reeval 统一应用）：
{
    "模式": "AI动态复评",
    "当前风险等级": "P1-P4",
    "风险方向": "下降|上升|保持",
    "复评结论": str,
    "判断依据": str,
    "下一步动作": str,
    "跟进天数": int (0-30),
    "升级标记": bool,
    "需人工复核": bool,
}
"""
import json
import re

from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 合法等级/方向
_VALID_TIERS = ("P1", "P2", "P3", "P4")
_VALID_DIRECTIONS = ("下降", "上升", "保持")

# 复评Prompt模板
_SYSTEM_PROMPT = (
    "你是高途在线教育的学员风险复评专家。老师刚完成一次家长沟通，"
    "你需要基于给定的真实数据，动态复评该学员当前的风险等级并决策下一步服务动作。"
    "你的判断必须严谨：只能依据给定数据推理，禁止编造任何不存在的学情、沟通内容或结果。"
)

_PROMPT_TEMPLATE = """# 学生学情数据（真实数据）
{student_context}

# 任务当前状态
- 原始AI分层（仅供参考，复评时结合沟通情况重新判断）：{origin_tier}
- 当前任务风险等级：{current_tier}
- 风险原因（任务生成时）：{risk_reason}

# 历史沟通记录（按时间顺序）
{comm_history}

# 本次沟通
- 沟通结果：{comm_result}
- 老师备注：{teacher_note}

---

# 复评要求
1. 不要机械按沟通结果映射等级：例如"家长认可方案"但备注显示家长仍有明显不满、或成绩持续下降，风险不应下降甚至应上升；"未接通"若已连续多次，联系不上本身即是风险上升信号
2. 综合学情趋势、历史沟通轨迹、本次结果与备注，判断风险方向（下降/上升/保持）
3. 建议等级只能是 P1/P2/P3/P4（P1最高风险，P4基本无风险）
4. 判断依据必须逐条引用上述真实数据，禁止编造不存在的学情或沟通内容
5. 若数据不足以支撑判断（如缺少学情数据、备注信息矛盾且无法确认），必须令"信息不足"=true，复评结论写"信息不足，建议人工复核"
6. 下一步动作必须具体可执行（做什么、何时做），不要空泛建议
7. 跟进天数为整数0-30：0表示今日内、1-3表示短期、7及以上表示中长期观察
8. 若风险明显上升或家长疑虑未化解，令"升级标记"=true

# 输出格式（只输出如下JSON，不要任何其他文字、不要markdown代码块围栏）
{{"风险方向": "下降|上升|保持", "建议等级": "P1|P2|P3|P4", "复评结论": "一句话结论", "判断依据": "基于真实数据的推理（可分号分隔多条）", "下一步动作": "具体可执行动作", "跟进天数": 0, "升级标记": false, "信息不足": false}}"""


def _build_student_context(student: dict, task: dict) -> str:
    """构建学生学情上下文（优先用最新分析结果，任务字段兜底；无数据明确标注，不编造）"""
    src = student if student else {}
    get = lambda k, default="": src.get(k, task.get(k, default))

    def _fmt(v, na="暂无数据"):
        if v is None or v == "" or v == []:
            return na
        if isinstance(v, list):
            return "、".join(str(x) for x in v if x)
        return str(v)

    lines = [
        f"- 学生姓名：{_fmt(get('学生姓名'))}",
        f"- 年级：{_fmt(get('年级'))}",
        f"- 最近成绩：{_fmt(get('最近成绩'))}",
        f"- 成绩趋势：{_fmt(get('成绩趋势'))}",
        f"- 成绩变化：{_fmt(task.get('成绩变化'), na='暂无数据')}",
        f"- 家长态度：{_fmt(get('家长态度'))}",
        f"- 家长信号：{_fmt(get('家长信号'))}",
        f"- 续费意愿：{_fmt(get('续费意愿'))}",
        f"- 沟通间隔（上次沟通距今天数）：{_fmt(get('沟通间隔天数'))}",
        f"- 原始风险触发原因：{_fmt(get('风险触发'))}",
    ]
    if not student:
        lines.append("- 注：暂无该学生的完整学情分析数据（仅有任务侧数据），如不足以判断请令信息不足=true")
    return "\n".join(lines)


def _build_comm_history(task: dict) -> str:
    """历史沟通记录文本（真实记录，无记录明确标注）"""
    history = task.get("沟通结果历史") or []
    if not history:
        return "暂无历史沟通记录（本次为首次沟通）"
    lines = []
    for h in history:
        note = f"（备注：{h['备注']}）" if h.get("备注") else ""
        lines.append(f"- {h['时间']}：{h['结果']}{note}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """从LLM输出提取JSON（容错：裸JSON/代码块围栏/前后杂质）"""
    if not text:
        return None
    # 去掉 ```json ... ``` 围栏
    text = re.sub(r"```(?:json)?", "", text).strip()
    # 尝试整体解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 提取首个 {...} 块
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return None
    return None


def _validate(obj: dict, task: dict) -> dict:
    """校验并规范化AI输出；非法字段修正，无法修正返回None"""
    if not obj:
        return None
    # 信息不足路径：等级保持不变（安全第一）
    if obj.get("信息不足") is True:
        return {
            "模式": "AI动态复评",
            "当前风险等级": task.get("当前风险等级", "P3"),
            "风险方向": "保持",
            "复评结论": "信息不足，建议人工复核",
            "判断依据": str(obj.get("判断依据") or "AI判断现有数据不足以支撑风险等级调整"),
            "下一步动作": "信息不足，建议人工复核（人工确认后再决定等级与跟进安排）",
            "跟进天数": 1,
            "升级标记": True,
            "需人工复核": True,
        }

    # 等级校验
    tier = str(obj.get("建议等级") or "").strip().upper()
    if tier not in _VALID_TIERS:
        return None
    # 方向校验（缺失则按等级对比推断）
    direction = str(obj.get("风险方向") or "").strip()
    if direction not in _VALID_DIRECTIONS:
        cur = task.get("当前风险等级", "P3")
        direction = "下降" if _VALID_TIERS.index(tier) > _VALID_TIERS.index(cur) else (
               "上升" if _VALID_TIERS.index(tier) < _VALID_TIERS.index(cur) else "保持")
    # 跟进天数
    try:
        days = int(obj.get("跟进天数"))
        days = max(0, min(30, days))
    except (ValueError, TypeError):
        days = 3
    # 必要文本
    conclusion = str(obj.get("复评结论") or "").strip()
    next_action = str(obj.get("下一步动作") or "").strip()
    if not conclusion or not next_action:
        return None

    return {
        "模式": "AI动态复评",
        "当前风险等级": tier,
        "风险方向": direction,
        "复评结论": conclusion,
        "判断依据": str(obj.get("判断依据") or "AI基于学情与沟通记录综合判断").strip(),
        "下一步动作": next_action,
        "跟进天数": days,
        "升级标记": bool(obj.get("升级标记")) or bool(task.get("升级标记")),
        "需人工复核": False,
    }


def ai_reevaluate(task: dict, comm_result: str, teacher_note: str = "",
                  student_context: dict = None, max_retry: int = 3) -> dict:
    """AI动态复评入口。

    Args:
        task: 任务对象（含当前等级/历史沟通/学情快照）
        comm_result: 本次沟通结果（8种枚举之一）
        teacher_note: 老师填写的沟通备注
        student_context: 该学生的最新学情分析结果（analysis_result中的学生dict，可为None）
    Returns:
        统一结构复评结果；AI不可用/输出非法时返回 None（由调用方降级规则复评）

    注：MODEL_NAME为推理模型（先输出reasoning再输出content），max_tokens需为
    思考过程预留空间；content为空时从reasoning_content兜底提取JSON。
    """
    prompt = _PROMPT_TEMPLATE.format(
        student_context=_build_student_context(student_context, task),
        origin_tier=task.get("原风险等级", "未知"),
        current_tier=task.get("当前风险等级", "未知"),
        risk_reason=task.get("风险原因", "暂无数据"),
        comm_history=_build_comm_history(task),
        comm_result=comm_result,
        teacher_note=teacher_note.strip() if teacher_note else "（老师未填写备注）",
    )

    last_err = ""
    for attempt in range(max_retry):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                temperature=0.1,
                max_tokens=2000,
                timeout=45,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            content = (response.choices[0].message.content or "").strip()
            obj = _validate(_extract_json(content), task)
            if not obj:
                # 推理模型兜底：content为空（思考耗尽token）时，从reasoning_content提取JSON
                reasoning = getattr(response.choices[0].message, "reasoning_content", "") or ""
                obj = _validate(_extract_json(reasoning), task)
                if obj:
                    print(f"[AI复评] content为空，已从思考过程兜底提取（第{attempt + 1}次）")
            if obj:
                return obj
            last_err = f"输出无法解析为合法复评结果: {(content or '(空)')[:120]}"
            print(f"[AI复评] 第{attempt + 1}/{max_retry}次输出非法，重试...")
        except Exception as e:
            last_err = str(e)
            print(f"[AI复评] 调用异常: {e}，重试 {attempt + 1}/{max_retry}")

    print(f"[AI复评] AI不可用（{last_err}），将由规则复评兜底")
    return None
