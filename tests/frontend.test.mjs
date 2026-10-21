import {test} from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {Window} from "happy-dom";

const html = await readFile(new URL("../app/static/index.html", import.meta.url), "utf8");
const source = await readFile(new URL("../app/static/script.js", import.meta.url), "utf8");
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const quote = {symbol: "2330", name: "台積電", trade_date: "2026-10-20", open: 100, high: 112, low: 98, close: 110, change: 10, change_percent: 10, volume: 1000000, turnover: 105000000, transactions: 2000};
const other = {...quote, symbol: "2317", name: "鴻海", close: 95, change: -5, change_percent: -5};

async function until(predicate, label) {
  for (let attempt = 0; attempt < 100; attempt++) { if (predicate()) return; await pause(10); }
  assert.fail(`Timed out waiting for ${label}`);
}

function setup(options = {}) {
  const window = new Window({url: "http://localhost:8080", settings: {disableCSSFileLoading: true, disableJavaScriptFileLoading: true}});
  const calls = [];
  const meta = {retrieved_at: "2026-10-21T04:00:00Z", stale: Boolean(options.stale), warning: options.stale ? "資料來源暫時無法更新，目前顯示先前取得的資料。" : null};
  window.HTMLElement.prototype.scrollIntoView = function () {};
  window.scrollTo = function () {};
  window.fetch = async (path, request = {}) => {
    const url = new URL(path, "http://localhost:8080"); calls.push(url);
    if (url.pathname === "/api/stocks/2330" && options.slowInitialQuote) await pause(150);
    else await pause(1);
    if (request.signal?.aborted) { const error = new Error("Aborted"); error.name = "AbortError"; throw error; }
    let body;
    if (url.pathname === "/api/market") body = {summary: {trade_date: quote.trade_date, securities: 2, advancing: 1, declining: 1, unchanged: 0, unavailable: 0, total_volume: 2000000, total_turnover: 210000000}, featured: [quote, other], leaders: [quote, other], meta};
    else if (url.pathname.endsWith("/history")) {
      if (options.historyError) return {ok: false, json: async () => ({error: {message: "證交所回應逾時，請稍後再試。"}})};
      const month = url.searchParams.get("month");
      body = {data: [1, 2, 3, 4].map((day) => ({date: `${month}-${String(day).padStart(2, "0")}`, close: 100 + day})), meta};
    } else if (url.pathname === "/api/stocks") {
      const query = url.searchParams.get("q"); const items = [quote, other].filter((item) => item.name.includes(query) || item.symbol.includes(query));
      body = {data: items, count: items.length, meta};
    } else body = {data: url.pathname.endsWith("2317") ? other : quote, meta};
    return {ok: true, json: async () => body};
  };
  window.document.write(html);
  window.eval(source);
  return {window, document: window.document, calls};
}

test("initial dashboard shows source date, correct units, a real SVG series and rows", async () => {
  const {window, document} = setup();
  try {
    await until(() => document.querySelector("#stock-price").textContent === "110.00", "quote render");
    await until(() => document.querySelector("#chart svg"), "history chart");
    assert.equal(document.querySelector("#trade-date").textContent, "2026/10/20");
    assert.match(document.querySelector("#quote-date").textContent, /非即時報價/);
    assert.equal(document.querySelector("#fact-volume").textContent, "1,000,000");
    assert.equal(document.querySelectorAll("#leaders tr").length, 2);
    assert.equal(document.querySelector("#error").hidden, true);
  } finally { await window.happyDOM.close(); }
});

test("Chinese search selects a company; watchlist add/remove and month switch work", async () => {
  const {window, document, calls} = setup();
  try {
    await until(() => document.querySelector("#stock-price").textContent === "110.00", "startup");
    const input = document.querySelector("#search"); input.value = "鴻海";
    input.dispatchEvent(new window.Event("input", {bubbles: true}));
    await until(() => document.querySelector(".search-result"), "Chinese search results");
    document.querySelector(".search-result").click();
    await until(() => document.querySelector("#stock-name").textContent === "鴻海", "selected quote");
    assert.equal(document.querySelector("#stock-price").textContent, "95.00");
    document.querySelector("#favorite").click();
    assert.deepEqual(JSON.parse(window.localStorage.getItem("market-brief-watchlist")), ["2317"]);
    document.querySelector('[data-nav="watchlist"]').click();
    await until(() => document.querySelectorAll("#leaders .company-button").length === 1, "watchlist");
    assert.equal(document.querySelector("#table-title").textContent, "我的關注");
    document.querySelector("#leaders [data-favorite]").click();
    await until(() => document.querySelector("#leaders").textContent.includes("尚未加入關注"), "empty watchlist");
    document.querySelector('[data-month="previous"]').click();
    await until(() => document.querySelector("#chart svg"), "previous month chart");
    const months = calls.filter((call) => call.pathname.endsWith("/history")).map((call) => call.searchParams.get("month"));
    assert.ok(new Set(months).size >= 2);
  } finally { await window.happyDOM.close(); }
});

test("source failure is explained instead of displaying fabricated history", async () => {
  const {window, document} = setup({stale: true, historyError: true});
  try {
    await until(() => document.querySelector("#chart").textContent.includes("逾時"), "history error");
    assert.equal(document.querySelector("#chart svg"), null);
    assert.equal(document.querySelector("#notice").hidden, false);
    assert.match(document.querySelector("#notice").textContent, /先前取得/);
  } finally { await window.happyDOM.close(); }
});

test("a slow previous response cannot overwrite a newly selected security", async () => {
  const {window, document} = setup({slowInitialQuote: true});
  try {
    document.querySelector('.quick-search [data-symbol="2317"]').click();
    await until(() => document.querySelector("#stock-name").textContent === "鴻海", "new quote");
    await pause(200);
    assert.equal(document.querySelector("#stock-symbol").textContent, "2317");
    assert.equal(document.querySelector("#stock-price").textContent, "95.00");
  } finally { await window.happyDOM.close(); }
});
