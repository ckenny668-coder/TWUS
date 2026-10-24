# -*- coding: utf-8 -*-
"""
每天跑，輸出 JSON 給 GitHub Pages 網頁
用法:
  python screener.py --universe sp500  --out data   -> data/trend.json      (美股，S&P 500)
  python screener.py --universe sp1500 --out data   -> data/trend.json      (美股，S&P 1500)
  python screener.py --universe tw     --out data   -> data/trend_tw.json   (台股，上市+上櫃 4 碼普通股)
"""
import argparse, json, math, time, os
from io import StringIO
from types import SimpleNamespace
import numpy as np
import pandas as pd
import yfinance as yf
import requests

BENCH = "SPY"  # 向後相容；實際基準看 MARKETS[...]["bench"]

# 各市場參數。min_dv 是 50 日平均成交值（本幣）；lot 是一張的股數
MARKETS = {
    "us": dict(label="美股", bench="SPY",   bench_label="SPY",     currency="$",   min_price=10, min_dv=20e6,  equity=100_000,   lot=1,    out="trend.json",    mf_out="multifactor.json"),
    "tw": dict(label="台股", bench="^TWII", bench_label="加權指數", currency="NT$", min_price=10, min_dv=100e6, equity=1_000_000, lot=1000, out="trend_tw.json", mf_out="multifactor_tw.json"),
}

WIKI = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "sp400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "sp600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
# 證交所國際證券辨識號碼公告：strMode=2 上市、strMode=4 上櫃
ISIN = {
    "上市": ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", ".TW",  "TWSE"),
    "上櫃": ("https://isin.twse.com.tw/isin/C_public.jsp?strMode=4", ".TWO", "TPEX"),
}


def market_of(universe):
    return "tw" if universe == "tw" else "us"


# ---------------- 股票池 ----------------
def _wiki_tickers(url):
    """回傳 {代號: 公司名稱}"""
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    for tbl in pd.read_html(StringIO(resp.text)):
        cols = [str(c) for c in tbl.columns]
        for key in ("Symbol", "Ticker symbol", "Ticker"):
            if key in cols:
                syms = tbl[key].astype(str).str.strip().str.upper()
                ncol = next((c for c in ("Security", "Company", "Name") if c in cols), None)
                names = tbl[ncol].astype(str).str.strip() if ncol else [""] * len(syms)
                return {sy.replace(".", "-"): nm for sy, nm in zip(syms, names) if sy and sy != "NAN"}
    raise RuntimeError(url)


def load_index_universe(name):
    parts = ["sp500"] if name == "sp500" else ["sp500", "sp400", "sp600"]
    names = {}
    for p in parts:
        names.update(_wiki_tickers(WIKI[p]))
    return sorted(names), names


def parse_isin_html(html, suffix, tv):
    """解析證交所 ISIN 表，只留 4 碼普通股 (CFICode 以 ES 開頭)，排除 ETF、特別股、權證。
    回傳 {yfinance代號: (股票代號, 名稱, TradingView代號)}"""
    tbl = pd.read_html(StringIO(html), header=0)[0]
    ccol = tbl.columns[0]
    cfi = next((c for c in tbl.columns if "CFI" in str(c).upper()), None)
    if cfi is None:
        raise RuntimeError("找不到 CFICode 欄位，ISIN 頁面格式可能改了")
    out = {}
    for raw, cf in zip(tbl[ccol].astype(str), tbl[cfi].astype(str)):
        parts = raw.replace("　", " ").split()
        if len(parts) < 2:
            continue
        code, nm = parts[0], parts[1]
        if code.isdigit() and len(code) == 4 and cf.startswith("ES"):
            out[code + suffix] = (code, nm, f"{tv}:{code}")
    return out


def load_tw_universe():
    """上市 + 上櫃 4 碼普通股。抓不到時退回同資料夾的 tw_universe.csv (欄位: code,name,market[TWSE/TPEX])"""
    info = {}
    for label, (url, suffix, tv) in ISIN.items():
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            info.update(parse_isin_html(resp.content.decode("big5", errors="ignore"), suffix, tv))
        except Exception as e:
            print(f"{label} 股票池抓取失敗: {e}")
    if not info and os.path.exists("tw_universe.csv"):
        df = pd.read_csv("tw_universe.csv", dtype=str)
        for code, nm, mk in zip(df["code"], df["name"], df.get("market", pd.Series(["TWSE"] * len(df)))):
            sfx = ".TWO" if str(mk).upper() == "TPEX" else ".TW"
            info[code + sfx] = (code, nm, f"{str(mk).upper() if str(mk).upper() in ('TWSE','TPEX') else 'TWSE'}:{code}")
        print("使用本機 tw_universe.csv", len(info))
    if not info:
        raise SystemExit("台股股票池抓不到：請檢查網路，或放一份 tw_universe.csv (code,name,market)")
    tickers = sorted(info)
    names = {t: v[1] for t, v in info.items()}
    meta = {t: {"code": v[0], "tv": v[2]} for t, v in info.items()}
    return tickers, names, meta


