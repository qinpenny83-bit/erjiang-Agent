"""家长答疑助手V2 — 轻量级，不依赖ChromaDB"""
import os
import sys
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS
from core.prompt_utils import append_constraints

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def load_prompt(template_name: str) -> str:
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    filepath = os.path.join(prompt_dir, template_name)
    with open(filepath, "r", encoding="utf-8") as f:
        return append_constraints(f.read())


def generate_qa_response(question: str, qa_type: str = "续费沟通", qa_duration: str = "", qa_subject: str = "", qa_grade: str = "") -> str:
    """生成家长答疑完整回复（5部分），支持学生背景信息"""
    template = load_prompt("qa_response_v2.txt")

    # 构建学生背景文本
    bg_parts = []
    if qa_type:
        bg_parts.append(f"沟通类型：{qa_type}")
    if qa_duration:
        bg_parts.append(f"学员在读时间：{qa_duration}")
    if qa_subject:
        bg_parts.append(f"科目：{qa_subject}")
    if qa_grade:
        bg_parts.append(f"在读年级：{qa_grade}")
    student_bg = "\n".join(bg_parts) if bg_parts else "无"

    prompt = template.format(question=question, student_bg=student_bg)

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                temperature=0.7,
                max_tokens=2000,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是高途二讲老师沟通策略顾问（Communication Coach）。"
                            "你的目标是提供最牛的沟通思路和颠覆常规的话术切入点，直接提升老师的沟通专业度与续费率。"
                            "拒绝平庸，直击本质：洞察家长潜意识里的真实焦虑，提供心理学、教育学维度的全新沟通出发点。"
                            "话术自然、专业、有温度、绝不模板化。不承诺提分，不推卸责任。"
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
            )
            content = response.choices[0].message.content
            if content and content.strip():
                return content
            print(f"[QA] 空返回，重试 {attempt+1}/3")
        except Exception as e:
            print(f"[QA] 异常: {e}，重试 {attempt+1}/3")
            import time as _time
            _time.sleep(2)
    return "分析生成失败，请重试"
