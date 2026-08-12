"""AI智能试卷批改与分析系统

核心功能：
1. 试卷图片质量检测（模糊、遮挡、倾斜、完整性、光线）
2. 试卷内容识别（科目、年级、题目、学生答案）
3. AI批改（逐题判断对错、给分、错误类型分类）
4. 错误知识点聚类分析
5. 生成专业试卷分析报告
6. 同类题生成（基础巩固/专项提升/易错变式/综合应用/模拟考试）

环境变量：
    OPENAI_API_KEY  - OpenAI API密钥
    OPENAI_BASE_URL - OpenAI API基础URL
    MODEL_NAME      - 模型名称（默认: deepseek-v4-flash）
    VISION_MODEL    - 视觉模型名称（默认: gpt-4o-mini，用于图片识别）
"""
import os
import sys
import json
import base64
import re
from typing import List, Dict, Any, Optional, Union

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.lecture_risk_analyzer import get_client
from core.prompt_utils import append_constraints

# ==================== 全局配置 ====================

_MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-v4-flash")
_VISION_MODEL = os.environ.get("VISION_MODEL", "gpt-4o-mini")

# 提示词模板（模块加载时读取一次）
_SYSTEM_PROMPT: Optional[str] = None


def _get_vision_client():
    """获取视觉模型客户端（用于图片识别）"""
    from openai import OpenAI
    return OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )


def _encode_image(image_path: str) -> str:
    """将图片编码为base64字符串"""
    _, ext = os.path.splitext(image_path)
    ext = ext.lower()
    if ext == ".png":
        media_type = "image/png"
    elif ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".webp":
        media_type = "image/webp"
    elif ext == ".gif":
        media_type = "image/gif"
    else:
        media_type = "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{media_type};base64,{b64}"


def _load_system_prompt() -> str:
    """加载试卷分析提示词模板，自动追加精准性约束"""
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is not None:
        return _SYSTEM_PROMPT
    prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
    filepath = os.path.join(prompt_dir, "exam_analysis_script.txt")
    with open(filepath, "r", encoding="utf-8") as f:
        _SYSTEM_PROMPT = append_constraints(f.read())
    return _SYSTEM_PROMPT


# ==================== 辅助函数 ====================





