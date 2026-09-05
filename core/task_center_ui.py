# -*- coding: utf-8 -*-
"""今日风险处理中心 — UI渲染模块

嵌入Tab1顶部（通过 st.container 占位实现"视觉在顶部、代码在分析后执行"），
读取 st.session_state["analysis_result"] 渲染今日任务驾驶舱与任务卡片。

安全约定：任何内部异常都不影响现有功能，仅显示警告。
"""
import streamlit as st
from datetime import datetime

from config import TIER_COLORS
from core import task_engine as engine
from utils.task_store import load_tasks, save_tasks

# 状态徽章（颜色+图标，与规格书一致）
STATUS_BADGE = {
    "待处理":     ("#FF4B4B", "🔴 待处理"),
    "处理中":     ("#1E88E5", "🔵 处理中"),
    "已完成":     ("#43A047", "🟢 已完成"),
    "待二次跟进": ("#F9A825", "🟡 待二次跟进"),
    "已超时":     ("#E53935", "⚠️ 已超时"),
    "已关闭":     ("#9E9E9E", "⚪ 已关闭"),
}

STATUS_FILTERS = ["全部", "待处理", "已超时", "处理中", "待二次跟进", "已完成", "已关闭"]


def _badge(text: str, color: str, extra: str = "") -> str:
    return (f"<span style='background:{color};color:white;padding:2px 8px;"
            f"border-radius:4px;font-size:0.78em;font-weight:600;white-space:nowrap'>{text}{extra}</span>")


def _metric_card(title: str, value: str, sub: str, bg: str, border: str) -> str:
    return f"""
    <div style='background:{bg};border:1px solid {border};border-radius:8px;
                padding:10px 14px;text-align:center'>
        <div style='color:#666;font-size:0.82em'>{title}</div>
        <div style='color:#222;font-size:1.45em;font-weight:700;margin:2px 0'>{value}</div>
        <div style='color:#888;font-size:0.75em'>{sub}</div>
    </div>
    """


# ============================================================
# 主入口
# ============================================================

def render_task_center():
    try:
        _render()
    except Exception as e:
        st.warning(f"今日风险处理中心渲染异常（不影响其他功能）：{e}")


def _render():
    analysis_result = st.session_state.get("analysis_result")
    upload_name = st.session_state.get("_upload_name")
    demo_mode = st.session_state.get("task_demo_mode", False)

    # ===== 标题栏 =====
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%);
        border-left: 4px solid #FF8C00;
        padding: 10px 16px;
        border-radius: 6px;
        margin-bottom: 8px;
    ">
        <span style="color:#E65100;font-size:15px;font-weight:700">🔥 今日风险处理中心</span>
        <span style="color:#8D6E63;font-size:12px;margin-left:10px">
            AI自动排序今日优先处理对象 · 任务执行 · 结果反馈 · 动态复评闭环
        </span>
    </div>
    """, unsafe_allow_html=True)

    # ===== Demo模式 =====
    if demo_mode:
        st.markdown("""
        <div style="background:#FFF9C4;border:1px dashed #FBC02D;border-radius:6px;
                    padding:8px 14px;margin-bottom:8px;color:#795548;font-size:0.85em">
            ⚠️ <b>当前为 Demo 演示数据（示例学员）</b>，非真实学员数据，仅用于展示任务闭环流程。
            上传学情表后自动切换为真实数据。
        </div>
        """, unsafe_allow_html=True)
        if "task_demo_tasks" not in st.session_state:
            st.session_state["task_demo_tasks"] = engine.get_demo_tasks()
        tasks = st.session_state["task_demo_tasks"]
        _render_tasks(tasks, is_demo=True)
        if st.button("📤 退出Demo，返回上传引导", key="exit_demo"):
            st.session_state.pop("task_demo_mode", None)
            st.session_state.pop("task_demo_tasks", None)
            st.rerun()
        return

    # ===== 真实数据模式 =====
    if analysis_result and upload_name:
        stored = load_tasks(upload_name)
        tasks = engine.sync_tasks_from_analysis(analysis_result, upload_name, stored)
        tasks = engine.check_overdue(tasks)
        save_tasks(upload_name, tasks)
        st.session_state["task_center_tasks"] = tasks
        _render_tasks(tasks, is_demo=False, upload_name=upload_name)
        return

    # ===== 无数据引导 =====
    st.markdown("""
    <div style="background:#FAFAFA;border:1px dashed #BDBDBD;border-radius:8px;
                padding:16px 20px;text-align:center">
        <div style="color:#555;font-size:0.95em;margin-bottom:6px">
            📤 上传学情表后，AI 将自动完成：<b>风险识别 → P1-P4分层 → 今日任务生成 → 优先级排序</b>
        </div>
        <div style="color:#999;font-size:0.8em">
            「今日风险处理中心」会告诉老师：今天最应该先处理哪些学生、为什么、具体做什么
        </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("▶️ 查看 Demo 演示（模拟数据）", key="enter_demo"):
        st.session_state["task_demo_mode"] = True
        st.rerun()


