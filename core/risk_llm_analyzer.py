"""
AI驱动风险分析引擎
基于统一学生画像，通过LLM进行多维度风险理解与评估
像有经验的二讲老师一样阅读学情表，而不是机械评分
"""
import os
import json
import sys
import time
import random
import hashlib
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, TEMPERATURE, MAX_TOKENS
from core.prompt_utils import get_accuracy_constraints

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 学生级AI分析结果缓存（key=学生数据哈希，value=分析结果）
# 避免同一学生在同一会话中重复分析
_student_cache = {}

# =====================================================================
# 系统提示词 — 定义AI的角色和分析框架
# =====================================================================

SYSTEM_PROMPT = """你是资深K12学情分析师（10年二讲经验）。必须严格输出JSON格式。

【核心原则】
1. 时间线分析优先：最新成绩=当前状态，历史=参考。禁止因历史低分直接判定当前高风险。
2. 问题状态分类：当前存在问题 vs 历史已改善 vs 无法确认。风险判断只能基于"当前存在问题"。
3. 已改善的问题不能作为当前高风险依据。

【风险判断权重（从高到低）】
最高权重：成绩状态与趋势（成绩下降/偏低 > 其他所有风险）
次高权重：家长对课程的态度（近期不满意/投诉 > 沟通频率）
较低权重：沟通间隔时间（仅作为辅助参考，不能单独决定高风险）
综合权重：续费意愿、特殊风险作为补充

【P1-P4等级定义】
- P1（特别关注）：成绩明显下降或不达标 + 家长态度消极，或成绩严重下降 + 多个维度高风险
- P2（需关注）：成绩偏低或下降趋势，或家长态度消极，或续费有阻力
- P3（相对稳定）：成绩正常、家长态度中性、沟通频率偏低但无其他风险
- P4（优）：主动识别优秀学生，需满足：
  * 成绩优秀（≥85分）且无下降趋势，家长反馈积极，沟通正常
  * 成绩良好（≥75分）且趋势上升，家长态度良好，无异常信号

【5维度评估】
每个维度输出：维度名称、风险等级（高/中/低/暂无数据）、判断依据、判断逻辑。
1. 学习效果风险（权重最高）：成绩/趋势/课堂/作业/出勤
2. 家长满意度风险（权重次高）：态度/反馈/投诉
3. 服务连接风险（辅助参考）：沟通频率
4. 续费意愿风险（补充）：续费状态/订金
5. 动态特殊风险（补充）：竞品/时间冲突/厌学

【输出格式】只输出一行JSON，不要markdown、不要解释、不要```包裹：
{"整体风险等级":"P4","等级说明":"简短说明","分层依据":"成绩优秀+趋势上升+家长反馈积极","各维度风险":[{"维度":"学习效果风险","风险等级":"低","判断依据":"成绩100分","判断逻辑":"当前成绩优秀"}],"风险证据":["证据1"],"判断逻辑":"综合判断","下一步服务动作":["动作1"]}"""

# 动态追加精准性约束
_accuracy = get_accuracy_constraints()
if _accuracy:
    SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + _accuracy


