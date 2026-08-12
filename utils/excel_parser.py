import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
import sys
import os
import re

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import RISK_THRESHOLD_S, RISK_THRESHOLD_A, RISK_THRESHOLD_B


# =====================================================================
# 成绩列时间排序工具
# =====================================================================

# 年级数字映射
_GRADE_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9,
    "初": 7,  # 初一=7
}
# 学期映射（上=1, 下=2）
_SEMESTER_MAP = {"上": 1, "下": 2, "春": 1, "秋": 2}
# 考试类型映射（期中<期末<月考<单元）
_EXAM_TYPE_MAP = {"单元": 0, "月考": 1, "期中": 2, "期末": 3, "阶段": 1, "模拟": 2}


def _parse_score_column_time(col_name: str) -> tuple:
    """
    从成绩列名中提取时间排序键，返回 (年级数, 学期, 考试类型, 原始列名)
    值越大表示越晚。
    例如："五下期末" → (5, 2, 3, "五下期末")
          "四上期中" → (4, 1, 2, "四上期中")
    """
    col = str(col_name).strip()
    # 提取年级数字
    grade_num = 0
    for ch, num in _GRADE_NUM.items():
        if ch in col:
            grade_num = num
            break
    # 如果没找到中文数字，尝试阿拉伯数字（限1-12，避免年份如2025被误判为年级）
    if grade_num == 0:
        m = re.search(r'(?<!\d)(\d{1,2})(?!\d)', col)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 12:
                grade_num = num
    # 提取学期
    semester = 0
    for kw, val in _SEMESTER_MAP.items():
        if kw in col:
            semester = val
            break
    # 提取考试类型
    exam_type = 0
    for kw, val in _EXAM_TYPE_MAP.items():
        if kw in col:
            exam_type = max(exam_type, val)
    return (grade_num, semester, exam_type, col)


def _get_latest_score(row, score_cols: list) -> Optional[float]:
    """
    从多个成绩列中按时间排序，取最新一次有效成绩。
    支持纯数字和〖score〗文本格式。
    如果所有列都无法排序（无时间信息），取最后一个有效值。
    """
    if not score_cols:
        return None
    # 收集所有有效成绩：(排序键, 数值)
    scored = []
    for col in score_cols:
        v = _normalize_numeric(row.get(col))
        if v is None:
            # 尝试从文本中提取 〖score〗 格式
            text_val = _normalize_text(row.get(col))
            if text_val:
                m = re.search(r'〖(\d+(?:\.\d+)?)〗', text_val)
                if m:
                    v = float(m.group(1))
        if v is not None:
            sort_key = _parse_score_column_time(col)
            scored.append((sort_key, v))
    if not scored:
        return None
    # 按时间排序，取最新（最大排序键）
    scored.sort(key=lambda x: x[0])
    return scored[-1][1]


# =====================================================================
# 统一学生画像（新架构 — 阶段二）
# =====================================================================

@dataclass
class LearningRisk:
    """学习风险子结构"""
    score_level: Optional[float] = None       # 最近成绩（数值）
    score_trend: Optional[str] = None         # 成绩趋势（上升/平稳/下降）
    performance: Optional[str] = None         # 学习表现（积极/一般/消极）
    homework_rate: Optional[float] = None     # 作业/练习完成率（0-1）
    attendance_rate: Optional[float] = None   # 听课/出勤率（0-1）
    raw_columns: dict = field(default_factory=dict)  # {原始列名: 原始值}


@dataclass
class ParentRisk:
    """家长风险子结构"""
    attitude: Optional[str] = None            # 家长态度
    communication: Optional[str] = None       # 沟通记录（文本摘要）
    concern: Optional[str] = None             # 核心诉求/异议
    signals: list = field(default_factory=list)  # [{signal, label, matched, source_col}]
    raw_columns: dict = field(default_factory=dict)


@dataclass
class ServiceRisk:
    """服务风险子结构"""
    renewal_intention: Optional[str] = None   # 续费意愿（已续费/未续费/自然续费/...）
    renewal_days: Optional[int] = None        # 续费剩余天数
    last_contact_days: Optional[int] = None   # 最近沟通间隔天数
    raw_columns: dict = field(default_factory=dict)


