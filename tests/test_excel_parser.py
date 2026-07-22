import pytest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.excel_parser import StudentProfile, parse_student_excel, df_to_profiles


def test_s_tier_student_has_high_risk():
    """S级学生应该有高流失风险分"""
    profile = StudentProfile(
        name="测试S", grade="初二", class_name="A班",
        recent_score=45, score_trend="下降", participation="消极",
        homework_rate=0.3, last_contact_days=20, renewal_days_left=10,
        renewal_history=0, parent_attitude="消极"
    )
    assert profile.tier == "S"
    assert profile.risk_score >= 75


def test_c_tier_student_has_low_risk():
    """C级学生应该有低流失风险分"""
    profile = StudentProfile(
        name="测试C", grade="初二", class_name="A班",
        recent_score=95, score_trend="上升", participation="积极",
        homework_rate=1.0, last_contact_days=2, renewal_days_left=120,
        renewal_history=5, parent_attitude="积极"
    )
    assert profile.tier == "C"
    assert profile.risk_score < 25


def test_priority_sorting():
    """S级且续费即将到期的学生优先级最高"""
    s_urgent = StudentProfile("S紧急", "初二", "A班", 50, "下降", "消极",
                               0.4, 20, 5, 0, "消极")
    a_normal = StudentProfile("A普通", "初二", "A班", 70, "平稳", "一般",
                               0.7, 10, 45, 1, "中性")
    assert s_urgent.priority < a_normal.priority


def test_parse_sample_excel():
    """测试解析示例Excel文件"""
    sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_students.xlsx")
    if not os.path.exists(sample_path):
        pytest.skip("示例数据文件尚未生成")
    df = parse_student_excel(sample_path)
    assert len(df) > 0
    assert "学生姓名" in df.columns


def test_student_profile_to_dict():
    """测试学生画像转字典"""
    profile = StudentProfile(
        name="张三", grade="初二", class_name="数学A班",
        recent_score=85, score_trend="上升", participation="积极",
        homework_rate=0.95, last_contact_days=3, renewal_days_left=30,
        renewal_history=2, parent_attitude="积极"
    )
    d = profile.to_dict()
    assert d["学生姓名"] == "张三"
    assert d["分层"] in ["S", "A", "B", "C"]
    assert "流失风险分" in d


def test_df_to_profiles():
    """测试DataFrame转Profile列表"""
    import pandas as pd
    df = pd.DataFrame([
        {
            "学生姓名": "测试1", "年级": "初二", "班级": "A班",
            "最近成绩": 90, "成绩趋势": "上升", "课堂参与度": "积极",
            "作业完成率": 0.95, "距上次沟通(天)": 2, "续费剩余(天)": 100,
            "历史续费次数": 4, "家长态度": "积极"
        },
        {
            "学生姓名": "测试2", "年级": "初三", "班级": "B班",
            "最近成绩": 50, "成绩趋势": "下降", "课堂参与度": "消极",
            "作业完成率": 0.4, "距上次沟通(天)": 20, "续费剩余(天)": 8,
            "历史续费次数": 0, "家长态度": "消极"
        },
    ])
    profiles = df_to_profiles(df)
    assert len(profiles) == 2
    assert profiles[0].tier != profiles[1].tier