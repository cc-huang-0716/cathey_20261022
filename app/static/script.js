"use strict";

const $ = (id) => document.getElementById(id);
const todayParts = new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit"}).formatToParts(new Date());
const localDate = Object.fromEntries(todayParts.map((part) => [part.type, part.value]));
const todayISO = `${localDate.year}-${localDate.month}-${localDate.day}`;
const currentMonth = todayISO.slice(0, 7);
const lastMonthDate = new Date(Date.UTC(Number(localDate.year), Number(localDate.month) - 2, 1));
const previousMonth = `${lastMonthDate.getUTCFullYear()}-${String(lastMonthDate.getUTCMonth() + 1).padStart(2, "0")}`;
const state = {symbol: "2330", month: currentMonth, sort: "volume", view: "overview", quotes: new Map(), market: null, selection: 0, marketRequest: 0, tableRequest: 0, searchRequest: 0, chartRequest: 0};
let searchTimer;
let searchController;
let toastTimer;
let favorites = [];
try { const stored = JSON.parse(localStorage.getItem("market-brief-watchlist") || "[]"); if (Array.isArray(stored)) favorites = [...new Set(stored.filter((s) => typeof s === "string" && /^[0-9A-Z]{4,6}$/.test(s)))].slice(0, 20); } catch { /* Storage may be disabled in private browsing. */ }

