"use strict";

const LC = window.LightweightCharts;
const $ = (sel, root = document) => root.querySelector(sel);

const rub = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const pctFmt = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const dateFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const state = { data: null, rangeDays: 0, detailsId: null, editId: null, pollTimer: null };

// --- helpers -------------------------------------------------------------

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join("; ");
    throw new Error(msg || `Ошибка ${res.status}`);
  }
  return data;
}

const sign = (v) => (v > 0 ? "+" : v < 0 ? "−" : "");
const signedRub = (v) => sign(v) + rub.format(Math.abs(v));
const signedPct = (v) => (v == null ? "" : sign(v) + pctFmt.format(Math.abs(v)) + " %");
const trend = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const parseLocal = (s) => new Date(s.length === 10 ? s + "T00:00:00" : s);
const fmtDate = (s) => dateFmt.format(parseLocal(s));
const fmtDateTime = (s) => dateTimeFmt.format(parseLocal(s));
const todayIso = () => {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const icon = (name, cls = "icon") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const arrow = (v) => (v > 0 ? icon("up") : v < 0 ? icon("down") : "");
const unsigned = (v) => (v == null ? "" : pctFmt.format(Math.abs(v)) + " %");

function toast(text, ms = 4000) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), ms);
}

// --- charts --------------------------------------------------------------

function makeChart(container) {
  return LC.createChart(container, {
    autoSize: true,
    layout: { background: { color: "transparent" }, textColor: css("--muted"), fontFamily: css("--mono"), fontSize: 11, attributionLogo: false },
    grid: { vertLines: { visible: false }, horzLines: { color: css("--border") } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false },
    crosshair: { mode: LC.CrosshairMode.Magnet },
    localization: { locale: "ru-RU", priceFormatter: (p) => num.format(p) + " ₽" },
    handleScroll: { vertTouchDrag: false },
  });
}

function areaColors(up) {
  const color = up ? css("--up") : css("--down");
  return { lineColor: color, topColor: color + "4d", bottomColor: color + "00" };
}

const mainChart = { chart: null, value: null, cost: null };

