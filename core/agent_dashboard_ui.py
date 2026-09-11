# -*- coding: utf-8 -*-
"""🏠 AI服务驾驶舱 — UI渲染（老板视角首页）

作为应用默认首页，展示「AI今天替团队做了什么」：
- 今日学员服务概况（总学员 / 立即处理 / 持续观察 / 无需人工介入 / 数据待确认）
- AI今日自动完成清单
- AI自动化率 + 人工介入率（关键管理指标）
- AI服务运营驾驶舱（老板指标卡）
- 📌 今日AI任务（立即处理 / 今日处理 / 持续观察）
- 闭环进度漏斗

安全约定：任何内部异常都不影响其他 Tab，仅显示提示，绝不抛出中断。
"""
import streamlit as st
from datetime import datetime

from config import TIER_COLORS

try:
    from core import agent_decision as ad
    from core import agent_dashboard as dashboard
    from core.risk_followup_center import RiskFollowupStore
    from utils.task_store import load_tasks
except Exception:  # pragma: no cover
    ad = dashboard = load_tasks = None
    RiskFollowupStore = None


# ============================================================
# 工具：卡片 / 徽章
# ============================================================

def _metric_card(title, value, sub, bg, border, accent):
    return f"""
    <div style='background:{bg};border:1px solid {border};border-radius:8px;
                padding:10px 14px;text-align:center'>
        <div style='color:#666;font-size:0.82em'>{title}</div>
        <div style='color:{accent};font-size:1.7em;font-weight:800;margin:2px 0;line-height:1.1'>{value}</div>
        <div style='color:#888;font-size:0.74em'>{sub}</div>
    </div>
    """


def _badge(text, color):
    return (f"<span style='background:{color};color:white;padding:1px 8px;border-radius:4px;"
            f"font-size:0.72em;font-weight:700;white-space:nowrap'>{text}</span>")


LevelColor = {
    "立即处理": "#C62828",
    "今日处理": "#EF6C00",
    "持续观察": "#F9A825",
    "AI自动跟踪": "#2E7D32",
}
LevelIcon = {
    "立即处理": "🔴",
    "今日处理": "🟠",
    "持续观察": "🟡",
    "AI自动跟踪": "🟢",
}


# ============================================================
# 主入口
# ============================================================

def render_dashboard():
    try:
        _render()
    except Exception as e:  # pragma: no cover
        st.warning(f"AI服务驾驶舱渲染异常（不影响其他功能）：{e}")


def _render():
    analysis_result = st.session_state.get("analysis_result")
    upload_name = st.session_state.get("_upload_name")

    _header()

    # ---------- Demo 模式 ----------
    if st.session_state.get("agent_demo_mode"):
        _render_demo()
        return

    # ---------- 无数据引导 ----------
    if not analysis_result:
        _empty_state()
        return

    # ---------- 有数据：完整驾驶舱 ----------
    tasks = _get_tasks(analysis_result, upload_name)
    decisions = ad.build_agent_tasks(analysis_result, tasks)
    stats = dashboard.compute_agent_stats(analysis_result, tasks, decisions)

    _overview(stats, analysis_result)
    _resource_allocation(analysis_result, tasks, decisions)
    _ai_actions_checklist(stats)
    _automation_rates(stats)
    _boss_metrics(stats)
    _service_effect(tasks)
    _funnel(stats, tasks)
    _today_tasks(decisions)
    _service_review(analysis_result, tasks, decisions)


# ============================================================
# 各部分渲染
# ============================================================

