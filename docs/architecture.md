# 架構與流程圖

## 系統運行架構

![Runtime Architecture](architecture.svg)

```mermaid
flowchart LR
    Browser[使用者瀏覽器]
    subgraph GCP[Google Cloud]
      subgraph Run[Cloud Run 容器]
        Static[HTML / CSS / JavaScript]
        API[Python FastAPI + Uvicorn]
        Cache[有界記憶體快取]
        Static -->|同源 /api 請求| API
        API <--> Cache
      end
      Logs[Cloud Logging]
      API -. 結構化 stdout 日誌 .-> Logs
    end
    TWSE[證交所公開 API]
    Browser <-->|HTTPS| Static
    API <-->|HTTPX / HTTPS / JSON| TWSE
```

前端與 API 共用來源，因此不需要另開 CORS。Cloud Run 提供 HTTPS 與執行個體擴縮；容器只監聽 HTTP `0.0.0.0:$PORT`。執行身分不持有專案角色，僅需要存取網際網路上的公開資料。Cloud Logging 收集 stdout 的 JSON 日誌。

記憶體快取不構成持久儲存：執行個體重啟就會清空，不同個體之間不共享快取。這個取捨適合小型 Demo；若流量放大，應改為排程匯入與共享儲存，避免每個個體重複向來源擷取。

## 單檔行情執行流程

```mermaid
sequenceDiagram
    actor User as 使用者
    participant Web as 瀏覽器前端
    participant API as FastAPI
    participant Cache as 記憶體快取
    participant TWSE as 臺灣證券交易所
    User->>Web: 搜尋「台積電」或「2330」
    Web->>API: GET /api/stocks?q=2330
    API->>Cache: 讀取最新行情快照
    alt 快取有效
        Cache-->>API: 已取得的行情
    else 快取過期或不存在
        API->>TWSE: GET STOCK_DAY_ALL
        TWSE-->>API: 上市證券日行情 JSON
        API->>API: 驗證欄位、轉換民國日期與數字
        API->>Cache: 儲存有效快照
    end
    API-->>Web: 搜尋結果與資料日期
    User->>Web: 選擇證券
    Web->>API: GET /api/stocks/2330
    API-->>Web: 統一格式的日行情
    Web->>API: GET /api/stocks/2330/history?month=YYYY-MM
    API->>TWSE: 快取未命中時，查詢 STOCK_DAY
    TWSE-->>API: 月度每日成交資料
    API-->>Web: 日期排序後的歷史行情
    Web-->>User: 收盤資訊、月度走勢與交易快覽
```

來源失敗時，若快取仍在容許的舊資料期限內，回傳 `stale=true` 與提示；否則回傳 502／503／504。相同個體內的同時更新會合併成一個來源請求，失敗後退避 30 秒。

## CI/CD 部署架構

![CI/CD Architecture](cicd.svg)

```mermaid
flowchart TB
    Branch[功能分支 / Pull Request] --> Test[pytest]
    Test --> Docker[Docker build + 容器 smoke test]
    Branch --> TF[Terraform fmt / init / validate]
    Docker --> Review[Code Review 與合併 main]
    TF --> Review
    Review --> Gate{已設定 DEPLOY_ENABLED?}
    Gate -->|否| Complete[CI 完成，部署略過]
    Gate -->|是| OIDC[GitHub OIDC → GCP WIF 短期身分]
    OIDC --> Build[建置並推送 commit image]
    Build --> AR[Artifact Registry]
    AR --> Deploy[更新 Cloud Run image]
    Deploy --> Smoke[檢查 /health 與 /openapi.json]
    Smoke --> URL[公開 HTTPS 網址]
```

WIF 同時比對 GitHub repository ID、owner ID 及 `refs/heads/main`；Pull Request 測試不取得部署身分。部署者僅具備對指定映像倉庫的寫入權、Cloud Run developer 權限及使用 runtime service account 的權限。

Terraform 建立資源及 IAM，GitHub Actions 更新映像版本。回滾使用已存在的 commit tag／digest，參考 [部署說明](deployment.md)。
