"""
字段语义识别层 — 结合列名关键词 + 数据值类型 + 内容信号分析
将任意格式Excel列映射到统一业务维度
"""
import pandas as pd
import re
from typing import Optional


# =====================================================================
# 值类型检测
# =====================================================================

def _sample_values(series: pd.Series, n: int = 20) -> list:
    """采样前N个非空值"""
    return series.dropna().head(n).tolist()


def _detect_value_type(series: pd.Series, sample_n: int = 50) -> str:
    """
    检测列的值类型
    返回: name_string / grade_string / numeric_score / percentage /
          categorical_status / date_value / days_number /
          long_text / boolean_flag / unknown
    """
    samples = _sample_values(series, sample_n)
    if not samples:
        return "unknown"

    str_samples = [str(s).strip() for s in samples]
    non_empty = [s for s in str_samples if s]

    if not non_empty:
        return "unknown"

    # 1. 日期检测
    if all(isinstance(s, pd.Timestamp) for s in samples if pd.notna(s)):
        return "date_value"

    # 2. 布尔标记检测
    bool_set = {"是", "否", "True", "true", "False", "false", "1", "0", "Y", "N", "yes", "no"}
    if all(s in bool_set for s in non_empty):
        return "boolean_flag"

    # 3. 纯数字检测
    numeric_count = 0
    for s in non_empty:
        try:
            float(s.replace("%", "").replace(",", ""))
            numeric_count += 1
        except ValueError:
            pass

    if numeric_count == len(non_empty):
        nums = [float(s.replace("%", "").replace(",", "")) for s in non_empty]

        # 百分比（含%符号或0-1之间的小数）
        has_pct = any("%" in s for s in non_empty)
        all_small = all(0 <= n <= 1 for n in nums)
        if has_pct or all_small:
            return "percentage"

        # 成绩分数（0-150范围）— 必须在天数之前检测，否则85/60/92被误判为天数
        if all(0 <= n <= 150 for n in nums):
            return "numeric_score"

        # 天数（正整数，0-365范围，且不全是0-150的成绩）
        all_int = all(n == int(n) for n in nums)
        all_in_range = all(0 <= n <= 365 for n in nums)
        if all_int and all_in_range:
            return "days_number"

        return "numeric_score"

    # 4. 长文本检测（任一值>30字符或平均长度>20字符）
    max_len = max(len(s) for s in non_empty)
    avg_len = sum(len(s) for s in non_empty) / len(non_empty)
    if max_len > 30 or avg_len > 20:
        return "long_text"

    # 5. 年级检测
    grade_pattern = re.compile(
        r"^(?:一|二|三|四|五|六|七|八|九|初[一二三]|高[一二三]|"
        r"小[一二三四五六]|大[一二三四]|"
        r"一年级|二年级|三年级|四年级|五年级|六年级|"
        r"学前|幼儿园|中班|大班|小班)$"
    )
    if all(grade_pattern.match(s) for s in non_empty):
        return "grade_string"

    # 6. 姓名检测（1-4个中文字符，允许&连接双人姓名，允许末尾标点）
    #    采样50条，唯一性阈值分级：≤20条要求70%，>20条要求40%
    #    真实数据中重名是正常的，不能要求100%唯一
    #    排除地名：含省/市/区/县/镇/乡/路/街/省/自治区等后缀，或匹配已知地名
    #    匹配率≥95%即可（容忍个别数据录入错误如末尾句号、双人&连接等）
    unique_vals = set(non_empty)
    name_pattern = re.compile(r"^[\u4e00-\u9fff·&]{1,8}$")
    name_match_count = sum(1 for s in non_empty if name_pattern.match(s))
    name_match_ratio = name_match_count / len(non_empty) if non_empty else 0
    if name_match_ratio >= 0.95:
        # 地名检测：如果大部分值看起来像地名，不判为姓名
        location_suffix = re.compile(r"(省|市|区|县|镇|乡|村|路|街|道|巷|弄|自治区|自治州)$")
        location_count = sum(1 for s in non_empty if location_suffix.search(s))
        # 已知常见地名（不含后缀的纯地名）
        known_locations = {
            "北京", "上海", "天津", "重庆",
            "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东",
            "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海",
            "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
            "西安", "南京", "杭州", "武汉", "成都", "广州", "深圳", "苏州", "郑州", "长沙",
            "合肥", "福州", "南昌", "济南", "青岛", "大连", "沈阳", "哈尔滨", "长春", "昆明",
            "贵阳", "南宁", "兰州", "银川", "西宁", "拉萨", "乌鲁木齐", "呼和浩特", "石家庄", "太原",
            "海口", "珠海", "东莞", "佛山", "无锡", "宁波", "温州", "厦门", "泉州", "烟台",
        }
        location_hit_count = sum(1 for s in non_empty if any(loc in s for loc in known_locations))
        # 如果超过30%的值是已知地名或含地名后缀，排除
        if len(non_empty) > 0:
            loc_ratio = (location_count + location_hit_count) / len(non_empty)
            if loc_ratio > 0.3:
                return "unknown"

        uniqueness = len(unique_vals) / len(non_empty)
        if len(non_empty) <= 20:
            if uniqueness >= 0.7:
                return "name_string"
        else:
            if uniqueness >= 0.4:
                return "name_string"

    # 7. 分类状态检测（有限枚举值，每个值≤8字符，且未被姓名检测捕获）
    all_short = all(len(s) <= 8 for s in non_empty)
    if len(unique_vals) <= 10 and all_short:
        return "categorical_status"

    return "unknown"