def load_universe(universe):
    """回傳 (tickers, names, meta)。meta 只有台股會有 (code, tv)"""
    if universe == "tw":
        return load_tw_universe()
    t, n = load_index_universe(universe)
    return t, n, {}


def clean(o):
    """JSON 不能有 NaN/Infinity，瀏覽器會解析失敗；統一換成 None，並轉成原生型別"""
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, np.generic): o = o.item()
    if isinstance(o, float) and not math.isfinite(o): return None
    return o


# ---------------- 價格 ----------------
def _download_chunk(chunk, period):
    raw = yf.download(list(chunk), period=period, interval="1d", auto_adjust=True, group_by="ticker", threads=True, progress=False)
    out = {}
    if raw is None or raw.empty:
        return out
    # 相容兩種 MultiIndex 順序
    if isinstance(raw.columns, pd.MultiIndex):
        for t in chunk:
            try:
                d = raw.xs(t, level=1, axis=1) if t in raw.columns.get_level_values(1) else raw[t]
                d = d.dropna(subset=["Close"])
                if len(d): out[t] = d
            except Exception:
                continue
    else:
        d = raw.dropna(subset=["Close"])
        if len(d): out[chunk[0]] = d
    return out


def load_prices(tickers, period="2y", batch=80):
    out = {}
    chunks = [tuple(tickers[i:i+batch]) for i in range(0, len(tickers), batch)]
    for k, ch in enumerate(chunks, 1):
        try:
            out.update(_download_chunk(ch, period))
            time.sleep(1)  # 避免 429
        except Exception as e:
            print(f"batch {k} fail {e}")
    return out


def analyze_price(df):
    d = df.dropna(subset=["Close"])
    if len(d) < 253: return None
    c, h, l, v = d["Close"], d["High"], d["Low"], d["Volume"]
    last = float(c.iloc[-1])
    prev_c = c.shift(1)
    tr = pd.concat([h-l, (h-prev_c).abs(), (l-prev_c).abs()], axis=1).max(axis=1)
    hi52, lo52 = float(h.iloc[-252:].max()), float(l.iloc[-252:].min())
    sma200 = c.rolling(200).mean()
    return {
        "last_date": str(d.index[-1].date()),
        "close": last,
        "sma50": float(c.rolling(50).mean().iloc[-1]),
        "sma150": float(c.rolling(150).mean().iloc[-1]),
        "sma200": float(sma200.iloc[-1]),
        "sma200_prev": float(sma200.iloc[-22]),
        "hi52": hi52, "lo52": lo52,
        "near_high": last/hi52,
        "atr": float(tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1]),
        "dollar_vol": float((c*v).rolling(50).mean().iloc[-1]),
        "vol_ratio": float(v.iloc[-5:].mean() / v.rolling(50).mean().iloc[-1]),
        "vol60": float(c.pct_change().iloc[-60:].std()*math.sqrt(252)),
        "r12_1": float(c.iloc[-22])/float(c.iloc[-253])-1,
        "r6": last/float(c.iloc[-127])-1,
        "r3": last/float(c.iloc[-64])-1,
    }


def build_tech(prices, skip=BENCH):
    rows = {}
    for t, d in prices.items():
        if t == skip: continue
        r = analyze_price(d)
        if r: rows[t] = r
    return pd.DataFrame.from_dict(rows, orient="index")


def regime(spy_df, label="SPY"):
    c = spy_df["Close"].dropna()
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    last = float(c.iloc[-1])
    above = last > float(s200.iloc[-1])
    golden = float(s50.iloc[-1]) > float(s200.iloc[-1])
    if above and golden: lab, scale = "進攻（多頭）", 1.0
    elif above: lab, scale = "謹慎（僅在200日線上）", 0.6
    else: lab, scale = f"防守（{label} 在 200 日線下）", 0.3
    # spy_* 欄位名稱沿用，網頁讀的是這幾個；代表「基準指數」
    return {"label": lab, "scale": scale, "spy_close": last, "spy_sma50": float(s50.iloc[-1]), "spy_sma200": float(s200.iloc[-1])}


