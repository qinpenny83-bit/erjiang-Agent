"""家长答疑回复生成器 — 分类 + RAG检索SOP + 生成回复的完整流程"""
import os
import sys
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE
from core.qa_classifier import classify_question
from core.rag_engine import search_sop, init_chroma
from core.script_generator import load_prompt

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def generate_qa_response(question: str, student_context: dict = None) -> dict:
    """
    完整的家长答疑流程：
    1. 分类 → 2. 检索SOP → 3. 生成回复
    """
    # Step 1: 分类
    classification = classify_question(question)

    # Step 2: 检索相关SOP
    collection = init_chroma()
    sop_results = search_sop(question, collection, n_results=2)
    sop_reference = "\n\n".join([s["content"] for s in sop_results]) if sop_results else "暂无匹配的SOP条目"

    # Step 3: 生成回复
    template = load_prompt("qa_response.txt")

    student_info = "无" if not student_context else "\n".join(
        f"- {k}: {v}" for k, v in student_context.items()
    )

    prompt = template.format(
        question=question,
        classification=classification,
        sop_reference=sop_reference,
        student_context=student_info,
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        messages=[
            {"role": "system", "content": "你是一位经验丰富的二讲老师，回复要专业、有温度、可执行。"},
            {"role": "user", "content": prompt}
        ]
    )

    return {
        "question": question,
        "classification": classification,
        "sop_references": [{"title": s["title"], "source": s["source"]} for s in sop_results],
        "response": response.choices[0].message.content,
    }
