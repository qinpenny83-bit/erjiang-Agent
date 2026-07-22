import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
import sys
import os

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_THRESHOLD_S, RISK_THRESHOLD_A, RISK_THRESHOLD_B


@dataclass
class StudentProfile:
    """学生画像数据类"""
    name: str
    grade: str
    class_name: str
    recent_score: float
    score_trend: str          # 上升/平稳/下降
    participation: str        # 积极/一般/消极
    homework_rate: float      # 0.0-1.0
    last_contact_days: int    # 距上次沟通天数
    renewal_days_left: int    # 续费剩余天数
    renewal_history: int      # 历史续费次数
    parent_attitude: str      # 积极/中性/消极
    exam_rank: Optional[str] = None
    notes: Optional[str] = None

    # 自动计算字段
    risk_score: float = field(init=False)
    tier: str = field(init=False)
    priority: int = field(init=False)

    def __post_init__(self):
        self.risk_score = self._calc_risk_score()
        self.tier = self._calc_tier()
        self.priority = self._calc_priority()

    def _calc_risk_score(self) -> float:
        """计算流失风险分（0-100）"""
        score = 0.0

        # 成绩趋势（权重25%）
        trend_map = {"下降": 25, "平稳": 10, "上升": 0}
        score += trend_map.get(self.score_trend, 10)

        # 课堂参与度（权重20%）
        part_map = {"消极": 20, "一般": 10, "积极": 0}
        score += part_map.get(self.participation, 10)

        # 作业完成率（权重20%）
        score += (1 - self.homework_rate) * 20

        # 续费紧迫度（权重20%）— 30天内到期加满分
        if self.renewal_days_left <= 30:
            score += 20
        elif self.renewal_days_left <= 60:
            score += 10

        # 沟通间隔（权重15%）— 超过14天未沟通加分
        if self.last_contact_days > 14:
            score += 15
        elif self.last_contact_days > 7:
            score += 8

        return min(score, 100)

    def _calc_tier(self) -> str:
        """学生分层"""
        if self.risk_score >= RISK_THRESHOLD_S:
            return "S"
        elif self.risk_score >= RISK_THRESHOLD_A:
            return "A"
        elif self.risk_score >= RISK_THRESHOLD_B:
            return "B"
        return "C"

    def _calc_priority(self) -> int:
        """优先级排序值（数值越小优先级越高）"""
        tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        return tier_order[self.tier] * 1000 + self.renewal_days_left

    def to_dict(self) -> dict:
        return {
            "学生姓名": self.name,
            "年级": self.grade,
            "班级": self.class_name,
            "最近成绩": self.recent_score,
            "成绩趋势": self.score_trend,
            "课堂参与度": self.participation,
            "作业完成率": f"{self.homework_rate:.0%}",
            "距上次沟通(天)": self.last_contact_days,
            "续费剩余(天)": self.renewal_days_left,
            "历史续费次数": self.renewal_history,
            "家长态度": self.parent_attitude,
            "流失风险分": round(self.risk_score, 1),
            "分层": self.tier,
            "优先级": self.priority,
        }


def parse_student_excel(file_path: str) -> pd.DataFrame:
    """解析学情Excel文件"""
    df = pd.read_excel(file_path)
    required_cols = [
        "学生姓名", "年级", "班级", "最近成绩", "成绩趋势",
        "课堂参与度", "作业完成率", "距上次沟通(天)",
        "续费剩余(天)", "历史续费次数", "家长态度"
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel缺少必要列: {missing}")
    return df


def parse_uploaded_excel(uploaded_file) -> pd.DataFrame:
    """解析Streamlit上传的Excel文件"""
    df = pd.read_excel(uploaded_file)
    required_cols = [
        "学生姓名", "年级", "班级", "最近成绩", "成绩趋势",
        "课堂参与度", "作业完成率", "距上次沟通(天)",
        "续费剩余(天)", "历史续费次数", "家长态度"
    ]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Excel缺少必要列: {missing}")
    return df


def df_to_profiles(df: pd.DataFrame) -> list[StudentProfile]:
    """将DataFrame转换为StudentProfile列表"""
    profiles = []
    for _, row in df.iterrows():
        hw_rate = row["作业完成率"]
        if isinstance(hw_rate, str):
            hw_rate = float(hw_rate.strip("%")) / 100
        profile = StudentProfile(
            name=str(row["学生姓名"]),
            grade=str(row["年级"]),
            class_name=str(row["班级"]),
            recent_score=float(row["最近成绩"]),
            score_trend=str(row["成绩趋势"]),
            participation=str(row["课堂参与度"]),
            homework_rate=float(hw_rate),
            last_contact_days=int(row["距上次沟通(天)"]),
            renewal_days_left=int(row["续费剩余(天)"]),
            renewal_history=int(row["历史续费次数"]),
            parent_attitude=str(row["家长态度"]),
        )
        profiles.append(profile)
    return profiles