def run_trend(prices, p, names=None, meta=None):
    bench = getattr(p, "bench", BENCH)
    tech = build_tech(prices, skip=bench)
    liquid = tech[(tech["close"] >= p.min_price) & (tech["dollar_vol"] >= p.min_dv)].copy()
    breadth = float((liquid["close"] > liquid["sma200"]).mean()*100) if len(liquid) else 0
    raw = 0.4*liquid["r12_1"].rank(pct=True) + 0.3*liquid["r6"].rank(pct=True) + 0.3*liquid["r3"].rank(pct=True)
    liquid["rs"] = (raw.rank(pct=True)*98+1).round(0)
    t = liquid
    liquid["trend_ok"] = (t.close>t.sma150)&(t.close>t.sma200)&(t.sma150>t.sma200)&(t.sma200>t.sma200_prev)&(t.sma50>t.sma150)&(t.sma50>t.sma200)&(t.close>t.sma50)&(t.close>=1.30*t.lo52)&(t.close>=0.75*t.hi52)
    cand = liquid[liquid["trend_ok"] & (liquid["rs"] >= p.min_rs)].sort_values("rs", ascending=False).head(p.top).copy()
    reg = regime(prices[bench], getattr(p, "bench_label", bench))
    risk_pct = p.risk*reg["scale"]
    cand["stop"] = cand["close"] - p.atr_mult*cand["atr"]
    per_share = (cand["close"] - cand["stop"]).clip(lower=0.01)
    by_risk = (p.equity*risk_pct/per_share).apply(math.floor)
    by_cap = (p.equity*p.max_position/cand["close"]).apply(math.floor)
    cand["shares"] = np.minimum(by_risk, by_cap).astype(int)
    cand["dist_high"] = (1-cand["near_high"])*100
    cand["ext50"] = (cand["close"]/cand["sma50"]-1)*100
    cand["status"] = cand.apply(lambda r: "過度延伸，等回檔" if r["ext50"]>20 else ("接近新高，可關注突破" if r["dist_high"]<=5 else "趨勢中，等回檔至50日線附近"), axis=1)
    sym = list(cand.index)
    cand["name"] = [(names or {}).get(s, "") for s in sym]
    cand["ticker"] = [((meta or {}).get(s) or {}).get("code", s) for s in sym]   # 台股顯示 4 碼代號
    cand["tv"] = [((meta or {}).get(s) or {}).get("tv") for s in sym]              # TradingView 代號 (台股: TWSE:2330)
    cand["close_history"] = [prices[s]["Close"].iloc[-60:].tolist()[-20:] for s in sym]  # 只存20天給手機畫 sparkline
    highs = int((liquid["near_high"] >= 0.98).sum()); lows = int((liquid["close"] <= liquid["lo52"]*1.02).sum())
    return {"cand": cand, "regime": reg, "breadth": breadth, "highs": highs, "lows": lows,
            "funnel": {"下載": len(prices)-1, "足夠資料": len(tech), "流動性": len(liquid), "趨勢": int(liquid["trend_ok"].sum()), "RS": len(cand)}}


def make_params(market, **over):
    m = MARKETS[market]
    d = dict(min_price=m["min_price"], min_dv=m["min_dv"], equity=m["equity"], min_rs=80, atr_mult=2.5,
             risk=0.01, max_position=0.2, top=30, bench=m["bench"], bench_label=m["bench_label"])
    d.update(over)
    return SimpleNamespace(**d)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default="sp500", choices=["sp500", "sp1500", "tw"])
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    market = market_of(args.universe)
    cfg = MARKETS[market]
    os.makedirs(args.out, exist_ok=True)
    tickers, names, meta = load_universe(args.universe)
    print(f"Universe {args.universe}: {len(tickers)}")
    prices = load_prices(sorted(set(tickers + [cfg["bench"]])), period="2y")
    if cfg["bench"] not in prices:
        raise SystemExit(f"{cfg['bench']} download fail")
    p = make_params(market)
    res = run_trend(prices, p, names, meta)
    out_cand = res["cand"].reset_index(drop=True).to_dict(orient="records")
    path = f"{args.out}/{cfg['out']}"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean({"market": market, "currency": cfg["currency"], "lot": cfg["lot"], "bench_label": cfg["bench_label"],
                         "regime": res["regime"], "breadth": res["breadth"], "highs": res["highs"], "lows": res["lows"], "funnel": res["funnel"],
                         "params": {"min_price": p.min_price, "min_dv": p.min_dv, "min_rs": p.min_rs, "atr_mult": p.atr_mult,
                                    "risk": p.risk, "max_position": p.max_position, "equity": p.equity},
                         "stocks": out_cand, "updated": time.strftime("%Y-%m-%d %H:%M")}),
                  f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"Saved {path} {len(out_cand)} stocks")