def _header():
    st.markdown("""
    <div style="
        background: linear-gradient(135deg, #1a237e 0%, #0d47a1 55%, #00838f 100%);
        padding: 18px 22px; border-radius: 10px; margin-bottom: 12px; color: #fff;
    ">
        <div style="font-size:1.35em; font-weight:800;">🏠 AI服务运营驾驶舱</div>
        <div style="font-size:0.86em; opacity:0.9; margin-top:4px;">
            AI替二讲老师持续监测风险 · 自动决策 · 生成任务 · 追踪跟进 · 动态复评
        </div>
        <div style="font-size:0.78em; opacity:0.75; margin-top:8px;">
            「老师不负责找问题，AI负责找问题；老师只处理AI认为必须由人处理的问题。」
        </div>
    </div>
    """, unsafe_allow_html=True)


def _overview(stats, analysis_result):
    # 数据待确认：缺失维度非空的学生数
    students = (analysis_result or {}).get("students", [])
    data_uncertain = sum(1 for s in students if s.get("缺失维度"))

    st.markdown("### 今日学员服务概况")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(_metric_card("总学员", f"{stats['总学员数']}人", "AI已自动分析", "#F5F7FF", "#D7DFFF", "#1a237e"), unsafe_allow_html=True)
    with c2:
        st.markdown(_metric_card("🔴 立即处理", f"{stats['立即处理']}人", "今日必须联系", "#FFEAEA", "#FFCDD2", "#C62828"), unsafe_allow_html=True)
    with c3:
        st.markdown(_metric_card("🟠 持续观察", f"{stats['持续观察']}人", "AI自动复查", "#FFF8E1", "#FFE082", "#EF6C00"), unsafe_allow_html=True)
    with c4:
        st.markdown(_metric_card("🟢 无需人工介入", f"{stats['AI自动跟踪']}人", "AI自主监测", "#E8F5E9", "#A5D6A7", "#2E7D32"), unsafe_allow_html=True)
    with c5:
        st.markdown(_metric_card("⚠️ 数据待确认", f"{data_uncertain}人", "建议人工核实", "#ECEFF1", "#CFD8DC", "#546E7A"), unsafe_allow_html=True)


def _ai_actions_checklist(stats):
    st.markdown("### ⚡ AI今日自动完成")
    checklist = dashboard.build_ai_actions_checklist(
        st.session_state.get("analysis_result"),
        _get_tasks(st.session_state.get("analysis_result"), st.session_state.get("_upload_name")),
    )
    items = "".join(
        f"<span style='display:inline-block;background:#F1F8E9;color:#33691E;border:1px solid #C5E1A5;"
        f"border-radius:20px;padding:4px 12px;margin:3px 6px 3px 0;font-size:0.82em'>"
        f"✓ {label} <b>{num}</b></span>" for label, num in checklist
    )
    st.markdown(f"<div>{items}</div>", unsafe_allow_html=True)
    st.caption("AI不是分析完就结束，而是在持续运营整个学员池。")


def _automation_rates(stats):
    st.markdown("### 🤖 AI处理效率")
    c1, c2 = st.columns(2)
    r1 = stats["AI自动化率"]
    r2 = stats["人工介入率"]
    with c1:
        st.markdown(_metric_card(
            "AI自动处理率", f"{r1:.0%}",
            f"{stats['AI自动跟踪'] + stats['持续观察']}人由AI接管监测/观察",
            "#F1F8E9", "#C5E1A5", "#2E7D32"), unsafe_allow_html=True)
    with c2:
        st.markdown(_metric_card(
            "人工介入率", f"{r2:.1%}",
            f"仅 {stats['需人工介入']} 人需老师今日联系",
            "#FFF3E0", "#FFE0B2", "#EF6C00"), unsafe_allow_html=True)
    st.caption("AI把二讲老师从「逐个盯学生」，变成「只处理AI筛选出的关键问题」；AI自动化 ≠ AI替代老师。")


