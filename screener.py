"""網頁版：強勢股 + 整理轉強掃描（Streamlit）
台股專用。部署時 Main file path 請設為 scanner_app.py，並與 tw_scanner.py、momentum_scanner.py、tw_themes.csv 放在同一層。"""
import traceback
from dataclasses import replace

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots

import momentum_scanner as ms
import tw_scanner as tw

st.set_page_config(page_title="台股強勢整理掃描", layout="wide")
st.title("台股強勢股 + 整理轉強掃描")
st.caption("台股上市＋上櫃普通股 · 流程：強勢排名 → 流動性 → 上漲後整理(低點墊高、波動收斂、站上 9/21 EMA、週線在 10 週線上)。"
           "只用價量資料，不推測誰在買。結果是縮小範圍的觀察名單，請再人工看圖。")


@st.cache_data(ttl=3600, show_spinner=False)
def get_ohlc(tk: str):
    """單檔還原 OHLCV（K 線需要開盤價）。失敗回傳 None。"""
    try:
        df = yf.download(tk, period="2y", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        return df if len(df) > 30 else None
    except Exception:
        return None


def _missing_days(idx) -> list:
    """沒有交易的日期（週末與休市日），讓 K 線不留空隙。"""
    full = pd.date_range(idx.min(), idx.max(), freq="D")
    return [d.strftime("%Y-%m-%d") for d in full.difference(pd.DatetimeIndex(idx).normalize())]


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_universe() -> pd.DataFrame:
    return tw.load_tw_universe()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_prices(tickers: tuple, period: str) -> ms.Prices:
    return ms.download_prices(list(tickers), period)


# ---------------- 側邊欄參數 ----------------
with st.sidebar:
    market = "tw"
    cur = "新台幣"
    d = tw.TW_PARAMS
    st.header("參數")
    atr_max = st.slider("波動收斂：ATR(10)/ATR(30) 小於", 0.5, 1.3, d.atr_ratio_max, 0.05)
    depth_lo, depth_hi = st.slider("高點後回檔幅度", 0.0, 0.5, (d.min_depth, d.max_depth), 0.01)
    max_off = st.slider("現價距高點上限", 0.05, 0.4, d.max_off_high, 0.01)
    pivot_k = st.slider("波段低點：左右各幾根", 2, 8, d.pivot_k)
    min_hl = st.slider("新低點至少比前低點高", 0.0, 0.05, d.min_higher_low, 0.005, format="%.3f")
    min_gain = st.slider("3 或 6 個月漲幅大於", 0.0, 1.0, d.min_gain, 0.05)
    use_tt = st.checkbox("要求通過 Minervini 趨勢模板（8 條）", value=False,
                         help="股價在 150/200 日線之上、200 日線上升、50>150>200、距 52 週低 +30% 以上、"
                              "距 52 週高 25% 內、RS 前 30%。至少需要一年的價格資料。")
    min_dv = st.number_input(f"20 日均成交金額下限（百萬{cur}）", 1, 5000, int(d.min_dollar_vol / 1e6))
    st.caption("更動參數不用重新下載價格，會立即重算。")

params = replace(d, atr_ratio_max=atr_max, min_depth=depth_lo, max_depth=depth_hi,
                 max_off_high=max_off, pivot_k=pivot_k, min_higher_low=min_hl,
                 min_gain=min_gain, min_dollar_vol=min_dv * 1e6,
                 require_trend_template=use_tt)

# ---------------- 載入資料 ----------------
if st.button("載入／更新價格資料", type="primary"):
    st.session_state["loaded"] = True
if st.button("清除快取並重抓"):
    st.cache_data.clear()
    st.session_state["loaded"] = False
    st.rerun()

if not st.session_state.get("loaded"):
    st.info("按「載入／更新價格資料」開始。第一次要下載約 1,500 檔，約需 1～3 分鐘。")
    st.stop()

try:
    with st.spinner("取得股票池與價格中…（約 1～3 分鐘）"):
        uni = get_universe()
        prices = get_prices(tuple(uni.index), "2y")
    info_cols = [c for c in ("name", "sector", "industry") if c in uni.columns]
    res = ms.scan(prices, params=params, info=uni[info_cols])
except Exception as e:                      # 出錯時顯示原因，不要空白
    st.error(f"執行失敗：{e}")
    st.code(traceback.format_exc())
    st.stop()

asof = prices.close.index[-1].date()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("資料截至", str(asof))
c2.metric("股票數", f"{len(res):,}")
c3.metric("全部通過", int(res["passed"].sum()))
c4.metric("差一項", int(res["near_miss"].sum()))
c5.metric("趨勢模板8條全過", int((res["trend_template"] & res["liquid"]).sum()))

st.subheader("條件漏斗")
st.dataframe(ms.funnel(res, with_tt=use_tt), hide_index=True, width=360)

cols = (["name"] if "name" in res.columns else []) + [
    "close", "ret_63", "ret_126", "avg_pct", "depth", "off_high",
    "atr_ratio", "missing", "tt_count", "tt_missing", "sector", "industry"]
fmt = {c: "{:.3f}" for c in ["ret_63", "ret_126", "avg_pct", "depth", "off_high", "atr_ratio"]}
fmt["close"] = "{:.2f}"

passed = res[res["passed"]]
near = res[res["near_miss"]]
rcols = (["name"] if "name" in res.columns else []) + [
    "cons_score", "tt_count", "missing", "close", "ret_63", "ret_126", "avg_pct",
    "depth", "off_high", "atr_ratio", "tt_missing", "sector", "industry"]
min_score = st.slider("排名：整理條件（共 6 條）至少要過幾條", 3, 6, 4,
                      help="流動性、強勢（及勾選時的趨勢模板）是硬條件；整理型態六條改看分數。"
                           "6 = 全部通過，5 = 差一項，4 = 差兩項。")
rank = res[res["candidate"] & (res["cons_score"] >= min_score)].sort_values(
    ["cons_score", "tt_count", "avg_pct"], ascending=False)
cand = rank

t1, t2, t5, t3, t4 = st.tabs(["全部通過", "差一項", "排名", "板塊共振", "看圖"])
with t1:
    if passed.empty:
        st.warning("目前沒有股票通過全部條件，可看「差一項」或放寬左側參數。")
    else:
        st.dataframe(passed[cols].style.format(fmt), width='stretch')
with t2:
    st.caption("missing 欄是唯一沒過的條件。")
    st.dataframe(near[cols].style.format(fmt), width='stretch')
with t5:
    st.caption(f"共 {len(rank)} 檔。依整理分數、趨勢模板條數、強勢百分位排序；missing 欄是沒過的整理條件。")
    st.dataframe(rank[rcols].style.format(fmt), width='stretch')
with t3:
    st.caption("在『排名』名單中，同一板塊有 2 檔以上者（階段 2 的雛形）。"
               + ("台股的板塊是證交所產業別；放 tw_themes.csv 可改成自訂題材。" if market == "tw" else ""))
    if cand.empty:
        st.write("沒有候選股。")
    else:
        g = (cand.dropna(subset=["industry"]).groupby("industry")
             .agg(檔數=("close", "size"), 全過=("passed", "sum"),
                  代號=("close", lambda s: ", ".join(s.index)))
             .query("檔數 >= 2").sort_values(["檔數", "全過"], ascending=False))
        st.dataframe(g, width='stretch') if len(g) else st.write("沒有同細產業 2 檔以上。")
with t4:
    if cand.empty:
        st.write("沒有候選股可看。")
    else:
        label = (lambda t: f"{t} {cand.loc[t, 'name']}") if "name" in cand.columns else (lambda t: t)
        tk = st.selectbox("選一檔", list(cand.index), format_func=label)
        n = st.slider("顯示天數", 60, 400, 180)
        ohlc = get_ohlc(tk)
        if ohlc is None:  # 抓不到開盤價時，用前一日收盤當開盤的近似
            c = prices.close[tk].dropna()
            ohlc = pd.DataFrame({"Open": c.shift(1).fillna(c), "High": prices.high[tk].reindex(c.index),
                                 "Low": prices.low[tk].reindex(c.index), "Close": c,
                                 "Volume": prices.volume[tk].reindex(c.index)})
            st.caption("抓不到開盤價，K 棒開盤以前一日收盤近似。")
        ohlc = ohlc.copy()
        ohlc["EMA9"] = ohlc["Close"].ewm(span=9, adjust=False).mean()
        ohlc["EMA21"] = ohlc["Close"].ewm(span=21, adjust=False).mean()
        ohlc["SMA50"] = ohlc["Close"].rolling(50).mean()
        d = ohlc.tail(n)
        up, dn = ("#e03131", "#2f9e44") if market == "tw" else ("#2f9e44", "#e03131")  # 台股紅漲綠跌
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=d.index, open=d.Open, high=d.High, low=d.Low, close=d.Close,
                                     increasing_line_color=up, increasing_fillcolor=up,
                                     decreasing_line_color=dn, decreasing_fillcolor=dn,
                                     name="K線", showlegend=False), row=1, col=1)
        for col, color in (("EMA9", "#f59f00"), ("EMA21", "#1c7ed6"), ("SMA50", "#868e96")):
            fig.add_trace(go.Scatter(x=d.index, y=d[col], mode="lines", name=col,
                                     line=dict(width=1.3, color=color)), row=1, col=1)
        vcol = [up if c >= o else dn for o, c in zip(d.Open, d.Close)]
        fig.add_trace(go.Bar(x=d.index, y=d.Volume, marker_color=vcol, name="成交量", showlegend=False), row=2, col=1)
        fig.update_xaxes(rangeslider_visible=False, rangebreaks=[dict(values=_missing_days(d.index))])
        fig.update_layout(height=620, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.02),
                          hovermode="x unified")
        st.plotly_chart(fig, width='stretch')
        r = res.loc[tk]
        st.write(f"{tk} · {r.get('industry', '')} · 回檔 {r['depth']:.1%} · "
                 f"ATR 比 {r['atr_ratio']:.2f} · 前低 {r['pivot_prev']:.2f} → 最近低 {r['pivot_last']:.2f}"
                 + (f" · 未過：{r['missing']}" if r["missing"] else ""))
