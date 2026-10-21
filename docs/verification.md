# 驗證紀錄

驗證日期：2026-10-21（Asia/Taipei）。

## 已執行並通過

| 項目 | 結果 |
|---|---|
| Python 測試 | `python -m pytest -q`：42 passed |
| 前端操作測試 | `npm run test:frontend`：4 passed，使用 happy-dom |
| JavaScript 語法 | Node 語法檢查通過 |
| Docker 建置 | `docker compose build` 成功，Linux amd64 |
| Docker 執行 | `docker compose up -d` 成功，容器 healthy |
| 真實網路整合 | `scripts/smoke_test.py` 通過，非模擬資料 |
| Terraform 格式 | `terraform fmt -check` 通過 |
| Terraform 結構 | `terraform init -backend=false` 及 `terraform validate` 通過 |
| Provider 鎖定 | 已取得 Windows amd64 與 Linux amd64 checksum |
| GitHub 上傳 | 完整專案已成功上傳至指定儲存庫的 main |
| GitHub Actions | 前端、Python／Docker、Terraform 三個檢查 job 全部成功 |

真實資料驗證觀察：來源最新交易日為 **2026-10-20**，回傳 **1,383** 檔上市證券；`2330` 名稱為台積電，日行情查詢成功，本月歷史端點回傳 **14** 個交易日。這些是當次測試觀察，不是固定產品資料，後續呼叫可能隨來源更新而不同。

Python 測試出現一則上游 Starlette TestClient 對 HTTPX 的棄用提示；測試仍全部通過。此為開發測試工具提示，不影響目前容器的行情查詢。

## 前端操作測試內容

1. 首頁能顯示來源交易日、股數單位、行情表及 SVG 歷史圖。
2. 中文搜尋能選擇公司，加入／移除關注及月份切換有效。
3. 歷史來源失敗時顯示錯誤，不產生替代的假走勢；舊資料有提示。
4. 前一次較慢的回應，不會覆蓋後來選擇的證券。

## GitHub 遠端 CI 證據

儲存庫：<https://github.com/cc-huang-0716/cathey_20261022>

已驗證的程式版本：`ad72ee53f75039cd843e962affffc090a563547e`。

[成功的 GitHub Actions 執行紀錄](https://github.com/cc-huang-0716/cathey_20261022/actions/runs/39603808193)：

- Frontend DOM behavior：success。
- Python tests and container smoke test：success。
- Terraform validation：success。
- Publish to Google Cloud Run：skipped，尚未設定 GCP 部署變數。

GitHub 連線最初因新儲存庫未開放寫入而回傳 403；使用者調整存取後，重新上傳已成功。上述 CI 成功不代表 Cloud Run 已部署。

## 尚未完成的外部驗證

- **真實瀏覽器視覺檢查**：目前工作階段沒有可用的瀏覽器控制通道，開啟本機頁面時工具回報 `Browser is not available: iab`。響應式 CSS 已提供，但桌面／手機實際排版仍需在瀏覽器查看。
- **GCP 部署**：尚未取得 GCP 專案 ID 與可用部署身分；未執行 terraform apply，未建立雲端資源，沒有公開 Cloud Run 網址。Terraform validate 不等於實際建置成功。

## 完成上雲後應補的證據

1. Cloud Run HTTPS 網址與首頁畫面。
2. `/health`、`/docs` 與實際行情查詢成功。
3. GitHub Actions 通過的 run 連結。
4. Terraform apply 結果及 GCP 資源畫面。
5. 若要宣稱已多人協作，附上實際 PR 與 Review 紀錄。