@dataclass
class UnifiedStudentProfile:
    """统一学生画像 — 字段语义理解后的标准化结构"""
    name: str
    grade: Optional[str] = None
    class_name: Optional[str] = None

    learning: LearningRisk = field(default_factory=LearningRisk)
    parent: ParentRisk = field(default_factory=ParentRisk)
    service: ServiceRisk = field(default_factory=ServiceRisk)

    raw_data: dict = field(default_factory=dict)       # 原始行数据
    recognition: dict = field(default_factory=dict)    # recognize_columns() 结果
    missing_dimensions: list = field(default_factory=list)  # 缺失的业务维度

    def to_dict(self) -> dict:
        """转为字典（供话术生成使用）"""
        return {
            "学生姓名": self.name,
            "年级": self.grade or "未知",
            "班级": self.class_name or "未知",
            # 学习
            "最近成绩": self.learning.score_level,
            "成绩趋势": self.learning.score_trend,
            "学习表现": self.learning.performance,
            "作业完成率": f"{self.learning.homework_rate:.0%}" if self.learning.homework_rate is not None else None,
            "听课率": f"{self.learning.attendance_rate:.0%}" if self.learning.attendance_rate is not None else None,
            # 家长
            "家长态度": self.parent.attitude,
            "家长沟通": self.parent.communication,
            "家长诉求": self.parent.concern,
            "家长信号": [s["label"] for s in self.parent.signals],
            # 服务
            "续费意愿": self.service.renewal_intention,
            "续费剩余天数": self.service.renewal_days,
            "沟通间隔天数": self.service.last_contact_days,
            # 元数据
            "缺失维度": self.missing_dimensions,
            "原始数据": self.raw_data,
        }


def _normalize_numeric(val) -> Optional[float]:
    """将值标准化为浮点数"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        s = str(val).strip()
        if "%" in s:
            return float(s.strip("%")) / 100
        return float(s.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _normalize_text(val) -> Optional[str]:
    """将值标准化为文本"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("nan", "none", "-", "") else None