# ============================================================
# 驾驶舱 + 任务列表
# ============================================================

def _render_tasks(tasks: list, is_demo: bool, upload_name: str = ""):
    if not tasks:
        st.info("当前数据中无 P1-P3 风险学生，暂无需处理的今日任务。")
        return

    stats = engine.get_dashboard_stats(tasks)

    # ===== 今日风险总览（全部动态计算） =====
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(_metric_card(
            "今日风险", f"{stats['今日风险人数']}人",
            f"🔴 P1:{stats['P1']} ｜ 🟠 P2:{stats['P2']} ｜ 🟡 P3:{stats['P3']}",
            "#FFF5F5", "#FFCDD2"), unsafe_allow_html=True)
    with m2:
        pct = f"{stats['处理进度']:.0%}"
        st.markdown(_metric_card(
            "今日处理进度", f"{stats['已完成']} / {stats['总数']}", pct,
            "#F1F8E9", "#C5E1A5"), unsafe_allow_html=True)
    with m3:
        st.markdown(_metric_card(
            "⚠️ 超时风险", f"{stats['超时风险']}人",
            "已进入重点升级队列" if stats["超时风险"] else "暂无超时任务",
            "#FFF8E1" if stats["超时风险"] else "#FAFAFA", "#FFE082" if stats["超时风险"] else "#E0E0E0",
        ), unsafe_allow_html=True)
    with m4:
        st.markdown(_metric_card(
            "🔄 待二次跟进", f"{stats['待二次跟进']}人",
            f"重点升级 {stats['重点升级']} 人" if stats["重点升级"] else "按约定时间回访",
            "#E3F2FD", "#BBDEFB"), unsafe_allow_html=True)
    with m5:
        st.markdown(_metric_card(
            "✅ 风险闭环率", f"{stats['风险闭环率']:.0%}",
            "已反馈结果 ÷ 应处理人数",
            "#F3E5F5", "#E1BEE7"), unsafe_allow_html=True)
    st.caption("预留指标：服务及时率、服务覆盖率（需完整服务周期数据后启用，当前仅展示计算逻辑）")

    if stats["超时风险"] > 0:
        st.markdown(
            f"<div style='background:#FFEBEE;border-left:3px solid #E53935;padding:6px 12px;"
            f"border-radius:4px;color:#B71C1C;font-size:0.85em'>"
            f"⚠️ <b>{stats['超时风险']} 项任务已超时</b>，AI 已自动置顶并进入重点升级处理队列，请优先完成。</div>",
            unsafe_allow_html=True)

    # ===== 筛选 + 任务卡片 =====
    sorted_tasks = engine.sort_tasks(tasks)

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        status_filter = st.selectbox("状态筛选", STATUS_FILTERS, key="tc_status_filter")
    with col_f2:
        tier_filter = st.selectbox("等级筛选", ["全部", "P1", "P2", "P3"], key="tc_tier_filter")
    with col_f3:
        st.caption("")  # 对齐占位

    def _match(t):
        if status_filter != "全部" and t["任务状态"] != status_filter:
            return False
        if tier_filter != "全部" and t["当前风险等级"] != tier_filter:
            return False
        return True

    visible = [t for t in sorted_tasks if _match(t)]
    if not visible:
        st.info("当前筛选条件下无任务，可调整筛选查看。")
        return

    # 分页展示（任务多时避免页面过长）
    limit_key = f"tc_limit_{upload_name or 'demo'}"
    limit = st.session_state.get(limit_key, 10)
    st.markdown(f"**📋 今日任务清单**（AI已按紧迫度排序，共 {len(visible)} 项）")

    # 学生字典（供AI策略生成使用，含完整画像）
    students_by_name = {}
    if not is_demo and st.session_state.get("analysis_result"):
        for s in st.session_state["analysis_result"].get("students", []):
            students_by_name[s.get("学生姓名")] = s

    for idx, t in enumerate(visible[:limit]):
        _render_task_card(t, idx, students_by_name, is_demo, upload_name)

    if len(visible) > limit:
        c_more, c_all = st.columns([1, 1])
        with c_more:
            if st.button(f"⬇️ 显示更多（剩余 {len(visible) - limit} 项）", key="tc_more", use_container_width=True):
                st.session_state[limit_key] = limit + 10
                st.rerun()
        with c_all:
            if st.button("📄 显示全部", key="tc_all", use_container_width=True):
                st.session_state[limit_key] = len(visible)
                st.rerun()


