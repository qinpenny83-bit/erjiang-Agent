"""AI学情风险洞察中心 — 规则层引擎（零AI调用）

职责：在现有5维风险分析和P1-P4算法结果之上，用纯规则生成：
1. validate_data_quality   数据质量校验（哪些维度可用、哪些缺失，不足时明确提示）
2. classify_risk_type      风险类型分类（参与度/练习执行/学习效果/趋势变化/数据异常）
3. analyze_trend           近期趋势判断（5维逐讲次序列：↗上升 →稳定 ↘下降 ⚠️波动 ？数据不足）
4. detect_inconsistency    数据与风险不一致检测（汇总指标好但系统判P1-P3时解释异常，不强行合理化）
5. locate_problem_lectures 问题讲次定位（讲次+异常指标+对应真实数据）
6. build_rule_insight      规则版风险洞察（触发指标/风险解释/建议关注，全部来自真实数据）

铁律：本模块所有结论只来自输入数据，不调用大模型，不修改P1-P4结果。
"""
import re
import pandas as pd

# 复用风险分析器的同源解析规则，保证洞察与指标口径完全一致
from core.lecture_risk_analyzer import _parse_val

# ====== 常量 ======
DIM_ORDER = ["有效听课", "听课时长", "答题正确率", "练习提交", "练习得分"]

TREND_SYMBOL = {
    "上升": "↗", "稳定": "→", "下降": "↘", "波动": "⚠️", "暂无足够数据": "？",
}

TREND_COLOR = {
    "上升": "#2E7D32", "稳定": "#607D8B", "下降": "#C62828",
    "波动": "#E65100", "暂无足够数据": "#9E9E9E",
}

# 维度 → 讲次子列名（与 lecture_parser.sub_fields 对应）
DIM_COL_KEY = {
    "有效听课": "是否有效听课",
    "听课时长": "听课时长",
    "答题正确率": "直播答题正确率",
    "练习提交": "练习状态",
    "练习得分": "练习得分",
}

RISK_TYPE_META = {
    "参与度风险": "🔴",
    "练习执行风险": "🟠",
    "学习效果风险": "🟡",
    "趋势变化风险": "🔵",
    "数据异常/待确认": "⚪",
}


def _lecture_num(lec_name: str) -> int:
    """从讲次名提取序号用于排序（第3讲 → 3）"""
    m = re.search(r'(\d+)', str(lec_name))
    return int(m.group(1)) if m else 0


# ============================================================
# 一、数据质量校验
# ============================================================

def validate_data_quality(df: pd.DataFrame, lectures: list, name_col: str) -> dict:
    """上传Excel后自动检查数据质量：学员/讲次识别、5维指标存在性与覆盖率。

    Returns:
        {
          "student_count": int, "lecture_count": int,
          "dims": {维度: {"lecture_coverage": float, "missing_students": int,
                          "missing_rate": float, "usable": bool, "note": str}},
          "errors": [str],      # 阻断性错误
          "warnings": [str],    # 提示性警告（该维度不作为主要判断依据等）
        }
    """
    errors, warnings = [], []
    student_count = len(df)
    lecture_count = len(lectures)

    if student_count == 0:
        errors.append("未识别到学员数据（表格为空）")
    if lecture_count == 0:
        errors.append("未识别到讲次列（列名需以「第N讲」开头并含听课/答题/练习等子字段）")

    dims = {}
    for dim, col_key in DIM_COL_KEY.items():
        if lecture_count == 0:
            dims[dim] = {"lecture_coverage": 0.0, "missing_students": student_count,
                         "missing_rate": 1.0 if student_count else 0.0,
                         "usable": False, "note": "无讲次数据"}
            continue
        cols = [l["cols"][col_key] for l in lectures if l["cols"].get(col_key)]
        lec_cov = len(cols) / lecture_count

        missing_students = 0
        if cols:
            for _, row in df.iterrows():
                has_data = False
                for c in cols:
                    v = row.get(c)
                    if pd.notna(v) and str(v).strip() not in ("", "nan", "None"):
                        has_data = True
                        break
                if not has_data:
                    missing_students += 1
        missing_rate = (missing_students / student_count) if student_count else 0.0

        usable = True
        note = "数据完整"
        if lec_cov == 0:
            usable = False
            note = "该维度列缺失，不参与判断"
            warnings.append(f"当前数据中「{dim}」维度完全缺失，该维度暂不作为判断依据。")
        elif lec_cov < 0.5:
            usable = False
            note = f"讲次覆盖率仅{lec_cov:.0%}，数据不足"
            warnings.append(f"当前数据中「{dim}」覆盖讲次较少（{lec_cov:.0%}），该维度暂不作为主要判断依据。")
        elif missing_rate > 0.3:
            note = f"{missing_rate:.0%}学员无该维度数据"
            warnings.append(f"当前数据中「{dim}」缺失较多（{missing_students}/{student_count}名学员无数据），该维度结论需谨慎参考。")

        dims[dim] = {"lecture_coverage": lec_cov, "missing_students": missing_students,
                     "missing_rate": missing_rate, "usable": usable, "note": note}

    # 异常值检测：正确率/得分超出0-100、时长为负
    anomaly_count = 0
    for dim in ("答题正确率", "练习得分"):
        col_key = DIM_COL_KEY[dim]
        for l in lectures:
            c = l["cols"].get(col_key)
            if not c or c not in df.columns:
                continue
            for v in df[c].dropna():
                num = _parse_val(v)
                if num is not None and (num > 100 or num < 0):
                    anomaly_count += 1
    dur_col = next((l["cols"].get("听课时长") for l in lectures if l["cols"].get("听课时长")), None)
    if dur_col and dur_col in df.columns:
        for v in df[dur_col].dropna():
            num = _parse_val(v)
            if num is not None and num < 0:
                anomaly_count += 1
    if anomaly_count > 0:
        warnings.append(f"检测到{anomaly_count}处异常值（正确率/得分超出0-100或时长为负），已按原值参与统计，建议核实原始数据。")

    return {
        "student_count": student_count,
        "lecture_count": lecture_count,
        "dims": dims,
        "errors": errors,
        "warnings": warnings,
    }