def build_unified_profiles(df: pd.DataFrame) -> list[UnifiedStudentProfile]:
    """
    基于语义识别结果，将DataFrame转换为统一学生画像列表

    流程：
    1. 调用 recognize_columns() 理解每列业务含义
    2. 遍历每行，按维度提取和标准化值
    3. 检测文本列中的业务信号
    4. 构建 UnifiedStudentProfile

    Args:
        df: 原始数据DataFrame

    Returns:
        list[UnifiedStudentProfile]
    """
    from core.semantic_column_recognizer import (
        recognize_columns, get_dimension_columns, get_dimension_value,
        _analyze_text_content, BUSINESS_DIMENSIONS
    )

    recognition = recognize_columns(df)
    profiles = []

    # === 预计算：维度→列名映射（避免逐行重复查找）===
    ALL_DIM_KEYS = [
        "student_name", "grade", "class_name",
        "score_level", "score_trend", "performance", "homework_rate", "attendance_rate",
        "parent_attitude", "parent_communication", "parent_concern",
        "renewal_intention", "renewal_days", "last_contact_days",
    ]
    dim_cols = {dim: get_dimension_columns(recognition, dim) for dim in ALL_DIM_KEYS}

    # === 预计算：维度标签映射（用于缺失维度标注）===
    dim_label_map = {d["dimension"]: d["label"] for d in BUSINESS_DIMENSIONS}

    for _, row in df.iterrows():
        raw_data = {str(col): row[col] for col in df.columns}

        # --- 学生基础信息 ---
        name_cols = dim_cols["student_name"]
        name = "未知"
        all_col_names = {str(c) for c in df.columns}
        for nc in name_cols:
            v = _normalize_text(row.get(nc))
            # 跳过等于列名本身的值（防止表头行被当作数据）
            if v and v not in all_col_names:
                name = v
                break

        grade_cols = dim_cols["grade"]
        grade = None
        for gc in grade_cols:
            v = _normalize_text(row.get(gc))
            if v:
                grade = v
                break

        class_cols = dim_cols["class_name"]
        class_name = None
        for cc in class_cols:
            v = _normalize_text(row.get(cc))
            if v:
                class_name = v
                break

        # --- 学习风险 ---
        learning = LearningRisk()
        learning_raw = {}

        # 按时间排序取最新成绩
        latest_score = _get_latest_score(row, dim_cols["score_level"])
        if latest_score is not None:
            learning.score_level = latest_score
        # 记录所有成绩列的值（含纯数字和〖score〗文本格式）
        for col in dim_cols["score_level"]:
            raw_val = row.get(col)
            if raw_val is not None and not (isinstance(raw_val, float) and pd.isna(raw_val)):
                learning_raw[col] = raw_val

        for col in dim_cols["score_trend"]:
            v = _normalize_text(row.get(col))
            if v:
                # 标准化趋势描述
                v_lower = v
                if any(kw in v_lower for kw in ["上升", "进步", "提升", "提高"]):
                    learning.score_trend = "上升"
                elif any(kw in v_lower for kw in ["下降", "下滑", "退步", "降低"]):
                    learning.score_trend = "下降"
                else:
                    learning.score_trend = "平稳"
                learning_raw[col] = row[col]

        for col in dim_cols["performance"]:
            v = _normalize_text(row.get(col))
            if v:
                v_lower = v
                if any(kw in v_lower for kw in ["积极", "好", "优秀", "认真"]):
                    learning.performance = "积极"
                elif any(kw in v_lower for kw in ["消极", "差", "不认真", "走神"]):
                    learning.performance = "消极"
                else:
                    learning.performance = "一般"
                learning_raw[col] = row[col]

        for col in dim_cols["homework_rate"]:
            v = _normalize_numeric(row.get(col))
            if v is not None:
                learning.homework_rate = min(v, 1.0) if v > 1 else v
                learning_raw[col] = row[col]

        for col in dim_cols["attendance_rate"]:
            v = _normalize_numeric(row.get(col))
            if v is not None:
                learning.attendance_rate = min(v, 1.0) if v > 1 else v
                learning_raw[col] = row[col]

        learning.raw_columns = learning_raw

        # --- 家长风险 ---
        parent = ParentRisk()
        parent_raw = {}

        for col in dim_cols["parent_attitude"]:
            v = _normalize_text(row.get(col))
            if v:
                v_lower = v
                # 先检查负面（"不满意"含"不满"，必须在"满意"之前检查）
                if any(kw in v_lower for kw in ["消极", "差", "不满", "抵触", "不满意"]):
                    parent.attitude = "消极"
                elif any(kw in v_lower for kw in ["积极", "好", "满意", "支持"]):
                    parent.attitude = "积极"
                else:
                    parent.attitude = "中性"
                parent_raw[col] = row[col]

        for col in dim_cols["parent_communication"]:
            v = _normalize_text(row.get(col))
            if v:
                parent.communication = v[:200]  # 截取前200字符
                parent_raw[col] = row[col]
                # 分析文本信号
                signals = _analyze_text_content(v)
                for sig in signals:
                    parent.signals.append({
                        "signal": sig["signal"],
                        "label": sig["label"],
                        "matched": sig["matched"],
                        "source_col": col,
                    })

        for col in dim_cols["parent_concern"]:
            v = _normalize_text(row.get(col))
            if v:
                parent.concern = v[:200]
                parent_raw[col] = row[col]
                signals = _analyze_text_content(v)
                for sig in signals:
                    parent.signals.append({
                        "signal": sig["signal"],
                        "label": sig["label"],
                        "matched": sig["matched"],
                        "source_col": col,
                    })

        parent.raw_columns = parent_raw

        # --- 服务风险 ---
        service = ServiceRisk()
        service_raw = {}

        for col in dim_cols["renewal_intention"]:
            v = _normalize_text(row.get(col))
            if v:
                service.renewal_intention = v
                service_raw[col] = row[col]

        for col in dim_cols["renewal_days"]:
            v = _normalize_numeric(row.get(col))
            if v is not None:
                service.renewal_days = int(v)
                service_raw[col] = row[col]

        for col in dim_cols["last_contact_days"]:
            raw_val = row.get(col)
            # 日期类型：计算距今多少天
            if isinstance(raw_val, pd.Timestamp):
                from datetime import datetime
                days_ago = (datetime.now() - raw_val.to_pydatetime()).days
                service.last_contact_days = days_ago
                service_raw[col] = row[col]
            elif raw_val is not None:
                # 尝试解析日期字符串
                from datetime import datetime
                try:
                    dt = pd.Timestamp(raw_val)
                    days_ago = (datetime.now() - dt.to_pydatetime()).days
                    service.last_contact_days = days_ago
                    service_raw[col] = row[col]
                except Exception:
                    v = _normalize_numeric(raw_val)
                    if v is not None:
                        service.last_contact_days = int(v)
                        service_raw[col] = row[col]

        service.raw_columns = service_raw

        # --- 缺失维度 ---
        missing = []
        all_dims = {
            "score_level": learning.score_level,
            "score_trend": learning.score_trend,
            "performance": learning.performance,
            "homework_rate": learning.homework_rate,
            "attendance_rate": learning.attendance_rate,
            "parent_attitude": parent.attitude,
            "parent_communication": parent.communication,
            "parent_concern": parent.concern,
            "renewal_intention": service.renewal_intention,
            "renewal_days": service.renewal_days,
            "last_contact_days": service.last_contact_days,
        }
        for dim_key, val in all_dims.items():
            if val is None:
                # 使用预计算的标签映射
                missing.append(dim_label_map.get(dim_key, dim_key))

        profile = UnifiedStudentProfile(
            name=name,
            grade=grade,
            class_name=class_name,
            learning=learning,
            parent=parent,
            service=service,
            raw_data=raw_data,
            recognition=recognition,
            missing_dimensions=missing,
        )
        profiles.append(profile)

    return profiles


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
    """解析学情Excel文件（智能检测表头行位置，高效读取）"""
    # 先读取前3行检测表头（使用calamine引擎加速）
    df_preview = pd.read_excel(file_path, engine="calamine", header=None, nrows=3)

    if len(df_preview) < 2:
        return pd.read_excel(file_path, engine="calamine", header=None)

    row0 = df_preview.iloc[0]
    row0_nan_ratio = row0.isna().sum() / len(row0)

    row1 = df_preview.iloc[1]
    row1_non_nan = row1.dropna()
    row1_short_text = sum(1 for v in row1_non_nan if isinstance(v, str) and len(str(v).strip()) <= 20)
    row1_header_ratio = row1_short_text / len(row1) if len(row1) > 0 else 0

    if row0_nan_ratio > 0.5 and row1_header_ratio > 0.3:
        df_raw = pd.read_excel(file_path, engine="calamine", header=None)
        headers = []
        seen = {}
        for i in range(len(df_raw.columns)):
            v0 = row0.iloc[i] if i < len(row0) else None
            v1 = row1.iloc[i] if i < len(row1) else None
            v0_str = str(v0).strip() if pd.notna(v0) and str(v0).strip() else ""
            v1_str = str(v1).strip() if pd.notna(v1) and str(v1).strip() else ""
            if v0_str and v1_str:
                h = f"{v0_str}_{v1_str}"
            elif v1_str:
                h = v1_str
            elif v0_str:
                h = v0_str
            else:
                h = f"Unnamed_{i}"
            if h in seen:
                seen[h] += 1
                h = f"{h}_{seen[h]}"
            else:
                seen[h] = 1
            headers.append(h)
        df = df_raw.iloc[2:].copy()
        df.columns = headers
        df = df.reset_index(drop=True)
        return df

    df = pd.read_excel(file_path, engine="calamine", header=0)
    return df


