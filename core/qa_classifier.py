"""家长问题分类器 — 将家长问题分为教学/服务/续费/投诉四类"""
import json
import os
import sys
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME
from core.script_generator import load_prompt

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def classify_question(question: str) -> dict:
    """对家长问题进行分类"""
    template = load_prompt("qa_classification.txt")
    prompt = template.format(question=question)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.1,  # 分类任务用低温度保证稳定
        messages=[
            {"role": "system", "content": "你是一个精确的文本分类器，只输出JSON格式结果。"},
            {"role": "user", "content": prompt}
        ]
    )
    content = response.choices[0].message.content.strip()
    # 提取JSON（处理可能的markdown代码块包裹）
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 降级：返回默认分类
        return {
            "category": "教学类",
            "subcategory": "未分类",
            "urgency": "中",
            "key_concern": question[:50]
        }
