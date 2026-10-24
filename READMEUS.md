# 美股選股 - GitHub Pages 手機版

index.html 讀 `data/trend.json`（趨勢突破）與 `data/multifactor.json`（多因子，選填），無後端。

## 檔案
- `index.html`：畫面（單一檔案、不依賴外部套件）
- `screener.py`：每日產生 `data/trend.json`
- `data/`：放 JSON 的資料夾

## 本機測試
```
python screener.py --universe sp500 --out data
python -m http.server 8000
```
瀏覽器開 http://localhost:8000 。
不能直接點兩下開 index.html（file://），瀏覽器會擋 fetch，畫面會顯示「無資料」。

## 部署
1. 建一個 public repo，放 index.html、screener.py、data/
2. Settings -> Pages -> Source: main branch / root
3. 用 GitHub Actions 每天跑 screener.py 並 commit data/trend.json

## 多因子
有 `data/multifactor.json` 才會顯示。格式：陣列，或 `{"stocks": [...]}`。
欄位：ticker, name, action(買進/續抱/觀望), composite, mom, quality, value, growth, weight_pct, close, stop, shares