def _build_student_data_text(profile_dict: dict) -> str:
    """
    将学生画像转为紧凑自然语言文本，供AI阅读
    """
    lines = [f"学生：{profile_dict.get('学生姓名', '未知')}"]
    if profile_dict.get("年级") and profile_dict["年级"] != "未知":
        lines.append(f"年级：{profile_dict['年级']}")

    # 学习数据
    for key, label in [("最近成绩", "成绩"), ("成绩趋势", "趋势"), ("学习表现", "表现"),
                       ("作业完成率", "作业率"), ("听课率", "听课率")]:
        v = profile_dict.get(key)
        if v is not None and str(v).strip():
            lines.append(f"{label}：{v}")

    # 原始成绩数据（只展示已汇总中未包含的）
    raw_data = profile_dict.get("原始数据", {})
    if raw_data:
        score_keywords = ["成绩", "分数", "得分", "考试", "测试", "月考", "期中", "期末", "单元", "阶段"]
        comm_keywords = ["沟通", "反馈", "家长", "态度", "意见", "诉求", "异议", "投诉", "满意"]
        score_lines = []
        comm_lines = []
        for col, val in raw_data.items():
            col_str = str(col).strip()
            val_str = str(val).strip() if val is not None and not (isinstance(val, float) and pd.isna(val)) else ""
            if not val_str or val_str in ("nan", "None", "-", ""):
                continue
            if any(kw in col_str for kw in ["姓名", "名字", "学生", "年级", "班级", "ID", "编号", "学号"]):
                continue
            if any(kw in col_str for kw in score_keywords):
                score_lines.append(f"{col_str}：{val_str}")
            elif any(kw in col_str for kw in comm_keywords):
                comm_lines.append(f"{col_str}：{val_str}")
        if score_lines:
            lines.append(f"成绩明细：{'；'.join(score_lines[:3])}")
        if comm_lines:
            lines.append(f"沟通明细：{'；'.join(comm_lines[:3])}")

    # 家长数据
    if profile_dict.get("家长态度"):
        lines.append(f"家长态度：{profile_dict['家长态度']}")
    signals = profile_dict.get("家长信号", [])
    if signals:
        lines.append(f"家长信号：{'、'.join(signals[:3])}")

    # 沟通文本（截短）
    if profile_dict.get("_profile") and hasattr(profile_dict["_profile"], "parent"):
        p = profile_dict["_profile"]
        if p.parent.communication:
            lines.append(f"沟通：{p.parent.communication[:300]}")
        if p.parent.concern:
            lines.append(f"诉求：{p.parent.concern[:300]}")

    # 服务数据
    if profile_dict.get("续费意愿"):
        lines.append(f"续费：{profile_dict['续费意愿']}")
    if profile_dict.get("续费剩余天数") is not None:
        lines.append(f"续费剩余：{profile_dict['续费剩余天数']}天")
    if profile_dict.get("沟通间隔天数") is not None:
        lines.append(f"沟通间隔：{profile_dict['沟通间隔天数']}天")

    return "\n".join(lines)


