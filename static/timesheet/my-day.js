// static/timesheet/my-day.js - the day-by-day timesheet ("My day").
// Talks to /timesheet/v2/*. Everything coming from the server is inserted with textContent (never innerHTML).
(function () {
  "use strict";

  const LOCS = [["Office", "Office"], ["Client Site", "Client site"], ["Work From Home", "WFH"],
                ["Leave", "Leave"], ["Week Off", "Week off"], ["PHY", "PHY"]];
  const DAY_OFF = ["Leave", "Week Off", "PHY"];
  const STATUS = [["done", "Done"], ["in_progress", "In progress"], ["blocked", "Blocked"]];
  const MAX_HOURS = 24;

  const emp = (localStorage.getItem("loggedInEmployeeId") || "").trim().toUpperCase();
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
  if (!token || !emp) { window.location.href = "/static/login.html"; return; }

  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  // ── tiny DOM helper ───────────────────────────────────────────────────────────────
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === false || v == null) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, v);
    }
    kids.flat().forEach((c) => { if (c == null || c === false) return; el.append(c.nodeType ? c : document.createTextNode(String(c))); });
    return el;
  }

  async function api(method, url, body) {
    const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("Please log in again"); }
    if (!res.ok) {
      let msg = (data && data.detail) || `Request failed (${res.status})`;
      if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join("; ");
      const err = new Error(msg); err.status = res.status; throw err;
    }
    return data;
  }

  // ── state ─────────────────────────────────────────────────────────────────────────
  const S = {
    date: null, day: null, strip: null, rows: [], location: "Office", readOnly: false,
    timer: null, chain: Promise.resolve(), dirty: false, hintsOn: false,
    taskQuery: "", taskOpen: new Set(),         // search text and which task groups the person opened
  };
  let seq = 0;
  const newRow = (init) => Object.assign({ key: ++seq, task_id: null, unplanned: false, hours: "", status: "in_progress", remarks: "", extra: "", info: null }, init || {});
  const locKey = `myday_location_${emp}`;
  const remembered = () => { try { const v = localStorage.getItem(locKey) || ""; return DAY_OFF.includes(v) ? "" : v; } catch (_) { return ""; } };
  const remember = (v) => { if (DAY_OFF.includes(v)) return; try { localStorage.setItem(locKey, v); } catch (_) { /* ignore */ } };

  const fmtDate = (iso, opts) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", opts);
  const shortDate = (iso) => (iso ? fmtDate(iso, { day: "numeric", month: "short" }) : "");
  function addDays(iso, n) {                        // local-date arithmetic (toISOString would shift by the UTC offset)
    const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + n);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  const num = (v) => { const t = String(v == null ? "" : v).trim(); return t === "" ? null : Number(t); };
  const fmt = (v) => (v == null ? "—" : String(Math.round(v * 100) / 100));
  const isDayOff = () => DAY_OFF.includes(S.location);

  // ── status line + banners + toast ─────────────────────────────────────────────────
  function setSaveState(kind, text) {
    const el = $("saveState");
    el.textContent = text; el.className = "save-state" + (kind ? " " + kind : "");
  }
  function banner(kind, text, dismissible) {
    const b = h("div", { class: "banner " + kind }, h("span", { text }));
    if (dismissible) b.append(h("button", { type: "button", "aria-label": "Dismiss", onclick: () => b.remove(), text: "×" }));
    $("banners").append(b);
    return b;
  }
  function clearBanners(kind) {
    $("banners").querySelectorAll(kind ? ".banner." + kind : ".banner").forEach((b) => b.remove());
  }
  function toast(text) {
    const t = h("div", { class: "toast", role: "status", text });
    document.body.append(t);
    setTimeout(() => t.remove(), 2200);
  }

  // ── loading ───────────────────────────────────────────────────────────────────────
  async function loadDay(date) {
    setSaveState("", "Loading…");
    const page = await api("GET", `/timesheet/v2/page/${emp}${date ? "?date=" + date : ""}`);
    if (!page.enabled) { window.location.replace("/static/timesheet/index.html"); return; }
    const day = page.day, strip = page.strip;
    S.date = day.date; S.day = day; S.strip = strip; S.dirty = false;
    S.location = day.location || remembered() || "Office";
    S.readOnly = !!day.read_only;
    S.rows = day.entries.map((e) => newRow({
      task_id: e.task_id, unplanned: !!e.is_unplanned, hours: e.hours == null ? "" : String(e.hours),
      status: e.task_status || "in_progress", remarks: e.remarks || "", extra: e.extra_remarks || "",
      info: { name: e.task_name || (e.is_unplanned ? "Unplanned work" : ""), client: e.client, project: e.project, code: e.project_code },
    }));
    S.hintsOn = false;
    renderAll();
    setSaveState("", day.submitted ? "Submitted" : (S.rows.length ? "Draft" : ""));
  }

  async function refreshStrip() {
    try { S.strip = await api("GET", `/timesheet/v2/cycle-days/${emp}?date=${S.date}`); renderStrip(); } catch (_) { /* keep the old strip */ }
  }

  async function goto(date) {
    await flush();
    try { await loadDay(date); } catch (err) { banner("err", err.message, true); }
  }

  // ── rendering ─────────────────────────────────────────────────────────────────────
  function renderAll() {
    renderBanners(); renderTitle(); renderStrip(); renderLocation(); renderTasks(); renderWork(); renderTotals();
  }

  function renderBanners() {
    clearBanners();
    const d = S.day;
    if (d.nq_unavailable) banner("warn", "Project data from Nexus Quant is unavailable right now, so your tasks cannot be listed. You can still add unplanned work or mark a day off. Please refresh in a few minutes.");
    else if (d.nq_data_may_be_stale) banner("warn", "Project data may be out of date.");
    if (d.cycle.review_status === "sent_back") banner("warn", "Your manager sent this cycle back: " + (d.cycle.review_note || "please check your days") + ". Fix the days, then submit them again.");
    if (d.read_only) banner("info", d.read_only_text || "This day is view only.");
    else if (d.submitted) banner("info", "This day was submitted earlier and has been opened for changes. Fix it, then submit it again.");
  }

  function renderTitle() {
    const d = S.day, c = d.cycle;
    $("cycLabel").textContent = `Cycle ${c.label} · fill by ${shortDate(c.deadline)}${!c.configured ? " (not set up)" : c.deadline_passed && c.review_status !== "sent_back" && c.review_status !== "reopened" ? " (closed)" : ""}`;
    $("dayTitle").textContent = `${d.weekday}, ${shortDate(d.date)}`;
    $("datePick").value = d.date;
    $("datePick").max = S.strip.today;
    $("nextDay").disabled = d.date >= S.strip.today;
    $("nextCycle").disabled = !S.strip.next_date;
  }

  function renderStrip() {
    const box = $("strip"); box.textContent = "";
    S.strip.days.forEach((x) => {
      const label = { submitted: `${x.day} ✓`, missing: `${x.day} missing`, saved: `${x.day} saved`, off: `${x.day} off`,
                      open: `${x.day} today`, future: `${x.day}` }[x.state] || String(x.day);
      const tip = `${x.weekday} ${x.day}${x.location ? " · " + x.location : ""}${x.hours ? " · " + x.hours + " h" : ""}`;
      box.append(h("button", {
        type: "button", class: `pill ${x.state}${x.date === S.date ? " sel" : ""}`, title: tip,
        "aria-label": tip + " - " + x.state, "aria-current": x.date === S.date ? "date" : null,
        onclick: () => goto(x.date),
      }, label));
    });
    const s = S.strip.summary;
    $("stripSum").textContent = `${s.submitted} submitted · ${s.saved} saved · ${s.missing} to do`;
  }

  function renderLocation() {
    const sel = $("loc"); sel.textContent = "";
    LOCS.forEach(([v, l]) => sel.append(h("option", { value: v, text: l })));
    sel.value = S.location;
    sel.disabled = S.readOnly;
  }

  function usedTaskIds() { return new Set(S.rows.filter((r) => r.task_id != null).map((r) => r.task_id)); }

  function taskInfo(t) { return { name: t.task_name, client: t.client_name, project: t.project_name, code: t.project_code, end: t.end_date, overdue: t.is_overdue }; }

  // "My tasks today": searchable, grouped client > project; overdue tasks sit in a collapsed sub-group with a count.
  function taskMatches(t, q) {
    if (!q) return true;
    return [t.task_name, t.client_name, t.project_name, t.project_code].some((v) => String(v || "").toLowerCase().includes(q));
  }

  function taskCard(t, used) {
    const meta = t.is_overdue ? `Overdue · ended ${shortDate(t.end_date)}`
      : `${t.end_date ? "Ends " + shortDate(t.end_date) : "No end date"} · ${fmt(t.hours_used)} of ${fmt(t.budget_hours)} h used`;
    return h("button", { type: "button", class: "tcard" + (t.is_overdue ? " overdue" : "") + (used.has(t.task_id) ? " added" : ""),
      disabled: S.readOnly || isDayOff(), onclick: () => addTask(t) },
      h("div", { class: "t1", text: t.task_name }),
      h("div", { class: "t3", text: used.has(t.task_id) ? "Added to today ✓" : meta }));
  }

  function renderTasks() {
    const box = $("taskCards"); box.textContent = "";
    const sum = $("taskSummary"); sum.textContent = "";
    const all = S.day.tasks, used = usedTaskIds();
    $("taskSearchWrap").hidden = all.length < 6;
    if (!all.length) { box.append(h("div", { class: "empty", text: S.day.nq_unavailable ? "Tasks are unavailable right now." : "No tasks are assigned to you for this date. Use “Unplanned work” if you did something else." })); return; }
    const q = S.taskQuery.trim().toLowerCase();
    const tasks = all.filter((t) => taskMatches(t, q));
    const overdueAll = all.filter((t) => t.is_overdue).length;
    sum.textContent = q ? `${tasks.length} of ${all.length} tasks match` : `${all.length - overdueAll} current · ${overdueAll} overdue`;
    if (!tasks.length) { box.append(h("div", { class: "empty", text: "No task matches your search." })); return; }

    const byClient = new Map();                       // client -> project key -> { name, code, current[], overdue[] }
    tasks.forEach((t) => {
      const c = t.client_name || "No client", pk = t.project_code || t.project_name || "";
      if (!byClient.has(c)) byClient.set(c, new Map());
      const projects = byClient.get(c);
      if (!projects.has(pk)) projects.set(pk, { name: t.project_name || pk, code: t.project_code || "", current: [], overdue: [] });
      projects.get(pk)[t.is_overdue ? "overdue" : "current"].push(t);
    });

    const isOpen = (key, dflt) => { const on = [...S.taskOpen].includes(key + ":1"), off = [...S.taskOpen].includes(key + ":0"); return on ? true : off ? false : dflt; };
    const mk = (key, cls, summary, kids, dflt) => {
      const d = h("details", { class: cls });
      d.open = !!q || isOpen(key, dflt);
      d.append(h("summary", {}, ...summary), ...kids);
      d.addEventListener("toggle", () => {
        if (q) return;
        S.taskOpen.delete(key + ":1"); S.taskOpen.delete(key + ":0"); S.taskOpen.add(key + (d.open ? ":1" : ":0"));
      });
      return d;
    };

    [...byClient.keys()].sort((a, b) => a.localeCompare(b)).forEach((client) => {
      const projects = [...byClient.get(client).values()].sort((a, b) => (b.current.length > 0) - (a.current.length > 0) || a.name.localeCompare(b.name));
      const clientCount = projects.reduce((n, p) => n + p.current.length + p.overdue.length, 0);
      const kids = projects.map((p) => {
        const inner = p.current.map((t) => taskCard(t, used));
        if (p.overdue.length) {
          inner.push(mk(`od:${client}|${p.code}`, "tgroup od", [h("span", { text: `Overdue (${p.overdue.length})` })],
            p.overdue.map((t) => taskCard(t, used)), false));
        }
        return mk(`p:${client}|${p.code}`, "tgroup proj",
          [h("span", { class: "tname", text: p.name }), " ", h("span", { class: "mono tcode", text: p.code }), h("span", { class: "tcount", text: String(p.current.length + p.overdue.length) })],
          inner, p.current.length > 0);
      });
      box.append(mk(`c:${client}`, "tgroup client", [h("span", { class: "tname", text: client }), h("span", { class: "tcount", text: String(clientCount) })], kids, true));
    });
  }

  function rowCaption(r) {
    if (r.unplanned) return h("div", { class: "cap warn", text: "Not in Nexus Quant · your manager reviews it" });
    if (!r.info || !r.task_id && !r.info.name) return h("div", { class: "cap", text: "Client, project and code are filled in when you pick a task" });
    return h("div", { class: "cap" }, `${r.info.client || "—"} › ${r.info.project || ""} · `, h("span", { class: "mono", text: r.info.code || "" }));
  }

  function renderWork() {
    const body = $("workBody"); body.textContent = "";
    if (isDayOff()) {
      body.append(h("div", { class: "dayoff", text: `${LOCS.find((l) => l[0] === S.location)[1]}: no work rows needed. Press “Submit day” to confirm.` }));
      return;
    }
    const ro = S.readOnly;
    body.append(h("div", { class: "whead" }, h("div", { text: "Task" }), h("div", { text: "Hours" }), h("div", { text: "Status" }), h("div")));
    S.rows.forEach((r) => body.append(buildRow(r, ro)));
    if (!S.rows.length) body.append(h("div", { class: "empty", text: "Nothing added yet. Click a task on the left, or press “+ Add task”." }));
    const actions = h("div", { class: "rowactions" });
    if (!ro) {
      actions.append(h("button", { class: "btn small", type: "button", onclick: addEmptyRow }, "+ Add task"));
      actions.append(h("button", { class: "btn small", type: "button", onclick: copyYesterday, title: "Add the tasks you worked on the last day you filled" }, "Copy yesterday's tasks"));
    }
    body.append(actions);
  }

  function buildRow(r, ro) {
    const row = h("div", { class: "wrow" + (r.unplanned ? " unplanned" : ""), "data-key": r.key });

    // task picker
    const pick = h("input", { class: "inp", type: "text", "aria-label": "Task", autocomplete: "off", readonly: ro, placeholder: "Pick a task…",
      value: r.unplanned ? "Unplanned work" : (r.info && r.info.name) || "" });
    pick.addEventListener("focus", () => { if (!ro) openPicker(pick, r); });
    pick.addEventListener("click", () => { if (!ro) openPicker(pick, r); });
    pick.addEventListener("input", () => openPicker(pick, r, pick.value));
    pick.addEventListener("keydown", (e) => pickerKey(e, pick, r));
    row.append(h("div", { class: "picker" }, pick, rowCaption(r)));

    // what I did
    const what = h("input", { class: "inp", type: "text", "aria-label": "What I did", maxlength: "1000", disabled: ro,
      placeholder: r.unplanned ? "What did you do? (required)" : "What I did (optional)", value: r.remarks });
    what.addEventListener("input", () => { r.remarks = what.value; touched(); });
    row.append(h("div", {}, what));

    // hours
    const hrs = h("input", { class: "inp mono", type: "text", inputmode: "decimal", "aria-label": "Hours", disabled: ro, placeholder: "0.0", value: r.hours, "data-hours": r.key });
    hrs.addEventListener("input", () => { r.hours = hrs.value.replace(",", "."); touched(); });
    const chips = ro ? null : h("div", { class: "chips" },
      h("button", { type: "button", class: "chip", onclick: () => bump(r, hrs, 0.5) }, "+0.5"),
      h("button", { type: "button", class: "chip", onclick: () => bump(r, hrs, 1) }, "+1"));
    row.append(h("div", { class: "hoursbox" }, hrs, chips));

    // status
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Status" });
    STATUS.forEach(([v, l]) => seg.append(h("button", { type: "button", "data-s": v, class: r.status === v ? "on" : "", "aria-pressed": r.status === v ? "true" : "false", disabled: ro,
      onclick: () => { r.status = v; seg.querySelectorAll("button").forEach((b, i) => { b.classList.toggle("on", STATUS[i][0] === v); b.setAttribute("aria-pressed", STATUS[i][0] === v ? "true" : "false"); }); touched(); } }, l)));
    row.append(h("div", {}, seg));

    row.append(h("div", {}, ro ? null : h("button", { class: "x", type: "button", "aria-label": "Remove this row", title: "Remove", onclick: () => removeRow(r) }, "×")));

    // optional free-text remarks, after "What I did"
    const extra = h("input", { class: "inp", type: "text", "aria-label": "Remarks (optional)", maxlength: "1000", disabled: ro,
      placeholder: "Remarks (optional)", value: r.extra });
    extra.addEventListener("input", () => { r.extra = extra.value; touched(); });
    row.append(h("div", {}, extra));
    return row;
  }

  function bump(r, input, by) {
    const cur = num(r.hours) || 0;
    const next = Math.min(MAX_HOURS, Math.round((cur + by) * 100) / 100);
    r.hours = String(next); input.value = r.hours; touched();
  }

  // ── hints / totals ────────────────────────────────────────────────────────────────
  function rowsToSave() { return S.rows.filter((r) => r.task_id != null || r.unplanned); }

  function hoursValue(r) {
    const t = String(r.hours || "").trim();
    if (t === "") return null;
    return /^\d{0,2}(\.\d{0,2})?$/.test(t) && !isNaN(Number(t)) ? Number(t) : NaN;
  }

  function problems() {
    const out = [];
    if (isDayOff()) return out;
    const rows = rowsToSave();
    if (!rows.length) { out.push("Add at least one task for the day."); return out; }
    let total = 0;
    rows.forEach((r, i) => {
      const hv = hoursValue(r);
      if (hv === null) out.push(`Row ${i + 1}: add your hours.`);
      else if (Number.isNaN(hv) || hv <= 0 || hv > MAX_HOURS) out.push(`Row ${i + 1}: hours must be more than 0 and at most ${MAX_HOURS}, up to 2 decimals.`);
      else total += hv;
      if (r.unplanned && r.remarks.trim().length < 3) out.push(`Row ${i + 1}: describe the unplanned work.`);
    });
    if (S.rows.some((r) => r.task_id == null && !r.unplanned)) out.push("A row without a task is not saved - pick a task or remove the row.");
    if (total > MAX_HOURS) out.push(`The day's hours add up to ${Math.round(total * 100) / 100} - more than ${MAX_HOURS}.`);
    return out;
  }

  function renderTotals() {
    const off = isDayOff();
    $("totals").hidden = off;
    const rows = rowsToSave();
    const total = rows.reduce((t, r) => { const v = hoursValue(r); return t + (v && !Number.isNaN(v) ? v : 0); }, 0);
    $("tHours").textContent = fmt(total);
    $("tHours").classList.toggle("bad", total > MAX_HOURS);
    $("tRows").textContent = String(rows.length);
    const hints = $("hints"); hints.textContent = "";
    if (S.hintsOn && !S.readOnly) problems().forEach((p) => hints.append(h("li", { text: p })));
    const btn = $("submitBtn");
    btn.hidden = S.readOnly;
    btn.textContent = "Submit day";
    $("submitNote").textContent = S.readOnly ? "" : (S.day.day_reopened
      ? "Your admin has allowed changes to this day. Fix it and submit again; it locks once you submit."
      : "Hours are what you worked. Once you submit, the day is locked and only your admin can allow changes.");
  }

  // ── editing actions ───────────────────────────────────────────────────────────────
  function touched() { S.dirty = true; S.day.submitted = false; renderTotals(); scheduleSave(); }

  function addTask(t) {
    if (S.readOnly || isDayOff()) return;
    const existing = S.rows.find((r) => r.task_id === t.task_id);
    if (existing) { const el = document.querySelector(`[data-hours="${existing.key}"]`); if (el) el.focus(); return; }
    const blank = S.rows.find((r) => r.task_id == null && !r.unplanned && !r.hours && !r.remarks && !r.extra);
    if (blank) { blank.task_id = t.task_id; blank.info = taskInfo(t); } else S.rows.push(newRow({ task_id: t.task_id, info: taskInfo(t) }));
    renderWork(); renderTasks(); touched();
    const last = S.rows.find((r) => r.task_id === t.task_id);
    const el = last && document.querySelector(`[data-hours="${last.key}"]`); if (el) el.focus();
  }

  function addEmptyRow() {
    if (S.readOnly) return;
    S.rows.push(newRow());
    renderWork();
    const rows = document.querySelectorAll(".wrow"); const last = rows[rows.length - 1]; if (last) last.querySelector("input").focus();
  }

  function removeRow(r) {
    S.rows = S.rows.filter((x) => x.key !== r.key);
    renderWork(); renderTasks(); touched();
  }

  async function copyYesterday() {
    if (S.readOnly) return;
    for (let i = 1; i <= 7; i++) {
      const iso = addDays(S.date, -i);
      let day;
      try { day = await api("GET", `/timesheet/v2/day/${emp}?date=${iso}`); } catch (_) { continue; }
      const ids = day.entries.filter((e) => e.task_id != null).map((e) => e.task_id);
      if (!ids.length) continue;
      const today = new Map(S.day.tasks.map((t) => [t.task_id, t]));
      const used = usedTaskIds();
      let added = 0;
      ids.forEach((id) => { const t = today.get(id); if (t && !used.has(id)) { S.rows.push(newRow({ task_id: id, info: taskInfo(t) })); added++; } });
      if (added) { renderWork(); renderTasks(); touched(); toast(`Added ${added} task${added > 1 ? "s" : ""} from ${shortDate(iso)}`); }
      else toast(`Nothing to copy: those tasks are not on today's list`);
      return;
    }
    toast("No earlier day with tasks found in the last week");
  }

  // ── task picker (one shared floating list) ────────────────────────────────────────
  const plist = $("plist");
  let pk = null;                                     // { input, row, items, hl }

  function pickerOptions(query) {
    const q = (query || "").trim().toLowerCase(), used = usedTaskIds();
    const groups = new Map();
    S.day.tasks.forEach((t) => {
      const hay = `${t.task_name} ${t.client_name} ${t.project_name} ${t.project_code}`.toLowerCase();
      if (q && !hay.includes(q)) return;
      const g = `${t.client_name || "—"} › ${t.project_name || ""} · ${t.project_code}`;
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(t);
    });
    return { groups, used };
  }

  function openPicker(input, row, query) {
    if (S.readOnly) return;
    const q = query !== undefined && query !== (row.info && row.info.name) && query !== "Unplanned work" ? query : "";
    const { groups, used } = pickerOptions(q);
    plist.textContent = "";
    const items = [];
    groups.forEach((tasks, g) => {
      plist.append(h("div", { class: "pgroup", text: g }));
      tasks.forEach((t) => {
        const taken = used.has(t.task_id) && row.task_id !== t.task_id;
        const el = h("div", { class: "popt" + (taken ? " used" : ""), role: "option", "aria-disabled": taken ? "true" : "false" },
          h("div", { text: t.task_name }),
          h("div", { class: "m", text: taken ? "Already added today" : (t.is_overdue ? `Overdue · ended ${shortDate(t.end_date)}` : (t.end_date ? `Ends ${shortDate(t.end_date)}` : "")) }));
        const item = { el, task: t, taken };
        el.addEventListener("mousedown", (e) => { e.preventDefault(); if (!taken) choose(item); });
        items.push(item); plist.append(el);
      });
    });
    if (!items.length) plist.append(h("div", { class: "pnone", text: q ? "No task matches. Use “Unplanned work” below." : "No tasks for this date." }));
    const un = h("div", { class: "popt un", role: "option", text: "Unplanned work… (not in Nexus Quant)" });
    const unItem = { el: un, unplanned: true };
    un.addEventListener("mousedown", (e) => { e.preventDefault(); choose(unItem); });
    items.push(unItem); plist.append(un);
    pk = { input, row, items, hl: -1 };
    const r = input.getBoundingClientRect();
    plist.style.left = r.left + "px"; plist.style.top = r.bottom + 2 + "px"; plist.style.width = Math.max(r.width, 320) + "px";
    plist.hidden = false;
  }

  function closePicker() { plist.hidden = true; pk = null; }

  function highlight(i) {
    if (!pk) return;
    pk.items.forEach((it, j) => it.el.classList.toggle("hl", j === i));
    pk.hl = i;
    const el = pk.items[i] && pk.items[i].el; if (el) el.scrollIntoView({ block: "nearest" });
  }

  function pickerKey(e, input, row) {
    if (S.readOnly) return;
    if (e.key === "Escape") { closePicker(); input.blur(); return; }
    if (e.key === "Tab") { closePicker(); return; }
    if (plist.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) { openPicker(input, row); }
    if (!pk) return;
    const sel = pk.items.map((it, i) => (it.taken ? -1 : i)).filter((i) => i >= 0);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const at = sel.indexOf(pk.hl);
      const next = e.key === "ArrowDown" ? sel[Math.min(at + 1, sel.length - 1)] : sel[Math.max(at - 1, 0)];
      highlight(next === undefined ? sel[0] : next);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const it = pk.items[pk.hl >= 0 ? pk.hl : sel[0]];
      if (it && !it.taken) choose(it);
    }
  }

  function choose(item) {
    if (!pk) return;
    const r = pk.row;
    if (item.unplanned) { r.task_id = null; r.unplanned = true; r.info = { name: "Unplanned work" }; }
    else { r.task_id = item.task.task_id; r.unplanned = false; r.info = taskInfo(item.task); }
    closePicker();
    renderWork(); renderTasks(); touched();
    const el = document.querySelector(`[data-hours="${r.key}"]`); if (el) el.focus();
  }

  document.addEventListener("mousedown", (e) => { if (pk && !plist.contains(e.target) && e.target !== pk.input) closePicker(); });
  window.addEventListener("scroll", () => { if (pk) { const r = pk.input.getBoundingClientRect(); plist.style.left = r.left + "px"; plist.style.top = r.bottom + 2 + "px"; } }, true);
  window.addEventListener("resize", closePicker);

  // ── saving (autosave, one save at a time) ─────────────────────────────────────────
  function scheduleSave() {
    if (S.readOnly) return;
    setSaveState("", "Unsaved changes…");
    clearTimeout(S.timer);
    S.timer = setTimeout(() => { S.chain = S.chain.then(doSave); }, 700);
  }

  function flush() {
    if (S.timer) { clearTimeout(S.timer); S.timer = null; S.chain = S.chain.then(doSave); }
    return S.chain;
  }

  async function doSave() {
    S.timer = null;
    if (!S.dirty || S.readOnly) return;
    const entries = [];
    for (const r of rowsToSave()) {
      const hv = hoursValue(r);
      if (Number.isNaN(hv) || (hv !== null && (hv < 0 || hv > MAX_HOURS))) { setSaveState("err", "Fix the hours to save"); return; }
      entries.push({ task_id: r.unplanned ? null : r.task_id, hours: hv, task_status: r.status, remarks: r.remarks, extra_remarks: r.extra, is_unplanned: r.unplanned });
    }
    setSaveState("", "Saving…");
    try {
      S.dirty = false;
      const day = await api("PUT", `/timesheet/v2/day/${emp}/${S.date}`, { location: S.location, entries: isDayOff() ? [] : entries });
      S.day.submitted = day.submitted; S.day.totals = day.totals; S.day.tasks = day.tasks;
      setSaveState("ok", "Saved ✓");
      remember(S.location);
      refreshStrip();
      renderTasks(); renderTotals();
    } catch (err) {
      S.dirty = true;
      if (err.status === 409) { setSaveState("err", "Not saved"); banner("err", err.message, true); try { await loadDay(S.date); } catch (_) { /* leave */ } }
      else { setSaveState("err", "Not saved: " + err.message); }
    }
  }

  async function submitDay() {
    clearBanners("err");
    S.hintsOn = true;
    const local = problems();
    if (local.length) { renderTotals(); banner("err", "Please fix this before submitting: " + local.slice(0, 3).join(" "), true); return; }
    clearTimeout(S.timer);
    S.dirty = true;                                 // always save the latest rows before submitting
    S.chain = S.chain.then(doSave);
    await S.chain;
    if (S.dirty) return;                          // the save failed; its message is showing
    try {
      const day = await api("POST", `/timesheet/v2/day/${emp}/${S.date}/submit`);
      await loadDay(S.date);                          // a submitted day is now locked: show it read-only
      setSaveState("ok", "Submitted ✓");
      toast("Day submitted ✓");
    } catch (err) { banner("err", err.message, true); }
  }

  // ── wiring ────────────────────────────────────────────────────────────────────────
  $("loc").addEventListener("change", () => {
    const next = $("loc").value;
    if (DAY_OFF.includes(next) && rowsToSave().length && !confirm("A day off carries no work rows. Remove today's rows?")) { $("loc").value = S.location; return; }
    S.location = next;
    if (DAY_OFF.includes(next)) S.rows = [];
    renderWork(); renderTasks(); touched();
  });
  $("submitBtn").addEventListener("click", submitDay);
  $("taskSearch").addEventListener("input", () => { S.taskQuery = $("taskSearch").value; renderTasks(); });
  $("prevDay").addEventListener("click", () => goto(addDays(S.date, -1)));
  $("nextDay").addEventListener("click", () => goto(addDays(S.date, 1)));
  $("todayBtn").addEventListener("click", () => goto(S.strip.today));
  $("datePick").addEventListener("change", () => { if ($("datePick").value) goto($("datePick").value); });
  $("prevCycle").addEventListener("click", () => goto(S.strip.prev_date));
  $("nextCycle").addEventListener("click", () => { if (S.strip.next_date) goto(S.strip.next_date); });
  window.addEventListener("beforeunload", (e) => { if (S.dirty && !S.readOnly) { e.preventDefault(); e.returnValue = ""; } });

  // ── start: only pilot employees see this page; everyone else gets the classic timesheet ──
  (async function start() {
    try {
      await loadDay(null);                          // today; sends people who are not on the new timesheet to the classic one
      if (!S.day) return;
      $("boot").hidden = true; $("app").hidden = false;
    } catch (err) {
      $("boot").textContent = "Could not load your timesheet: " + err.message;
    }
  })();
})();
