import streamlit as st
import pandas as pd
import time
import os
import sys
from datetime import datetime

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TIER_COLORS, TIER_LABELS, OUTPUT_DIR
from utils.excel_parser import parse_uploaded_excel
from utils.excel_exporter import export_analysis_to_excel, export_reports_to_excel
from utils.logger import log_event, get_daily_stats, get_all_stats

st.set_page_config(page_title="二讲服务效能Agent", layout="wide", page_icon="🎓")

st.title("🎓 二讲服务效能Agent")
st.caption("AI驱动的学情分析 · 家长答疑 · 报告生成 一站式平台")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 学情分析与续费策略",
    "💬 家长答疑助手",
    "📋 批量报告生成",
    "📈 数据看板"
])

# ============================================================
# Tab 1: 学情分析与续费策略
# ============================================================
with tab1:
    st.header("学情分析与续费策略")
    st.info("上传学情Excel文件，系统将自动完成学生分层、优先级排序和话术生成。")

    col_upload, col_template = st.columns([3, 1])
    with col_upload:
        uploaded_file = st.file_uploader(
            "上传学情数据",
            type=["xlsx", "xls"],
            key="analysis_upload",
            help="支持 .xlsx 格式，需包含：学生姓名、年级、班级、最近成绩、成绩趋势、课堂参与度、作业完成率、距上次沟通(天)、续费剩余(天)、历史续费次数、家长态度"
        )
    with col_template:
        st.markdown("###")
        if st.button("📥 下载模板", use_container_width=True):
            sample_path = os.path.join(os.path.dirname(__file__), "data", "sample_students.xlsx")
            if os.path.exists(sample_path):
                with open(sample_path, "rb") as f:
                    st.download_button(
                        "下载示例Excel",
                        data=f,
                        file_name="学情数据模板.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )

    if uploaded_file:
        try:
            df = parse_uploaded_excel(uploaded_file)
            st.success(f"已解析文件：{uploaded_file.name}，共 {len(df)} 条学生数据")

            # 延迟导入，避免启动时就加载LLM相关模块
            from core.student_analyzer import analyze_and_generate_scripts

            # 先做分层分析（不调LLM）
            if "analysis_result" not in st.session_state or st.session_state.get("_upload_name") != uploaded_file.name:
                start_time = time.time()
                st.session_state["analysis_result"] = analyze_and_generate_scripts(df, generate=False)
                st.session_state["_upload_name"] = uploaded_file.name
                st.session_state["scripts_generated"] = False
                elapsed = time.time() - start_time
                log_event("analysis_end", {"student_count": len(df), "duration_s": round(elapsed, 2)})

            result = st.session_state["analysis_result"]

            # 分层统计展示
            st.subheader("分层概览")
            col_s, col_a, col_b, col_c, col_total = st.columns(5)
            tier_stats = result["tier_stats"]
            col_s.metric("S级 - 高危流失", tier_stats["S"], delta_color="inverse")
            col_a.metric("A级 - 需关注", tier_stats["A"])
            col_b.metric("B级 - 稳定", tier_stats["B"])
            col_c.metric("C级 - 低优先", tier_stats["C"])
            col_total.metric("总计", result["total"])

            # 分层柱状图
            st.subheader("分层分布")
            chart_df = pd.DataFrame([
                {"分层": label, "人数": count}
                for tier, count in tier_stats.items()
                for label in [TIER_LABELS[tier]]
            ])
            st.bar_chart(chart_df, x="分层", y="人数")

            # 一键生成话术按钮
            if not st.session_state.get("scripts_generated"):
                if st.button("🚀 一键生成全部沟通话术", type="primary", use_container_width=True):
                    with st.spinner("正在为每位学生生成个性化沟通话术，请稍候..."):
                        start_time = time.time()

                        def progress_cb(current, total):
                            st.session_state["gen_progress"] = current / total

                        st.session_state["analysis_result"] = analyze_and_generate_scripts(
                            df, generate=True, progress_callback=progress_cb
                        )
                        st.session_state["scripts_generated"] = True
                        elapsed = time.time() - start_time
                        log_event("analysis_end", {
                            "student_count": len(df),
                            "duration_s": round(elapsed, 2),
                            "with_scripts": True
                        })
                    st.success(f"话术生成完成！{len(df)}位学生的沟通话术已就绪，耗时 {elapsed:.1f} 秒")
                    st.rerun()

            # 学生列表与话术展示
            if st.session_state.get("scripts_generated"):
                st.subheader("学生沟通话术")

                # 分层筛选
                selected_tier = st.selectbox(
                    "按分层筛选",
                    ["全部", "S级 - 高危流失", "A级 - 需关注", "B级 - 稳定", "C级 - 低优先"],
                    key="tier_filter"
                )

                students = result["students"]
                if selected_tier != "全部":
                    tier_key = selected_tier[0]
                    students = [s for s in students if s["分层"] == tier_key]

                for student in students:
                    tier = student["分层"]
                    color = TIER_COLORS.get(tier, "#888")
                    with st.expander(
                        f"**{student['学生姓名']}** | {TIER_LABELS[tier]} | 风险分: {student['流失风险分']} | 续费剩余: {student['续费剩余(天)']}天",
                        expanded=(tier == "S")
                    ):
                        col_info, col_script = st.columns([1, 2])
                        with col_info:
                            st.markdown(f"**成绩**: {student['最近成绩']}分 ({student['成绩趋势']})")
                            st.markdown(f"**参与度**: {student['课堂参与度']}")
                            st.markdown(f"**作业率**: {student['作业完成率']}")
                            st.markdown(f"**沟通间隔**: {student['距上次沟通(天)']}天")
                            st.markdown(f"**家长态度**: {student['家长态度']}")
                        with col_script:
                            if "沟通话术" in student:
                                st.text_area(
                                    "沟通话术",
                                    value=student["沟通话术"],
                                    height=300,
                                    key=f"script_{student['学生姓名']}",
                                    label_visibility="collapsed"
                                )

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

        except ValueError as e:
            st.error(f"数据格式错误：{e}")
        except Exception as e:
            st.error(f"处理出错：{e}")

    with st.expander("📥 数据格式说明"):
        st.markdown("请使用以下标准格式准备学情数据：")
        st.dataframe(
            {
                "学生姓名": ["张三", "李四"],
                "年级": ["初二", "初三"],
                "班级": ["数学A班", "数学B班"],
                "最近成绩": [85, 72],
                "成绩趋势": ["上升", "下降"],
                "课堂参与度": ["积极", "一般"],
                "作业完成率": ["95%", "70%"],
                "距上次沟通(天)": [3, 15],
                "续费剩余(天)": [45, 12],
                "历史续费次数": [3, 1],
                "家长态度": ["积极", "中性"],
            },
            use_container_width=True,
        )


# ============================================================
# Tab 2: 家长答疑助手
# ============================================================
with tab2:
    st.header("家长答疑助手")
    st.info("输入家长问题，系统将自动分类并生成专业回复话术。")

    question = st.text_area(
        "请输入家长的问题",
        placeholder="例如：孩子最近成绩下降了怎么办？",
        height=100,
        key="qa_input"
    )

    col1, col2 = st.columns([1, 5])
    with col1:
        generate_btn = st.button("✨ 生成回复", type="primary", use_container_width=True)

    if generate_btn and question:
        with st.spinner("正在分析问题并生成回复..."):
            start_time = time.time()
            try:
                from core.qa_responder import generate_qa_response
                result = generate_qa_response(question)
                elapsed = time.time() - start_time
                log_event("qa_end", {"duration_s": round(elapsed, 2), "category": result["classification"].get("category", "unknown")})

                # 分类结果展示
                cls = result["classification"]
                category = cls.get("category", "未知")
                urgency = cls.get("urgency", "中")
                key_concern = cls.get("key_concern", "")

                category_colors = {
                    "教学类": "#4472C4",
                    "服务类": "#70AD47",
                    "续费类": "#FFC000",
                    "投诉类": "#FF4B4B",
                }
                cat_color = category_colors.get(category, "#888")

                st.markdown(f"### 分类结果")
                col_cat, col_urgency, col_concern = st.columns(3)
                with col_cat:
                    st.markdown(
                        f"<span style='background-color:{cat_color};color:white;padding:4px 12px;border-radius:4px;font-weight:bold'>{category}</span>",
                        unsafe_allow_html=True
                    )
                with col_urgency:
                    urg_colors = {"高": "#FF4B4B", "中": "#FFC000", "低": "#70AD47"}
                    urg_color = urg_colors.get(urgency, "#888")
                    st.markdown(
                        f"紧急度：<span style='background-color:{urg_color};color:white;padding:4px 12px;border-radius:4px'>{urgency}</span>",
                        unsafe_allow_html=True
                    )
                with col_concern:
                    st.markdown(f"**核心诉求**：{key_concern}")

                # SOP参考
                if result["sop_references"]:
                    st.markdown("### 📚 参考SOP")
                    for ref in result["sop_references"]:
                        st.markdown(f"- {ref['title']}（来源：{ref['source']}）")

                # 推荐回复
                st.markdown("### 💬 推荐回复话术")
                st.text_area(
                    "回复话术（可编辑后复制）",
                    value=result["response"],
                    height=200,
                    key="qa_response_output",
                    label_visibility="collapsed"
                )

                st.success(f"回复生成完成，耗时 {elapsed:.1f} 秒")

            except Exception as e:
                st.error(f"生成失败：{e}")
    elif generate_btn and not question:
        st.warning("请先输入家长的问题")

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
# Tab 3: 批量报告生成
# ============================================================
with tab3:
    st.header("学情报告批量生成")
    st.info("上传学情数据，一键批量生成个性化学生反馈报告。")

    uploaded_file2 = st.file_uploader(
        "上传学情数据",
        type=["xlsx", "xls"],
        key="report_upload",
        help="格式与学情分析模块相同"
    )

    if uploaded_file2:
        try:
            df = parse_uploaded_excel(uploaded_file2)
            st.success(f"已解析文件：{uploaded_file2.name}，共 {len(df)} 条学生数据")

            from core.student_analyzer import analyze_students
            from core.report_generator import batch_generate_reports

            # 先做分层分析
            if "report_analysis" not in st.session_state or st.session_state.get("_report_upload") != uploaded_file2.name:
                st.session_state["report_analysis"] = analyze_students(df)
                st.session_state["_report_upload"] = uploaded_file2.name
                st.session_state["reports_generated"] = False

            result = st.session_state["report_analysis"]

            # 分层预览
            st.subheader("分层预览")
            col_s, col_a, col_b, col_c = st.columns(4)
            ts = result["tier_stats"]
            col_s.metric("S级", ts["S"])
            col_a.metric("A级", ts["A"])
            col_b.metric("B级", ts["B"])
            col_c.metric("C级", ts["C"])

            # 批量生成按钮
            if not st.session_state.get("reports_generated"):
                if st.button("🚀 批量生成学情报告", type="primary", use_container_width=True):
                    progress_text = st.empty()
                    progress_bar = st.progress(0)

                    start_time = time.time()

                    def report_progress(current, total):
                        progress_bar.progress(current / total)
                        progress_text.text(f"正在生成：{current}/{total}")

                    reports = batch_generate_reports(result["students"], progress_callback=report_progress)
                    st.session_state["reports"] = reports
                    st.session_state["reports_generated"] = True
                    elapsed = time.time() - start_time

                    log_event("report_end", {
                        "student_count": len(df),
                        "duration_s": round(elapsed, 2)
                    })

                    progress_text.text(f"报告生成完成！共 {len(df)} 份，耗时 {elapsed:.1f} 秒")
                    st.success(f"批量报告生成完成！共 {len(df)} 份，耗时 {elapsed:.1f} 秒")
                    st.rerun()

            # 报告预览与导出
            if st.session_state.get("reports_generated"):
                reports = st.session_state["reports"]
                st.subheader("报告预览")

                selected_student = st.selectbox(
                    "选择学生查看报告",
                    [r["学生姓名"] for r in reports],
                    key="report_student_select"
                )
                selected_report = next((r for r in reports if r["学生姓名"] == selected_student), None)
                if selected_report:
                    st.markdown(f"**分层**: {selected_report['分层']}")
                    st.text_area(
                        "学情报告",
                        value=selected_report["学情报告"],
                        height=400,
                        key=f"report_{selected_student}",
                        label_visibility="collapsed"
                    )

                # 导出
                st.subheader("导出全部报告")
                output_filename = f"学情报告_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                output_path = os.path.join(OUTPUT_DIR, output_filename)
                export_reports_to_excel(reports, output_path)
                with open(output_path, "rb") as f:
                    st.download_button(
                        "📥 导出批量报告Excel",
                        data=f,
                        file_name=output_filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
                log_event("export", {"type": "report", "file": output_filename})

        except ValueError as e:
            st.error(f"数据格式错误：{e}")
        except Exception as e:
            st.error(f"处理出错：{e}")


# ============================================================
# Tab 4: 数据看板
# ============================================================
with tab4:
    st.header("数据看板")
    st.info("展示Agent使用数据与效率对比。")

    today_stats = get_daily_stats()
    all_stats = get_all_stats()

    # 今日数据
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
            today_stats.get("analysis_count", 0) * 180  # 假设手动分析300人需3小时=180分钟
            + today_stats.get("qa_count", 0) * 5  # 假设手动答疑每条5分钟
            + today_stats.get("report_count", 0) * 120  # 假设手动报告每份6分钟
        )
        st.metric("累计节省时间(分钟)", total_saved)

    # Agent耗时 vs 手动基准对比
    if today_stats["total_events"] > 0:
        st.subheader("效率对比（今日）")

        # 分析模块对比
        if today_stats["analysis_count"] > 0:
            agent_time = today_stats["analysis_total_time_s"]
            manual_time = today_stats["analysis_count"] * 180 * 60  # 分钟转秒
            st.markdown(f"**学情分析**: Agent {agent_time:.0f}秒 vs 手动基准 {manual_time:.0f}秒 → 节省 {(1 - agent_time/manual_time)*100:.1f}%")

        if today_stats["qa_count"] > 0:
            agent_time = today_stats["qa_total_time_s"]
            manual_time = today_stats["qa_count"] * 5 * 60
            st.markdown(f"**家长答疑**: Agent {agent_time:.0f}秒 vs 手动基准 {manual_time:.0f}秒 → 节省 {(1 - agent_time/manual_time)*100:.1f}%")

        if today_stats["report_count"] > 0:
            agent_time = today_stats["report_total_time_s"]
            manual_time = today_stats["report_count"] * 6 * 60
            st.markdown(f"**报告生成**: Agent {agent_time:.0f}秒 vs 手动基准 {manual_time:.0f}秒 → 节省 {(1 - agent_time/manual_time)*100:.1f}%")

    # 历史趋势
    if all_stats:
        st.subheader("历史趋势")
        stats_df = pd.DataFrame(all_stats)
        if len(stats_df) > 0:
            st.dataframe(stats_df, use_container_width=True)
    else:
        st.info("暂无历史数据，开始使用Agent后将自动记录。")

    # A/B测试说明
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
