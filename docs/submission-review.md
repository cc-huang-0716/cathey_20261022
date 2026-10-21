# 繳交要求、測試與上傳檔案檢查

檢查日期：2026-10-21。原先已上傳的版本為 `810174f3aeb157e298375f29e9a1e60491895a8b`，共 50 個檔案、3 筆 Git 提交。本次檢查也涵蓋補強後的工作副本與重新產生的繳交 ZIP。

## 一、上傳檔案與敏感資料

經檢查原先的 Git 檔案清單與歷史，未發現誤傳的實際 `.env`、私鑰、service account JSON、Terraform state／plan／實際變數檔、虛擬環境、node_modules、本機工具或輸出 ZIP。

使用 Gitleaks **8.30.1** 掃描原先已上傳的全部 3 筆提交，結果為 **0 筆憑證／金鑰發現**。本次補強後的繳交來源也另做內容掃描。工具及掃描輸出置於被忽略的 `.tools/`、`.artifacts/security-audit/`，不提交原始掃描資料。這是對已掃描內容的檢查結果，不是對任意未來變更的保證。

以下檔案有意保留，並非誤傳：

| 檔案 | 為何需要上傳 |
|---|---|
| `.env.example` | 可公開的設定範本，只有連接埠、快取與逾時值，沒有密碼或金鑰 |
| `terraform/terraform.tfvars.example` | GCP project 使用佔位文字；GitHub repository／owner ID 是公開識別資料，不是憑證 |
| `terraform/.terraform.lock.hcl` | Provider 版本與校驗碼，確保 IaC 依賴一致；不是 Terraform state |
| `requirements.lock`、`requirements-dev.lock` | 固定 Python 正式及測試依賴版本 |
| `package-lock.json` | 固定前端測試依賴版本 |
| `.github/workflows/deploy.yml` | CI/CD 原始設定，僅引用變數名稱，沒有硬編碼的雲端憑證 |

## 二、本次修正

1. `.gitignore` 原先只排除 `.env`，現在一併排除 `.env.local`、`.env.production` 及其他變體，僅放行明確的 example 範本。
2. 補上私鑰／憑證格式、常見本機雲端憑證、Terraform `.tfvars.json`、state／plan、工具、編輯器及測試產物的忽略規則。
3. `.dockerignore` 改為只放行 Dockerfile、runtime lock 與 `app/`，並排除即使放進 `app/` 的環境設定、私鑰及憑證檔。Docker 重新建置成功。
4. 新增 `scripts/check_repository.py`；若已被 Git 追蹤的檔案違反目前 `.gitignore`，CI 會失敗。這也涵蓋以 `git add -f` 誤加的檔案。
5. CI 使用 Gitleaks 掃描完整 Git 歷史，工具固定版本並校驗下載檔；發現憑證時阻止部署，輸出遮蔽敏感值。
6. 打包腳本在產生 ZIP 前執行檔案追蹤檢查，僅打包 Git 來源。ZIP 不含 `.git/`、工具、依賴環境或掃描產物。

以 17 個應排除路徑及 10 個應保留路徑驗證 `.gitignore`，全部符合預期。另核對目前追蹤的檔案沒有命中忽略規則。

## 三、單元測試與 CI/CD

| 測試類別 | 檔案 | 案例數 | 驗證內容 |
|---|---|---:|---|
| 單元／服務測試 | [test_cache_and_parsing.py](../tests/test_cache_and_parsing.py) | 15 | 民國日期、缺失值、Decimal、月份範圍、並行合併與快取容量 |
| API 測試 | [test_api.py](../tests/test_api.py) | 27 | 搜尋、行情、歷史、錯誤回應、來源失敗、快取及健康檢查 |
| 前端 DOM 操作 | [frontend.test.mjs](../tests/frontend.test.mjs) | 4 | 初始畫面資料、中文搜尋、關注、月份切換、錯誤與非同步競態 |

Python 共 42 項、前端共 4 項。API 測試使用 MockTransport 模擬第三方資料，前端測試也使用固定回應，CI 不依賴證交所當下是否可連線。`scripts/smoke_test.py` 是額外的真實資料整合檢查，不是單元測試，也未作為 CI 的必要外部網路依賴。

Pull Request、push main 與手動 workflow 均會執行驗證；部署 job 的 `needs` 包含 Python／Docker、前端及 Terraform 三個 job。任一必要檢查失敗，就不會進入部署。檔案追蹤及 Gitleaks 掃描也放在必要的 Python job 中。

已有 [成功的 GitHub Actions 紀錄](https://github.com/cc-huang-0716/cathey_20261022/actions/runs/39604032531)。本次補強後的即時結果可在 [Actions](https://github.com/cc-huang-0716/cathey_20261022/actions) 查看。

## 四、與題目逐項對照

| 題目要求 | 狀態與成果 |
|---|---|
| 放置 Java／Python 程式的雲端後端架構 | 已提供 Python FastAPI、Docker、Cloud Run 架構與 Terraform 設定 |
| 雲端架構圖 | 已提供 [architecture.svg](architecture.svg) 與 [架構說明](architecture.md) |
| 簡述用途、主要功能及選用原因 | 已提供 [架構與實作說明](架構與實作說明.md) |
| 加分 1：前端 | 已實作 HTML／CSS／JavaScript 行情介面；實際瀏覽器視覺驗證仍待完成 |
| 加分 2：第三方 RESTful API | 已串接證交所日行情及月度歷史，完成真實來源查詢 |
| 加分 3：CI/CD 架構／流程圖 | 已提供 [cicd.svg](cicd.svg) 與 Actions workflow；CI 已成功，CD 尚待 GCP 設定 |
| 加分 4：多人 Git 流程圖 | 已提供 [git-workflow.svg](git-workflow.svg) 及 GitHub Flow 說明 |
| 加分 5：使用 IaC 建置 | Terraform 程式及 validate 已完成；**尚未 apply 建立雲端資源** |
| 加分 6：AI 工具及心得 | 已提供 [AI 輔助開發方式與觀察](ai-development.md) |
| Python 原始碼／Git 連結／原始碼壓縮檔 | 已提供 GitHub 儲存庫與本機繳交 ZIP |

不能將「CI 通過」或「Terraform validate 通過」視為 Cloud Run 已部署。完成實際 CD 與 IaC 建置，仍需 GCP 專案、Billing 與部署身分；這是目前主要待完成項目。
