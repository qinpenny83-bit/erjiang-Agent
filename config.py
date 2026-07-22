import os
from dotenv import load_dotenv

load_dotenv()

# LLM 配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
TEMPERATURE = 0.7
MAX_TOKENS = 2000

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
    "S": "#FF4B4B",  # 红色 - 高危
    "A": "#FFA500",  # 橙色 - 需关注
    "B": "#4CAF50",  # 绿色 - 稳定
    "C": "#2196F3",  # 蓝色 - 低优先
}

TIER_LABELS = {
    "S": "S级 - 高危流失",
    "A": "A级 - 需关注",
    "B": "B级 - 稳定",
    "C": "C级 - 低优先",
}