"""续费风险引擎 — 4维度风险评分 + 成绩下滑检测 + 升降级 + 回访计划"""
import re
import sys
import os
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd


# ============================================================
# 列智能分类
# ============================================================

COLUMN_CATEGORIES = [
    {"name": "身份信息", "keywords": ["ID", "id", "姓名", "名字", "学生", "电话", "手机", "联系方式", "班级", "年级"]},
    {"name": "成绩信息", "keywords": ["成绩", "考试", "期末", "期中", "月考", "测验", "五下", "五上", "六下", "六上", "四下", "四上"]},
    {"name": "沟通记录", "keywords": ["沟通", "学情", "记录", "备注", "服务", "反馈", "交流"]},
    {"name": "续费相关", "keywords": ["续费", "续班", "订金", "预报", "异议", "分层"]},
    {"name": "学情特征", "keywords": ["薄弱", "参与度", "作业", "打卡", "时间", "紧张", "住校", "练习", "听课", "到课", "完课", "答题", "伴学"]},
    {"name": "家长画像", "keywords": ["家长", "父母", "付费", "理念", "陪伴", "支付", "态度"]},
]

# 成绩信息排除关键词（含这些词的列不作为考试成绩）
SCORE_EXCLUDE_KEYWORDS = ["练习", "听课", "答题", "到课", "完课", "伴学", "时长", "进度", "正确率", "状态", "关系", "ID", "年龄", "学号", "班", "排名", "名次", "次数", "天数", "登记", "编号", "序号", "号码"]


def classify_columns(columns: list) -> dict:
    """对列名列表进行语义分类"""
    result = {cat["name"]: [] for cat in COLUMN_CATEGORIES}
    result["未分类"] = []
    for col in columns:
        classified = False
        for cat in COLUMN_CATEGORIES:
            for kw in cat["keywords"]:
                if kw in str(col):
                    # 成绩信息需要排除非考试成绩列（练习得分、听课进度等）
                    if cat["name"] == "成绩信息":
                        if any(ex in str(col) for ex in SCORE_EXCLUDE_KEYWORDS):
                            classified = False
                            continue
                    result[cat["name"]].append(col)
                    classified = True
                    break
            if classified:
                break
        if not classified:
            result["未分类"].append(col)
    return result


def get_mapping_summary(classification: dict) -> str:
    lines = []
    for cat, cols in classification.items():
        if cols:
            lines.append(f"✅ {cat}：{', '.join(cols[:5])}{'...' if len(cols) > 5 else ''}")
    return "\n".join(lines)


# ============================================================
# 成绩提取与趋势分析
# ============================================================

def extract_score(text) -> Optional[float]:
    """从文本中提取成绩数值（严格模式，避免误提取学号等）
    优先提取〖数字〗格式（成绩标记），纯数字仅在0-100范围内识别"""
    if pd.isna(text):
        return None
    text = str(text).strip()
    # 优先提取〖数字〗或〖数字分〗格式（这是明确的成绩标记）
    m = re.search(r'〖(\d+(?:\.\d+)?)\s*分?〗', text)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 150:  # 合理成绩范围
            return val
    # 纯数字单元格（不含其他任何文字），且在合理成绩范围
    if re.match(r'^\d+(?:\.\d+)?$', text):
        val = float(text)
        # 成绩范围严格限制在0-100（避免把年龄、学号等误识别）
        if 0 <= val <= 100:
            return val
    return None