def _parse_json(text: str) -> Union[dict, list]:
    """从LLM返回文本中健壮地提取JSON

    支持以下格式：
    - 纯JSON字符串
    - markdown代码块包裹的JSON
    - 文本前后有额外说明
    """
    text = text.strip()

    # 尝试移除 markdown 代码块标记
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?\s*```$', '', text)
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试找第一个 { 到最后一个 }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    # 尝试找第一个 [ 到最后一个 ]
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start != -1 and bracket_end != -1 and bracket_end > bracket_start:
        try:
            return json.loads(text[bracket_start:bracket_end + 1])
        except json.JSONDecodeError:
            pass

    # 都不行则抛出异常
    raise ValueError(f"无法从LLM返回文本中解析JSON:\n{text[:500]}")


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    image_path: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """通用LLM调用函数（仅文本，不支持图片输入）

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        image_path: 保留参数，当前模型不支持图片输入
        temperature: 温度参数
        max_tokens: 最大输出token数

    Returns:
        LLM返回的文本内容
    """
    client = get_client()
    model = os.environ.get("MODEL_NAME", _MODEL_NAME)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        raise RuntimeError(f"LLM调用失败: {e}")


# ==================== 1. 试卷图片质量检测 ====================


def check_image_quality(image_path: str) -> dict:
    """检测试卷图片质量（基于文件属性，无需LLM视觉能力）

    Returns:
        dict: { "pass": bool, "score": float, "issues": [str], "details": {} }
    """
    if not os.path.exists(image_path):
        return {"pass": False, "score": 0, "issues": ["图片文件不存在"], "details": {}}
    file_size = os.path.getsize(image_path)
    if file_size > 50 * 1024 * 1024:
        return {"pass": False, "score": 0, "issues": ["图片文件过大（超过50MB）"], "details": {}}
    if file_size == 0:
        return {"pass": False, "score": 0, "issues": ["图片文件为空"], "details": {}}
    # 检查文件扩展名
    _, ext = os.path.splitext(image_path)
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return {"pass": False, "score": 0, "issues": [f"不支持的图片格式: {ext}"], "details": {}}
    return {
        "pass": True,
        "score": 100,
        "issues": [],
        "details": {"清晰度": "待LLM验证", "遮挡": "待LLM验证", "倾斜": "待LLM验证", "完整性": "待LLM验证", "光线": "待LLM验证"}
    }


# ==================== 2. 试卷内容识别 ====================


def recognize_paper(image_path: str) -> dict:
    """识别试卷内容（使用视觉模型）

    识别内容包括：科目、年级、试卷名称、学生姓名、所有题目、
    题目选项、学生手写答案、题目分值等。

    Args:
        image_path: 试卷图片路径

    Returns:
        dict: 识别结果
    """
    if not os.path.exists(image_path):
        return {"error": f"图片文件不存在: {image_path}"}

    prompt = """请完整识别这张试卷的所有内容，输出JSON格式。

识别要求：
1. 试卷基本信息：科目、年级、试卷名称、学生姓名（如有）
2. 所有题目：题号、题型、题目内容、选项（如有）
3. 学生填写的手写答案（重点识别）
4. 每道题的分值（如有标注）

必须严格按照以下JSON格式输出：
{
    "subject": "科目",
    "grade": "年级",
    "name": "试卷名称",
    "student_name": "学生姓名（如无法识别则为空字符串）",
    "total_score": 总分（整数或null）,
    "questions": [
        {
            "id": 题号,
            "type": "题型（选择题/填空题/判断题/计算题/解答题/作文题/阅读题/其他）",
            "content": "题目内容",
            "options": ["A. 选项A", "B. 选项B"],
            "student_answer": "学生填写的答案",
            "correct_answer": "标准答案（如有标注）",
            "score": 分值（整数或null）
        }
    ]
}

注意事项：
- 如无法识别某些内容，对应字段填 null 或空字符串
- 如学生答案无法辨认，student_answer 标记为 "无法识别"
- 如题目没有选项，options 字段为 []
- 如没有标注分值，score 为 null
- 保留原题结构，不改变题意
- 数学公式用文字描述保留
- 表格内容逐行识别"""

    try:
        client = _get_vision_client()
        base64_image = _encode_image(image_path)

        response = client.chat.completions.create(
            model=_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": base64_image, "detail": "high"},
                        },
                    ],
                }
            ],
            temperature=0.2,
            max_tokens=8192,
        )

        result = response.choices[0].message.content.strip()
        parsed = _parse_json(result)
        if "questions" not in parsed:
            parsed["questions"] = []
        return parsed
    except Exception as e:
        return {"error": f"试卷内容识别失败: {str(e)}"}


# ==================== 3. AI批改 ====================


def grade_paper(recognition: dict) -> dict:
    """逐题批改试卷

    对每道题判断对错、给分、分析错误原因和错误类型。

    Args:
        recognition: 试卷识别结果（recognize_paper的返回值）

    Returns:
        dict: {
            "total_score": float,          # 总得分
            "total_correct": int,          # 正确题数
            "total_wrong": int,            # 错误题数
            "accuracy": float,             # 正确率 (0-1)
            "questions": [                 # 每题批改结果
                {
                    "id": int,
                    "content": str,
                    "student_answer": str,
                    "correct_answer": str,
                    "score": float,              # 得分
                    "max_score": float,          # 满分
                    "is_correct": bool,
                    "error_type": str,           # 错误类型
                    "error_reason": str,         # 错误原因分析
                    "knowledge_points": [str]    # 涉及知识点
                }
            ]
        }
    """
    questions = recognition.get("questions", [])
    if not questions:
        return {"error": "识别结果中无题目信息，无法批改"}

    system_prompt = _load_system_prompt()

    # 清理识别结果中可能干扰批改的冗余字段
    clean_recognition = {
        "subject": recognition.get("subject", ""),
        "grade": recognition.get("grade", ""),
        "name": recognition.get("name", ""),
        "total_score": recognition.get("total_score"),
        "questions": []
    }
    for q in questions:
        clean_recognition["questions"].append({
            "id": q.get("id", 0),
            "type": q.get("type", ""),
            "content": q.get("content", ""),
            "options": q.get("options", []),
            "student_answer": q.get("student_answer", ""),
            "correct_answer": q.get("correct_answer", ""),
            "score": q.get("score"),
        })

    prompt = f"""请根据以下试卷识别结果，逐题进行严格批改。

试卷识别结果：
{json.dumps(clean_recognition, ensure_ascii=False, indent=2)}

请严格按照以下JSON格式输出批改结果：
{{
    "total_score": 总得分,
    "total_correct": 正确题数,
    "total_wrong": 错误题数,
    "accuracy": 正确率(0-1之间的小数),
    "questions": [
        {{
            "id": 题号,
            "content": "题目内容",
            "student_answer": "学生答案",
            "correct_answer": "正确答案",
            "score": 学生得分,
            "max_score": 题目满分,
            "is_correct": true或false,
            "error_type": "错误类型（仅错题填写，正确题填null）",
            "error_reason": "错误原因详细分析（仅错题填写，正确题填null）",
            "knowledge_points": ["涉及的知识点1", "涉及的知识点2"]
        }}
    ]
}}

错误类型（仅限以下7类，用编号或名称均可）：
1. 知识点不会
2. 方法错误
3. 概念理解错误
4. 审题错误
5. 计算错误
6. 表达不规范
7. 粗心失误

批改原则：
- 主观题（作文、解答题等）根据评分标准和答案要点合理给分
- 部分正确的情况给部分分数，is_correct 为 false
- 逐题给出详细的错误原因分析
- 如果学生答案无法识别，标记为待人工确认"""

    try:
        result = _call_llm(
            system_prompt=system_prompt,
            user_prompt=prompt,
            temperature=0.2,
            max_tokens=8192,
        )
        parsed = _parse_json(result)
        # 确保必填字段存在
        if "questions" not in parsed:
            parsed["questions"] = []
        if "total_score" not in parsed:
            parsed["total_score"] = 0
        if "total_correct" not in parsed:
            parsed["total_correct"] = 0
        if "total_wrong" not in parsed:
            parsed["total_wrong"] = 0
        if "accuracy" not in parsed:
            total = parsed["total_correct"] + parsed["total_wrong"]
            parsed["accuracy"] = parsed["total_correct"] / total if total > 0 else 0
        return parsed
    except Exception as e:
        return {"error": f"试卷批改失败: {str(e)}"}


# ==================== 4. 错误知识点聚类分析 ====================


def analyze_errors(grading: dict) -> dict:
    """错误知识点聚类分析

    对所有错题进行知识点聚类、错误类型统计、掌握程度评估。

    Args:
        grading: 批改结果（grade_paper的返回值）

    Returns:
        dict: {
            "error_summary": {
                "total_errors": int,                # 总错误题数
                "error_rate": float,                # 错误率 (0-1)
                "top_error_types": [                # 错误类型TOP
                    {"type": str, "count": int, "ratio": float}
                ],
                "knowledge_point_clusters": [       # 知识点聚类
                    {
                        "knowledge_point": str,     # 知识点名称
                        "error_count": int,         # 错误次数
                        "error_ratio": float,       # 错误比例
                        "error_performance": str,   # 错误表现描述
                        "mastery_level": str        # 掌握程度
                    }
                ]
            },
            "weakness_analysis": str,               # 薄弱环节综合分析
            "learning_suggestions": [str]           # 学习建议列表
        }
    """
    questions = grading.get("questions", [])
    wrong_questions = [q for q in questions if not q.get("is_correct", True)]

    if not wrong_questions:
        return {
            "error_summary": {
                "total_errors": 0,
                "error_rate": 0,
                "top_error_types": [],
                "knowledge_point_clusters": []
            },
            "weakness_analysis": "本次考试全部正确，无需错误分析。继续保持当前学习状态。",
            "learning_suggestions": [
                "继续保持当前学习状态",
                "可尝试挑战更高难度题目",
                "建议定期复习巩固，防止遗忘"
            ]
        }

    system_prompt = _load_system_prompt()

    # 只提取错题信息进行分析
    grading_for_analysis = {
        "total_score": grading.get("total_score", 0),
        "total_correct": grading.get("total_correct", 0),
        "total_wrong": grading.get("total_wrong", 0),
        "accuracy": grading.get("accuracy", 0),
        "wrong_questions": []
    }
    for q in wrong_questions:
        grading_for_analysis["wrong_questions"].append({
            "id": q.get("id", 0),
            "content": q.get("content", ""),
            "student_answer": q.get("student_answer", ""),
            "correct_answer": q.get("correct_answer", ""),
            "score": q.get("score", 0),
            "max_score": q.get("max_score", 0),
            "error_type": q.get("error_type", ""),
            "error_reason": q.get("error_reason", ""),
            "knowledge_points": q.get("knowledge_points", []),
        })

    prompt = f"""请对以下批改结果中的错题进行知识点聚类分析和错误诊断。

错题信息：
{json.dumps(grading_for_analysis, ensure_ascii=False, indent=2)}

请按照以下JSON格式输出分析结果：
{{
    "error_summary": {{
        "total_errors": 总错误题数,
        "error_rate": 错误率(0-1小数),
        "top_error_types": [
            {{"type": "错误类型名称", "count": 出现次数, "ratio": 占比(0-1小数)}}
        ],
        "knowledge_point_clusters": [
            {{
                "knowledge_point": "知识点名称",
                "error_count": 该知识点错误次数,
                "error_ratio": 该知识点错误占所有错题的比例(0-1小数),
                "error_performance": "学生在该知识点上的具体错误表现描述",
                "mastery_level": "掌握程度（严重薄弱/需要加强/基本掌握/已掌握）"
            }}
        ]
    }},
    "weakness_analysis": "对薄弱环节的综合文本分析，指出知识漏洞、方法问题和能力短板，以及可能的原因",
    "learning_suggestions": [
        "具体可行的学习建议1",
        "具体可行的学习建议2",
        "具体可行的学习建议3"
    ]
}}"""

    try:
        result = _call_llm(
            system_prompt=system_prompt,
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=4096,
        )
        parsed = _parse_json(result)
        # 确保结构完整
        if "error_summary" not in parsed:
            parsed["error_summary"] = {
                "total_errors": len(wrong_questions),
                "error_rate": grading.get("total_wrong", 0) / max(
                    grading.get("total_correct", 0) + grading.get("total_wrong", 0), 1
                ),
                "top_error_types": [],
                "knowledge_point_clusters": []
            }
        if "weakness_analysis" not in parsed:
            parsed["weakness_analysis"] = "分析生成失败，请重试。"
        if "learning_suggestions" not in parsed:
            parsed["learning_suggestions"] = ["请重试生成分析建议"]
        return parsed
    except Exception as e:
        return {
            "error_summary": {
                "total_errors": len(wrong_questions),
                "error_rate": grading.get("total_wrong", 0) / max(
                    grading.get("total_correct", 0) + grading.get("total_wrong", 0), 1
                ),
                "top_error_types": [],
                "knowledge_point_clusters": []
            },
            "weakness_analysis": f"错误分析过程异常: {str(e)}",
            "learning_suggestions": ["请重试错误分析"],
            "error": str(e)
        }


# ==================== 5. 生成专业试卷分析报告 ====================


def generate_report(
    recognition: dict,
    grading: dict,
    analysis: dict,
) -> str:
    """生成完整的学生个人试卷诊断报告

    基于识别结果、批改结果和错误分析，生成一份专业的Markdown格式诊断报告。

    Args:
        recognition: 试卷识别结果
        grading: 批改结果
        analysis: 错误分析结果

    Returns:
        str: Markdown格式的诊断报告文本
    """
    # 检查是否有错误
    if isinstance(recognition, dict) and "error" in recognition:
        return f"报告生成失败：识别结果异常 - {recognition['error']}"
    if isinstance(grading, dict) and "error" in grading:
        return f"报告生成失败：批改结果异常 - {grading['error']}"
    if isinstance(analysis, dict) and "error" in analysis:
        return f"报告生成失败：分析结果异常 - {analysis['error']}"

    system_prompt = _load_system_prompt()

    # 构造报告上下文
    report_context = {
        "基本信息": {
            "subject": recognition.get("subject", "未知"),
            "grade": recognition.get("grade", "未知"),
            "name": recognition.get("name", "未知"),
            "student_name": recognition.get("student_name", "未知"),
            "total_score": recognition.get("total_score", "未标注"),
        },
        "成绩概览": {
            "得分": grading.get("total_score", 0),
            "正确题数": grading.get("total_correct", 0),
            "错误题数": grading.get("total_wrong", 0),
            "正确率": grading.get("accuracy", 0),
        },
        "逐题批改详情": grading.get("questions", []),
        "错误分析": {
            "错误统计": analysis.get("error_summary", {}),
            "薄弱环节分析": analysis.get("weakness_analysis", ""),
            "学习建议": analysis.get("learning_suggestions", []),
        },
    }

    prompt = f"""请根据以下试卷分析数据，生成一份完整、专业、有针对性的学生个人试卷诊断报告（Markdown格式）。

数据：
{json.dumps(report_context, ensure_ascii=False, indent=2)}

报告必须包含以下部分，每个部分都需要基于真实数据撰写，禁止编造：

# 《学生个人试卷诊断报告》

## 一、基本信息
- 学生姓名、科目、年级、试卷名称
- 考试时间（如未提供则写"待补充"）

## 二、整体成绩分析
- 总分/得分/得分率
- 正确题数/错误题数/正确率
- 优势模块与薄弱模块概览

## 三、能力维度分析
- 知识掌握能力
- 计算能力
- 应用迁移能力

## 四、逐题批改详情
- 每题对错状态、得分、错误原因

## 五、错题原因深度分析
- 知识漏洞分析
- 方法问题分析
- 能力不足分析
- 学习习惯问题分析

## 六、错误知识点聚类分析
- 各知识点掌握程度评估
- 错误表现描述

## 七、个性化学习建议
- 针对薄弱知识点的具体学习建议
- 推荐的训练方向和优先级

报告要求：
1. 专业、具体、有针对性
2. 全部基于真实数据，禁止编造
3. 语言亲切但专业，对学生有鼓励作用
4. 建议具体可执行"""

    try:
        report = _call_llm(
            system_prompt=system_prompt,
            user_prompt=prompt,
            temperature=0.4,
            max_tokens=8192,
        )
        return report
    except Exception as e:
        return f"报告生成失败：{e}"


# ==================== 6. 同类题生成 ====================


def generate_similar_questions(
    errors: list,
    question_type: str = "基础巩固",
    count: int = 5,
    difficulty: str = "中等",
) -> list:
    """根据错题生成针对性同类训练题

    支持5种题目类型和4种难度级别，题目数量可选5/10/20/30。

    Args:
        errors: 错题列表，每项包含题目、错误类型、知识点等信息
        question_type: 题目类型
            - "基础巩固": 针对基础知识点，强化记忆和理解
            - "专项提升": 针对特定薄弱环节，深度训练
            - "易错变式": 改变常见错误题型，训练识别能力
            - "综合应用": 多知识点综合，提升应用能力
            - "模拟考试": 模拟真实考试，适应考试节奏
        count: 题目数量，可选 5/10/20/30
        difficulty: 难度级别，可选 "简单"/"中等"/"困难"/"考试难度"

    Returns:
        list: [
            {
                "question": str,          # 题目内容
                "answer": str,            # 正确答案
                "analysis": str,          # 详细解析（含解题思路）
                "knowledge_point": str,   # 考察知识点
                "training_purpose": str   # 训练目的
            }
        ]
    """
    # 参数校验
    valid_types = ["基础巩固", "专项提升", "易错变式", "综合应用", "模拟考试"]
    valid_counts = [5, 10, 20, 30]
    valid_difficulties = ["简单", "中等", "困难", "考试难度"]

    if question_type not in valid_types:
        question_type = "基础巩固"
    if count not in valid_counts:
        count = 5
    if difficulty not in valid_difficulties:
        difficulty = "中等"

    if not errors:
        return [{"error": "错题列表为空，无法生成同类题"}]

    # 支持传入单个错误对象
    if isinstance(errors, dict):
        errors = [errors]

    system_prompt = _load_system_prompt()

    # 提取错题的核心信息用于生成
    error_items = []
    for e in errors:
        error_items.append({
            "id": e.get("id", "未知"),
            "content": e.get("content", e.get("question", "")),
            "error_type": e.get("error_type", ""),
            "error_reason": e.get("error_reason", ""),
            "knowledge_points": e.get("knowledge_points", []),
        })

    # 题型设计说明
    type_descriptions = {
        "基础巩固": "针对基础知识点，强化记忆和理解，题目以基础题为主",
        "专项提升": "针对特定薄弱环节，深度训练，题目难度逐步提升",
        "易错变式": "改变常见错误题型，训练识别能力和避免踩坑",
        "综合应用": "多知识点综合，提升应用迁移能力",
        "模拟考试": "模拟真实考试环境和题型分布，适应考试节奏",
    }

    prompt = f"""请根据以下错题信息，生成{count}道「{question_type}」类型的训练题，难度为「{difficulty}」。

{type_descriptions.get(question_type, "")}

错题信息：
{json.dumps(error_items, ensure_ascii=False, indent=2)}

生成要求：
1. 知识点必须与错题保持一致
2. 针对错题的错误原因进行针对性设计
3. 覆盖不同题型变化（选择题、填空题、解答题等）
4. 符合学生年级水平
5. 难度逐步提升（从易到难排列）
6. 禁止只改变数字生成机械重复题
7. 每道题必须包含完整解析

请严格按照以下JSON数组格式输出：
[
    {{
        "question": "题目内容",
        "answer": "正确答案",
        "analysis": "详细解析，包含解题思路和步骤",
        "knowledge_point": "考察的知识点",
        "training_purpose": "训练目的（说明针对什么能力/知识点进行训练）"
    }}
]

注意：共生成{count}道题，数组长度必须为{count}。"""

    try:
        result = _call_llm(
            system_prompt=system_prompt,
            user_prompt=prompt,
            temperature=0.4,
            max_tokens=8192,
        )
        parsed = _parse_json(result)
        if isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            # 可能包裹在某个键下
            for key in ("questions", "exercises", "items", "results"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            return [parsed]
        else:
            return [{"error": f"返回格式异常: {type(parsed)}"}]
    except Exception as e:
        return [{"error": f"同类题生成失败: {str(e)}"}]


# ==================== 便捷管道函数 ====================


def full_pipeline(image_path: str) -> dict:
    """完整试卷分析流水线：质量检测 -> 识别 -> 批改 -> 分析 -> 报告

    Args:
        image_path: 试卷图片路径

    Returns:
        dict: {
            "quality": dict,         # 质量检测结果
            "recognition": dict,     # 识别结果
            "grading": dict,         # 批改结果
            "analysis": dict,        # 错误分析
            "report": str,           # 诊断报告
            "pipeline_status": str   # 流水线状态
        }
    """
    result = {
        "quality": None,
        "recognition": None,
        "grading": None,
        "analysis": None,
        "report": None,
        "pipeline_status": "success",
    }

    # 1. 质量检测
    quality = check_image_quality(image_path)
    result["quality"] = quality
    if not quality.get("pass", False):
        result["pipeline_status"] = "quality_failed"
        result["report"] = (
            "## 试卷图片质量检测未通过\n\n"
            f"**问题列表：**\n"
        )
        for issue in quality.get("issues", []):
            result["report"] += f"- {issue}\n"
        result["report"] += (
            "\n请重新上传清晰完整的试卷图片后重试。"
        )
        return result

    # 2. 内容识别
    recognition = recognize_paper(image_path)
    result["recognition"] = recognition
    if "error" in recognition:
        result["pipeline_status"] = "recognition_failed"
        result["report"] = f"试卷内容识别失败：{recognition['error']}"
        return result

    questions = recognition.get("questions", [])
    if not questions:
        result["pipeline_status"] = "no_questions"
        result["report"] = "未能从试卷中识别出任何题目，请检查图片内容。"
        return result

    # 3. AI批改
    grading = grade_paper(recognition)
    result["grading"] = grading
    if "error" in grading:
        result["pipeline_status"] = "grading_failed"
        result["report"] = f"AI批改失败：{grading['error']}"
        return result

    # 4. 错误分析
    analysis = analyze_errors(grading)
    result["analysis"] = analysis

    # 5. 生成报告
    report = generate_report(recognition, grading, analysis)
    result["report"] = report

    return result


# ==================== 测试代码 ====================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AI智能试卷批改与分析系统 - 命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  # 检测图片质量
  python exam_analyzer.py check -i试卷.jpg

  # 识别试卷内容
  python exam_analyzer.py recognize -i试卷.jpg -o recognition.json

  # 批改试卷
  python exam_analyzer.py grade -r recognition.json -o grading.json

  # 错误分析
  python exam_analyzer.py analyze -g grading.json -o analysis.json

  # 生成完整报告
  python exam_analyzer.py report -i试卷.jpg -o report.md

  # 生成同类题（从stdin输入错题JSON）
  echo '[{"content":"1+1=？","error_type":"计算错误"}]' | python exam_analyzer.py generate -t 基础巩固 -c 5 -d 中等
        """
    )

    parser.add_argument(
        "action",
        choices=["check", "recognize", "grade", "analyze", "report", "generate", "pipeline"],
        help="要执行的操作",
    )
    parser.add_argument("--image", "-i", help="试卷图片路径")
    parser.add_argument("--recognition", "-r", help="识别结果JSON文件路径")
    parser.add_argument("--grading", "-g", help="批改结果JSON文件路径")
    parser.add_argument("--analysis", "-a", help="错误分析JSON文件路径")
    parser.add_argument("--type", "-t", default="基础巩固", help="同类题类型")
    parser.add_argument("--count", "-c", type=int, default=5, help="同类题数量")
    parser.add_argument("--difficulty", "-d", default="中等", help="同类题难度")
    parser.add_argument("--output", "-o", help="输出文件路径")

    args = parser.parse_args()

    # ---- 图片质量检测 ----
    if args.action == "check":
        if not args.image:
            print("错误: 请指定 --image 参数")
            sys.exit(1)
        result = check_image_quality(args.image)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"质量检测结果已保存至: {args.output}")
        else:
            print(output)

    # ---- 试卷内容识别 ----
    elif args.action == "recognize":
        if not args.image:
            print("错误: 请指定 --image 参数")
            sys.exit(1)
        result = recognize_paper(args.image)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"识别结果已保存至: {args.output}")
        else:
            print(output)

    # ---- AI批改 ----
    elif args.action == "grade":
        if not args.recognition:
            print("错误: 请指定 --recognition 参数")
            sys.exit(1)
        with open(args.recognition, "r", encoding="utf-8") as f:
            recognition = json.load(f)
        result = grade_paper(recognition)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"批改结果已保存至: {args.output}")
        else:
            print(output)

    # ---- 错误分析 ----
    elif args.action == "analyze":
        if not args.grading:
            print("错误: 请指定 --grading 参数")
            sys.exit(1)
        with open(args.grading, "r", encoding="utf-8") as f:
            grading = json.load(f)
        result = analyze_errors(grading)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"错误分析结果已保存至: {args.output}")
        else:
            print(output)

    # ---- 生成报告 ----
    elif args.action == "report":
        if args.image:
            # 从图片直接生成完整报告
            result = full_pipeline(args.image)
            report = result.get("report", "生成报告失败")
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"诊断报告已保存至: {args.output}")
            else:
                print(report)
        elif args.recognition and args.grading:
            # 从已有的识别和批改结果生成报告
            with open(args.recognition, "r", encoding="utf-8") as f:
                recognition = json.load(f)
            with open(args.grading, "r", encoding="utf-8") as f:
                grading = json.load(f)
            if args.analysis:
                with open(args.analysis, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
            else:
                analysis = analyze_errors(grading)
            report = generate_report(recognition, grading, analysis)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"诊断报告已保存至: {args.output}")
            else:
                print(report)
        else:
            print("错误: 请指定 --image 参数，或同时指定 --recognition 和 --grading 参数")
            sys.exit(1)

    # ---- 生成同类题 ----
    elif args.action == "generate":
        # 从stdin读取错题JSON
        if not sys.stdin.isatty():
            raw = sys.stdin.read().strip()
            if raw:
                errors_data = json.loads(raw)
            else:
                print("错误: 标准输入为空，请通过stdin传入错题JSON数据")
                sys.exit(1)
        else:
            # 也可以从文件读取
            if args.recognition:
                with open(args.recognition, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 尝试从识别结果中提取错题
                errors_data = data.get("questions", data.get("wrong_questions", [data]))
            else:
                print("错误: 请通过stdin传入错题JSON数据，或使用 --recognition 指定错题文件")
                sys.exit(1)

        result = generate_similar_questions(
            errors=errors_data,
            question_type=args.type,
            count=args.count,
            difficulty=args.difficulty,
        )
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"同类题已保存至: {args.output}")
        else:
            print(output)

    # ---- 完整流水线 ----
    elif args.action == "pipeline":
        if not args.image:
            print("错误: 请指定 --image 参数")
            sys.exit(1)
        result = full_pipeline(args.image)
        output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        # 修正: 使用default=str处理不可序列化的字段
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"完整分析结果已保存至: {args.output}")
        else:
            # 只打印报告文本
            report = result.get("report", "")
            if report:
                print(report)
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))