# ============================================================
# 二、近期趋势判断（逐讲次序列，不只看平均值）
# ============================================================

def _build_dim_series(row_data: dict, lectures: list) -> dict:
    """按讲次顺序构建5维数据序列（与风险分析器同源同规则）。

    Returns: {维度: [(讲次序号, 值), ...]}
    """
    sorted_lecs = sorted(lectures, key=lambda l: _lecture_num(l["lecture"]))
    series = {d: [] for d in DIM_ORDER}
    for lec in sorted_lecs:
        cols = lec["cols"]
        num = _lecture_num(lec["lecture"])

        eff_col = cols.get("是否有效听课")
        if eff_col and eff_col in row_data:
            val = str(row_data[eff_col]).strip()
            if val in ("是", "1", "True", "true", "有效"):
                series["有效听课"].append((num, 1))
            elif val in ("否", "0", "False", "false", "无效"):
                series["有效听课"].append((num, 0))

        dur_col = cols.get("听课时长")
        if dur_col and dur_col in row_data:
            v = _parse_val(row_data[dur_col])
            if v is not None and v > 0:
                series["听课时长"].append((num, v))

        acc_col = cols.get("直播答题正确率")
        if acc_col and acc_col in row_data:
            v = _parse_val(row_data[acc_col])
            if v is not None and v > 0:
                series["答题正确率"].append((num, v))

        pr_col = cols.get("练习状态")
        if pr_col and pr_col in row_data:
            pv = str(row_data[pr_col]).strip()
            series["练习提交"].append(
                (num, 0 if pv in ("未提交", "未完成", "0", "", "nan", "None") else 1))

        sc_col = cols.get("练习得分")
        if sc_col and sc_col in row_data:
            v = _parse_val(row_data[sc_col])
            if v is not None and v > 0:
                series["练习得分"].append((num, v))
    return series


