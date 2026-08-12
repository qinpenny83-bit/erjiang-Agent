"""续费预警话术生成器 — 并发加速 + 精准数据传入"""
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

# 并发数：DeepSeek API 一般支持 5-10 并发
MAX_WORKERS = 5


def load_prompt(template_name: str) -> str:
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    filepath = os.path.join(prompt_dir, template_name)
    with open(filepath, "r", encoding="utf-8") as f:
        return append_constraints(f.read())


def build_student_data_text(student: dict, classification: dict) -> str:
    """只传关键信息，减少token消耗"""
    lines = []
    raw = student.get("原始数据", {})
    if not raw:
        raw = student  # 后备：如果顶层就是原始数据

    # 已知元数据键名（不参与数据查找）
    METADATA_KEYS = {"学生姓名", "流失风险分", "风险详情", "触发维度", "成绩下滑红标",
                     "沟通间隔天数", "原始数据", "分层", "回访频率", "下次跟进",
                     "跟进逾期", "风险问题", "续费剩余(天)", "生成话术", "沟通话术",
                     "整改措施", "提升方案", "学生得分"}

    # 只传关键类别，跳过未分类和无关列
    priority_cats = ["身份信息", "成绩信息", "沟通记录", "续费相关", "学情特征", "家长画像"]
    for cat in priority_cats:
        cols = classification.get(cat, [])
        cat_items = []
        for col in cols:
            # 优先从raw读取，再查student顶层，跳过元数据键
            val = None
            if col in raw:
                val = raw.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                if col not in METADATA_KEYS:
                    val = student.get(col)
            if pd.notna(val) and str(val).strip():
                # 长文本截断，避免token浪费
                val_str = str(val)
                if len(val_str) > 300:
                    val_str = val_str[:300] + "..."
                cat_items.append(f"  - {col}: {val_str}")
        if cat_items:
            lines.append(f"【{cat}】")
            lines.extend(cat_items)

    return "\n".join(lines)


def _call_llm(prompt: str) -> str:
    """单次LLM调用"""
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.7,
        max_tokens=1500,
        messages=[
            {
                "role": "system",
                "content": "你是顶级教育销售大师+资深学情分析师。话术要有针对性、有温度、可执行。严禁空话套话，每句话都要有信息量。"
            },
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def generate_single_script(student: dict, classification: dict) -> str:
    """为单个学生生成话术"""
    template = load_prompt("renewal_risk_advisory.txt")

    student_data = build_student_data_text(student, classification)
    risk_details = student.get("风险详情", {})
    score_detail = risk_details.get("成绩情况", {})
    score_evidence = score_detail.get("evidence", [])
    score_trend = "未知"
    for ev in score_evidence:
        if "成绩下滑" in str(ev) or "成绩上升" in str(ev) or "期末成绩" in str(ev):
            score_trend = str(ev)
            break

    prompt = template.format(
        student_data=student_data,
        risk_score=student.get("流失风险分", 0),
        tier=student.get("分层", "C"),
        risk_issues=student.get("风险问题", "无"),
        score_trend=score_trend,
        contact_days=student.get("沟通间隔天数", 0),
        followup_freq=student.get("回访频率", "低频维系"),
    )

    return _call_llm(prompt)


def batch_generate_scripts(students: list, classification: dict, progress_callback=None) -> list:
    """并发批量生成话术，5x加速"""
    results = [None] * len(students)
    completed = 0
    total = len(students)

    # 按优先级排序：S级先生成
    indexed = list(enumerate(students))
    indexed.sort(key=lambda x: {"S": 0, "A": 1, "B": 2, "C": 3}.get(x[1].get("分层", "C"), 3))

    def _gen_task(idx, student):
        try:
            script = generate_single_script(student, classification)
            student["沟通话术"] = script
            student["整改措施"] = _extract_section(script, "沟通话术")
            student["提升方案"] = _extract_section(script, "孩子提升建议")
            return idx, student
        except Exception as e:
            student["沟通话术"] = f"生成失败: {e}"
            student["整改措施"] = ""
            student["提升方案"] = ""
            return idx, student

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_gen_task, idx, student): idx
            for idx, student in indexed
        }
        for future in as_completed(futures):
            idx, student = future.result()
            results[idx] = student
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    # 过滤None
    results = [r for r in results if r is not None]
    return results


def _extract_section(script: str, section_title: str) -> str:
    """从LLM输出中提取指定章节"""
    pattern = rf'###\s*\d+\.\s*{re.escape(section_title)}[^\n]*\n(.*?)(?=###\s*\d+\.|$)'
    match = re.search(pattern, script, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""