function renderMainChart(series) {
  if (!mainChart.chart) {
    mainChart.chart = makeChart($("#main-chart"));
    mainChart.value = mainChart.chart.addSeries(LC.AreaSeries, {
      lineWidth: 2, priceLineVisible: false, crosshairMarkerRadius: 5, crosshairMarkerBorderWidth: 2,
    });
    mainChart.cost = mainChart.chart.addSeries(LC.LineSeries, {
      color: css("--cost"), lineWidth: 1, lineStyle: LC.LineStyle.Dashed, lineType: LC.LineType.WithSteps,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
  }
  const last = series[series.length - 1];
  mainChart.value.applyOptions(areaColors(!last || last.value >= last.cost));
  mainChart.value.setData(series.map((p) => ({ time: p.date, value: p.value })));
  mainChart.cost.setData(series.map((p) => ({ time: p.date, value: p.cost })));
  applyRange();
}

function applyRange() {
  const series = state.data ? state.data.series : [];
  const ts = mainChart.chart && mainChart.chart.timeScale();
  if (!ts || !series.length) return;
  if (!state.rangeDays || series.length <= state.rangeDays) {
    ts.fitContent();
    return;
  }
  ts.setVisibleRange({ from: series[series.length - 1 - state.rangeDays].date, to: series[series.length - 1].date });
}

function sparkline(values, up) {
  if (values.length < 2) return '<span class="check">—</span>';
  const w = 120, h = 34, pad = 3;
  const min = Math.min(...values), max = Math.max(...values);
  // At least ±3 % of the price, so a few rubles of noise do not look like a crash.
  const span = Math.max(max - min, ((min + max) / 2) * 0.06) || 1;
  const base = (min + max) / 2 - span / 2;
  const pts = values.map((v, i) => [
    (i / (values.length - 1)) * w,
    h - pad - ((v - base) / span) * (h - pad * 2),
  ]);
  const d = pts.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1)).join(" ");
  const color = up ? "var(--up)" : "var(--down)";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`;
}

// --- main page -----------------------------------------------------------

async function load() {
  const data = await api("/api/portfolio");
  state.data = data;
  renderSummary(data.summary);
  renderMainChart(data.series);
  renderPositions(data.components);
  renderTicker(data.components);
  renderStatus(data.status);
}

function renderSummary(s) {
  $("#total-value").textContent = rub.format(s.value);
  $("#total-cost").textContent = rub.format(s.cost);
  const change = $("#total-change");
  change.className = "quote-change " + trend(s.change);
  change.innerHTML = s.cost
    ? `${arrow(s.change)}<span>${signedRub(s.change)}</span><span class="pct">${signedPct(s.change_pct) || "0,0 %"}</span><span class="since">с момента сборки</span>`
    : "";
  const day = $("#day-change");
  day.innerHTML = s.day_change
    ? `за день <span class="${trend(s.day_change)}">${signedRub(s.day_change)} · ${signedPct(s.day_change_pct)}</span>`
    : "";
}

function checkCell(c) {
  const lc = c.last_check;
  if (!c.url) return '<span class="check">без ссылки</span>';
  if (!lc) return '<span class="check">ещё не проверялось</span>';
  if (lc.ok) return `<span class="check check-ok">${fmtDateTime(lc.checked_at)}</span>`;
  const why = lc.available === false ? "нет в наличии" : "ошибка";
  return `<span class="check check-bad" title="${esc(lc.error || why)}">${fmtDateTime(lc.checked_at)} · ${why}</span>`;
}

function renderPositions(items) {
  $("#empty").hidden = items.length > 0;
  $("#positions").hidden = items.length === 0;
  $("#count").textContent = items.length ? String(items.length) : "";
  $("#positions tbody").innerHTML = items.map((c) => {
    const t = trend(c.change);
    const qty = c.quantity > 1 ? ` <span class="qty">×${c.quantity}</span>` : "";
    return `<tr data-id="${c.id}" tabindex="0">
      <td><div class="pos-name">${esc(c.name)}${qty}</div><div class="pos-sub">${esc(c.category || "")}${c.category ? " · " : ""}куплено ${fmtDate(c.purchase_date)}</div></td>
      <td class="num hide-sm">${rub.format(c.cost)}</td>
      <td class="num">${rub.format(c.value)}</td>
      <td class="num ${t}"><div class="change-pct">${arrow(c.change)}${unsigned(c.change_pct) || "0,0 %"}</div><div class="change-abs">${signedRub(c.change)}</div></td>
      <td class="hide-sm">${sparkline(c.sparkline, c.change >= 0)}</td>
      <td class="hide-sm">${checkCell(c)}</td>
    </tr>`;
  }).join("");
}

// Short ticker label: drop the category word and the [model code] from the DNS name.
function tickerName(c) {
  let name = c.name.replace(/\s*\[.*?\]\s*/g, " ").trim();
  if (c.category && name.toLowerCase().startsWith(c.category.toLowerCase() + " ")) {
    name = name.slice(c.category.length + 1);
  } else {
    name = name.replace(/^(Видеокарта|Процессор|Материнская плата|Оперативная память|Блок питания|Корпус|Кулер для процессора|Вентилятор|SSD-накопитель|Монитор)\s+/i, "");
  }
  return name.length > 34 ? name.slice(0, 33).trimEnd() + "…" : name;
}

function renderTicker(items) {
  const ticker = $("#ticker");
  ticker.hidden = items.length === 0;
  if (!items.length) return;
  const chunk = (hidden) => items.map((c) => `<button class="tick" data-id="${c.id}"${hidden ? ' aria-hidden="true" tabindex="-1"' : ""}>
      <span class="tick-name">${esc(tickerName(c))}</span>
      <span class="tick-price">${num.format(c.current_price)}</span>
      <span class="tick-chg ${trend(c.change)}">${arrow(c.change)}${unsigned(c.change_pct) || "0,0 %"}</span>
    </button>`).join("");
  // Two identical halves: the track slides by exactly one half and loops seamlessly.
  $("#ticker-track").innerHTML = `<div class="ticker-half">${chunk(false)}</div><div class="ticker-half" aria-hidden="true">${chunk(true)}</div>`;
  ticker.style.setProperty("--ticker-duration", `${Math.max(30, items.length * 7)}s`);
}

function renderStatus(st) {
  const el = $("#run-status");
  const btn = $("#refresh-btn");
  btn.disabled = st.running;
  if (st.running) {
    el.textContent = `Проверяю цены ${st.done}/${st.total}${st.current ? ": " + st.current : ""}…`;
    startPolling();
    return;
  }
  const parts = [];
  if (st.last_run_finished) {
    parts.push(`Последняя проверка ${fmtDateTime(st.last_run_finished)}: ${st.last_run_ok} ок` + (st.last_run_failed ? `, ${st.last_run_failed} с ошибкой` : ""));
  }
  if (st.next_run) parts.push(`следующая ${fmtDateTime(st.next_run)}`);
  el.textContent = parts.join(" · ");
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(async () => {
    try {
      const st = await api("/api/status");
      if (!st.running) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        await load();
        if (state.detailsId) openDetails(state.detailsId);
      } else {
        renderStatus(st);
      }
    } catch (e) { /* the Pi may be busy; try again on the next tick */ }
  }, 3000);
}

async function refresh(componentId) {
  try {
    const st = await api("/api/refresh", { method: "POST", body: componentId ? { component_id: componentId } : {} });
    renderStatus(st);
    startPolling();
  } catch (e) {
    toast(e.message);
  }
}

// --- add / edit form -----------------------------------------------------

function openForm(component, prefill = {}) {
  const form = $("#component-form");
  form.reset();
  state.editId = component ? component.id : null;
  $("#form-title").textContent = component ? "Изменить комплектующее" : "Новое комплектующее";
  const values = component
    ? { ...component, name: component.name_auto ? "" : component.name }
    : { quantity: 1, purchase_date: todayIso(), ...prefill };
  for (const key of ["url", "name", "category", "purchase_price", "quantity", "purchase_date"]) {
    if (values[key] != null) form.elements[key].value = values[key];
  }
  $("#form-error").hidden = true;
  $("#form-dialog").showModal();
}

$("#component-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target.elements;
  const body = {
    url: f.url.value.trim() || null,
    name: f.name.value.trim() || null,
    category: f.category.value.trim(),
    purchase_price: Number(f.purchase_price.value),
    quantity: Number(f.quantity.value),
    purchase_date: f.purchase_date.value,
  };
  try {
    if (state.editId) {
      await api(`/api/components/${state.editId}`, { method: "PUT", body });
    } else {
      await api("/api/components", { method: "POST", body });
      if (body.url) toast("Добавил. Сейчас схожу в DNS за актуальной ценой — это займёт минуту.");
    }
    $("#form-dialog").close();
    await load();
    if (state.editId && state.detailsId === state.editId) openDetails(state.editId);
  } catch (e) {
    const err = $("#form-error");
    err.textContent = e.message;
    err.hidden = false;
  }
});

// --- details -------------------------------------------------------------

let detailsChart = null;

async function openDetails(id) {
  const c = await api(`/api/components/${id}`);
  state.detailsId = id;
  $("#d-category").textContent = c.category || "";
  $("#d-name").textContent = c.name + (c.quantity > 1 ? ` × ${c.quantity}` : "");
  const link = $("#d-link");
  link.hidden = !c.url;
  link.href = c.url || "#";
  $("#d-refresh").hidden = !c.url;

  const t = trend(c.change);
  $("#d-stats").innerHTML = `
    <div class="stat"><div class="stat-label">Купил за</div><div class="v">${rub.format(c.purchase_price)}</div><div class="stat-sub">${fmtDate(c.purchase_date)}</div></div>
    <div class="stat"><div class="stat-label">Сейчас в DNS</div><div class="v">${rub.format(c.current_price)}</div><div class="stat-sub">${c.priced_at ? fmtDate(c.priced_at) : "ещё нет данных"}</div></div>
    <div class="stat"><div class="stat-label">Изменение</div><div class="v ${t}">${signedPct(c.change_pct) || "0,0 %"}</div><div class="stat-sub ${t}">${signedRub(c.change)}</div></div>`;

  const dlg = $("#details-dialog");
  if (!dlg.open) dlg.showModal();

  if (detailsChart) detailsChart.remove();
  detailsChart = makeChart($("#d-chart"));
  const series = detailsChart.addSeries(LC.AreaSeries, { lineWidth: 2, priceLineVisible: false, ...areaColors(c.change >= 0) });
  series.setData(c.series.map((p) => ({ time: p.date, value: p.price })));
  series.createPriceLine({ price: c.purchase_price, color: css("--cost"), lineStyle: LC.LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: "покупка" });
  detailsChart.timeScale().fitContent();

  $("#d-debug").hidden = !c.debug;
  const stamp = Date.now();
  for (const a of document.querySelectorAll("#d-debug [data-debug]")) {
    a.href = `/api/components/${c.id}/debug.${a.dataset.debug}?t=${stamp}`;
  }

  const sourceName = { auto: "авто", manual: "вручную", bookmarklet: "закладка" };
  $("#d-history").innerHTML = c.history.length
    ? c.history.map((p) => `<tr>
        <td>${fmtDateTime(p.checked_at)}</td>
        <td class="num">${p.price != null ? rub.format(p.price) : `<span class="down">${p.available === 0 ? "нет в наличии" : "—"}</span>`}</td>
        <td class="src">${sourceName[p.source] || p.source}${p.error ? ` · <span title="${esc(p.error)}">${esc(p.error.slice(0, 60))}</span>` : ""}</td>
        <td class="num"><button class="del" data-price="${p.id}" title="Удалить запись" aria-label="Удалить запись">${icon("close")}</button></td>
      </tr>`).join("")
    : '<tr><td class="src">Проверок ещё не было</td></tr>';
}

$("#positions tbody").addEventListener("click", (ev) => {
  const row = ev.target.closest("tr[data-id]");
  if (row) openDetails(Number(row.dataset.id)).catch((e) => toast(e.message));
});
$("#positions tbody").addEventListener("keydown", (ev) => {
  const row = ev.target.closest("tr[data-id]");
  if (row && (ev.key === "Enter" || ev.key === " ")) {
    ev.preventDefault();
    openDetails(Number(row.dataset.id)).catch((e) => toast(e.message));
  }
});
$("#ticker-track").addEventListener("click", (ev) => {
  const tick = ev.target.closest(".tick[data-id]");
  if (tick) openDetails(Number(tick.dataset.id)).catch((e) => toast(e.message));
});

$("#d-history").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-price]");
  if (!btn || !confirm("Удалить эту запись о цене?")) return;
  await api(`/api/prices/${btn.dataset.price}`, { method: "DELETE" });
  await Promise.all([load(), openDetails(state.detailsId)]);
});

$("#manual-price").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target.elements;
  try {
    await api(`/api/components/${state.detailsId}/prices`, {
      method: "POST",
      body: { price: Number(f.price.value), date: f.date.value || null },
    });
    ev.target.reset();
    await Promise.all([load(), openDetails(state.detailsId)]);
  } catch (e) {
    toast(e.message);
  }
});

$("#d-edit").addEventListener("click", () => {
  const c = state.data.components.find((x) => x.id === state.detailsId);
  if (c) openForm(c);
});

$("#d-refresh").addEventListener("click", () => refresh(state.detailsId));

$("#d-delete").addEventListener("click", async () => {
  if (!confirm("Удалить комплектующее вместе со всей историей цен?")) return;
  await api(`/api/components/${state.detailsId}`, { method: "DELETE" });
  $("#details-dialog").close();
  await load();
});

$("#details-dialog").addEventListener("close", () => { state.detailsId = null; });

// --- bookmarklet ---------------------------------------------------------

function bookmarkletCode(origin) {
  const body = `(function(){
    var e=document.querySelector('.product-buy__price'),t='';
    if(e){for(var i=0;i<e.childNodes.length;i++){var n=e.childNodes[i];if(n.nodeType===3)t+=n.textContent;}if(!/\\d/.test(t))t=e.textContent;}
    var m=t.replace(/[\\s\\u00a0\\u2009\\u202f]/g,'').match(/\\d+/);
    var h=document.querySelector('.product-card-top__title')||document.querySelector('h1');
    var q=new URLSearchParams({url:location.href,price:m?m[0]:'',name:h?h.textContent.trim():''});
    window.open(${JSON.stringify(origin)}+'/#capture?'+q.toString(),'_blank');
  })();`;
  return "javascript:" + body.replace(/\n\s*/g, "");
}

async function handleCapture() {
  if (!location.hash.startsWith("#capture?")) return;
  const params = new URLSearchParams(location.hash.slice("#capture?".length));
  history.replaceState(null, "", location.pathname);
  const price = Number(params.get("price")) || null;
  try {
    const res = await api("/api/capture", { method: "POST", body: { url: params.get("url"), price, name: params.get("name") } });
    if (res.matched) {
      toast(price ? `Записал ${rub.format(price)} для «${res.component.name}»` : "Цену на странице найти не удалось", 6000);
      await load();
    } else {
      toast("Этого товара ещё нет в портфеле — добавь цену покупки.", 6000);
      openForm(null, { url: params.get("url"), name: params.get("name") });
    }
  } catch (e) {
    toast(e.message, 6000);
  }
}

// --- wiring --------------------------------------------------------------

$("#bookmarklet").href = bookmarkletCode(location.origin);
$("#bookmarklet").addEventListener("click", (ev) => {
  ev.preventDefault();
  toast("Перетащи эту кнопку на панель закладок браузера");
});
$("#add-btn").addEventListener("click", () => openForm(null));
$("#refresh-btn").addEventListener("click", () => refresh());
document.addEventListener("click", (ev) => {
  if (ev.target.closest("[data-action=add]")) openForm(null);
  const closer = ev.target.closest("[data-close]");
  if (closer) closer.closest("dialog").close();
});
$("#range-tabs").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-days]");
  if (!btn) return;
  for (const b of $("#range-tabs").children) b.classList.toggle("active", b === btn);
  state.rangeDays = Number(btn.dataset.days);
  applyRange();
});

load().then(handleCapture).catch((e) => toast("Не удалось загрузить данные: " + e.message, 8000));