def _boss_metrics(stats):
    st.markdown("### 📊 AI服务运营驾驶舱")
    tier = stats["等级分布"]
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.markdown(_metric_card("学员池", f"{stats['总学员数']}人",
            f"P1:{tier['P1']}｜P2:{tier['P2']}｜P3:{tier['P3']}｜正常:{tier['P4']}",
            "#F5F7FF", "#D7DFFF", "#1a237e"), unsafe_allow_html=True)
    with m2:
        st.markdown(_metric_card("今日AI自动决策", f"{stats['风险学员数']}人",
            "识别并决策风险学员", "#FFF8E1", "#FFE082", "#EF6C00"), unsafe_allow_html=True)
    with m3:
        st.markdown(_metric_card("今日需人工介入", f"{stats['需人工介入']}人",
            f"已完成 {stats['已完成']} ｜ 待处理 {stats['待处理']}", "#FFEAEA", "#FFCDD2", "#C62828"), unsafe_allow_html=True)
    with m4:
        st.markdown(_metric_card("风险流转", f"缓解{stats['风险已缓解']} / 升级{stats['风险升级']}人",
            f"逾期 {stats['已逾期']} ｜ 重点升级 {stats['重点升级']}",
            "#E8F5E9", "#A5D6A7", "#2E7D32"), unsafe_allow_html=True)
    with m5:
        st.markdown(_metric_card("闭环率", f"{stats['人工介入率']:.1%}",
            "AI筛出需人的关键问题占比", "#F3E5F5", "#E1BEE7", "#6A1B9A"), unsafe_allow_html=True)


def _load_records():
    """加载 Tab3 风险跟进记录（用于效果评估与策略记忆，安全兜底为空）。"""
    try:
        return RiskFollowupStore().load() if RiskFollowupStore else {}
    except Exception:
        return {}


def _fmt_rate(v):
    return f"{v:.1%}" if isinstance(v, (int, float)) else v


def _iv_color(level):
    return {"高": "#C62828", "中": "#EF6C00", "低": "#2E7D32"}.get(level, "#888")


def _resource_allocation(analysis_result, tasks, decisions):
    st.markdown("### 🎯 AI资源决策")
    alloc = dashboard.compute_resource_allocation(analysis_result, tasks, decisions)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(_metric_card("🔴 重点人工介入", f"{alloc['重点人工介入']}人",
            "今日真正需要处理", "#FFEAEA", "#FFCDD2", "#C62828"), unsafe_allow_html=True)
    with c2:
        st.markdown(_metric_card("💬 轻量触达", f"{alloc['轻量触达']}人",
            "低频/微信触达", "#FFF3E0", "#FFE0B2", "#EF6C00"), unsafe_allow_html=True)
    with c3:
        st.markdown(_metric_card("🟠 持续观察", f"{alloc['持续观察']}人",
            "AI自动复查", "#FFF8E1", "#FFE082", "#F9A825"), unsafe_allow_html=True)
    with c4:
        st.markdown(_metric_card("🟢 AI自动管理", f"{alloc['AI自动管理']}人",
            "无需人工介入", "#E8F5E9", "#A5D6A7", "#2E7D32"), unsafe_allow_html=True)

    top = alloc.get("建议优先投入") or []
    est = alloc.get("人工投入估算") or {}
    if top:
        st.markdown(f"**👩‍🏫 建议优先投入**：{'、'.join(top)}")
    st.caption(f"⏱ 今日预计人工投入：约 {est.get('小时', 0)} 小时（{est.get('说明', '')}）")


def _service_effect(tasks):
    st.markdown("### 📈 AI服务效果")
    eff = dashboard.compute_service_effect(_load_records(), tasks)
    metrics = [
        ("风险缓解率", eff["风险缓解率"]),
        ("跟进后改善率", eff["跟进后改善率"]),
        ("任务及时处理率", eff["任务及时处理率"]),
        ("重复跟进率", eff["重复跟进率"]),
        ("风险升级率", eff["风险升级率"]),
    ]
    cols = st.columns(len(metrics))
    for col, (label, val) in zip(cols, metrics):
        with col:
            st.markdown(_metric_card(label, _fmt_rate(val),
                f"已跟进 {eff['已跟进人数']} 人", "#F5F7FF", "#D7DFFF", "#1a237e"),
                unsafe_allow_html=True)
    st.caption("指标均基于真实跟进记录计算；无数据项显示「待积累数据」，不虚构数值。")


