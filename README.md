# 股日 Market Brief

台灣上市證券每日行情查詢系統。使用 **Python FastAPI + HTTPX** 串接證交所公開 API，前端為原生 **HTML / CSS / JavaScript**。前後端放在同一個 **Docker** 容器，部署目標為 **Google Cloud Run**。

## 快速開始

### Docker（建議）

```powershell
docker compose up --build -d
```

- 網頁：<http://localhost:8080>
- 互動 API 文件：<http://localhost:8080/docs>
- 健康檢查：<http://localhost:8080/health>
- 日誌：`docker compose logs -f`
- 停止：`docker compose down`

不需要 API 金鑰，也不需要建立資料庫。Docker Desktop 必須處於運行狀態。

### Python 本機開發

安裝 Python 3.12，或使用 [uv](https://docs.astral.sh/uv/) 建立執行環境：

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.lock
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload --no-access-log
```

已有 Python 的環境也可以使用 `python -m venv .venv`，再用 `.venv\Scripts\python.exe -m pip install -r requirements-dev.lock`。

## 功能

- 依公司名稱、ETF 名稱或代號搜尋證交所最新行情資料中的上市證券。
- 顯示收盤價、漲跌價差、漲跌幅、開高低價、成交股數、成交金額、成交筆數。
- 查詢最近 12 個月中任一月份的每日歷史資料；網頁提供本月／上月走勢切換。
- 顯示市場漲跌家數、成交金額，以及成交量／漲幅／跌幅排行。
- 在瀏覽器儲存最多 20 檔關注證券，免登入。
- 明確標示來源交易日期、缺失資料及來源異常時的舊資料提示。

**這是日行情，不是即時報價。** 當日資料尚未公布或遇到休市，會顯示來源最近提供的交易日。歷史走勢使用未還原的原始收盤價，不代表含股息報酬。

## 雲端架構

![系統運行架構](docs/architecture.svg)

瀏覽器 → 同一個 Cloud Run 服務（前端 + FastAPI）→ 證交所公開 API。

無持久資料庫；每個執行個體使用有容量上限的記憶體快取。最新行情快取 5 分鐘、本月歷史快取 15 分鐘、過去月份快取 24 小時。來源失敗時，可在原快取期限後最多 1 小時使用先前資料，回應會設 `meta.stale=true`。來源失敗後暫停重試 30 秒。

## API

| 路徑 | 用途 |
|---|---|
| `GET /` | 前端網站 |
| `GET /health` | 程式存活檢查，不依賴第三方 API |
| `GET /api/market?sort=volume` | 市場統計；sort 支援 volume、gainers、losers |
| `GET /api/stocks?q=台積電&limit=10` | 依名稱或代號搜尋；limit 上限 20 |
| `GET /api/stocks/2330` | 單檔最新日行情 |
| `GET /api/stocks/2330/history?month=2026-10` | 單月每日行情；省略 month 則使用台北時間本月 |
| `GET /docs` | Swagger UI |

成交量單位為**股**，成交金額與價格單位為**新臺幣元**。缺失值為 `null`，前端顯示「—」。漲跌幅使用 `漲跌價差 / (收盤價 - 漲跌價差) × 100`，以 Decimal 計算後四捨五入到小數點後兩位；沒有有效參考價時回傳 `null`。

錯誤使用統一格式：

```json
{"error":{"code":"STOCK_NOT_FOUND","message":"查無此上市證券，請確認名稱或代號。","request_id":"..."}}
```

## 驗證

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\smoke_test.py
terraform -chdir=terraform fmt -check
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
```

pytest 使用模擬外部回應，涵蓋正常查詢、搜尋、數值／日期轉換、無效參數、來源逾時、格式異常、失敗退避、快取過期與並行合併。`smoke_test.py` 則是選用的真實網路驗證，需要先啟動服務；第三方維護時可能失敗，因此不納入 CI 的必要檢查。

前端另有 4 項 DOM 操作測試，使用 Node.js 24 與 happy-dom。這是開發測試工具，執行網站不需要 Node：

```bash
npm ci
npm run test:frontend
```

DOM 測試確認搜尋、關注、圖表資料與非同步競態，不能取代真實瀏覽器的視覺排版檢查。

## CI/CD 與 IaC

- Pull Request：pytest、Docker 建置與容器健康檢查、Terraform 格式與語法驗證。
- 合併 main：在已設定部署變數後，以 GitHub OIDC / Workload Identity Federation 取得短期身分，推送不可覆寫的 commit image，再更新 Cloud Run。
- Terraform：管理啟用 API、Artifact Registry、Cloud Run、執行身分、部署身分及 GitHub WIF。
- Terraform 忽略 image 欄位後續變更；CI 負責發布版本，避免基礎設施更新回滾應用程式。

**實際上雲需要你自己的 GCP 專案、Billing、部署身分及 GitHub 儲存庫。** 專案提供完整設定檔與操作步驟；本機驗證成功不代表已完成 GCP 部署。設定前，GitHub 的部署 job 會跳過，CI 仍可運行。

## 文件

- [繳交用：架構與實作說明](docs/架構與實作說明.md)
- [架構與 API 執行流程圖](docs/architecture.md)
- [GCP 首次部署與 CI/CD 設定](docs/deployment.md)
- [多人協作 Git 工作流程](docs/git-workflow.md)
- [AI 輔助開發方式與觀察](docs/ai-development.md)
- [實際驗證紀錄](docs/verification.md)

## 專案結構

```text
app/
  main.py                 # FastAPI 路由、生命週期、錯誤格式與 JSON 日誌
  config.py               # 環境變數
  models.py               # API 資料模型
  services/cache.py       # 有界快取、同時請求合併、舊資料回退
  services/stocks.py      # HTTPX、資料清理與日期／數值轉換
  static/                 # 同源前端，不依賴外部 CDN
tests/                    # 離線可重現的 API 與服務測試
scripts/                  # 真實網路驗證、架構圖產生工具
terraform/                # Google Cloud IaC
.github/workflows/        # CI/CD
docs/                     # 繳交文件與 SVG 架構圖
```

執行環境依賴固定在 `requirements.lock`，開發／測試依賴固定在 `requirements-dev.lock`。修改版本範圍後，使用 `uv pip compile requirements.txt --python-version 3.12 -o requirements.lock`，再產生 `requirements-dev.lock`，提交兩份 lock 檔。

## 來源

- [臺灣證券交易所 OpenAPI](https://openapi.twse.com.tw/)：`/v1/exchangeReport/STOCK_DAY_ALL`。
- [證交所個股日成交資訊](https://www.twse.com.tw/zh/trading/historical/stock-day.html)：`/exchangeReport/STOCK_DAY`。
- [Cloud Run 容器執行契約](https://docs.cloud.google.com/run/docs/container-contract)：監聽 `0.0.0.0` 與 `PORT`。
- [Google GitHub Actions 身分驗證](https://github.com/google-github-actions/auth)：Workload Identity Federation。
