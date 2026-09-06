"""家长答疑回复生成器 — 沟通策略顾问模式（六段式结构化输出，Tab2升级版）

输出结构（新版六段式，向后兼容旧四段式）：
一、问题判断（事实与AI分析分离：学生当前情况/表层问题=事实；核心诉求/情绪状态/沟通阶段=AI分析）
二、沟通策略（含"本次沟通成功标准"）
三、沟通依据与风险提醒（真实依据 + 注意避免）
四、家长沟通话术
五、家长回应分支（情况A/B/C：家长可能回应/老师推荐回应/沟通目的）
六、行动方案
"""
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


# ============================================================
# 解析工具
# ============================================================

def _split_lines(text: str) -> list:
    """把多行列表文本拆成条目（去掉-、①等前缀符号和空行）"""
    if not text:
        return []
    items = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 去掉列表前缀符号
        line = re.sub(r'^[-•·①②③④⑤⑥⑦⑧1-9][.、)）]?\s*', '', line)
        if line:
            items.append(line)
    return items


def _extract_fields(section_text: str, fields: list) -> dict:
    """从段落文本中按字段名提取内容（支持多行，直到下一个已知字段）"""
    result = {}
    others = [re.escape(f) for f in fields]
    for field in fields:
        pattern = rf'{re.escape(field)}[：:]\s*(.*?)(?=\n\s*(?:{"|".join(others)})[：:]|\Z)'
        m = re.search(pattern, section_text, re.DOTALL)
        result[field] = m.group(1).strip() if m else ""
    return result