def _judge_dim_trend(dim: str, pairs: list) -> dict:
    """判断单一维度的趋势：↗上升 →稳定 ↘下降 ⚠️波动 ？暂无足够数据"""
    vals = [v for _, v in pairs]
    n = len(vals)
    if n < 3:
        return {"trend": "暂无足够数据", "symbol": TREND_SYMBOL["暂无足够数据"],
                "detail": f"仅{n}讲有数据", "continuous_decline": False, "values": vals}

    # 维度阈值：比率类（答题/得分按分值）10分；二值率类0.15；时长按均值20%
    if dim in ("答题正确率", "练习得分"):
        thr = 10.0
    elif dim in ("有效听课", "练习提交"):
        thr = 0.15
    else:
        thr = max(5.0, (sum(vals) / n) * 0.2)

    # 近期窗口 vs 前期窗口
    if n >= 6:
        recent, earlier = vals[-3:], vals[:-3]
    elif n == 5:
        recent, earlier = vals[-2:], vals[:-2]
    elif n == 4:
        recent, earlier = vals[-2:], vals[:2]
    else:
        recent, earlier = vals[-2:], vals[:1]
    rec_avg = sum(recent) / len(recent)
    ear_avg = sum(earlier) / len(earlier)
    delta = rec_avg - ear_avg

    # 连续下降步（>=2步即3个点连续走低）
    diffs = [vals[i + 1] - vals[i] for i in range(n - 1)]
    consec, max_consec = 0, 0
    for d in diffs:
        if d < 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    continuous_decline = max_consec >= 2 and delta < 0

    # 方向切换次数（识别波动）
    signs = [1 if d > thr * 0.2 else (-1 if d < -thr * 0.2 else 0) for d in diffs]
    changes = sum(1 for i in range(len(signs) - 1)
                  if signs[i] != 0 and signs[i + 1] != 0 and signs[i] != signs[i + 1])
    rng = max(vals) - min(vals)

    # 先判波动（多次方向切换且振幅大），再判方向（避免震荡下跌被误判为单纯下降）
    if changes >= 2 and rng >= 2 * thr:
        trend = "波动"
    elif delta <= -thr:
        trend = "下降"
    elif delta >= thr:
        trend = "上升"
    else:
        trend = "稳定"

    def _fmt(v):
        return f"{v * 100:.0f}%" if dim in ("有效听课", "练习提交") and v <= 1 else f"{v:.0f}"

    detail = f"近期均值{_fmt(rec_avg)} vs 前期{_fmt(ear_avg)}"
    return {"trend": trend, "symbol": TREND_SYMBOL[trend], "detail": detail,
            "continuous_decline": continuous_decline, "values": vals,
            "recent_avg": rec_avg, "earlier_avg": ear_avg}


def analyze_trend(row_data: dict, lectures: list, risk_detail: dict = None) -> dict:
    """5维趋势判断 + 整体结论与模式识别。

    模式：持续下降 / 多维同步下降 / 单项异常 / 当前稳定但存在历史异常
    """
    series = _build_dim_series(row_data, lectures)
    dims = {d: _judge_dim_trend(d, series[d]) for d in DIM_ORDER}

    declining = [d for d in DIM_ORDER if dims[d]["trend"] == "下降"]
    rising = [d for d in DIM_ORDER if dims[d]["trend"] == "上升"]
    volatile = [d for d in DIM_ORDER if dims[d]["trend"] == "波动"]
    abnormal = [d for d in DIM_ORDER if dims[d]["trend"] in ("下降", "波动")]
    no_data = [d for d in DIM_ORDER if dims[d]["trend"] == "暂无足够数据"]
    cont_decline_dims = [d for d in DIM_ORDER if dims[d].get("continuous_decline")]

    # 历史异常 vs 当前稳定：问题讲次是否全部发生在较早讲次（最近3讲干净）
    history_clean_current = False
    if risk_detail and lectures:
        sorted_lecs = sorted(lectures, key=lambda l: _lecture_num(l["lecture"]))
        recent_nums = {_lecture_num(l["lecture"]) for l in sorted_lecs[-3:]}
        problem_nums = set()
        anomalies = risk_detail.get("anomalies", {})
        for key in ("无效听课", "答题低于70", "未提交练习", "练习低于70"):
            for item in anomalies.get(key, []):
                problem_nums.add(_lecture_num(item[0]))
        if problem_nums and not (problem_nums & recent_nums):
            history_clean_current = True

    patterns = {
        "持续下降": cont_decline_dims,
        "多维同步下降": len(declining) >= 2,
        "单项异常": len(abnormal) == 1,
        "当前稳定但存在历史异常": history_clean_current and not declining,
    }

    # 整体结论（优先级从高到低）
    if len(declining) >= 2:
        conclusion = f"多维度下降（{'、'.join(declining)}），需重点关注"
        symbol = "↘"
    elif cont_decline_dims:
        conclusion = f"{cont_decline_dims[0]}持续下降，需重点关注"
        symbol = "↘"
    elif declining:
        conclusion = f"{declining[0]}近期下降，建议关注"
        symbol = "↘"
    elif volatile:
        conclusion = f"{volatile[0]}波动明显，其他维度稳定"
        symbol = "⚠️"
    elif len(no_data) >= 4:
        conclusion = f"数据不足（{len(no_data)}个维度缺数据），暂无法完整判断趋势"
        symbol = "？"
    elif history_clean_current:
        conclusion = "近期表现稳定，问题讲次均发生在较早讲次，当前暂无持续恶化证据"
        symbol = "→"
    elif rising:
        conclusion = "整体稳定回升，暂无恶化证据"
        symbol = "↗"
    else:
        conclusion = "整体稳定，当前暂无持续恶化证据"
        symbol = "→"

    return {
        "dims": dims,
        "patterns": patterns,
        "conclusion": conclusion,
        "summary_symbol": symbol,
        "declining": declining, "rising": rising,
        "volatile": volatile, "no_data": no_data,
    }


