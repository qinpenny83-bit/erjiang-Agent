"""家长答疑回复生成器 — 沟通策略顾问模式（六段式结构化输出，Tab2升级版）

输出结构（新版六段式，向后兼容旧四段式）：
一、问题判断（证据边界三分类：已知事实/基于事实的分析/待确认信息+关键核实问题；诉求识别4字段）
二、沟通策略（含"本次沟通成功标准"，区分事实与分析）
三、沟通依据与风险提醒（真实依据 + 注意避免，无数据时明确标注）
四、家长沟通话术（禁止编造成绩/进步/课堂表现）
五、家长回应分支（情况A/B/C：家长可能回应/老师推荐回应/沟通目的）
六、行动方案（缺关键数据时优先确认/诊断）

证据边界原则：有依据才下结论，没有依据明确说明，绝不为内容完整而自行补全。
"""
import os
import sys
import re
import base64
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
# 截图OCR（视觉模型还原真实对话，杜绝脑补截图内容）
# ============================================================

def _detect_mime(data: bytes) -> str:
    """按文件头识别图片MIME类型"""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/png"


def _ocr_screenshot(image_bytes: bytes) -> str:
    """用视觉模型识别聊天截图，返回还原的对话文本；失败/无法识别返回空串。
    vision实验模型识别不稳定，内部重试1次提高成功率。"""
    if not image_bytes:
        return ""
    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _detect_mime(image_bytes)
        vision_model = os.environ.get("VISION_MODEL", "deepseek-v4-flash-vision-exp")

        def _call_once() -> str:
            resp = client.chat.completions.create(
                model=vision_model,
                temperature=0,
                max_tokens=1500,
                timeout=45,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            "这是一段老师和家长的微信聊天记录截图。请逐条还原对话内容，要求：\n"
                            "1. 按顺序区分【家长】和【老师】的消息\n"
                            "2. 原样转述文字，不概括、不改写、不加评论\n"
                            "3. 截图中出现的成绩、分数、日期、数字必须原样保留，禁止修改\n"
                            "4. 看不清或无法确定的部分标注[无法辨认]，禁止猜测\n"
                            "5. 只输出对话内容本身，不要任何分析\n"
                            "如果整张图没有可识别的对话内容，只输出：[无有效内容]")},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}},
                    ],
                }],
            )
            return (resp.choices[0].message.content or "").strip()

        for attempt in range(2):
            text = _call_once()
            if text and "[无有效内容]" not in text:
                return text
            print(f"[QA] 截图OCR第{attempt + 1}次未识别到有效内容")
        return ""
    except Exception as e:
        print(f"[QA] 截图OCR失败: {type(e).__name__}: {e}")
        return ""


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


