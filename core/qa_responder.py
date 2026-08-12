"""家长答疑回复生成器 — 沟通策略顾问模式（5段式结构化输出）"""
import os
import sys
import re
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from core.prompt_utils import append_constraints

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# ====== 模块级缓存 ======
_prompt_cache = {}


def _load_prompt_cached(name: str) -> str:
    if name in _prompt_cache:
        return _prompt_cache[name]
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    filepath = os.path.join(prompt_dir, name)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    content = append_constraints(content)
    _prompt_cache[name] = content
    return content


def _parse_sections(raw_text: str) -> dict:
    """解析AI输出的4段式结构化文本"""
    result = {
        "问题判断": {},
        "沟通策略": {},
        "话术": "",
        "行动方案": {},
        "raw": raw_text,
    }
    section_patterns = [
        ("问题判断", r"【一、问题判断】[^\n]*\s*\n(.*?)(?=【二、沟通策略】|$)", [
            "学生当前情况", "家长核心顾虑", "解决重点"
        ]),
        ("沟通策略", r"【二、沟通策略】[^\n]*\s*\n(.*?)(?=【三、家长沟通话术】|$)", [
            "沟通目标", "最佳切入点", "沟通注意事项"
        ]),
        ("话术", r"【三、家长沟通话术】[^\n]*\s*\n(.*?)(?=【四、行动方案】|$)", None),
        ("行动方案", r"【四、行动方案】[^\n]*\s*\n(.*)", [
            "老师下一步", "学生下一步", "家长配合", "后续跟踪时间"
        ]),
    ]

    for key, pattern, fields in section_patterns:
        match = re.search(pattern, raw_text, re.DOTALL)
        if match:
            section_text = match.group(1).strip()
            if fields is None:
                result[key] = section_text
            else:
                for field in fields:
                    fm = re.search(rf'{re.escape(field)}[：:]\s*(.*?)(?=\n(?:{"|".join(re.escape(f) for f in fields if f != field)})[：:]|\Z)', section_text, re.DOTALL)
                    if fm:
                        result[key][field] = fm.group(1).strip()
                    else:
                        result[key][field] = ""
    return result


def generate_qa_response(question: str, student_context: dict = None, image_data: bytes = None) -> dict:
    """
    沟通策略顾问模式：1次API调用，输出5段式结构化分析。
    支持文字输入、截图输入、或两者结合。
    """
    # 构建学生上下文
    student_info = "暂无学生背景数据，请基于问题本身和家长常见场景进行分析。"
    if student_context:
        parts = [f"- {k}: {v}" for k, v in student_context.items()]
        student_info = "\n".join(parts)

    # 构建问题描述
    has_text = bool(question and question.strip())
    if has_text and image_data:
        question_desc = (
            f"家长问题（文字补充）：{question}\n\n"
            "⚠️ 老师上传了一段和家长的微信聊天截图（这就是对话记录本身，不是家长发给老师的截图）：\n"
            "1. 左侧消息框 = 家长发的，右侧消息框 = 老师（我们）发的\n"
            "2. 还原对话全貌：谁先说的→对方怎么回的→最后停在哪个话题\n"
            "3. 判断老师之前的回复是否恰当，如有不当需在沟通注意事项中指出\n"
            "4. 家长最后一条消息是当前需要回复的核心问题\n"
            "5. 话术中只能说「看到您发的消息」，严禁说「看到您的截图」"
        )
    elif image_data:
        question_desc = (
            "⚠️ 老师上传了一段和家长的微信聊天截图（这就是对话记录本身，不是家长发给老师的截图）：\n"
            "1. 左侧消息框 = 家长发的，右侧消息框 = 老师（我们）发的\n"
            "2. 还原对话全貌：谁先说的→对方怎么回的→最后停在哪个话题\n"
            "3. 判断老师之前的回复是否恰当，如有不当需在沟通注意事项中指出\n"
            "4. 家长最后一条消息是当前需要回复的核心问题\n"
            "5. 根据截图内容判断家长问题类型，理解家长真实诉求\n"
            "6. 话术中只能说「看到您发的消息」，严禁说「看到您的截图」"
        )
    else:
        question_desc = question

    # 加载 prompt
    template = _load_prompt_cached("qa_combined.txt")
    prompt = template.format(
        question=question_desc,
        student_context=student_info,
    )

    system_prompt = (
        "你是一名高途在线教育资深家长沟通策略专家，具备课程顾问能力。"
        "你的输出必须严格按4段式结构：问题判断（简洁）→ 沟通策略（简洁）→ 家长沟通话术（重点，>=300字）→ 行动方案。"
        "禁止输出低价值模板话术，所有回复必须结合学生实际情况。"
        "当用户上传截图时，那截图就是老师和家长的聊天记录本身，不是家长发给老师的图片。"
        "话术中严禁说「看到您的截图」之类的话，只能说「看到您发的消息」"
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.1,
        max_tokens=2500,
        timeout=45,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    )

    raw_content = response.choices[0].message.content.strip()
    parsed = _parse_sections(raw_content)

    return {
        "question": question,
        "问题判断": parsed["问题判断"],
        "沟通策略": parsed["沟通策略"],
        "话术": parsed["话术"],
        "行动方案": parsed["行动方案"],
        "raw": raw_content,
    }