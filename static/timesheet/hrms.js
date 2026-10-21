// static/timesheet/hrms.js — admin HRMS upload (preview, then import). Talks to /hrms/*.
// All server text goes through textContent.
(function () {
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  if (!token) { window.location.href = "/static/login.html"; return; }
  const $ = (id) => document.getElementById(id);
  const auth = { Authorization: `Bearer ${token}` };

  function banner(text, kind) {
    const el = $("msg");
    if (!text) { el.style.display = "none"; return; }
    el.textContent = text; el.className = "dt-banner " + kind; el.style.display = "block";
  }

  async function call(method, url, body) {
    const res = await fetch(url, { method, headers: auth, body });
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

  const formFile = () => {
    const f = $("file").files[0];
    if (!f) throw new Error("Choose a file first");
    const fd = new FormData(); fd.append("file", f);
    return fd;
  };

  function stat(box, label, value) {
    const d = document.createElement("div"); d.className = "kpi" + (label === "Errors" && value > 0 ? " red" : "");
    const s = document.createElement("span"); s.textContent = label;
    const b = document.createElement("b"); b.textContent = value;
    d.append(s, b); box.append(d);
  }

  function cell(tr, text) { tr.insertCell().textContent = text === null || text === undefined ? "—" : text; }

  async function loadStatus() {
    const d = await call("GET", "/hrms/uploads");
    const last = d.last_upload;
    $("status").textContent = last
      ? `Last upload: ${new Date(last.uploaded_at).toLocaleString()} · ${last.file_name} · covers ${last.date_from} to ${last.date_to}`
      : "No HRMS file has been uploaded yet.";
    $("awaiting").textContent = d.awaiting_dates.length
      ? "Working days still awaiting HRMS (last 30 days): " + d.awaiting_dates.join(", ")
      : "No working days awaiting HRMS in the last 30 days.";
    const body = $("history"); body.textContent = "";
    if (!d.uploads.length) { const td = body.insertRow().insertCell(); td.colSpan = 6; td.className = "empty-row"; td.textContent = "No uploads yet."; }
    d.uploads.forEach((u) => {
      const tr = body.insertRow();
      cell(tr, new Date(u.uploaded_at).toLocaleString()); cell(tr, u.file_name); cell(tr, u.uploaded_by);
      cell(tr, `${u.date_from} → ${u.date_to}`); cell(tr, u.rows_imported); cell(tr, u.rows_errors);
    });
    const heads = [...body.closest("table").querySelectorAll("thead th")].map((th) => th.textContent);
    [...body.rows].forEach((tr) => [...tr.cells].forEach((td, i) => { if (heads[i] && !td.classList.contains("empty-row")) td.setAttribute("data-label", heads[i]); }));
  }

  $("previewBtn").onclick = async () => {
    banner("");
    try {
      const p = await call("POST", "/hrms/upload/preview", formFile());
      const box = $("previewStats"); box.textContent = "";
      stat(box, "Rows", p.total_rows); stat(box, "Valid", p.valid_rows); stat(box, "Errors", p.error_count);
      stat(box, "Employees", p.employees); stat(box, "Dates", `${p.date_from || "—"} → ${p.date_to || "—"}`);
      const w = $("warnings");
      w.textContent = p.warnings.join(" • "); w.style.display = p.warnings.length ? "block" : "none";
      const eb = $("errorsBody"); eb.textContent = "";
      p.errors.forEach((e) => { const tr = eb.insertRow(); cell(tr, e.row); cell(tr, e.message); });
      $("errorsWrap").style.display = p.errors.length ? "block" : "none";
      $("importBtn").disabled = p.valid_rows === 0;
      $("previewCard").style.display = "block";
    } catch (err) { banner(err.message, "err"); }
  };

  $("importBtn").onclick = async () => {
    banner("");
    $("importBtn").disabled = true;
    try {
      const r = await call("POST", "/hrms/upload/commit", formFile());
      const c = r.reco_counts || {};
      banner(`Imported ${r.rows_imported} rows (${r.rows_new} new, ${r.rows_existing} already there). ` +
        `Reconciled: ${Object.entries(c).map(([k, v]) => `${v} ${k}`).join(", ") || "nothing to reconcile"}.` +
        (r.holidays_added.length ? ` Holidays added: ${r.holidays_added.join(", ")}.` : ""), "ok");
      $("previewCard").style.display = "none"; $("file").value = "";
      await loadStatus();
    } catch (err) { banner(err.message, "err"); $("importBtn").disabled = false; }
  };

  loadStatus().catch((err) => banner(err.message, "err"));
})();
