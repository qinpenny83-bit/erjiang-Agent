"""学生分析器 — AI驱动的风险分析引擎"""
import os
import sys
import hashlib
import json
import pickle

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.excel_parser import df_to_profiles, parse_uploaded_excel
from core.script_generator import batch_generate_scripts

# 文件级分析结果缓存（内存+磁盘双缓存，避免重复上传同一文件时重复分析）
_analysis_cache = {}
_analysis_cache_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache", "analysis_cache.pkl"
)

# 启动时从磁盘加载缓存
def _load_cache_from_disk():
    global _analysis_cache
    try:
        if os.path.exists(_analysis_cache_path):
            with open(_analysis_cache_path, "rb") as f:
                _analysis_cache = pickle.load(f)
    except Exception:
        _analysis_cache = {}

# 写入磁盘缓存
def _save_cache_to_disk():
    try:
        os.makedirs(os.path.dirname(_analysis_cache_path), exist_ok=True)
        with open(_analysis_cache_path, "wb") as f:
            pickle.dump(_analysis_cache, f)
    except Exception:
        pass

# 加载已有缓存
_load_cache_from_disk()


# =====================================================================
# AI驱动风险分析（新架构 V2）
# =====================================================================

def analyze_students_unified(df, generate: bool = False, progress_callback=None) -> dict:
    """
    统一学情分析流程（AI驱动）：
    1. 语义识别 → 2. 统一画像 → 3. AI风险分析 → 4. 分层排序

    Args:
        df: 原始数据DataFrame
        generate: 是否生成话术（保留参数，话术在UI端单独生成）
        progress_callback: 进度回调函数(processed, total)

    Returns:
        {
            tier_stats: {P1: N, P2: N, P3: N, P4: N},
            total: int,
            students: [{学生姓名, 分层, 风险证据, 判断逻辑, 下一步服务动作, 各维度风险, ...}],
            recognition: dict,
        }
    """
    from utils.excel_parser import build_unified_profiles
    from core.risk_llm_analyzer import analyze_batch, build_risk_scores

    # === 文件级缓存检查 ===
    # 用DataFrame的列名+行数+前5行数据+后5行数据的哈希作为缓存键
    df_hash_input = (
        str(list(df.columns)) +
        str(len(df)) +
        df.head(5).to_json(orient="records") +
        df.tail(5).to_json(orient="records")
    )
    cache_key = hashlib.md5(df_hash_input.encode("utf-8")).hexdigest()
    if cache_key in _analysis_cache:
        return _analysis_cache[cache_key]

    profiles = build_unified_profiles(df)

    if not profiles:
        return {
            "tier_stats": {"P1": 0, "P2": 0, "P3": 0, "P4": 0},
            "total": 0,
            "students": [],
            "recognition": {},
        }

    # 阶段1：AI风险分析（批量处理）
    if progress_callback:
        progress_callback(0, len(profiles))

    ai_results = analyze_batch(profiles, batch_size=10, progress_callback=progress_callback)

    # 阶段2：构建风险评分（用于排序）
    ai_results = build_risk_scores(ai_results)

    # 阶段3：构建学生字典
    students = []
    tier_labels = {"P1": "特别关注", "P2": "需关注", "P3": "相对稳定", "P4": "优"}

    for item in ai_results:
        p = item["profile"]
        ai = item["ai_result"]
        risk_score = item["risk_score"]

        # 从AI获取分层
        ai_tier = ai.get("整体风险等级", "P3")
        if ai_tier not in tier_labels:
            ai_tier = "P3"

        # 风险证据
        evidence = ai.get("风险证据", [])
        evidence_text = evidence if isinstance(evidence, list) else [str(evidence)]

        # 各维度风险
        dim_risks = ai.get("各维度风险", [])

        # 构建评分依据（从各维度风险提取）
        scoring_evidence = []
        for dim in dim_risks:
            scoring_evidence.append({
                "维度": dim.get("维度", "未知"),
                "数据": dim.get("判断依据", ""),
                "规则": dim.get("判断逻辑", ""),
                "得分": dim.get("风险等级", "暂无数据"),
            })

        # 构建风险触发
        triggers = []
        for dim in dim_risks:
            if dim.get("风险等级") == "高":
                triggers.append(f"{dim.get('维度', '')}高")
            elif dim.get("风险等级") == "中":
                triggers.append(f"{dim.get('维度', '')}中")
        # 从证据也提取
        for ev in evidence_text:
            triggers.append(ev)

        # 去重
        triggers = list(dict.fromkeys(triggers))

        student_dict = {
            "学生姓名": p.name,
            "年级": p.grade or "未知",
            "班级": p.class_name or "未知",
            "分层": ai_tier,
            "分层标签": tier_labels[ai_tier],
            "分层依据": ai.get("分层依据", ""),
            "流失风险分": risk_score,
            "风险触发": triggers[:8],  # 限制数量
            "评分依据": scoring_evidence,
            "判断逻辑": ai.get("判断逻辑", ""),
            "下一步服务动作": ai.get("下一步服务动作", []),
            "各维度风险": dim_risks,
            "等级说明": ai.get("等级说明", ""),
            "缺失维度": p.missing_dimensions,
            # 展开关键维度值
            "最近成绩": p.learning.score_level,
            "成绩趋势": p.learning.score_trend,
            "学习表现": p.learning.performance,
            "作业完成率": f"{p.learning.homework_rate:.0%}" if p.learning.homework_rate is not None else None,
            "听课率": f"{p.learning.attendance_rate:.0%}" if p.learning.attendance_rate is not None else None,
            "家长态度": p.parent.attitude,
            "家长信号": [s["label"] for s in p.parent.signals],
            "续费意愿": p.service.renewal_intention,
            "续费剩余天数": p.service.renewal_days,
            "沟通间隔天数": p.service.last_contact_days,
            # 保留原始数据供话术生成使用
            "_profile": p,
        }
        students.append(student_dict)

    # 阶段4：按风险分排序，保留AI原始分层
    students.sort(key=lambda s: s["流失风险分"], reverse=True)

    # ================================================================
    # 阶段5：群体分布校准 — 避免优秀层为空，禁止将风险学生调为优秀
    # ================================================================
    def _calibrate_group_distribution(students: list) -> list:
        total = len(students)
        if total < 10:
            return students
        p4_count = sum(1 for s in students if s["分层"] == "P4")
        if p4_count / total >= 0.05:
            return students

        # 从P3中寻找可提升的候选人
        p3_candidates = []
        for s in students:
            if s["分层"] != "P3":
                continue
            dim_risks = s.get("各维度风险", [])
            has_high = any(d.get("风险等级") == "高" for d in dim_risks)
            has_mid = any(d.get("风险等级") == "中" for d in dim_risks)
            if has_high or has_mid:
                continue
            score = s.get("最近成绩")
            comm_gap = s.get("沟通间隔天数")
            parent = s.get("家长态度")
            renewal = s.get("续费意愿", "")
            if comm_gap and comm_gap > 30:
                continue
            if parent == "消极":
                continue
            if renewal and renewal not in ("自然续费", "已续费", ""):
                continue
            excellence = 0
            if score is not None:
                try:
                    sv = float(score)
                    if sv >= 85:
                        excellence += 30
                        trend = s.get("成绩趋势")
                        if trend == "上升":
                            excellence += 20
                        elif trend == "平稳":
                            excellence += 10
                    elif sv >= 75:
                        excellence += 15
                except (ValueError, TypeError):
                    pass
            low_count = sum(1 for d in dim_risks if d.get("风险等级") == "低")
            excellence += low_count * 5
            if excellence > 0:
                p3_candidates.append((s, excellence))

        p3_candidates.sort(key=lambda x: x[1], reverse=True)
        target_p4 = max(1, int(total * 0.05))
        promote_count = max(0, target_p4 - p4_count)
        for s, _ in p3_candidates[:promote_count]:
            s["分层"] = "P4"
            s["分层标签"] = tier_labels["P4"]
            if not s.get("分层依据") or s["分层依据"] == "数据不足":
                s["分层依据"] = "群体校准：从P3提升至P4（成绩良好+各维度无风险）"
            else:
                s["分层依据"] = "群体校准→P4：" + s.get("分层依据", "")
        return students

    students = _calibrate_group_distribution(students)

    tier_stats = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}

    # 保留AI原始分层，不做强制百分位分配
    # 只对明显不合理的情况做微调
    for s in students:
        tier_stats[s["分层"]] += 1

    # 添加分层说明
    total = len(students)
    for s in students:
        s["评分依据"].append({
            "维度": "分层方式",
            "数据": "AI综合评估（保留原始分层）",
            "规则": "AI风险分析 + 排序",
            "得分": s["流失风险分"],
        })

    # 获取识别结果
    recognition = profiles[0].recognition if profiles else {}

    result = {
        "tier_stats": tier_stats,
        "total": total,
        "students": students,
        "recognition": recognition,
    }

    # 存入缓存（内存+磁盘双缓存）
    _analysis_cache[cache_key] = result
    _save_cache_to_disk()

    return result


