import streamlit as st
import pandas as pd
import time
import os
import sys
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TIER_COLORS, TIER_LABELS, OUTPUT_DIR
from utils.excel_parser import parse_uploaded_excel, detect_name_column
from utils.excel_exporter import export_analysis_to_excel, export_reports_to_excel
from utils.logger import log_event, get_daily_stats, get_all_stats

st.set_page_config(page_title="二讲智能服务效能增长Agent", layout="wide", page_icon="🥇")

st.title("🥇二讲智能服务效能增长Agent")
st.caption("AI驱动学情洞察、家校沟通与学员运营，提升服务效能，促进续费增长")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 学情续费预警系统",
    "💬 家校沟通策略助手",
    "📋 风险优先处理中心",
    "📈 数据看板"
])

# ============================================================
# Tab 1: 学情续费预警系统
# ============================================================
with tab1:
    # 🔥 今日风险处理中心：顶部视觉占位（在学情分析完成后渲染，未上传时显示引导）
    task_center_slot = st.container()

    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #e8eaf6 0%, #f3e5f5 100%);
        padding: 10px 18px;
        border-radius: 6px;
        margin-bottom: 4px;
        max-width: 520px;
    ">
        <span style="color: #5c6bc0; font-size: 14px; font-weight: 500;">
            📊 上传学情Excel文件，自动完成字段识别 · 学生分层 · 风险评分 · 话术生成
        </span>
    </div>
    """, unsafe_allow_html=True)

    uploaded_file = st.file_uploader(
        "上传学情数据",
        type=["xlsx", "xls"],
        key="analysis_upload",
        help="支持任意列名格式的Excel文件，系统自动识别字段含义"
    )

    if uploaded_file:
        try:
            df = parse_uploaded_excel(uploaded_file)

            # 统一分析流程：语义识别 → 画像构建 → AI风险分析
            if "analysis_result" not in st.session_state or st.session_state.get("_upload_name") != uploaded_file.name:
                start_time = time.time()
                from core.student_analyzer import analyze_students_unified
                # 添加进度条（AI分析耗时较长，尤其学生数量多时）
                progress_bar = st.progress(0, text="正在预处理学生数据...")
                st.session_state["analysis_result"] = analyze_students_unified(
                    df, generate=False,
                    progress_callback=lambda cur, total: progress_bar.progress(
                        cur / total,
                        text=f"正在AI分析学生风险... {cur}/{total}人"
                    )
                )
                progress_bar.empty()
                st.session_state["_upload_name"] = uploaded_file.name
                st.session_state["scripts_generated"] = False
                elapsed = time.time() - start_time
                log_event("analysis_end", {"student_count": len(df), "duration_s": round(elapsed, 2), "mode": "unified"})

            result = st.session_state["analysis_result"]

            # 4预警标签
            tier_stats = result["tier_stats"]
            tag_p1, tag_p2, tag_p3, tag_p4 = st.columns(4)
            with tag_p1:
                st.markdown(f"<div style='background:#FF4B4B;color:white;padding:6px 12px;border-radius:4px;text-align:center;font-weight:bold'>P1-特别关注: {tier_stats.get('P1', 0)}人</div>", unsafe_allow_html=True)
            with tag_p2:
                st.markdown(f"<div style='background:#FF8C00;color:white;padding:6px 12px;border-radius:4px;text-align:center;font-weight:bold'>P2-需关注: {tier_stats.get('P2', 0)}人</div>", unsafe_allow_html=True)
            with tag_p3:
                st.markdown(f"<div style='background:#FFC000;color:white;padding:6px 12px;border-radius:4px;text-align:center;font-weight:bold'>P3-相对稳定: {tier_stats.get('P3', 0)}人</div>", unsafe_allow_html=True)
            with tag_p4:
                st.markdown(f"<div style='background:#70AD47;color:white;padding:6px 12px;border-radius:4px;text-align:center;font-weight:bold'>P4-优: {tier_stats.get('P4', 0)}人</div>", unsafe_allow_html=True)

            # ============================================================
            # 模块一：风险学员优先处理中心
            # ============================================================
            with st.expander("🎯 风险学员优先处理中心", expanded=True):
                st.caption("基于风险分析结果，对全部学员进行优先级排序，帮助老师快速判断沟通顺序和重点。")

                # --- 排序逻辑 ---
                students = result["students"]
                tier_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}

                def _sort_key(student):
                    tier = student["分层"]
                    tier_rank = tier_order.get(tier, 3)
                    # 同等级内二次排序因子
                    score_decline = 1 if student.get("成绩趋势") == "下降" else 0
                    comm_gap = student.get("沟通间隔天数") or 0
                    # 续费风险：非自然续费/已续费则加分
                    renewal = student.get("续费意愿", "")
                    renewal_risk = 0 if renewal in ("自然续费", "已续费", "") else 1
                    # 风险证据数量
                    evidence_count = len(student.get("风险证据", []))
                    # 排序键：tier升序，其他因子降序（越危险越靠前）
                    return (tier_rank, -score_decline, -comm_gap, -renewal_risk, -evidence_count)

                priority_students = sorted(students, key=_sort_key)

                # --- 构建风险原因文本（4个维度，最多4条） ---
                def _build_risk_reason(s):
                    """按成绩/家长/学生/沟通四维度构建风险原因，最多4条"""
                    risk_points = []
                    score = s.get("最近成绩")
                    trend = s.get("成绩趋势")
                    performance = s.get("学习表现")
                    comm_gap = s.get("沟通间隔天数")
                    renewal = s.get("续费意愿", "")
                    parent = s.get("家长态度")
                    parent_signals = s.get("家长信号", [])

                    # 1. 成绩方面 — 展示最新成绩+趋势
                    if score is not None:
                        # 尝试从原始数据计算趋势（对比最新两次成绩）
                        trend_desc = ""
                        profile = s.get("_profile")
                        if profile and hasattr(profile, "learning"):
                            raw_cols = profile.learning.raw_columns
                            if raw_cols:
                                from utils.excel_parser import _parse_score_column_time
                                import re
                                scored = []
                                for col, val in raw_cols.items():
                                    v = None
                                    try:
                                        if isinstance(val, (int, float)):
                                            v = float(val)
                                    except (ValueError, TypeError):
                                        pass
                                    if v is None:
                                        text_val = str(val).strip() if val is not None else ""
                                        m = re.search(r'〖(\d+(?:\.\d+)?)〗', text_val)
                                        if m:
                                            v = float(m.group(1))
                                    if v is not None:
                                        sort_key = _parse_score_column_time(col)
                                        scored.append((sort_key, v))
                                if len(scored) >= 2:
                                    scored.sort(key=lambda x: x[0])
                                    latest_val = scored[-1][1]
                                    prev_val = scored[-2][1]
                                    diff = latest_val - prev_val
                                    if diff < -5:
                                        trend_desc = f"，较前次{prev_val}分下降{abs(int(diff))}分"
                                    elif diff < 0:
                                        trend_desc = f"，较前次{prev_val}分略降{abs(int(diff))}分"
                                    elif diff > 5:
                                        trend_desc = f"，较前次{prev_val}分提升{int(diff)}分"
                                    else:
                                        trend_desc = f"，较前次持平"
                        if trend == "下降":
                            risk_points.append(f"成绩{score}分，呈下降趋势{trend_desc}")
                        elif trend == "上升":
                            risk_points.append(f"成绩{score}分，呈上升趋势{trend_desc}")
                        elif score < 60:
                            risk_points.append(f"成绩{score}分，不及格{trend_desc}")
                        elif score < 75:
                            risk_points.append(f"成绩{score}分偏低{trend_desc}")
                        else:
                            risk_points.append(f"成绩{score}分{trend_desc}")

                    # 2. 家长态度
                    if parent == "消极":
                        risk_points.append("家长态度消极")
                    elif parent:
                        signal_texts = [s for s in parent_signals if isinstance(s, str) and s and s not in ("暂无数据", "-")]
                        if signal_texts:
                            risk_points.append(f"家长信号：{'、'.join(signal_texts[:2])}")
                        elif parent != "积极":
                            risk_points.append(f"家长态度：{parent}")

                    # 3. 学生情况（孩子积极与否）
                    if performance:
                        perf_map = {"积极": "学习态度积极", "消极": "学习态度消极", "一般": "学习态度一般"}
                        risk_points.append(perf_map.get(performance, f"学习态度：{performance}"))
                    elif renewal and renewal not in ("自然续费", "已续费", ""):
                        risk_points.append(f"续费状态：{renewal}")

                    # 4. 沟通间隔
                    if comm_gap and comm_gap > 30:
                        if comm_gap > 90:
                            risk_points.append(f"距上次沟通{comm_gap}天，长期失联")
                        else:
                            risk_points.append(f"距上次沟通{comm_gap}天，沟通频率偏低")
                    elif comm_gap is not None:
                        risk_points.append(f"沟通间隔{comm_gap}天")

                    # 有明确信号时取最多4条
                    if risk_points:
                        return "；".join(risk_points[:4])

                    # 无数据时按等级兜底
                    tier = s.get("分层", "P3")
                    if tier == "P4":
                        return "各项数据正常，当前无明确风险"
                    elif tier == "P3":
                        return "存在轻微观察项，整体相对稳定"
                    elif tier == "P2":
                        return "存在需关注的风险信号"
                    else:
                        return "存在明确风险，需优先处理"

                # --- 构建下一步动作建议（精简，结合优先级） ---
                def _build_action_suggestions(s):
                    """基于优先级和数据生成精简沟通建议，不含行课数据"""
                    tier = s.get("分层", "P3")
                    comm_gap = s.get("沟通间隔天数")
                    renewal = s.get("续费意愿", "")
                    trend = s.get("成绩趋势")

                    # 建议沟通时间
                    time_map = {"P1": "今天", "P2": "本周内", "P3": "2周内", "P4": "1月内"}
                    contact_time = time_map.get(tier, "本月内")

                    # 沟通切入点
                    angles = []
                    if comm_gap and comm_gap > 30:
                        angles.append(f"恢复联系（已间隔{comm_gap}天）")
                    if renewal and renewal not in ("自然续费", "已续费", ""):
                        angles.append(f"了解续费意向（状态：{renewal}）")
                    if trend == "下降":
                        angles.append("同步成绩下降情况及改进方案")
                    elif s.get("最近成绩") is not None and s.get("最近成绩") < 75:
                        angles.append("了解学习困难，提供辅导建议")
                    if s.get("家长态度") == "消极":
                        angles.append("化解家长不满情绪")

                    if not angles:
                        if tier in ("P3", "P4"):
                            angles.append("常规学习反馈与关怀")
                        else:
                            angles.append("了解学习近况与家长期望")

                    return [f"⏰ {contact_time}联系 | {angles[0]}"]

                # --- 构建在线表格数据 ---
                tier_display = {"P1": "P1 特别关注", "P2": "P2 重点关注", "P3": "P3 稳定跟进", "P4": "P4 正常维护"}
                table_rows = []
                for idx, s in enumerate(priority_students):
                    tier = s["分层"]
                    actions = _build_action_suggestions(s)
                    table_rows.append({
                        "序号": idx + 1,
                        "姓名": s["学生姓名"],
                        "风险等级": tier_display.get(tier, tier),
                        "风险原因": _build_risk_reason(s),
                        "下一步动作建议": "；".join(actions[:3]),
                    })
                priority_df = pd.DataFrame(table_rows)

                # --- 带颜色标记的在线表格 ---
                def _highlight_tier(val):
                    color_map = {
                        "P1 特别关注": "background-color:#FF4B4B;color:white;font-weight:bold",
                        "P2 重点关注": "background-color:#FFA500;color:white;font-weight:bold",
                        "P3 稳定跟进": "background-color:#FFC000;color:#333;font-weight:bold",
                        "P4 正常维护": "background-color:#70AD47;color:white;font-weight:bold",
                    }
                    return color_map.get(val, "")

                styled_df = priority_df.style.map(_highlight_tier, subset=["风险等级"])
                st.dataframe(
                    styled_df,
                    use_container_width=True,
                    hide_index=True,
                    height=500,
                    column_config={
                        "序号": st.column_config.NumberColumn("序号", width="small"),
                        "姓名": st.column_config.TextColumn("姓名", width="small"),
                        "风险等级": st.column_config.TextColumn("风险等级", width="small"),
                        "风险原因": st.column_config.TextColumn("风险原因", width="large"),
                        "下一步动作建议": st.column_config.TextColumn("下一步动作建议", width="large"),
                    }
                )

                # --- Excel导出 ---
                col_exp1, col_exp2 = st.columns([1, 5])
                with col_exp1:
                    if st.button("📥 导出Excel", key="export_priority", use_container_width=True):
                        export_rows = []
                        for s in priority_students:
                            tier = s["分层"]
                            follow_time = {"P1": "今天", "P2": "本周内", "P3": "2周内", "P4": "1月内"}.get(tier, "本月内")
                            export_rows.append({
                                "姓名": s["学生姓名"],
                                "风险等级": tier_display.get(tier, tier),
                                "风险原因": _build_risk_reason(s),
                                "当前问题": "；".join(s.get("风险触发", [])[:3]) if s.get("风险触发") else "暂无",
                                "下一步动作建议": "；".join(_build_action_suggestions(s)[:3]),
                                "建议跟进时间": follow_time,
                            })
                        export_df = pd.DataFrame(export_rows)
                        export_path = os.path.join(OUTPUT_DIR, f"风险处理清单_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
                            export_df.to_excel(writer, index=False, sheet_name="风险处理清单")
                        with open(export_path, "rb") as f:
                            st.download_button(
                                "📥 下载Excel",
                                data=f,
                                file_name=f"风险处理清单_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                            )

            # ============================================================
            # 模块二：学员个性化服务方案
            # ============================================================
            with st.expander("📋 学员个性化服务方案", expanded=True):
                students = result["students"]

                # 筛选条件（选填，用于个性化策略生成）
                st.markdown("**🎯 筛选条件（选填，用于个性化策略生成）**")
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    script_grade = st.selectbox(
                        "年级/阶段",
                        ["全部",
                         "一年级上", "一年级下", "二年级上", "二年级下", "三年级上", "三年级下",
                         "四年级上", "四年级下", "五年级上", "五年级下", "六年级上", "六年级下",
                         "初一", "初二", "初三", "高一", "高二", "高三"],
                        key="script_grade_filter"
                    )
                with col_f2:
                    script_subject = st.selectbox(
                        "科目",
                        ["全部", "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"],
                        key="script_subject_filter"
                    )
                with col_f3:
                    script_period = st.text_input(
                        "在读周期（选填）",
                        placeholder="如：3个月、半年、1年",
                        key="script_period_filter"
                    )
                st.markdown("---")

                for idx, student in enumerate(students):
                    tier = student["分层"]
                    color = TIER_COLORS.get(tier, "#888")

                    col_info, col_btn = st.columns([5, 1])
                    with col_info:
                        # 紧凑标题：姓名 + 等级 + 风险分 放一行
                        st.markdown(
                            f"**{student['学生姓名']}** "
                            f"<span style='color:{color};font-size:0.85em'>{tier}-{student.get('分层标签', '')}</span> "
                            f"<span style='color:#888;font-size:0.75em'>风险{student['流失风险分']}分</span>",
                            unsafe_allow_html=True
                        )

                        # 风险触发因素（紧凑标签）
                        triggers = student.get("风险触发", [])
                        if triggers:
                            trigger_tags = " ".join([
                                f"<span style='color:{color};font-size:0.65em;padding:0 4px;border:1px solid {color};border-radius:2px;margin-right:2px'>{t}</span>"
                                for t in triggers[:5]
                            ])
                            st.markdown(trigger_tags, unsafe_allow_html=True)

                        # 关键维度展示（一行紧凑）
                        info_items = []
                        for key, label in [
                            ("最近成绩", "成绩"), ("成绩趋势", "趋势"), ("学习表现", "表现"),
                            ("作业完成率", "作业率"), ("听课率", "听课率"),
                            ("家长态度", "家长"), ("续费意愿", "续费"),
                        ]:
                            v = student.get(key)
                            if v is not None and str(v).strip():
                                info_items.append(f"{label}:{v}")
                        if info_items:
                            st.caption(" | ".join(info_items[:7]))

                        # AI风险分析详情
                        with st.expander("🧠 AI风险分析详情", expanded=False):
                            level_desc = student.get("等级说明", "")
                            logic = student.get("判断逻辑", "")
                            evidence = student.get("风险证据", [])
                            actions = student.get("下一步服务动作", [])

                            # 如果所有字段都为空，显示兜底信息
                            if not level_desc and not logic and not evidence and not actions:
                                st.info("该学生AI分析暂未完成或返回异常，建议重新上传学情表重试。")
                            else:
                                if level_desc:
                                    st.markdown(f"**等级说明**: {level_desc}")
                                if logic:
                                    st.markdown(f"**判断逻辑**: {logic}")
                                if evidence:
                                    st.markdown("**风险证据**")
                                    for ev in evidence:
                                        st.markdown(f"- {ev}")
                                if actions:
                                    st.markdown("**下一步动作**")
                                    for action in actions:
                                        st.markdown(f"- {action}")

                    with col_btn:
                        script_key = f"script_{idx}_{student['学生姓名']}"
                        if st.button("✨ 生成方案", key=f"gen_{idx}_{student['学生姓名']}", type="primary", use_container_width=True):
                            with st.spinner(f"正在为 {student['学生姓名']} 生成跟踪服务方案..."):
                                from core.script_generator import generate_student_script_unified
                                script_config = {
                                    "grade": script_grade,
                                    "subject": script_subject,
                                    "study_period": script_period,
                                }
                                script = generate_student_script_unified(student, config=script_config)
                                st.session_state[script_key] = script
                                st.rerun()

                    if script_key in st.session_state:
                        st.markdown(st.session_state[script_key])

            # 导出按钮
            st.subheader("导出结果")
            output_filename = f"学情分析_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            export_analysis_to_excel(result, output_path)
            with open(output_path, "rb") as f:
                st.download_button(
                    "📥 导出学情分析Excel",
                    data=f,
                    file_name=output_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            log_event("export", {"type": "analysis", "file": output_filename})

        except Exception as e:
            st.error(f"处理出错：{e}")

    # ============================================================
    # 🔥 今日风险处理中心（渲染到Tab1顶部占位）
    # 链路：风险识别 → 今日任务生成 → AI优先级排序 → 老师执行 → 结果反馈 → 动态复评
    # ============================================================
    with task_center_slot:
        from core.task_center_ui import render_task_center
        render_task_center()


# ============================================================
# Tab 2: 家校沟通策略助手
# ============================================================
with tab2:
    st.markdown("""
    <style>
    /* 让左右两列展开后高度一致 */
    div[data-testid="column"] > div[data-testid="stVerticalBlock"] {
        height: 100% !important;
    }
    div[data-testid="column"] > div[data-testid="stVerticalBlock"] > div[data-testid="stExpander"] {
        height: 100% !important;
        display: flex !important;
        flex-direction: column !important;
    }
    div[data-testid="column"] > div[data-testid="stVerticalBlock"] > div[data-testid="stExpander"] > div[data-testid="stExpanderDetails"] {
        flex: 1 !important;
        height: auto !important;
        min-height: 280px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #e8eaf6 0%, #f3e5f5 100%);
        padding: 10px 18px;
        border-radius: 6px;
        margin-bottom: 4px;
        margin-top: -25px;
        max-width: 520px;
    ">
        <span style="color: #5c6bc0; font-size: 14px; font-weight: 500;">
            💬 输入家长问题，AI自动判断家长真实诉求 → 明确沟通目标与成功标准 → 提取真实依据与踩雷提醒 → 生成话术 → 预判家长回应 → 记录沟通结果，AI生成跟进计划并到期提醒。
        </span>
    </div>
    """, unsafe_allow_html=True)

    # 学生背景信息 + 快捷场景模板 并列（左窄右宽）
    col_left, col_right = st.columns([1, 1.6])
    with col_left:
        with st.expander("📋 学生背景信息（点击展开）"):
            col_bg1, col_bg2 = st.columns(2)
            with col_bg1:
                comm_type = st.selectbox(
                    "沟通类型",
                    ["", "退费申请", "日常抱怨", "续费沟通", "投诉处理", "其他"],
                    key="qa_comm_type",
                )
                # 选择"其他"时自动显示文本输入框
                if comm_type == "其他":
                    comm_type_other = st.text_input(
                        "请填写沟通类型",
                        key="qa_comm_type_other",
                        placeholder="请输入具体类型"
                    )
            with col_bg2:
                study_duration = st.text_input(
                    "学员在读时间",
                    key="qa_study_duration",
                    placeholder="如：6个月"
                )
            col_bg3, col_bg4 = st.columns(2)
            with col_bg3:
                subject = st.selectbox(
                    "科目",
                    ["", "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理"],
                    key="qa_subject",
                )
            with col_bg4:
                grade = st.selectbox(
                    "在读年级",
                    ["", "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
                     "初一", "初二", "初三", "高一", "高二", "高三"],
                    key="qa_grade",
                )
    with col_right:
        with st.expander("💡 快捷场景模板（点击展开）"):
            scenario_tab1, scenario_tab2, scenario_tab3, scenario_tab4 = st.tabs([
                "成绩与效果", "学习习惯与态度", "续费与投诉", "家长沟通"
            ])
            with scenario_tab1:
                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    if st.button("📉 成绩下降了", key="s1", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子最近考试成绩下降了，请问是什么原因？有什么办法可以提升？"
                with col_s2:
                    if st.button("🎯 考试不理想", key="s3", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子这次考试不太理想，想了解一下具体薄弱环节在哪里？"
                col_s3, col_s4 = st.columns(2)
                with col_s3:
                    if st.button("📝 作业不会做", key="s4", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子回家说作业很多不会做，课堂是不是没听懂？"
                with col_s4:
                    if st.button("📊 效果不明显", key="s6", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子上了一段时间感觉效果不明显，想了解一下原因。"
                col_s5, _ = st.columns(2)
                with col_s5:
                    if st.button("🏆 想冲刺高分", key="s5", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子基础还可以，想冲刺更高分数，有什么建议？"
            with scenario_tab2:
                col_h1, col_h2 = st.columns(2)
                with col_h1:
                    if st.button("😴 上课不专心", key="h1", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子反映上课容易走神，请问课堂上有这种情况吗？"
                with col_h2:
                    if st.button("📱 沉迷手机", key="h2", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子最近沉迷手机游戏，学习状态很差，有什么建议？"
                col_h3, col_h4 = st.columns(2)
                with col_h3:
                    if st.button("⏰ 作业拖拉", key="h3", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子做作业总是拖拉，经常做到很晚，怎么办？"
                with col_h4:
                    if st.button("😰 学习压力大", key="h4", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子最近说学习压力很大，情绪不太好，想了解一下情况。"
                col_h5, _ = st.columns(2)
                with col_h5:
                    if st.button("📚 不爱学习", key="h5", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子对学习提不起兴趣，怎么引导比较好？"
            with scenario_tab3:
                col_x1, col_x2 = st.columns(2)
                with col_x1:
                    if st.button("💰 续费优惠咨询", key="x1", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，课程快到期了，现在续费有什么优惠活动吗？"
                with col_x2:
                    if st.button("🔄 想换老师", key="x2", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子说不太适应现在的老师，可以换班吗？"
                col_x3, col_x4 = st.columns(2)
                with col_x3:
                    if st.button("❌ 想退费", key="x3", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子不想继续上了，想申请退费，流程是怎样的？"
                with col_x4:
                    if st.button("📊 效果不明显", key="x4", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子上了一段时间感觉效果不明显，想了解一下原因。"
                col_x5, _ = st.columns(2)
                with col_x5:
                    if st.button("⏸ 想暂停课程", key="x5", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子最近太忙了，想暂停一段时间课程，可以吗？"
            with scenario_tab4:
                col_j1, col_j2 = st.columns(2)
                with col_j1:
                    if st.button("👋 初次沟通", key="j1", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，孩子刚报名，想了解一下课程安排和学习规划。"
                with col_j2:
                    if st.button("📅 约家长会", key="j2", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，想约个时间跟您详细聊聊孩子的学习情况，您什么时候方便？"
                col_j3, col_j4 = st.columns(2)
                with col_j3:
                    if st.button("🙏 感谢老师", key="j3", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，感谢您这段时间对孩子的悉心教导，孩子进步很大！"
                with col_j4:
                    if st.button("🤝 配合建议", key="j4", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，作为家长我们在家应该怎么配合，才能帮孩子学得更好？"
                col_j5, _ = st.columns(2)
                with col_j5:
                    if st.button("📋 了解学习情况", key="j5", use_container_width=True):
                        st.session_state["qa_input"] = "老师您好，想了解一下孩子最近的学习情况和表现，有什么需要注意的吗？"

    # 图片上传
    uploaded_image = st.file_uploader(
        "📷 上传截图（选填，支持 PNG/JPG/JPEG）",
        type=["png", "jpg", "jpeg"],
        key="qa_image",
        help="上传家长聊天截图，可辅助分析问题"
    )

    question = st.text_area(
        "请输入家长的问题",
        placeholder="例如：孩子最近成绩下降了怎么办？",
        height=60,
        key="qa_input",
        label_visibility="collapsed"
    )

    col1, col2 = st.columns([1, 5])
    with col1:
        generate_btn = st.button("✨ 生成回复", type="primary", use_container_width=True)

    # 结果存入session_state：记录沟通结果等交互触发重跑时，六段式输出不再消失
    if (generate_btn and (question or uploaded_image)) or st.session_state.get("qa_last_result"):
        with st.spinner("正在分析问题并生成回复..."):
            try:
                if generate_btn and (question or uploaded_image):
                    start_time = time.time()
                    from core.qa_responder import generate_qa_response
                    student_context = {}
                    if comm_type:
                        if comm_type == "其他":
                            student_context["沟通类型"] = st.session_state.get("qa_comm_type_other", "其他") or "其他"
                        else:
                            student_context["沟通类型"] = comm_type
                    if study_duration:
                        student_context["在读时间"] = study_duration
                    if subject:
                        student_context["科目"] = subject
                    if grade:
                        student_context["年级"] = grade
                    # 读取截图数据
                    img_data = uploaded_image.getvalue() if uploaded_image else None
                    result = generate_qa_response(
                        question or "",
                        student_context=student_context if student_context else None,
                        image_data=img_data
                    )
                    elapsed = time.time() - start_time
                    st.session_state["qa_last_result"] = result
                    st.session_state["qa_last_context"] = {
                        "question": question or "",
                        "student_context": student_context,
                    }
                    st.success(f"策略生成完成，耗时 {elapsed:.1f} 秒")
                else:
                    # 已有结果（交互控件触发重跑），直接复用，不重复调用AI
                    result = st.session_state["qa_last_result"]

                # ====== 一、问题判断（含AI诉求识别） ======
                with st.expander("🔍 一、问题判断", expanded=True):
                    diag = result.get("问题判断", {})
                    # --- AI诉求识别（情绪/阶段徽章） ---
                    emotion = (diag.get("情绪状态") or "").strip()
                    stage = (diag.get("沟通阶段") or "").strip()
                    if emotion or stage:
                        EMOTION_COLORS = {
                            "焦虑": "#E53935", "质疑": "#F57C00", "犹豫": "#F9A825",
                            "抵触": "#8E24AA", "认可": "#43A047", "平和": "#1E88E5",
                        }
                        STAGE_COLORS = {
                            "效果质疑": "#F57C00", "续费犹豫": "#F9A825", "学习问题": "#1E88E5",
                            "服务问题": "#8E24AA", "初次沟通": "#43A047", "感谢认可": "#43A047",
                        }

                        def _qa_badge(label: str, text: str, colors: dict) -> str:
                            color = next((c for k, c in colors.items() if k in text), "#607D8B")
                            main = text.split("，")[0].split(",")[0].strip()
                            return (f"<span style='background:{color};color:white;padding:2px 10px;"
                                    f"border-radius:10px;font-size:0.82em;font-weight:600;margin-right:6px'>"
                                    f"{label}：{main}</span>")

                        badge_html = ""
                        if emotion:
                            badge_html += _qa_badge("情绪", emotion, EMOTION_COLORS)
                        if stage:
                            badge_html += _qa_badge("沟通阶段", stage, STAGE_COLORS)
                        st.markdown(badge_html, unsafe_allow_html=True)

                    # --- 事实 vs AI分析 ---
                    has_new_fields = diag.get("表层问题") or diag.get("核心诉求")
                    if has_new_fields:
                        c_f, c_a = st.columns(2)
                        with c_f:
                            st.markdown(
                                "<span style='color:#37474F;font-size:0.85em'>🔵 <b>表层问题</b>"
                                "<span style='color:#90A4AE'>（事实 · 家长原话）</span></span>",
                                unsafe_allow_html=True)
                            st.info(diag.get("表层问题", "") or "暂无")
                        with c_a:
                            st.markdown(
                                "<span style='color:#37474F;font-size:0.85em'>🧠 <b>核心诉求</b>"
                                "<span style='color:#90A4AE'>（AI分析 · 真正担心什么）</span></span>",
                                unsafe_allow_html=True)
                            st.warning(diag.get("核心诉求", "") or "暂无")

                    # --- 证据边界三分类：🟢已知事实 / 🔵基于事实的分析 / 🟡待确认信息 ---
                    facts = diag.get("已知事实") or []
                    analyses = diag.get("基于事实的分析") or []
                    pendings = diag.get("待确认信息") or []
                    verify_qs = diag.get("关键核实问题") or []
                    if facts or analyses or pendings:
                        c_f, c_a = st.columns(2)
                        with c_f:
                            st.markdown(
                                "<span style='color:#2E7D32;font-size:0.85em'>🟢 <b>已知事实</b>"
                                "<span style='color:#90A4AE'>（仅限已提供信息，未改写）</span></span>",
                                unsafe_allow_html=True)
                            if facts:
                                for item in facts:
                                    st.markdown(
                                        f"<div style='background:#F1F8E9;border-left:3px solid #43A047;"
                                        f"border-radius:4px;padding:5px 10px;color:#33691E;"
                                        f"font-size:0.85em;margin-bottom:3px'>{item}</div>",
                                        unsafe_allow_html=True)
                            else:
                                st.caption("暂无")
                        with c_a:
                            st.markdown(
                                "<span style='color:#1565C0;font-size:0.85em'>🔵 <b>基于事实的分析</b>"
                                "<span style='color:#90A4AE'>（推测已标注，非事实）</span></span>",
                                unsafe_allow_html=True)
                            if analyses:
                                for item in analyses:
                                    st.markdown(
                                        f"<div style='background:#E3F2FD;border-left:3px solid #1E88E5;"
                                        f"border-radius:4px;padding:5px 10px;color:#0D47A1;"
                                        f"font-size:0.85em;margin-bottom:3px'>{item}</div>",
                                        unsafe_allow_html=True)
                            else:
                                st.caption("暂无")
                        # 🟡待确认信息 + 关键核实问题（全宽，突出提示）
                        if pendings:
                            st.markdown(
                                "<span style='color:#795548;font-size:0.85em'>🟡 <b>待确认信息</b>"
                                "<span style='color:#90A4AE'>（重要但未提供，不猜测）</span></span>",
                                unsafe_allow_html=True)
                            for item in pendings:
                                st.markdown(
                                    f"<div style='background:#FFF8E1;border-left:3px solid #F9A825;"
                                    f"border-radius:4px;padding:5px 10px;color:#795548;"
                                    f"font-size:0.85em;margin-bottom:3px'>{item}</div>",
                                    unsafe_allow_html=True)
                        if verify_qs:
                            qs_html = "　".join(verify_qs)
                            st.markdown(
                                f"<div style='background:#FFFDE7;border:1px dashed #F9A825;"
                                f"border-radius:4px;padding:6px 10px;color:#5D4037;"
                                f"font-size:0.85em'>❓ <b>关键核实问题：</b>{qs_html}</div>",
                                unsafe_allow_html=True)
                    else:
                        # 旧格式回退
                        st.markdown("**学生当前情况**"
                                    "<span style='color:#90A4AE;font-size:0.8em'>（仅基于已提供信息）</span>",
                                    unsafe_allow_html=True)
                        st.info(diag.get("学生当前情况", "") or "暂无")
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**家长核心顾虑**")
                        st.warning(diag.get("家长核心顾虑", "") or "暂无")
                    with cols[1]:
                        st.markdown("**解决重点**")
                        st.success(diag.get("解决重点", "") or "暂无")

                # ====== 二、沟通策略（含成功标准） ======
                with st.expander("🎯 二、沟通策略", expanded=True):
                    strat = result.get("沟通策略", {})
                    st.markdown("**沟通目标**")
                    st.info(strat.get("沟通目标", "") or "暂无")

                    # 本次沟通成功标准（动态生成）
                    success_list = strat.get("本次沟通成功标准") or []
                    if success_list:
                        st.markdown("**✅ 本次沟通成功标准**"
                                    "<span style='color:#90A4AE;font-size:0.8em'>（达成即为成功，可逐项对照）</span>",
                                    unsafe_allow_html=True)
                        for s in success_list:
                            st.markdown(f"☑️ {s}")

                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**最佳切入点**")
                        st.success(strat.get("最佳切入点", "") or "暂无")
                    with cols[1]:
                        st.markdown("**沟通注意事项**")
                        st.warning(strat.get("沟通注意事项", "") or "暂无")

                # ====== 三、沟通依据与踩雷提醒 ======
                evidence = result.get("沟通依据", {})
                if evidence.get("真实依据") or evidence.get("注意避免"):
                    with st.expander("📌 三、沟通依据与踩雷提醒", expanded=True):
                        c_ev, c_av = st.columns(2)
                        with c_ev:
                            st.markdown("**📌 可使用的真实依据**"
                                        "<span style='color:#90A4AE;font-size:0.8em'>（仅限已提供信息）</span>",
                                        unsafe_allow_html=True)
                            for item in evidence.get("真实依据", []):
                                is_missing = ("缺少" in item or "暂无" in item)
                                if is_missing:
                                    st.markdown(f"<div style='background:#FAFAFA;border:1px dashed #BDBDBD;"
                                                f"border-radius:4px;padding:6px 10px;color:#9E9E9E;"
                                                f"font-size:0.85em;margin-bottom:4px'>🚫 {item}</div>",
                                                unsafe_allow_html=True)
                                else:
                                    st.markdown(f"<div style='background:#F1F8E9;border-left:3px solid #43A047;"
                                                f"border-radius:4px;padding:6px 10px;color:#33691E;"
                                                f"font-size:0.85em;margin-bottom:4px'>✅ {item}</div>",
                                                unsafe_allow_html=True)
                        with c_av:
                            st.markdown("**⚠️ 本次沟通注意避免**")
                            for item in evidence.get("注意避免", []):
                                st.markdown(f"<div style='background:#FFEBEE;border-left:3px solid #E53935;"
                                            f"border-radius:4px;padding:6px 10px;color:#B71C1C;"
                                            f"font-size:0.85em;margin-bottom:4px'>❌ {item}</div>",
                                            unsafe_allow_html=True)

                # ====== 四、家长沟通话术 ======
                with st.expander("💬 四、家长沟通话术", expanded=True):
                    script_text = result.get("话术", "")
                    st.text_area(
                        "话术（可编辑后复制）",
                        value=script_text,
                        height=300,
                        key="qa_response_output",
                        label_visibility="collapsed"
                    )

                # ====== 五、家长回应分支 ======
                branches = result.get("回应分支", [])
                if branches:
                    with st.expander(f"🔄 五、如果家长这样回应（预判{len(branches)}种方向）", expanded=False):
                        BRANCH_COLORS = ["#43A047", "#F9A825", "#E53935", "#1E88E5"]
                        BRANCH_ICONS = ["🟢", "🟡", "🔴", "🔵"]
                        for i, b in enumerate(branches):
                            color = BRANCH_COLORS[i % len(BRANCH_COLORS)]
                            icon = BRANCH_ICONS[i % len(BRANCH_ICONS)]
                            title = b.get("标题", f"情况{chr(65 + i)}")
                            st.markdown(
                                f"<span style='background:{color};color:white;padding:2px 12px;"
                                f"border-radius:10px;font-size:0.85em;font-weight:600'>{icon} {title}</span>",
                                unsafe_allow_html=True)
                            bc1, bc2 = st.columns(2)
                            with bc1:
                                st.markdown("**家长可能回应**")
                                st.markdown(f"<div style='background:#F5F5F5;border-radius:4px;"
                                            f"padding:8px 12px;color:#455A64;font-size:0.88em;"
                                            f"font-style:italic'>💬 {b.get('家长可能回应', '-')}</div>",
                                            unsafe_allow_html=True)
                            with bc2:
                                st.markdown("**老师推荐回应**")
                                st.markdown(f"<div style='background:#E3F2FD;border-left:3px solid #1E88E5;"
                                            f"border-radius:4px;padding:8px 12px;color:#0D47A1;"
                                            f"font-size:0.88em'>👨‍🏫 {b.get('老师推荐回应', '-')}</div>",
                                            unsafe_allow_html=True)
                            st.caption(f"🎯 沟通目的：{b.get('沟通目的', '-')}")
                            if i < len(branches) - 1:
                                st.markdown("<div style='border-top:1px dashed #E0E0E0;margin:8px 0'></div>",
                                            unsafe_allow_html=True)

                # ====== 六、行动方案 ======
                with st.expander("📋 六、行动方案", expanded=False):
                    actions = result.get("行动方案", {})
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**👨‍🏫 老师下一步**")
                        st.info(actions.get("老师下一步", "") or "暂无")
                        st.markdown("**👦 学生下一步**")
                        st.info(actions.get("学生下一步", "") or "暂无")
                    with cols[1]:
                        st.markdown("**👨‍👩‍👧 家长配合**")
                        st.info(actions.get("家长配合", "") or "暂无")
                        st.markdown("**📅 后续跟踪时间**")
                        st.success(actions.get("后续跟踪时间", "") or "暂无")

                # ====== 七、记录本次沟通结果 & 跟进计划（沟通跟进中心入口） ======
                try:
                    from core.followup_engine import (
                        COMM_RESULTS, generate_followup_plan, FollowupStore,
                        new_task, build_analysis_summary, now_cn,
                    )
                    _last_ctx = st.session_state.get("qa_last_context", {}) or {}
                    _fu_question = _last_ctx.get("question") or (question or "")
                    with st.expander("📝 七、记录本次沟通结果 & 跟进计划", expanded=False):
                        st.caption("沟通完成后记录结果，AI自动生成跟进计划并加入下方「我的跟进」，到期不再靠脑子记。")
                        c_r1, c_r2 = st.columns(2)
                        with c_r1:
                            fu_name = st.text_input(
                                "学员姓名", key="fu_student_name",
                                placeholder="用于跟进中心显示（必填）")
                        with c_r2:
                            fu_result = st.selectbox(
                                "本次沟通结果", COMM_RESULTS, key="fu_comm_result")
                        fu_note = st.text_area(
                            "备注（选填）", key="fu_note", height=60,
                            placeholder="如：家长担心数学跟不上，约定周五晚8点电话；或记录拒绝原因")
                        if st.button("✨ AI生成跟进计划", key="fu_gen_plan", type="primary"):
                            if not fu_name.strip():
                                st.warning("请先填写学员姓名")
                            else:
                                diag = result.get("问题判断", {}) or {}
                                _summary = build_analysis_summary(result)
                                with st.spinner("正在生成跟进计划..."):
                                    _plan = generate_followup_plan(
                                        fu_name.strip(), _fu_question, _summary,
                                        (diag.get("沟通阶段") or "").strip(),
                                        fu_result, fu_note)
                                st.session_state["fu_pending_plan"] = {
                                    "plan": _plan, "name": fu_name.strip(),
                                    "question": _fu_question, "result": fu_result,
                                    "note": fu_note, "stage": (diag.get("沟通阶段") or "").strip(),
                                    "summary": _summary,
                                }
                        _pending = st.session_state.get("fu_pending_plan")
                        if _pending:
                            _p = _pending["plan"]
                            _PRIO_COLOR = {"高": "#E53935", "中": "#F57C00", "低": "#43A047"}
                            st.markdown(
                                f"<div style='background:#F1F8E9;border:1px solid #AED581;border-radius:6px;"
                                f"padding:10px 14px;margin:8px 0'>"
                                f"<div style='font-size:0.95em;color:#33691E'><b>📅 建议跟进时间：{_p['followup_at'].strftime('%Y-%m-%d %H:%M')}</b>"
                                f"　<span style='background:{_PRIO_COLOR.get(_p['priority'], '#607D8B')};color:white;"
                                f"padding:1px 10px;border-radius:10px;font-size:0.8em'>优先级 {_p['priority']}</span></div>"
                                f"<div style='color:#37474F;font-size:0.88em;margin-top:5px'>🎯 <b>本次跟进目标：</b>{_p['goal']}</div>"
                                f"<div style='color:#37474F;font-size:0.88em'>👀 <b>下一次重点关注：</b>{_p['focus']}</div>"
                                f"<div style='color:#37474F;font-size:0.88em'>⚠️ <b>跟进提醒：</b>{_p['reminder']}</div>"
                                f"<div style='color:#78909C;font-size:0.8em;margin-top:4px'>⏱️ 时间依据：{_p['time_basis']}"
                                + ("（规则兜底，可手动调整）" if _p.get("source") == "rule" else "")
                                + "</div></div>", unsafe_allow_html=True)
                            c_add, _ = st.columns([1, 2])
                            with c_add:
                                if st.button("➕ 加入跟进中心", key="fu_add_task", type="primary"):
                                    try:
                                        _store = FollowupStore()
                                        _task = new_task(
                                            _pending["name"], _pending["question"], _p,
                                            _pending["result"], _pending["note"],
                                            _pending["stage"], _pending["summary"])
                                        _store.add(_task)
                                        st.session_state["fu_pending_plan"] = None
                                        st.success("✅ 已加入跟进中心，可在下方「📋 我的跟进」查看")
                                    except Exception as ex:
                                        st.error(f"加入跟进中心失败：{ex}")
                            if st.button("🗑️ 放弃该计划", key="fu_drop_plan"):
                                st.session_state["fu_pending_plan"] = None
                                st.rerun()
                except Exception as _fu_ex:
                    st.error(f"跟进计划生成异常：{_fu_ex}")

            except Exception as e:
                st.error(f"生成失败：{e}")
    elif generate_btn and not question and not uploaded_image:
        st.warning("请先输入家长问题或上传截图")

    # 历史记录
    if "qa_history" in st.session_state and st.session_state["qa_history"]:
        st.markdown("---")
        st.subheader("📜 本次会话历史")
        for i, item in enumerate(reversed(st.session_state["qa_history"][-5:])):
            with st.expander(f"Q: {item['question'][:50]}..."):
                st.markdown(f"**分类**: {item['classification'].get('category', '未知')}")
                st.markdown(f"**回复**: {item['response']}")

    # ============================================================
    # 沟通跟进中心（围绕Tab2沟通场景的持续跟进，与Tab1风险中心独立）
    # ============================================================
    try:
        import json as _json
        from datetime import timedelta as _td
        from core.followup_engine import (
            COMM_RESULTS, generate_followup_plan, FollowupStore,
            new_task, group_tasks, task_display_status, parse_task_time, now_cn,
        )

        _fu_store = FollowupStore()
        _fu_all = _fu_store.load()
        _fu_groups = group_tasks(_fu_all)
        _n_today = len(_fu_groups["today"])
        _n_up = len(_fu_groups["upcoming"])
        _n_done = len(_fu_groups["done"])
        _n_overdue = sum(1 for t in _fu_groups["today"] if task_display_status(t) == "已超时")

        def _render_fu_task(t: dict, done: bool = False):
            """渲染单条跟进任务卡片：学员｜问题｜时间｜优先级｜目标｜状态 + 操作"""
            tid = t["id"]
            name = t.get("student_name", "?")
            q_short = (t.get("question") or "")[:18] or "（无问题记录）"
            fu_dt = t.get("followup_at", "")
            prio = t.get("priority", "中")
            status = task_display_status(t)
            _PRIO_BG = {"高": "#E53935", "中": "#F57C00", "低": "#43A047"}
            _STATUS_BG = {"待跟进": "#1E88E5", "已超时": "#E53935", "已完成": "#607D8B"}
            icon = "⏰" if status == "已超时" else ("✅" if done else "📌")
            with st.expander(f"{icon} {name} ｜ {q_short} ｜ {fu_dt}"):
                st.markdown(
                    f"<div style='background:#FAFAFA;border:1px solid #E0E0E0;border-radius:6px;"
                    f"padding:8px 12px;margin-bottom:8px'>"
                    f"<span style='background:{_PRIO_BG.get(prio, '#607D8B')};color:white;padding:1px 10px;"
                    f"border-radius:10px;font-size:0.8em'>优先级 {prio}</span> "
                    f"<span style='background:{_STATUS_BG.get(status, '#607D8B')};color:white;padding:1px 10px;"
                    f"border-radius:10px;font-size:0.8em'>{status}</span> "
                    f"<span style='color:#90A4AE;font-size:0.8em'>沟通结果：{t.get('comm_result', '')}"
                    f"｜创建于 {t.get('created_at', '')}</span>"
                    f"<div style='color:#37474F;font-size:0.88em;margin-top:6px'>🎯 <b>跟进目标：</b>{t.get('goal', '')}</div>"
                    f"<div style='color:#37474F;font-size:0.88em'>👀 <b>重点关注：</b>{t.get('focus', '')}</div>"
                    f"<div style='color:#37474F;font-size:0.88em'>⚠️ <b>跟进提醒：</b>{t.get('reminder', '')}</div>"
                    f"</div>", unsafe_allow_html=True)
                if t.get("time_basis"):
                    _src = "（规则兜底）" if t.get("plan_source") == "rule" else ""
                    st.caption(f"⏱️ 时间依据：{t['time_basis']}{_src}")
                hist = t.get("history") or []
                if hist:
                    st.markdown("**📜 沟通记录**")
                    for h in hist[-5:]:
                        st.markdown(
                            f"<div style='border-left:2px solid #B0BEC5;padding:2px 8px;"
                            f"color:#546E7A;font-size:0.82em;margin-bottom:2px'>"
                            f"[{h.get('time', '')}] {h.get('result', '')}　{h.get('note', '')}</div>",
                            unsafe_allow_html=True)
                if t.get("delayed_count"):
                    st.caption(f"已延后 {t['delayed_count']} 次")

                if done:
                    c_del, _ = st.columns([1, 3])
                    with c_del:
                        if st.button("🗑️ 删除记录", key=f"{tid}_del", use_container_width=True):
                            _fu_store.delete(tid)
                            st.rerun()
                    return

                c1, c2, c3 = st.columns([1, 1.4, 1])
                with c1:
                    if st.button("✅ 标记完成", key=f"{tid}_done", use_container_width=True):
                        _fu_store.complete(tid)
                        st.rerun()
                with c2:
                    _cur_dt = parse_task_time(t)
                    _d = st.date_input("延后至", value=_cur_dt.date() + _td(days=1),
                                       key=f"{tid}_ddate", label_visibility="collapsed")
                    if st.button("⏰ 确认延后", key=f"{tid}_delay", use_container_width=True):
                        _new_dt = datetime.combine(_d, _cur_dt.time())
                        _fu_store.delay(tid, _new_dt)
                        st.rerun()
                with c3:
                    if st.button("🗑️ 删除", key=f"{tid}_del2", use_container_width=True):
                        _fu_store.delete(tid)
                        st.rerun()

                # 循环跟进：完成当前任务并生成下一次跟进
                with st.expander("🔄 记录跟进结果 & 生成下一次跟进"):
                    nres = st.selectbox("本次沟通结果", COMM_RESULTS, key=f"{tid}_nres")
                    nnote = st.text_area("备注（选填）", key=f"{tid}_nnote", height=60)
                    if st.button("✨ 生成跟进计划", key=f"{tid}_ngen"):
                        with st.spinner("正在生成跟进计划..."):
                            nplan = generate_followup_plan(
                                name, t.get("question", ""), t.get("analysis_summary", ""),
                                t.get("stage", ""), nres, nnote)
                        st.session_state[f"{tid}_nplan"] = {"plan": nplan, "result": nres, "note": nnote}
                    _np = st.session_state.get(f"{tid}_nplan")
                    if _np:
                        _np_plan = _np["plan"]
                        _PC = {"高": "#E53935", "中": "#F57C00", "低": "#43A047"}
                        st.markdown(
                            f"<div style='background:#F1F8E9;border:1px solid #AED581;border-radius:6px;"
                            f"padding:10px 14px;margin:8px 0'>"
                            f"<div style='font-size:0.95em;color:#33691E'><b>📅 下次跟进：{_np_plan['followup_at'].strftime('%Y-%m-%d %H:%M')}</b>"
                            f"　<span style='background:{_PC.get(_np_plan['priority'], '#607D8B')};color:white;"
                            f"padding:1px 10px;border-radius:10px;font-size:0.8em'>优先级 {_np_plan['priority']}</span></div>"
                            f"<div style='color:#37474F;font-size:0.88em;margin-top:5px'>🎯 <b>跟进目标：</b>{_np_plan['goal']}</div>"
                            f"<div style='color:#37474F;font-size:0.88em'>👀 <b>重点关注：</b>{_np_plan['focus']}</div>"
                            f"<div style='color:#37474F;font-size:0.88em'>⚠️ <b>跟进提醒：</b>{_np_plan['reminder']}</div>"
                            f"</div>", unsafe_allow_html=True)
                        if st.button("➕ 完成当前任务并加入新跟进", key=f"{tid}_nadd", type="primary"):
                            _rec = {"time": now_cn().strftime("%Y-%m-%d %H:%M"),
                                    "result": _np["result"], "note": _np["note"] or "（无备注）"}
                            _new_task = new_task(
                                name, t.get("question", ""), _np_plan, _np["result"],
                                _np["note"], t.get("stage", ""), t.get("analysis_summary", ""))
                            _fu_store.complete(tid, _rec)
                            _fu_store.add(_new_task)
                            st.session_state[f"{tid}_nplan"] = None
                            st.rerun()

        _fu_title = f"📋 我的跟进（今日待跟进 {_n_today} · 即将 {_n_up} · 已完成 {_n_done}）"
        if _n_overdue:
            _fu_title += f" ⚠️ {_n_overdue} 条已超时"
        with st.expander(_fu_title, expanded=_n_overdue > 0):
            if not _fu_all:
                st.caption("暂无跟进任务。在上方生成沟通策略后，于「七、记录本次沟通结果」中记录结果即可自动创建跟进任务。")
            else:
                _ft1, _ft2, _ft3 = st.tabs([
                    f"🔴 今日待跟进（{_n_today}）",
                    f"🟡 即将跟进（{_n_up}）",
                    f"🔵 已完成（{_n_done}）",
                ])
                with _ft1:
                    if not _fu_groups["today"]:
                        st.caption("今天没有待跟进任务 🎉")
                    for _t in _fu_groups["today"]:
                        _render_fu_task(_t)
                with _ft2:
                    if not _fu_groups["upcoming"]:
                        st.caption("暂无即将跟进的任务")
                    for _t in _fu_groups["upcoming"]:
                        _render_fu_task(_t)
                with _ft3:
                    if not _fu_groups["done"]:
                        st.caption("暂无已完成记录")
                    for _t in _fu_groups["done"][:20]:
                        _render_fu_task(_t, done=True)
                    if len(_fu_groups["done"]) > 20:
                        st.caption(f"仅显示最近20条，共 {len(_fu_groups['done'])} 条")
            # 备份/恢复（云端重新部署后数据会清空，导入备份可恢复）
            with st.expander("⚙️ 备份 / 恢复"):
                st.caption("云端应用重新部署后跟进数据会清空，建议定期导出备份。")
                st.download_button(
                    "📤 导出全部跟进数据",
                    data=_fu_store.export_data(),
                    file_name=f"跟进备份_{now_cn().strftime('%Y%m%d_%H%M')}.json",
                    mime="application/json", key="fu_export")
                _fu_up = st.file_uploader("📥 导入备份JSON（按任务ID去重合并）", type=["json"], key="fu_import")
                if _fu_up is not None:
                    try:
                        _imported = _json.loads(_fu_up.getvalue().decode("utf-8"))
                        _added = _fu_store.import_merge(_imported if isinstance(_imported, list) else [])
                        if _added:
                            st.success(f"导入完成，新增 {_added} 条（重复任务自动跳过）")
                            st.rerun()
                        else:
                            st.info("导入完成，没有新增任务（全部为重复任务）")
                    except Exception as _imp_ex:
                        st.error(f"导入失败：{_imp_ex}")
    except Exception as _fu_center_ex:
        st.error(f"跟进中心加载异常：{_fu_center_ex}")

    with st.expander("💡 支持的问题类型"):
        st.markdown("""
        - **教学类**：课程内容、教学方法、考试安排、成绩分析
        - **服务类**：排课、请假、教材、上课时间、校区服务
        - **续费类**：续费优惠、课程套餐、退费政策
        - **投诉类**：教学质量、老师态度、服务不满
        """)


# ============================================================
# Tab 3: AI学情风险洞察中心（渲染辅助函数）
# ============================================================
_CIRCLED_NUM = "①②③④⑤⑥⑦⑧⑨⑩"


def _esc_html(s) -> str:
    """HTML转义（AI输出内容插入HTML卡片前必须转义）"""
    import html as _h
    return _h.escape(str(s))


def _conclusion_color(symbol: str) -> str:
    """趋势结论颜色"""
    if symbol == "↘":
        return "#C62828"
    if symbol == "↗":
        return "#2E7D32"
    if symbol == "⚠️":
        return "#E65100"
    return "#607D8B"


def _priority_color(priority: str) -> str:
    """P1-P4优先级颜色"""
    if "P1" in str(priority):
        return "#C62828"
    if "P2" in str(priority):
        return "#E65100"
    if "P3" in str(priority):
        return "#F9A825"
    return "#2E7D32"


def _risk_type_color(risk_type: str) -> str:
    """风险类型颜色"""
    return {
        "参与度风险": "#C62828",
        "练习执行风险": "#E65100",
        "学习效果风险": "#F9A825",
        "趋势变化风险": "#1565C0",
        "数据异常/待确认": "#757575",
    }.get(str(risk_type), "#2E7D32")


def _trend_short(trend: dict) -> str:
    """趋势短标签（TOP10卡片/明细表用），基于规则层真实判断结果"""
    if not trend:
        return "？数据不足"
    s = trend.get("summary_symbol", "？")
    if len(trend.get("declining", [])) >= 2:
        return f"{s} 多维下降"
    if trend.get("patterns", {}).get("持续下降"):
        return f"{s} 持续下降"
    if trend.get("declining"):
        return f"{s} 下降"
    if trend.get("volatile"):
        return f"{s} 波动"
    if s == "？":
        return "？数据不足"
    if s == "↗":
        return f"{s} 稳定回升"
    return f"{s} 整体稳定"


# ============================================================
# Tab 3: 风险优先处理中心
# ============================================================
with tab3:
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #e8eaf6 0%, #f3e5f5 100%);
        padding: 10px 18px;
        border-radius: 6px;
        margin-bottom: 4px;
        max-width: 640px;
    ">
        <span style="color: #5c6bc0; font-size: 14px; font-weight: 500;">
            📋 风险优先处理中心：上传行课Excel → 风险分析与P1-P4排序 → AI解释风险原因 → 跟进建议 → 生成沟通方案 → 记录跟进结果 → AI判断下一步 → 最新数据重新评估（闭环）
        </span>
    </div>
    """, unsafe_allow_html=True)

    uploaded_file3 = st.file_uploader(
        "上传行课数据",
        type=["xlsx", "xls"],
        key="lecture_upload",
        help="支持任意列名的Excel文件，系统会自动识别讲次列和姓名列"
    )

    if uploaded_file3:
        try:
            df = parse_uploaded_excel(uploaded_file3)

            # 智能检测姓名列
            from core.column_classifier import classify_columns
            classification = classify_columns(df)
            try:
                name_col = detect_name_column(df, classification)
            except ValueError as e:
                st.error(f"姓名列检测失败：{e}")
                st.stop()

            # 检测ID列
            id_col = None
            for col in df.columns:
                col_str = str(col)
                if ("ID" in col_str or "id" in col_str or "编号" in col_str or "学号" in col_str) and col != name_col:
                    id_col = col
                    break

            # 解析讲次列
            from core.lecture_parser import parse_lecture_columns, calc_lecture_attendance_rate
            lectures = parse_lecture_columns(list(df.columns))
            attendance_rates = calc_lecture_attendance_rate(df, lectures)

            # 过滤：只保留全班有效听课率 >= 10% 的讲次（正课），排除家长会/复习课等
            active_lectures = [l for l in lectures if attendance_rates.get(l["lecture"], 0) >= 0.1]
            skipped = len(lectures) - len(active_lectures)

            # 诊断：展示解析出的讲次结构
            with st.expander("🔧 诊断：讲次解析结果", expanded=False):
                st.write(f"**总列数**: {len(df.columns)} | **全部讲次**: {len(lectures)} | **有效正课**: {len(active_lectures)} | **已跳过**: {skipped}")
                st.write("**出勤率**: " + ", ".join([f"{l['lecture']}={attendance_rates.get(l['lecture'],0):.0%}" for l in lectures]))
                for lec in lectures[:3]:
                    st.write(f"  {lec['lecture']} → cols={list(lec['cols'].keys())}")
                st.write("**前2行原始数据**")
                st.dataframe(df.head(2), use_container_width=True)

            # 后续全部使用 active_lectures（仅正课）
            lectures = active_lectures

            if lectures:
                st.markdown(
                    f"<div style='font-size:12px;color:#4a5568;padding:2px 0;'>📐 已识别 {len(lectures)} 个讲次：{', '.join([l['lecture'] for l in lectures[:5]])}{'...' if len(lectures) > 5 else ''}</div>",
                    unsafe_allow_html=True
                )
            else:
                st.warning("⚠️ 未识别到讲次列，将使用基础分析模式")

            # 文件变更时清空风险洞察缓存（结果/洞察/AI分析/报告）
            _file_identity3 = uploaded_file3.name + str(len(df))
            if st.session_state.get("lec_risk_file_identity") != _file_identity3:
                for _k in list(st.session_state.keys()):
                    if _k.startswith("lec_risk_") or _k.startswith("lec_rpt_") or _k == "lec_detail_sel":
                        st.session_state.pop(_k, None)
                st.session_state["lec_risk_file_identity"] = _file_identity3

            # 模式切换
            report_mode = st.radio(
                "选择功能",
                ["⚠️ 风险分析&沟通优先级", "📄 批量报告生成"],
                horizontal=True,
                key="lecture_report_mode"
            )

            # ===== 风险优先处理中心（风险分析&跟进闭环）=====
            if report_mode == "⚠️ 风险分析&沟通优先级":
                st.markdown("**⚠️ 风险优先处理中心**")
                st.caption(f"基于5维指标（有效听课·听课时长·答题正确率·练习提交·练习得分）对 {len(df)} 名学员进行风险排序 → AI解释原因 → 跟进建议 → 沟通方案 → 跟进记录 → 重新评估")

                # ---- 第0步：数据质量校验（上传后自动，先于风险分析）----
                from core.risk_insight_engine import validate_data_quality, build_all_insights
                quality = validate_data_quality(df, lectures, name_col)

                if quality["errors"]:
                    for _err in quality["errors"]:
                        st.error(f"⛔ {_err}，请检查Excel后重新上传")
                else:
                    _n_warn = len(quality["warnings"])
                    with st.expander(f"🧪 数据质量校验（{_n_warn}项提示）", expanded=False):
                        st.table(pd.DataFrame([
                            {"维度": _d, "讲次覆盖率": f"{_v['lecture_coverage']:.0%}",
                             "无数据学员": f"{_v['missing_students']}/{quality['student_count']}",
                             "参与判断": "✅ 是" if _v["usable"] else "⚠️ 否（数据不足）"}
                            for _d, _v in quality["dims"].items()
                        ]))
                        if _n_warn:
                            for _w in quality["warnings"]:
                                st.markdown(f"⚠️ {_w}")
                        else:
                            st.markdown("✅ 5维指标数据完整，全部参与风险判断。")

                if not quality["errors"]:
                    if st.button("🔍 开始风险分析", type="primary", use_container_width=True):
                        from core.lecture_risk_analyzer import batch_analyze_risk, export_risk_excel

                        progress_text = st.empty()
                        progress_bar = st.progress(0)
                        start_time = time.time()

                        with st.spinner("正在进行5维风险分析与P1-P4排序..."):
                            results = batch_analyze_risk(
                                df, lectures, attendance_rates,
                                name_col=name_col, id_col=id_col,
                                progress_callback=lambda cur, total: progress_bar.progress(cur / total)
                            )
                        progress_text.text("正在生成风险洞察（规则层：风险类型·近期趋势·问题讲次，零AI调用）...")
                        insights = build_all_insights(results, lectures)
                        elapsed = time.time() - start_time
                        progress_text.text(f"✅ 风险分析完成！{len(results)} 名学员，耗时 {elapsed:.1f} 秒")

                        # 数据回流入口：记录风险快照（重新分析时自动对比风险变化，更新跟进状态）
                        try:
                            from core.risk_followup_center import RiskFollowupStore
                            RiskFollowupStore().snapshot_risk(results)
                        except Exception as _snap_ex:
                            print(f"[RiskCenter] 风险快照记录失败(不影响分析): {_snap_ex}")

                        # 预生成导出Excel
                        output_filename = f"风险分析_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                        output_path = os.path.join(OUTPUT_DIR, output_filename)
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        export_risk_excel(results, lectures, attendance_rates, output_path, df)

                        st.session_state["lec_risk_results"] = results
                        st.session_state["lec_risk_insights"] = insights
                        st.session_state["lec_risk_quality"] = quality
                        st.session_state["lec_risk_elapsed"] = elapsed
                        st.session_state["lec_risk_export_path"] = output_path
                        st.session_state["lec_risk_export_filename"] = output_filename
                        st.session_state.pop("lec_risk_ai_insights", None)
                        st.session_state.pop("lec_rpt_content", None)
                        st.session_state.pop("lec_rpt_content_name", None)
                        st.session_state.pop("lec_detail_sel", None)
                        st.session_state.pop("lec_rpt_student", None)
                        log_event("analysis_end", {"student_count": len(df), "duration_s": round(elapsed, 2)})
                        st.rerun()

                results = st.session_state.get("lec_risk_results")
                insights = st.session_state.get("lec_risk_insights") or []

                if not results:
                    st.info("👆 点击「开始风险分析」，系统将自动完成：数据质量校验 → 5维风险分析 → P1-P4排序 → 风险类型分类 → 近期趋势判断 → 问题讲次定位 → AI风险洞察 → 学情风险报告")
                else:
                    elapsed = st.session_state.get("lec_risk_elapsed", 0)
                    insight_map = {i["name"]: i for i in insights}
                    result_map = {r["学员姓名"]: r for r in results}

                    # ===== 跟进闭环状态加载（规则层，零LLM）=====
                    from core.risk_followup_center import (
                        RiskFollowupStore, compute_funnel, build_task_list,
                        STATUS_META, status_display, default_status_for, STATUS_ORDER,
                        STATUS_PENDING, suggest_next_action, rule_followup_judgment,
                        risk_change_label, FU_METHODS, FU_RESULTS,
                    )
                    _rfu_store = RiskFollowupStore()
                    _rfu_states = _rfu_store.load()

                    # ===== 0. 🔁 今日风险处理（闭环进度漏斗）=====
                    st.subheader("🔁 今日风险处理")
                    _funnel = compute_funnel(results, _rfu_states)
                    _funnel_items = [
                        ("待联系", _funnel["待联系"], "#C62828"),
                        ("已联系·待观察", _funnel["已联系·待观察"], "#F9A825"),
                        ("已完成跟进", _funnel["已完成跟进"], "#2E7D32"),
                        ("风险缓解", _funnel["风险缓解"], "#1565C0"),
                    ]
                    _fbox = []
                    for _fi, (_fl, _fc, _fcol) in enumerate(_funnel_items):
                        if _fi:
                            _fbox.append('<div style="color:#90A4AE;font-size:16px;align-self:center;">→</div>')
                        _fbox.append(
                            '<div style="flex:1;min-width:110px;border:1px solid #e8eaf0;border-radius:6px;'
                            'padding:6px 10px;text-align:center;background:#ffffff;">'
                            f'<div style="font-size:22px;font-weight:700;color:{_fcol};">{_fc}</div>'
                            f'<div style="font-size:12px;color:#555;">{_fl}</div></div>')
                    st.markdown('<div style="display:flex;gap:8px;align-items:stretch;flex-wrap:wrap;">'
                                + "".join(_fbox) + '</div>', unsafe_allow_html=True)
                    st.caption("闭环：AI发现风险 → 跟进建议 → 生成沟通方案 → 老师联系 → 记录结果 → AI判断下一步 → 最新数据重新评估 → TOP10与状态自动更新")

                    # ===== 0.5. 📌 今日待处理 =====
                    _rfu_tasks = build_task_list(results, insights, _rfu_states)
                    if _rfu_tasks:
                        with st.container(border=True):
                            st.markdown(f"**📌 今日待处理（{_rfu_tasks.__len__()}项）**　"
                                        "<span style='color:#888;font-size:12px;'>按紧急度排序，点击学员进入风险处理卡</span>")
                            _task_cols = st.columns(2)
                            for _ti, _tk in enumerate(_rfu_tasks):
                                with _task_cols[_ti % 2]:
                                    if st.button(f"{_tk['name']}｜{_tk['tag']}",
                                                 key=f"rfu_task_{_ti}", use_container_width=True):
                                        st.session_state["lec_detail_sel"] = _tk["name"]
                                        st.rerun()
                    else:
                        st.success("今日暂无待处理风险任务，继续保持。")

                    # ===== 1. 📊 数据分析概览 =====
                    st.subheader("📊 数据分析概览")
                    st.caption(f"✅ 分析完成：{len(results)} 名学员 · {len(lectures)} 个讲次 · 耗时 {elapsed:.1f} 秒（P1-P4由系统规则判定，AI仅解释不修改）")

                    _qual = st.session_state.get("lec_risk_quality") or {}
                    if _qual.get("warnings"):
                        st.warning("⚠️ **数据质量提示（相关维度结论需谨慎参考）**\n\n" + "\n".join(f"- {_w}" for _w in _qual["warnings"]))

                    # 诊断：展示前3名学员的原始指标
                    with st.expander("🔧 诊断：风险分析原始数据", expanded=False):
                        for r in results[:3]:
                            rd = r.get("_risk_detail", {})
                            m = rd.get("metrics", {})
                            st.write(f"**{r['学员姓名']}** | 优先级={r['优先级']} | 风险分={r['风险分']}")
                            st.write(f"  有效听课 total={m.get('有效听课',{}).get('total',0)} count={m.get('有效听课',{}).get('count',0)} rate={m.get('有效听课',{}).get('rate',0):.2f}")
                            st.write(f"  听课时长 values={m.get('听课时长',{}).get('values',[])}")
                            st.write(f"  答题正确率 values={m.get('答题正确率',{}).get('values',[])}")
                            st.write(f"  练习提交 total={m.get('练习提交',{}).get('total',0)} count={m.get('练习提交',{}).get('count',0)}")
                            st.write(f"  练习得分 values={m.get('练习得分',{}).get('values',[])}")
                            anom = rd.get("anomalies", {})
                            st.write(f"  异常: 无效听课={len(anom.get('无效听课',[]))}, 未提交练习={len(anom.get('未提交练习',[]))}, 答题低于70={len(anom.get('答题低于70',[]))}, 练习低于70={len(anom.get('练习低于70',[]))}")

                    p1 = sum(1 for r in results if "P1" in r.get("优先级", ""))
                    p2 = sum(1 for r in results if "P2" in r.get("优先级", ""))
                    p3 = sum(1 for r in results if "P3" in r.get("优先级", ""))
                    p4 = sum(1 for r in results if "P4" in r.get("优先级", ""))

                    col1, col2, col3, col4, col5 = st.columns(5)
                    col1.metric("🔴 P1-紧急", p1)
                    col2.metric("🟠 P2-高", p2)
                    col3.metric("🟡 P3-中", p3)
                    col4.metric("🟢 P4-低", p4)
                    col5.metric("总计", len(results))

                    # ===== 2. 🔥 优先关注TOP10 =====
                    st.subheader("🔥 优先关注TOP10")
                    st.caption("按P1-P4和风险分排序，快速锁定最需要关注的学员（在下方明细区选择学员查看完整信息）")
                    _cards = []
                    for _idx, r in enumerate(results[:10]):
                        _ins_c = insight_map.get(r["学员姓名"])
                        _pc = _priority_color(r["优先级"])
                        if _ins_c and _ins_c.get("risk_type"):
                            _type_str = f"{_ins_c['risk_icon']}{_ins_c['risk_type']}"
                        else:
                            _type_str = "🟢暂无明显风险"
                        _ts = _trend_short(_ins_c["trend"]) if _ins_c else "？数据不足"
                        _tc = _conclusion_color(_ins_c["trend"]["summary_symbol"]) if _ins_c else "#607D8B"
                        # 跟进状态徽章（默认按数据判断：P1-P3待联系/P4暂不需要跟进）
                        _rec_c = _rfu_states.get(r["学员姓名"]) or {}
                        _stts_c = _rec_c.get("status") or default_status_for(r["优先级"])
                        _sm_c = STATUS_META.get(_stts_c, STATUS_META[STATUS_PENDING])
                        _stts_chip = (f'<span style="background:{_sm_c["color"]}1A;color:{_sm_c["color"]};'
                                      f'border:1px solid {_sm_c["color"]};border-radius:3px;'
                                      f'padding:1px 6px;font-size:11px;">{_sm_c["icon"]}{_stts_c}</span>')
                        _cards.append(
                            '<div style="flex:1 1 300px;min-width:280px;border:1px solid #e8eaf0;'
                            f'border-left:4px solid {_pc};border-radius:6px;padding:8px 12px;background:#ffffff;">'
                            f'<span style="color:{_pc};font-weight:700;font-size:15px;">{_CIRCLED_NUM[_idx]}</span> '
                            f'<b style="font-size:14px;">{_esc_html(r["学员姓名"])}</b> '
                            f'<span style="background:{_pc};color:#fff;border-radius:3px;padding:1px 6px;font-size:11px;">{r["优先级"]}</span> '
                            f'<span style="color:#555;font-size:12px;">风险分{r["风险分"]}</span> '
                            f'<span style="color:#333;font-size:12px;">{_esc_html(_type_str)}</span> '
                            f'<span style="color:{_tc};font-weight:600;font-size:12px;">{_esc_html(_ts)}</span> '
                            f'{_stts_chip}'
                            '</div>'
                        )
                    st.markdown('<div style="display:flex;flex-wrap:wrap;gap:8px;">' + "".join(_cards) + '</div>', unsafe_allow_html=True)

                    # ===== 3. 📋 学员风险明细 =====
                    st.subheader("📋 学员风险明细")

                    def _fu_status_of(_n, _p):
                        _rec_x = _rfu_states.get(_n) or {}
                        return status_display(_rec_x.get("status") or default_status_for(_p))

                    display_df = pd.DataFrame([
                        {
                            "排名": r["排名"],
                            "姓名": r["学员姓名"],
                            "优先级": r["优先级"],
                            "风险分": r["风险分"],
                            "有效听课率": r["有效听课率"],
                            "平均正确率": r["平均正确率"],
                            "练习提交率": r["练习提交率"],
                            "平均得分": r["平均得分"],
                            "问题讲次": r["问题讲次"],
                            "风险类型": (f"{insight_map[r['学员姓名']]['risk_icon']}{insight_map[r['学员姓名']]['risk_type']}"
                                         if r["学员姓名"] in insight_map and insight_map[r["学员姓名"]].get("risk_type")
                                         else "🟢暂无明显风险"),
                            "近期趋势": _trend_short(insight_map[r["学员姓名"]]["trend"]) if r["学员姓名"] in insight_map else "？数据不足",
                            "跟进状态": _fu_status_of(r["学员姓名"], r["优先级"]),
                        }
                        for r in results
                    ])
                    st.dataframe(display_df, use_container_width=True, hide_index=True)

                    # ===== 4. 🔍 AI风险洞察 =====
                    st.subheader("🔍 AI风险洞察")
                    _top_ins = [i for i in insights if "P1" in i["priority"] or "P2" in i["priority"]][:15]
                    _top_names = {i["name"] for i in _top_ins}
                    _incons_ins = [i for i in insights if i["inconsistency"].get("inconsistent") and i["name"] not in _top_names][:5]
                    _ai_targets = _top_ins + _incons_ins
                    _n_calls = (len(_ai_targets) + 4) // 5 if _ai_targets else 0

                    ai_map = st.session_state.get("lec_risk_ai_insights") or {}
                    if _ai_targets:
                        _hint = f"对风险最高的{len(_top_ins)}名学员"
                        if _incons_ins:
                            _hint += f"及{len(_incons_ins)}名数据异常学员"
                        _hint += f"进行AI深度分析（约{_n_calls}次模型调用，输出校验数据依据，失败自动降级规则版），其余学员采用规则分析，速度优先"
                        st.caption(_hint)
                        if st.button("🤖 开始AI深度分析", key="lec_ai_btn", type="primary"):
                            from core.ai_risk_insight import generate_batch_insights
                            _p_bar = st.progress(0)
                            with st.spinner("AI正在分析重点学员风险原因..."):
                                ai_map = generate_batch_insights(
                                    _ai_targets,
                                    progress_callback=lambda cur, total: _p_bar.progress(cur / total)
                                )
                            st.session_state["lec_risk_ai_insights"] = ai_map
                            st.rerun()

                    if ai_map:
                        _ai_cnt = sum(1 for v in ai_map.values() if v.get("source") == "ai")
                        st.caption(f"已生成 {len(ai_map)} 名学员风险洞察（AI深度分析 {_ai_cnt} 名 · 规则兜底 {len(ai_map) - _ai_cnt} 名）")
                        for _i in _ai_targets:
                            _a = ai_map.get(_i["name"])
                            _data = _a if _a else _i["rule_insight"]
                            _src = _a.get("source", "rule") if _a else "rule"
                            _tc2 = _risk_type_color(_data.get("主要风险", ""))
                            _src_tag = "🤖 AI深度分析" if _src == "ai" else "⚙️ 规则分析（真实数据）"
                            _incons_html = ""
                            if _i["inconsistency"].get("inconsistent"):
                                _incons_html = (f'<div style="color:#1565C0;font-size:12px;margin-top:4px;">'
                                                f'⚖️ {_esc_html(_i["inconsistency"]["message"])}</div>')
                            _n_h = _esc_html(_i["name"])
                            _pr_h = _esc_html(_i["priority"])
                            _pr_c = _priority_color(_i["priority"])
                            _ts_h = _esc_html(_trend_short(_i["trend"]))
                            _ts_c = _conclusion_color(_i["trend"]["summary_symbol"])
                            _risk_h = _esc_html(_data.get("主要风险", ""))
                            _trig_h = _esc_html(_data.get("触发指标", ""))
                            _expl_h = _esc_html(_data.get("风险解释", ""))
                            _foc_h = _esc_html(_data.get("建议关注", ""))
                            st.markdown(f"""
<div style="border:1px solid #e8eaf0;border-left:4px solid {_tc2};border-radius:6px;padding:10px 14px;margin:6px 0;background:#fff;">
<div style="margin-bottom:4px;"><b style="font-size:14px;">{_n_h}</b>
<span style="background:{_pr_c};color:#fff;border-radius:3px;padding:1px 6px;font-size:11px;">{_pr_h}</span>
<span style="color:#555;font-size:12px;">风险分{_i["risk_score"]}</span>
<span style="color:{_tc2};font-weight:600;font-size:12px;">{_risk_h}</span>
<span style="color:{_ts_c};font-size:12px;">{_ts_h}</span>
<span style="color:#999;font-size:11px;float:right;">{_src_tag}</span></div>
<div style="font-size:12.5px;color:#333;line-height:1.7;">
<div>触发指标：{_trig_h}</div>
<div>风险解释：{_expl_h}</div>
<div>建议关注：{_foc_h}</div>
</div>
{_incons_html}
</div>
""", unsafe_allow_html=True)

                    # ===== 5+6. 🗂️ 风险处理卡（当前风险→AI诊断→跟进建议→沟通方案→跟进记录→AI判断→风险变化）=====
                    st.subheader("🗂️ 风险处理卡")
                    st.caption("选择学员：①查看风险与趋势 → ②AI诊断原因 → ③跟进建议 → ④生成沟通方案 → ⑤记录跟进结果 → ⑥AI判断下一步 → ⑦风险状态变化")
                    sel_name = st.selectbox("选择学员", [r["学员姓名"] for r in results], key="lec_detail_sel")
                    _ins = insight_map.get(sel_name)
                    _res = result_map.get(sel_name)
                    if _ins and _res:
                        _t = _ins["trend"]
                        st.markdown("**① 当前风险**（P1-P4与风险分由系统规则判定，AI仅解释不修改；趋势时间优先：最新讲次优先）")
                        _rt_color = _risk_type_color(_ins["risk_type"]) if _ins.get("risk_type") else "#2E7D32"
                        _sel_h = _esc_html(sel_name)
                        _pr2_c = _priority_color(_ins["priority"])
                        _pr2_h = _esc_html(_ins["priority"])
                        _rt_h = _esc_html(_ins["risk_type"] or "暂无明显风险")
                        _tcn_c = _conclusion_color(_t["summary_symbol"])
                        _tcn_h = _esc_html(_t["conclusion"])
                        st.markdown(
                            f"**{_sel_h}** ｜ "
                            f"<span style='background:{_pr2_c};color:#fff;border-radius:3px;padding:1px 6px;font-size:12px;'>{_pr2_h}</span> "
                            f"<span style='color:#555;font-size:13px;'>风险分{_ins['risk_score']}</span> ｜ "
                            f"<span style='color:{_rt_color};font-weight:600;font-size:13px;'>{_ins['risk_icon']}{_rt_h}</span> ｜ "
                            f"<span style='color:{_tcn_c};font-size:13px;'>近期趋势：{_t['summary_symbol']} {_tcn_h}</span>",
                            unsafe_allow_html=True)
                        st.caption(f"5维指标：{_ins['metrics_brief']} ｜ 异常汇总：{_ins['anomalies_brief']}")

                        if _ins["inconsistency"].get("inconsistent"):
                            st.info(f"⚖️ **数据与风险不一致**：{_ins['inconsistency']['message']}")

                        st.markdown("**📈 5维近期趋势**")
                        _dim_rows = [
                            {"维度": _d, "趋势": f"{_td['symbol']} {_td['trend']}", "数据对比": _td["detail"]}
                            for _d, _td in _t["dims"].items()
                        ]
                        st.dataframe(pd.DataFrame(_dim_rows), use_container_width=True, hide_index=True)

                        st.markdown(f"**🔎 问题讲次（共{_ins['problem_count']}项异常）**")
                        if _ins["problem_lectures"]:
                            _pl_lines = []
                            for _pl in _ins["problem_lectures"]:
                                _issues = "、".join(f"{_iv['type']}（{_iv['data']}）" for _iv in _pl["issues"])
                                _title = f"《{_esc_html(_pl['title'])}》" if _pl.get("title") else ""
                                _pl_lines.append(
                                    f"<div style='padding:4px 0;border-bottom:1px dashed #eee;font-size:13px;color:#333;'>"
                                    f"<b>{_esc_html(_pl['lecture'])}</b>{_title} ｜ {_esc_html(_issues)}</div>")
                            st.markdown("".join(_pl_lines), unsafe_allow_html=True)
                        else:
                            st.success("暂无问题讲次，继续保持。")

                        _ai_i = ai_map.get(sel_name)
                        _data_i = _ai_i if _ai_i else _ins["rule_insight"]
                        _src_i = _ai_i.get("source", "rule") if _ai_i else "rule"
                        _src_tag_i = "🤖 AI深度分析" if _src_i == "ai" else "⚙️ 规则分析（真实数据）"
                        st.markdown(f"**🔍 该学员风险洞察**（{_src_tag_i}）")
                        _tc_i = _risk_type_color(_data_i.get("主要风险", ""))
                        _di_risk = _esc_html(_data_i.get("主要风险", ""))
                        _di_trig = _esc_html(_data_i.get("触发指标", ""))
                        _di_expl = _esc_html(_data_i.get("风险解释", ""))
                        _di_foc = _esc_html(_data_i.get("建议关注", ""))
                        st.markdown(f"""
<div style="border:1px solid #e8eaf0;border-left:4px solid {_tc_i};border-radius:6px;padding:10px 14px;background:#fafafa;font-size:13px;line-height:1.8;">
<div><b>主要风险：</b>{_di_risk}</div>
<div><b>触发指标：</b>{_di_trig}</div>
<div><b>风险解释：</b>{_di_expl}</div>
<div><b>建议关注：</b>{_di_foc}</div>
<div><b>趋势结论：</b>{_tcn_h}</div>
</div>
""", unsafe_allow_html=True)

                        # ---- ② 🔍 AI风险诊断（真实数据组装，零编造）----
                        st.markdown("**② 🔍 AI风险诊断**（为什么这个学员需要关注）")
                        _chg_lines = []
                        for _d, _td in _t["dims"].items():
                            if _td["trend"] in ("下降", "上升", "波动"):
                                _chg_lines.append(f"{_d}{_td['symbol']}（{_td['detail']}）")
                        _key_change = "；".join(_chg_lines) if _chg_lines else f"各维度暂无明显变化（{_t['conclusion']}）"
                        if _ins["inconsistency"].get("inconsistent"):
                            _cur_judge = _ins["inconsistency"]["message"]
                        elif len(_t.get("no_data", [])) >= 4:
                            _cur_judge = "数据不足，建议人工确认（多数维度缺少有效数据）"
                        else:
                            _cur_judge = _t["conclusion"]
                        _diag_core = (f"{_ins['risk_icon']}{_ins['risk_type']}（触发：{'、'.join(_ins['risk_triggers'])}）"
                                      if _ins.get("risk_type") else "暂无明显风险（5维指标未触发风险规则）")
                        _diag_evidence = (f"5维指标：{_ins['metrics_brief']}；异常：{_ins['anomalies_brief']}；"
                                          f"问题讲次共{_ins['problem_count']}项")
                        st.markdown(f"""
<div style="border:1px solid #e8eaf0;border-left:4px solid #1565C0;border-radius:6px;padding:10px 14px;margin:6px 0;background:#fff;font-size:13px;line-height:1.8;">
<div><b>核心风险：</b>{_esc_html(_diag_core)}</div>
<div><b>关键变化：</b>{_esc_html(_key_change)}</div>
<div><b>当前判断：</b>{_esc_html(_cur_judge)}</div>
<div><b>风险证据：</b>{_esc_html(_diag_evidence)}</div>
</div>
""", unsafe_allow_html=True)

                        # ---- ③ 🎯 建议跟进动作（规则版，零LLM）----
                        st.markdown("**③ 🎯 建议跟进动作**（风险是什么 → 为什么 → 老师现在应该做什么）")
                        _rec_sel = _rfu_states.get(sel_name) or {}
                        _next_act = suggest_next_action(_ins, _rec_sel)
                        _focus_html = "".join(
                            f"<div>{_fi + 1}. {_esc_html(_fp)}</div>"
                            for _fi, _fp in enumerate(_next_act["focus_points"]))
                        st.markdown(f"""
<div style="border:1px solid #e8eaf0;border-left:4px solid {_next_act["urgency_color"]};border-radius:6px;padding:10px 14px;margin:6px 0;background:#fafafa;font-size:13px;line-height:1.8;">
<div><b>建议：</b>{_esc_html(_next_act["action"])}　<span style="background:{_next_act["urgency_color"]};color:#fff;border-radius:3px;padding:1px 8px;font-size:11px;">跟进优先级 {_next_act["urgency"]}</span></div>
<div><b>建议重点：</b></div>{_focus_html}
<div style="color:#888;font-size:12px;">判断依据：{_esc_html(_next_act["basis"])}（全部来自真实数据）</div>
</div>
""", unsafe_allow_html=True)

                        # ---- ④ ☎️ 生成沟通方案（AI按需调用）----
                        st.markdown("**④ ☎️ 沟通方案**（开场/核心沟通/家长可能反馈/老师应对/收尾；真人沟通感，全部基于真实数据）")
                        if st.button("☎️ 生成沟通方案", key="lec_plan_btn", type="primary"):
                            from core.ai_comm_plan import generate_comm_plan
                            with st.spinner("AI正在生成沟通方案（5模块完整性校验，失败自动降级规则版）..."):
                                _plan_txt = generate_comm_plan(_ins, _rec_sel, ai_map.get(sel_name))
                            st.session_state["lec_plan_content"] = _plan_txt
                            st.session_state["lec_plan_name"] = sel_name
                            st.rerun()
                        _plan_shown = st.session_state.get("lec_plan_content")
                        if _plan_shown and st.session_state.get("lec_plan_name") == sel_name:
                            st.markdown(_plan_shown)
                            _safe_pn = re.sub(r'[\\/:*?"<>|]', '', sel_name)
                            st.download_button("📥 下载沟通方案（TXT）", data=_plan_shown.encode("utf-8"),
                                               file_name=f"沟通方案_{_safe_pn}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                                               mime="text/plain", key="lec_plan_dl")

                        # ---- ⑤ ✅ 记录本次跟进（含跟进状态与手动更新）----
                        _stts_cur = _rec_sel.get("status") or default_status_for(_ins["priority"])
                        _sm_cur = STATUS_META.get(_stts_cur, STATUS_META[STATUS_PENDING])
                        st.markdown(f"**⑤ ✅ 记录本次跟进**　当前跟进状态："
                                    f"<span style='background:{_sm_cur['color']}1A;color:{_sm_cur['color']};"
                                    f"border:1px solid {_sm_cur['color']};border-radius:3px;"
                                    f"padding:1px 8px;font-size:12px;'>{_sm_cur['icon']} {_stts_cur}</span>",
                                    unsafe_allow_html=True)
                        if _rec_sel.get("last_followup_at"):
                            _last_fu = (f"最后跟进：{_rec_sel['last_followup_at']}"
                                        f"（{_rec_sel.get('followup_method') or '未记录'}｜{_rec_sel.get('followup_result') or '未记录'}）")
                            if _rec_sel.get("next_followup_date"):
                                _last_fu += f"｜下次跟进：{_rec_sel['next_followup_date']}"
                            st.caption(_last_fu)
                        with st.expander("✅ 记录本次跟进（完成电话/微信沟通后填写，保存后立即生成AI跟进判断）", expanded=False):
                            _fu_m = st.selectbox("跟进方式", FU_METHODS, key=f"fu3_method_{sel_name}")
                            _fu_r = st.selectbox("跟进结果", FU_RESULTS, key=f"fu3_result_{sel_name}")
                            _fu_fb = st.text_area("家长反馈", key=f"fu3_feedback_{sel_name}", height=80,
                                                  placeholder="请输入本次沟通后的真实反馈……")
                            _fu_nt = st.text_area("老师备注（选填）", key=f"fu3_note_{sel_name}", height=60)
                            _fu_nd_def = _rec_sel.get("next_followup_date")
                            _fu_nd_val = None
                            if _fu_nd_def:
                                try:
                                    _fu_nd_val = datetime.strptime(_fu_nd_def, "%Y-%m-%d").date()
                                except ValueError:
                                    _fu_nd_val = None
                            _fu_nd = st.date_input("下次跟进时间", value=_fu_nd_val, key=f"fu3_next_{sel_name}")
                            _c_save, _c_sts = st.columns(2)
                            with _c_save:
                                if st.button("💾 保存跟进记录", key=f"fu3_save_{sel_name}", type="primary", use_container_width=True):
                                    _j = rule_followup_judgment(_fu_m, _fu_r, _fu_fb, _fu_nt, _ins)
                                    try:
                                        _rfu_store.record_followup(
                                            sel_name, _fu_m, _fu_r, _fu_fb, _fu_nt,
                                            _fu_nd.strftime("%Y-%m-%d"), _ins["risk_score"], _ins["priority"],
                                            new_status=_j["new_status"])
                                        st.session_state["lec_fu_judgment"] = {
                                            "name": sel_name, "method": _fu_m, "result": _fu_r,
                                            "feedback": _fu_fb, "note": _fu_nt}
                                        st.rerun()
                                    except Exception as _fu_ex:
                                        st.error(f"保存失败：{_fu_ex}")
                            with _c_sts:
                                _stts_manual = st.selectbox("手动更新跟进状态", STATUS_ORDER,
                                                            index=STATUS_ORDER.index(_stts_cur),
                                                            key=f"fu3_stts_{sel_name}")
                                if st.button("🔄 仅更新状态", key=f"fu3_stts_btn_{sel_name}", use_container_width=True):
                                    if _rfu_store.update_status(sel_name, _stts_manual):
                                        st.rerun()

                        # ---- ⑥ 🤖 AI跟进判断（保存后立即显示，规则版零延迟 + 可选AI深度判断）----
                        _fuj = st.session_state.get("lec_fu_judgment")
                        if _fuj and _fuj.get("name") == sel_name:
                            st.markdown("**⑥ 🤖 AI跟进判断**（基于本次跟进真实反馈 + 学情数据，无数据不下结论）")
                            _rule_j = rule_followup_judgment(_fuj["method"], _fuj["result"],
                                                             _fuj["feedback"], _fuj["note"], _ins)
                            st.markdown(f"""
<div style="border:1px solid #e8eaf0;border-left:4px solid #F9A825;border-radius:6px;padding:10px 14px;margin:6px 0;background:#fff;font-size:13px;line-height:1.8;">
<div><b>当前状态：</b>{_esc_html(_rule_j["state_label"])}</div>
<div><b>AI判断：</b>{_esc_html(_rule_j["judgment"])}</div>
<div><b>下一步：</b>{_esc_html(_rule_j["next_step"])}</div>
<div style="color:#888;font-size:12px;">建议下次跟进日期：{_rule_j["suggest_next_date"]}（可在上方表单中调整）</div>
</div>
""", unsafe_allow_html=True)
                            _ai_j_shown = st.session_state.get("lec_fuj_ai")
                            if _ai_j_shown and _ai_j_shown.get("name") == sel_name:
                                st.markdown("**🤖 AI深度判断**（结合家长真实反馈的深度分析）")
                                st.markdown(_ai_j_shown["text"])
                            else:
                                if st.button("🤖 AI深度判断（结合家长反馈深度分析）", key="lec_fuj_ai_btn"):
                                    from core.ai_comm_plan import generate_followup_judgment
                                    with st.spinner("AI正在深度分析（3模块校验，失败自动降级规则版）..."):
                                        _ai_j = generate_followup_judgment(
                                            _fuj["method"], _fuj["result"], _fuj["feedback"], _fuj["note"],
                                            _ins, _rec_sel)
                                    st.session_state["lec_fuj_ai"] = {"name": sel_name, "text": _ai_j}
                                    st.rerun()

                        # ---- ⑦ 📉 风险状态变化（跟进前 → 重新分析后自动对比）----
                        st.markdown("**⑦ 📉 风险状态变化**（跟进后上传最新行课数据重新分析，系统自动对比风险变化）")
                        _chg = risk_change_label(_rec_sel, _ins["risk_score"])
                        st.markdown(f"""
<div style="border:1px solid {_chg["color"]}66;border-left:4px solid {_chg["color"]};border-radius:6px;padding:10px 14px;margin:6px 0;background:#fff;font-size:13px;line-height:1.8;">
<div><b>{_chg["icon"]} {_esc_html(_chg["label"])}</b></div>
<div style="color:#555;">{_esc_html(_chg["detail"])}</div>
</div>
""", unsafe_allow_html=True)
                        if _rec_sel.get("risk_history"):
                            _tl = " → ".join(f"{_h['risk_score']:.0f}分({str(_h['priority']).split('-')[0]})"
                                             for _h in _rec_sel["risk_history"][-5:])
                            st.caption(f"分析快照：{_tl}")
                        if _rec_sel.get("history"):
                            with st.expander(f"📜 跟进记录（共{len(_rec_sel['history'])}次）"):
                                for _h in reversed(_rec_sel["history"][-5:]):
                                    _h_fb = f"｜反馈：{_h['feedback']}" if _h.get("feedback") else ""
                                    st.markdown(f"- [{_h['time']}] {_h['method']}｜{_h['result']}{_h_fb}")

                    # ===== 7. 📄 AI学情风险报告（单个学员）=====
                    st.subheader("📄 AI学情风险报告（单个学员）")
                    st.caption("10模块报告：整体状态·5维指标·近期趋势·风险等级·风险类型·风险原因·问题讲次·已知事实🟢·待确认🟡·关注建议（全部基于真实数据，数据不足时明确提示）")
                    rpt_name = st.selectbox("选择学员生成报告", [r["学员姓名"] for r in results], key="lec_rpt_student")
                    if st.button("📄 生成AI学情风险报告", key="lec_rpt_gen", type="primary"):
                        from core.ai_risk_insight import generate_risk_report
                        _ri = insight_map.get(rpt_name)
                        _rr = result_map.get(rpt_name)
                        with st.spinner("AI正在生成学情风险报告（含10模块完整性校验，失败自动降级规则版）..."):
                            _rpt = generate_risk_report(_ri, _rr)
                        st.session_state["lec_rpt_content"] = _rpt
                        st.session_state["lec_rpt_content_name"] = rpt_name
                        st.rerun()

                    if st.session_state.get("lec_rpt_content"):
                        _rname = st.session_state.get("lec_rpt_content_name", "")
                        _rpt = st.session_state["lec_rpt_content"]
                        st.success(f"✅ AI学情风险报告已生成：{_rname}")
                        st.text_area("报告内容", value=_rpt, height=380, key="lec_rpt_preview", label_visibility="collapsed")
                        _safe_rn = re.sub(r'[\\/:*?"<>|]', '', _rname)
                        st.download_button(
                            "📥 下载报告（TXT）",
                            data=_rpt.encode("utf-8"),
                            file_name=f"AI学情风险报告_{_safe_rn}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt",
                            mime="text/plain",
                            key="lec_rpt_dl",
                        )

                    # ===== 导出结果 =====
                    st.subheader("导出结果")
                    if st.session_state.get("lec_risk_export_path"):
                        with open(st.session_state["lec_risk_export_path"], "rb") as f:
                            st.download_button(
                                "📥 导出风险分析Excel",
                                data=f,
                                file_name=st.session_state.get("lec_risk_export_filename", "风险分析.xlsx"),
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                use_container_width=True,
                                key="lec_risk_dl_excel",
                            )

            # ===== 批量报告生成 =====
            elif report_mode == "📄 批量报告生成":
                # 仅当上传文件变更时清空缓存（避免 st.rerun() 后误删）
                if uploaded_file3:
                    file_identity = uploaded_file3.name + str(len(df))
                else:
                    file_identity = None
                if st.session_state.get("lec_file_identity") != file_identity:
                    for key in ["lec_reports", "lec_reports_elapsed", "lec_single_report", "lec_single_report_name", "lec_single_report_elapsed", "lec_pdf_bytes", "lec_pdf_filename", "lec_zip_bytes", "lec_zip_filename", "lec_zip_ready", "lec_single_pdf_bytes", "lec_single_pdf_filename", "lec_zip_path"]:
                        st.session_state.pop(key, None)
                    st.session_state["lec_file_identity"] = file_identity

                from core.report_generator_v3 import classify_student, batch_generate_reports
                students_data = []
                for _, row in df.iterrows():
                    row_data = {col: row[col] for col in df.columns}
                    students_data.append({
                        "name": str(row[name_col]) if pd.notna(row[name_col]) else "未知",
                        "student_id": str(row[id_col]) if id_col and pd.notna(row[id_col]) else "",
                        "row_data": row_data,
                    })

                for item in students_data:
                    item["category"] = classify_student(
                        item["row_data"],
                        all_students_data=students_data,
                        lectures=lectures,
                        attendance_rates=attendance_rates
                    )

                cat_stats = {"优秀": 0, "中等": 0, "差": 0}
                for item in students_data:
                    cat_stats[item["category"]] = cat_stats.get(item["category"], 0) + 1

                col1, col2, col3 = st.columns(3)
                col1.metric("🟢 优秀", cat_stats.get("优秀", 0))
                col2.metric("🟡 中等", cat_stats.get("中等", 0))
                col3.metric("🔴 差", cat_stats.get("差", 0))

                # 单个学员选择生成
                st.markdown("<hr style='margin:8px 0;border:0;border-top:1px solid #e0e0e0;'>", unsafe_allow_html=True)
                st.markdown("**🎯 单个学员报告生成**")
                cat_filter = st.multiselect(
                    "筛选分类",
                    ["优秀", "中等", "差"],
                    default=["优秀", "中等", "差"],
                    key="lec_single_cat_filter"
                )
                filtered_students = [s for s in students_data if s.get("category", "") in cat_filter]
                if not filtered_students:
                    filtered_students = students_data
                selected_student_name = st.selectbox(
                    "选择学员",
                    [s["name"] for s in filtered_students],
                    key="lec_single_student"
                )
                if st.button("📄 生成单个报告", type="primary", use_container_width=True):
                    progress_text = st.empty()
                    progress_bar = st.progress(0)
                    start_time = time.time()

                    selected_item = next((s for s in filtered_students if s["name"] == selected_student_name), None)
                    if selected_item:
                        single_reports = batch_generate_reports(
                            [selected_item],
                            progress_callback=lambda cur, total: progress_bar.progress(cur / total),
                            lectures=lectures,
                            attendance_rates=attendance_rates
                        )
                        elapsed = time.time() - start_time
                        st.session_state["lec_single_report"] = single_reports[0]
                        st.session_state["lec_single_report_name"] = selected_student_name
                        st.session_state["lec_single_report_elapsed"] = elapsed
                        st.rerun()

                if st.session_state.get("lec_single_report"):
                    single_report = st.session_state["lec_single_report"]
                    single_name = st.session_state["lec_single_report_name"]
                    report_content = single_report.get("正式报告", single_report.get("完整输出", single_report.get("report", "")))
                    
                    # 检查是否为错误报告
                    is_error = report_content.startswith("报告生成失败") or report_content.startswith("报告生成异常")
                    
                    if is_error:
                        st.error(f"报告生成失败！{single_name}，耗时 {st.session_state['lec_single_report_elapsed']:.1f} 秒")
                        st.error(report_content)
                    else:
                        st.success(f"报告生成完成！{single_name}，耗时 {st.session_state['lec_single_report_elapsed']:.1f} 秒")

                    st.subheader(f"📋 {single_name} 的学情报告")
                    st.markdown(f"**分类**: {single_report.get('分类', single_report.get('category', '未知'))}")
                    st.text_area(
                        "学情报告",
                        value=report_content,
                        height=400,
                        key="lec_single_report_preview",
                        label_visibility="collapsed"
                    )

                    # 导出单个报告Excel
                    output_filename = f"学情报告_{single_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    output_path = os.path.join(OUTPUT_DIR, output_filename)
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    export_reports_to_excel([single_report], output_path)
                    with open(output_path, "rb") as f:
                        st.download_button(
                            "📥 导出报告Excel",
                            data=f,
                            file_name=output_filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )

                    # 导出单个PDF
                    from core.report_generator_v3 import generate_pdf_report
                    safe_name = re.sub(r'[\\/:*?"<>|]', '', single_name)
                    pdf_filename = f"学情报告_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                    if st.button("📕 生成PDF报告", key="lec_export_single_pdf2", use_container_width=True):
                        with st.spinner("正在生成PDF..."):
                            try:
                                pdf_path = generate_pdf_report(single_report, OUTPUT_DIR)
                                with open(pdf_path, "rb") as f:
                                    pdf_bytes = f.read()
                                st.session_state["lec_single_pdf_bytes"] = pdf_bytes
                                st.session_state["lec_single_pdf_filename"] = pdf_filename
                                st.rerun()
                            except Exception as e:
                                st.error(f"PDF生成失败: {e}")
                    if st.session_state.get("lec_single_pdf_bytes") and st.session_state.get("lec_single_pdf_filename") == pdf_filename:
                        st.download_button(
                            "📕 点击下载PDF",
                            data=st.session_state["lec_single_pdf_bytes"],
                            file_name=pdf_filename,
                            mime="application/pdf",
                            use_container_width=True,
                            key="lec_dl_single_pdf2"
                        )

                # 批量生成
                st.markdown("<hr style='margin:8px 0;border:0;border-top:1px solid #e0e0e0;'>", unsafe_allow_html=True)
                st.markdown("**🚀 批量生成全部报告**")
                if st.button("🚀 批量生成学情报告", type="primary", use_container_width=True):
                    progress_text = st.empty()
                    progress_bar = st.progress(0)

                    start_time = time.time()
                    reports = batch_generate_reports(
                        students_data,
                        progress_callback=lambda cur, total: progress_bar.progress(cur / total),
                        lectures=lectures,
                        attendance_rates=attendance_rates
                    )
                    elapsed = time.time() - start_time
                    st.session_state["lec_reports"] = reports
                    st.session_state["lec_reports_elapsed"] = elapsed

                    # 同步生成全部PDF打包zip（一步到位）
                    progress_text.text("📕 正在打包全部PDF...")
                    import zipfile
                    from core.report_generator_v3 import generate_pdf_report
                    zip_filename = f"学情报告PDF_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
                    zip_path = os.path.join(OUTPUT_DIR, zip_filename)
                    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                        for i, r in enumerate(reports):
                            try:
                                pdf_path = generate_pdf_report(r, OUTPUT_DIR)
                                zf.write(pdf_path, os.path.basename(pdf_path))
                            except Exception as e:
                                st.warning(f"学员 {r.get('学生姓名', '未知')} PDF生成失败: {e}")
                                continue
                            progress_bar.progress(0.5 + 0.5 * (i + 1) / len(reports))
                    st.session_state["lec_zip_path"] = zip_path
                    st.session_state["lec_zip_filename"] = zip_filename
                    st.rerun()

                # 显示已生成的报告（持久化在 session_state 中）
                if st.session_state.get("lec_reports"):
                    reports = st.session_state["lec_reports"]
                    elapsed = st.session_state["lec_reports_elapsed"]
                    st.success(f"报告生成完成！{len(reports)} 份，耗时 {elapsed:.1f} 秒")

                    st.subheader("导出全部报告")
                    with open(st.session_state["lec_zip_path"], "rb") as f:
                        st.download_button(
                            "📕 导出全部PDF（打包zip）",
                            data=f,
                            file_name=st.session_state["lec_zip_filename"],
                            mime="application/zip",
                            use_container_width=True,
                        )
                    log_event("report_end", {"student_count": len(df), "duration_s": round(elapsed, 2)})

        except ValueError as e:
            st.error(f"数据格式错误：{e}")
        except Exception as e:
            st.error(f"处理出错：{e}")


# ============================================================
# Tab 4: 数据看板
# ============================================================
with tab4:
    st.info("展示Agent使用数据与效率对比。")

    today_stats = get_daily_stats()
    all_stats = get_all_stats()

    st.subheader("今日概览")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("今日分析次数", today_stats.get("analysis_count", 0))
    with col2:
        st.metric("今日答疑次数", today_stats.get("qa_count", 0))
    with col3:
        st.metric("今日报告数", today_stats.get("report_count", 0))
    with col4:
        total_saved = (
            today_stats.get("analysis_count", 0) * 180
            + today_stats.get("qa_count", 0) * 5
            + today_stats.get("report_count", 0) * 120
        )
        st.metric("累计节省时间(分钟)", total_saved)

    if today_stats["total_events"] > 0:
        st.subheader("效率对比（今日）")
        if today_stats["analysis_count"] > 0:
            agent_time = today_stats["analysis_total_time_s"]
            manual_time = today_stats["analysis_count"] * 180 * 60
            st.markdown(f"**学情分析**: Agent {agent_time:.0f}秒 vs 手动基准 {manual_time:.0f}秒 → 节省 {(1 - agent_time/manual_time)*100:.1f}%")
        if today_stats["qa_count"] > 0:
            agent_time = today_stats["qa_total_time_s"]
            manual_time = today_stats["qa_count"] * 5 * 60
            st.markdown(f"**家长答疑**: Agent {agent_time:.0f}秒 vs 手动基准 {manual_time:.0f}秒 → 节省 {(1 - agent_time/manual_time)*100:.1f}%")
        if today_stats["report_count"] > 0:
            agent_time = today_stats["report_total_time_s"]
            manual_time = today_stats["report_count"] * 6 * 60
            st.markdown(f"**报告生成**: Agent {agent_time:.0f}秒 vs 手动基准 {manual_time:.0f}秒 → 节省 {(1 - agent_time/manual_time)*100:.1f}%")

    if all_stats:
        st.subheader("历史趋势")
        stats_df = pd.DataFrame(all_stats)
        if len(stats_df) > 0:
            st.dataframe(stats_df, use_container_width=True)
    else:
        st.info("暂无历史数据，开始使用Agent后将自动记录。")

    with st.expander("📊 A/B测试基准数据"):
        st.markdown("""
        **手动基准（对照组）：**
        - 学情分析300人：约180分钟（3小时）
        - 单条家长答疑：约5分钟
        - 批量报告生成：约120分钟（2小时）

        **Agent目标：**
        - 学情分析：10分钟内完成
        - 单条答疑：30秒内完成
        - 批量报告：5分钟内完成
        """)


# ============================================================
# 侧边栏：飞书机器人配置
# ============================================================
with st.sidebar:
    st.markdown("---")
    st.subheader("🤖 飞书机器人配置")

    feishu_app_id = st.text_input("FEISHU_APP_ID", value=os.environ.get("FEISHU_APP_ID", ""), key="feishu_app_id")
    feishu_app_secret = st.text_input("FEISHU_APP_SECRET", type="password", value=os.environ.get("FEISHU_APP_SECRET", ""), key="feishu_app_secret")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        if st.button("💾 保存", key="save_feishu", use_container_width=True):
            os.environ["FEISHU_APP_ID"] = feishu_app_id
            os.environ["FEISHU_APP_SECRET"] = feishu_app_secret
            st.success("已保存")
    with col_s2:
        if st.button("🔗 测试", key="test_feishu", use_container_width=True):
            if feishu_app_id and feishu_app_secret:
                try:
                    os.environ["FEISHU_APP_ID"] = feishu_app_id
                    os.environ["FEISHU_APP_SECRET"] = feishu_app_secret
                    from core.feishu_bot import FeishuBot
                    bot = FeishuBot()
                    st.success("✅ 连接成功")
                except Exception as e:
                    st.error(f"❌ {e}")
            else:
                st.warning("请填写配置")

    with st.expander("📖 使用说明"):
        st.markdown("""
        1. 登录[飞书开发者后台](https://open.feishu.cn/app)
        2. 创建应用，获取 App ID 和 App Secret
        3. 配置机器人权限（im:message, im:resource, im:chat）
        4. 填入配置后保存

        **支持命令：** `/risk` `/report` `/help`
        """)

# ============================================================
# 侧边栏：企业微信机器人配置
# ============================================================
with st.sidebar:
    st.markdown("---")
    st.subheader("💬 企业微信机器人配置")

    wecom_corp_id = st.text_input("WECOM_CORP_ID", value=os.environ.get("WECOM_CORP_ID", ""), key="wecom_corp_id")
    wecom_agent_id = st.text_input("WECOM_AGENT_ID", value=os.environ.get("WECOM_AGENT_ID", ""), key="wecom_agent_id")
    wecom_corp_secret = st.text_input("WECOM_CORP_SECRET", type="password", value=os.environ.get("WECOM_CORP_SECRET", ""), key="wecom_corp_secret")
    wecom_token = st.text_input("WECOM_TOKEN", type="password", value=os.environ.get("WECOM_TOKEN", ""), key="wecom_token")

    col_w1, col_w2 = st.columns(2)
    with col_w1:
        if st.button("💾 保存", key="save_wecom", use_container_width=True):
            os.environ["WECOM_CORP_ID"] = wecom_corp_id
            os.environ["WECOM_AGENT_ID"] = wecom_agent_id
            os.environ["WECOM_CORP_SECRET"] = wecom_corp_secret
            os.environ["WECOM_TOKEN"] = wecom_token
            st.success("已保存")
    with col_w2:
        if st.button("🔗 测试", key="test_wecom", use_container_width=True):
            if wecom_corp_id and wecom_corp_secret:
                try:
                    os.environ["WECOM_CORP_ID"] = wecom_corp_id
                    os.environ["WECOM_CORP_SECRET"] = wecom_corp_secret
                    os.environ["WECOM_AGENT_ID"] = wecom_agent_id
                    from core.wecom_bot import WeComBot
                    bot = WeComBot()
                    token = bot.get_access_token()
                    st.success(f"✅ 连接成功")
                except Exception as e:
                    st.error(f"❌ {e}")
            else:
                st.warning("请填写配置")

    with st.expander("📖 使用说明"):
        st.markdown("""
        1. 登录[企业微信管理后台](https://work.weixin.qq.com/wework_admin/frame#apps)
        2. 创建自建应用，获取 CorpID、AgentID、Secret
        3. 配置回调URL和Token
        4. 填入配置后保存
        """)