# ============================================================
# 三、风险类型分类
# ============================================================

def classify_risk_type(risk_detail: dict, trend_result: dict) -> dict:
    """基于异常明细与指标，分类主要风险类型（纯规则，不改变P1-P4）。

    Returns: {"primary": (类型, 图标, [触发指标]) 或 None,
              "secondary": [(类型, 图标, [触发指标]), ...]}
    """
    anomalies = risk_detail.get("anomalies", {})
    m = risk_detail.get("metrics", {})
    inv = len(anomalies.get("无效听课", []))
    unpr = len(anomalies.get("未提交练习", []))
    lowacc = len(anomalies.get("答题低于70", []))
    lowsc = len(anomalies.get("练习低于70", []))

    listen_rate = m["有效听课"]["rate"] if m["有效听课"]["total"] > 0 else None
    submit_rate = m["练习提交"]["rate"] if m["练习提交"]["total"] > 0 else None

    types = []
    if inv >= 2 or (listen_rate is not None and listen_rate < 0.6):
        triggers = []
        if listen_rate is not None:
            triggers.append(f"有效听课率{listen_rate * 100:.0f}%")
        if inv:
            triggers.append(f"无效听课{inv}讲")
        types.append(("参与度风险", "🔴", triggers))
    if unpr >= 2 or (submit_rate is not None and submit_rate < 0.6):
        triggers = []
        if submit_rate is not None:
            triggers.append(f"练习提交率{submit_rate * 100:.0f}%")
        if unpr:
            triggers.append(f"未提交练习{unpr}讲")
        types.append(("练习执行风险", "🟠", triggers))
    if lowacc >= 2 or lowsc >= 2:
        triggers = []
        if lowacc:
            triggers.append(f"答题低于70%共{lowacc}讲")
        if lowsc:
            triggers.append(f"练习低于70分共{lowsc}讲")
        types.append(("学习效果风险", "🟡", triggers))
    if len(trend_result.get("declining", [])) >= 2 or trend_result.get("patterns", {}).get("持续下降"):
        triggers = [f"{d}呈下降趋势" for d in trend_result["declining"]] or \
                   [f"{d[0] if isinstance(d, list) else d}持续下降"
                    for d in ([trend_result["patterns"]["持续下降"]] if trend_result["patterns"].get("持续下降") else [])]
        types.append(("趋势变化风险", "🔵", triggers))

    if not types:
        if "P4" in str(risk_detail.get("priority", "")):
            return {"primary": None, "secondary": []}
        # 有风险等级但无明显类型 → 数据异常/待确认（典型：单次问题讲次触发P1）
        problem_count = sum(len(v) for v in anomalies.values())
        triggers = []
        if problem_count:
            triggers.append(f"存在{problem_count}个问题讲次，但汇总指标未达风险阈值")
        if not triggers:
            triggers.append("触发依据需人工核实")
        return {"primary": ("数据异常/待确认", "⚪", triggers), "secondary": []}

    return {"primary": types[0], "secondary": types[1:3]}


# ============================================================
# 四、数据与风险不一致检测
# ============================================================

