# Google Cloud Run 首次部署與 CI/CD

目標儲存庫：<https://github.com/cc-huang-0716/cathey_20261022>。

本機 Docker 與 GCP 使用同一份 Dockerfile。首次用 Terraform 建立資源後，GitHub Actions 只負責更新映像版本。以下是可實際執行的步驟，不代表目前已完成上雲。

## 1. 準備帳戶與工具

需要已啟用 Billing 的 GCP 專案、可建立資源／service account／IAM／WIF 的 bootstrap 身分，以及 Google Cloud CLI、Terraform 1.6+、Git、Docker。

```powershell
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
```

`gcloud auth` 供映像推送與 CLI 使用；Application Default Credentials 供本機 Terraform 使用。請在自己的登入畫面完成驗證，不要把權杖或 JSON 金鑰提交到 Git。

## 2. 設定 Terraform 變數

```powershell
Copy-Item terraform\terraform.tfvars.example terraform\terraform.tfvars
```

將 `project_id` 及 `container_image` 中的 `YOUR_GCP_PROJECT_ID` 替換成實際值。`terraform.tfvars` 已被 Git 忽略。

目前儲存庫的數字 ID 已填入 example：

- `github_repository_id = "1428349958"`
- `github_owner_id = "173608276"`

若換了儲存庫，從 GitHub repository API 查詢新的 `id` 與 `owner.id`，一併更新。WIF 使用數字 ID 及 main ref 約束信任來源。

## 3. 先建立映像倉庫

Cloud Run 建立服務時需要一個已存在的應用 image，因此首次 bootstrap 分為兩階段。先建立 Artifact Registry（Terraform 自動一併建立相依的 API 啟用資源）：

```powershell
terraform -chdir=terraform init
terraform -chdir=terraform plan -target=google_artifact_registry_repository.images -out=registry.tfplan
terraform -chdir=terraform apply registry.tfplan
```

這裡的 `-target` 僅用於首次 bootstrap；之後使用完整 plan / apply。

## 4. 建置並推送首次應用映像

下列命令在專案根目錄執行。請將 project ID 改成實際值，region 與 Terraform 保持一致：

```powershell
$projectId = 'YOUR_GCP_PROJECT_ID'
$deployRegion = 'asia-east1'
$registryHost = "$deployRegion-docker.pkg.dev"
$bootstrapImage = "$registryHost/$projectId/market-brief/market-brief:bootstrap-1"
gcloud auth configure-docker $registryHost --quiet
docker build --platform linux/amd64 -t $bootstrapImage .
docker push $bootstrapImage
```

`terraform.tfvars` 的 `container_image` 須與此一致。映像 tag 設為不可覆寫，重建時請使用 `bootstrap-2` 等新 tag。

## 5. 建立完整環境並檢查

```powershell
terraform -chdir=terraform plan -out=deploy.tfplan
terraform -chdir=terraform apply deploy.tfplan
$serviceUrl = terraform -chdir=terraform output -raw service_url
curl.exe --fail "$serviceUrl/health"
curl.exe --fail "$serviceUrl/api/stocks/2330"
```

預設 `public_access=true`，授予 `allUsers` 的 Cloud Run invoker，提供公開 Demo。組織政策若禁止公開存取，須改採組織允許的訪問方式，並調整 CI smoke test 的驗證方式；不要嘗試繞過該政策。

確認以下實際結果後再記錄為部署完成：公開網址能開啟前端、`/docs` 可操作、`/health` 成功，以及 `/api/stocks/2330` 可回傳實際行情。不同雲端出口可能遇到證交所流量管制，仍須以部署後測試為準。

## 6. 設定 GitHub Actions Variables

查看 Terraform 輸出：

```powershell
terraform -chdir=terraform output github_actions_variables
```

到儲存庫 **Settings → Secrets and variables → Actions → Variables** 設定：

| 變數 | 內容 |
|---|---|
| `GCP_PROJECT_ID` | GCP 專案 ID |
| `GCP_REGION` | `asia-east1` 或實際 region |
| `GCP_AR_REPOSITORY` | `market-brief` 或實際倉庫名稱 |
| `CLOUD_RUN_SERVICE` | `market-brief` 或實際 Cloud Run 名稱 |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Terraform 輸出的完整 provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Terraform 輸出的 deployer email |
| `DEPLOY_ENABLED` | `true` |

這些是資源識別資料，不是長期金鑰。不需要建立或上傳 service account JSON 私鑰。先完成 Terraform 與首次服務建立，再啟用自動部署。

推送 main 或手動執行 workflow 後，CI 會先驗證 Python、Docker 與 Terraform，通過才執行部署。workflow summary 會顯示服務網址。要提供 CI/CD 證明，請保留成功的 workflow run 連結。

## 7. 日誌、回滾與清理

```powershell
gcloud run services logs read market-brief --region asia-east1 --project $projectId --limit 50
```

應用日誌包含 `request_id`、method、path、status、duration_ms。HTTP 回應也附帶 `X-Request-ID`。

回滾範例：

```powershell
$knownGoodImage = 'asia-east1-docker.pkg.dev/YOUR_GCP_PROJECT_ID/market-brief/market-brief:KNOWN_GOOD_COMMIT_SHA'
gcloud run services update market-brief --image $knownGoodImage --region asia-east1 --project $projectId
```

Terraform 忽略後續 image 欄位更新，下一次一般 apply 不會把版本改回 bootstrap image。要回滾應用，使用上面指令或發布修復 commit。

Demo 不再使用時，可先檢查 `terraform plan -destroy` 的刪除範圍，再決定是否執行 `terraform destroy`。映像倉庫仍有內容時可能需要先移除映像或調整清理方式；本專案不自動刪除既有映像。

## 8. 成本及多人 Terraform 狀態

Cloud Run 設定最小執行個體 0、最大 2，但 Artifact Registry 儲存、Cloud Run 請求／運算、網路及日誌仍可能產生費用，這些設定不是硬性帳單上限。可在自己的 GCP 專案設定預算通知。

單人 Demo 預設使用本機 state，已被 `.gitignore` 排除。多人操作 Terraform 前，先在共用 GCS bucket 設定遠端 backend、版本控管與適當 IAM，再執行 `terraform init -migrate-state`；不要把 state 放進 Git 或讓多位成員各自管理同一批資源。

## 官方參考

- [Cloud Run 容器契約](https://docs.cloud.google.com/run/docs/container-contract)
- [Cloud Run 公開存取](https://docs.cloud.google.com/run/docs/authenticating/public)
- [GitHub Actions Google Auth / WIF](https://github.com/google-github-actions/auth)
- [Terraform Cloud Run v2 Service](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_service)
