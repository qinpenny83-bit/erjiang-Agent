import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def _get_config(key: str, default: str = "") -> str:
    """读取配置，兼容本地 .env 和 Streamlit Cloud st.secrets"""
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


# LLM 配置
OPENAI_API_KEY = _get_config("OPENAI_API_KEY", "")
OPENAI_BASE_URL = _get_config("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = "deepseek-v4-flash"  # 强制锁定 v4-flash，不允许被环境变量覆盖
TEMPERATURE = 0.7
MAX_TOKENS = 4000

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SOP_DIR = os.path.join(DATA_DIR, "sop_knowledge")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")
LOG_DIR = os.path.join(DATA_DIR, "logs")

# 学生分层阈值
RISK_THRESHOLD_S = 75    # 高危流失
RISK_THRESHOLD_A = 50    # 需关注
RISK_THRESHOLD_B = 25    # 稳定
# 低于B为C级（低优先）

# 分层颜色映射（用于UI展示）
TIER_COLORS = {
    "P1": "#FF4B4B",  # 红色 - 高危
    "P2": "#FFA500",  # 橙色 - 中危
    "P3": "#4CAF50",  # 绿色 - 关注
    "P4": "#2196F3",  # 蓝色 - 正常
}

TIER_LABELS = {
    "P1": "P1 - 特别关注",
    "P2": "P2 - 需关注",
    "P3": "P3 - 相对稳定",
    "P4": "P4 - 优",
}

# ====== 风险评分辅助函数 ======
from datetime import datetime

def _calc_contact_risk(val) -> float:
    """计算沟通间隔风险分，支持datetime和整数天数"""
    if pd.isna(val):
        return 0
    try:
        if isinstance(val, pd.Timestamp):
            days = (datetime.now() - val.to_pydatetime()).days
        elif isinstance(val, datetime):
            days = (datetime.now() - val).days
        elif hasattr(val, 'days'):  # timedelta
            days = val.days
        else:
            days = int(val)
        if days > 90:
            return 15
        elif days > 60:
            return 10
        elif days > 30:
            return 5
        return 0
    except Exception:
        return 0


def _calc_rate_risk(val, high_threshold=0.8, low_threshold=0.6) -> float:
    """计算比率类风险分（听课率、提交率等）"""
    if pd.isna(val):
        return 0
    try:
        s = str(val).strip()
        if "%" in s:
            rate = float(s.strip("%")) / 100
        else:
            rate = float(val)
        if rate < low_threshold:
            return 10
        elif rate < high_threshold:
            return 5
        return 0
    except Exception:
        return 0


# ====== 风险评分维度注册表 ======
RISK_DIMENSIONS = [
    {
        "name": "续费状态",
        "match_keywords": ["续费", "续班", "续保", "续报", "分层"],
        "score_func": lambda val: {
            "未续费": 30, "不可续未续": 30, "死磕": 25, "甩班强关": 25, "甩班": 25,
            "一般磕单": 15, "一般关单": 15, "强关": 20, "自然续费": 0
        }.get(str(val).strip() if pd.notna(val) else "", 0),
        "weight": 30
    },
    {
        "name": "订金状态",
        "match_keywords": ["订金", "预报", "预报名", "报名"],
        "score_func": lambda val: 15 if str(val).strip() in ["未预报", "未参与", "未报名"] else 0,
        "weight": 15
    },
    {
        "name": "续费异议",
        "match_keywords": ["异议", "疑义", "顾虑", "担忧"],
        "score_func": lambda val: 15 if pd.notna(val) and str(val).strip() and str(val).strip() != "-" else 0,
        "weight": 15
    },
    {
        "name": "沟通间隔",
        "match_keywords": ["沟通日期", "最新沟通", "沟通间隔", "最近看课", "最近沟通", "上次沟通", "最后联系", "看课时间"],
        "score_func": lambda val: _calc_contact_risk(val),
        "weight": 15
    },
    {
        "name": "成绩趋势",
        "match_keywords": ["成绩", "分数", "下滑", "红标", "下降", "退步", "进步", "提升"],
        "score_func": lambda val: 15 if (pd.notna(val) and (str(val).strip() in ["下降", "下滑", "True", "true", "是", "退步", "红标"] or "下滑" in str(val).strip())) else 0,
        "weight": 15
    },
    {
        "name": "有效听课率",
        "match_keywords": ["有效听课", "听课率", "到课率", "出勤", "听课"],
        "score_func": lambda val: _calc_rate_risk(val, 0.8, 0.6),
        "weight": 10
    },
    {
        "name": "练习提交率",
        "match_keywords": ["练习提交", "提交率", "作业完成", "作业率", "作业提交"],
        "score_func": lambda val: _calc_rate_risk(val, 0.8, 0.6),
        "weight": 10
    },
    {
        "name": "时间紧张",
        "match_keywords": ["时间是否紧张", "时间紧张", "时间紧迫", "紧迫"],
        "score_func": lambda val: 5 if str(val).strip() == "是" else 0,
        "weight": 5
    },
    {
        "name": "支付能力",
        "match_keywords": ["支付能力", "支付", "经济", "消费能力"],
        "score_func": lambda val: {"差": 5, "一般": 3, "好": 0}.get(str(val).strip() if pd.notna(val) else "", 0),
        "weight": 5
    },
]