def _service_review(analysis_result, tasks, decisions):
    st.markdown("### 🧠 AI服务复盘")
    students = (analysis_result or {}).get("students", [])
    review = dashboard.compute_service_review(_load_records(), students, tasks, decisions)
    items = [
        ("发现风险", review["发现风险"], "#C62828"),
        ("AI自动观察", review["AI自动观察"], "#F9A825"),
        ("人工介入", review["人工介入"], "#EF6C00"),
        ("风险改善", review["风险改善"], "#2E7D32"),
        ("风险升级", review["风险升级"], "#C62828"),
        ("无明显变化", review["无明显变化"], "#9E9E9E"),
    ]
    cols = st.columns(len(items))
    for col, (label, num, color) in zip(cols, items):
        with col:
            st.markdown(_metric_card(label, f"{num}人", "真实数据", "#F5F7FF", "#D7DFFF", color),
                        unsafe_allow_html=True)
    st.markdown(f"**🔬 策略洞察**（样本状态：{review.get('样本状态', '')}）")
    for line in (review.get("策略洞察") or []):
        st.caption("· " + line)


def _funnel(stats, tasks):
    st.markdown("### 🔁 今日风险处理漏斗")
    contacted = sum(1 for t in tasks if t.get("沟通结果历史"))
    funnel = [
        ("待联系", stats["需人工介入"], "#C62828"),
        ("已联系", contacted, "#F9A825"),
        ("待观察", stats["持续观察"], "#EF6C00"),
        ("风险缓解", stats["风险已缓解"], "#1565C0"),
    ]
    box = []
    for i, (label, count, color) in enumerate(funnel):
        if i:
            box.append('<div style="color:#90A4AE;font-size:16px;align-self:center;">→</div>')
        box.append(
            f'<div style="flex:1;min-width:110px;border:1px solid #e8eaf0;border-radius:6px;'
            f'padding:6px 10px;text-align:center;background:#fff;">'
            f'<div style="font-size:22px;font-weight:800;color:{color};">{count}</div>'
            f'<div style="font-size:12px;color:#555;">{label}</div></div>')
    st.markdown('<div style="display:flex;gap:8px;align-items:stretch;flex-wrap:wrap;">' + "".join(box) + "</div>",
                unsafe_allow_html=True)


def _today_tasks(decisions):
    st.markdown("### 📌 今日AI任务")
    buckets = ad.bucket_decisions(decisions)

    if not decisions:
        st.info("当前暂无风险学员，AI持续监测中。")
        return

    _render_task_group("🔴 立即处理（今日必须联系）", buckets["立即处理"], expanded_default=True)
    _render_task_group("🟠 今日处理（今日优先级）", buckets["今日处理"], expanded_default=True)
    _render_task_group("🟡 持续观察（AI自动复查，暂不打扰）", buckets["持续观察"], expanded_default=False)


def _render_task_group(title, items, expanded_default):
    if not items:
        return
    st.markdown(f"**{title}**（{len(items)}人）")
    for d in items:
        _render_task_card(d, expanded_default)


