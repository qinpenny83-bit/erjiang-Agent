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
    "📋 行课数据风险分析&批量报告生成",
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
            💬 输入家长问题，系统将自动分类并生成专业回复话术。
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

    if generate_btn and (question or uploaded_image):
        with st.spinner("正在分析问题并生成回复..."):
            start_time = time.time()
            try:
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
                st.success(f"策略生成完成，耗时 {elapsed:.1f} 秒")

                # ====== 一、问题判断 ======
                with st.expander("🔍 一、问题判断", expanded=True):
                    diag = result.get("问题判断", {})
                    st.markdown("**学生当前情况**")
                    st.info(diag.get("学生当前情况", "") or "暂无")
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**家长核心顾虑**")
                        st.warning(diag.get("家长核心顾虑", "") or "暂无")
                    with cols[1]:
                        st.markdown("**解决重点**")
                        st.success(diag.get("解决重点", "") or "暂无")

                # ====== 二、沟通策略 ======
                with st.expander("🎯 二、沟通策略", expanded=True):
                    strat = result.get("沟通策略", {})
                    st.markdown("**沟通目标**")
                    st.info(strat.get("沟通目标", "") or "暂无")
                    cols = st.columns(2)
                    with cols[0]:
                        st.markdown("**最佳切入点**")
                        st.success(strat.get("最佳切入点", "") or "暂无")
                    with cols[1]:
                        st.markdown("**沟通注意事项**")
                        st.warning(strat.get("沟通注意事项", "") or "暂无")

                # ====== 三、家长沟通话术 ======
                with st.expander("💬 三、家长沟通话术", expanded=True):
                    script_text = result.get("话术", "")
                    st.text_area(
                        "话术（可编辑后复制）",
                        value=script_text,
                        height=300,
                        key="qa_response_output",
                        label_visibility="collapsed"
                    )

                # ====== 四、行动方案 ======
                with st.expander("📋 四、行动方案", expanded=False):
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

    with st.expander("💡 支持的问题类型"):
        st.markdown("""
        - **教学类**：课程内容、教学方法、考试安排、成绩分析
        - **服务类**：排课、请假、教材、上课时间、校区服务
        - **续费类**：续费优惠、课程套餐、退费政策
        - **投诉类**：教学质量、老师态度、服务不满
        """)


# ============================================================
# Tab 3: 行课数据风险分析&批量报告生成
# ============================================================
with tab3:
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #e8eaf6 0%, #f3e5f5 100%);
        padding: 10px 18px;
        border-radius: 6px;
        margin-bottom: 4px;
        max-width: 580px;
    ">
        <span style="color: #5c6bc0; font-size: 14px; font-weight: 500;">
            📋 上传行课数据Excel，系统自动识别讲次列，进行5维风险分析（有效听课·答题正确率·练习提交·练习得分·听课时长），按P1-P4优先级排序，并支持批量报告生成。
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

            # 模式切换
            report_mode = st.radio(
                "选择功能",
                ["⚠️ 风险分析&沟通优先级", "📄 批量报告生成"],
                horizontal=True,
                key="lecture_report_mode"
            )

            # ===== 风险分析&沟通优先级 =====
            if report_mode == "⚠️ 风险分析&沟通优先级":
                st.markdown("**⚠️ 学员沟通优先级分析**")
                st.caption(f"基于5维指标（有效听课·听课时长·答题正确率·练习提交·练习得分）对 {len(df)} 名学员进行风险排序")

                if st.button("🔍 开始风险分析", type="primary", use_container_width=True):
                    from core.lecture_risk_analyzer import batch_analyze_risk, export_risk_excel, batch_generate_scripts

                    progress_text = st.empty()
                    progress_bar = st.progress(0)

                    start_time = time.time()
                    results = batch_analyze_risk(
                        df, lectures, attendance_rates,
                        name_col=name_col, id_col=id_col,
                        progress_callback=lambda cur, total: progress_bar.progress(cur / total)
                    )
                    elapsed = time.time() - start_time
                    progress_text.text(f"✅ 风险分析完成！{len(results)} 名学员，耗时 {elapsed:.1f} 秒")

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

                    st.subheader("风险排序结果")
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
                        }
                        for r in results
                    ])
                    st.dataframe(display_df, use_container_width=True, hide_index=True)

                    st.subheader("导出结果")
                    output_filename = f"风险分析_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                    output_path = os.path.join(OUTPUT_DIR, output_filename)
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    export_risk_excel(results, lectures, attendance_rates, output_path, df)
                    with open(output_path, "rb") as f:
                        st.download_button(
                            "📥 导出风险分析Excel",
                            data=f,
                            file_name=output_filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    log_event("analysis_end", {"student_count": len(df), "duration_s": round(elapsed, 2)})

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
