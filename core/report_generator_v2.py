"""学情报告生成器V2 — 7部分完整报告 + 并发加速"""
import os
import sys
import re
import pandas as pd
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS
from core.prompt_utils import append_constraints

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
MAX_WORKERS = 5


def load_prompt(template_name: str) -> str:
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    filepath = os.path.join(prompt_dir, template_name)
    with open(filepath, "r", encoding="utf-8") as f:
        return append_constraints(f.read())


def build_student_data_text(row_data: dict) -> str:
    """将学生所有数据组织成文本"""
    lines = []
    for key, val in row_data.items():
        if pd.notna(val) and str(val).strip():
            val_str = str(val)
            if len(val_str) > 500:
                val_str = val_str[:500] + "..."
            lines.append(f"- {key}: {val_str}")
    return "\n".join(lines)


def _call_llm(prompt: str) -> str:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.7,
        max_tokens=3000,
        messages=[
            {
                "role": "system",
                "content": "你是资深K12学习分析专家和班主任。分析客观真实，语言专业有温度，建议具体可执行。"
            },
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def generate_single_report(row_data: dict, name: str) -> str:
    """为单个学生生成完整学情报告"""
    template = load_prompt("batch_report_v2.txt")
    student_data = build_student_data_text(row_data)
    prompt = template.format(student_data=student_data)
    return _call_llm(prompt)


def batch_generate_reports(students_data: list[dict], progress_callback=None) -> list[dict]:
    """
    批量生成学情报告（并发）
    students_data: [{"name": "张三", "row_data": {...}}, ...]
    """
    results = [None] * len(students_data)
    completed = 0
    total = len(students_data)

    def _task(idx, item):
        try:
            report = generate_single_report(item["row_data"], item["name"])
            return idx, {
                "学生姓名": item["name"],
                "学情报告": report,
            }
        except Exception as e:
            return idx, {
                "学生姓名": item["name"],
                "学情报告": f"生成失败: {e}",
            }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_task, i, s): i for i, s in enumerate(students_data)}
        for future in as_completed(futures):
            idx, result = future.result()
            results[idx] = result
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return [r for r in results if r is not None]