def _strip_field_emojis(section_text: str, fields: list) -> str:
    """剥离行首字段名前的emoji符号（AI可能在字段名前加🟢🔵🟡等），保证解析稳定"""
    names = "|".join(re.escape(f) for f in fields)
    return re.sub(rf'(?m)^(\s*)[🟢🔵🟡❓✅⚠️⭐📌💬🔄📋🎯]+\s*({names})([：:])',
                  r'\1\2\3', section_text)


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

    # --- 一、问题判断（证据边界三分类 + 诉求分析，保留旧字段兼容） ---
    diag_text = _section(r"问题判断")
    if diag_text:
        DIAG_FIELDS = [
            "已知事实", "基于事实的分析", "待确认信息", "关键核实问题",
            "学生当前情况", "表层问题", "核心诉求", "情绪状态", "沟通阶段",
            "家长核心顾虑", "解决重点",
        ]
        diag_text = _strip_field_emojis(diag_text, DIAG_FIELDS)
        diag_fields = _extract_fields(diag_text, DIAG_FIELDS)
        # 列表型字段拆条
        for lf in ("已知事实", "基于事实的分析", "待确认信息", "关键核实问题"):
            diag_fields[lf] = _split_lines(diag_fields.get(lf, ""))
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

    # 构建问题描述（截图先OCR还原为真实文本，杜绝脑补截图内容）
    has_text = bool(question and question.strip())
    ocr_text = _ocr_screenshot(image_data) if image_data else ""

    if (has_text or image_data) and ocr_text:
        text_part = f"家长问题（文字补充）：{question}\n\n" if has_text else ""
        question_desc = (
            f"{text_part}【截图识别内容（🟢事实：以下为截图OCR还原的对话，只可引用其中明确可读的部分，[无法辨认]处禁止猜测）】\n"
            f"{ocr_text}\n\n"
            "⚠️ 以上就是老师和家长的聊天记录本身（不是家长发给老师的截图）：\n"
            "1. 左侧消息 = 家长发的，右侧消息 = 老师（我们）发的\n"
            "2. 还原对话全貌：谁先说的→对方怎么回的→最后停在哪个话题\n"
            "3. 判断老师之前的回复是否恰当，如有不当需在沟通注意事项中指出\n"
            "4. 家长最后一条消息是当前需要回复的核心问题\n"
            "5. 截图中明确可读的成绩、日期、数字属于已知事实，只能原样引用，不得扩展\n"
            "6. 话术中只能说「看到您发的消息」，严禁说「看到您的截图」"
        )
    elif has_text and image_data:
        # OCR失败：明确标注无法识别，严禁虚构
        question_desc = (
            f"家长问题（文字补充）：{question}\n\n"
            "⚠️ 老师上传了一段和家长微信聊天截图，但截图内容暂无法准确识别，建议人工核实。\n"
            "严禁虚构截图中的任何对话和数据；必须在「待确认信息」中标注\"截图内容需人工核实\"，"
            "并建议老师补充截图中的关键信息（如家长原话、提到的成绩）。"
        )
    elif image_data:
        question_desc = (
            "⚠️ 老师上传了一段和家长微信聊天截图，但截图内容暂无法准确识别，建议人工核实。\n"
            "严禁虚构截图中的任何对话和数据；必须在「待确认信息」中标注\"截图内容需人工核实\"，"
            "并建议老师补充截图中的关键信息（如家长原话、提到的成绩）。"
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
        "你的输出必须严格按六段式结构：问题判断（证据边界：已知事实/基于事实的分析/待确认信息+关键核实问题，"
        "及诉求识别）→ 沟通策略（含动态成功标准，区分事实与分析）→ "
        "沟通依据与风险提醒（真实依据+踩雷提醒）→ 家长沟通话术（>=300字）→ 家长回应分支（预判2-3种回应）→ 行动方案。\n"
        "幻觉拦截铁律（最高优先级）：【家长问题】和【学生背景】中没有明确出现的信息，禁止以任何形式生成——"
        "包括成绩、排名、分数变化、进步退步、课堂表现、作业情况、学习习惯/能力/态度定性、家长真实心理、"
        "学校课程进度教材内容、'通常某年级都会'式群体判断、任何课程效果结论。"
        "拿不准某信息是否真实存在时，一律放入'待确认信息'，绝不猜。\n"
        "证据边界：🟢已知事实只能原样转述用户提供的信息，不得改写成更强结论；"
        "🔵分析必须对应到具体事实，推测用'可能/倾向于/建议进一步确认'；🟡待确认信息绝不自行补齐。\n"
        "沟通依据无客观数据时必须写'暂无可引用的客观学习数据。'\n"
        "禁止低价值模板话术，所有回复必须结合学生实际情况。"
        "话术自然口语化，像真实二讲老师，禁止机器人腔和'我理解您的心情'式套话。"
        "当输入包含【截图识别内容】时，那截图就是老师和家长的聊天记录本身，不是家长发给老师的图片，"
        "只能引用其中明确可读的部分；截图无法识别时严禁虚构截图内容。"
        "话术中严禁说「看到您的截图」之类的话，只能说「看到您发的消息」"
    )

    # 完整性校验：六段核心内容必须存在（防v4-flash空返回/截断）
    def _is_complete(parsed: dict, raw: str) -> bool:
        if len(raw) < 300:
            return False
        diag = parsed["问题判断"]
        # 新版：已知事实必填；旧版兼容：学生当前情况
        if not (diag.get("已知事实") or diag.get("学生当前情况")):
            return False
        if not diag.get("表层问题"):
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
                max_tokens=4000,
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