def _render_task_card(d, expanded_default):
    tier = d.get("分层", "P3")
    tier_color = TIER_COLORS.get(tier, "#888")
    level = d["决策档位"]
    level_color = LevelColor.get(level, "#888")
    icon = LevelIcon.get(level, "🟡")
    score = d.get("风险分")
    score_txt = f"{int(score)}" if isinstance(score, (int, float)) else "-"
    trend = d.get("成绩趋势") or "-"
    action = d.get("建议动作", "-")

    with st.expander(f"{icon} {d['学员姓名']}｜{tier}｜风险分{score_txt}｜趋势{trend}", expanded=expanded_default):
        st.markdown(
            f"{_badge(tier, tier_color)} {_badge(level, level_color)} "
            f"<span style='color:#666;font-size:0.85em'>风险状态：{d.get('风险状态','-')}</span>",
            unsafe_allow_html=True)
        st.markdown(f"**🎯 AI建议**：{action}")
        if d.get("复查时间"):
            st.markdown(f"**⏰ 复查时间**：{d['复查时间']} ｜ **自动化分类**：{d['自动化分类']}")
        iv = d.get("干预价值")
        if isinstance(iv, (int, float)):
            iv_level = d.get('干预价值等级', '')
            iv_badge = _badge(f"{iv_level}·{int(iv)}分", _iv_color(iv_level))
            st.markdown(f"**🎯 AI干预价值**：{iv_badge}", unsafe_allow_html=True)
        strat = d.get("服务策略") or {}
        if strat.get("推荐策略"):
            st.markdown(f"**{strat.get('策略图标', '👀')} 推荐策略**：{strat['推荐策略']}"
                        f"｜预计检查：{strat.get('预计检查', '持续监测')}")
            for r in (strat.get("推荐原因") or []):
                st.markdown(f"　· {r}")
        reasons = d.get("判断依据") or []
        if reasons:
            st.markdown("**💡 AI判断依据**（基于真实数据）")
            for r in reasons:
                st.markdown(f"- {r}")
        reason = d.get("决策理由") or {}
        if reason and reason.get("为什么TA"):
            with st.expander("🔎 为什么是TA？AI决策理由", expanded=False):
                for label in ("为什么TA", "为什么现在", "为什么这种方式", "为什么不是别人"):
                    parts = reason.get(label) or []
                    if parts:
                        st.markdown(f"**{label}**：" + "；".join(parts))
        if d.get("风险触发"):
            st.caption("风险触发：" + "、".join(str(x) for x in d["风险触发"][:4]))
        st.caption("前往「📊 学情续费预警系统」或「📋 风险优先处理中心」执行跟进与记录。")


# ============================================================
# 数据获取（安全加载任务态，复用既有存储）
# ============================================================

def _get_tasks(analysis_result, upload_name):
    """获取任务态：优先 session_state，其次从持久化加载并同步。"""
    cached = st.session_state.get("task_center_tasks")
    if cached:
        return cached
    if not analysis_result or not upload_name or not load_tasks:
        return []
    try:
        from core import task_engine
        stored = load_tasks(upload_name)
        tasks = task_engine.sync_tasks_from_analysis(analysis_result, upload_name, stored)
        tasks = task_engine.check_overdue(tasks)
        st.session_state["task_center_tasks"] = tasks
        return tasks
    except Exception as e:
        print(f"[Dashboard] 任务态加载失败: {e}")
        return []


# ============================================================
# 空数据 / Demo
# ============================================================

