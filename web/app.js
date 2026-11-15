/* Flame in Freefall — HTML frontend. Plain JS, no build step.
   All numbers come from the Python engine through /api/*; the Gemini key never reaches this page. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const S = { meta: null, lang: "es", tab: "assistant", stage: "ask", last: null, ai: null, aiPending: false,
              explorer: null, expLimit: 300, charts: {}, seq: 0, advanceTimer: null };

  // ---------- helpers ----------
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  function t(key, params, lang) {
    const L = lang || S.lang;
    const table = (S.meta && S.meta.strings[L]) || {};
    let s = table[key] ?? (S.meta && S.meta.strings.en[key]) ?? key;
    if (params) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m));
    return s;
  }
  const phaseName = (p, L) => t("phase." + p, null, L);
  async function api(path, body) {
    const opt = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
    const r = await fetch(path, opt);
    let data = null;
    try { data = await r.json(); } catch (e) { /* ignore */ }
    if (!r.ok) throw new Error((data && (data.error || JSON.stringify(data.detail))) || ("HTTP " + r.status));
    return data;
  }
  const fmt = (v) => (v === null || v === undefined || v === "" || (typeof v === "number" && !isFinite(v))) ? "" :
    (typeof v === "number" ? (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)) : String(v));
  function embed(el, spec) {
    el.innerHTML = "";
    if (!spec) return;
    if (!window.vegaEmbed) { el.textContent = "(chart library missing)"; return; }
    vegaEmbed(el, spec, {
      actions: false, renderer: "svg", tooltip: { theme: "dark" },
      config: {
        background: "transparent",
        view: { stroke: "transparent" },
        axis: { labelColor: "#9db6cd", titleColor: "#dcecff", gridColor: "#233b56", domainColor: "#405a73", tickColor: "#405a73", labelFont: "DM Sans", titleFont: "DM Sans" },
        legend: { labelColor: "#bcd0e3", titleColor: "#e6f3ff", labelFont: "DM Sans", titleFont: "DM Sans" },
        title: { color: "#eaf6ff", font: "Space Grotesk" }
      }
    }).catch((e) => { el.textContent = String(e); });
  }

  // Page-only copy (not in the engine's string table). Pillar texts adapted from the alternative page.
  const PAGE = {
    en: { alt: "Alternative view ↗", pillars: {
      prevent: "Find the oxygen, pressure and fuel conditions in which a fire can start and keep burning.",
      detect: "Microgravity flames are round, dim and blue: what the tests recorded about spotting them early.",
      extinguish: "Compare diluents and conditions that actually put flames out in orbit." } },
    es: { alt: "Vista alternativa ↗", pillars: {
      prevent: "Encuentra las condiciones de oxígeno, presión y combustible en las que un fuego puede empezar y seguir ardiendo.",
      detect: "Las llamas en microgravedad son redondas, tenues y azules: lo que registraron los ensayos para verlas a tiempo.",
      extinguish: "Compara diluyentes y condiciones que de verdad apagaron llamas en órbita." } },
  };

  // ---------- chrome ----------
  function setLang(L, keepTab) {
    S.lang = L === "en" ? "en" : "es";
    document.documentElement.lang = S.lang;
    try { localStorage.setItem("ff-lang", S.lang); } catch (e) { /* ignore */ }
    renderChrome();
    if (S.stage === "results" && S.last) renderResults();
    if (S.tab === "explorer" && S.explorer) renderExplorer();
    if (S.tab === "charts") loadCharts();
  }
  function renderChrome() {
    const m = S.meta, L = S.lang;
    $("brand").innerHTML = m.html.brand[L];
    $("hero").innerHTML = m.html.hero[L];
    $("footer").innerHTML = m.html.footer[L] + `<div class="ff-footer ff-ai-footer">${esc(t("ai.footer"))}</div>`;
    document.querySelectorAll(".ff-tab").forEach((b) => { b.textContent = t("tab." + b.dataset.tab); });
    document.querySelectorAll(".ff-lang").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.lang === L)));
    $("lang-note").textContent = t("lang.note");
    $("ask-label").textContent = t("ask.label");
    $("question").placeholder = t("ask.placeholder");
    $("ask-button").textContent = t("ask.button");
    $("ask-hint").textContent = "";  // no AI chain / key hints on the page
    $("ask-hint").hidden = true;
    const colors = m.phase_colors || {};
    document.querySelectorAll(".ff-chip").forEach((b) => { b.textContent = t("chip." + b.dataset.kind); b.style.setProperty("--chip", colors[b.dataset.kind] || "#4fd1e8"); });
    $("alt-link").textContent = PAGE[L].alt;
    $("pillars").innerHTML = ["prevent", "detect", "extinguish"].map((p) =>
      `<div class="ff-pillar" style="--k:${colors[p] || "#4fd1e8"}"><b>${esc(phaseName(p))}</b><p>${esc(PAGE[L].pillars[p])}</p></div>`).join("");
    $("see-results").textContent = t("btn.see_results");
    $("new-question").textContent = t("btn.new_question");
    $("loader-text").textContent = t("spinner.searching");
    $("exp-calc").textContent = t("res.calculations");
    $("exp-written").textContent = t("dash.full_answer");
    $("exp-ranked").textContent = t("res.ranked_expander");
    $("evidence-l").textContent = t("res.evidence_fold");
    $("f-measure-l").textContent = t("col.measure");
    fillMeasures();
    const sim = m.simulated_warning && m.simulated_rows;
    $("simwarn").hidden = !sim;
    if (sim) $("simwarn").textContent = t("simulated_warning", { n_sim: m.simulated_rows, n_rows: m.rows });
    // explorer labels
    $("f-search-l").textContent = t("exp.search");
    $("f-phase-l").textContent = t("col.phase");
    $("f-fuel-l").textContent = t("col.fuel");
    $("f-o2-l").textContent = t("col.oxygen");
    $("f-p-l").textContent = t("col.pressure");
    $("exp-download").textContent = t("exp.download");
  }
  function setTab(tab) {
    S.tab = tab;
    document.querySelectorAll(".ff-tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === tab)));
    ["assistant", "explorer", "charts"].forEach((k) => { $("tab-" + k).hidden = k !== tab; });
    if (tab === "explorer") loadExplorer();
    if (tab === "charts") loadCharts();
  }
  function setStage(stage) {
    S.stage = stage;
    $("stage-ask").hidden = stage !== "ask";
    $("stage-anim").hidden = stage !== "anim";
    $("stage-results").hidden = stage !== "results";
    $("stage-error").hidden = true;
    window.scrollTo({ top: 0 });
  }

  // ---------- ask flow ----------
  async function ask(question, opts = {}) {
    question = (question || "").trim();
    if (!question) { showError(t("ask.empty")); return; }
    const seq = ++S.seq;
    S.last = null; S.ai = null; S.aiPending = false;
    clearTimeout(S.advanceTimer);
    setStage("anim");
    $("anim-loader").hidden = false; $("anim-frame").hidden = true; $("see-results").hidden = false; $("see-results").disabled = true;
    let data;
    try {
      data = await api("/api/ask", { question, lang: S.lang, ai: false });
    } catch (e) {
      if (seq !== S.seq) return;
      setStage("ask"); showError(t("err.pipeline_user")); return;
    }
    if (seq !== S.seq) return;
    S.last = data;
    if (data.lang && data.lang !== S.lang) setLang(data.lang);
    // The AI interpretation runs while the animation plays.
    if (!data.out_of_scope) {
      S.aiPending = true;
      api("/api/interpret", { question, lang: data.lang }).then((r) => r.ai).catch((e) => ({
        ok: false, badge: t("ai.badge_engine"), user_note: t("ai.engine_user_note"), title: t("ai.title_engine")
      })).then((ai) => {
        if (seq !== S.seq) return;
        S.ai = ai; S.aiPending = false;
        if (S.stage === "results") renderAI();
      });
    }
    if (opts.skipAnimation || !data.animation) { showResults(); return; }
    $("see-results").disabled = false;
    const frame = $("anim-frame");
    frame.style.height = (data.animation.height || S.meta.mission_height || 660) + "px";
    frame.srcdoc = data.animation.html;
    frame.hidden = false; $("anim-loader").hidden = true;
    const secs = Math.max(Number(data.animation.auto_seconds) || 0, Number(S.meta.animation_seconds) || 0);
    if (secs > 0) S.advanceTimer = setTimeout(() => { if (seq === S.seq && S.stage === "anim") showResults(); }, (secs + 4) * 1000);
  }
  function showResults() {
    clearTimeout(S.advanceTimer);
    if (!S.last) return;
    $("anim-frame").srcdoc = "";
    setStage("results");
    renderResults();
  }
  function showError(msg) {
    const el = $("stage-error"); el.textContent = msg; el.hidden = false;
  }
  function resetFlow() {
    S.seq++; clearTimeout(S.advanceTimer); S.last = null; S.ai = null;
    $("anim-frame").srcdoc = "";
    setStage("ask");
    $("question").value = ""; $("question").focus();
  }

  // ---------- results ----------
  function renderResults() {
    const d = S.last;
    if (!d) return;
    // Only the question, in full (the phase / confidence / source badges are no longer shown here).
    $("strip").innerHTML = d.question ? `<p class="ff-res-q"><span>${esc(t("results.your_question"))}</span>${esc(d.question)}</p>` : "";
    $("lead").innerHTML = d.lead_html || "";
    $("res-warnings").innerHTML = (d.warnings || []).map((w) => `<div class="ff-banner ff-banner-warn">${esc(w)}</div>`).join("");
    $("board").innerHTML = (d.html && d.html.board) || "";
    const oos = !!d.out_of_scope;
    $("evidence").open = !d.lead_html;  // answer first; the evidence stays folded unless there is no answer card
    $("ai-panel").hidden = oos; $("metric-chart").hidden = oos;
    document.querySelector(".ff-expanders").hidden = oos;
    if (oos) return;
    renderAI();
    renderMetric(d.metric_chart);
    renderCalc(d.calculations);
    $("written").innerHTML = d.written_html || "";
    renderRanked(d.ranked);
  }
  function renderMetric(mc) {
    const el = $("metric-chart");
    if (!mc) { el.innerHTML = ""; return; }
    el.innerHTML = `<h3 class="ff-h3">${esc(mc.title)}</h3>` + (mc.warning ? `<div class="ff-banner ff-banner-warn">${esc(mc.warning)}</div>` : "") +
      (mc.spec ? `<div class="ff-chart" id="metric-spec"></div>` : `<div class="ff-banner ff-banner-info">${esc(mc.empty)}</div>`) +
      (mc.caption ? `<p class="ff-sub">${esc(mc.caption)}</p>` : "");
    if (mc.spec) embed($("metric-spec"), mc.spec);
  }
  function renderCalc(c) {
    if (!c) { $("calc").innerHTML = ""; return; }
    $("calc").innerHTML = (c.lines.length ? `<ul>${c.lines.map((l) => `<li>${l}</li>`).join("")}</ul>` : "") + `<p class="ff-sub">${esc(c.caption)}</p>`;
  }
  function cell(col, v, row) {
    if (col === "row_id" && row._url) return `<a class="ff-cite" href="${esc(row._url)}" target="_blank" rel="noopener">${esc(v)}</a>`;
    return esc(fmt(v));
  }
  function renderRanked(r) {
    if (!r) { $("ranked").innerHTML = ""; return; }
    const head = r.columns.map((c) => `<th>${esc(c.label)}</th>`).join("");
    const body = r.rows.map((row) => `<tr>${r.columns.map((c) => `<td${typeof row[c.key] === "number" ? ' class="num"' : ""}>${cell(c.key, row[c.key], row)}</td>`).join("")}</tr>`).join("");
    $("ranked").innerHTML = `<p class="ff-sub">${esc(r.help)}</p><div class="ff-table-wrap"><table class="ff-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div><p class="ff-sub">${esc(r.caption)}</p>`;
  }

  // ---------- AI panel ----------
  function renderAI() {
    const el = $("ai-panel");
    const ai = S.ai;
    if (!ai) {
      el.innerHTML = `<h3>${esc(t("ai.title"))}</h3><div class="ff-working"><i></i><i></i><i></i><span>${esc(t("ai.working"))}</span></div>`;
      return;
    }
    let h = `<h3>${esc(ai.title)}</h3>`;
    const badge = ai.badge;
    if (!ai.ok) {
      h += `<span class="ff-ai-badge ff-ai-engine">${esc(badge)}</span>`;
      if (ai.user_note) h += `<p class="ff-sub">${esc(ai.user_note)}</p>`;
    } else {
      h += `<span class="ff-ai-badge">${esc(badge)}</span>`;
      h += `<div class="ff-ai-body">`;
      if (!ai.enough_evidence && ai.insufficient_note) h += `<div class="ff-banner ff-banner-warn">${esc(ai.insufficient_note)}</div>`;
      if (ai.conclusion_html) h += `<div class="ff-verdict"><span class="ff-tag">${esc(ai.conclusion_label)}</span><p>${ai.conclusion_html}</p></div>`;
      if (ai.recommendation_html) h += `<div class="ff-verdict ff-verdict-rec"><span class="ff-tag">${esc(ai.recommendation_label)}</span><p>${ai.recommendation_html}</p></div>`;
      h += `<p>${ai.summary_html}</p>`;
      if (ai.claims && ai.claims.length) {
        const colors = S.meta.phase_colors || {};
        h += `<h4 class="ff-mono">${esc(ai.claims_title)}</h4><ul class="ff-claims">` + ai.claims.map((c) =>
          `<li style="--k:${colors[c.phase] || "#4fd1e8"}"><span class="ff-tag">${esc(c.phase_label)}</span><span class="ff-kind">${esc(c.kind_label)}</span>${c.html}</li>`).join("") + `</ul>`;
      }
      if (ai.chart && ai.chart.spec) h += `<div class="ff-chart" id="ai-chart"></div><p class="ff-sub">${esc(ai.chart.caption)}</p>`;
      if (ai.limitations_html) h += `<p><b>${esc(ai.limitations_label)}</b> ${ai.limitations_html}</p>`;
      h += `<p class="ff-sub ff-legend">${esc(t("ai.legend"))}</p>`;
      if (ai.missing_html) h += `<p><b>${esc(ai.missing_label)}</b> ${ai.missing_html}</p>`;
      h += `</div>`;
      if (ai.cited_rows && ai.cited_rows.length) {
        const urls = ai.row_urls || {};
        const keys = ["row_id", "experimento", "combustible", "oxigeno_num", "presion_num", "resultado", "fuente"].filter((k) => k in ai.cited_rows[0]);
        const labels = { row_id: t("col.row"), experimento: t("col.experiment"), combustible: t("col.fuel"), oxigeno_num: t("col.oxygen"), presion_num: t("col.pressure"), resultado: t("col.result"), fuente: t("col.source") };
        h += `<details class="ff-exp"><summary>${esc(t("ai.cited_rows"))} · ${ai.cited_rows.length}</summary><div class="ff-exp-body"><div class="ff-table-wrap"><table class="ff-table"><thead><tr>${keys.map((k) => `<th>${esc(labels[k] || k)}</th>`).join("")}</tr></thead><tbody>` +
          ai.cited_rows.map((r) => `<tr>${keys.map((k) => `<td>${k === "row_id" && urls[r.row_id] ? `<a class="ff-cite" href="${esc(urls[r.row_id])}" target="_blank" rel="noopener">${esc(r.row_id)}</a>` : esc(fmt(r[k]))}</td>`).join("")}</tr>`).join("") +
          `</tbody></table></div></div></details>`;
      }
    }
    el.innerHTML = h;
    if (ai.ok && ai.chart && ai.chart.spec) embed($("ai-chart"), ai.chart.spec);
  }

  // ---------- explorer ----------
  const EXP_LABEL = { row_id: "col.row", experimento: "col.experiment", combustible: "col.fuel", oxigeno_num: "col.oxygen", presion_num: "col.pressure",
    o2_start_pct: "col.o2_start_pct", o2_end_pct: "col.o2_end_pct", co2_start_ppm: "col.co2_start_ppm", co2_end_ppm: "col.co2_end_ppm",
    co_start_ppm: "col.co_start_ppm", co_end_ppm: "col.co_end_ppm", diluent: "col.diluent", outcome_not_listed: "col.outcome_not_listed",
    resultado: "col.result", medicion: "col.measure", fase: "col.phase", fuente: "col.source", link: "col.link" };
  const EXP_SHOW = ["row_id", "experimento", "medicion", "combustible", "oxigeno_num", "presion_num", "o2_start_pct", "o2_end_pct", "co2_start_ppm", "co2_end_ppm",
    "co_start_ppm", "co_end_ppm", "diluent", "outcome_not_listed", "resultado", "fase", "fuente", "link"];
  function fillMeasures() {
    const sel = $("f-measure"), X = S.explorer;
    if (!sel || !X || !X.measure_labels) return;
    const keep = sel.value;
    sel.innerHTML = `<option value="">—</option>` + Object.entries(X.measure_labels).map(([k, v]) => `<option value="${esc(k)}">${esc(v[S.lang] || v.en)}</option>`).join("");
    sel.value = keep;
  }
  async function loadExplorer() {
    if (S.explorer) { renderExplorer(); return; }
    $("exp-table").innerHTML = `<div class="ff-working"><i></i><i></i><i></i></div>`;
    try { S.explorer = await api("/api/explorer"); } catch (e) { $("exp-table").textContent = e.message; return; }
    const sel = $("f-fuel");
    sel.innerHTML = `<option value="">—</option>` + S.explorer.fuels.map((f) => `<option>${esc(f)}</option>`).join("");
    const nums = (k) => S.explorer.rows.map((r) => r[k]).filter((v) => typeof v === "number");
    const o2 = nums("oxigeno_num"), p = nums("presion_num");
    $("f-o2-min").placeholder = Math.min(...o2); $("f-o2-max").placeholder = Math.max(...o2);
    $("f-p-min").placeholder = Math.min(...p); $("f-p-max").placeholder = Math.max(...p);
    fillMeasures();
    renderExplorer();
  }
  function explorerView() {
    const X = S.explorer;
    const q = $("f-search").value.trim().toLowerCase();
    const phases = [...document.querySelectorAll("#f-phases input:checked")].map((i) => i.value);
    const fuel = $("f-fuel").value, measure = $("f-measure").value;
    const rng = (a, b) => [parseFloat($(a).value), parseFloat($(b).value)];
    const [o2a, o2b] = rng("f-o2-min", "f-o2-max"), [pa, pb] = rng("f-p-min", "f-p-max");
    const inR = (v, a, b) => (isNaN(a) && isNaN(b)) || (typeof v === "number" && (isNaN(a) || v >= a) && (isNaN(b) || v <= b));
    return X.rows.filter((r) =>
      (!q || `${r.experimento} ${r.combustible} ${r.resultado}`.toLowerCase().includes(q)) &&
      (!phases.length || phases.includes(r.fase)) && (!fuel || r.combustible === fuel) && (!measure || r.medicion === measure) &&
      inR(r.oxigeno_num, o2a, o2b) && inR(r.presion_num, pa, pb));
  }
  function renderExplorer() {
    const X = S.explorer;
    if (!X) return;
    const box = $("f-phases"), checked = new Set([...box.querySelectorAll("input:checked")].map((i) => i.value));
    box.innerHTML = X.phases.map((p) => `<label><input type="checkbox" value="${esc(p)}"${checked.has(p) ? " checked" : ""}><span>${esc(phaseName(p))}</span></label>`).join("");
    const view = explorerView();
    $("exp-caption").textContent = t("exp.rows_caption", { n: view.length, total: X.rows.length });
    const cols = EXP_SHOW.filter((c) => c === "link" || X.columns.includes(c));
    const shown = view.slice(0, S.expLimit);
    const head = cols.map((c) => `<th>${esc(t(EXP_LABEL[c] || c))}</th>`).join("");
    const body = shown.map((r) => `<tr>${cols.map((c) => {
      if (c === "link") return `<td>${r.link ? `<a href="${esc(r.link)}" target="_blank" rel="noopener">↗</a>` : ""}</td>`;
      if (c === "fase") return `<td>${esc(r.fase ? phaseName(r.fase) : "")}</td>`;
      if (c === "medicion") { const m = (X.measure_labels || {})[r.medicion]; return `<td>${esc(m ? (m[S.lang] || m.en) : "")}</td>`; }
      return `<td${typeof r[c] === "number" ? ' class="num"' : ""}>${esc(fmt(r[c]))}</td>`;
    }).join("")}</tr>`).join("");
    $("exp-table").innerHTML = `<table class="ff-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    const more = $("exp-more");
    more.hidden = view.length <= S.expLimit;
    more.textContent = `+ ${Math.min(300, view.length - S.expLimit)} · ${shown.length} / ${view.length}`;
  }
  function downloadCSV() {
    const X = S.explorer; if (!X) return;
    const cols = X.required;
    const q = (v) => { const s = fmt(v); return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    const csv = [cols.join(",")].concat(explorerView().map((r) => cols.map((c) => q(r[c])).join(","))).join("\n") + "\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = "flame_experiments_filtered.csv";
    document.body.appendChild(a); a.click(); a.remove();
  }

  // ---------- charts tab ----------
  async function loadCharts() {
    const L = S.lang;
    if (!S.charts[L]) {
      $("ch-oxy").innerHTML = `<div class="ff-working"><i></i><i></i><i></i></div>`;
      try { S.charts[L] = await api("/api/charts?lang=" + L); } catch (e) { $("ch-oxy").textContent = e.message; return; }
    }
    if (L !== S.lang || S.tab !== "charts") return;
    const c = S.charts[L];
    const put = (key, title, box, cap) => {
      $(title).textContent = c[key + "_title"] || "";
      const part = c[key === "oxygen" ? "oxygen" : "conditions"] || {};
      if (part.spec) { embed($(box), part.spec); $(cap).textContent = part.caption || ""; }
      else { $(box).innerHTML = `<div class="ff-banner ff-banner-info">${esc(part.empty || "")}</div>`; $(cap).textContent = ""; }
    };
    put("oxygen", "ch-oxy-title", "ch-oxy", "ch-oxy-cap");
    put("conditions", "ch-cond-title", "ch-cond", "ch-cond-cap");
  }

  // ---------- boot ----------
  async function boot() {
    let saved = null;
    try { saved = localStorage.getItem("ff-lang"); } catch (e) { /* ignore */ }
    const params = new URLSearchParams(location.search);
    S.lang = params.get("lang") || saved || ((navigator.language || "es").toLowerCase().startsWith("en") ? "en" : "es");
    try { S.meta = await api("/api/meta?lang=" + S.lang); }
    catch (e) { document.body.innerHTML = `<div class="ff-page"><div class="ff-banner ff-banner-err">${esc(e.message)}</div></div>`; return; }
    setLang(S.lang);
    document.querySelectorAll(".ff-tab").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
    document.querySelectorAll(".ff-lang").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));
    document.querySelectorAll(".ff-chip").forEach((b) => b.addEventListener("click", () => { $("question").value = t("example." + b.dataset.kind); $("question").focus(); }));
    $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("question").value); });
    $("question").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey || !e.shiftKey)) { e.preventDefault(); ask($("question").value); } });
    $("see-results").addEventListener("click", showResults);
    // Vega charts measure their container: draw the metric chart when the evidence is opened, not while it is folded.
    $("evidence").addEventListener("toggle", () => { if ($("evidence").open && S.last && !S.last.out_of_scope) renderMetric(S.last.metric_chart); });
    $("new-question").addEventListener("click", resetFlow);
    ["f-search", "f-fuel", "f-measure", "f-o2-min", "f-o2-max", "f-p-min", "f-p-max"].forEach((id) => $(id).addEventListener("input", () => { S.expLimit = 300; renderExplorer(); }));
    $("f-phases").addEventListener("change", () => { S.expLimit = 300; renderExplorer(); });
    $("exp-more").addEventListener("click", () => { S.expLimit += 300; renderExplorer(); });
    $("exp-download").addEventListener("click", downloadCSV);
    const tab = params.get("tab");
    if (tab) setTab(tab);
    const q = params.get("q");
    if (q) { $("question").value = q; ask(q, { skipAnimation: params.get("skip") === "1" }); }
  }
  window.FF = { state: S, ask, showResults, setTab, setLang };
  boot();
})();
