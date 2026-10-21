"""Generate standalone, editable SVG architecture diagrams using only the stdlib."""

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs"


class Diagram:
    def __init__(self, title, subtitle, height=680):
        self.height = height
        self.parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img" aria-label="{escape(title)}">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#7d9273"/></marker></defs>
<rect width="1200" height="{height}" rx="16" fill="#f6f7f9"/>
<g font-family="Segoe UI, Microsoft JhengHei, Noto Sans CJK TC, sans-serif">''']
        self.text(45, 50, "MARKET BRIEF / 股日", 12, "#899581", weight=700)
        self.text(45, 92, title, 28, "#25312d", weight=700)
        self.text(45, 121, subtitle, 13, "#8a9499")

    def text(self, x, y, value, size=14, color="#64726c", weight=400, anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">{escape(value)}</text>')

    def rect(self, x, y, w, h, fill="#fff", stroke="#dfe5df", dashed=False, radius=12):
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"{dash}/>')

    def box(self, x, y, w, h, title, lines=(), *, dark=False, badge=None):
        self.rect(x, y, w, h, "#25362b" if dark else "#fff", "#25362b" if dark else "#dfe5df")
        if badge:
            self.text(x + 18, y + 25, badge, 10, "#b5c49e" if dark else "#8fa27d", weight=700)
        offset = 52 if badge else 33
        self.text(x + 18, y + offset, title, 17, "#eef5e7" if dark else "#334336", weight=650)
        for i, line in enumerate(lines):
            self.text(x + 18, y + offset + 27 + i * 22, line, 12, "#bbcab2" if dark else "#8d9891")

    def arrow(self, points, label=None, label_x=None, label_y=None):
        coordinates = " ".join(f"{x},{y}" for x, y in points)
        self.parts.append(f'<polyline points="{coordinates}" fill="none" stroke="#7d9273" stroke-width="1.7" marker-end="url(#arrow)"/>')
        if label:
            self.text(label_x, label_y, label, 11, "#7b8d71", anchor="middle")

    def save(self, name, footer):
        self.text(45, self.height - 25, footer, 11, "#9ba49f")
        self.parts.append("</g></svg>")
        (OUT / name).write_text("\n".join(self.parts), encoding="utf-8")


def runtime():
    d = Diagram("系統運行架構", "Python FastAPI + 原生前端，共用一個 Docker 容器；部署於 Google Cloud Run。", 720)
    d.rect(305, 165, 555, 415, "#eef3e9", "#cbd8bd", dashed=True)
    d.text(329, 198, "GOOGLE CLOUD RUN · asia-east1", 13, "#5d714d", weight=650)
    d.rect(329, 225, 507, 267, "#f9fbf6", "#dce5d3")
    d.text(349, 254, "DOCKER CONTAINER · 0.0.0.0:$PORT", 10, "#9aa68e", weight=650)
    d.box(40, 285, 190, 150, "使用者瀏覽器", ["公司名稱／代號搜尋", "行情、歷史走勢、關注"], badge="CLIENT")
    d.box(350, 290, 178, 130, "原生前端", ["HTML / CSS / JavaScript", "同源靜態檔案"], badge="PRESENTATION")
    d.box(608, 290, 208, 130, "FastAPI + HTTPX", ["驗證、轉換、錯誤處理", "連線池與逾時"], dark=True, badge="APPLICATION")
    d.box(970, 285, 190, 150, "證交所公開 API", ["STOCK_DAY_ALL", "STOCK_DAY（月度）"], badge="PUBLIC DATA")
    d.arrow([(230, 351), (350, 351)], "HTTPS", 290, 338)
    d.arrow([(528, 351), (608, 351)], "/api", 567, 338)
    d.arrow([(816, 351), (970, 351)], "HTTPS / JSON", 895, 338)
    d.rect(608, 441, 208, 36, "#f0f4ea", "#dce5d3", radius=6)
    d.text(712, 464, "有界記憶體快取", 12, "#748765", anchor="middle")
    d.arrow([(712, 420), (712, 441)])
    d.text(331, 525, "自動 HTTPS · 0–2 個執行個體 · 無持久資料庫", 13, "#798c69")
    d.text(331, 553, "快取在重啟後清空；執行個體之間不共享狀態。", 11, "#98a58c")
    d.box(405, 620, 355, 57, "Cloud Logging", [""], badge=None)
    d.arrow([(582, 580), (582, 620)], "stdout JSON", 675, 606)
    d.save("architecture.svg", "日行情，非盤中即時報價。交易日期與來源異常狀態皆由 API 明確回傳。")


def cicd():
    d = Diagram("CI/CD 與部署架構", "PR 先驗證；main 使用短期 OIDC 身分發布不可覆寫的 commit image。", 720)
    d.box(45, 195, 235, 145, "功能分支 / PR", ["GitHub Repository", "提交程式、測試與 IaC"], badge="01 / CHANGE")
    d.box(365, 195, 265, 145, "GitHub Actions CI", ["pytest · Docker smoke test", "Terraform fmt / validate"], badge="02 / VERIFY")
    d.box(720, 195, 265, 145, "Review → 合併 main", ["檢查通過後發布", "未設定雲端時跳過部署"], badge="03 / MERGE")
    d.arrow([(280, 268), (365, 268)])
    d.arrow([(630, 268), (720, 268)])
    d.box(45, 445, 260, 155, "WIF 短期部署身分", ["GitHub OIDC → Google IAM", "比對 repository / owner / main"], dark=True, badge="04 / AUTHENTICATE")
    d.box(395, 445, 260, 155, "Artifact Registry", ["Build + Push Docker image", "不可覆寫的 commit tag"], badge="05 / PACKAGE")
    d.box(745, 445, 350, 155, "Google Cloud Run", ["更新 image → 新 revision", "檢查 /health 與 OpenAPI"], badge="06 / DEPLOY & CHECK")
    d.arrow([(985, 268), (1120, 268), (1120, 389), (175, 389), (175, 445)], "DEPLOY_ENABLED = true", 624, 380)
    d.arrow([(305, 520), (395, 520)])
    d.arrow([(655, 520), (745, 520)])
    d.text(45, 654, "Terraform 管理資源與 IAM；CI 管理後續 image 版本。部署需要已啟用 Billing 的 GCP 專案。", 12, "#89967e")
    d.save("cicd.svg", "Pull Request 不取得部署身分；GitHub 不保存長期有效的 service account JSON 私鑰。")


def git_flow():
    d = Diagram("多人協作 GitHub Flow", "每個功能獨立分支，透過 Pull Request、CI 與 Review 合併到 main。", 470)
    boxes = [
        ("同步 main", ["pull --ff-only", "確認最新版本"]),
        ("功能分支", ["feature/…", "小範圍變更"]),
        ("Commit / Push", ["程式與測試", "推送遠端分支"]),
        ("Pull Request", ["說明行為與驗證", "執行 CI"]),
        ("Code Review", ["修正回饋", "檢查通過"]),
        ("合併與部署", ["Squash merge", "main 自動發布"]),
    ]
    for index, (title, lines) in enumerate(boxes):
        x = 35 + index * 195
        d.box(x, 210, 160, 150, title, lines, dark=index == 5, badge=f"0{index + 1}")
        if index < 5:
            d.arrow([(x + 160, 285), (x + 195, 285)])
    d.text(45, 410, "建議 main 分支保護：CI 必須通過、至少一位 Reviewer、禁止直接推送。", 13, "#87967c")
    d.save("git-workflow.svg", "此圖為協作設計；實際參與者、Review 與部署證據應以 GitHub 紀錄為準。")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    runtime()
    cicd()
    git_flow()
    print("Generated architecture.svg, cicd.svg, git-workflow.svg")