def parse_uploaded_excel(uploaded_file) -> pd.DataFrame:
    """解析Streamlit上传的Excel文件（智能检测表头行位置，高效读取）"""
    import tempfile
    # 保存到临时文件，使用calamine引擎加速读取
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(uploaded_file.getbuffer())
        tmp_path = tmp.name

    try:
        # 只读取前3行检测表头位置（避免全量读取两次）
        df_preview = pd.read_excel(tmp_path, engine="calamine", header=None, nrows=3)

        if len(df_preview) < 2:
            # 文件太小，直接全量读取
            df = pd.read_excel(tmp_path, engine="calamine", header=None)
            return df

        # 检测第0行是否像表头（非NaN的短文本比例高）
        row0 = df_preview.iloc[0]
        row0_non_nan = row0.dropna()
        row0_short_text = sum(1 for v in row0_non_nan if isinstance(v, str) and len(str(v).strip()) <= 20)
        row0_header_ratio = row0_short_text / len(row0) if len(row0) > 0 else 0

        # 检测第1行是否像表头
        row1 = df_preview.iloc[1]
        row1_non_nan = row1.dropna()
        row1_short_text = sum(1 for v in row1_non_nan if isinstance(v, str) and len(str(v).strip()) <= 20)
        row1_header_ratio = row1_short_text / len(row1) if len(row1) > 0 else 0

        # 如果第0行大部分是NaN（合并单元格表头行），且第1行像表头 → 用第1行做表头
        row0_nan_ratio = row0.isna().sum() / len(row0)
        if row0_nan_ratio > 0.5 and row1_header_ratio > 0.3:
            # 全量读取（无表头），合并第0行和第1行作为表头
            df_raw = pd.read_excel(tmp_path, engine="calamine", header=None)
            headers = []
            seen = {}
            for i in range(len(df_raw.columns)):
                v0 = row0.iloc[i] if i < len(row0) else None
                v1 = row1.iloc[i] if i < len(row1) else None
                v0_str = str(v0).strip() if pd.notna(v0) and str(v0).strip() else ""
                v1_str = str(v1).strip() if pd.notna(v1) and str(v1).strip() else ""
                if v0_str and v1_str:
                    h = f"{v0_str}_{v1_str}"
                elif v1_str:
                    h = v1_str
                elif v0_str:
                    h = v0_str
                else:
                    h = f"Unnamed_{i}"
                if h in seen:
                    seen[h] += 1
                    h = f"{h}_{seen[h]}"
                else:
                    seen[h] = 1
                headers.append(h)
            df = df_raw.iloc[2:].copy()
            df.columns = headers
            df = df.reset_index(drop=True)
            return df

        # 默认：用第0行做表头（一次全量读取）
        df = pd.read_excel(tmp_path, engine="calamine", header=0)
        return df
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def df_to_profiles(df: pd.DataFrame) -> list[StudentProfile]:
    """将DataFrame转换为StudentProfile列表（容错：缺失列使用默认值）"""
    profiles = []
    for _, row in df.iterrows():
        # 安全获取作业完成率（支持百分比字符串）
        hw_raw = row.get("作业完成率", 0.5)
        if isinstance(hw_raw, str):
            hw_raw = float(hw_raw.strip("%")) / 100
        hw_rate = float(hw_raw) if pd.notna(hw_raw) else 0.5

        profile = StudentProfile(
            name=str(row.get("学生姓名", row.get("姓名", "未知"))),
            grade=str(row.get("年级", "未知")),
            class_name=str(row.get("班级", "未知")),
            recent_score=float(row.get("最近成绩", 0)),
            score_trend=str(row.get("成绩趋势", "平稳")),
            participation=str(row.get("课堂参与度", "一般")),
            homework_rate=hw_rate,
            last_contact_days=int(row.get("距上次沟通(天)", 0)),
            renewal_days_left=int(row.get("续费剩余(天)", 999)),
            renewal_history=int(row.get("历史续费次数", 0)),
            parent_attitude=str(row.get("家长态度", "中性")),
        )
        profiles.append(profile)
    return profiles


