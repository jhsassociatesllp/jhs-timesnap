/* static/timesheet/forms.js
 * "Forms" section of the Timesheet module. Currently hosts the Employee
 * Declaration & Undertaking; add further forms to FORM_REGISTRY.
 * Visible to every employee for now (access restrictions to come later).
 */
(function () {
  const BASE = "/employee-declaration";
  const authHeaders = () => ({ Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` });

  const FORM_REGISTRY = [
    {
      id: "declaration",
      title: "Employee Declaration & Undertaking",
      subtitle: "Code of Conduct, Confidentiality, Data Protection and Compliance Declaration",
      icon: "fa-file-signature",
      open: openDeclaration,
      status: declarationStatus,
    },
  ];

  /* ---------- styles ---------- */
  const css = `
  .fm-wrap{padding:2.2rem 3rem 3rem}
  .fm-title{font-size:1.4rem;font-weight:700;margin:0 0 .3rem;display:flex;gap:.6rem;align-items:center}
  .fm-sub{color:var(--text-light);margin:0 0 1.6rem;font-size:.95rem}
  .fm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1.2rem}
  .fm-card{border:1px solid var(--border-color);border-radius:14px;padding:1.4rem;background:#fff;box-shadow:var(--shadow-light);display:flex;flex-direction:column;gap:.7rem;transition:var(--transition)}
  .fm-card:hover{transform:translateY(-3px);box-shadow:var(--shadow-medium)}
  .fm-card i.fm-ico{font-size:1.6rem;color:#667eea}
  .fm-card h3{margin:0;font-size:1.05rem}
  .fm-card p{margin:0;color:var(--text-light);font-size:.86rem;flex:1}
  .fm-badge{align-self:flex-start;font-size:.74rem;font-weight:600;padding:.2rem .7rem;border-radius:20px}
  .fm-badge.pending{background:#fff4e0;color:#b9770e}
  .fm-badge.done{background:#e3f8ee;color:#117a4d}
  .fm-btn{display:inline-flex;align-items:center;gap:.5rem;padding:.65rem 1.3rem;border:none;border-radius:10px;font-size:.9rem;font-weight:600;font-family:inherit;cursor:pointer;transition:var(--transition);text-decoration:none}
  .fm-btn.primary{background:var(--primary-gradient);color:#fff;box-shadow:var(--shadow-light)}
  .fm-btn.primary:hover:not(:disabled){transform:translateY(-2px);box-shadow:var(--shadow-medium)}
  .fm-btn:disabled{opacity:.45;cursor:not-allowed}
  .fm-btn.ghost{background:#fff;color:var(--text-dark);border:1px solid var(--border-color)}
  .fm-btn.ghost:hover:not(:disabled){background:var(--light-bg)}
  .fm-back{margin-bottom:1.2rem}
  .fm-label{font-size:.8rem;font-weight:600;color:var(--text-light);text-transform:uppercase;letter-spacing:.6px;margin:1.6rem 0 .7rem;display:flex;gap:.5rem;align-items:center}
  .fm-doc{background:var(--light-bg);border:1px solid var(--border-color);border-radius:12px;padding:2rem 2.2rem;max-height:480px;overflow-y:auto;font-family:Georgia,'Times New Roman',serif;line-height:1.7;color:#1f2d3d}
  .fm-doc p{margin:0 0 .8rem}
  .fm-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}
  .fm-field label{display:block;font-size:.8rem;font-weight:600;color:var(--text-light);margin-bottom:.3rem}
  .fm-field input[type=text]{width:100%;padding:.65rem .8rem;border:1px solid var(--border-color);border-radius:8px;background:#f1f3f6;font-family:inherit;font-size:.95rem;color:var(--text-dark)}
  .fm-sigbox{border:2px dashed #cbd5e1;border-radius:12px;background:#fbfcfe;padding:1rem}
  .fm-tabs{display:flex;gap:.5rem;margin-bottom:.8rem;flex-wrap:wrap}
  .fm-tab{padding:.45rem 1rem;border-radius:20px;border:1px solid var(--border-color);background:#fff;font-size:.85rem;font-weight:600;font-family:inherit;cursor:pointer;color:var(--text-light)}
  .fm-tab.active{background:var(--primary-gradient);color:#fff;border-color:transparent}
  .fm-pane{display:none}.fm-pane.active{display:block}
  .fm-canvas-holder{background:#fff;border:1px solid var(--border-color);border-radius:8px;touch-action:none}
  .fm-canvas-holder canvas{display:block;width:100%;height:170px;cursor:crosshair;border-radius:8px}
  .fm-typed{width:100%;padding:.7rem .9rem;border:1px solid var(--border-color);border-radius:8px;font-size:1rem;font-family:inherit}
  .fm-typed-prev{margin-top:.7rem;height:110px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid var(--border-color);border-radius:8px;font-family:'Dancing Script','Brush Script MT',cursive;font-size:3rem;color:#1f2d3d;overflow:hidden;white-space:nowrap}
  .fm-up-prev{margin-top:.7rem;max-height:130px;display:none;border:1px solid var(--border-color);border-radius:8px;background:#fff;padding:.4rem}
  .fm-hint{font-size:.82rem;color:var(--text-light);margin-top:.6rem}
  .fm-agree{display:flex;gap:.6rem;align-items:flex-start;margin-top:1.3rem;font-size:.92rem;cursor:pointer}
  .fm-agree input{margin-top:.3rem;width:auto}
  .fm-actions{display:flex;gap:.8rem;flex-wrap:wrap;margin-top:1.4rem;align-items:center}
  .fm-err{display:none;margin-top:1rem;padding:.8rem 1rem;border-radius:10px;background:#fdecea;color:#c0392b;border:1px solid #f5c6c0;font-size:.88rem}
  .fm-err.show{display:block}
  .fm-done{text-align:center;padding:1.5rem 0 .5rem}
  .fm-done i.big{font-size:3rem;color:#11998e}
  .fm-done h3{margin:.6rem 0 .3rem}
  .fm-tbl{width:100%;max-width:620px;margin:1.2rem auto;border-collapse:collapse;font-size:.9rem;text-align:left}
  .fm-tbl th{background:var(--light-bg);padding:.6rem .8rem;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--text-light);border:1px solid var(--border-color)}
  .fm-tbl td{padding:.6rem .8rem;border:1px solid var(--border-color)}
  .fm-tbl img{max-height:60px;display:block}
  .fm-modal{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:2000;display:none;align-items:center;justify-content:center;padding:1.5rem}
  .fm-modal.show{display:flex}
  .fm-modal-box{background:#fff;border-radius:14px;width:min(980px,100%);height:min(92vh,1000px);display:flex;flex-direction:column;overflow:hidden}
  .fm-modal-head{display:flex;justify-content:space-between;align-items:center;padding:.8rem 1.2rem;background:var(--dark-bg);color:#fff;gap:1rem}
  .fm-modal-head strong{font-size:.95rem}
  .fm-modal-head .fm-btn{padding:.4rem .9rem;font-size:.82rem}
  .fm-modal-box iframe{flex:1;border:0;width:100%}
  @media(max-width:768px){.fm-wrap{padding:1.3rem}.fm-doc{padding:1.2rem}}
  `;
  const styleEl = document.createElement("style");
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  /* ---------- helpers ---------- */
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtDate = (v) => {
    if (!v) return "—";
    try { return new Date(v).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }); } catch { return "—"; }
  };
  const fmtDateTime = (v) => {
    if (!v) return "—";
    try { return new Date(v).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return "—"; }
  };
  let _status = null;

  async function fetchStatus() {
    const r = await fetch(`${BASE}/status`, { headers: authHeaders() });
    if (!r.ok) throw new Error("status");
    _status = await r.json();
    return _status;
  }

  async function declarationStatus() {
    try {
      const s = await fetchStatus();
      return s.submitted
        ? { cls: "done", text: `Signed on ${fmtDate(s.submitted_at)}` }
        : { cls: "pending", text: "Action required - not signed yet" };
    } catch { return { cls: "pending", text: "Status unavailable" }; }
  }

  /* ---------- PDF viewer modal ---------- */
  let _blobUrl = null;
  function ensureModal() {
    if ($("fmModal")) return;
    const m = document.createElement("div");
    m.className = "fm-modal";
    m.id = "fmModal";
    m.innerHTML = `<div class="fm-modal-box">
      <div class="fm-modal-head"><strong id="fmModalTitle">Declaration PDF</strong>
        <div style="display:flex;gap:.6rem">
          <a class="fm-btn ghost" id="fmModalDl" style="display:none"><i class="fas fa-download"></i> Download</a>
          <button class="fm-btn ghost" id="fmModalClose"><i class="fas fa-times"></i> Close</button>
        </div></div>
      <iframe id="fmModalFrame" title="Declaration PDF"></iframe></div>`;
    document.body.appendChild(m);
    $("fmModalClose").onclick = closeModal;
    m.addEventListener("click", (e) => { if (e.target === m) closeModal(); });
  }
  function closeModal() {
    $("fmModal").classList.remove("show");
    $("fmModalFrame").src = "about:blank";
    if (_blobUrl) { URL.revokeObjectURL(_blobUrl); _blobUrl = null; }
  }
  async function showPdf(title, url, init, downloadName) {
    ensureModal();
    $("fmModalTitle").textContent = title;
    try {
      const r = await fetch(url, { headers: { ...authHeaders(), ...(init?.headers || {}) }, method: init?.method || "GET", body: init?.body });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "Could not load the PDF");
      const blob = await r.blob();
      _blobUrl = URL.createObjectURL(blob);
      $("fmModalFrame").src = _blobUrl;
      const dl = $("fmModalDl");
      if (downloadName) { dl.href = _blobUrl; dl.download = downloadName; dl.style.display = ""; } else dl.style.display = "none";
      $("fmModal").classList.add("show");
    } catch (e) { alert(e.message || "Could not load the PDF"); }
  }
  async function downloadMyPdf() {
    try {
      const r = await fetch(`${BASE}/my-pdf?download=true`, { headers: authHeaders() });
      if (!r.ok) throw new Error();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob());
      a.download = `Employee-Declaration-${localStorage.getItem("loggedInEmployeeId") || ""}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch { alert("Could not download the PDF."); }
  }

  /* ---------- Forms list ---------- */
  async function initFormsSection() {
    const root = $("formsSection");
    if (!root) return;
    root.innerHTML = `<div class="fm-wrap">
      <h2 class="fm-title"><i class="fas fa-file-alt"></i> Forms</h2>
      <p class="fm-sub">Forms you need to read, fill in and sign.</p>
      <div class="fm-grid" id="fmGrid"></div></div>`;
    const grid = $("fmGrid");
    for (const f of FORM_REGISTRY) {
      const st = await f.status();
      const card = document.createElement("div");
      card.className = "fm-card";
      card.innerHTML = `<i class="fas ${f.icon} fm-ico"></i><h3>${esc(f.title)}</h3><p>${esc(f.subtitle)}</p>
        <span class="fm-badge ${st.cls}">${esc(st.text)}</span>
        <button class="fm-btn primary"><i class="fas ${st.cls === "done" ? "fa-eye" : "fa-pen"}"></i> ${st.cls === "done" ? "View" : "Fill & Sign"}</button>`;
      card.querySelector("button").onclick = () => f.open(root);
      grid.appendChild(card);
    }
  }

  /* ---------- Employee Declaration ---------- */
  async function openDeclaration(root) {
    root.innerHTML = `<div class="fm-wrap"><p class="fm-sub"><i class="fas fa-spinner fa-spin"></i> Loading…</p></div>`;
    let s;
    try { s = await fetchStatus(); } catch { root.innerHTML = `<div class="fm-wrap"><p class="fm-sub">Could not load the form. Please refresh.</p></div>`; return; }
    s.submitted ? renderDone(root, s) : await renderForm(root, s);
  }

  function renderDone(root, s) {
    root.innerHTML = `<div class="fm-wrap">
      <button class="fm-btn ghost fm-back" id="fmBack"><i class="fas fa-arrow-left"></i> All forms</button>
      <div class="fm-done"><i class="fas fa-check-circle big"></i>
        <h3>Declaration submitted</h3>
        <p class="fm-sub">No further action is needed - your signed declaration is on record.</p>
        <table class="fm-tbl"><thead><tr><th>Employee Name</th><th>Date</th><th>Signature</th></tr></thead>
          <tbody><tr><td>${esc(s.employee_name)}</td><td>${esc(fmtDateTime(s.submitted_at))}</td>
          <td>${s.signature ? `<img src="${esc(s.signature)}" alt="Signature">` : "—"}</td></tr></tbody></table>
        <div class="fm-actions" style="justify-content:center">
          <button class="fm-btn primary" id="fmView"><i class="fas fa-eye"></i> View PDF</button>
          <button class="fm-btn ghost" id="fmDl"><i class="fas fa-download"></i> Download PDF</button>
        </div></div></div>`;
    $("fmBack").onclick = initFormsSection;
    $("fmView").onclick = () => showPdf("Employee Declaration & Undertaking", `${BASE}/my-pdf`, null, `Employee-Declaration.pdf`);
    $("fmDl").onclick = downloadMyPdf;
  }

  async function renderForm(root, s) {
    let docHtml = "<p>Could not load the declaration document.</p>";
    try {
      const r = await fetch(`${BASE}/document`, { headers: authHeaders() });
      if (r.ok) docHtml = (await r.json()).html || docHtml;
    } catch {}
    const today = new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });

    root.innerHTML = `<div class="fm-wrap">
      <button class="fm-btn ghost fm-back" id="fmBack"><i class="fas fa-arrow-left"></i> All forms</button>
      <h2 class="fm-title"><i class="fas fa-file-signature"></i> Employee Declaration &amp; Undertaking</h2>
      <p class="fm-sub">Read the declaration, fill in the details below and sign to submit.</p>

      <div class="fm-label"><i class="fas fa-file-alt"></i> Declaration</div>
      <div class="fm-doc">${docHtml}</div>

      <div class="fm-label"><i class="fas fa-user"></i> Your details</div>
      <div class="fm-fields">
        <div class="fm-field"><label>Employee Name</label><input type="text" id="fmName" readonly value="${esc(s.employee_name)}"></div>
        <div class="fm-field"><label>Date</label><input type="text" id="fmDate" readonly value="${esc(today)}"></div>
      </div>

      <div class="fm-label"><i class="fas fa-signature"></i> Signature</div>
      <div class="fm-sigbox">
        <div class="fm-tabs">
          <button class="fm-tab active" data-p="draw"><i class="fas fa-pen"></i> Draw</button>
          <button class="fm-tab" data-p="type"><i class="fas fa-keyboard"></i> Type</button>
          <button class="fm-tab" data-p="upload"><i class="fas fa-upload"></i> Upload image</button>
        </div>
        <div class="fm-pane active" id="fmPane-draw">
          <div class="fm-canvas-holder"><canvas id="fmCanvas"></canvas></div>
          <p class="fm-hint"><i class="fas fa-info-circle"></i> Sign with your mouse, finger or stylus.</p>
          <button class="fm-btn ghost" id="fmClear"><i class="fas fa-eraser"></i> Clear</button>
        </div>
        <div class="fm-pane" id="fmPane-type">
          <input class="fm-typed" id="fmTyped" type="text" maxlength="40" placeholder="Type your full name" value="">
          <div class="fm-typed-prev" id="fmTypedPrev"></div>
        </div>
        <div class="fm-pane" id="fmPane-upload">
          <input type="file" id="fmFile" accept="image/png,image/jpeg">
          <img class="fm-up-prev" id="fmUpPrev" alt="Uploaded signature">
          <p class="fm-hint">PNG or JPG of your signature on a plain/white background.</p>
        </div>
      </div>

      <label class="fm-agree"><input type="checkbox" id="fmAgree">
        <span>I have read, understood and agree to the above Employee Declaration &amp; Undertaking.</span></label>

      <div class="fm-actions">
        <button class="fm-btn ghost" id="fmPreview" disabled><i class="fas fa-eye"></i> Preview PDF</button>
        <button class="fm-btn primary" id="fmSubmit" disabled><i class="fas fa-check"></i> Submit Declaration</button>
      </div>
      <div class="fm-err" id="fmErr"></div></div>`;

    $("fmBack").onclick = initFormsSection;
    wireSignature(s);
  }

  function wireSignature(s) {
    let mode = "draw", drawn = false, typedUrl = null, uploadUrl = null, drawing = false;
    const canvas = $("fmCanvas"), ctx = canvas.getContext("2d");

    function sizeCanvas() {
      const r = canvas.getBoundingClientRect();
      if (!r.width) return requestAnimationFrame(sizeCanvas);
      const k = window.devicePixelRatio || 1;
      canvas.width = r.width * k; canvas.height = r.height * k;
      ctx.scale(k, k); ctx.lineWidth = 2.4; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#1f2d3d";
    }
    sizeCanvas();
    const pos = (e) => { const r = canvas.getBoundingClientRect(), p = e.touches ? e.touches[0] : e; return { x: p.clientX - r.left, y: p.clientY - r.top }; };
    const start = (e) => { e.preventDefault(); drawing = true; const p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); };
    const move = (e) => { if (!drawing) return; e.preventDefault(); const p = pos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); if (!drawn) { drawn = true; refresh(); } };
    canvas.addEventListener("mousedown", start); canvas.addEventListener("mousemove", move);
    window.addEventListener("mouseup", () => (drawing = false));
    canvas.addEventListener("touchstart", start, { passive: false });
    canvas.addEventListener("touchmove", move, { passive: false });
    canvas.addEventListener("touchend", () => (drawing = false));
    $("fmClear").onclick = () => { const r = canvas.getBoundingClientRect(); ctx.clearRect(0, 0, r.width, r.height); drawn = false; refresh(); };

    // Typed signature -> PNG via canvas, so the server stores one format only.
    $("fmTyped").addEventListener("input", async () => {
      const t = $("fmTyped").value.trim();
      $("fmTypedPrev").textContent = t;
      if (!t) { typedUrl = null; return refresh(); }
      try { await document.fonts.load("56px 'Dancing Script'"); } catch {}
      const c = document.createElement("canvas"); c.width = 700; c.height = 160;
      const x = c.getContext("2d");
      x.fillStyle = "#1f2d3d"; x.textBaseline = "middle";
      let size = 72; x.font = `${size}px 'Dancing Script','Brush Script MT',cursive`;
      while (x.measureText(t).width > 660 && size > 20) { size -= 4; x.font = `${size}px 'Dancing Script','Brush Script MT',cursive`; }
      x.fillText(t, 20, 82);
      typedUrl = c.toDataURL("image/png"); refresh();
    });

    $("fmFile").addEventListener("change", (e) => {
      const f = e.target.files[0];
      uploadUrl = null; $("fmUpPrev").style.display = "none";
      if (!f) return refresh();
      if (!/^image\/(png|jpeg)$/.test(f.type)) { showErr("Please choose a PNG or JPG image."); e.target.value = ""; return refresh(); }
      const img = new Image();
      img.onload = () => {
        const sc = Math.min(1, 700 / img.width, 200 / img.height);
        const c = document.createElement("canvas"); c.width = Math.round(img.width * sc); c.height = Math.round(img.height * sc);
        const x = c.getContext("2d"); x.fillStyle = "#fff"; x.fillRect(0, 0, c.width, c.height); x.drawImage(img, 0, 0, c.width, c.height);
        uploadUrl = c.toDataURL("image/png");
        $("fmUpPrev").src = uploadUrl; $("fmUpPrev").style.display = "block"; refresh();
      };
      img.onerror = () => showErr("That image could not be read.");
      img.src = URL.createObjectURL(f);
    });

    document.querySelectorAll(".fm-tab").forEach((b) => (b.onclick = () => {
      mode = b.dataset.p;
      document.querySelectorAll(".fm-tab").forEach((x) => x.classList.toggle("active", x === b));
      document.querySelectorAll(".fm-pane").forEach((p) => p.classList.toggle("active", p.id === `fmPane-${mode}`));
      if (mode === "draw") sizeCanvas();
      refresh();
    }));

    const currentSig = () => (mode === "draw" ? (drawn ? canvas.toDataURL("image/png") : null) : mode === "type" ? typedUrl : uploadUrl);
    function showErr(m) { const e = $("fmErr"); e.textContent = m; e.classList.add("show"); }
    function refresh() {
      $("fmErr").classList.remove("show");
      const ok = !!currentSig();
      $("fmPreview").disabled = !ok;
      $("fmSubmit").disabled = !(ok && $("fmAgree").checked);
    }
    $("fmAgree").onchange = refresh;

    $("fmPreview").onclick = () => showPdf("Preview - how your declaration will look", `${BASE}/preview-pdf`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ signature: currentSig() }) });

    $("fmSubmit").onclick = async () => {
      const sig = currentSig(); if (!sig) return;
      if (!confirm("Submit your signed declaration? This can't be changed afterwards.")) return;
      const btn = $("fmSubmit"); btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Submitting…';
      try {
        const r = await fetch(`${BASE}/submit`, { method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" }, body: JSON.stringify({ signature: sig }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { showErr(d.detail || "Could not submit the declaration."); btn.innerHTML = '<i class="fas fa-check"></i> Submit Declaration'; refresh(); return; }
        const st = await fetchStatus();
        renderDone($("formsSection"), st);
      } catch { showErr("Network error - please try again."); btn.innerHTML = '<i class="fas fa-check"></i> Submit Declaration'; refresh(); }
    };
  }

  window.initFormsSection = initFormsSection;
})();