def _generate_fallback_analysis(profile_dict: dict) -> dict:
    """
    当AI返回空或失败时，基于可用数据生成规则化fallback分析。
    确保即使AI不可用，也能给出有数据支撑的分析结果。
    """
    name = profile_dict.get("学生姓名", "未知")
    score = profile_dict.get("最近成绩")
    trend = profile_dict.get("成绩趋势")
    performance = profile_dict.get("学习表现")
    homework = profile_dict.get("作业完成率")
    attendance = profile_dict.get("听课率")
    parent_attitude = profile_dict.get("家长态度")
    renewal = profile_dict.get("续费意愿")
    renewal_days = profile_dict.get("续费剩余天数")
    contact_days = profile_dict.get("沟通间隔天数")
    parent_signals = profile_dict.get("家长信号", [])
    missing = profile_dict.get("缺失维度", [])

    # === 各维度规则化评估 ===
    dimensions = []
    risk_evidences = []
    risk_score_count = 0  # 高风险维度计数

    # 1. 学习效果风险
    learn_risk = "暂无数据"
    learn_reason = "无成绩数据"
    learn_logic = "无法判断"
    if score is not None:
        try:
            s = float(score)
            if s < 60:
                learn_risk = "高"
                learn_reason = f"最新成绩{s}分，处于不及格水平"
                learn_logic = f"当前成绩{s}分偏低，需重点关注学习效果"
                risk_evidences.append(f"最新成绩{s}分（不及格）")
                risk_score_count += 1
            elif s < 75:
                learn_risk = "中"
                learn_reason = f"最新成绩{s}分，处于中等偏下水平"
                learn_logic = f"当前成绩{s}分有提升空间，需关注学习进展"
                risk_evidences.append(f"最新成绩{s}分（中等偏下）")
            elif s < 90:
                learn_risk = "低"
                learn_reason = f"最新成绩{s}分，处于良好水平"
                learn_logic = f"当前成绩{s}分表现良好，保持关注即可"
            else:
                learn_risk = "低"
                learn_reason = f"最新成绩{s}分，处于优秀水平"
                learn_logic = f"当前成绩{s}分表现优秀，无明显风险"
        except (ValueError, TypeError):
            learn_risk = "暂无数据"
            learn_reason = f"成绩数据格式异常：{score}"
            learn_logic = "无法判断"

    if trend:
        if trend in ("下降", "下滑"):
            if learn_risk in ("低", "暂无数据"):
                learn_risk = "中"
            learn_reason += f"；成绩趋势为下降"
            learn_logic += f"；成绩呈下降趋势需警惕"
            risk_evidences.append(f"成绩趋势：下降")
            risk_score_count += 1

    dimensions.append({
        "维度": "学习效果风险",
        "风险等级": learn_risk,
        "判断依据": learn_reason,
        "判断逻辑": learn_logic
    })

    # 2. 家长满意度风险
    parent_risk = "暂无数据"
    parent_reason = "无家长反馈数据"
    parent_logic = "无法判断"
    if parent_attitude:
        if parent_attitude == "消极":
            parent_risk = "高"
            parent_reason = f"家长态度消极"
            parent_logic = "家长当前态度消极，存在满意度风险"
            risk_evidences.append("家长态度消极")
            risk_score_count += 1
        elif parent_attitude == "中性":
            parent_risk = "中"
            parent_reason = "家长态度中性"
            parent_logic = "家长态度中性，需加强沟通引导"
        else:
            parent_risk = "低"
            parent_reason = "家长态度积极"
            parent_logic = "家长态度积极，满意度良好"
    if parent_signals:
        signal_texts = [s for s in parent_signals if isinstance(s, str)]
        if signal_texts:
            parent_reason += f"；检测信号：{'、'.join(signal_texts[:3])}"
            if parent_risk in ("低", "暂无数据"):
                parent_risk = "中"

    dimensions.append({
        "维度": "家长满意度风险",
        "风险等级": parent_risk,
        "判断依据": parent_reason,
        "判断逻辑": parent_logic
    })

    # 3. 服务连接风险
    service_risk = "暂无数据"
    service_reason = "无沟通数据"
    service_logic = "无法判断"
    if contact_days is not None:
        try:
            days = int(contact_days)
            if days > 90:
                service_risk = "高"
                service_reason = f"距上次沟通{days}天，长期失联"
                service_logic = f"沟通间隔{days}天远超安全阈值，服务连接严重断裂"
                risk_evidences.append(f"沟通间隔{days}天（长期失联）")
                risk_score_count += 1
            elif days > 30:
                service_risk = "中"
                service_reason = f"距上次沟通{days}天，沟通频率偏低"
                service_logic = f"沟通间隔{days}天，需尽快恢复联系"
                risk_evidences.append(f"沟通间隔{days}天（频率偏低）")
            elif days > 14:
                service_risk = "低"
                service_reason = f"距上次沟通{days}天"
                service_logic = f"沟通间隔{days}天，保持正常跟进即可"
            else:
                service_risk = "低"
                service_reason = f"距上次沟通{days}天，沟通频率正常"
                service_logic = "沟通频率正常，服务连接良好"
        except (ValueError, TypeError):
            service_risk = "暂无数据"

    dimensions.append({
        "维度": "服务连接风险",
        "风险等级": service_risk,
        "判断依据": service_reason,
        "判断逻辑": service_logic
    })

    # 4. 续费意愿风险
    renewal_risk = "暂无数据"
    renewal_reason = "无续费数据"
    renewal_logic = "无法判断"
    if renewal:
        r = str(renewal).strip()
        if r in ("未续费", "不可续未续", "死磕", "甩班强关", "甩班"):
            renewal_risk = "高"
            renewal_reason = f"续费状态：{r}"
            renewal_logic = f"续费状态为'{r}'，续费意愿风险高"
            risk_evidences.append(f"续费状态：{r}")
            risk_score_count += 1
        elif r in ("一般磕单", "一般关单", "强关"):
            renewal_risk = "中"
            renewal_reason = f"续费状态：{r}"
            renewal_logic = f"续费状态为'{r}'，需加强续费推动"
            risk_evidences.append(f"续费状态：{r}")
        elif r in ("自然续费", "已续费"):
            renewal_risk = "低"
            renewal_reason = f"续费状态：{r}"
            renewal_logic = f"续费状态为'{r}'，续费意愿良好"
        else:
            renewal_risk = "低"
            renewal_reason = f"续费状态：{r}"
            renewal_logic = f"续费状态为'{r}'"

    dimensions.append({
        "维度": "续费意愿风险",
        "风险等级": renewal_risk,
        "判断依据": renewal_reason,
        "判断逻辑": renewal_logic
    })

    # 5. 动态特殊风险
    special_risk = "暂无数据"
    special_reason = "无特殊风险数据"
    special_logic = "无法判断"
    dimensions.append({
        "维度": "动态特殊风险",
        "风险等级": special_risk,
        "判断依据": special_reason,
        "判断逻辑": special_logic
    })

    # === 综合判定（加权评分） ===
    # 权重定义：成绩(3) > 家长态度(2) > 沟通间隔/续费/特殊(1)
    dim_weights = [3, 2, 1, 1, 1]  # 学习效果, 家长满意度, 服务连接, 续费意愿, 动态特殊
    weighted_high = 0
    weighted_mid = 0
    for i, d in enumerate(dimensions):
        w = dim_weights[i]
        if d["风险等级"] == "高":
            weighted_high += w
        elif d["风险等级"] == "中":
            weighted_mid += w

    high_count = sum(1 for d in dimensions if d["风险等级"] == "高")
    mid_count = sum(1 for d in dimensions if d["风险等级"] == "中")
    low_count = sum(1 for d in dimensions if d["风险等级"] == "低")
    data_count = sum(1 for d in dimensions if d["风险等级"] != "暂无数据")

    learn_high = dimensions[0]["风险等级"] == "高"
    learn_mid = dimensions[0]["风险等级"] == "中"
    parent_high = dimensions[1]["风险等级"] == "高"
    parent_mid = dimensions[1]["风险等级"] == "中"

    # === 主动识别优秀层（P4） ===
    # 条件1：成绩优秀≥85分 + 无高中风险 + 无沟通中断
    is_excellent = False
    excellent_reason = ""
    if score is not None:
        try:
            s = float(score)
            has_comm_risk = (contact_days is not None and contact_days > 30)
            has_parent_risk = (parent_attitude == "消极")
            has_renewal_risk = (renewal and str(renewal).strip() not in ("自然续费", "已续费", ""))
            if s >= 85 and high_count == 0 and mid_count == 0 and not has_comm_risk and not has_parent_risk:
                is_excellent = True
                if trend == "上升":
                    excellent_reason = "成绩优秀+趋势上升"
                elif trend == "下降":
                    # 成绩虽好但趋势下降，不能算优秀
                    is_excellent = False
                elif trend == "平稳":
                    excellent_reason = "成绩优秀+趋势平稳"
                else:
                    excellent_reason = "成绩优秀"
            elif s >= 75 and trend == "上升" and high_count == 0 and mid_count == 0 and not has_comm_risk and not has_parent_risk:
                is_excellent = True
                excellent_reason = "成绩良好+趋势上升+各维度低风险"
        except (ValueError, TypeError):
            pass

    # 条件2：无任何中高风险 + 至少2个维度有数据且为低风险
    if not is_excellent and high_count == 0 and mid_count == 0 and low_count >= 2:
        is_excellent = True
        excellent_reason = "各维度均为低风险，无异常信号"

    if is_excellent:
        tier = "P4"
        tier_desc = "各项数据正常，无明显风险"
        tier_reason = excellent_reason
    elif learn_high and parent_high:
        tier = "P1"
        tier_desc = "成绩和家态度均存在高风险，需立即介入"
        tier_reason = f"学习效果高+家长满意度高（加权高={weighted_high}）"
    elif learn_high and parent_mid:
        tier = "P1"
        tier_desc = "成绩高风险+家长态度中等，需重点关注"
        tier_reason = f"学习效果高+家长满意度中（加权高={weighted_high}）"
    elif learn_high:
        tier = "P2"
        tier_desc = "成绩存在高风险，需关注学习效果"
        tier_reason = f"学习效果高风险（加权高={weighted_high}）"
    elif parent_high:
        tier = "P2"
        tier_desc = "家长态度存在高风险，需加强关系维护"
        tier_reason = f"家长满意度高风险（加权高={weighted_high}）"
    elif weighted_high >= 3:
        tier = "P2"
        tier_desc = "加权高风险维度较高"
        tier_reason = f"加权高={weighted_high}（仅辅助维度高风险，核心维度无高风险）"
    elif weighted_high >= 2:
        tier = "P3"
        tier_desc = "辅助维度存在高风险，但成绩和家长正常"
        tier_reason = f"加权高={weighted_high}（仅辅助维度高风险，核心维度正常）"
    elif weighted_mid >= 4:
        tier = "P2"
        tier_desc = "多个维度存在中等风险"
        tier_reason = f"加权中={weighted_mid}"
    elif weighted_mid >= 2:
        tier = "P3"
        tier_desc = "存在中等风险，需关注"
        tier_reason = f"加权中={weighted_mid}"
    elif data_count >= 2:
        tier = "P4"
        tier_desc = "各项数据正常，无明显风险"
        tier_reason = "有数据维度均正常"
    else:
        tier = "P3"
        tier_desc = "数据不足，采用保守评估"
        tier_reason = "数据不足"

    # === 下一步动作 ===
    actions = []
    if contact_days and (isinstance(contact_days, (int, float)) and contact_days > 30):
        actions.append(f"距上次沟通已{int(contact_days)}天，建议本周内联系家长")
    if score is not None:
        try:
            if float(score) < 75:
                actions.append(f"成绩{score}分偏低，建议了解学习困难点并提供辅导方案")
        except (ValueError, TypeError):
            pass
    if renewal and str(renewal).strip() not in ("自然续费", "已续费", ""):
        actions.append(f"续费状态异常，建议优先沟通续费意向")
    if not actions:
        if missing:
            actions.append(f"以下维度暂无数据：{'、'.join(missing[:3])}，建议补充后重新评估")
        else:
            actions.append("保持常规跟进，关注成绩变化和家长期望")

    return {
        "整体风险等级": tier,
        "等级说明": f"基于可用数据的规则化评估（AI未返回有效结果）。{name}：{tier_desc}。",
        "分层依据": tier_reason,
        "各维度风险": dimensions,
        "风险证据": risk_evidences if risk_evidences else ["当前数据不足以识别明确风险"],
        "判断逻辑": f"规则化评估：{tier_desc}。高维度{high_count}个，中维度{mid_count}个，低维度{low_count}个，有效数据维度{data_count}个。",
        "下一步服务动作": actions
    }