# =====================================================================
# 旧版分析（保留兼容）
# =====================================================================

def analyze_students(df) -> dict:
    """
    完整学情分析流程（旧版，保留兼容）
    """
    profiles = df_to_profiles(df)
    profiles.sort(key=lambda p: p.priority)

    tier_stats = {"S": 0, "A": 0, "B": 0, "C": 0}
    for p in profiles:
        tier_stats[p.tier] += 1

    profile_dicts = [p.to_dict() for p in profiles]

    return {
        "tier_stats": tier_stats,
        "total": len(profiles),
        "students": profile_dicts,
    }


def analyze_and_generate_scripts(df, generate: bool = True, progress_callback=None) -> dict:
    """旧版分析 + 话术生成（保留兼容）"""
    result = analyze_students(df)
    if generate:
        scripts = batch_generate_scripts(result["students"], progress_callback=progress_callback)
        script_map = {s["学生姓名"]: s["生成话术"] for s in scripts}
        for student in result["students"]:
            student["沟通话术"] = script_map.get(student["学生姓名"], "生成失败")
    return result


def analyze_students_flexible(df, classification: dict) -> dict:
    """基于动态列的学情分析（保留兼容）"""
    from utils.excel_parser import df_to_flexible_profiles
    profiles = df_to_flexible_profiles(df, classification)
    profiles.sort(key=lambda p: p.priority)

    tier_stats = {"S": 0, "A": 0, "B": 0, "C": 0}
    for p in profiles:
        tier_stats[p.tier] += 1

    profile_dicts = [p.to_dict() for p in profiles]

    warnings = _calc_warnings(profiles, classification)

    return {
        "tier_stats": tier_stats,
        "total": len(profiles),
        "students": profile_dicts,
        "classification": classification,
        "warnings": warnings,
    }


