"""讲次数据解析器 — 智能识别课程结构、未上课讲次、待完成任务"""
import re
import pandas as pd


def parse_lecture_columns(columns: list) -> list:
    """
    从列名中解析出讲次结构
    列名格式: "第3讲 第三讲 Tech Everywhere... 是否到课"
    策略: 从后往前匹配已知子字段，剩余部分就是讲次标识
    """
    lectures = []
    seen_lectures = {}
    
    sub_fields = ["伴学关系", "是否有效听课", "是否到课", "是否到课完课",
                  "听课时长", "听课进度", "看直播时长", "看回放时长", "看伴学时长",
                  "直播答题正确率", "直播答题", "练习状态", "练习得分"]
    
    for i, col in enumerate(columns):
        col_str = str(col)
        
        # 从后往前匹配子字段
        matched_field = None
        field_pos = -1
        for field in sub_fields:
            if col_str.endswith(field):
                matched_field = field
                field_pos = len(col_str) - len(field)
                break
        
        if matched_field is None:
            continue
        
        # 讲次前缀部分
        prefix = col_str[:field_pos].rstrip()
        
        # 提取讲次编号: "第3讲" or "习题课"
        m = re.match(r'^(第\d+讲|习题课)', prefix)
        if not m:
            continue
        
        lecture_num = m.group(1)
        lecture_title = prefix[len(lecture_num):].strip()
        
        # 讲次唯一标识
        lecture_key = lecture_num
        
        if lecture_key not in seen_lectures:
            seen_lectures[lecture_key] = len(lectures)
            lectures.append({
                "lecture": lecture_num,
                "title": lecture_title,
                "cols": {}
            })
        
        lectures[seen_lectures[lecture_key]]["cols"][matched_field] = col
    
    return lectures


def calc_lecture_attendance_rate(df: pd.DataFrame, lectures: list) -> dict:
    """
    计算每讲的全班有效听课率（以是否有效听课为准，不看是否到课）
    Returns: {"第1讲": 0.95, "第2讲": 0.0, ...}
    """
    rates = {}
    for lec in lectures:
        # 优先用"是否有效听课"判断课程是否已上
        effective_col = lec["cols"].get("是否有效听课")
        attend_col = lec["cols"].get("是否到课")
        
        if effective_col and effective_col in df.columns:
            total = len(df)
            # 有效听课=是，说明课已上且学生有效听了
            effective = df[effective_col].apply(lambda x: str(x).strip() in ["是", "1", "True", "true", "有效"]).sum()
            rates[lec["lecture"]] = effective / total if total > 0 else 0
        elif attend_col and attend_col in df.columns:
            # 退而求其次用到课率
            total = len(df)
            attended = df[attend_col].apply(lambda x: str(x).strip() in ["到课", "是", "1", "已到", "True", "true"]).sum()
            rates[lec["lecture"]] = attended / total if total > 0 else 0
        else:
            rates[lec["lecture"]] = 0
    return rates


def is_lecture_active(attendance_rate: float, threshold: float = 0.1) -> bool:
    """判断某讲是否已开课（有效听课率>10%说明课已上）"""
    return attendance_rate >= threshold


def analyze_student_lectures(row_data: dict, lectures: list, attendance_rates: dict) -> dict:
    """
    分析单个学生的讲次数据（以是否有效听课为核心指标）
    Returns: {
        "attended": ["第1讲", "第3讲", ...],  # 有效听课
        "missed": ["第2讲", ...],               # 课已上但未有效听课
        "not_started": ["第9讲", ...],           # 课还没上（全班都没上）
        "ineffective": ["第5讲", ...],           # 无效听课（到课但无效）
        "tasks": ["需补第2讲回放", "需完成第5讲练习", ...],
        "summary": {}
    }
    """
    attended = []
    missed = []
    not_started = []
    ineffective = []
    tasks = []
    
    total_effective = 0
    total_lectures_active = 0
    
    for lec in lectures:
        lec_name = lec["lecture"]
        lec_title = lec["title"]
        rate = attendance_rates.get(lec_name, 0)
        
        # 判断该讲是否已开课
        if not is_lecture_active(rate):
            not_started.append(lec_name)
            continue
        
        total_lectures_active += 1
        
        # 核心指标：是否有效听课
        effective_col = lec["cols"].get("是否有效听课")
        effective_val = str(row_data.get(effective_col, "")).strip() if effective_col else ""
        
        attend_col = lec["cols"].get("是否到课")
        attend_val = str(row_data.get(attend_col, "")).strip() if attend_col else ""
        
        if effective_val in ["是", "1", "True", "true", "有效"]:
            # 有效听课
            attended.append(lec_name)
            total_effective += 1
        elif attend_val in ["到课", "是", "1", "已到", "True", "true"]:
            # 到课了但无效听课
            ineffective.append(lec_name)
            tasks.append(f"需补{lec_name}《{lec_title}》回放（听课无效）")
        else:
            # 未到课
            missed.append(lec_name)
            tasks.append(f"需补{lec_name}《{lec_title}》回放")
        
        # 检查练习状态
        practice_col = lec["cols"].get("练习状态")
        practice_val = str(row_data.get(practice_col, "")).strip() if practice_col else ""
        if practice_val in ["未提交", "未完成", "0", ""]:
            # 检查该讲练习是否大部分人没做
            tasks.append(f"需完成{lec_name}《{lec_title}》练习")
        
        # 检查练习得分
        score_col = lec["cols"].get("练习得分")
        score_val = row_data.get(score_col)
        if pd.notna(score_val) and str(score_val).strip():
            try:
                score_num = float(str(score_val).strip())
                if score_num < 60:
                    tasks.append(f"需订正{lec_name}《{lec_title}》练习（得分{score_num:.0f}）")
            except:
                pass
    
    # 汇总统计
    effective_rate = total_effective / total_lectures_active * 100 if total_lectures_active > 0 else 0
    
    summary = {
        "总讲次": len(lectures),
        "已开讲": total_lectures_active,
        "有效听课": total_effective,
        "有效听课率": f"{effective_rate:.0f}%",
        "无效听课": len(ineffective),
        "缺课数": len(missed),
        "未开讲": len(not_started),
    }
    
    return {
        "attended": attended,
        "missed": missed,
        "not_started": not_started,
        "ineffective": ineffective,
        "tasks": tasks,
        "summary": summary,
    }


def build_lecture_context(student_analysis: dict, lectures: list) -> str:
    """将讲次分析结果组织成文本，传给LLM"""
    lines = []
    
    s = student_analysis["summary"]
    lines.append(f"【听课概况】共{s['总讲次']}讲，已开{s['已开讲']}讲，有效听课{s['有效听课']}讲（有效率{s['有效听课率']}），无效听课{s['无效听课']}讲，缺课{s['缺课数']}讲，未开讲{s['未开讲']}讲")
    
    if student_analysis["attended"]:
        lines.append(f"【有效听课讲次】{', '.join(student_analysis['attended'])}")
    
    if student_analysis["ineffective"]:
        lines.append(f"【无效听课】{', '.join(student_analysis['ineffective'])}（到课但听课无效，需补回放）")
    
    if student_analysis["missed"]:
        lines.append(f"【缺课讲次】{', '.join(student_analysis['missed'])}")
    
    if student_analysis["not_started"]:
        lines.append(f"【未开讲】{', '.join(student_analysis['not_started'])}（课程尚未安排，非学生问题）")
    
    if student_analysis["tasks"]:
        lines.append(f"【待完成任务】")
        for task in student_analysis["tasks"]:
            lines.append(f"  - {task}")
    
    return "\n".join(lines)