def calc_score_trend(score_cols: list, row_data: dict) -> tuple:
    """
    分析成绩趋势（严格判定，减少误判）
    Returns: (trend_score, trend_label, is_declining)
    """
    scores = []
    for col in score_cols:
        val = row_data.get(col)
        # 排除"未布置""未考""缺考"等无效成绩
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if any(kw in val_str for kw in ["未布置", "未考", "缺考", "免考", "请假", "未参加"]):
            continue
        s = extract_score(val)
        if s is not None and s > 0:  # 0分不算（可能是未考）
            scores.append(s)

    if len(scores) < 3:  # 至少3次有效成绩才判断趋势
        return 0, "数据不足", False
    
    # 计算整体趋势：最后成绩 vs 最初成绩
    start_avg = sum(scores[:len(scores)//2]) / (len(scores)//2)
    end_avg = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
    
    decline_pct = (start_avg - end_avg) / start_avg if start_avg > 0 else 0
    
    # 连续下降次数
    consecutive_declines = 0
    max_consecutive = 0
    for i in range(1, len(scores)):
        if scores[i] < scores[i-1]:
            consecutive_declines += 1
            max_consecutive = max(max_consecutive, consecutive_declines)
        else:
            consecutive_declines = 0
    
    # 严格判定：需要整体下降幅度>10% 且 至少2次连续下降
    if decline_pct > 0.10 and max_consecutive >= 2:
        return 25, "持续下降", True
    elif decline_pct > 0.05 and max_consecutive >= 2:
        return 15, "有下降", True
    elif decline_pct > 0.10:
        return 10, "波动下降", True
    elif decline_pct > 0:
        return 5, "轻微波动", False
    else:
        return 0, "上升/平稳", False


# ============================================================
# 沟通间隔计算
# ============================================================

def calc_contact_days(val) -> int:
    """计算距今天数，支持datetime/timestamp/int"""
    if pd.isna(val):
        return 999
    try:
        if isinstance(val, pd.Timestamp):
            return (datetime.now() - val.to_pydatetime()).days
        elif isinstance(val, datetime):
            return (datetime.now() - val).days
        else:
            return int(val)
    except:
        return 999


# ============================================================
# 家长情绪分析（从沟通记录中提取负面信号）
# ============================================================

NEGATIVE_KEYWORDS = [
    "没效果", "不想学", "太贵了", "不续了", "退费", "转班",
    "效果不好", "不想报", "成绩没提高", "没用", "浪费时间",
    "孩子不愿意", "不想上", "不考虑", "没兴趣",
]


def calc_parent_sentiment(row_data: dict, classification: dict) -> tuple:
    """
    从沟通记录中分析家长情绪
    Returns: (score, matched_keywords)
    score: 0-25
    """
    matched = []
    text_all = ""
    
    # 汇集所有沟通记录列的文本
    for col in classification.get("沟通记录", []):
        val = row_data.get(col)
        if pd.notna(val) and str(val).strip():
            text_all += str(val) + " "
    
    # 也检查异议列
    for col in classification.get("续费相关", []):
        if "异议" in str(col):
            val = row_data.get(col)
            if pd.notna(val) and str(val).strip():
                text_all += str(val) + " "
    
    if not text_all.strip():
        return 0, []
    
    for kw in NEGATIVE_KEYWORDS:
        if kw in text_all:
            matched.append(kw)
    
    if len(matched) >= 3:
        return 25, matched
    elif len(matched) >= 2:
        return 18, matched
    elif len(matched) >= 1:
        return 10, matched
    
    return 0, []


# ============================================================
# 3维度风险评分（9分制，防幻觉）
# ============================================================

# 学期顺序对照表（用于成绩排序）
SEMESTER_ORDER = {
    "四上": 1, "四下": 2, "五上": 3, "五下": 4,
    "六上": 5, "六下": 6, "初一上": 7, "初一下": 8,
    "初二上": 9, "初二下": 10, "初三上": 11, "初三下": 12,
    "高一上": 13, "高一下": 14, "高二上": 15, "高二下": 16,
    "高三上": 17, "高三下": 18,
}

def calc_risk_score(row_data: dict, classification: dict) -> tuple:
    """
    3维度风险评分（满分9分）
    维度1: 成绩情况（最高3分）
    维度2: 平时表现（最高3分）
    维度3: 家校沟通（最高3分）
    Returns: (total_score, details_dict, triggered_dimensions)
    """
    details = {}
    triggered = []

    # ====== 维度1: 成绩情况 (最高3分) ======
    score1 = 0
    evidence1 = []
    score_cols = classification.get("成绩信息", [])
    # 按学期顺序排列成绩（上→下，先考→后考）

    def get_semester_rank(col_name):
        """从列名提取学期顺序（精确到期中/期末，确保时间顺序正确）"""
        col_str = str(col_name)
        for sem, rank in SEMESTER_ORDER.items():
            if sem in col_str:
                # 同一学期内：期中(0.51) < 期末(0.99)，确保时间顺序正确
                if "期中" in col_str:
                    return rank + 0.51
                elif "期末" in col_str:
                    return rank + 0.99
                elif "五下" in col_str and "期末" not in col_str:
                    # 五下默认是期中
                    return rank + 0.51
                return rank + 0.75
        # 按列在原始数据中的顺序
        return 999

    # 收集所有成绩，带学期顺序
    score_entries = []
    final_exam_score = None
    for col in score_cols:
        val = row_data.get(col)
        if pd.isna(val):
            continue
        val_str = str(val).strip()
        if any(kw in val_str for kw in ["未布置", "未考", "缺考", "免考", "请假", "未参加"]):
            continue
        s = extract_score(val)
        if s is not None and s > 0:
            rank = get_semester_rank(col)
            score_entries.append((rank, col, s, val))
            if "期末" in str(col) and "期中" not in str(col):
                final_exam_score = s

    # 按学期顺序排序（从早到晚）
    score_entries.sort(key=lambda x: x[0])
    scores = [e[2] for e in score_entries]
    for _, col, s, val in score_entries:
        evidence1.append(f"{col}={val}")

    if len(scores) >= 2:
        # 按时间顺序：最后一个是最新的，倒数第二个是上一次
        last = scores[-1]
        prev = scores[-2]
        if prev > 0 and (prev - last) / prev >= 0.2:  # 下降20%以上
            score1 = 3
            evidence1.append(f"成绩下滑{prev}→{last}")
        elif last > prev:
            evidence1.append(f"成绩上升{prev}→{last}")
        # 长期后15%且无起色
        if score1 == 0 and len(scores) >= 3:
            avg = sum(scores) / len(scores)
            if avg < 60:  # 平均不及格
                score1 = 2
                evidence1.append(f"平均成绩{avg:.0f}分，长期偏低")
    # 期末成绩单独评估
    if score1 == 0 and final_exam_score is not None:
        if final_exam_score < 60:
            score1 = 2
            evidence1.append(f"期末成绩{final_exam_score}分，不及格")
        elif final_exam_score < 80:
            score1 = 1
            evidence1.append(f"期末成绩{final_exam_score}分，偏低")
        else:
            evidence1.append(f"期末成绩{final_exam_score}分，正常")
    if score1 == 0 and scores and final_exam_score is None:
        evidence1.append(f"成绩正常({scores[-1]}分)")

    details["成绩情况"] = {"score": score1, "evidence": evidence1, "scores": scores, "期末成绩": final_exam_score}
    if score1 > 0:
        triggered.append("成绩问题")

    # ====== 维度2: 平时表现 (最高3分) ======
    score2 = 0
    evidence2 = []
    severe_keywords = ["极度厌学", "拒交作业", "严重违纪", "严重心理", "心理倾向", "自残", "抑郁"]
    mild_keywords = ["上课走神", "走神", "作业偶尔欠交", "欠交", "学习状态不稳定", "不稳定", "注意力不集中", "不专注"]

    # 扫描学情特征和沟通记录中的文本
    scan_cols = classification.get("学情特征", []) + classification.get("沟通记录", [])
    for col in scan_cols:
        val = str(row_data.get(col, "")).strip() if pd.notna(row_data.get(col)) else ""
        if not val:
            continue
        # 严重情况
        for kw in severe_keywords:
            if kw in val:
                score2 = max(score2, 3)
                evidence2.append(f"{col}: 含'{kw}'")
                break
        # 轻微情况（只有当没触发严重时才记）
        if score2 < 3:
            for kw in mild_keywords:
                if kw in val:
                    score2 = max(score2, 1)
                    evidence2.append(f"{col}: 含'{kw}'")
                    break

    # 练习得分趋势分析（作为平时表现的补充证据）
    practice_scores = []
    for col in classification.get("学情特征", []):
        if "练习得分" in str(col):
            val = str(row_data.get(col, "")).strip() if pd.notna(row_data.get(col)) else ""
            if val and val not in ["未布置", "未考", ""]:
                try:
                    s = float(val.replace("分", ""))
                    if s > 0:
                        practice_scores.append(s)
                except (ValueError, AttributeError):
                    pass
    if len(practice_scores) >= 3:
        recent_avg = sum(practice_scores[len(practice_scores)//2:]) / (len(practice_scores) - len(practice_scores)//2)
        if recent_avg < 50:  # 练习平均低于50分
            score2 = max(score2, 1)
            evidence2.append(f"练习得分偏低(均{recent_avg:.0f}分)")

    # 缺课率高
    absent_count = 0
    total_lectures = 0
    for col in classification.get("学情特征", []):
        if "是否到课" in str(col) and "完课" not in str(col):
            total_lectures += 1
            val = str(row_data.get(col, "")).strip() if pd.notna(row_data.get(col)) else ""
            if val == "否":
                absent_count += 1
    if total_lectures > 0:
        absent_rate = absent_count / total_lectures
        if absent_rate >= 0.5:
            score2 = max(score2, 1)
            evidence2.append(f"缺课率{absent_rate:.0%}({absent_count}/{total_lectures}讲)")

    if score2 == 0:
        evidence2.append("平时表现正常")
    details["平时表现"] = {"score": score2, "evidence": evidence2}
    if score2 > 0:
        triggered.append("表现异常")

    # ====== 维度3: 家校沟通 (最高3分) ======
    score3 = 0
    evidence3 = []
    severe_comm_keywords = ["极度不配合", "家长表达放弃", "家长放弃", "严重厌学", "不配合", "放弃"]
    mild_comm_keywords = ["焦虑", "沟通较少", "沟通少", "家长焦虑", "较为焦虑"]

    for col in classification.get("沟通记录", []) + classification.get("家长画像", []):
        val = str(row_data.get(col, "")).strip() if pd.notna(row_data.get(col)) else ""
        if not val:
            continue
        for kw in severe_comm_keywords:
            if kw in val:
                score3 = max(score3, 3)
                evidence3.append(f"{col}: 含'{kw}'")
                break
        if score3 < 3:
            for kw in mild_comm_keywords:
                if kw in val:
                    score3 = max(score3, 1)
                    evidence3.append(f"{col}: 含'{kw}'")
                    break

    # 沟通频率（结合期末成绩综合判断）
    has_communication = False
    contact_col = None
    days = 999
    for col in classification.get("沟通记录", []):
        val = row_data.get(col)
        if pd.notna(val) and str(val).strip():
            has_communication = True
        if "沟通日期" in str(col) or "最新沟通" in str(col):
            days = calc_contact_days(row_data.get(col))
            contact_col = col
            break
    # 综合判断：成绩好(>=80) + 沟通少 = 正常，不扣分
    # 成绩差(<60) + 沟通少 = 高风险，扣分加重
    if not has_communication:
        if final_exam_score is not None and final_exam_score >= 80:
            evidence3.append(f"无沟通记录，但期末{final_exam_score}分成绩好，暂不扣分")
        elif final_exam_score is not None and final_exam_score < 60:
            score3 = max(score3, 2)
            evidence3.append(f"无沟通记录且期末{final_exam_score}分成绩差，风险高")
        else:
            score3 = max(score3, 1)
            evidence3.append("无任何沟通记录")
    elif days > 90:
        if final_exam_score is not None and final_exam_score >= 80:
            evidence3.append(f"超{days}天未沟通，但期末{final_exam_score}分成绩好，暂不扣分")
        elif final_exam_score is not None and final_exam_score < 60:
            score3 = max(score3, 2)
            evidence3.append(f"超{days}天未沟通且期末{final_exam_score}分成绩差，风险高")
        else:
            score3 = max(score3, 1)
            evidence3.append(f"超{days}天未沟通")
    elif days > 60:
        if final_exam_score is not None and final_exam_score < 60:
            score3 = max(score3, 1)
            evidence3.append(f"超{days}天未沟通且期末成绩偏低")

    if score3 == 0:
        evidence3.append("家校沟通正常")
    details["家校沟通"] = {"score": score3, "evidence": evidence3, "days": days}
    if score3 > 0:
        triggered.append("沟通异常")

    total = score1 + score2 + score3
    return total, details, triggered


# ============================================================
# 分层 + 升降级
# ============================================================

def assign_tier(risk_score: float, thresholds: dict = None) -> str:
    """
    9分制分层：
    P1(特别关注): >=5分
    P2(需关注): 3-4分
    P3(相对稳定): 1-2分
    P4(优): 0分
    """
    if thresholds is None:
        thresholds = {"P1": 5, "P2": 3, "P3": 1}
    if risk_score >= thresholds["P1"]:
        return "P1"
    elif risk_score >= thresholds["P2"]:
        return "P2"
    elif risk_score >= thresholds["P3"]:
        return "P3"
    return "P4"


def assign_tier_by_percentile(risk_score: float, all_scores: list, contact_days: int = 999) -> str:
    """
    按风险分分配分层（强制按比例分配，同分用沟通天数作为辅助排序）：
    P1: 前15%（风险最高）
    P2: 前15%~40%
    P3: 前40%~70%
    P4: 后30%（最优）
    """
    return "P4"  # 占位，实际在analyze_students中统一分配


def apply_upgrade(tier: str) -> str:
    """续费窗口期全员上调一级"""
    upgrade_map = {"P4": "P3", "P3": "P2", "P2": "P1", "P1": "P1"}
    return upgrade_map.get(tier, tier)


# ============================================================
# 回访规则
# ============================================================

FOLLOWUP_RULES = {
    "P1": {"frequency": "每周1次", "days": 7},
    "P2": {"frequency": "每3周1次", "days": 21},
    "P3": {"frequency": "日常轻反馈", "days": 0},
    "P4": {"frequency": "低频维系", "days": 30},
}


def calc_next_followup(tier: str, last_contact_days: int) -> dict:
    """计算下次跟进信息"""
    rule = FOLLOWUP_RULES.get(tier, FOLLOWUP_RULES["P4"])
    if rule["days"] == 0:
        return {"frequency": rule["frequency"], "next_date": "日常", "overdue": False}

    next_date = datetime.now() + timedelta(days=rule["days"])
    overdue = last_contact_days > rule["days"]
    return {
        "frequency": rule["frequency"],
        "next_date": next_date.strftime("%Y-%m-%d"),
        "overdue": overdue
    }


# ============================================================
# 沟通记录解析
# ============================================================

def parse_communication_timeline(text: str) -> list:
    """解析沟通记录，返回时间线"""
    if pd.isna(text) or not text:
        return []
    records = []
    pattern = r'(\d{1,2}\.\d{1,2}|\d{4}-\d{2}-\d{2})'
    dates = re.findall(pattern, str(text))
    parts = re.split(pattern, str(text))
    for i, date_str in enumerate(dates):
        idx = i * 2 + 2
        if idx < len(parts):
            content = parts[idx].strip()[:150]
            if "." in date_str:
                md = date_str.split(".")
                date_norm = f"2026-{md[0].zfill(2)}-{md[1].zfill(2)}"
            else:
                date_norm = date_str
            records.append({"date": date_norm, "content": content})
    return records


# ============================================================
# 完整分析流程
# ============================================================

def analyze_uploaded_excel(uploaded_file, thresholds: dict = None) -> dict:
    """
    完整分析流程：解析Excel → 分类列 → 计算风险 → 分层 → 回访计划
    """
    df = pd.read_excel(uploaded_file)
    columns = list(df.columns)
    classification = classify_columns(columns)

    # 智能检测姓名列
    from utils.excel_parser import detect_name_column
    try:
        name_col = detect_name_column(df, classification)
    except ValueError as e:
        raise ValueError(str(e))

    # 查找沟通日期列
    contact_col = None
    for col in classification.get("沟通记录", []):
        if "沟通日期" in str(col) or "最新沟通" in str(col):
            contact_col = col
            break

    # 逐行分析 - 第一步：计算所有学生分数
    students = []
    tier_stats = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    red_flag_count = 0
    all_scores = []

    for _, row in df.iterrows():
        row_data = {col: row[col] for col in columns}
        name = str(row[name_col]) if pd.notna(row[name_col]) else "未知"

        # 风险评分
        risk_score, risk_details, triggered = calc_risk_score(row_data, classification)
        all_scores.append(risk_score)

        # 续费异议检测（从原始数据中扫描续费相关列）
        has_objection = False
        for col in classification.get("续费相关", []):
            val = str(row_data.get(col, "")).strip() if pd.notna(row_data.get(col)) else ""
            if val in ["未续费", "死磕", "甩班强关", "强关", "异议", "不续费"]:
                has_objection = True
                break
            if any(kw in val for kw in ["异议", "不续", "退费", "考虑"]):
                has_objection = True
                break
        if has_objection and "续费异议" not in triggered:
            triggered.append("续费异议")

        # 成绩下滑红标：基于五上→五下实际对比
        is_declining = False
        scores_detail = risk_details.get("成绩情况", {}).get("scores", [])
        evidence = risk_details.get("成绩情况", {}).get("evidence", [])
        # 检查evidence中是否有"成绩下滑"标记（从高到低的真实下降）
        for ev in evidence:
            if "成绩下滑" in str(ev):
                is_declining = True
                break
        if is_declining:
            red_flag_count += 1

        # 沟通间隔
        contact_days = calc_contact_days(row_data.get(contact_col)) if contact_col else 999

        students.append({
            "学生姓名": name,
            "流失风险分": round(risk_score, 1),
            "风险详情": risk_details,
            "触发维度": triggered,
            "成绩下滑红标": is_declining,
            "沟通间隔天数": contact_days,
            "原始数据": row_data,
        })

    # 第二步：按比例分配分层（强制按比例，同分用沟通天数辅排）
    # 排序：风险分从高到低，同分时沟通天数多的排前面
    students.sort(key=lambda x: (-x["流失风险分"], -x["沟通间隔天数"]))
    n = len(students)
    p1_end = round(n * 0.05)
    p2_end = round(n * 0.30)
    p3_end = round(n * 0.70)
    for i, s in enumerate(students):
        if i < p1_end:
            s["分层"] = "P1"
        elif i < p2_end:
            s["分层"] = "P2"
        elif i < p3_end:
            s["分层"] = "P3"
        else:
            s["分层"] = "P4"
        followup = calc_next_followup(s["分层"], s["沟通间隔天数"])
        s["回访频率"] = followup["frequency"]
        s["下次跟进"] = followup["next_date"]
        s["跟进逾期"] = followup["overdue"]
        s["风险问题"] = "、".join(s["触发维度"]) if s["触发维度"] else "无"
        tier_stats[s["分层"]] += 1

    # 按优先级排序（P1→P2→P3→P4，同层按沟通天数降序）
    tier_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    students.sort(key=lambda x: (tier_order.get(x["分层"], 3), -x["沟通间隔天数"]))

    # 预警统计
    warnings = {
        "成绩下滑": sum(1 for s in students if "成绩问题" in s["触发维度"]),
        "续费异议": sum(1 for s in students if "续费异议" in s["触发维度"]),
        "沟通少": sum(1 for s in students if "沟通异常" in s["触发维度"]),
        "家长负面": sum(1 for s in students if "表现异常" in s["触发维度"]),
    }

    return {
        "tier_stats": tier_stats,
        "total": len(students),
        "students": students,
        "classification": classification,
        "warnings": warnings,
        "red_flag_count": red_flag_count,
    }


def generate_weekly_plan(analysis_result: dict) -> list:
    """生成本周回访执行计划（按优先级推荐40人）"""
    students = analysis_result["students"]
    tier_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    
    # 按优先级排序：P1→P2→P3→P4，同层沟通间隔天数降序
    sorted_students = sorted(students, key=lambda x: (tier_order.get(x.get("分层", "P4"), 3), -x.get("沟通间隔天数", 0)))
    
    plan = []
    for s in sorted_students[:40]:
        plan.append({
            "学生姓名": s["学生姓名"],
            "分层": s["分层"],
            "回访频率": s.get("回访频率", ""),
            "风险问题": s.get("风险问题", s.get("触发维度", [])),
            "跟进逾期": s.get("跟进逾期", False),
            "沟通间隔天数": s.get("沟通间隔天数", 999),
        })
    return plan