@dataclass
class FlexibleStudentProfile:
    """动态字段的学生画像 - 支持任意列数据"""
    name: str
    raw_data: dict
    classification: dict
    
    risk_score: float = field(init=False)
    tier: str = field(init=False)
    priority: int = field(init=False)
    risk_details: dict = field(default_factory=dict, init=False)
    
    def __post_init__(self):
        self.risk_score, self.risk_details = self._calc_risk_score()
        self.tier = self._calc_tier()
        self.priority = self._calc_priority()
    
    def _calc_risk_score(self) -> tuple:
        """基于维度注册表动态计算风险分"""
        from config import RISK_DIMENSIONS
        
        total_weight = 0
        total_score = 0.0
        details = {}
        
        for dim in RISK_DIMENSIONS:
            # 查找所有匹配的列
            matched_cols = []
            for col in self.raw_data.keys():
                for keyword in dim["match_keywords"]:
                    if keyword in str(col):
                        matched_cols.append(col)
                        break
            
            if not matched_cols:
                continue
            
            # 对所有匹配列计算得分，取最高风险分
            best_score = 0
            best_col = matched_cols[0]
            best_val = self.raw_data.get(matched_cols[0])
            
            for col in matched_cols:
                val = self.raw_data.get(col)
                try:
                    score = dim["score_func"](val)
                    if score > best_score:
                        best_score = score
                        best_col = col
                        best_val = val
                except Exception:
                    pass
            
            total_score += best_score
            details[dim["name"]] = {
                "column": best_col,
                "value": str(best_val)[:50] if pd.notna(best_val) and best_val else "",
                "score": best_score
            }
        
        return min(total_score, 120), details
    
    def _calc_tier(self) -> str:
        if self.risk_score >= RISK_THRESHOLD_S:
            return "S"
        elif self.risk_score >= RISK_THRESHOLD_A:
            return "A"
        elif self.risk_score >= RISK_THRESHOLD_B:
            return "B"
        return "C"
    
    def _calc_priority(self) -> int:
        tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        renewal_days = 999
        for key, val in self.raw_data.items():
            if "续费" in str(key) or "剩余" in str(key):
                try:
                    renewal_days = int(val) if pd.notna(val) else 999
                    break
                except Exception:
                    pass
        return tier_order[self.tier] * 1000 + renewal_days
    
    def to_dict(self) -> dict:
        result = {
            "学生姓名": self.name,
            "流失风险分": round(self.risk_score, 1),
            "分层": self.tier,
            "优先级": self.priority,
            "风险详情": self.risk_details,
        }
        for cat, cols in self.classification.items():
            for col in cols[:3]:
                if col in self.raw_data:
                    result[col] = self.raw_data[col]
        return result


