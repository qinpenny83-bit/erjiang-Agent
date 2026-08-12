"""列智能分类器 — 自动识别Excel列的语义类别"""
import re
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class ColumnCategory:
    """列类别定义"""
    name: str
    keywords: list[str]
    description: str = ""
    columns: list[str] = field(default_factory=list)


COLUMN_CATEGORIES = [
    ColumnCategory(
        name="身份信息",
        keywords=["ID", "id", "姓名", "名字", "学生", "电话", "手机", "联系方式", "班级", "年级"],
        description="学生基本身份信息"
    ),
    ColumnCategory(
        name="成绩信息",
        keywords=["成绩", "分数", "考试", "期末", "期中", "得分"],
        description="学生考试成绩相关数据"
    ),
    ColumnCategory(
        name="沟通记录",
        keywords=["沟通", "学情", "记录", "备注", "服务", "反馈", "交流"],
        description="与家长的沟通记录"
    ),
    ColumnCategory(
        name="续费相关",
        keywords=["续费", "续班", "订金", "预报", "异议", "分层"],
        description="续费状态和意向相关"
    ),
    ColumnCategory(
        name="学情特征",
        keywords=["薄弱", "参与度", "作业", "打卡", "时间", "紧张", "住校"],
        description="学生学习状态特征"
    ),
    ColumnCategory(
        name="家长画像",
        keywords=["家长", "父母", "付费", "理念", "陪伴", "支付", "态度"],
        description="家长相关信息"
    ),
]


def classify_columns(df: pd.DataFrame) -> dict:
    """
    对DataFrame的所有列进行分类

    Returns:
        {
            "身份信息": ["姓名", "电话", "ID"],
            "成绩信息": ["五下期末成绩", "期中成绩"],
            "沟通记录": ["学情沟通"],
            "续费相关": ["6.25续班寒春分层", "Q2订金"],
            "学情特征": ["薄弱点", "时间是否紧张"],
            "家长画像": ["父母理念", "付费人", "支付能力"],
            "未分类": ["教材版本", "周五/周四班"]
        }
    """
    result = {cat.name: [] for cat in COLUMN_CATEGORIES}
    result["未分类"] = []

    for col in df.columns:
        classified = False
        col_str = str(col)

        for cat in COLUMN_CATEGORIES:
            for keyword in cat.keywords:
                if keyword in col_str:
                    result[cat.name].append(col)
                    classified = True
                    break
            if classified:
                break

        if not classified:
            result["未分类"].append(col)

    return result


def get_column_mapping_summary(classification: dict) -> str:
    """生成分类摘要文本"""
    lines = []
    for cat_name, columns in classification.items():
        if columns:
            lines.append(f"✅ {cat_name}：{', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
    return "\n".join(lines)


def extract_score_from_text(text: str) -> Optional[float]:
    """从文本中提取成绩数值"""
    if pd.isna(text):
        return None
    text = str(text)

    match = re.search(r'〖(\d+(?:\.\d+)?)〗', text)
    if match:
        return float(match.group(1))

    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        return float(match.group(1))

    return None


def extract_grade_from_text(text: str) -> Optional[str]:
    """从文本中提取成绩等级"""
    if pd.isna(text):
        return None
    text = str(text)

    match = re.search(r'〖([A-D][+-]?)〗', text)
    if match:
        return match.group(1)

    return None


def parse_communication_records(text: str) -> list[dict]:
    """
    解析沟通记录文本，按日期拆分

    Returns:
        [{"date": "2026-03-11", "content": "..."}, ...]
    """
    if pd.isna(text) or not text:
        return []

    records = []
    pattern = r'(\d{1,2}\.\d{1,2}|\d{4}-\d{2}-\d{2})'

    parts = re.split(pattern, str(text))
    dates = re.findall(pattern, str(text))

    for i, date_str in enumerate(dates):
        content_index = i * 2 + 2
        if content_index < len(parts):
            content = parts[content_index].strip()
            if "." in date_str:
                month_day = date_str.split(".")
                date_normalized = f"2026-{month_day[0].zfill(2)}-{month_day[1].zfill(2)}"
            else:
                date_normalized = date_str

            records.append({
                "date": date_normalized,
                "content": content[:200]
            })

    return records