# =====================================================================
# 业务维度定义
# =====================================================================

BUSINESS_DIMENSIONS = [
    {
        "dimension": "student_name",
        "label": "学生姓名",
        "column_keywords": ["姓名", "名字", "学生", "学员", "考生", "同学", "name", "孩子", "中文名", "昵称", "用户名", "用户"],
        "value_types": ["name_string"],
        "exclude_keywords": ["地区", "城市", "省份", "省", "市", "区", "地址", "所在地", "归属地", "地域", "区域", "学校", "校区", "住址"],
        "priority": 10,  # 最高优先级
    },
    {
        "dimension": "grade",
        "label": "年级",
        "column_keywords": ["年级", "grade", "在读年级"],
        "value_types": ["grade_string", "categorical_status"],
        "priority": 9,
    },
    {
        "dimension": "score_level",
        "label": "成绩水平",
        "column_keywords": ["成绩", "分数", "考试", "期末", "期中", "得分", "测评", "score", "最近成绩"],
        "value_types": ["numeric_score", "categorical_status", "long_text"],
        "exclude_keywords": ["趋势", "变化", "下滑", "上升", "下降", "退步", "进步", "红标", "提升", "满意度", "是否满意"],
        "priority": 8,
    },
    {
        "dimension": "score_trend",
        "label": "成绩趋势",
        "column_keywords": ["趋势", "下滑", "上升", "下降", "退步", "进步", "红标", "变化", "提升"],
        "value_types": ["categorical_status", "boolean_flag"],
        "priority": 8,
    },
    {
        "dimension": "performance",
        "label": "学习表现",
        "column_keywords": ["参与度", "表现", "课堂", "学习态度", "学习状态", "状态"],
        "value_types": ["categorical_status"],
        "exclude_keywords": ["续班", "续费", "报名"],
        "priority": 7,
    },
    {
        "dimension": "homework_rate",
        "label": "作业/练习完成率",
        "column_keywords": ["作业", "练习", "提交", "完成率", "打卡", "作业率", "练习提交"],
        "value_types": ["percentage", "numeric_score"],
        "exclude_keywords": ["时间", "写作业", "作业时间", "作业时长"],
        "priority": 7,
    },
    {
        "dimension": "attendance_rate",
        "label": "听课/出勤率",
        "column_keywords": ["听课", "到课", "出勤", "有效听课", "听课率", "到课率"],
        "value_types": ["percentage", "numeric_score"],
        "priority": 7,
    },
    {
        "dimension": "parent_attitude",
        "label": "家长态度",
        "column_keywords": ["家长态度", "父母态度", "态度", "是否满意", "满意度", "满意"],
        "value_types": ["categorical_status", "long_text"],
        "priority": 6,
    },
    {
        "dimension": "parent_communication",
        "label": "家长沟通记录",
        "column_keywords": ["沟通", "反馈", "回访", "联系", "交流", "家长意见", "家长沟通"],
        "value_types": ["long_text", "categorical_status"],
        "priority": 6,
    },
    {
        "dimension": "parent_concern",
        "label": "家长核心诉求/异议",
        "column_keywords": ["诉求", "关注", "担心", "顾虑", "异议", "疑义", "问题"],
        "value_types": ["long_text", "categorical_status"],
        "priority": 6,
    },
    {
        "dimension": "renewal_intention",
        "label": "续费意愿",
        "column_keywords": ["续费", "续班", "续保", "续报", "意向", "续费状态", "续班状态", "报名", "订金", "意愿", "学员分层", "分层"],
        "value_types": ["categorical_status"],
        "exclude_keywords": ["剩余", "天数", "次数", "历史", "到期", "行课", "下行课"],
        "priority": 8,
    },
    {
        "dimension": "renewal_days",
        "label": "续费剩余天数",
        "column_keywords": ["剩余", "到期", "天数", "续费天数", "续费剩余"],
        "value_types": ["days_number", "date_value"],
        "priority": 8,
    },
    {
        "dimension": "last_contact_days",
        "label": "最近沟通时间",
        "column_keywords": ["沟通间隔", "上次沟通", "最近沟通", "最后联系", "沟通日期", "沟通天数", "距上次沟通", "沟通时间"],
        "value_types": ["days_number", "date_value"],
        "priority": 7,
    },
    {
        "dimension": "class_name",
        "label": "班级",
        "column_keywords": ["班级", "class", "班型"],
        "value_types": ["categorical_status", "name_string"],
        "priority": 5,
    },
    {
        "dimension": "location",
        "label": "地区",
        "column_keywords": ["地区", "城市", "省份", "地址", "所在地", "归属地", "地域", "区域", "省", "市", "区", "学校", "校区", "住址"],
        "value_types": ["name_string", "categorical_status"],
        "priority": 4,
    },
]