def _calc_warnings(profiles: list, classification: dict) -> dict:
    """计算预警数据（旧版兼容）"""
    import pandas as pd
    from datetime import datetime
    warnings = {
        "即将到期未续费": 0,
        "有续费异议": 0,
        "超过14天未沟通": 0,
        "成绩持续下降": 0,
    }
    for p in profiles:
        for key, val in p.raw_data.items():
            if "续费" in str(key) or "续班" in str(key):
                if "未续费" in str(val) or "死磕" in str(val):
                    warnings["即将到期未续费"] += 1
                    break
        for key, val in p.raw_data.items():
            if "异议" in str(key) and pd.notna(val) and str(val).strip():
                warnings["有续费异议"] += 1
                break
        for key, val in p.raw_data.items():
            if "沟通日期" in str(key) or "最新沟通" in str(key):
                try:
                    if isinstance(val, pd.Timestamp):
                        days = (datetime.now() - val.to_pydatetime()).days
                    elif isinstance(val, datetime):
                        days = (datetime.now() - val).days
                    elif pd.notna(val):
                        days = int(val)
                    else:
                        days = 0
                    if days > 14:
                        warnings["超过14天未沟通"] += 1
                except Exception:
                    pass
                break
    return warnings


def analyze_and_generate_scripts_flexible(df, classification: dict, generate: bool = True, progress_callback=None) -> dict:
    """动态列分析 + 话术生成（保留兼容）"""
    result = analyze_students_flexible(df, classification)
    if generate:
        from core.script_generator import batch_generate_scripts_flexible
        scripts = batch_generate_scripts_flexible(
            result["students"],
            classification,
            progress_callback=progress_callback
        )
        script_map = {s["学生姓名"]: s["生成话术"] for s in scripts}
        for student in result["students"]:
            student["沟通话术"] = script_map.get(student["学生姓名"], "生成失败")
    return result