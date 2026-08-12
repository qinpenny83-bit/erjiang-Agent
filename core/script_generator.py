"""话术生成引擎 — 负责调用LLM生成学情分析与沟通话术"""
import os
from openai import OpenAI
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


from core.prompt_utils import append_constraints


def load_prompt(template_name: str) -> str:
    """加载Prompt模板，自动追加精准性约束"""
    prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
    filepath = os.path.join(prompt_dir, template_name)
    with open(filepath, "r", encoding="utf-8") as f:
        return append_constraints(f.read())


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
    """批量生成学生话术（并发版）"""
    total = len(profiles)
    results = [None] * total
    completed = 0

    def _gen_and_store(i, profile):
        script = generate_student_script(profile)
        return i, {
            "学生姓名": profile["学生姓名"],
            "分层": profile["分层"],
            "流失风险分": profile["流失风险分"],
            "续费剩余(天)": profile["续费剩余(天)"],
            "生成话术": script,
        }

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(_gen_and_store, i, p): i for i, p in enumerate(profiles)}
        for future in as_completed(future_map):
            i, result = future.result()
            results[i] = result
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return results


def generate_student_script_flexible(profile_dict: dict, classification: dict, config: dict = None) -> str:
    """为单个学生生成学情分析与沟通话术（动态字段版本，支持配置）"""
    import pandas as pd

    template = load_prompt("student_segmentation_flexible.txt")

    # 原始数据可能在"原始数据"嵌套中，也可能在顶层
    raw_data = profile_dict.get("原始数据", {})
    if not raw_data:
        raw_data = profile_dict  # 如果顶层就是原始数据

    # 已知元数据键名（不参与数据查找，避免冲突）
    METADATA_KEYS = {"学生姓名", "流失风险分", "风险详情", "触发维度", "成绩下滑红标",
                     "沟通间隔天数", "原始数据", "分层", "回访频率", "下次跟进",
                     "跟进逾期", "风险问题", "续费剩余(天)", "生成话术", "沟通话术",
                     "整改措施", "提升方案", "学生得分"}

    student_data_lines = []
    for cat, cols in classification.items():
        if cat == "未分类":
            continue
        cat_data = []
        for col in cols:
            # 优先从raw_data读取（原始数据），再查顶层，跳过元数据键
            val = None
            if col in raw_data:
                val = raw_data.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                if col not in METADATA_KEYS:
                    val = profile_dict.get(col)
            if pd.notna(val) if not isinstance(val, str) else (val is not None and str(val).strip()):
                val_str = str(val).strip() if val is not None else ""
                if val_str:
                    cat_data.append(f"  - {col}: {val}")
        if cat_data:
            student_data_lines.append(f"【{cat}】")
            student_data_lines.extend(cat_data)

    student_data_text = "\n".join(student_data_lines)

    # 提取所有成绩值，用于AI核对（带列名来源标注）
    score_values = []
    for col in classification.get("成绩信息", []):
        # 优先从raw_data读取，再查顶层，跳过元数据键
        val = None
        if col in raw_data:
            val = raw_data.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            if col not in METADATA_KEYS:
                val = profile_dict.get(col)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            val_str = str(val).strip()
            if val_str and not any(kw in val_str for kw in ["未布置", "未考", "缺考", "免考", "请假", "未参加", "nan", "None", "暂无"]):
                score_values.append(f"【{col}】原始值: {val_str}")
    score_summary = "\n".join(score_values) if score_values else "无成绩数据"

    # 生成成绩趋势说明（按时间顺序排列，帮助AI正确理解升降）
    from core.renewal_risk_engine import extract_score, SEMESTER_ORDER as SO
    trend_entries = []
    for col in classification.get("成绩信息", []):
        val = None
        if col in raw_data:
            val = raw_data.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            if col not in METADATA_KEYS:
                val = profile_dict.get(col)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            s = extract_score(val)
            if s is not None and s > 0:
                # 计算学期排序
                col_str = str(col)
                rank = 999
                for sem, r in SO.items():
                    if sem in col_str:
                        rank = r
                        if "期中" in col_str:
                            rank += 0.51
                        elif "期末" in col_str:
                            rank += 0.99
                        else:
                            rank += 0.75
                        break
                trend_entries.append((rank, col, s))
    trend_entries.sort(key=lambda x: x[0])
    if len(trend_entries) >= 2:
        trend_text_parts = []
        for _, col, s in trend_entries:
            trend_text_parts.append(f"{col}={s}分")
        trend_text = " → ".join(trend_text_parts)
        last_score = trend_entries[-1][2]
        prev_score = trend_entries[-2][2]
        if last_score > prev_score:
            trend_desc = f"成绩趋势：上升（{trend_text}），最新{last_score}分，较上次提升{last_score-prev_score:.1f}分"
        elif last_score < prev_score:
            trend_desc = f"成绩趋势：下降（{trend_text}），最新{last_score}分，较上次下降{prev_score-last_score:.1f}分"
        else:
            trend_desc = f"成绩趋势：持平（{trend_text}），最新{last_score}分"
    else:
        trend_desc = "成绩数据不足，无法判断趋势"

    risk_details = profile_dict.get("风险详情", {})
    risk_text = "; ".join([f"{k}: {v.get('score', 0)}分({'; '.join(v.get('evidence', []))})" for k, v in risk_details.items() if isinstance(v, dict)])

    # 拼接配置信息
    config_text = ""
    if config:
        parts = []
        if config.get("grade") and config.get("subject"):
            parts.append(f"年级学科：{config['grade']}{config.get('semester', '')}{config['subject']}")
        if config.get("course_name"):
            parts.append(f"课程名称：{config['course_name']}")
        if config.get("style"):
            parts.append(f"沟通风格：{config['style']}")
        if config.get("focus"):
            parts.append(f"侧重方向：{'、'.join(config['focus'])}")
        if config.get("avoid"):
            parts.append(f"必须避免：{'、'.join(config['avoid'])}")
        config_text = "\n## 话术生成配置\n" + "\n".join(parts)

    prompt = template.format(
        student_data=student_data_text + config_text,
        流失风险分=profile_dict.get("流失风险分", 0),
        分层=profile_dict.get("分层", "P4"),
        风险详情=risk_text,
        score_summary=score_summary,
        trend_desc=trend_desc,
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": "你是一位资深的教育行业学情分析专家，擅长从复杂数据中提炼关键信息，并转化为有温度、可执行的家长沟通策略。严格依据配置参数生成话术。"},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


def batch_generate_scripts_flexible(profiles: list, classification: dict, progress_callback=None) -> list:
    """批量生成学生话术（动态字段版本，并发版）"""
    total = len(profiles)
    results = [None] * total
    completed = 0

    def _gen_and_store(i, profile):
        script = generate_student_script_flexible(profile, classification)
        return i, {
            "学生姓名": profile["学生姓名"],
            "分层": profile["分层"],
            "流失风险分": profile["流失风险分"],
            "生成话术": script,
        }

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(_gen_and_store, i, p): i for i, p in enumerate(profiles)}
        for future in as_completed(future_map):
            i, result = future.result()
            results[i] = result
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return results