# =====================================================================
# 文本内容业务信号分析
# =====================================================================

# 信号定义：(信号名, 关键词列表, 业务含义)
CONTENT_SIGNALS = [
    # 学习效果满意度风险
    {
        "signal": "learning_effectiveness_concern",
        "label": "学习效果满意度风险",
        "keywords": [
            "没效果", "效果不明显", "提升不明显", "进步不大",
            "没有进步", "没进步", "看不到效果", "效果不好",
            "对学习效果有疑虑", "成绩没提高", "没提高",
            "学了没用", "没什么用", "帮助不大",
            "考的不算好", "考得不好", "成绩不理想",
        ],
    },
    # 续费意愿不明确
    {
        "signal": "renewal_uncertain",
        "label": "续费意愿不明确",
        "keywords": [
            "考虑一下", "再看看", "观望", "还没决定", "不确定",
            "暂时不", "先看看", "再想想", "犹豫", "纠结",
            "和家人商量", "商量一下", "回去考虑",
            "未预报", "未续报",
        ],
    },
    # 家长不满
    {
        "signal": "parent_dissatisfaction",
        "label": "家长不满风险",
        "keywords": [
            "不满意", "投诉", "要退费", "退费", "退款",
            "不上了", "不想上", "不学了", "换老师", "换班",
            "太贵", "不值", "浪费钱", "不值得",
        ],
    },
    # 时间紧张
    {
        "signal": "time_pressure",
        "label": "时间紧张风险",
        "keywords": [
            "太忙", "没时间", "时间不够", "作业太多",
            "学校任务重", "顾不上", "没空", "时间冲突",
            "孩子没时间",
        ],
    },
    # 明确续费
    {
        "signal": "renewal_confirmed",
        "label": "明确续费意向",
        "keywords": [
            "续费", "继续上", "继续学", "报名", "续报",
            "再报一期", "接着上", "挺好的", "满意",
        ],
    },
    # 竞品/替代风险
    {
        "signal": "competitor_risk",
        "label": "竞品/替代风险",
        "keywords": [
            "学而思", "新东方", "作业帮", "猿辅导", "线下课",
            "其他机构", "别的机构", "换了机构",
        ],
    },
    # 学习动力不足
    {
        "signal": "motivation_issue",
        "label": "学习动力不足",
        "keywords": [
            "作业不积极", "不积极", "不想做", "不愿意",
            "抵触学习", "厌学", "不想学",
        ],
    },
]


def _analyze_text_content(text: str) -> list:
    """
    分析文本内容中的业务信号
    返回: [{"signal": "learning_effectiveness_concern", "matched": "没效果"}, ...]
    """
    if not text or not isinstance(text, str):
        return []
    signals = []
    for sig in CONTENT_SIGNALS:
        for kw in sig["keywords"]:
            if kw in text:
                # 排除误判：如"不满意"不应匹配"满意"
                if sig["signal"] == "renewal_confirmed" and "不满意" in text:
                    continue
                signals.append({
                    "signal": sig["signal"],
                    "label": sig["label"],
                    "matched": kw,
                })
                break  # 每个信号只匹配一次
    return signals


def _analyze_column_content(series: pd.Series) -> dict:
    """
    分析整列文本内容的业务信号汇总
    返回: {signal_name: {"count": N, "label": "...", "samples": [...]}}
    """
    samples = _sample_values(series, 50)
    text_samples = [str(s).strip() for s in samples if pd.notna(s) and str(s).strip()]

    signal_summary = {}
    for text in text_samples:
        signals = _analyze_text_content(text)
        for sig in signals:
            name = sig["signal"]
            if name not in signal_summary:
                signal_summary[name] = {"count": 0, "label": sig["label"], "samples": []}
            signal_summary[name]["count"] += 1
            if len(signal_summary[name]["samples"]) < 3:
                signal_summary[name]["samples"].append(text[:80])

    return signal_summary


