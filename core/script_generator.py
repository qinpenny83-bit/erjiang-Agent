"""话术生成引擎 — 负责调用LLM生成学情分析与沟通话术"""
import os
from openai import OpenAI
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def load_prompt(template_name: str) -> str:
    """加载Prompt模板"""
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    filepath = os.path.join(prompt_dir, template_name)
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def generate_student_script(profile_dict: dict) -> str:
    """为单个学生生成学情分析与沟通话术"""
    template = load_prompt("student_segmentation.txt")
    prompt = template.format(**profile_dict)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": "你是一位资深的教育行业学情分析专家，擅长将数据转化为有温度的家长沟通话术。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def batch_generate_scripts(profiles: list[dict], progress_callback=None) -> list[dict]:
    """批量生成学生话术"""
    results = []
    total = len(profiles)
    for i, profile in enumerate(profiles):
        script = generate_student_script(profile)
        results.append({
            "学生姓名": profile["学生姓名"],
            "分层": profile["分层"],
            "流失风险分": profile["流失风险分"],
            "续费剩余(天)": profile["续费剩余(天)"],
            "生成话术": script,
        })
        if progress_callback:
            progress_callback(i + 1, total)
    return results