def parse_flexible_excel(uploaded_file) -> tuple:
    """
    解析Excel文件，返回DataFrame和列分类结果
    """
    from core.column_classifier import classify_columns
    
    df = pd.read_excel(uploaded_file)
    classification = classify_columns(df)
    return df, classification


def detect_name_column(df: pd.DataFrame, classification: dict = None) -> str:
    """智能检测学生姓名列

    支持多种列名格式（无论中英文）：
    - 姓名 / 名字 / 学生姓名 / 学员姓名 / 考生姓名 / 学生名称 / 学员名称
    - 学生 / 学员 / 考生 / 同学
    - name / Name / NAME / student name / student_name
    - 第一列（如果前面都没匹配到，取第一列）

    Args:
        df: 数据DataFrame
        classification: classify_columns() 的结果（可选）

    Returns:
        匹配到的列名

    Raises:
        ValueError: 所有策略都匹配失败
    """
    columns = list(df.columns)

    # 策略1: 通过分类结果查找
    if classification:
        for col in classification.get("身份信息", []):
            if _is_name_column(col):
                return col

    # 策略2: 精确关键词匹配
    for col in columns:
        if _is_name_column(col):
            return col

    # 策略3: 取第一列文本列（只要不是纯数字列）
    first_col = columns[0]
    non_null = df[first_col].dropna()
    if len(non_null) > 0:
        # 检查第一列是否看起来像名字（文本、不全是数字）
        sample = str(non_null.iloc[0])
        if not sample.replace(".", "").replace("-", "").isdigit():
            return first_col

    # 策略4: 找第一个非纯数字列
    for col in columns:
        non_null = df[col].dropna()
        if len(non_null) > 0:
            sample = str(non_null.iloc[0])
            if not sample.replace(".", "").replace("-", "").isdigit():
                return col

    raise ValueError("无法找到学生姓名列，请确保Excel包含姓名相关列")


def _is_name_column(col) -> bool:
    """判断列名是否表示学生姓名"""
    name_keywords = [
        "姓名", "名字", "学生", "学员", "考生", "同学",
        "name", "Name", "NAME", "student", "Student",
    ]
    col_str = str(col)
    for kw in name_keywords:
        if kw in col_str:
            return True
    return False


def df_to_flexible_profiles(df: pd.DataFrame, classification: dict) -> list:
    """将DataFrame转换为FlexibleStudentProfile列表"""
    profiles = []
    name_col = detect_name_column(df, classification)
    for _, row in df.iterrows():
        raw_data = {col: row[col] for col in df.columns}
        name = str(row[name_col]) if pd.notna(row[name_col]) else "未知"
        profile = FlexibleStudentProfile(
            name=name,
            raw_data=raw_data,
            classification=classification
        )
        profiles.append(profile)
    return profiles
