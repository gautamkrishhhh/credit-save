/* CreditSage SPA — vanilla JS, no build step. */
"use strict";

// ------------------------------------------------------------------ utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (v, d = 0) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const num = (v, d = 0) => Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: d });
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<i>$2</i>").replace(/_\((.+?)\)_/g, '<span class="muted">($1)</span>');
const COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c8)"];

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 2600);
}
function modal(html) { $("#modalBox").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

let META = null, CATALOG = null;
async function meta() { return META || (META = await api("/catalog/meta")); }
async function catalog() { return CATALOG || (CATALOG = await api("/catalog/cards")); }
const catName = (c) => (META && META.categories[c]) || c;

// ------------------------------------------------------------------ charts (inline SVG)
function barChart(rows, { height = 200, fmt = inr, color = "var(--c1)", highlightLast = false } = {}) {
  if (!rows.length) return '<div class="empty small">No data yet</div>';
  const W = 600, H = height, pad = { l: 8, r: 8, t: 18, b: 26 };
  const max = Math.max(...rows.map((r) => r.value), 1);
  const bw = (W - pad.l - pad.r) / rows.length;
  const bars = rows.map((r, i) => {
    const h = ((H - pad.t - pad.b) * r.value) / max;
    const x = pad.l + i * bw + bw * 0.18, y = H - pad.b - h;
    const fill = r.color || (highlightLast && i === rows.length - 1 ? "var(--c2)" : color);
    return `<rect x="${x}" y="${y}" width="${bw * 0.64}" height="${Math.max(h, 1)}" rx="4" fill="${fill}"><title>${esc(r.label)}: ${fmt(r.value)}</title></rect>
      <text x="${x + bw * 0.32}" y="${y - 5}" text-anchor="middle">${fmt(r.value).replace("₹", "₹")}</text>
      <text x="${x + bw * 0.32}" y="${H - 8}" text-anchor="middle">${esc(r.label)}</text>`;
  }).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img">${bars}</svg>`;
}

function hbars(rows, { fmt = inr } = {}) {
  if (!rows.length) return '<div class="empty small">No data yet</div>';
  const max = Math.max(...rows.map((r) => r.value), 1);
  return rows.map((r, i) => `<div style="margin:7px 0">
    <div class="row between small"><span>${esc(r.label)}</span><b>${fmt(r.value)}</b></div>
    <div class="bar"><span style="width:${(100 * r.value) / max}%;background:${r.color || COLORS[i % COLORS.length]}"></span></div></div>`).join("");
}

function donut(rows, { size = 170, center = "" } = {}) {
  const total = rows.reduce((a, r) => a + r.value, 0) || 1;
  const R = 70, C = 2 * Math.PI * R;
  let off = 0;
  const arcs = rows.map((r, i) => {
    const len = (C * r.value) / total;
    const s = `<circle r="${R}" cx="90" cy="90" fill="none" stroke="${COLORS[i % COLORS.length]}" stroke-width="22" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 90 90)"><title>${esc(r.label)}: ${inr(r.value)}</title></circle>`;
    off += len;
    return s;
  }).join("");
  const legend = rows.map((r, i) => `<span style="--c:${COLORS[i % COLORS.length]}">${esc(r.label)} ${Math.round((100 * r.value) / total)}%</span>`).join("");
  return `<div class="row gap wrap"><svg viewBox="0 0 180 180" width="${size}" height="${size}">${arcs}
    <text x="90" y="86" text-anchor="middle" style="font-size:12px">Total</text><text x="90" y="104" text-anchor="middle" style="font-size:15px;font-weight:700;fill:var(--ink)">${esc(center)}</text></svg>
    <div class="legend" style="flex:1;min-width:160px">${legend}</div></div>`;
}

function forecastChart(months, history, fc) {
  const pts = history.map((v, i) => ({ x: i, v }));
  const n = pts.length + 1;
  const all = [...history, fc.upper || fc.point];
  const max = Math.max(...all, 1) * 1.1;
  const W = 600, H = 210, pl = 50, pr = 14, pt = 12, pb = 28;
  const X = (i) => pl + ((W - pl - pr) * i) / Math.max(n - 1, 1);
  const Y = (v) => H - pb - ((H - pt - pb) * v) / max;
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(p.x)},${Y(p.v)}`).join("");
  const last = pts[pts.length - 1];
  const fx = X(n - 1);
  const grid = [0, 0.5, 1].map((f) => `<line x1="${pl}" x2="${W - pr}" y1="${Y(max * f / 1.1)}" y2="${Y(max * f / 1.1)}" stroke="var(--line)"/><text x="${pl - 6}" y="${Y(max * f / 1.1) + 4}" text-anchor="end">${inr(max * f / 1.1 / 1000)}k</text>`).join("");
  const labels = [...months, "Next"].map((m, i) => `<text x="${X(i)}" y="${H - 8}" text-anchor="middle">${esc(m.length > 5 ? m.slice(5) + "/" + m.slice(2, 4) : m)}</text>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${grid}${labels}
    <polygon points="${X(last.x)},${Y(last.v)} ${fx},${Y(fc.upper)} ${fx},${Y(fc.lower)}" fill="var(--c2)" opacity=".15"/>
    <path d="${line}" fill="none" stroke="var(--c1)" stroke-width="2.5"/>
    ${pts.map((p) => `<circle cx="${X(p.x)}" cy="${Y(p.v)}" r="3.5" fill="var(--c1)"><title>${inr(p.v)}</title></circle>`).join("")}
    <line x1="${X(last.x)}" y1="${Y(last.v)}" x2="${fx}" y2="${Y(fc.point)}" stroke="var(--c2)" stroke-width="2.5" stroke-dasharray="5 4"/>
    <circle cx="${fx}" cy="${Y(fc.point)}" r="5" fill="var(--c2)"><title>Forecast ${inr(fc.point)}</title></circle>
    <text x="${fx - 6}" y="${Y(fc.point) - 10}" text-anchor="end" style="fill:var(--c2);font-weight:700">${inr(fc.point)}</text></svg>`;
}

const cardVisual = (c, extra = "") => `<div class="ccard t-${esc(c.card.tier)}">
  <div class="row between"><span class="issuer">${esc(c.card.issuer)}</span><span class="issuer">${esc(c.card.network)}</span></div>
  <div><div class="name">${esc(c.display_name)}</div><div class="num">•••• ${esc(c.last4 || "0000")}</div></div>
  <div class="row between"><span>${num(c.points_balance)} ${esc(c.card.reward_currency)}</span><b>${inr(c.points_value)}</b></div>${extra}</div>`;

// ------------------------------------------------------------------ views
const VIEWS = {};

VIEWS.dashboard = async (v) => {
  const d = await api("/dashboard");
  if (!d.cards) return v.innerHTML = onboarding();
  const cats = d.by_category.slice(0, 7).map((c) => ({ label: c.name, value: c.amount }));
  const effCls = d.month.efficiency_pct >= 85 ? "good" : d.month.efficiency_pct >= 60 ? "warn" : "bad";
  v.innerHTML = `
  <div class="grid g4">
    <div class="panel stat"><div class="label">Rewards value</div><div class="value good">${inr(d.points_value.best)}</div><div class="sub">${inr(d.points_value.cash)} as cash · ${d.cards} cards</div></div>
    <div class="panel stat"><div class="label">Spent this month</div><div class="value">${inr(d.month.spend)}</div><div class="sub">${d.month.txns} transactions</div></div>
    <div class="panel stat"><div class="label">Earned this month</div><div class="value">${inr(d.month.rewards)}</div><div class="sub">Missed <span class="bad">${inr(d.month.missed)}</span></div></div>
    <div class="panel stat"><div class="label">Card-choice efficiency</div><div class="value ${effCls}">${d.ytd.efficiency_pct}%</div><div class="sub">YTD missed ${inr(d.ytd.missed)} of ${inr(d.ytd.rewards + d.ytd.missed)}</div></div>
  </div>
  <div class="grid g2" style="margin-top:16px">
    <div class="panel"><h2>Monthly spend</h2>${barChart(d.trend.map((t) => ({ label: t.month.slice(5) + "/" + t.month.slice(2, 4), value: t.spend })), { highlightLast: true, fmt: (x) => inr(x / 1000, 0) + "k" })}</div>
    <div class="panel"><h2>This month by category</h2>${donut(cats, { center: inr(d.month.spend) })}</div>
  </div>
  <div class="grid g3" style="margin-top:16px">
    <div class="panel span2"><div class="row between"><h2>Missed savings — biggest this month</h2><a href="#/which-card" class="small">Check before you pay →</a></div>
      ${d.top_misses.length ? `<table><tr><th>Date</th><th>Merchant</th><th class="num">Amount</th><th>Used</th><th>Better card</th><th class="num">Missed</th></tr>
      ${d.top_misses.map((m) => `<tr><td>${m.date.slice(5)}</td><td>${esc(m.merchant)}</td><td class="num">${inr(m.amount)}</td><td>${esc(m.used)}</td><td><span class="tag green">${esc(m.better)}</span></td><td class="num bad">+${inr(m.missed)}</td></tr>`).join("")}</table>` : '<div class="empty small">🎉 You used the optimal card for every transaction this month.</div>'}
    </div>
    <div class="panel"><h2>Heads-up</h2><div class="stack">
      ${d.expiring.map((c) => `<div class="tag red">⏳ ${num(c.balance)} pts on ${esc(c.name)} expire in ${c.expiring.days} days</div>`).join("")}
      ${d.upcoming_milestones.map((m) => `<div><div class="row between small"><span>${esc(m.card)} · ${esc(m.label)}</span><b>${m.pct}%</b></div><div class="bar ${m.on_track ? "" : "warn"}"><span style="width:${m.pct}%"></span></div><div class="small muted">${inr(m.remaining)} to go · worth ${inr(m.reward_value)}</div></div>`).join("") || '<div class="muted small">No pending milestones.</div>'}
    </div></div>
  </div>
  <div class="panel" style="margin-top:16px"><h2>Your cards this month</h2><div class="grid g4">
    ${d.wallet.map((c) => `<div>${cardVisual(c)}<div class="small" style="margin-top:8px">Spent ${inr(c.month_spend)} · earned <b class="good">${inr(c.month_value)}</b></div>
      ${c.caps.map((cp) => `<div class="small muted" style="margin-top:4px">${esc(cp.rule)} cap ${cp.pct}%</div><div class="bar ${cp.pct >= 100 ? "red" : cp.pct > 75 ? "warn" : ""}"><span style="width:${Math.min(cp.pct, 100)}%"></span></div>`).join("")}</div>`).join("")}
  </div></div>`;
};

function onboarding() {
  return `<div class="panel empty"><div class="big">🦉</div><h2>Welcome to CreditSage</h2>
    <p>Add your credit cards to see which card to use, what your points are worth and how much you're leaving on the table.</p>
    <div class="row gap" style="justify-content:center"><a class="btn" href="#/wallet">Add my cards</a><button class="btn ghost" onclick="seed()">Explore with demo data</button></div></div>`;
}

VIEWS["which-card"] = async (v) => {
  const m = await meta();
  const popular = ["swiggy", "zomato", "amazon", "flipkart", "myntra", "bigbasket", "uber", "makemytrip", "smartbuy", "airtel", "croma", "taj"];
  v.innerHTML = `<div class="grid g3">
    <div class="panel"><h2>Where are you paying?</h2><div class="stack">
      <label>Merchant or description<input id="wcQuery" placeholder="e.g. Swiggy, HP petrol pump, Taj hotel" list="merchantList"></label>
      <datalist id="merchantList">${Object.values(m.merchants).map((x) => `<option value="${esc(x.name)}">`).join("")}</datalist>
      <label>…or a category<select id="wcCat"><option value="">—</option>${Object.entries(m.categories).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join("")}</select></label>
      <label>Amount (₹)<input id="wcAmt" type="number" min="1" value="1000"></label>
      <button class="btn" id="wcGo">Find best card</button>
      <div><div class="small muted" style="margin-bottom:6px">Popular</div><div class="chips">${popular.map((p) => `<button class="chip" data-m="${p}">${esc(m.merchants[p].name)}</button>`).join("")}</div></div>
    </div></div>
    <div class="panel span2" id="wcOut"><div class="empty"><div class="big">⚡</div>Pick a merchant to see which of your cards returns the most — caps, exclusions and live offers included.</div></div></div>`;
  const run = async () => {
    const amount = +$("#wcAmt").value || 1000;
    const q = $("#wcQuery").value.trim(), cat = $("#wcCat").value;
    const mid = Object.entries(m.merchants).find(([k, x]) => x.name.toLowerCase() === q.toLowerCase())?.[0];
    const body = { amount };
    if (mid) body.merchant = mid; else if (q) body.query = q; else if (cat) body.category = cat; else return toast("Enter a merchant or pick a category");
    const r = await api("/recommend/best-card", { body });
    $("#wcOut").innerHTML = renderBest(r);
  };
  $("#wcGo").onclick = run;
  $("#wcQuery").addEventListener("keydown", (e) => e.key === "Enter" && run());
  $$(".chip[data-m]", v).forEach((c) => (c.onclick = () => { $("#wcQuery").value = m.merchants[c.dataset.m].name; $("#wcCat").value = ""; run(); }));
};

function renderBest(r) {
  if (!r.ranked.length) return `<div class="empty">Add cards to your wallet first. <a href="#/wallet">My Cards →</a></div>`;
  const cls = r.classification ? `<span class="tag blue">ML: ${esc(catName(r.classification.category))} · ${Math.round(r.classification.confidence * 100)}% (${esc(r.classification.method)})</span>` : "";
  return `<div class="row between wrap gap"><h2>${inr(r.amount)} at ${esc(r.merchant_name || r.category_name)}</h2><div class="row gap">${cls}<span class="tag">${esc(r.category_name)}</span></div></div>
    ${r.ranked.map((x, i) => `<div class="rank ${i === 0 ? "best" : ""}"><div class="pos">${i + 1}</div>
      <div class="grow"><b>${esc(x.name)}</b> <span class="muted small">${esc(x.issuer)}</span>
        <div class="small muted">${num(x.points, 1)} ${esc(x.currency)} · ${esc(x.rule)}${x.offer ? ` · <span class="good">+ offer: ${esc(x.offer.title)}</span>` : ""}</div>
        ${x.notes.map((n) => `<div class="small warn">⚠ ${esc(n)}</div>`).join("")}</div>
      <div><div class="big ${i === 0 ? "good" : ""}">${inr(x.total_value)}</div><div class="small muted" style="text-align:right">${x.effective_pct}% back</div></div></div>`).join("")}
    ${r.not_owned_suggestion ? `<div class="panel" style="margin-top:12px;background:var(--panel2)">💡 Not in your wallet: <b>${esc(r.not_owned_suggestion.name)}</b> would return <b>${r.not_owned_suggestion.effective_pct}%</b> here (+${inr(r.not_owned_suggestion.extra_value)}). <a href="#/discover">See if it's worth it →</a></div>` : ""}`;
}

VIEWS.wallet = async (v) => {
  const w = await api("/wallet");
  v.innerHTML = `<div class="row between" style="margin-bottom:14px"><div class="muted">${w.length} card(s). Keep point balances updated from your statements for accurate valuations.</div><button class="btn" id="addCard">+ Add card</button></div>
  ${w.length ? `<div class="grid g3">${w.map((c) => `<div class="panel">${cardVisual(c)}
    <dl class="kv" style="margin-top:12px"><dt>Value / point</dt><dd>₹${c.value_per_point}</dd><dt>Annual fee</dt><dd>${inr(c.card.annual_fee)}${c.card.fee_waiver_spend ? ` <span class="muted small">(waived at ${inr(c.card.fee_waiver_spend)})</span>` : ""}</dd>
    <dt>12-month spend</dt><dd>${inr(c.spend_12m)}</dd><dt>Points expiry</dt><dd>${esc(c.points_expiry || "—")}</dd><dt>Base return</dt><dd>${c.card.base_return_pct}% · up to ${c.card.top_return_pct}%</dd></dl>
    ${c.caps.map((cp) => `<div class="small muted" style="margin-top:6px">${esc(cp.rule)}: ${num(cp.used)} / ${num(cp.cap)} this month</div><div class="bar ${cp.pct >= 100 ? "red" : cp.pct > 75 ? "warn" : ""}"><span style="width:${Math.min(cp.pct, 100)}%"></span></div>`).join("")}
    <div class="row gap" style="margin-top:12px"><button class="btn ghost sm" data-edit="${c.id}">Update balance</button><button class="btn ghost sm" data-del="${c.id}">Remove</button></div></div>`).join("")}</div>` : onboarding()}`;
  $("#addCard").onclick = addCardModal;
  $$("[data-edit]", v).forEach((b) => (b.onclick = () => editCardModal(w.find((c) => c.id == b.dataset.edit))));
  $$("[data-del]", v).forEach((b) => (b.onclick = async () => { if (confirm("Remove this card?")) { await api("/wallet/" + b.dataset.del, { method: "DELETE" }); render(); } }));
};

async function addCardModal() {
  const cards = await catalog();
  modal(`<div class="row between"><h2>Add a card</h2><button class="btn ghost sm" onclick="closeModal()">✕</button></div>
    <input id="catSearch" placeholder="Search 20 cards…" style="width:100%;margin-bottom:10px">
    <div id="catList">${cards.map((c) => `<div class="catalog-item" data-id="${c.id}" data-s="${esc((c.name + " " + c.issuer).toLowerCase())}"><div class="swatch t-${c.tier}"></div>
      <div style="flex:1"><b>${esc(c.name)}</b><div class="small muted">${esc(c.issuer)} · ${inr(c.annual_fee)} fee · ${c.base_return_pct}% base</div></div><span class="tag">${esc(c.tier.replace("_", " "))}</span></div>`).join("")}</div>`);
  $("#catSearch").oninput = (e) => $$(".catalog-item").forEach((el) => (el.style.display = el.dataset.s.includes(e.target.value.toLowerCase()) ? "" : "none"));
  $$(".catalog-item").forEach((el) => (el.onclick = () => {
    const c = cards.find((x) => x.id === el.dataset.id);
    modal(`<h2>${esc(c.name)}</h2><div class="stack">
      <label>Nickname<input id="fNick" value="${esc(c.name)}"></label>
      <div class="grid g2"><label>Last 4 digits (for SMS matching)<input id="fLast4" maxlength="4" placeholder="1234"></label>
      <label>Current ${esc(c.reward_currency)} balance<input id="fPts" type="number" min="0" value="0"></label></div>
      <label>Points expiry date (optional)<input id="fExp" type="date"></label>
      <div class="row gap"><button class="btn" id="fSave">Add to wallet</button><button class="btn ghost" onclick="closeModal()">Cancel</button></div></div>`);
    $("#fSave").onclick = async () => {
      try {
        await api("/wallet", { method: "POST", body: { card_id: c.id, nickname: $("#fNick").value || null, last4: $("#fLast4").value || null, points_balance: +$("#fPts").value || 0, points_expiry: $("#fExp").value || null } });
        closeModal(); toast("Card added"); render();
      } catch (e) { toast(e.message); }
    };
  }));
}

function editCardModal(c) {
  modal(`<h2>${esc(c.display_name)}</h2><div class="stack">
    <label>Nickname<input id="eNick" value="${esc(c.nickname || "")}"></label>
    <div class="grid g2"><label>${esc(c.card.reward_currency)} balance<input id="ePts" type="number" min="0" value="${c.points_balance}"></label>
    <label>Last 4<input id="eLast4" maxlength="4" value="${esc(c.last4 || "")}"></label></div>
    <label>Points expiry<input id="eExp" type="date" value="${esc(c.points_expiry || "")}"></label>
    <div class="row gap"><button class="btn" id="eSave">Save</button><button class="btn ghost" onclick="closeModal()">Cancel</button></div></div>`);
  $("#eSave").onclick = async () => {
    try {
      await api("/wallet/" + c.id, { method: "PATCH", body: { nickname: $("#eNick").value || null, points_balance: +$("#ePts").value, last4: $("#eLast4").value || null, points_expiry: $("#eExp").value || null } });
      closeModal(); toast("Saved"); render();
    } catch (e) { toast(e.message); }
  };
}

VIEWS.transactions = async (v) => {
  const [txns, w, m] = await Promise.all([api("/transactions?limit=400"), api("/wallet"), meta()]);
  const cardOpts = `<option value="">— card —</option>` + w.map((c) => `<option value="${c.id}">${esc(c.display_name)}</option>`).join("");
  const catOpts = (sel) => Object.entries(m.categories).map(([k, n]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  v.innerHTML = `<div class="grid g2">
    <div class="panel"><h2>Add transaction</h2><div class="stack">
      <div class="grid g2"><label>Description / merchant<input id="tDesc" placeholder="e.g. Swiggy, Meghana Foods"></label><label>Amount (₹)<input id="tAmt" type="number" min="1"></label></div>
      <div class="grid g2"><label>Card<select id="tCard">${cardOpts}</select></label><label>Date<input id="tDate" type="date" value="${new Date().toISOString().slice(0, 10)}"></label></div>
      <div id="tPred" class="small muted">Category is predicted by the ML model as you type.</div>
      <button class="btn" id="tAdd">Add</button></div></div>
    <div class="panel"><h2>Import from bank SMS</h2><div class="stack">
      <textarea id="smsText" placeholder="Paste one or more card alert SMS (blank line between them)">Rs.1,250.00 spent on HDFC Bank Card x1234 at SWIGGY on ${new Date().toISOString().slice(0, 10)}

INR 2,499.00 spent using Axis Bank Card XX5678 on ${new Date().toLocaleDateString("en-GB").replace(/\//g, "-")} at MEGHANA FOODS. Avl Limit: INR 1,20,000

Thank you for using SBI Card ending 3456 for Rs 890 at NAYARA ENERGY on ${new Date().toLocaleDateString("en-GB")}.</textarea>
      <div class="row gap"><button class="btn ghost" id="smsPrev">Preview</button><button class="btn" id="smsImp">Import</button></div><div id="smsOut"></div></div></div></div>
  <div class="panel" style="margin-top:16px"><div class="row between"><h2>History</h2><span class="muted small">${txns.length} shown · change a category to teach the model</span></div>
  <div class="scroll-x"><table><tr><th>Date</th><th>Description</th><th>Category</th><th>Card</th><th class="num">Amount</th><th></th></tr>
  ${txns.map((t) => `<tr><td>${esc(t.txn_date)}</td><td>${esc(t.merchant_name || t.description)} ${t.is_anomaly ? '<span class="tag red" title="Unusual for you">unusual</span>' : ""} ${t.source === "sms" ? '<span class="tag blue">sms</span>' : ""}</td>
    <td><select data-cat="${t.id}" style="padding:3px 6px;font-size:12px">${catOpts(t.category)}</select> ${t.category_confidence < 0.6 ? `<span class="tag warn" title="Low model confidence">${Math.round(t.category_confidence * 100)}%</span>` : ""}</td>
    <td class="small">${esc(t.card_name || "—")}</td><td class="num ${t.is_refund ? "good" : ""}">${t.is_refund ? "−" : ""}${inr(t.amount)}</td><td><button class="btn ghost sm" data-deltx="${t.id}">✕</button></td></tr>`).join("")}</table></div></div>`;
  let debounce;
  $("#tDesc").oninput = (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(async () => {
      if (!e.target.value.trim()) return;
      const c = await api("/ml/classify", { body: { text: e.target.value } });
      $("#tPred").innerHTML = `Predicted: <b>${esc(catName(c.category))}</b> · ${Math.round(c.confidence * 100)}% via ${esc(c.method)}${c.alternatives?.length ? ` <span class="muted">(${c.alternatives.slice(1).map((a) => esc(catName(a[0])) + " " + Math.round(a[1] * 100) + "%").join(", ")})</span>` : ""}`;
    }, 250);
  };
  $("#tAdd").onclick = async () => {
    try {
      await api("/transactions", { method: "POST", body: { description: $("#tDesc").value, amount: +$("#tAmt").value, user_card_id: +$("#tCard").value || null, txn_date: $("#tDate").value } });
      toast("Added"); render();
    } catch (e) { toast(e.message); }
  };
  $("#smsPrev").onclick = async () => {
    const rows = await api("/transactions/sms/preview", { body: { text: $("#smsText").value } });
    $("#smsOut").innerHTML = `<table><tr><th>Parsed</th><th>Merchant</th><th>Category</th><th>Card</th><th class="num">Amount</th></tr>${rows.map((r) => r.ok
      ? `<tr><td>✅ ${esc(r.txn_date)}</td><td>${esc(r.merchant_text || "—")}</td><td>${esc(catName(r.classification.category))} <span class="muted small">${Math.round(r.classification.confidence * 100)}%</span></td><td>${r.user_card_id ? esc(w.find((c) => c.id === r.user_card_id)?.display_name) : `<span class="warn small">x${esc(r.last4 || "?")} unmatched</span>`}</td><td class="num">${r.is_refund ? "−" : ""}${inr(r.amount, 2)}</td></tr>`
      : `<tr><td colspan="5" class="bad small">✗ ${esc(r.error)}: ${esc(r.raw.slice(0, 60))}</td></tr>`).join("")}</table>`;
  };
  $("#smsImp").onclick = async () => {
    const r = await api("/transactions/sms/import", { body: { text: $("#smsText").value } });
    toast(`Imported ${r.imported.length}, skipped ${r.skipped.length}`); render();
  };
  $$("[data-cat]", v).forEach((s) => (s.onchange = async () => { await api("/transactions/" + s.dataset.cat, { method: "PATCH", body: { category: s.value } }); toast("Category saved — the model will learn from this on retrain"); }));
  $$("[data-deltx]", v).forEach((b) => (b.onclick = async () => { await api("/transactions/" + b.dataset.deltx, { method: "DELETE" }); render(); }));
};

VIEWS.rewards = async (v) => {
  const [r, ms, goals, m] = await Promise.all([api("/redeem"), api("/milestones"), api("/goals"), meta()]);
  v.innerHTML = `<div class="grid g3">
    <div class="panel stat"><div class="label">Best-value redemption</div><div class="value good">${inr(r.totals.best)}</div><div class="sub">via transfer partners</div></div>
    <div class="panel stat"><div class="label">Travel portal</div><div class="value">${inr(r.totals.portal)}</div></div>
    <div class="panel stat"><div class="label">As cash / statement credit</div><div class="value">${inr(r.totals.cash)}</div><div class="sub bad">${inr(r.totals.best - r.totals.cash)} lost if you cash out</div></div></div>
  <div class="grid g2" style="margin-top:16px">${r.cards.filter((c) => c.options.length).map((c) => `<div class="panel">
    <div class="row between"><h2>${esc(c.name)}</h2><span class="tag">${num(c.balance)} ${esc(c.currency)}</span></div>
    ${c.expiring ? `<div class="tag red" style="margin-bottom:8px">⏳ expires in ${c.expiring.days} days (${esc(c.expiring.date)})</div>` : ""}
    <table><tr><th>Option</th><th class="num">₹/pt</th><th class="num">Value</th></tr>${c.options.slice(0, 6).map((o, i) => `<tr><td>${i === 0 ? "🏆 " : ""}${esc(o.type)}${o.ratio ? ` <span class="muted small">1:${o.ratio}</span>` : ""}</td><td class="num">${o.per_point.toFixed(2)}</td><td class="num ${i === 0 ? "good" : ""}">${inr(o.value)}</td></tr>`).join("")}</table></div>`).join("")}</div>
  <div class="grid g2" style="margin-top:16px">
    <div class="panel"><h2>Transfer goal planner</h2><div class="stack">
      <div class="grid g2"><label>Programme<select id="gP">${Object.entries(m.partners).map(([k, p]) => `<option value="${k}">${esc(p.name)}</option>`).join("")}</select></label>
      <label>Points needed<input id="gN" type="number" value="60000"></label></div>
      <div class="row gap"><button class="btn" id="gGo">Plan</button><button class="btn ghost" id="gSave">Save goal</button></div><div id="gOut"></div>
      ${goals.map((g) => `<div class="panel" style="background:var(--panel2)"><div class="row between"><b>${esc(g.name)}</b><button class="btn ghost sm" data-delgoal="${g.id}">✕</button></div>
        <div class="small muted">${num(g.plan.achievable)} / ${num(g.target_points)} ${esc(g.plan.partner_name)} reachable</div><div class="bar ${g.plan.complete ? "" : "warn"}"><span style="width:${Math.min(100, (100 * g.plan.achievable) / g.target_points)}%"></span></div></div>`).join("")}
    </div></div>
    <div class="panel"><h2>Milestones & fee waivers</h2>${ms.length ? ms.map((c) => `<div style="margin-bottom:14px"><div class="row between"><b>${esc(c.name)}</b><span class="small muted">projected ${inr(c.projected_annual)}/yr</span></div>
      ${c.milestones.map((x) => `<div style="margin-top:6px"><div class="row between small"><span>${esc(x.label)}</span><span>${x.achieved ? '<span class="tag green">achieved</span>' : x.on_track ? '<span class="tag green">on track</span>' : `<span class="tag warn">${inr(x.remaining)} to go</span>`}</span></div>
      <div class="bar ${x.achieved || x.on_track ? "" : "warn"}"><span style="width:${x.pct}%"></span></div></div>`).join("")}</div>`).join("") : '<div class="muted">No milestone cards in your wallet.</div>'}</div></div>`;
  const plan = async (save) => {
    const g = await api("/redeem/goal", { body: { partner: $("#gP").value, target_points: +$("#gN").value, save } });
    $("#gOut").innerHTML = g.steps.length ? `<table><tr><th>From</th><th class="num">Card pts</th><th>Ratio</th><th class="num">Partner pts</th></tr>${g.steps.map((s) => `<tr><td>${esc(s.card)}</td><td class="num">${num(s.transfer_card_points)}</td><td>${esc(s.ratio)}</td><td class="num">${num(s.partner_points)}</td></tr>`).join("")}</table>
      <div class="${g.complete ? "good" : "warn"}" style="margin-top:6px">${g.complete ? "✅ Reachable today" : `Short by ${num(g.shortfall)} points`} · worth ≈ ${inr(g.estimated_value_inr)}</div>` : `<div class="warn">None of your cards transfer to ${esc(g.partner_name)}.</div>`;
    if (save) render();
  };
  $("#gGo").onclick = () => plan(false);
  $("#gSave").onclick = () => plan(true);
  $$("[data-delgoal]", v).forEach((b) => (b.onclick = async () => { await api("/goals/" + b.dataset.delgoal, { method: "DELETE" }); render(); }));
};

VIEWS.discover = async (v, custom) => {
  v.innerHTML = '<div class="panel empty">Running the portfolio optimizer across 20 cards…</div>';
  const d = await api("/recommend/discover", { body: custom ? { profile: custom } : {} });
  const prof = d.profile;
  v.innerHTML = `<div class="grid g3">
    <div class="panel"><h2>Your spend profile</h2><div class="small muted" style="margin-bottom:8px">Source: <b>${esc(d.profile_source)}</b>${d.profile_source === "forecast" ? " (history re-scaled by the ML forecast)" : ""} · ${inr(d.monthly_spend)}/month</div>
      <div class="stack" id="profEdit">${prof.map((p) => `<label class="row between" style="flex-direction:row;align-items:center"><span>${esc(p.name)}</span><input data-p="${p.category}" type="number" value="${p.monthly}" style="width:110px;text-align:right"></label>`).join("")}</div>
      <button class="btn ghost sm" id="reRun" style="margin-top:10px">Re-run with these numbers</button></div>
    <div class="panel span2"><div class="row between wrap"><h2>Best cards to add</h2><span class="small muted">Current wallet nets <b>${inr(d.current_wallet_net)}</b>/yr (after fees)</span></div>
      ${d.recommendations.map((r, i) => `<div class="rank ${i === 0 ? "best" : ""}"><div class="pos">${i + 1}</div><div class="swatch t-${r.card.tier}"></div>
        <div class="grow"><b>${esc(r.card.name)}</b> <span class="small muted">${esc(r.card.issuer)} · fee ${inr(r.card.annual_fee)}</span>
        <div class="small muted">${r.why.map(esc).join(" · ") || "Marginal improvement"}</div></div>
        <div><div class="big ${r.incremental_value > 0 ? "good" : r.incremental_value < 0 ? "bad" : "muted"}">${r.incremental_value >= 0 ? "+" : ""}${inr(r.incremental_value)}</div><div class="small muted" style="text-align:right">per year</div></div></div>`).join("")}
      ${d.best_pair ? `<div class="panel" style="margin-top:12px;background:var(--panel2)">🧩 <b>Starting from scratch?</b> The best 2-card combo for your spending is <b>${d.best_pair.cards.map(esc).join(" + ")}</b> — ≈ <b class="good">${inr(d.best_pair.annual_net)}</b>/yr net.</div>` : ""}
    </div></div>
  <div class="panel" style="margin-top:16px"><h2>How your current wallet performs</h2><table><tr><th>Card</th><th class="num">Routed spend/yr</th><th class="num">Rewards</th><th class="num">Milestones</th><th class="num">Fee</th><th class="num">Net</th></tr>
    ${d.current_per_card.map((c) => `<tr><td>${esc(c.name)}</td><td class="num">${inr(c.annual_spend)}</td><td class="num">${inr(c.rewards)}</td><td class="num">${inr(c.milestones)}</td><td class="num">${inr(c.fee)}</td><td class="num ${c.net >= 0 ? "good" : "bad"}">${inr(c.net)}</td></tr>`).join("")}</table>
    <div class="small muted" style="margin-top:8px">Optimizer: greedy, cap-aware allocation of your monthly spend in chunks across cards, annualised with milestones and fee waivers.</div></div>`;
  $("#reRun").onclick = () => {
    const p = {};
    $$("[data-p]").forEach((i) => (p[i.dataset.p] = +i.value || 0));
    VIEWS.discover(v, p);
  };
};

VIEWS.compare = async (v) => {
  const cards = await catalog();
  const sel = (id, def) => `<select id="${id}">${cards.map((c) => `<option value="${c.id}" ${c.id === def ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select>`;
  v.innerHTML = `<div class="panel"><div class="row gap wrap">${sel("cA", "axis_atlas")}<span>vs</span>${sel("cB", "hdfc_infinia")}<span>vs</span><select id="cC"><option value="">(optional)</option>${cards.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select><button class="btn" id="cGo">Compare</button></div></div><div id="cOut" style="margin-top:16px"></div>`;
  const go = async () => {
    const ids = [$("#cA").value, $("#cB").value, $("#cC").value].filter(Boolean);
    const r = await api("/recommend/compare?ids=" + [...new Set(ids)].join(","));
    const best = Math.max(...r.cards.map((c) => c.annual_net_on_profile));
    const row = (label, f) => `<tr><td class="muted">${label}</td>${r.cards.map((c) => `<td>${f(c)}</td>`).join("")}</tr>`;
    $("#cOut").innerHTML = `<div class="panel scroll-x"><table><tr><th></th>${r.cards.map((c) => `<th>${esc(c.name)}</th>`).join("")}</tr>
      ${row("Net value on <b>your</b> spend / yr", (c) => `<b class="${c.annual_net_on_profile === best ? "good" : ""}">${inr(c.annual_net_on_profile)}</b>${c.annual_net_on_profile === best ? " 🏆" : ""}`)}
      ${row("Annual fee", (c) => inr(c.annual_fee) + (c.fee_waiver_spend ? ` <span class="small muted">waived @ ${inr(c.fee_waiver_spend)}</span>` : ""))}
      ${row("Base return", (c) => c.base_return_pct + "%")}${row("Top return", (c) => c.top_return_pct + "%")}
      ${row("Reward currency", (c) => esc(c.reward_currency) + ` <span class="small muted">₹${c.value_per_point}/pt</span>`)}
      ${row("Accelerators", (c) => c.rules.map((x) => `<div class="small">${esc(x.label)}</div>`).join("") || "—")}
      ${row("Lounges (dom/intl)", (c) => `${c.lounge.domestic} / ${c.lounge.international}`)}${row("Forex markup", (c) => c.forex_markup + "%")}
      ${row("Best transfer", (c) => c.best_transfer ? `${esc(META?.partners[c.best_transfer]?.name || c.best_transfer)} <span class="small muted">₹${c.best_transfer_value}/pt</span>` : "—")}
      ${row("Perks", (c) => c.perks.map((p) => `<div class="small">• ${esc(p)}</div>`).join(""))}</table></div>
      <div class="panel" style="margin-top:16px"><h2>Return by category (% of spend, ${esc(r.value_mode)} valuation)</h2><div class="scroll-x"><table><tr><th>Category</th>${r.cards.map((c) => `<th class="num">${esc(c.name)}</th>`).join("")}</tr>
      ${r.return_by_category_pct.map((g) => { const mx = Math.max(...r.cards.map((c) => g[c.id])); return `<tr><td>${esc(g.name)}</td>${r.cards.map((c) => `<td class="num ${g[c.id] === mx && mx > 0 ? "good" : g[c.id] === 0 ? "muted" : ""}">${g[c.id]}%</td>`).join("")}</tr>`; }).join("")}</table></div></div>`;
  };
  $("#cGo").onclick = go;
  await meta();
  go();
};

VIEWS.offers = async (v) => {
  const o = await api("/offers");
  v.innerHTML = `<div class="row gap" style="margin-bottom:12px"><button class="chip on" data-f="all">All offers</button><button class="chip" data-f="mine">On my cards</button></div>
  <div class="grid g3" id="offGrid">${o.map((x) => `<div class="panel" data-mine="${x.eligible_cards.length > 0}"><div class="row between"><span class="tag">${esc(x.merchant_name)}</span>${x.eligible_cards.length ? '<span class="tag green">eligible</span>' : ""}</div>
    <h3 style="margin-top:8px">${esc(x.title)}</h3><div class="small muted">Min ${inr(x.min_txn)}${x.max_discount ? ` · max ${inr(x.max_discount)}` : ""} · till ${esc(x.valid_till)}</div>
    <div class="small" style="margin-top:6px">${x.eligible_cards.length ? "Use: " + x.eligible_cards.map(esc).join(", ") : `<span class="muted">${esc((x.issuers || x.cards || []).join(", "))}</span>`}</div></div>`).join("")}</div>`;
  $$("[data-f]", v).forEach((b) => (b.onclick = () => { $$("[data-f]").forEach((x) => x.classList.toggle("on", x === b)); $$("#offGrid > .panel").forEach((p) => (p.style.display = b.dataset.f === "all" || p.dataset.mine === "true" ? "" : "none")); }));
};

VIEWS.insights = async (v) => {
  const [ins, ml] = await Promise.all([api("/insights"), api("/ml/status"), meta()]);
  const fc = ins.forecast;
  const cats = Object.entries(fc.categories).sort((a, b) => b[1].point - a[1].point);
  v.innerHTML = `<div class="grid g3">
    <div class="panel span2"><div class="row between"><h2>Spend forecast — next month</h2><span class="tag blue">Holt exponential smoothing</span></div>
      ${fc.months.length >= 2 ? forecastChart(fc.months, fc.months.map((_, i) => Object.values(fc.categories).reduce((a, c) => a + (c.history[i] || 0), 0)), fc.total) : '<div class="empty small">Need ≥2 months of history.</div>'}
      <div class="small muted">Shaded wedge = 80% prediction interval. Total: <b>${inr(fc.total.point)}</b> (${inr(fc.total.lower)}–${inr(fc.total.upper)})</div></div>
    <div class="panel"><h2>💡 Smart tips</h2><div class="stack">${ins.tips.map((t) => `<div class="small">${esc(t.text)}</div>`).join("") || '<div class="muted">Add more transactions for tips.</div>'}</div></div></div>
  <div class="grid g2" style="margin-top:16px">
    <div class="panel"><h2>Category forecasts</h2><table><tr><th>Category</th><th class="num">Next month</th><th class="num">Range</th><th class="num">Trend/mo</th></tr>
      ${cats.slice(0, 10).map(([c, f]) => `<tr><td>${esc(catName(c))}</td><td class="num"><b>${inr(f.point)}</b></td><td class="num small muted">${inr(f.lower)}–${inr(f.upper)}</td><td class="num ${f.trend > 0 ? "warn" : "good"}">${f.trend > 0 ? "↑" : f.trend < 0 ? "↓" : ""} ${inr(Math.abs(f.trend))}</td></tr>`).join("")}</table></div>
    <div class="panel"><h2>🚨 Unusual transactions</h2>${ins.anomalies.length ? `<table>${ins.anomalies.map((t) => `<tr><td>${esc(t.txn_date)}</td><td>${esc(t.description)}<div class="small muted">${esc(t.reason || "Unusual pattern (Isolation Forest)")}</div></td><td class="num bad">${inr(t.amount)}</td></tr>`).join("")}</table>` : '<div class="muted">Nothing unusual. ✅</div>'}
      <h2 style="margin-top:18px">Top merchants</h2>${hbars(ins.top_merchants.slice(0, 6).map((m) => ({ label: m.merchant, value: m.amount })))}</div></div>
  <div class="panel" style="margin-top:16px"><div class="row between"><h2>🧠 ML engine status</h2><button class="btn ghost sm" id="retrain">Retrain with my corrections</button></div>
    <div class="grid g3">
      <div><h3>Transaction categorizer</h3><dl class="kv"><dt>Model</dt><dd>TF-IDF (char+word) → LogReg</dd><dt>Training set</dt><dd>${num(ml.categorizer.train_size)} (+${ml.categorizer.feedback_examples} yours)</dd><dt>Unseen-merchant acc.</dt><dd><b>${((ml.categorizer.unseen_merchant_accuracy || 0) * 100).toFixed(1)}%</b></dd><dt>Macro F1</dt><dd>${((ml.categorizer.unseen_merchant_macro_f1 || 0) * 100).toFixed(1)}%</dd></dl></div>
      <div><h3>Sage intent classifier</h3><dl class="kv"><dt>Model</dt><dd>TF-IDF → LogReg</dd><dt>Intents</dt><dd>${ml.intent_classifier.intents}</dd><dt>Examples</dt><dd>${ml.intent_classifier.examples}</dd><dt>5-fold CV acc.</dt><dd><b>${((ml.intent_classifier.cv_accuracy || 0) * 100).toFixed(1)}%</b></dd></dl></div>
      <div><h3>Other models</h3><dl class="kv"><dt>Anomalies</dt><dd>Isolation Forest + robust z</dd><dt>Forecast</dt><dd>Holt (α,β grid-fit)</dd><dt>Optimizer</dt><dd>Cap-aware greedy</dd><dt>Trained in</dt><dd>${ml.train_seconds ?? "—"}s</dd></dl></div></div></div>`;
  $("#retrain").onclick = async () => { toast("Retraining…"); await api("/ml/retrain", { method: "POST" }); toast("Models retrained"); render(); };
};

VIEWS.sage = async (v) => {
  const hist = await api("/assistant/history");
  v.innerHTML = `<div class="panel chat"><div class="msgs" id="msgs"></div>
    <div class="chips" id="sugg" style="margin:8px 0"></div>
    <div class="composer"><input id="chatIn" placeholder="Ask anything — “which card for Swiggy ₹800?”, “Atlas vs Infinia”, “I need 60k KrisFlyer miles”" autocomplete="off"><button class="btn" id="chatSend">Send</button><button class="btn ghost" id="chatClear" title="Clear chat">⟲</button></div></div>`;
  const box = $("#msgs");
  const add = (role, text, metaTxt) => {
    const d = document.createElement("div");
    d.className = "msg " + role;
    d.innerHTML = md(text) + (metaTxt ? `<div class="meta">${esc(metaTxt)}</div>` : "");
    box.appendChild(d);
    box.scrollTop = box.scrollHeight;
  };
  const setSugg = (s) => {
    $("#sugg").innerHTML = (s || []).map((x) => `<button class="chip">${esc(x)}</button>`).join("");
    $$("#sugg .chip").forEach((c) => (c.onclick = () => send(c.textContent)));
  };
  if (!hist.length) {
    add("assistant", "Hi! I'm **Sage** 🦉. I know your cards, caps, points and spending. Ask me which card to use, what your points are worth, or which card to get next.");
    setSugg(["Which card for Swiggy ₹800?", "How much are my points worth?", "Suggest a new card", "Atlas vs Infinia", "Missed savings", "Any unusual transactions?"]);
  } else {
    hist.forEach((h) => add(h.role, h.content, h.payload ? `intent: ${h.payload.intent} · ${Math.round(h.payload.confidence * 100)}%` : ""));
    setSugg(hist[hist.length - 1]?.payload?.suggestions);
  }
  async function send(text) {
    text = (text || $("#chatIn").value).trim();
    if (!text) return;
    $("#chatIn").value = "";
    add("user", text);
    const typing = document.createElement("div");
    typing.className = "msg assistant muted"; typing.textContent = "Sage is thinking…";
    box.appendChild(typing);
    try {
      const r = await api("/assistant/chat", { body: { message: text } });
      typing.remove();
      add("assistant", r.text, `intent: ${r.intent} · ${Math.round(r.confidence * 100)}%`);
      setSugg(r.suggestions);
    } catch (e) { typing.remove(); add("assistant", "Error: " + e.message); }
  }
  $("#chatSend").onclick = () => send();
  $("#chatIn").addEventListener("keydown", (e) => e.key === "Enter" && send());
  $("#chatClear").onclick = async () => { await api("/assistant/history", { method: "DELETE" }); render(); };
  $("#chatIn").focus();
  if (window._pendingAsk) { const q = window._pendingAsk; window._pendingAsk = null; send(q); }
};

// ------------------------------------------------------------------ router & chrome
const TITLES = { dashboard: "Dashboard", "which-card": "Which card should I use?", sage: "Ask Sage", wallet: "My Cards", transactions: "Transactions", rewards: "Rewards & Redeem", discover: "Discover Cards", compare: "Compare Cards", offers: "Offers", insights: "Insights & ML" };

async function render() {
  const route = (location.hash.replace(/^#\//, "") || "dashboard").split("?")[0];
  const view = VIEWS[route] ? route : "dashboard";
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === view));
  $("#title").textContent = TITLES[view];
  $("#sidebar").classList.remove("open");
  const v = $("#view");
  try { await meta(); await VIEWS[view](v); }
  catch (e) { v.innerHTML = `<div class="panel bad">Something went wrong: ${esc(e.message)}</div>`; console.error(e); }
}

async function seed() {
  toast("Loading demo data…");
  const r = await api("/demo/seed", { method: "POST" });
  toast(`Demo loaded: ${r.cards} cards, ${r.transactions} transactions`);
  render();
}
window.seed = seed; window.closeModal = closeModal;

$("#seedBtn").onclick = seed;
$("#resetBtn").onclick = async () => { if (confirm("Delete all your data?")) { await api("/demo/reset", { method: "POST" }); toast("All data cleared"); render(); } };
$("#menuBtn").onclick = () => $("#sidebar").classList.toggle("open");
$("#valueMode").onchange = async (e) => { await api("/settings", { method: "PUT", body: { value_mode: e.target.value } }); CATALOG = null; toast("Valuation: " + e.target.selectedOptions[0].text); render(); };
$("#quickAsk").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.value.trim()) return;
  window._pendingAsk = e.target.value.trim(); e.target.value = "";
  if (location.hash === "#/sage") render(); else location.hash = "#/sage";
});
window.addEventListener("hashchange", render);

(async function boot() {
  const s = await api("/settings");
  $("#valueMode").value = s.value_mode;
  const poll = async () => {
    const h = await api("/health");
    const b = $("#mlBadge");
    if (h.ml_ready) { b.textContent = "● ML engine ready"; b.classList.add("ok"); } else { b.textContent = "◌ ML engine training…"; setTimeout(poll, 1500); }
  };
  poll();
  render();
})();