# ============================================================
# 单张任务卡片
# ============================================================

def _render_task_card(t: dict, idx: int, students_by_name: dict, is_demo: bool, upload_name: str):
    tid = t["task_id"]
    tier = t.get("当前风险等级", "P3")
    tier_color = TIER_COLORS.get(tier, "#888")
    status = t.get("任务状态", "待处理")
    s_color, s_text = STATUS_BADGE.get(status, ("#9E9E9E", status))
    demo_tag = " <span style='color:#F57F17;font-size:0.7em'>Demo模拟数据</span>" if is_demo else ""

    with st.container(border=True):
        # --- 第一层：今天最重要的事（谁、什么等级、什么状态） ---
        c1, c2, c3, c4 = st.columns([1.6, 1.1, 1.5, 2.2])
        with c1:
            st.markdown(
                f"**{t['学生姓名']}** {demo_tag}<br>"
                f"{_badge(tier, tier_color)}",
                unsafe_allow_html=True)
        with c2:
            st.markdown(_badge(s_text, s_color), unsafe_allow_html=True)
            if t.get("升级标记") and status in ("待处理", "处理中", "待二次跟进", "已超时"):
                st.markdown("<span style='color:#B71C1C;font-size:0.72em'>⚠️ 重点升级</span>", unsafe_allow_html=True)
        with c3:
            score = t.get("最近成绩")
            score_txt = f"{score:g}分" if isinstance(score, (int, float)) else (str(score) if score else "暂无成绩数据")
            trend = t.get("成绩趋势") or "-"
            st.markdown(
                f"<span style='color:#666;font-size:0.8em'>最近成绩 <b>{score_txt}</b> ｜ 趋势 {trend}</span>",
                unsafe_allow_html=True)
            st.caption(f"最近沟通：{t.get('最近沟通时间', '暂无数据')}")
        with c4:
            st.markdown(
                f"<span style='color:#666;font-size:0.8em'>⏰ 建议完成 <b>{t.get('建议完成时间', '-')}</b></span>",
                unsafe_allow_html=True)
            st.caption(f"下一步：{t.get('下一步动作', '-')}")

        # --- 风险原因 + 今日动作（第二三层：为什么、做什么） ---
        st.markdown(
            f"<span style='color:#555;font-size:0.83em'>🔎 <b>风险原因</b>：{t.get('风险原因', '暂无数据')}</span>",
            unsafe_allow_html=True)
        st.markdown(
            f"<span style='color:#1565C0;font-size:0.86em'>🎯 <b>AI今日动作</b>：{t.get('今日建议动作', '-')}</span>",
            unsafe_allow_html=True)

        # --- AI优先原因 + 今日动作详情（可展开） ---
        with st.expander("💡 AI为什么让我先处理他？（优先原因 · 沟通目标 · 完成标准）", expanded=(idx == 0)):
            st.markdown("**【AI优先原因】**（基于真实学情数据）")
            for r in t.get("优先原因", []):
                st.markdown(f"- {r}")
            detail = t.get("今日动作详情", {})
            st.markdown(f"**【AI今日动作】** {detail.get('动作', t.get('今日建议动作', '-'))}")
            dc1, dc2 = st.columns(2)
            with dc1:
                st.markdown(f"**沟通目标**\n\n{detail.get('沟通目标', '-')}")
                st.markdown(f"**沟通重点**\n\n{detail.get('沟通重点', '-')}")
            with dc2:
                st.markdown(f"**完成标准**\n\n{detail.get('完成标准', '-')}")
                if t.get("成绩变化"):
                    st.caption(f"数据依据：{t['成绩变化']}")

        # --- 沟通结果历史 ---
        if t.get("沟通结果历史"):
            with st.expander(f"📝 沟通结果记录（{len(t['沟通结果历史'])} 次）"):
                for r in t["沟通结果历史"]:
                    note = f" ｜ 备注：{r['备注']}" if r.get("备注") else ""
                    st.markdown(f"- **{r['时间']}** — {r['结果']}{note}")

        # --- AI复评结果（第二阶段：AI动态复评展示） ---
        r = t.get("AI复评结果")
        if r:
            is_rule = r.get("模式", "").startswith("规则")
            need_review = r.get("需人工复核", False)
            header = ("⚖️ AI复评结果（规则兜底）" if is_rule else "🤖 AI复评结果") + \
                     (" · ⚠️ 需人工复核" if need_review else "")
            with st.expander(header, expanded=True):
                if need_review:
                    st.markdown(
                        "<div style='background:#FFEBEE;border-left:3px solid #E53935;padding:8px 12px;"
                        "border-radius:4px;color:#B71C1C;font-size:0.88em'>"
                        "⚠️ <b>信息不足，建议人工复核</b> — AI无法基于现有数据做出可靠判断，"
                        "请人工确认学生情况后再决定等级与跟进安排</div>", unsafe_allow_html=True)
                rev_tier = r.get("当前风险等级", "-")
                rev_color = TIER_COLORS.get(rev_tier, "#888")
                direction = r.get("风险方向", "保持")
                dir_icon = {"下降": "📉", "上升": "📈", "保持": "➡️"}.get(direction, "➡️")
                mode_tag = "规则兜底" if is_rule else "AI动态复评"
                st.markdown(
                    f"{_badge(rev_tier, rev_color)} "
                    f"<span style='color:#555;font-size:0.85em'>{dir_icon} 风险{direction} · {mode_tag} · {r.get('时间', '')}</span>",
                    unsafe_allow_html=True)
                st.markdown(f"**复评结论**：{r.get('复评结论', '-')}")
                st.markdown(f"**风险变化原因**：{r.get('判断依据', '-')}")
                st.markdown(f"**下一步行动**：{r.get('下一步动作', '-')}")
                st.caption(f"基于沟通结果「{r.get('本次沟通结果', '-')}」综合学情数据、历史沟通记录与老师备注动态判断")

        # --- 风险时间线（第四层：做完之后下一步） ---
        with st.expander("📜 风险服务时间线"):
            for e in t.get("时间线", []):
                st.markdown(f"**{e['时间']}** — {e['事件']}")
                if e.get("详情"):
                    st.caption(e["详情"])

        # --- AI策略（调用现有策略引擎，不重复开发） ---
        script_key = f"tc_script_{tid}"
        has_script = script_key in st.session_state
        with st.expander("🧠 AI沟通策略与话术" + ("（已生成 ✓）" if has_script else "")):
            if has_script:
                st.markdown(st.session_state[script_key])
            elif is_demo:
                st.caption("Demo 模式不调用 AI 生成（避免虚构策略），上传真实学情表后可一键生成。")
            else:
                if st.button("✨ 生成AI策略与话术", key=f"gen_ai_{tid}", type="primary"):
                    student = students_by_name.get(t["学生姓名"])
                    if student is None:
                        st.error("未找到该学生的分析数据，无法生成策略")
                    else:
                        with st.spinner(f"正在为 {t['学生姓名']} 生成沟通策略与话术..."):
                            try:
                                from core.script_generator import generate_student_script_unified
                                script = generate_student_script_unified(student)
                                st.session_state[script_key] = script
                                st.rerun()
                            except Exception as ex:
                                st.error(f"策略生成失败：{ex}")

        # --- 操作按钮（明显但不泛滥） ---
        bc = st.columns(5)
        col_i = 0
        if status in ("待处理", "已超时", "待二次跟进"):
            with bc[col_i]:
                btn_txt = "🚀 立即处理" if status in ("待处理", "已超时") else "🚀 开始二次跟进"
                if st.button(btn_txt, key=f"go_{tid}", type="primary", use_container_width=True):
                    _mutate(t, engine.start_task, tasks_key=_tasks_key(is_demo), upload_name=upload_name, task_id=tid)
            col_i += 1
        if status in ("待处理", "处理中", "已超时", "待二次跟进"):
            with bc[col_i]:
                with st.popover("✅ 完成跟进", key=f"done_{tid}", use_container_width=True):
                    st.markdown("**沟通结果反馈**（完成后 AI 动态复评并生成下一步）")
                    result = st.selectbox("本次沟通结果", engine.COMM_RESULTS, key=f"cr_{tid}")
                    note = st.text_area("老师备注（选填，AI复评的重要依据）", key=f"note_{tid}", height=68)
                    if st.button("提交并完成跟进", key=f"submit_{tid}", type="primary", use_container_width=True):
                        student = students_by_name.get(t["学生姓名"]) if not is_demo else None
                        with st.spinner("AI动态复评中（综合学情、历史沟通与备注）..." if not is_demo else "处理中..."):
                            _mutate(t, engine.complete_task, tasks_key=_tasks_key(is_demo),
                                    upload_name=upload_name, task_id=tid,
                                    comm_result=result, teacher_note=note,
                                    student_context=student, use_ai=not is_demo)
            col_i += 1
        if status in ("待处理", "处理中", "待二次跟进", "已超时"):
            with bc[col_i]:
                with st.popover("📅 安排二次跟进", key=f"fu_{tid}", use_container_width=True):
                    days = st.number_input("几天后跟进", min_value=0, max_value=30, value=3, key=f"days_{tid}")
                    if st.button("确认安排", key=f"fu_ok_{tid}", use_container_width=True):
                        _mutate(t, engine.schedule_followup, tasks_key=_tasks_key(is_demo),
                                upload_name=upload_name, task_id=tid, days=int(days))
            col_i += 1
        if status == "待二次跟进":
            with bc[col_i]:
                if st.button("🏁 确认闭环完成", key=f"fin_{tid}", use_container_width=True):
                    _mutate(t, engine.finish_task, tasks_key=_tasks_key(is_demo),
                            upload_name=upload_name, task_id=tid)
            col_i += 1
        if status != "已关闭":
            with bc[col_i]:
                with st.popover("⚪ 关闭任务", key=f"cl_{tid}", use_container_width=True):
                    reason = st.text_input("关闭原因（风险解除/无需跟进）", key=f"cl_r_{tid}")
                    if st.button("确认关闭", key=f"cl_ok_{tid}", use_container_width=True):
                        _mutate(t, engine.close_task, tasks_key=_tasks_key(is_demo),
                                upload_name=upload_name, task_id=tid, reason=reason)


# ============================================================
# 变更统一处理：执行动作 → 持久化 → 刷新
# ============================================================

def _tasks_key(is_demo: bool) -> str:
    return "task_demo_tasks" if is_demo else "task_center_tasks"


def _mutate(task: dict, action, tasks_key: str, upload_name: str, task_id: str, **kwargs):
    """执行任务动作并持久化（真实数据写文件；Demo仅会话内）"""
    tasks = st.session_state.get(tasks_key, [])
    if not tasks:
        return
    tasks = action(tasks, task_id, **kwargs)
    st.session_state[tasks_key] = tasks
    if upload_name and not task.get("is_demo"):
        save_tasks(upload_name, tasks)
    st.rerun()