# =====================================================================
# 主识别函数
# =====================================================================

def recognize_columns(df: pd.DataFrame) -> dict:
    """
    识别DataFrame中每列的业务含义

    算法：
    1. 对每列采样 → 判断值类型
    2. 列名关键词匹配 → 候选业务维度
    3. 值类型校验 → 排除不匹配的候选
    4. 文本列 → 分析内容信号
    5. 冲突解决 → 高优先级维度优先

    Args:
        df: 数据DataFrame

    Returns:
        {
            "columns": {
                "学生姓名": {
                    "dimension": "student_name",
                    "label": "学生姓名",
                    "confidence": 0.95,
                    "value_type": "name_string",
                    "content_signals": None
                },
                ...
            },
            "unrecognized": ["备注", "其他列"],
            "content_signals": {
                "learning_effectiveness_concern": {"count": 3, ...}
            }
        }
    """
    columns_result = {}
    unrecognized = []
    all_content_signals = {}

    for col in df.columns:
        col_str = str(col)
        value_type = _detect_value_type(df[col])

        # 对每列计算各维度的匹配分数
        best_dim = None
        best_score = 0
        best_has_kw = False  # 最佳维度是否有关键词命中

        for dim in BUSINESS_DIMENSIONS:
            score = 0

            # 列名关键词匹配
            kw_matches = 0
            for kw in dim["column_keywords"]:
                if kw in col_str:
                    kw_matches += 1

            # student_name 特殊约束：必须值类型匹配，防止"学员ID""学生编号"等数字列误判
            if dim["dimension"] == "student_name" and value_type not in dim.get("value_types", []):
                continue

            if kw_matches > 0:
                score += kw_matches * 2  # 每个关键词+2分

            # 值类型匹配（仅在有关键词命中时加分，避免纯数值类型误匹配）
            if kw_matches > 0 and value_type in dim.get("value_types", []):
                score += 5  # 值类型匹配+5分

            # 排除关键词（减分）
            exclude_hit = False
            for ek in dim.get("exclude_keywords", []):
                if ek in col_str:
                    score -= 5
                    exclude_hit = True
                    break

            # 优先级加成
            score += dim.get("priority", 0) * 0.5

            # 平局时优先选有关键词命中的维度
            if score > best_score or (score == best_score and kw_matches > 0 and not best_has_kw):
                best_score = score
                best_dim = dim
                best_has_kw = kw_matches > 0

        # 置信度计算
        confidence = 0
        if best_dim and best_score >= 3 and best_has_kw:
            confidence = min(best_score / 15, 1.0)  # 最高15分 → 1.0

        # 文本内容分析（对所有非纯数字列进行信号检测）
        content_signals = None
        if value_type in ("long_text", "unknown", "categorical_status"):
            content_signals = _analyze_column_content(df[col])
            for sig_name, sig_data in content_signals.items():
                if sig_name not in all_content_signals:
                    all_content_signals[sig_name] = sig_data
                else:
                    all_content_signals[sig_name]["count"] += sig_data["count"]

        if best_dim and best_score >= 3 and best_has_kw:
            columns_result[col] = {
                "dimension": best_dim["dimension"],
                "label": best_dim["label"],
                "confidence": round(confidence, 2),
                "value_type": value_type,
                "content_signals": content_signals,
            }
        else:
            unrecognized.append(col)

    # --- 去重：如果多列被识别为 student_name，只保留列名含关键词最多的那一列 ---
    name_cols = [col for col, info in columns_result.items() if info["dimension"] == "student_name"]
    if len(name_cols) > 1:
        name_keywords = ["姓名", "名字", "学生", "学员", "考生", "同学", "name", "孩子", "中文名", "昵称"]
        best_col = None
        best_kw = -1
        for col in name_cols:
            col_str = str(col)
            kw_count = sum(1 for kw in name_keywords if kw in col_str)
            if kw_count > best_kw:
                best_kw = kw_count
                best_col = col
        for col in name_cols:
            if col != best_col:
                unrecognized.append(col)
                del columns_result[col]

    return {
        "columns": columns_result,
        "unrecognized": unrecognized,
        "content_signals": all_content_signals,
    }


def get_dimension_value(row, col_name: str, recognition: dict) -> Optional[str]:
    """
    从行数据中获取指定列的维度值
    """
    if col_name not in recognition["columns"]:
        return None
    val = row.get(col_name)
    if pd.isna(val):
        return None
    return str(val).strip()


def get_dimension_columns(recognition: dict, dimension: str) -> list:
    """获取映射到指定维度的所有列名"""
    return [col for col, info in recognition["columns"].items()
            if info["dimension"] == dimension]