def _parse_branches(section_text: str) -> list:
    """解析家长回应分支：按"情况A/B/C"切分，每个分支含3个子字段"""
    branches = []
    if not section_text:
        return branches
    # 按"情况X："切分（容忍前面有emoji或空白）
    parts = re.split(r'\n(?=\s*(?:🔄\s*)?情况[A-ZＡ-Ｚ][：:])', section_text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        title_m = re.match(r'((?:🔄\s*)?情况[A-ZＡ-Ｚ][：:][^\n]*)', part)
        if not title_m:
            continue
        title = title_m.group(1).strip()
        fields = _extract_fields(part, ["家长可能回应", "老师推荐回应", "沟通目的"])
        if any(v for v in fields.values()):
            branches.append({"标题": title, **fields})
    return branches


def _parse_sections(raw_text: str) -> dict:
    """解析AI输出的六段式结构化文本（兼容旧四段式）"""
    result = {
        "问题判断": {},
        "沟通策略": {},
        "沟通依据": {"真实依据": [], "注意避免": []},
        "话术": "",
        "回应分支": [],
        "行动方案": {},
        "raw": raw_text,
    }

    def _section(name_pattern: str) -> str:
        """提取【X、名称】到下一个【之间的正文"""
        m = re.search(
            rf'【[^】]*{name_pattern}[^】]*】[^\n]*\n(.*?)(?=【[^】]*】|\Z)',
            raw_text, re.DOTALL)
        return m.group(1).strip() if m else ""

    # --- 一、问题判断（新增诉求分析4字段，保留旧字段） ---
    diag_text = _section(r"问题判断")
    if diag_text:
        diag_fields = _extract_fields(diag_text, [
            "学生当前情况", "表层问题", "核心诉求", "情绪状态", "沟通阶段",
            "家长核心顾虑", "解决重点",
        ])
        result["问题判断"] = diag_fields

    # --- 二、沟通策略（新增成功标准） ---
    strat_text = _section(r"沟通策略")
    if strat_text:
        strat_fields = _extract_fields(strat_text, [
            "沟通目标", "本次沟通成功标准", "最佳切入点", "沟通注意事项",
        ])
        strat_fields["本次沟通成功标准"] = _split_lines(strat_fields.get("本次沟通成功标准", ""))
        result["沟通策略"] = strat_fields

    # --- 三、沟通依据与风险提醒 ---
    evid_text = _section(r"沟通依据")
    if evid_text:
        m1 = re.search(r'可使用的真实依据[：:]\s*(.*?)(?=\n\s*注意避免[：:]|\Z)', evid_text, re.DOTALL)
        m2 = re.search(r'注意避免[：:]\s*(.*)', evid_text, re.DOTALL)
        result["沟通依据"]["真实依据"] = _split_lines(m1.group(1)) if m1 else []
        result["沟通依据"]["注意避免"] = _split_lines(m2.group(1)) if m2 else []

    # --- 四、话术 ---
    m_script = re.search(r'【[^】]*家长沟通话术】[^\n]*\n(.*?)(?=【[^】]*】|\Z)', raw_text, re.DOTALL)
    if m_script:
        result["话术"] = m_script.group(1).strip()

    # --- 五、家长回应分支 ---
    branch_text = _section(r"回应分支")
    if branch_text:
        result["回应分支"] = _parse_branches(branch_text)

    # --- 六、行动方案 ---
    action_text = _section(r"行动方案")
    if action_text:
        result["行动方案"] = _extract_fields(action_text, [
            "老师下一步", "学生下一步", "家长配合", "后续跟踪时间",
        ])

    return result


def generate_qa_response(question: str, student_context: dict = None, image_data: bytes = None) -> dict:
    """
    沟通策略顾问模式：1次API调用，输出六段式结构化分析。
    支持文字输入、截图输入、或两者结合。
    """
    # 构建学生上下文
    student_info = "暂无学生背景数据（老师未填写），请基于问题本身和家长常见场景分析，学生相关事实信息一律标注'暂无数据'。"
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
        "你的输出必须严格按六段式结构：问题判断（诉求识别，区分事实与AI分析）→ 沟通策略（含动态成功标准）→ "
        "沟通依据与风险提醒（真实依据+踩雷提醒）→ 家长沟通话术（>=300字）→ 家长回应分支（预判2-3种回应）→ 行动方案。"
        "铁律：学生背景中没有的数据绝对不能编造，推测必须用'从措辞看/可能'等表述与事实区分。"
        "禁止低价值模板话术，所有回复必须结合学生实际情况。"
        "话术自然口语化，像真实二讲老师，禁止机器人腔和'我理解您的心情'式套话。"
        "当用户上传截图时，那截图就是老师和家长的聊天记录本身，不是家长发给老师的图片。"
        "话术中严禁说「看到您的截图」之类的话，只能说「看到您发的消息」"
    )

    # 完整性校验：六段核心内容必须存在（防v4-flash空返回/截断）
    def _is_complete(parsed: dict, raw: str) -> bool:
        if len(raw) < 300:
            return False
        if not parsed["问题判断"].get("表层问题"):
            return False
        if not parsed["沟通策略"].get("沟通目标"):
            return False
        if not parsed["话术"] or len(parsed["话术"]) < 200:
            return False
        if not parsed["行动方案"].get("老师下一步"):
            return False
        return True

    import time as _time
    raw_content = ""
    parsed = _parse_sections("")

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                temperature=0.1,
                max_tokens=3500,
                timeout=60,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ]
            )
            raw_content = (response.choices[0].message.content or "").strip()
            parsed = _parse_sections(raw_content)
            if _is_complete(parsed, raw_content):
                break  # 完整，直接采用
            print(f"[QA] 返回不完整(长度{len(raw_content)})，重试 {attempt + 1}/3")
        except Exception as e:
            print(f"[QA] 异常: {type(e).__name__}: {e}，重试 {attempt + 1}/3")
        _time.sleep(2)

    return {
        "question": question,
        "问题判断": parsed["问题判断"],
        "沟通策略": parsed["沟通策略"],
        "沟通依据": parsed["沟通依据"],
        "话术": parsed["话术"],
        "回应分支": parsed["回应分支"],
        "行动方案": parsed["行动方案"],
        "raw": raw_content,
    }
