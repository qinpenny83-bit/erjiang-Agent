"""批量报告生成器 — 为每位学生生成个性化家长反馈报告"""
import os
import sys
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS
from core.script_generator import load_prompt

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def generate_single_report(profile_dict: dict) -> str:
    """为单个学生生成学情报告"""
    template = load_prompt("batch_report.txt")
    prompt = template.format(**profile_dict)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": "你是一位专业的教育咨询师，报告要专业、有数据、有温度。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def batch_generate_reports(profile_dicts: list[dict], progress_callback=None) -> list[dict]:
    """批量生成学情报告"""
    results = []
    total = len(profile_dicts)
    for i, profile in enumerate(profile_dicts):
        report = generate_single_report(profile)
        results.append({
            "学生姓名": profile["学生姓名"],
            "分层": profile["分层"],
            "学情报告": report,
        })
        if progress_callback:
            progress_callback(i + 1, total)
    return results
