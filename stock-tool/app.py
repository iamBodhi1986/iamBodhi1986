"""
A股自选股工具 - Streamlit 看板

功能页面：
  1. 📋 自选股看板 — 分组管理 + 实时行情表
  2. 🔍 股票筛选器 — 多条件 + 预设模板
  3. 📈 K线分析   — 单股 K线 + 技术指标叠加
  4. 🔔 价格提醒  — 规则管理 + 触发高亮

启动方式:
    cd stock-tool
    streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# 确保 core 包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import data, alerts, screener  # noqa: E402
from core.screener import ScreenCriteria, PRESETS  # noqa: E402
from core.alerts import RULE_TYPES  # noqa: E402

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="A股自选股工具",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    div[data-testid="metric-container"] { background: #f0f2f6; border-radius: 8px; padding: 10px; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 缓存包装（TTL 用于控制刷新频率）
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner="正在获取行情数据...")
def cached_snapshot() -> pd.DataFrame:
    return data.fetch_market_snapshot()


@st.cache_data(ttl=600, show_spinner="正在获取K线数据...")
def cached_kline(code: str, period: str, days: int) -> pd.DataFrame:
    return data.get_kline(code, period, days)


# ---------------------------------------------------------------------------
# 侧边栏导航
# ---------------------------------------------------------------------------
st.sidebar.title("📊 A股自选股工具")
page = st.sidebar.radio(
    "导航",
    ["📋 自选股看板", "🔍 股票筛选器", "📈 K线分析", "🔔 价格提醒"],
    label_visibility="collapsed",
)

if st.sidebar.button("🔄 刷新行情数据"):
    cached_snapshot.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.caption("数据来源：东方财富 via akshare\n仅供学习研究，不构成投资建议")


# ===========================================================================
# 页面 1：自选股看板
# ===========================================================================
if page == "📋 自选股看板":
    st.header("📋 自选股看板")

    groups = data.load_watchlist()

    # --- 管理区 ---
    with st.expander("➕ 管理自选股", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("添加股票")
            add_group = st.selectbox("分组", list(groups.keys()), key="add_grp")
            add_code = st.text_input("股票代码（6位）", key="add_code", max_chars=6)
            add_name = st.text_input("名称（可选）", key="add_name")
            add_note = st.text_input("备注（可选）", key="add_note")
            if st.button("添加"):
                if add_code and len(add_code) == 6:
                    data.add_stock(add_group, add_code, add_name, add_note)
                    st.success(f"✅ 已添加 {add_code} 到 [{add_group}]")
                    st.rerun()
                else:
                    st.warning("请输入6位股票代码")

        with col_b:
            st.subheader("分组管理")
            new_group = st.text_input("新建分组名称", key="new_grp")
            if st.button("创建分组"):
                if new_group:
                    data.add_group(new_group)
                    st.success(f"✅ 已创建分组 [{new_group}]")
                    st.rerun()

            del_group = st.selectbox("删除分组", list(groups.keys()), key="del_grp")
            if st.button("删除分组", type="secondary"):
                data.delete_group(del_group)
                st.warning(f"已删除分组 [{del_group}]")
                st.rerun()

    # --- 行情展示 ---
    if not groups:
        st.info("暂无自选股，请在上方添加。")
    else:
        # 收集所有代码
        all_codes = []
        for items in groups.values():
            all_codes.extend(item["code"] for item in items)
        all_codes = list(set(all_codes))

        if all_codes:
            try:
                snap = cached_snapshot()
                df_quotes = snap[snap["code"].isin(all_codes)].copy()
            except Exception as e:
                st.error(f"获取行情失败: {e}")
                df_quotes = pd.DataFrame()

            # 提醒检查
            if not df_quotes.empty:
                triggered = alerts.evaluate(df_quotes)
                if triggered:
                    st.warning(f"🔔 有 {len(triggered)} 条提醒被触发！")
                    for a in triggered:
                        st.toast(a.message, icon="⚠️")

            # 按分组显示
            for grp_name, items in groups.items():
                if not items:
                    continue
                st.subheader(f"📁 {grp_name}")
                codes_in_grp = [it["code"] for it in items]
                grp_df = df_quotes[df_quotes["code"].isin(codes_in_grp)] if not df_quotes.empty else pd.DataFrame()

                if grp_df.empty:
                    st.caption("暂无数据")
                    continue

                # 格式化展示
                display_cols = ["code", "name", "price", "pct_change", "change",
                                "volume", "turnover_rate", "pe", "pb", "market_cap"]
                display_cols = [c for c in display_cols if c in grp_df.columns]
                show_df = grp_df[display_cols].copy()

                col_labels = {
                    "code": "代码", "name": "名称", "price": "最新价",
                    "pct_change": "涨跌幅%", "change": "涨跌额",
                    "volume": "成交量", "turnover_rate": "换手率%",
                    "pe": "市盈率", "pb": "市净率", "market_cap": "总市值",
                }
                show_df = show_df.rename(columns=col_labels)

                # 涨跌颜色
                st.dataframe(
                    show_df.style.applymap(
                        lambda v: "color: red" if isinstance(v, (int, float)) and v > 0
                        else ("color: green" if isinstance(v, (int, float)) and v < 0 else ""),
                        subset=[c for c in ["涨跌幅%", "涨跌额"] if c in show_df.columns],
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

                # 删除按钮
                with st.expander(f"从 [{grp_name}] 移除股票"):
                    for item in items:
                        col1, col2 = st.columns([4, 1])
                        col1.write(f"{item['code']} {item['name']}")
                        if col2.button("移除", key=f"rm_{grp_name}_{item['code']}"):
                            data.remove_stock(grp_name, item["code"])
                            st.rerun()


# ===========================================================================
# 页面 2：股票筛选器
# ===========================================================================
elif page == "🔍 股票筛选器":
    st.header("🔍 股票筛选器")

    # 预设模板
    preset_name = st.selectbox("快速预设", ["自定义"] + list(PRESETS.keys()))

    if preset_name != "自定义":
        criteria = PRESETS[preset_name]()
    else:
        criteria = ScreenCriteria()

    # 筛选条件面板
    with st.expander("🔧 筛选条件", expanded=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**价格范围（元）**")
            price_min = st.number_input("最低价", value=criteria.price_min or 0.0, min_value=0.0, step=1.0)
            price_max = st.number_input("最高价", value=criteria.price_max or 9999.0, min_value=0.0, step=1.0)

            st.markdown("**涨跌幅范围（%）**")
            pct_min = st.number_input("最低涨跌幅", value=criteria.pct_change_min or -11.0, step=0.5)
            pct_max = st.number_input("最高涨跌幅", value=criteria.pct_change_max or 11.0, step=0.5)

        with col2:
            st.markdown("**换手率范围（%）**")
            tr_min = st.number_input("最低换手率", value=criteria.turnover_rate_min or 0.0, min_value=0.0, step=0.5)
            tr_max = st.number_input("最高换手率", value=criteria.turnover_rate_max or 100.0, min_value=0.0, step=1.0)

            st.markdown("**市盈率范围**")
            pe_min = st.number_input("最低PE", value=criteria.pe_min or 0.0, step=1.0)
            pe_max = st.number_input("最高PE", value=criteria.pe_max or 9999.0, step=10.0)

        with col3:
            st.markdown("**排除选项**")
            exc_st = st.checkbox("排除 ST", value=criteria.exclude_st)
            exc_cn = st.checkbox("排除创业板", value=criteria.exclude_chinext)
            exc_star = st.checkbox("排除科创板", value=criteria.exclude_star)
            exc_bj = st.checkbox("排除北交所", value=criteria.exclude_bj)

            st.markdown("**名称关键词**")
            keyword = st.text_input("包含关键词", value=criteria.name_keyword or "")

    # 构建条件
    final_criteria = ScreenCriteria(
        price_min=price_min if price_min > 0 else None,
        price_max=price_max if price_max < 9999 else None,
        pct_change_min=pct_min if pct_min > -11 else None,
        pct_change_max=pct_max if pct_max < 11 else None,
        turnover_rate_min=tr_min if tr_min > 0 else None,
        turnover_rate_max=tr_max if tr_max < 100 else None,
        pe_min=pe_min if pe_min > 0 else None,
        pe_max=pe_max if pe_max < 9999 else None,
        exclude_st=exc_st,
        exclude_chinext=exc_cn,
        exclude_star=exc_star,
        exclude_bj=exc_bj,
        name_keyword=keyword or None,
    )

    if st.button("🚀 开始筛选", type="primary"):
        try:
            snap = cached_snapshot()
            result = screener.screen(snap, final_criteria)
            st.success(f"筛选完成，共 {len(result)} 只股票符合条件")

            if not result.empty:
                # 按涨跌幅排序
                sort_col = st.selectbox("排序依据", ["pct_change", "turnover_rate", "volume", "pe", "market_cap"])
                ascending = st.checkbox("升序", value=False)
                result = result.sort_values(sort_col, ascending=ascending, na_position="last")

                st.dataframe(
                    result.head(100).rename(columns={
                        "code": "代码", "name": "名称", "price": "最新价",
                        "pct_change": "涨跌幅%", "turnover_rate": "换手率%",
                        "volume": "成交量", "pe": "市盈率", "pb": "市净率",
                        "market_cap": "总市值",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

                # 一键加入自选
                st.markdown("---")
                st.subheader("加入自选股")
                groups = data.load_watchlist()
                target_grp = st.selectbox("目标分组", list(groups.keys()), key="screen_grp")
                selected_code = st.text_input("输入要添加的代码", key="screen_add")
                if st.button("加入自选", key="screen_add_btn"):
                    if selected_code:
                        row = result[result["code"] == selected_code]
                        name = row.iloc[0]["name"] if not row.empty else ""
                        data.add_stock(target_grp, selected_code, name)
                        st.success(f"✅ 已添加 {selected_code} 到 [{target_grp}]")
        except Exception as e:
            st.error(f"筛选失败: {e}")


# ===========================================================================
# 页面 3：K线分析
# ===========================================================================
elif page == "📈 K线分析":
    st.header("📈 K线分析")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        kline_code = st.text_input("股票代码（6位）", value="600519", max_chars=6)
    with col2:
        kline_period = st.selectbox("周期", ["daily", "weekly", "monthly"], format_func=lambda x: {"daily": "日K", "weekly": "周K", "monthly": "月K"}[x])
    with col3:
        kline_days = st.selectbox("回看天数", [30, 60, 90, 120, 250], index=2)

    show_ma = st.multiselect("均线", ["MA5", "MA10", "MA20", "MA60"], default=["MA5", "MA20"])
    show_sub = st.selectbox("副图指标", ["MACD", "RSI", "KDJ", "无"])

    if st.button("📊 加载K线", type="primary") or kline_code:
        if len(kline_code) == 6:
            try:
                df_k = cached_kline(kline_code, kline_period, kline_days)
                if df_k.empty:
                    st.warning("未获取到K线数据，请检查代码是否正确。")
                else:
                    df_k = data.add_indicators(df_k)

                    # ---------- 绘图 ----------
                    rows = 2 if show_sub != "无" else 1
                    row_heights = [0.7, 0.3] if rows == 2 else [1.0]
                    fig = make_subplots(
                        rows=rows, cols=1, shared_xaxes=True,
                        row_heights=row_heights, vertical_spacing=0.03,
                    )

                    # 蜡烛图
                    fig.add_trace(go.Candlestick(
                        x=df_k["date"], open=df_k["open"], high=df_k["high"],
                        low=df_k["low"], close=df_k["close"], name="K线",
                        increasing_line_color="red", decreasing_line_color="green",
                    ), row=1, col=1)

                    # 均线
                    ma_colors = {"MA5": "#FF6B6B", "MA10": "#FFA502", "MA20": "#1E90FF", "MA60": "#A55EEA"}
                    for ma in show_ma:
                        col_name = ma.lower()
                        if col_name in df_k.columns:
                            fig.add_trace(go.Scatter(
                                x=df_k["date"], y=df_k[col_name],
                                name=ma, line=dict(width=1, color=ma_colors.get(ma, "gray")),
                            ), row=1, col=1)

                    # 副图
                    if show_sub == "MACD" and rows == 2:
                        colors = ["red" if v >= 0 else "green" for v in df_k["macd_bar"].fillna(0)]
                        fig.add_trace(go.Bar(x=df_k["date"], y=df_k["macd_bar"], name="MACD柱", marker_color=colors), row=2, col=1)
                        fig.add_trace(go.Scatter(x=df_k["date"], y=df_k["dif"], name="DIF", line=dict(width=1)), row=2, col=1)
                        fig.add_trace(go.Scatter(x=df_k["date"], y=df_k["dea"], name="DEA", line=dict(width=1)), row=2, col=1)
                    elif show_sub == "RSI" and rows == 2:
                        fig.add_trace(go.Scatter(x=df_k["date"], y=df_k["rsi14"], name="RSI(14)", line=dict(width=1.5, color="purple")), row=2, col=1)
                        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
                        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
                    elif show_sub == "KDJ" and rows == 2:
                        fig.add_trace(go.Scatter(x=df_k["date"], y=df_k["k"], name="K", line=dict(width=1)), row=2, col=1)
                        fig.add_trace(go.Scatter(x=df_k["date"], y=df_k["d"], name="D", line=dict(width=1)), row=2, col=1)
                        fig.add_trace(go.Scatter(x=df_k["date"], y=df_k["j"], name="J", line=dict(width=1)), row=2, col=1)

                    fig.update_layout(
                        height=600, xaxis_rangeslider_visible=False,
                        title=f"{kline_code} {'日' if kline_period == 'daily' else '周' if kline_period == 'weekly' else '月'}K线",
                        template="plotly_white",
                    )
                    fig.update_xaxes(type="category")  # 去掉非交易日空白

                    st.plotly_chart(fig, use_container_width=True)

                    # 最新指标摘要
                    latest = df_k.iloc[-1]
                    mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                    mcol1.metric("收盘价", f"{latest['close']:.2f}", f"{latest.get('pct_change', 0):.2f}%")
                    mcol2.metric("换手率", f"{latest.get('turnover_rate', 0):.2f}%")
                    mcol3.metric("RSI(14)", f"{latest.get('rsi14', 0):.1f}")
                    mcol4.metric("MACD柱", f"{latest.get('macd_bar', 0):.3f}")

            except Exception as e:
                st.error(f"K线加载失败: {e}")
        else:
            st.warning("请输入6位股票代码")


# ===========================================================================
# 页面 4：价格提醒
# ===========================================================================
elif page == "🔔 价格提醒":
    st.header("🔔 价格提醒")

    # --- 添加规则 ---
    with st.expander("➕ 新建提醒规则", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            rule_code = st.text_input("股票代码", max_chars=6, key="rule_code")
            rule_name = st.text_input("股票名称", key="rule_name")
        with col2:
            rule_type = st.selectbox("触发条件", list(RULE_TYPES.keys()), format_func=lambda k: RULE_TYPES[k])
            rule_value = st.number_input("阈值", value=10.0, step=0.5, key="rule_val")
        with col3:
            rule_note = st.text_input("备注", key="rule_note")
            st.write("")  # 占位
            if st.button("✅ 添加规则", type="primary"):
                if rule_code and len(rule_code) == 6:
                    alerts.add_rule(rule_code, rule_name or rule_code, rule_type, rule_value, rule_note)
                    st.success("规则已添加！")
                    st.rerun()
                else:
                    st.warning("请输入6位股票代码")

    st.markdown("---")

    # --- 当前规则列表 ---
    rules = alerts.load_rules()
    if not rules:
        st.info("暂无提醒规则。")
    else:
        st.subheader(f"当前规则（共 {len(rules)} 条）")

        for rule in rules:
            col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
            status = "🟢" if rule.get("enabled", True) else "⚪"
            col1.write(f"{status} **{rule['code']}** {rule['name']} — {RULE_TYPES.get(rule['type'], rule['type'])} {rule['value']}")
            col2.caption(rule.get("note", ""))
            if col3.button("切换", key=f"tog_{rule['id']}"):
                alerts.toggle_rule(rule["id"], not rule.get("enabled", True))
                st.rerun()
            if col4.button("删除", key=f"del_{rule['id']}"):
                alerts.delete_rule(rule["id"])
                st.rerun()

        # --- 立即检测 ---
        st.markdown("---")
        if st.button("🔍 立即检测提醒", type="primary"):
            try:
                snap = cached_snapshot()
                triggered = alerts.evaluate(snap)
                if triggered:
                    st.error(f"⚠️ {len(triggered)} 条规则被触发：")
                    for a in triggered:
                        st.warning(a.message)
                else:
                    st.success("✅ 所有规则均未触发。")
            except Exception as e:
                st.error(f"检测失败: {e}")