def _empty_state():
    st.markdown("""
    <div style="background:#FAFAFA;border:1px dashed #BDBDBD;border-radius:10px;
                padding:26px 24px;text-align:center">
        <div style="font-size:1.8em;margin-bottom:6px">🧠</div>
        <div style="color:#444;font-size:1em;font-weight:600;margin-bottom:8px">
            上传学情数据后，AI将自动完成风险监测与今日任务决策
        </div>
        <div style="color:#888;font-size:0.85em;max-width:640px;margin:0 auto 14px auto">
            前往「📊 学情续费预警系统」上传学情 Excel，AI 会自动：识别风险 → 判断该联系谁 →
            生成今日任务 → 生成沟通方案 → 追踪跟进 → 动态复评。你不需要从几十个学生里自己找问题。
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶️ 查看 Demo 演示（模拟决策）", key="agent_enter_demo", use_container_width=True):
            st.session_state["agent_demo_mode"] = True
            st.rerun()
    with c2:
        if st.button("📊 前往上传学情数据", key="agent_goto_upload", use_container_width=True):
            st.session_state["_goto_tab"] = "学情续费预警系统"
            st.rerun()


def _render_demo():
    st.markdown("""
    <div style="background:#FFF9C4;border:1px dashed #FBC02D;border-radius:6px;
                padding:8px 14px;margin-bottom:10px;color:#795548;font-size:0.85em">
        ⚠️ 当前为 <b>Demo 演示数据（示例学员）</b>，仅用于展示 AI 决策中枢，非真实数据。
    </div>
    """, unsafe_allow_html=True)

    # 构造轻量 demo 决策集（不含真实学员，仅展示决策分档逻辑）
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    demo = [
        {"学员姓名": "示例·张博", "分层": "P1", "风险分": 100, "成绩趋势": "下降",
         "决策档位": "立即处理", "档位键": "red", "是否需联系": True, "联系优先级": "高",
         "建议动作": "今日电话跟进", "风险状态": "仍在", "复查时间": "今日",
         "判断依据": ["分层P1（风险分100），成绩趋势「下降」，持续恶化",
                    "风险持续恶化且无改善信号，须今日人工介入"],
         "自动化分类": "人工决策", "风险触发": ["成绩下降", "参与度下降"]},
        {"学员姓名": "示例·康嘉益", "分层": "P1", "风险分": 100, "成绩趋势": "上升",
         "决策档位": "持续观察", "档位键": "yellow", "是否需联系": False, "联系优先级": "中",
         "建议动作": "暂不立即联系，3天后复查最新学习数据", "风险状态": "仍在", "复查时间": "3天后",
         "判断依据": ["分层P1（风险分100）为最高风险，但成绩趋势「上升」，出现明确改善信号",
                    "依据时间优先原则：风险仍高，但近期回升，不宜重复打扰家长"],
         "自动化分类": "AI辅助处理", "风险触发": ["参与度偏低"]},
        {"学员姓名": "示例·李明轩", "分层": "P2", "风险分": 72, "成绩趋势": "下降",
         "决策档位": "今日处理", "档位键": "orange", "是否需联系": True, "联系优先级": "中",
         "建议动作": "今日电话沟通", "风险状态": "仍在", "复查时间": "今日",
         "判断依据": ["分层P2（风险分72），成绩趋势「下降」持续下降"],
         "自动化分类": "人工决策", "风险触发": ["练习提交率低"]},
        {"学员姓名": "示例·韦宇熙", "分层": "P3", "风险分": 40, "成绩趋势": "平稳",
         "决策档位": "AI自动跟踪", "档位键": "green", "是否需联系": False, "联系优先级": "低",
         "建议动作": "无需人工介入，AI自动跟踪", "风险状态": "观察项", "复查时间": None,
         "判断依据": ["分层P3（风险分40），趋势「平稳」，整体相对稳定"],
         "自动化分类": "AI自主处理", "风险触发": []},
    ]
    demo_decisions = sorted(demo, key=lambda x: {"立即处理":0,"今日处理":1,"持续观察":2,"AI自动跟踪":3}[x["决策档位"]])

    demo_stats = {
        "总学员数": 81, "立即处理": 7, "今日处理": 5, "持续观察": 12,
        "AI自动跟踪": 56, "需人工介入": 12, "已完成": 5, "待处理": 2,
        "已逾期": 1, "重点升级": 1, "风险已缓解": 4, "风险升级": 1,
        "风险学员数": 19, "人工介入率": 0.148, "AI自动化率": 0.852,
    }
    _overview(demo_stats, {"students": []})
    _automation_rates(demo_stats)
    _render_task_group("今日AI任务（Demo）", demo_decisions, expanded_default=True)

    if st.button("📤 退出Demo", key="agent_exit_demo", use_container_width=True):
        st.session_state.pop("agent_demo_mode", None)
        st.rerun()