def detect_inconsistency(risk_detail: dict) -> dict:
    """检测「汇总指标整体较好但系统判为P1/P2/P3」的情况。

    场景：有效听课率90%、正确率95%、提交率90%、得分99，但因1个无效听课被判P1。
    此时AI/规则都不得说"学习表现差"，必须解释异常。
    """
    m = risk_detail.get("metrics", {})
    anomalies = risk_detail.get("anomalies", {})
    priority = str(risk_detail.get("priority", ""))
    if "P4" in priority:
        return {"inconsistent": False}

    problem_count = sum(len(v) for v in anomalies.values())

    checks = []  # (是否良好, 维度名)
    if m["有效听课"]["total"] > 0:
        checks.append((m["有效听课"]["rate"] >= 0.9, "有效听课率"))
    if m["答题正确率"]["values"]:
        checks.append((m["答题正确率"]["avg"] >= 85, "答题正确率"))
    if m["练习提交"]["total"] > 0:
        checks.append((m["练习提交"]["rate"] >= 0.9, "练习提交率"))
    if m["练习得分"]["values"]:
        checks.append((m["练习得分"]["avg"] >= 85, "练习得分"))

    good_dims = [name for ok, name in checks if ok]
    if len(checks) >= 2 and all(ok for ok, _ in checks) and problem_count <= 2:
        return {
            "inconsistent": True,
            "problem_count": problem_count,
            "good_dims": good_dims,
            "message": (
                f"当前汇总指标整体较好（{'、'.join(good_dims)}均达标），"
                f"但系统识别到{problem_count}个问题讲次。"
                f"建议查看具体问题讲次，暂不能仅凭当前汇总数据判断为持续性风险。"
            ),
        }
    return {"inconsistent": False}


# ============================================================
# 五、问题讲次定位
# ============================================================

def locate_problem_lectures(risk_detail: dict, lectures: list) -> list:
    """定位具体问题讲次：讲次 + 异常指标 + 对应真实数据。

    Returns: [{"lecture": "第2讲", "title": "课程名", "issues": [{"type", "data"}]}, ...]
    按讲次序号升序。
    """
    anomalies = risk_detail.get("anomalies", {})
    title_map = {l["lecture"]: l.get("title", "") for l in lectures}
    problems = {}

    def _add(lec, issue_type, data):
        entry = problems.setdefault(lec, {"lecture": lec, "title": title_map.get(lec, ""), "issues": []})
        entry["issues"].append({"type": issue_type, "data": data})

    for lec, _title in anomalies.get("无效听课", []):
        _add(lec, "有效听课异常", "无效听课")
    for lec, acc in anomalies.get("答题低于70", []):
        _add(lec, "答题正确率异常", f"正确率{acc:.0f}%")
    for item in anomalies.get("未提交练习", []):
        _add(item[0], "练习未提交", "练习状态：未提交")
    for lec, sc in anomalies.get("练习低于70", []):
        _add(lec, "练习得分偏低", f"得分{sc:.0f}分")

    return sorted(problems.values(), key=lambda p: _lecture_num(p["lecture"]))


# ============================================================
# 六、规则版风险洞察（无AI时的兜底 + 非TOP学员的轻量分析）
# ============================================================

_FOCUS_TEMPLATES = {
    "参与度风险": "建议优先关注近期课程参与情况，确认听课异常的具体原因。",
    "练习执行风险": "建议优先关注练习完成情况，督促按时提交练习。",
    "学习效果风险": "建议关注答题与练习得分偏低的讲次，安排错题订正。",
    "趋势变化风险": "建议关注近期指标变化趋势，确认是否持续恶化。",
    "数据异常/待确认": "建议核实数据完整性与具体问题讲次后再判断。",
}

_EXPLAIN_TEMPLATES = {
    "参与度风险": "课程参与度指标明显偏低，存在较多听课异常。",
    "练习执行风险": "练习完成情况明显不足，存在较多未提交练习。",
    "学习效果风险": "答题正确率与练习得分存在偏低讲次，学习效果有待提升。",
    "趋势变化风险": "多项指标近期呈下降趋势，需关注变化原因。",
    "数据异常/待确认": "汇总指标与风险等级的对应关系需进一步核实。",
}