def analyze_single_student(profile_dict: dict) -> dict:
    """
    分析单个学生的风险（由 batch_analyze 调用）
    """
    # === 学生级缓存检查 ===
    # 用关键数据构建缓存键，避免相同学生数据重复调用AI
    cache_input = {}
    for key in ["学生姓名", "最近成绩", "作业完成率", "听课率", "家长态度", "续费意愿",
                 "续费剩余天数", "沟通间隔天数", "成绩趋势", "学习表现"]:
        cache_input[key] = profile_dict.get(key)
    # 也包含沟通文本特征
    if profile_dict.get("_profile") and hasattr(profile_dict["_profile"], "parent"):
        p = profile_dict["_profile"]
        cache_input["_comm"] = (p.parent.communication or "")[:50]
        cache_input["_concern"] = (p.parent.concern or "")[:50]
    # 包含原始数据特征（支持时间线分析后，需要更精确的缓存匹配）
    raw_data = profile_dict.get("原始数据", {})
    if raw_data:
        # 只取原始数据的前10个关键值，避免缓存键过大
        raw_snapshot = {k: raw_data[k] for k in list(raw_data.keys())[:20]}
        cache_input["_raw"] = str(raw_snapshot)
    cache_key = hashlib.md5(json.dumps(cache_input, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    if cache_key in _student_cache:
        return _student_cache[cache_key]

    data_text = _build_student_data_text(profile_dict)[:1500]
    name = profile_dict.get("学生姓名", "未知")

    user_prompt = (
        f"分析以下学生数据，输出一行JSON：\n\n{data_text}\n\n"
        f"按时间线分析，缺失标'暂无数据'，不编造。只输出JSON，不要其他文字。"
    )

    try:
        # 重试1次，处理API空返回
        raw_content = None
        for retry in range(2):
            try:
                if retry > 0:
                    time.sleep(1 + random.random())
                response = client.chat.completions.create(
                    model=MODEL_NAME,
                    temperature=0,
                    max_tokens=3000,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ]
                )
                raw_content = response.choices[0].message.content
                if raw_content and raw_content.strip():
                    break
                # 空返回，等待后重试
                if retry < 2:
                    time.sleep(1 + retry)
            except Exception:
                if retry < 2:
                    time.sleep(2 + retry)
                else:
                    raise

        if not raw_content or not raw_content.strip():
            # AI返回空，使用规则化fallback分析
            result = _generate_fallback_analysis(profile_dict)
            result["等级说明"] = f"AI返回内容为空（重试2次），已采用规则化评估。{name}"
            result["风险证据"].insert(0, "AI返回内容为空，重试2次均失败")
            result["判断逻辑"] = "AI返回内容为空，采用规则化评估。" + result["判断逻辑"]
            _student_cache[cache_key] = result
            return result
        content = raw_content.strip()
        # 清理可能的markdown标记
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0].strip()
        # 如果JSON解析失败，尝试提取JSON部分（AI可能输出额外文本）
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 {} 包围的JSON部分
            brace_start = content.find("{")
            brace_end = content.rfind("}")
            if brace_start >= 0 and brace_end > brace_start:
                json_str = content[brace_start:brace_end+1]
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError:
                    # JSON可能被截断（max_tokens不够），尝试修复
                    # 找到最后一个完整的键值对，截断后补全
                    last_comma = json_str.rfind(',')
                    if last_comma > 0:
                        # 从最后一个逗号处截断，补全 }]}
                        truncated = json_str[:last_comma] + '}]}'
                        try:
                            result = json.loads(truncated)
                        except json.JSONDecodeError:
                            # 再尝试：只保留到最后一个完整的数组元素
                            last_bracket = json_str.rfind('}')
                            if last_bracket > brace_start:
                                truncated2 = json_str[:last_bracket+1] + ']}'
                                try:
                                    result = json.loads(truncated2)
                                except json.JSONDecodeError:
                                    raise
                    else:
                        raise
            else:
                # 最后尝试：在内容中搜索 "整体风险等级" 并手动构建JSON
                if "整体风险等级" in content:
                    import re
                    tier_match = re.search(r'整体风险等级["\':\s]+([Pp][1-4])', content)
                    if tier_match:
                        tier = tier_match.group(1).upper()
                        # 用规则化fallback做维度分析，保留AI的风险等级判断
                        result = _generate_fallback_analysis(profile_dict)
                        result["整体风险等级"] = tier
                        result["等级说明"] = f"AI返回非标准JSON，已提取风险等级并结合规则化评估。{name}"
                        result["风险证据"].insert(0, "AI返回非标准JSON格式，已提取风险等级")
                        result["判断逻辑"] = "AI返回非标准JSON，从中提取风险等级=" + tier + "。" + result["判断逻辑"]
                    else:
                        raise
                else:
                    raise
        # 写入缓存
        _student_cache[cache_key] = result
        return result
    except json.JSONDecodeError as e:
        # 记录到日志文件便于调试
        _debug_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "debug_ai_response.log")
        try:
            os.makedirs(os.path.dirname(_debug_log_path), exist_ok=True)
            with open(_debug_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"学生: {name} | 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"JSON解析错误: {str(e)[:100]}\n")
                f.write(f"AI返回内容:\n{content}\n")
                f.write(f"{'='*60}\n")
        except Exception:
            pass
        # 使用规则化fallback
        result = _generate_fallback_analysis(profile_dict)
        result["等级说明"] = f"AI分析结果解析失败，已采用规则化评估。{name}"
        result["风险证据"].insert(0, "AI返回格式异常，已记录日志")
        result["判断逻辑"] = "AI返回格式异常，采用规则化评估。" + result["判断逻辑"]
        _student_cache[cache_key] = result
        return result
    except Exception as e:
        # 使用规则化fallback
        result = _generate_fallback_analysis(profile_dict)
        result["等级说明"] = f"AI分析调用失败，已采用规则化评估。{name}"
        result["风险证据"].insert(0, f"AI调用异常: {str(e)[:80]}")
        result["判断逻辑"] = "AI调用失败，采用规则化评估。" + result["判断逻辑"]
        _student_cache[cache_key] = result
        return result


def analyze_batch(profiles: list, batch_size: int = 8, progress_callback=None) -> list:
    """
    批量分析学生风险 — 逐个调用AI分析，使用并发加速

    Args:
        profiles: UnifiedStudentProfile 列表
        batch_size: 并发数（同时处理的学生数量）
        progress_callback: 进度回调函数(processed, total)

    Returns:
        [{"profile": profile, "ai_result": dict, "student_dict": dict}, ...]
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    student_dicts = []
    for p in profiles:
        d = p.to_dict()
        d["_profile"] = p
        student_dicts.append(d)

    total = len(student_dicts)
    results = [None] * total

    # 使用原子计数器避免O(n)遍历
    completed = 0

    # 使用并发逐个分析（每个学生一个API调用，比批量调用更稳定）
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        future_map = {}
        for i, sd in enumerate(student_dicts):
            # 交错提交避免瞬间全部请求同时到达API
            if i > 0 and i % batch_size == 0:
                time.sleep(0.3)
            future = executor.submit(analyze_single_student, sd)
            future_map[future] = i

        for future in as_completed(future_map):
            idx = future_map[future]
            sd = student_dicts[idx]
            try:
                ai_result = future.result()
            except Exception as e:
                ai_result = _fallback_analysis(sd, str(e)[:50])

            results[idx] = {
                "profile": sd.get("_profile"),
                "ai_result": ai_result,
                "student_dict": sd,
            }

            # 更新进度（O(1)原子计数器）
            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return results


def _fallback_analysis(student_dict: dict, reason: str) -> dict:
    """
    当AI分析失败时的降级方案 — 使用规则化分析
    """
    return _generate_fallback_analysis(student_dict)


def build_risk_scores(ai_results: list) -> list:
    """
    将AI分析结果转换为风险评分（用于排序）

    P1=100, P2=70, P3=40, P4=10
    加权维度修正：成绩/家长(1.5x) > 沟通间隔(0.5x) = 续费/特殊(1.0x)
    """
    tier_base = {"P1": 100, "P2": 70, "P3": 40, "P4": 10}
    level_scores = {"高": 10, "中": 0, "低": -10, "暂无数据": 0}
    # 维度权重：成绩=家长态度 > 续费=特殊 > 沟通间隔（辅助参考）
    dim_weights = {
        "学习效果风险": 1.5,
        "家长满意度风险": 1.5,
        "服务连接风险": 0.5,
        "续费意愿风险": 1.0,
        "动态特殊风险": 1.0,
    }

    for item in ai_results:
        ai = item["ai_result"]
        tier = ai.get("整体风险等级", "P3")
        base = tier_base.get(tier, 40)

        # 加权维度修正
        dim_adjust = 0
        for dim in ai.get("各维度风险", []):
            level = dim.get("风险等级", "暂无数据")
            dim_name = dim.get("维度", "")
            weight = dim_weights.get(dim_name, 1.0)
            dim_adjust += level_scores.get(level, 0) * weight

        # 风险证据数量修正
        evidence_count = len(ai.get("风险证据", []))
        evidence_adjust = min(evidence_count * 5, 15)

        score = max(0, min(100, base + dim_adjust + evidence_adjust))
        item["risk_score"] = score

    return ai_results