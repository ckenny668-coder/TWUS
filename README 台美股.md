# 美股 / 台股選股 - GitHub Pages 手機版

index.html 右上方可切換美股、台股（網址加 `#tw` 會直接開台股）。無後端，只讀 `data/` 裡的 JSON。

## 檔案
- `index.html`：畫面（單一檔案、不依賴外部套件）
- `screener.py`：每日產生趨勢突破 JSON
- `multifactor.ipynb`：產生多因子 JSON（選填）
- `data/`：放 JSON 的資料夾

| 市場 | 趨勢突破 | 多因子 |
|---|---|---|
| 美股 | `data/trend.json` | `data/multifactor.json` |
| 台股 | `data/trend_tw.json` | `data/multifactor_tw.json` |

## 產生資料
```
python screener.py --universe sp500 --out data     # 美股（也可用 sp1500）
python screener.py --universe tw --out data        # 台股，上市＋上櫃 4 碼普通股，約 1,700 檔，要跑幾分鐘
```
台股股票池來自證交所 ISIN 公告（只留 CFICode 為 ES 開頭的普通股，排除 ETF、特別股、權證）。
抓不到時會讀同資料夾的 `tw_universe.csv`（欄位 `code,name,market`，market 填 TWSE 或 TPEX）。

台股預設：基準 ^TWII、最低股價 NT$10、日均成交值 NT$1 億、本金 NT$100 萬；建議部位 ≥1,000 股時顯示「張」，不足顯示零股。
這些數字在 `screener.py` 最上面的 `MARKETS` 改。

## 本機測試
```
python -m http.server 8000
```
瀏覽器開 http://localhost:8000 。不能直接點兩下開 index.html（file://），瀏覽器會擋 fetch，畫面會顯示「無資料」。

## 多因子
用 `multifactor.ipynb`（和 screener.py 放同一個資料夾，從上到下執行）。
- 第一格有選項：市場（美股／台股）、四個因子權重、持股檔數、續抱名次、單檔上限、離線測試。選好後從下一格往下執行（需 `pip install ipywidgets`，沒裝會用預設值）
- 離線測試勾選後用假資料跑完整流程，輸出到 `*.mock.json`；也可用環境變數 `MF_MARKET=tw`、`MF_MOCK=1` 事先指定
- 最後有 4 張圖：因子貢獻、倉位配置、20 日走勢、動能×品質
- 基本面從 yfinance 取得，快取在 `data/fundamentals_cache*.json`（7 天內不重抓）
- 買進/續抱判斷會讀上一次的輸出檔，所以每次跑完請保留 `data/multifactor*.json`

欄位：ticker, name, action(買進/續抱/觀望), composite, mom, quality, value, growth, weight_pct, close, stop, shares

## 部署
1. 建一個 public repo，放 index.html、screener.py、data/
2. Settings -> Pages -> Source: main branch / root
3. 用 GitHub Actions 每天跑 screener.py（美股、台股各一次）並 commit data/*.json