# =====================================================================
# 统一话术生成（新架构 — 阶段四）
# =====================================================================

def generate_student_script_unified(student_dict: dict, config: dict = None) -> str:
    """
    基于统一学生画像生成跟踪服务方案（续费服务策略顾问风格）

    Args:
        student_dict: analyze_students_unified() 返回的单个学生字典
        config: 可选配置，包含 grade, subject, study_period 等筛选条件

    Returns:
        生成的跟踪服务方案文本
    """
    profile = student_dict.get("_profile")
    if profile is None:
        return "无法生成方案：缺少学生画像数据"

    # ========== 构建丰富的结构化数据输入 ==========
    data_parts = []

    # 基本信息
    info = f"学生：{student_dict.get('学生姓名', '未知')}"
    if student_dict.get("年级") and student_dict["年级"] != "未知":
        info += f" | 年级：{student_dict['年级']}"
    info += f" | 风险等级：{student_dict.get('分层', '?')}（{student_dict.get('分层标签', '')}）"
    info += f" | 风险评分：{student_dict.get('流失风险分', 0)}分"
    data_parts.append(info)

    # 配置的筛选条件
    if config:
        config_items = []
        if config.get("grade") and config["grade"] != "全部":
            config_items.append(f"阶段：{config['grade']}")
        if config.get("subject") and config["subject"] != "全部":
            config_items.append(f"科目：{config['subject']}")
        if config.get("study_period") and config["study_period"] != "全部":
            config_items.append(f"在读周期：{config['study_period']}")
        if config_items:
            data_parts.append("配置信息：" + " | ".join(config_items))

    # 风险等级说明（AI分析的核心判断）
    level_desc = student_dict.get("等级说明", "")
    if level_desc:
        data_parts.append(f"风险说明：{level_desc}")

    # 综合判断逻辑（AI分析的核心推理）
    logic = student_dict.get("判断逻辑", "")
    if logic:
        data_parts.append(f"AI判断逻辑：{logic}")

    # 各维度风险详情（精简紧凑）
    dim_risks = student_dict.get("各维度风险", [])
    if dim_risks:
        dim_lines = []
        for dim in dim_risks:
            dim_name = dim.get("维度", "")
            dim_level = dim.get("风险等级", "")
            dim_evidence = dim.get("判断依据", "")
            if dim_name and dim_level:
                line = f"  - {dim_name}【{dim_level}】"
                if dim_evidence:
                    line += f" 依据：{dim_evidence}"
                dim_lines.append(line)
        if dim_lines:
            data_parts.append("各维度风险：")
            data_parts.extend(dim_lines)

    # 原始关键数据
    learn_items = []
    for key, label in [("最近成绩", "成绩"), ("成绩趋势", "趋势"), ("学习表现", "表现"),
                       ("作业完成率", "作业率"), ("听课率", "听课率")]:
        v = student_dict.get(key)
        if v is not None and str(v).strip():
            learn_items.append(f"{label}:{v}")
    if learn_items:
        data_parts.append(f"学习数据：{' '.join(learn_items)}")

    # 家长情况
    parent_items = []
    if student_dict.get("家长态度"):
        parent_items.append(f"态度:{student_dict['家长态度']}")
    signals = student_dict.get("家长信号", [])
    if signals:
        parent_items.append(f"信号:{'、'.join(signals[:3])}")
    if parent_items:
        data_parts.append(f"家长情况：{' '.join(parent_items)}")

    # 服务情况
    service_items = []
    if student_dict.get("续费意愿"):
        service_items.append(f"续费:{student_dict['续费意愿']}")
    if student_dict.get("续费剩余天数") is not None:
        service_items.append(f"剩余:{student_dict['续费剩余天数']}天")
    if student_dict.get("沟通间隔天数") is not None:
        service_items.append(f"沟通间隔:{student_dict['沟通间隔天数']}天")
    if service_items:
        data_parts.append(f"服务情况：{' '.join(service_items)}")

    # 缺失维度
    missing = student_dict.get("缺失维度", [])
    if missing:
        data_parts.append(f"缺失数据（勿编造）：{'、'.join(missing)}")

    # AI建议的下一步动作
    actions = student_dict.get("下一步服务动作", [])
    if actions:
        data_parts.append(f"AI初步建议动作：{'；'.join(actions[:3])}")

    # 从原始数据中提取可能有的科目/在读时间信息
    raw_data = profile.raw_data if hasattr(profile, 'raw_data') else {}
    raw_subject = None
    raw_duration = None
    for col, val in raw_data.items():
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in ["科目", "学科", "课程"]):
            raw_subject = str(val) if val else None
        if any(kw in col_lower for kw in ["在读", "就读", "学习时长", "报名时间"]):
            raw_duration = str(val) if val else None
    if raw_subject and (not config or config.get("subject") in ("全部", None, "")):
        data_parts.append(f"原始科目：{raw_subject}")
    if raw_duration and (not config or not config.get("study_period")):
        data_parts.append(f"原始在读信息：{raw_duration}")

    data_text = "\n".join(data_parts)

    # ========== 阶段策略提示 ==========
    stage_hint = ""
    if config:
        grade = config.get("grade", "全部")
        if any(grade.startswith(kw) for kw in ("一年级", "二年级", "三年级")):
            stage_hint = "该阶段学生重点：学习习惯培养、基础巩固、兴趣建立。策略应侧重习惯引导和正向激励。"
        elif any(grade.startswith(kw) for kw in ("四年级", "五年级", "六年级")):
            stage_hint = "该阶段学生重点：知识漏洞排查、学习方法优化、升学准备。策略应侧重查漏补缺和进步可视化。"
        elif grade in ("初一", "初二", "初三"):
            stage_hint = "该阶段学生重点：成绩提升空间挖掘、学科薄弱点突破、学习效率提升。策略应侧重提分路径规划和竞争分析。"
        elif grade in ("高一", "高二", "高三"):
            stage_hint = "该阶段学生重点：高考应试策略、学科薄弱点突破、学习效率提升。策略应侧重提分路径规划和升学竞争力分析。"
        elif grade == "全部" and student_dict.get("年级"):
            g = str(student_dict.get("年级", ""))
            if any(kw in g for kw in ["一", "二", "三"]):
                stage_hint = "该阶段学生重点：学习习惯培养、基础巩固、兴趣建立。"
            elif any(kw in g for kw in ["四", "五", "六"]):
                stage_hint = "该阶段学生重点：知识漏洞排查、学习方法优化、升学准备。"
            elif any(kw in g for kw in ["初"]):
                stage_hint = "该阶段学生重点：成绩提升空间挖掘、学科薄弱点突破、学习效率提升。"
            elif any(kw in g for kw in ["高"]):
                stage_hint = "该阶段学生重点：高考应试策略、学科薄弱点突破、学习效率提升。策略应侧重提分路径规划和升学竞争力分析。"

    # ========== 系统提示词（续费服务策略顾问风格）==========
    system_prompt = (
        "你是一位在K12教育行业有10年以上续费服务经验的资深二讲主管，"
        "擅长给一线老师提供**续费挽回策略**，帮助老师看到自己没注意到的关键点。\n\n"
        "【核心原则】\n"
        "1. 任何学生都需要尝试挽留，但不要强推。\n"
        "2. 输出完整链路：分析原因 → 找到突破点 → 调整服务方案 → 重新建立价值感 → 推动续费决策。\n"
        "3. 即使家长明确拒绝，也要输出下一步突破策略（如：重新确认真实原因、解决核心顾虑、提供阶段性改善方案、重新创造沟通机会）。\n"
        "4. 禁止出现：放弃挽留、不建议继续跟进、接受家长选择、直接转为维护关系。\n\n"
        "【服务模式】\n"
        "1. 不要生成过度频繁的服务承诺。禁止：每天联系、持续多次电话跟进、高频监督。\n"
        "2. 采用每周一次有效关注模式。\n"
        "3. 按本周关注目标 → 下周反馈节点 → 阶段效果验证 设计服务动作。\n"
        "4. 例如：不是「每天监督孩子学习」，而是「本周围绕数学计算错误问题进行专项关注，下周向家长反馈孩子改善情况」。\n\n"
        "【输出格式】\n"
        "严格按以下6个部分输出，每部分用【】标记：\n\n"
        "【学生当前状态】\n"
        "说明当前续费风险是什么。\n"
        "例如：该生当前核心风险是家长对课程效果产生怀疑，而非成绩问题。\n\n"
        "【核心原因分析】\n"
        "区分：\n"
        "  - 已知事实：（来自学情表的具体数据，如成绩下降、作业未交、家长反馈不满意等）\n"
        "  - 可能原因：（AI推测，每条必须标注「可能原因」，不能把推测当事实）\n\n"
        "【突破方向】\n"
        "告诉老师当前最应该突破什么。\n"
        "例如：不是强调课程优势，而是重新建立家长对学习效果的信心。\n"
        "要给出具体可操作的突破点，而非空泛建议。\n\n"
        "【阶段服务计划】\n"
        "按周设计，不要写每天联系：\n"
        "  - 第1周：老师动作 | 学生动作 | 家长反馈\n"
        "  - 第2周：老师动作 | 学生变化 | 家长沟通\n"
        "  - 阶段效果验证：什么时间点验证什么\n\n"
        "【沟通策略】\n"
        "本次沟通目标。不要直接销售。\n"
        "先：理解顾虑 → 解决问题 → 建立信任 → 推进续费\n"
        "输出：\n"
        "  - 沟通目标：\n"
        "  - 切入角度：\n"
        "  - 关键问题：\n"
        "  - 信号识别：\n\n"
        "【话术】\n"
        "一段可直接使用的沟通话术。\n"
        "要求：\n"
        "  - 家长称呼统一为「XX家长」，禁止使用姐姐、妈妈、宝妈等非正式称呼\n"
        "  - 不夸大承诺，禁止「保证提升」「肯定有效」「一定有效果」\n"
        "  - 强调：基于孩子当前情况制定方案，而非模板化话术\n"
        "  - 自然口语化，有策略性，120-250字\n\n"
        "【禁止行为】\n"
        "1. 放弃挽留、接受家长选择、转为维护关系\n"
        "2. 每天联系、高频监督、持续电话跟进\n"
        "3. 直接贬低竞品、过度承诺\n"
        "4. 使用「多沟通」「加强监督」「持续关注」「请放心」等空泛低价值表达\n"
        "5. 输出老师已经知道的内容（如：多沟通、加强监督、持续关注）\n\n"
        "【核心原则】\n"
        "1. 严格基于提供的数据，不编造\n"
        "2. 缺失数据直接说明，不推测\n"
        "3. 输出老师没想到的：家长真实决策因素、沟通切入角度、服务设计方式、风险突破路径\n"
        "4. 让老师感觉AI不是在帮写一句话，而是在帮制定一个完整的续费挽回策略"
    )

    # 阶段策略提示
    stage_block = ""
    if stage_hint:
        stage_block = f"\n\n【阶段策略提示】\n{stage_hint}"

    user_prompt = (
        "请基于以下学生数据，以资深二讲主管的身份，生成一份完整的跟踪服务方案。\n\n"
        f"{data_text}"
        f"{stage_block}\n\n"
        "请严格按照6段式输出：【学生当前状态】【核心原因分析】【突破方向】【阶段服务计划】【沟通策略】【话术】"
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0.7,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    return response.choices[0].message.content