function text(id, value) { $(id).textContent = value; }
function price(value) { return value == null ? "—" : Number(value).toLocaleString("zh-TW", {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
function integer(value) { return value == null ? "—" : Number(value).toLocaleString("zh-TW"); }
function compact(value, suffix = "") { if (value == null) return "—"; if (Math.abs(value) >= 100000000) return `${(value / 100000000).toLocaleString("zh-TW", {maximumFractionDigits: 2})} 億${suffix}`; if (Math.abs(value) >= 10000) return `${(value / 10000).toLocaleString("zh-TW", {maximumFractionDigits: 1})} 萬${suffix}`; return `${integer(value)}${suffix}`; }
function changeClass(value) { return value == null || value === 0 ? "neutral" : value > 0 ? "up" : "down"; }
function signed(value, percent = false) { return value == null ? "—" : `${value > 0 ? "+" : ""}${price(value)}${percent ? "%" : ""}`; }
function formatDate(value) { return value ? value.replaceAll("-", "/") : "—"; }
function toast(message) { text("toast", message); $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3000); }
function showError(message) { text("error", message); $("error").hidden = false; }
function clearError() { $("error").hidden = true; }

async function api(path, signal) {
  const response = await fetch(path, {signal, headers: {Accept: "application/json"}});
  let payload;
  try { payload = await response.json(); } catch { throw new Error("服務暫時無法回應，請稍後再試。"); }
  if (!response.ok) throw new Error(payload.error?.message || "無法取得資料，請稍後再試。");
  return payload;
}

function remember(quotes) { quotes.forEach((quote) => state.quotes.set(quote.symbol, quote)); }
function updateFavoriteButton() {
  const saved = favorites.includes(state.symbol);
  $("favorite").setAttribute("aria-pressed", String(saved));
  $("favorite").setAttribute("aria-label", saved ? "移除關注" : "加入關注");
  $("favorite").querySelector("span").textContent = saved ? "已關注" : "加入關注";
  text("watch-count", favorites.length);
}

function toggleFavorite(symbol) {
  const existed = favorites.includes(symbol);
  if (!existed && favorites.length >= 20) { toast("最多可以關注 20 檔證券。"); return; }
  favorites = existed ? favorites.filter((code) => code !== symbol) : [...favorites, symbol];
  try { localStorage.setItem("market-brief-watchlist", JSON.stringify(favorites)); } catch { toast("瀏覽器無法儲存清單，本次關注僅於此頁有效。"); }
  updateFavoriteButton();
  document.querySelectorAll("[data-favorite]").forEach((button) => { const active = favorites.includes(button.dataset.favorite); button.setAttribute("aria-pressed", String(active)); button.textContent = active ? "★" : "☆"; button.setAttribute("aria-label", `${active ? "取消關注" : "關注"} ${button.dataset.favorite}`); });
  if (state.view === "watchlist") loadTable();
  toast(existed ? "已從關注清單移除" : "已加入我的關注");
}

function renderQuote(quote) {
  remember([quote]);
  text("stock-symbol", quote.symbol); text("stock-name", quote.name); text("stock-price", price(quote.close));
  text("stock-change", `${signed(quote.change)} (${signed(quote.change_percent, true)})`);
  $("stock-change").className = `price-change ${changeClass(quote.change)}`;
  text("quote-date", `收盤價 · ${formatDate(quote.trade_date)} · 非即時報價`);
  text("facts-date", `${formatDate(quote.trade_date)} 交易資訊`);
  for (const field of ["open", "high", "low"]) text(`fact-${field}`, price(quote[field]));
  text("fact-volume", integer(quote.volume)); text("fact-turnover", compact(quote.turnover, "元")); text("fact-transactions", integer(quote.transactions));
  text("range-low", price(quote.low)); text("range-high", price(quote.high));
  const ranged = quote.low != null && quote.high != null && quote.close != null;
  text("range-value", ranged ? `${price(quote.low)} – ${price(quote.high)}` : "無有效價格");
  $("range-marker").hidden = !ranged;
  if (ranged) $("range-marker").style.left = `${quote.high === quote.low ? 50 : Math.min(100, Math.max(0, (quote.close - quote.low) / (quote.high - quote.low) * 100))}%`;
  updateFavoriteButton();
}

function chartMessage(message) { const div = document.createElement("div"); div.className = "chart-placeholder"; div.textContent = message; $("chart").replaceChildren(div); $("chart").setAttribute("aria-label", message); text("chart-period", `${state.month.replace("-", "/")} 月度行情`); }

function svgNode(tag, attributes = {}, content) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (content != null) node.textContent = content;
  return node;
}

function renderChart(points) {
  const valid = points.filter((point) => point.close != null);
  if (!valid.length) { chartMessage("這個月份尚無可用的成交資料，試試上個月。"); return; }
  const width = 690, height = 218, left = 8, right = 59, top = 15, bottom = 30;
  const w = width - left - right, h = height - top - bottom;
  const closes = valid.map((point) => point.close);
  const minValue = Math.min(...closes), maxValue = Math.max(...closes);
  const spread = maxValue - minValue || Math.max(maxValue * 0.01, 1);
  const low = Math.max(0, minValue - spread * 0.25), high = maxValue + spread * 0.25;
  const x = (i) => valid.length === 1 ? left + w / 2 : left + i / (valid.length - 1) * w;
  const y = (v) => top + (high - v) / (high - low) * h;
  const svg = svgNode("svg", {viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true", preserveAspectRatio: "none"});
  const defs = svgNode("defs"); const gradient = svgNode("linearGradient", {id: "chart-gradient", x1: 0, y1: 0, x2: 0, y2: 1}); gradient.append(svgNode("stop", {offset: "0%", "stop-color": "#a9bd94", "stop-opacity": ".24"}), svgNode("stop", {offset: "100%", "stop-color": "#a9bd94", "stop-opacity": ".01"})); defs.append(gradient); svg.append(defs);
  for (let i = 0; i <= 3; i++) { const py = top + h * i / 3; svg.append(svgNode("line", {x1: left, x2: left + w, y1: py, y2: py, stroke: "#edf0ed", "stroke-dasharray": "3 5"}), svgNode("text", {x: width - right + 12, y: py + 3, fill: "#a2aba8", "font-size": 9, "font-family": "inherit"}, price(high - (high - low) * i / 3))); }
  const path = valid.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.close).toFixed(1)}`).join(" ");
  if (valid.length > 1) svg.append(svgNode("path", {d: `${path} L${x(valid.length - 1)},${top + h} L${x(0)},${top + h} Z`, fill: "url(#chart-gradient)"}));
  svg.append(svgNode("path", {d: path, fill: "none", stroke: "#859d6c", "stroke-width": 2, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke"}));
  const indexes = [...new Set([0, Math.floor((valid.length - 1) / 3), Math.floor((valid.length - 1) * 2 / 3), valid.length - 1])];
  indexes.forEach((index) => svg.append(svgNode("text", {x: x(index), y: height - 7, fill: "#a5ada9", "font-size": 9, "font-family": "inherit", "text-anchor": index === 0 ? "start" : index === valid.length - 1 ? "end" : "middle"}, valid[index].date.slice(5).replace("-", "/"))));
  const cursor = svgNode("line", {x1: 0, x2: 0, y1: top, y2: top + h, stroke: "#afbb9f", "stroke-dasharray": "3 3", visibility: "hidden"});
  const dot = svgNode("circle", {cx: x(valid.length - 1), cy: y(valid.at(-1).close), r: 3, fill: "#7e9567", stroke: "white", "stroke-width": 2});
  svg.append(cursor, dot);
  const tooltip = document.createElement("div"); tooltip.className = "chart-tooltip"; tooltip.hidden = true;
  const hit = svgNode("rect", {x: left, y: top, width: w, height: h, class: "chart-hit"});
  hit.addEventListener("pointermove", (event) => { const box = svg.getBoundingClientRect(); const position = (event.clientX - box.left) / box.width * width; const index = Math.max(0, Math.min(valid.length - 1, Math.round((position - left) / w * (valid.length - 1)))); cursor.setAttribute("x1", x(index)); cursor.setAttribute("x2", x(index)); cursor.setAttribute("visibility", "visible"); dot.setAttribute("cx", x(index)); dot.setAttribute("cy", y(valid[index].close)); tooltip.textContent = `${formatDate(valid[index].date)}　${price(valid[index].close)}`; tooltip.hidden = false; });
  hit.addEventListener("pointerleave", () => { cursor.setAttribute("visibility", "hidden"); tooltip.hidden = true; dot.setAttribute("cx", x(valid.length - 1)); dot.setAttribute("cy", y(valid.at(-1).close)); });
  svg.append(hit); $("chart").replaceChildren(svg, tooltip);
  $("chart").setAttribute("aria-label", `${state.month}，${valid.length} 個交易日，首日收盤 ${price(valid[0].close)}，末日收盤 ${price(valid.at(-1).close)}，區間最低 ${price(minValue)}、最高 ${price(maxValue)}。`);
  text("chart-period", `${formatDate(valid[0].date)} — ${formatDate(valid.at(-1).date)} · ${valid.length} 個交易日`);
}

async function loadHistory() {
  const request = ++state.chartRequest, symbol = state.symbol, month = state.month;
  chartMessage("正在載入歷史走勢…");
  try {
    const response = await api(`/api/stocks/${encodeURIComponent(symbol)}/history?month=${month}`);
    if (request !== state.chartRequest) return;
    renderChart(response.data);
    if (response.meta.stale) { const warning = document.createElement("span"); warning.textContent = " · 先前資料"; $("chart-period").append(warning); }
  } catch (error) { if (request === state.chartRequest) chartMessage(error.message); }
}

async function selectStock(symbol) {
  const selection = ++state.selection;
  state.symbol = symbol; closeSearch(); clearError();
  $("quote-panel").setAttribute("aria-busy", "true");
  text("stock-symbol", symbol); text("stock-name", "載入中…"); text("stock-price", "—"); text("stock-change", "—");
  text("quote-date", "正在取得此證券的日行情…"); text("facts-date", "正在載入");
  for (const field of ["open", "high", "low", "volume", "turnover", "transactions"]) text(`fact-${field}`, "—");
  text("range-value", "—"); text("range-low", "最低"); text("range-high", "最高"); $("range-marker").hidden = true;
  updateFavoriteButton(); loadHistory();
  try {
    const response = await api(`/api/stocks/${encodeURIComponent(symbol)}`);
    if (selection !== state.selection) return;
    renderQuote(response.data);
    if (response.meta.stale) { text("notice", response.meta.warning); $("notice").hidden = false; }
    document.querySelectorAll(".quick-search [data-symbol]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.symbol === symbol)));
  } catch (error) {
    if (selection === state.selection) { text("stock-name", "無法取得行情"); text("quote-date", "請稍後重新整理"); showError(error.message); }
  } finally { if (selection === state.selection) $("quote-panel").setAttribute("aria-busy", "false"); }
}

function tableMessage(message) { const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 7; cell.className = "empty-state"; cell.textContent = message; row.append(cell); $("leaders").replaceChildren(row); }
function renderTable(quotes) {
  remember(quotes);
  if (!quotes.length) { tableMessage(state.view === "watchlist" ? "尚未加入關注。點選行情旁的星號，建立自己的觀察清單。" : "目前沒有符合此排行的資料。"); return; }
  const rows = quotes.map((quote, index) => {
    const row = document.createElement("tr"); const rank = document.createElement("td"); rank.className = "rank-cell"; rank.textContent = String(index + 1).padStart(2, "0"); row.append(rank);
    const company = document.createElement("td"); const button = document.createElement("button"); button.className = "company-button"; button.dataset.symbol = quote.symbol;
    const avatar = document.createElement("span"); avatar.className = "company-avatar"; avatar.textContent = quote.name.slice(0, 1);
    const identity = document.createElement("span"); const name = document.createElement("strong"); name.textContent = quote.name; const code = document.createElement("small"); code.textContent = quote.symbol; identity.append(name, code); button.append(avatar, identity); company.append(button); row.append(company);
    const close = document.createElement("td"); close.className = "number"; close.textContent = price(quote.close); row.append(close);
    const change = document.createElement("td"); change.className = "number"; const chip = document.createElement("span"); chip.className = `change-chip ${changeClass(quote.change_percent)}`; chip.textContent = signed(quote.change_percent, true); change.append(chip); row.append(change);
    const volume = document.createElement("td"); volume.className = "number"; volume.textContent = integer(quote.volume); row.append(volume);
    const turnover = document.createElement("td"); turnover.className = "number turnover-col"; turnover.textContent = compact(quote.turnover); row.append(turnover);
    const favorite = document.createElement("td"); const star = document.createElement("button"); const active = favorites.includes(quote.symbol); star.className = "table-star"; star.dataset.favorite = quote.symbol; star.setAttribute("aria-label", `${active ? "取消關注" : "關注"} ${quote.symbol}`); star.setAttribute("aria-pressed", String(active)); star.textContent = active ? "★" : "☆"; favorite.append(star); row.append(favorite);
    return row;
  }); $("leaders").replaceChildren(...rows);
}

async function loadTable() {
  const request = ++state.tableRequest;
  const watching = state.view === "watchlist";
  text("table-title", watching ? "我的關注" : "市場焦點");
  text("table-description", watching ? "保留你在意的公司，持續追蹤每一天" : "從成交量與漲跌幅，觀察當日交易動向");
  document.querySelector(".table-tabs").hidden = watching;
  if (!watching) { if (state.market) renderTable(state.market.leaders); return; }
  if (!favorites.length) { renderTable([]); return; }
  tableMessage("正在更新關注清單…");
  const results = await Promise.allSettled(favorites.map((symbol) => api(`/api/stocks/${symbol}`)));
  if (request !== state.tableRequest) return;
  const quotes = results.filter((result) => result.status === "fulfilled").map((result) => result.value.data);
  const failed = results.length - quotes.length;
  if (!quotes.length && failed) tableMessage("關注清單的行情暫時無法取得，請稍後重新整理。");
  else renderTable(quotes);
  if (failed) text("table-note", `${failed} 檔關注證券暫時無法取得行情，請稍後重新整理。`);
  else text("table-note", `已關注 ${quotes.length} 檔 · 儲存於此瀏覽器`);
}

async function loadMarket() {
  const request = ++state.marketRequest;
  const response = await api(`/api/market?sort=${state.sort}`);
  if (request !== state.marketRequest) return;
  state.market = response; remember([...response.featured, ...response.leaders]);
  const summary = response.summary;
  text("trade-date", formatDate(summary.trade_date));
  text("date-note", summary.trade_date === todayISO ? "今日公布的日成交行情" : "最近公布行情 · 今日資料尚未提供");
  text("advancing", integer(summary.advancing)); text("declining", integer(summary.declining));
  text("breadth-note", `持平 ${integer(summary.unchanged)} · 無有效漲跌資料 ${integer(summary.unavailable)}`);
  for (const [id, value] of [["up-bar", summary.advancing], ["flat-bar", summary.unchanged], ["down-bar", summary.declining]]) $(id).style.width = `${value / (summary.advancing + summary.declining + summary.unchanged || 1) * 100}%`;
  text("total-turnover", compact(summary.total_turnover)); text("securities", integer(summary.securities));
  const fetched = new Intl.DateTimeFormat("zh-TW", {timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", hour12: false}).format(new Date(response.meta.retrieved_at));
  text("fetched-at", `資料取得 ${fetched} · 台北時間`);
  $("notice").hidden = !response.meta.stale;
  if (response.meta.stale) text("notice", response.meta.warning);
  await loadTable();
}

function closeSearch() { ++state.searchRequest; clearTimeout(searchTimer); if (searchController) searchController.abort(); $("search-results").hidden = true; $("search").setAttribute("aria-expanded", "false"); }
function searchMessage(message) { const div = document.createElement("div"); div.className = "search-message"; div.textContent = message; $("search-results").replaceChildren(div); $("search-results").hidden = false; $("search").setAttribute("aria-expanded", "true"); }
async function searchStocks(autoSelect = false) {
  const query = $("search").value.trim();
  const request = ++state.searchRequest;
  if (searchController) searchController.abort();
  if (!query) { closeSearch(); return; }
  searchController = new AbortController(); searchMessage("搜尋中…");
  try {
    const response = await api(`/api/stocks?q=${encodeURIComponent(query)}&limit=8`, searchController.signal);
    if (request !== state.searchRequest) return;
    remember(response.data);
    if (autoSelect && response.data.length === 1) { selectStock(response.data[0].symbol); $("search").value = ""; return; }
    if (!response.data.length) { searchMessage("找不到符合的上市證券。請確認名稱或代號；目前不涵蓋上櫃及海外市場。"); return; }
    const buttons = response.data.map((quote) => { const button = document.createElement("button"); button.type = "button"; button.className = "search-result"; button.dataset.symbol = quote.symbol; const identity = document.createElement("span"); const name = document.createElement("strong"); name.textContent = quote.name; const symbol = document.createElement("small"); symbol.textContent = quote.symbol; identity.append(name, symbol); const value = document.createElement("span"); value.textContent = price(quote.close); button.append(identity, value); return button; });
    $("search-results").replaceChildren(...buttons); $("search-results").hidden = false; $("search").setAttribute("aria-expanded", "true");
  } catch (error) { if (error.name !== "AbortError" && request === state.searchRequest) searchMessage(error.message); }
}

$("search").addEventListener("input", () => { clearTimeout(searchTimer); ++state.searchRequest; if (searchController) searchController.abort(); if (!$("search").value.trim()) closeSearch(); else searchTimer = setTimeout(() => searchStocks(), 250); });
$("search-form").addEventListener("submit", (event) => { event.preventDefault(); clearTimeout(searchTimer); searchStocks(true); });
$("search").addEventListener("keydown", (event) => { if (event.key === "ArrowDown") { event.preventDefault(); $("search-results").querySelector("button")?.focus(); } if (event.key === "Escape") closeSearch(); });
$("search-results").addEventListener("keydown", (event) => { const buttons = [...$("search-results").querySelectorAll("button")], index = buttons.indexOf(document.activeElement); if (event.key === "ArrowDown") { event.preventDefault(); buttons[(index + 1) % buttons.length]?.focus(); } if (event.key === "ArrowUp") { event.preventDefault(); if (index <= 0) $("search").focus(); else buttons[index - 1]?.focus(); } if (event.key === "Escape") { closeSearch(); $("search").focus(); } });

document.addEventListener("click", (event) => {
  const favorite = event.target.closest("[data-favorite]"); if (favorite) { toggleFavorite(favorite.dataset.favorite); return; }
  const symbol = event.target.closest("[data-symbol]"); if (symbol) { selectStock(symbol.dataset.symbol); $("search").value = ""; if (symbol.closest("#leaders")) $("quote-panel").scrollIntoView({behavior: "smooth", block: "start"}); return; }
  if (!event.target.closest("#search-form")) closeSearch();
});
document.addEventListener("keydown", (event) => { if (event.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement.tagName) && !$("data-dialog").open) { event.preventDefault(); $("search").focus(); } });
$("favorite").addEventListener("click", () => toggleFavorite(state.symbol));
document.querySelectorAll("[data-month]").forEach((button) => button.addEventListener("click", () => { state.month = button.dataset.month === "current" ? currentMonth : previousMonth; document.querySelectorAll("[data-month]").forEach((tab) => { const selected = tab === button; tab.classList.toggle("selected", selected); tab.setAttribute("aria-pressed", String(selected)); }); loadHistory(); }));
document.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", async () => { state.sort = button.dataset.sort; document.querySelectorAll("[data-sort]").forEach((tab) => { const selected = tab === button; tab.classList.toggle("selected", selected); tab.setAttribute("aria-pressed", String(selected)); }); tableMessage("正在取得排行…"); try { await loadMarket(); } catch (error) { showError(error.message); tableMessage("排行暫時無法載入，請稍後再試。"); } }));
document.querySelectorAll("[data-nav]").forEach((button) => button.addEventListener("click", async () => { if (button.dataset.nav === "search") { $("search").focus(); window.scrollTo({top: 0, behavior: "smooth"}); return; } state.view = button.dataset.nav; document.querySelectorAll("[data-nav]").forEach((nav) => { nav.classList.toggle("active", nav === button); if (nav === button) nav.setAttribute("aria-current", "page"); else nav.removeAttribute("aria-current"); }); text("table-note", "點選證券名稱，查看完整行情"); await loadTable(); if (state.view === "watchlist") $("market-table").scrollIntoView({behavior: "smooth", block: "start"}); }));
$("refresh").addEventListener("click", async () => { clearError(); $("refresh").disabled = true; $("refresh").classList.add("refreshing"); try { await loadMarket(); await selectStock(state.symbol); toast("行情已重新整理"); } catch (error) { showError(error.message); } finally { $("refresh").disabled = false; $("refresh").classList.remove("refreshing"); } });
$("info-button").addEventListener("click", () => $("data-dialog").showModal()); $("close-dialog").addEventListener("click", () => $("data-dialog").close());
$("data-dialog").addEventListener("click", (event) => { if (event.target === $("data-dialog")) { const bounds = $("data-dialog").getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) $("data-dialog").close(); } });

updateFavoriteButton();
loadMarket().catch((error) => { showError(error.message); text("date-note", "請稍後重新整理"); tableMessage("目前無法取得市場資料。"); });
selectStock(state.symbol);
