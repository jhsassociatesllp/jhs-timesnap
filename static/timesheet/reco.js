// static/timesheet/reco.js — manager/admin reconciliation view. Talks to /hrms/reco*.
// All server text goes through textContent.
(function () {
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  const FLAGGED = ["short", "over", "no_punch", "not_filled"];
  const LABEL = { matched: "Matched", short: "Short", over: "Over", no_punch: "No punch", not_filled: "Not filled", leave: "Leave / off" };
  const TAG = { matched: "green", leave: "", short: "red", over: "red", no_punch: "amber", not_filled: "amber" };

  function banner(text, kind) {
    const el = $("msg");
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text; el.className = "dt-banner " + kind; el.style.display = "block";
  }

  async function call(method, url, body) {
    const res = await fetch(url, { method, headers, body: body ? JSON.stringify(body) : undefined });
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (res.status === 401) { window.location.href = "/static/login.html"; throw new Error("auth"); }
    if (!res.ok) {
      let msg = (data && data.detail) || `Request failed (${res.status})`;
      if (Array.isArray(msg)) msg = msg.map((m) => m.msg).join("; ");
      throw new Error(msg);
    }
    return data;
  }

  const fmt = (v) => (v === null || v === undefined ? "—" : String(v));
  function iso(d) { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 10); }

  function tag(text, cls) {
    const s = document.createElement("span"); s.className = "dt-tag " + (cls || ""); s.textContent = text; return s;
  }

  function render(d) {
    const sum = $("summary"); sum.textContent = "";
    Object.keys(LABEL).forEach((k) => {
      const box = document.createElement("div");
      const s = document.createElement("span"); s.textContent = LABEL[k];
      const b = document.createElement("b"); b.textContent = d.summary[k] || 0;
      box.append(s, b); sum.append(box);
    });
    const lu = d.last_upload;
    $("lastUpload").textContent = lu
      ? `Last HRMS upload: ${new Date(lu.uploaded_at).toLocaleString()} (covers ${lu.date_from} to ${lu.date_to})`
      : "No HRMS upload yet.";
    $("awaiting").textContent = d.awaiting_dates.length ? "Still awaiting HRMS: " + d.awaiting_dates.join(", ") : "";

    const body = $("rows"); body.textContent = "";
    if (!d.rows.length) {
      const td = body.insertRow().insertCell(); td.colSpan = 8; td.className = "dt-muted";
      td.textContent = "Nothing to show for this period."; return;
    }
    d.rows.forEach((r) => {
      const tr = body.insertRow();
      tr.insertCell().textContent = r.date;
      tr.insertCell().textContent = `${r.employee_name || ""} (${r.employee_id})`;
      tr.insertCell().textContent = fmt(r.hrms_net);
      tr.insertCell().textContent = fmt(r.timesheet_hours);
      tr.insertCell().textContent = r.diff === null || r.diff === undefined ? "—" : (r.diff > 0 ? "+" : "") + r.diff;
      tr.insertCell().append(tag(LABEL[r.result] || r.result, TAG[r.result]));
      tr.insertCell().textContent = r.reason || "";
      const act = tr.insertCell();
      if (FLAGGED.includes(r.result)) {
        if (r.status !== "open") {
          act.append(tag(r.status === "accepted" ? "Accepted" : "Sent back", r.status === "accepted" ? "green" : "amber"));
          if (r.manager_note) { const n = document.createElement("div"); n.className = "dt-muted"; n.textContent = r.manager_note; act.append(n); }
        } else {
          const a = document.createElement("button"); a.className = "dt-btn go small"; a.type = "button"; a.textContent = "Accept";
          a.onclick = () => review(r, "accept", "");
          const s = document.createElement("button"); s.className = "dt-btn del small"; s.type = "button"; s.textContent = "Send back"; s.style.marginLeft = ".4rem";
          s.onclick = () => {
            const note = window.prompt("What should the employee fix?");
            if (note && note.trim()) review(r, "send-back", note.trim());
          };
          act.append(a, s);
        }
      }
    });
  }

  async function review(r, action, note) {
    banner("");
    try {
      await call("POST", `/hrms/reco/${encodeURIComponent(r.employee_id)}/${r.date}/${action}`, { note });
      await load();
    } catch (err) { banner(err.message, "err"); }
  }

  async function load() {
    banner("");
    let url = `/hrms/reco?from=${$("from").value}&to=${$("to").value}`;
    const team = $("team").value.trim();
    if (team) url += `&manager=${encodeURIComponent(team)}`;
    try { render(await call("GET", url)); } catch (err) { banner(err.message, "err"); }
  }

  const today = new Date();
  $("to").value = iso(today);
  $("from").value = iso(new Date(today.getTime() - 9 * 86400000));
  $("go").onclick = load;
  (async () => {
    try {
      const a = await call("GET", "/hrms/access");
      if (a.is_admin) { $("teamWrap").style.display = "block"; $("uploadLink").style.display = "inline-block"; }
      if (!a.is_admin && !a.is_manager) { banner("Only managers and admins can view reconciliation.", "err"); return; }
      await load();
    } catch (err) { banner(err.message, "err"); }
  })();
})();