def build_rule_insight(risk_detail: dict, risk_type: dict, trend_result: dict,
                       inconsistency: dict, problem_count: int) -> dict:
    """规则版洞察：字段与AI版完全一致，全部由真实数据模板化生成。"""
    if inconsistency.get("inconsistent"):
        primary = "数据异常/待确认"
        triggers = [f"汇总指标较好但存在{inconsistency['problem_count']}个问题讲次"]
        explanation = inconsistency["message"]
        focus = "建议查看具体问题讲次核实情况，暂不作为持续性风险处理。"
    elif risk_type["primary"]:
        tname, _icon, triggers = risk_type["primary"]
        primary = tname
        trigger_strs = list(triggers)
        problem_hint = f"，当前存在{problem_count}个问题讲次" if problem_count > 0 else ""
        explanation = f"{'、'.join(trigger_strs)}{problem_hint}。{_EXPLAIN_TEMPLATES.get(tname, '')}"
        focus = _FOCUS_TEMPLATES.get(tname, "")
    else:
        primary = "暂无明显风险"
        triggers = ["5维指标均在正常范围"]
        explanation = "当前5维指标未触发风险规则，暂无明显风险。"
        focus = "保持当前学习状态，定期关注即可。"

    return {
        "主要风险": primary,
        "触发指标": "、".join(triggers),
        "风险解释": explanation,
        "建议关注": focus,
        "趋势结论": trend_result.get("conclusion", ""),
    }


# ============================================================
# 七、组合：构建单个学员完整洞察
# ============================================================

def build_student_insight(result: dict, lectures: list) -> dict:
    """组合规则层全部能力，生成单个学员完整洞察（零AI调用）。"""
    risk_detail = result["_risk_detail"]
    row_data = result["_row_data"]
    m = risk_detail["metrics"]
    anomalies = risk_detail["anomalies"]

    trend = analyze_trend(row_data, lectures, risk_detail)
    risk_type = classify_risk_type(risk_detail, trend)
    inconsistency = detect_inconsistency(risk_detail)
    problem_lectures = locate_problem_lectures(risk_detail, lectures)
    problem_count = sum(len(p["issues"]) for p in problem_lectures)
    rule_insight = build_rule_insight(risk_detail, risk_type, trend, inconsistency, problem_count)

    # 数据与风险不一致时，主要风险类型统一为「数据异常/待确认」
    # （与规则洞察/报告口径一致：解释异常，而不是强行合理化为某类学习风险）
    if inconsistency.get("inconsistent"):
        risk_type = {
            "primary": ("数据异常/待确认", "⚪",
                        [f"汇总指标较好但存在{inconsistency['problem_count']}个问题讲次"]),
            "secondary": risk_type.get("secondary", []),
        }

    # 5维数据简述（与明细表同口径）
    metrics_brief = "、".join(filter(None, [
        f"有效听课率{m['有效听课']['rate'] * 100:.0f}%" if m["有效听课"]["total"] > 0 else None,
        f"平均听课时长{m['听课时长']['avg']:.0f}分钟" if m["听课时长"]["values"] else None,
        f"答题正确率均值{m['答题正确率']['avg']:.0f}%" if m["答题正确率"]["values"] else None,
        f"练习提交率{m['练习提交']['rate'] * 100:.0f}%" if m["练习提交"]["total"] > 0 else None,
        f"平均练习得分{m['练习得分']['avg']:.0f}分" if m["练习得分"]["values"] else None,
    ])) or "暂无数据"

    anomalies_brief = "、".join(filter(None, [
        f"无效听课{len(anomalies['无效听课'])}讲" if anomalies["无效听课"] else None,
        f"答题低于70%共{len(anomalies['答题低于70'])}讲" if anomalies["答题低于70"] else None,
        f"未提交练习{len(anomalies['未提交练习'])}讲" if anomalies["未提交练习"] else None,
        f"练习低于70分共{len(anomalies['练习低于70'])}讲" if anomalies["练习低于70"] else None,
    ])) or "暂无异常"

    return {
        "name": result["学员姓名"],
        "priority": result["优先级"],
        "risk_score": result["风险分"],
        "risk_type": risk_type["primary"][0] if risk_type["primary"] else None,
        "risk_icon": risk_type["primary"][1] if risk_type["primary"] else "🟢",
        "risk_triggers": risk_type["primary"][2] if risk_type["primary"] else [],
        "secondary_types": [t[0] for t in risk_type["secondary"]],
        "trend": trend,
        "inconsistency": inconsistency,
        "problem_lectures": problem_lectures,
        "problem_count": problem_count,
        "metrics_brief": metrics_brief,
        "anomalies_brief": anomalies_brief,
        "rule_insight": rule_insight,
    }


def build_all_insights(results: list, lectures: list, progress_callback=None) -> list:
    """批量构建全部学员洞察（纯规则，速度优先）"""
    insights = []
    for i, r in enumerate(results):
        insights.append(build_student_insight(r, lectures))
        if progress_callback:
            progress_callback(i + 1, len(results))
    return insights
