// Bridges the normal JHS Timesnap login into this dashboard: if the
// employee's code is in the module's admins collection, they land here
// straight from the modules page with no separate HR login step. There is
// no standalone HR login anymore - access is entirely based on the
// platform login + the admins collection.
async function bootstrapAuth() {
  if (getToken("hr")) return true;

  const platformToken = localStorage.getItem("access_token");
  if (!platformToken) {
    window.location.href = "/login";
    return false;
  }

  try {
    const res = await fetch("/hr-quiz/api/platform-access", {
      headers: { Authorization: `Bearer ${platformToken}` },
    });
    if (!res.ok) {
      window.location.href = "/modules";
      return false;
    }
    const data = await res.json();
    setToken("hr", data.access_token);
    return true;
  } catch (e) {
    window.location.href = "/modules";
    return false;
  }
}

const hrDashboardReady = bootstrapAuth();

document.getElementById("logoutBtn").addEventListener("click", () => {
  localStorage.clear();
  sessionStorage.clear();
  window.location.href = "/login";
});

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => (p.style.display = "none"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).style.display = "block";
  });
});

// ---------------------------------------------------------------------------
// Date filter (From / To are calendar days; timestamps from the server are UTC) - also applied to the downloads
// ---------------------------------------------------------------------------
const utc = (s) => (/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
function inRange(iso, from, to) {
  if (!from && !to) return true;
  if (!iso) return false;
  const t = new Date(utc(iso)).getTime();
  if (from && t < new Date(from + "T00:00:00").getTime()) return false;
  if (to && t > new Date(to + "T23:59:59.999").getTime()) return false;
  return true;
}
function dateFilter() {
  return { by: document.getElementById("dfBy").value, from: document.getElementById("dfFrom").value, to: document.getElementById("dfTo").value };
}
function dateQuery() {
  const { by, from, to } = dateFilter();
  return [from && "date_from=" + from, to && "date_to=" + to, (from || to) && "by=" + by].filter(Boolean).join("&");
}
["dfBy", "dfFrom", "dfTo"].forEach((id) => document.getElementById(id).addEventListener("change", () => loadCandidates()));
document.getElementById("dfClear").addEventListener("click", () => {
  document.getElementById("dfFrom").value = ""; document.getElementById("dfTo").value = ""; loadCandidates();
});

// ---------------------------------------------------------------------------
// Paging: at most one page of candidates on screen (10 / 25 / 50 / 100 per page); the numbers above the table
// (total / completed / average) still cover every candidate that matches the date filter.
// ---------------------------------------------------------------------------
const quizPg = { page: 1, size: 10, sig: null };
function renderQuizPager(total) {
  const box = document.getElementById("pgQuiz");
  const pages = Math.max(1, Math.ceil(total / quizPg.size));
  if (!total) { box.innerHTML = ""; return; }
  box.innerHTML = `<span>Rows per page <select id="pgQuizSize">${[10, 25, 50, 100].map((n) => `<option${n === quizPg.size ? " selected" : ""}>${n}</option>`).join("")}</select></span>
    <span>${(quizPg.page - 1) * quizPg.size + 1}-${Math.min(total, quizPg.page * quizPg.size)} of ${total}</span>
    <span><button type="button" class="btn btn-ghost btn-sm" id="pgQuizPrev" ${quizPg.page <= 1 ? "disabled" : ""}>&lsaquo; Prev</button>
      Page ${quizPg.page} of ${pages}
      <button type="button" class="btn btn-ghost btn-sm" id="pgQuizNext" ${quizPg.page >= pages ? "disabled" : ""}>Next &rsaquo;</button></span>`;
  document.getElementById("pgQuizSize").addEventListener("change", (e) => { quizPg.size = +e.target.value; quizPg.page = 1; loadCandidates(); });
  document.getElementById("pgQuizPrev").addEventListener("click", () => { quizPg.page--; loadCandidates(); });
  document.getElementById("pgQuizNext").addEventListener("click", () => { quizPg.page++; loadCandidates(); });
}

// ---------------------------------------------------------------------------
// Candidate table + stats
// ---------------------------------------------------------------------------
async function loadCandidates() {
  let rows = await apiRequest("/api/hr/candidates", { role: "hr" });
  const total = rows.length;
  const { by, from, to } = dateFilter();
  if (from || to) rows = rows.filter((r) => inRange(r[by], from, to));
  document.getElementById("dfInfo").textContent = from || to ? `showing ${rows.length} of ${total} candidates` : "";
  const tbody = document.getElementById("candidateTableBody");
  const empty = document.getElementById("candidateEmpty");
  tbody.innerHTML = "";
  const sig = [by, from, to].join("|");                      // a new date filter starts on page 1
  if (quizPg.sig !== sig) { quizPg.sig = sig; quizPg.page = 1; }
  quizPg.page = Math.min(quizPg.page, Math.max(1, Math.ceil(rows.length / quizPg.size)));
  const pageStart = (quizPg.page - 1) * quizPg.size, pageEnd = pageStart + quizPg.size;
  renderQuizPager(rows.length);

  if (rows.length === 0) {
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
  }

  let completed = 0, inProgress = 0, scoreSum = 0, scoreCount = 0;

  rows.forEach((r, idx) => {
    if (r.status === "completed") { completed++; scoreSum += r.score; scoreCount++; }
    if (r.status === "in_progress") inProgress++;
    if (idx < pageStart || idx >= pageEnd) return;           // counted above, just not drawn on this page

    const tr = document.createElement("tr");
    const badgeClass = r.status === "completed" ? "badge-completed" : r.status === "in_progress" ? "badge-progress" : "badge-pending";
    const badgeText = r.status === "completed" ? "Completed" : r.status === "in_progress" ? "In progress" : "Not started";

    let scoreHtml = "-";
    if (r.status === "completed") {
      const pct = r.score / r.total_questions;
      const cls = pct >= 0.7 ? "score-good" : pct >= 0.4 ? "score-mid" : "score-low";
      scoreHtml = `<span class="score-pill ${cls}">${r.score}/${r.total_questions}</span>`;
    }

    const viewBtnHtml = r.status === "completed"
      ? `<button class="btn btn-secondary btn-sm" data-action="view">View answers</button>`
      : "-";

    tr.innerHTML = `
      <td>${escapeHtml(r.email)}</td>
      <td>${escapeHtml(r.quiz_set_name || "-")}</td>
      <td><span class="badge ${badgeClass}">${badgeText}</span></td>
      <td>${scoreHtml}</td>
      <td>${formatDateTime(r.submitted_at)}</td>
      <td>${viewBtnHtml}</td>
      <td><button class="btn btn-ghost btn-sm" data-action="regen">Regenerate</button></td>
      <td><button class="btn btn-ghost btn-sm" data-action="delete">Delete</button></td>
    `;
    tr.querySelector('[data-action="regen"]').addEventListener("click", () => quickRegenerate(r.email));
    tr.querySelector('[data-action="delete"]').addEventListener("click", () => deleteCandidate(r.email));
    const viewBtn = tr.querySelector('[data-action="view"]');
    if (viewBtn) viewBtn.addEventListener("click", () => viewAttempt(r.email));
    tbody.appendChild(tr);
  });

  document.getElementById("statTotal").textContent = rows.length;
  document.getElementById("statCompleted").textContent = completed;
  document.getElementById("statProgress").textContent = inProgress;
  document.getElementById("statAvg").textContent = scoreCount ? (scoreSum / scoreCount).toFixed(1) : "-";
}

const downloadBtn = document.getElementById("downloadBtn");
const downloadMenu = document.getElementById("downloadMenu");

downloadBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  downloadMenu.style.display = downloadMenu.style.display === "block" ? "none" : "block";
});
document.addEventListener("click", () => { downloadMenu.style.display = "none"; });
downloadMenu.querySelectorAll("button").forEach((btn) => {
  btn.addEventListener("click", () => {
    downloadMenu.style.display = "none";
    downloadReport(btn.dataset.format);
  });
});

async function downloadReport(format) {
  const originalText = downloadBtn.textContent;
  downloadBtn.disabled = true;
  downloadBtn.textContent = "Preparing...";
  try {
    const qs = dateQuery();
    const res = await fetch(`${API_BASE}/api/hr/candidates/export.${format}${qs ? "?" + qs : ""}`, {
      headers: { Authorization: "Bearer " + getToken("hr") },
    });
    if (!res.ok) throw new Error("Could not generate the report");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `candidates-report.${format}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message);
  } finally {
    downloadBtn.disabled = false;
    downloadBtn.textContent = originalText;
  }
}

function deleteCandidate(email) {
  showConfirmModal(
    `Delete <strong>${escapeHtml(email)}</strong>? This removes their login and their full quiz history. This can't be undone.`,
    "Yes, delete",
    async () => {
      try {
        await apiRequest(`/api/hr/candidates/${encodeURIComponent(email)}`, { method: "DELETE", role: "hr" });
        loadCandidates();
      } catch (err) {
        alert(err.message);
      }
    }
  );
}

function quickRegenerate(email) {
  showConfirmModal(
    `Generate a new password for <strong>${escapeHtml(email)}</strong>? Their old password will stop working.`,
    "Yes, regenerate",
    async () => {
      try {
        const data = await apiRequest("/api/hr/candidates/regenerate-password", {
          method: "POST",
          role: "hr",
          body: { emails: [email] },
        });
        showPasswordModal(email, data.password, data.mail);
      } catch (err) {
        alert(err.message);
      }
    }
  );
}

function showConfirmModal(messageHtml, confirmText, onConfirm) {
  const root = document.getElementById("attemptModalRoot");
  root.innerHTML = `
    <div class="modal-overlay" id="confirmModalOverlay">
      <div class="modal-box" style="max-width:420px;">
        <div class="modal-header">
          <h3>Are you sure?</h3>
        </div>
        <p style="margin: 0 0 22px; color: var(--gray-600); font-size:14px;">${messageHtml}</p>
        <div style="display:flex; justify-content:flex-end; gap:10px;">
          <button class="btn btn-ghost btn-sm" id="confirmCancelBtn">Cancel</button>
          <button class="btn btn-primary btn-sm" id="confirmOkBtn">${escapeHtml(confirmText)}</button>
        </div>
      </div>
    </div>
  `;
  const close = () => { root.innerHTML = ""; };
  document.getElementById("confirmCancelBtn").addEventListener("click", close);
  document.getElementById("confirmModalOverlay").addEventListener("click", (e) => {
    if (e.target.id === "confirmModalOverlay") close();
  });
  document.getElementById("confirmOkBtn").addEventListener("click", () => {
    close();
    onConfirm();
  });
}

function showPasswordModal(email, password, mail) {
  const root = document.getElementById("attemptModalRoot");
  root.innerHTML = `
    <div class="modal-overlay" id="passwordModalOverlay">
      <div class="modal-box" style="max-width:420px;">
        <div class="modal-header">
          <h3>New password generated</h3>
          <button class="btn btn-ghost btn-sm" id="passwordModalClose">Close</button>
        </div>
        <p class="hint" style="margin-bottom:14px;">For <strong>${escapeHtml(email)}</strong>. Their old password stopped working.</p>${mail ? mailNote(mail) : ""}
        <div class="password-display">
          <span id="passwordText">${escapeHtml(password)}</span>
          <button class="btn btn-secondary btn-sm" id="copyPasswordBtn">Copy</button>
        </div>
      </div>
    </div>
  `;
  const close = () => { root.innerHTML = ""; };
  document.getElementById("passwordModalClose").addEventListener("click", close);
  document.getElementById("passwordModalOverlay").addEventListener("click", (e) => {
    if (e.target.id === "passwordModalOverlay") close();
  });
  document.getElementById("copyPasswordBtn").addEventListener("click", () => {
    navigator.clipboard.writeText(password).then(() => {
      const btn = document.getElementById("copyPasswordBtn");
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    });
  });
}

document.getElementById("refreshBtn").addEventListener("click", loadCandidates);

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------
let allDocuments = [];

function mailNote(m) {
  m = m || {};
  if (m.configured === false) return `<div class="hint" style="margin-top:10px;color:#b9770e;"><strong>Email not sent</strong> - ${escapeHtml(m.error || "the mail service is not set up")} Share the password yourself.</div>`;
  if ((m.failed || []).length) return `<div class="hint" style="margin-top:10px;color:#b9770e;">Email sent to ${(m.sent || []).length}. <strong>Could not email:</strong> ${m.failed.map(escapeHtml).join(", ")}. ${escapeHtml(m.error || "")} Share the password yourself.</div>`;
  return `<div class="hint" style="margin-top:10px;color:#0d7a70;"><strong>Email sent</strong> to ${(m.sent || []).length} candidate(s) with the new password.</div>`;
}

// ---------------------------------------------------------------------------
// Question review: HR reads every question of a document, and edits or deletes the ones that are not good
// ---------------------------------------------------------------------------
let QV = { docId: null, title: "", all: [], page: 1, q: "", editing: null };
const QV_PAGE = 8;

async function viewQuestions(documentId, title) {
  try {
    const d = await apiRequest(`/api/hr/documents/${encodeURIComponent(documentId)}/questions`, { role: "hr" });
    QV = { docId: documentId, title, all: d.questions, page: 1, q: "", editing: null };
    let root = document.getElementById("qvRoot");
    if (!root) { root = document.createElement("div"); root.id = "qvRoot"; document.body.appendChild(root); }
    root.innerHTML = `
      <div class="modal-overlay" id="qvOverlay">
        <div class="modal-box" style="max-width:900px;width:94vw;max-height:88vh;display:flex;flex-direction:column;">
          <div class="modal-header"><h3 id="qvTitle"></h3><button class="btn btn-ghost btn-sm" id="qvClose">Close</button></div>
          <div style="padding:10px 16px;border-bottom:1px solid #e1e8ed;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <input id="qvSearch" placeholder="Search questions..." style="flex:1;min-width:200px;padding:8px 10px;border:1px solid #d5d9e4;border-radius:8px;">
            <span class="hint" style="margin:0;">Edit or delete anything unclear, trivial or silly. Changes apply to quizzes started from now on.</span>
          </div>
          <div id="qvList" style="overflow:auto;padding:12px 16px;flex:1;"></div>
          <div id="qvPager" style="display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 16px;border-top:1px solid #e1e8ed;font-size:13px;color:#7f8c8d;"></div>
        </div>
      </div>`;
    const close = () => { root.innerHTML = ""; loadDocuments(); };
    document.getElementById("qvClose").addEventListener("click", close);
    document.getElementById("qvOverlay").addEventListener("click", (e) => { if (e.target.id === "qvOverlay") close(); });
    document.getElementById("qvSearch").addEventListener("input", (e) => { QV.q = e.target.value.toLowerCase(); QV.page = 1; renderQv(); });
    document.getElementById("qvList").addEventListener("click", qvClick);
    renderQv();
  } catch (err) {
    alert(err.message);
  }
}

function renderQv() {
  const rows = QV.all.filter((x) => !QV.q || (x.question + " " + x.options.join(" ")).toLowerCase().includes(QV.q));
  const pages = Math.max(1, Math.ceil(rows.length / QV_PAGE));
  QV.page = Math.min(QV.page, pages);
  const start = (QV.page - 1) * QV_PAGE;
  document.getElementById("qvTitle").innerHTML = `Questions - ${escapeHtml(QV.title)} <span style="font-weight:400;font-size:13px;color:#7f8c8d;">(${QV.all.length})</span>`;
  document.getElementById("qvList").innerHTML = rows.length ? rows.slice(start, start + QV_PAGE).map((x, i) => {
    if (QV.editing === x.id) {
      return `<div class="qv-card" data-id="${x.id}" style="border:2px solid #667eea;border-radius:10px;padding:12px;margin-bottom:12px;">
        <label style="font-size:12px;font-weight:600;color:#7f8c8d;">Question</label>
        <textarea id="qvEq" rows="2" style="width:100%;padding:8px;border:1px solid #d5d9e4;border-radius:8px;margin:4px 0 8px;font-family:inherit;">${escapeHtml(x.question)}</textarea>
        ${x.options.map((o, j) => `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px;"><input type="radio" name="qvCorrect" value="${j}" ${j === x.correct_index ? "checked" : ""} title="Correct answer"><span style="width:18px;font-weight:700;color:#7f8c8d;">${"ABCD"[j]}</span><input class="qvEo" value="${escapeHtml(o)}" style="flex:1;padding:7px 9px;border:1px solid #d5d9e4;border-radius:8px;"></div>`).join("")}
        <div class="hint" style="margin:4px 0 8px;">The dot marks the correct answer.</div>
        <button class="btn btn-primary btn-sm" data-act="save">Save</button> <button class="btn btn-ghost btn-sm" data-act="cancel">Cancel</button>
        <span class="hint" id="qvErr" style="color:#c0392b;margin-left:8px;"></span></div>`;
    }
    return `<div class="qv-card" data-id="${x.id}" style="border:1px solid #e1e8ed;border-radius:10px;padding:12px;margin-bottom:12px;">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start;"><div style="font-weight:600;">${start + i + 1}. ${escapeHtml(x.question)}</div>
        <div style="white-space:nowrap;"><button class="btn btn-ghost btn-sm" data-act="edit">Edit</button> <button class="btn btn-ghost btn-sm" data-act="delete">Delete</button></div></div>
      <ul style="list-style:none;margin:8px 0 0;padding:0;">${x.options.map((o, j) => `<li style="padding:3px 0;${j === x.correct_index ? "color:#0d7a70;font-weight:600;" : ""}">${"ABCD"[j]}. ${escapeHtml(o)}${j === x.correct_index ? " &#10003;" : ""}</li>`).join("")}</ul>
      ${x.source ? `<div class="hint" style="margin:8px 0 0;">From the document: &ldquo;${escapeHtml(x.source)}&rdquo;</div>` : ""}</div>`;
  }).join("") : `<div class="empty-state">No questions match.</div>`;
  document.getElementById("qvPager").innerHTML = `<span>${rows.length ? start + 1 : 0}-${Math.min(rows.length, start + QV_PAGE)} of ${rows.length}</span>
    <span><button class="btn btn-ghost btn-sm" id="qvPrev" ${QV.page <= 1 ? "disabled" : ""}>&lsaquo; Prev</button> Page ${QV.page} of ${pages} <button class="btn btn-ghost btn-sm" id="qvNext" ${QV.page >= pages ? "disabled" : ""}>Next &rsaquo;</button></span>`;
  document.getElementById("qvPrev").addEventListener("click", () => { QV.page--; QV.editing = null; renderQv(); });
  document.getElementById("qvNext").addEventListener("click", () => { QV.page++; QV.editing = null; renderQv(); });
}

async function qvClick(e) {
  const btn = e.target.closest("[data-act]"); if (!btn) return;
  const card = btn.closest(".qv-card"), id = card.dataset.id, item = QV.all.find((x) => x.id === id), act = btn.dataset.act;
  if (act === "edit") { QV.editing = id; renderQv(); return; }
  if (act === "cancel") { QV.editing = null; renderQv(); return; }
  const base = `/api/hr/documents/${encodeURIComponent(QV.docId)}/questions/${encodeURIComponent(id)}`;
  if (act === "delete") {
    if (!confirm("Delete this question?\n\n" + item.question)) return;
    try { await apiRequest(base, { method: "DELETE", role: "hr" }); QV.all = QV.all.filter((x) => x.id !== id); renderQv(); }
    catch (err) { alert(err.message); }
    return;
  }
  if (act === "save") {
    const body = {
      question: document.getElementById("qvEq").value,
      options: [...card.querySelectorAll(".qvEo")].map((i) => i.value),
      correct_index: Number((card.querySelector('input[name="qvCorrect"]:checked') || {}).value),
    };
    try {
      const saved = await apiRequest(base, { method: "PUT", role: "hr", body });
      Object.assign(item, saved); QV.editing = null; renderQv();
    } catch (err) { document.getElementById("qvErr").textContent = err.message; }
  }
}

async function cleanDocumentQuestions(documentId, title) {
  if (!confirm(`Remove the vague or weak questions from the question bank of "${title}"?\n\nThe AI reviews every question; unclear, trivial or silly ones are removed. Quizzes already taken are not affected.`)) return;
  try {
    const r = await apiRequest(`/api/hr/documents/${encodeURIComponent(documentId)}/clean-questions`, { method: "POST", role: "hr" });
    alert(`Done. ${r.removed_count} weak question(s) removed; ${r.after} good questions remain (was ${r.before}).` +
      (r.removed.length ? "\n\nExamples removed:\n- " + r.removed.map((x) => x.question).join("\n- ") : ""));
    loadDocuments();
  } catch (err) {
    alert(err.message);
  }
}

async function loadDocuments() {
  const docs = await apiRequest("/api/hr/documents", { role: "hr" });
  allDocuments = docs;
  const tbody = document.getElementById("documentTableBody");
  const empty = document.getElementById("documentEmpty");
  const categoryList = document.getElementById("docCategoryList");

  tbody.innerHTML = "";
  empty.style.display = docs.length === 0 ? "block" : "none";

  const categories = new Set();

  docs.forEach((d) => {
    if (d.category) categories.add(d.category);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(d.title)}</td>
      <td>${d.category ? `<span class="cat-tag">${escapeHtml(d.category)}</span>` : "-"}</td>
      <td>${escapeHtml(d.filename)}</td>
      <td>${d.question_pool_size}</td>
      <td>${formatDateTime(d.uploaded_at)}</td>
      <td><button class="btn btn-secondary btn-sm" data-action="view-questions" title="Read every question, then edit or delete the ones that are not good">View questions</button>
          <button class="btn btn-ghost btn-sm" data-action="clean-doc" title="Remove vague or trivial questions from this document's question bank">Clean up questions</button>
          <button class="btn btn-ghost btn-sm" data-action="delete-doc">Delete</button></td>
    `;
    tr.querySelector('[data-action="view-questions"]').addEventListener("click", () => viewQuestions(d.document_id, d.title));
    tr.querySelector('[data-action="clean-doc"]').addEventListener("click", () => cleanDocumentQuestions(d.document_id, d.title));
    tr.querySelector('[data-action="delete-doc"]').addEventListener("click", () => deleteDocument(d.document_id, d.title));
    tbody.appendChild(tr);
  });

  categoryList.innerHTML = "";
  categories.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c;
    categoryList.appendChild(opt);
  });

  renderQuizSetDocPicker();
}

function deleteDocument(documentId, title) {
  showConfirmModal(
    `Delete "<strong>${escapeHtml(title)}</strong>"? Its generated questions will be removed too. This can't be undone.`,
    "Yes, delete",
    async () => {
      try {
        await apiRequest(`/api/hr/documents/${encodeURIComponent(documentId)}`, { method: "DELETE", role: "hr" });
        loadDocuments();
      } catch (err) {
        alert(err.message);
      }
    }
  );
}

document.getElementById("uploadForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("uploadError");
  const successBox = document.getElementById("uploadSuccess");
  const btn = document.getElementById("uploadBtn");
  hideError(errorBox);
  successBox.style.display = "none";

  const fileInput = document.getElementById("docFile");
  if (!fileInput.files.length) return;

  const formData = new FormData();
  formData.append("title", document.getElementById("docTitle").value.trim());
  formData.append("category", document.getElementById("docCategory").value.trim());
  formData.append("file", fileInput.files[0]);

  btn.disabled = true;
  btn.textContent = "Reading document and generating questions...";
  try {
    const data = await apiRequest("/api/hr/documents", { method: "POST", role: "hr", body: formData, isForm: true });
    successBox.textContent = `"${data.title}" uploaded - ${data.question_pool_size} questions generated and ready.`;
    successBox.style.display = "block";
    document.getElementById("uploadForm").reset();
    loadDocuments();
  } catch (err) {
    showError(errorBox, err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload and generate questions";
  }
});

// ---------------------------------------------------------------------------
// Quiz sets: pick multiple documents + a per-document question count
// (weightage), save as a named, reusable, editable composition.
// ---------------------------------------------------------------------------
let editingQuizSetId = null;

function renderQuizSetDocPicker(checkedEntries) {
  // checkedEntries: optional [{document_id, count}] to pre-check when
  // loading a quiz set for editing. Without it, keeps whatever is
  // currently checked (e.g. after a re-render triggered by loadDocuments).
  const preset = checkedEntries ? new Map(checkedEntries.map((e) => [e.document_id, e.count])) : null;
  const list = document.getElementById("quizSetDocList");
  const previouslyChecked = preset || new Map(
    Array.from(list.querySelectorAll(".quiz-doc-check:checked")).map((cb) => [cb.dataset.docId, parseInt(cb.closest(".quiz-doc-row").querySelector(".quiz-doc-count").value, 10) || 1])
  );

  list.innerHTML = "";
  if (allDocuments.length === 0) {
    list.innerHTML = `<div class="quiz-doc-row"><span class="hint">Upload a document first.</span></div>`;
    updateQuizSetTotal();
    return;
  }

  allDocuments.forEach((d) => {
    const isChecked = previouslyChecked.has(d.document_id);
    const count = previouslyChecked.get(d.document_id) || Math.min(5, d.question_pool_size || 1);
    const row = document.createElement("label");
    row.className = "quiz-doc-row" + (isChecked ? " checked" : "");
    row.innerHTML = `
      <input type="checkbox" class="quiz-doc-check" data-doc-id="${d.document_id}" ${isChecked ? "checked" : ""} />
      <span class="quiz-doc-title">${escapeHtml(d.title)}
        ${d.category ? `<span class="cat-tag">${escapeHtml(d.category)}</span>` : ""}
        <span class="quiz-doc-pool">(${d.question_pool_size} available)</span>
      </span>
      <span class="quiz-doc-count-label">questions:</span>
      <input type="number" class="quiz-doc-count" min="1" max="${d.question_pool_size}" value="${count}" ${isChecked ? "" : "disabled"} />
    `;
    const checkbox = row.querySelector(".quiz-doc-check");
    const countInput = row.querySelector(".quiz-doc-count");
    checkbox.addEventListener("change", () => {
      countInput.disabled = !checkbox.checked;
      row.classList.toggle("checked", checkbox.checked);
      updateQuizSetTotal();
    });
    countInput.addEventListener("input", updateQuizSetTotal);
    countInput.addEventListener("click", (e) => e.stopPropagation());
    list.appendChild(row);
  });

  updateQuizSetTotal();
}

function getQuizSetSelection() {
  return Array.from(document.querySelectorAll("#quizSetDocList .quiz-doc-check:checked")).map((cb) => ({
    document_id: cb.dataset.docId,
    count: parseInt(cb.closest(".quiz-doc-row").querySelector(".quiz-doc-count").value, 10) || 0,
  }));
}

function updateQuizSetTotal() {
  const total = getQuizSetSelection().reduce((sum, e) => sum + e.count, 0);
  document.getElementById("quizSetTotalHint").textContent = `Total questions: ${total}`;
}

async function loadQuizSets() {
  const sets = await apiRequest("/api/hr/quiz-sets", { role: "hr" });
  const tbody = document.getElementById("quizSetTableBody");
  const empty = document.getElementById("quizSetEmpty");
  const select = document.getElementById("quizSetSelect");

  tbody.innerHTML = "";
  select.innerHTML = "";
  empty.style.display = sets.length === 0 ? "block" : "none";

  sets.forEach((s) => {
    const composition = s.documents.map((doc) => `${escapeHtml(doc.document_title)} ×${doc.count}`).join(", ");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(s.name)}</td>
      <td>${composition}</td>
      <td>${s.total_questions}</td>
      <td><button class="btn btn-ghost btn-sm" data-action="edit-set">Edit</button></td>
      <td><button class="btn btn-ghost btn-sm" data-action="delete-set">Delete</button></td>
    `;
    tr.querySelector('[data-action="edit-set"]').addEventListener("click", () => editQuizSet(s));
    tr.querySelector('[data-action="delete-set"]').addEventListener("click", () => deleteQuizSet(s.quiz_set_id, s.name));
    tbody.appendChild(tr);

    const opt = document.createElement("option");
    opt.value = s.quiz_set_id;
    opt.textContent = `${s.name} (${s.total_questions} questions)`;
    select.appendChild(opt);
  });

  if (sets.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "Build a quiz set first";
    opt.disabled = true;
    select.appendChild(opt);
  }
}

function editQuizSet(set) {
  editingQuizSetId = set.quiz_set_id;
  document.getElementById("quizSetFormTitle").textContent = `Editing "${set.name}"`;
  document.getElementById("quizSetName").value = set.name;
  document.getElementById("quizSetSaveBtn").textContent = "Update quiz set";
  document.getElementById("quizSetCancelEditBtn").style.display = "inline-flex";
  renderQuizSetDocPicker(set.documents.map((d) => ({ document_id: d.document_id, count: d.count })));
  document.querySelector('.tab-btn[data-tab="quizsets"]').click();
  document.getElementById("quizSetForm").scrollIntoView({ behavior: "smooth" });
}

function resetQuizSetForm() {
  editingQuizSetId = null;
  document.getElementById("quizSetFormTitle").textContent = "Build a quiz set";
  document.getElementById("quizSetForm").reset();
  document.getElementById("quizSetSaveBtn").textContent = "Save quiz set";
  document.getElementById("quizSetCancelEditBtn").style.display = "none";
  renderQuizSetDocPicker([]);
}

document.getElementById("quizSetCancelEditBtn").addEventListener("click", resetQuizSetForm);

function deleteQuizSet(quizSetId, name) {
  showConfirmModal(
    `Delete quiz set "<strong>${escapeHtml(name)}</strong>"? This only works if no candidates are currently assigned to it.`,
    "Yes, delete",
    async () => {
      try {
        await apiRequest(`/api/hr/quiz-sets/${encodeURIComponent(quizSetId)}`, { method: "DELETE", role: "hr" });
        if (editingQuizSetId === quizSetId) resetQuizSetForm();
        loadQuizSets();
      } catch (err) {
        alert(err.message);
      }
    }
  );
}

document.getElementById("quizSetForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("quizSetError");
  const successBox = document.getElementById("quizSetSuccess");
  const btn = document.getElementById("quizSetSaveBtn");
  hideError(errorBox);
  successBox.style.display = "none";

  const name = document.getElementById("quizSetName").value.trim();
  const documents = getQuizSetSelection();

  if (!name) { showError(errorBox, "Give this quiz set a name"); return; }
  if (documents.length === 0) { showError(errorBox, "Tick at least one document"); return; }
  if (documents.some((d) => !d.count || d.count < 1)) { showError(errorBox, "Every ticked document needs a question count of at least 1"); return; }

  btn.disabled = true;
  btn.textContent = editingQuizSetId ? "Updating..." : "Saving...";
  try {
    if (editingQuizSetId) {
      await apiRequest(`/api/hr/quiz-sets/${encodeURIComponent(editingQuizSetId)}`, {
        method: "PUT", role: "hr", body: { name, documents },
      });
      successBox.textContent = `"${name}" updated.`;
    } else {
      await apiRequest("/api/hr/quiz-sets", { method: "POST", role: "hr", body: { name, documents } });
      successBox.textContent = `"${name}" saved.`;
    }
    successBox.style.display = "block";
    resetQuizSetForm();
    loadQuizSets();
  } catch (err) {
    showError(errorBox, err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = editingQuizSetId ? "Update quiz set" : "Save quiz set";
  }
});

// ---------------------------------------------------------------------------
function parseEmailList(raw) {
  if (!raw) return [];
  return Array.from(
    new Set(
      raw
        .split(/[\r\n,;\s]+/)
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean)
    )
  );
}

// Add candidates
// ---------------------------------------------------------------------------
document.getElementById("addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("addError");
  const successBox = document.getElementById("addSuccess");
  const btn = document.getElementById("addBtn");
  hideError(errorBox);
  successBox.style.display = "none";

  const emails = parseEmailList(document.getElementById("emails").value);
  const quizSetId = document.getElementById("quizSetSelect").value;

  if (emails.length === 0) { showError(errorBox, "Add at least one email"); return; }
  if (!quizSetId) { showError(errorBox, "Choose a quiz set to assign"); return; }

  btn.disabled = true;
  btn.textContent = "Adding...";
  try {
    const data = await apiRequest("/api/hr/candidates", {
      method: "POST",
      role: "hr",
      body: { emails, quiz_set_id: quizSetId },
    });
    successBox.innerHTML = `Added ${data.emails.length} candidate(s) for "${data.quiz_set_name}".
      <div class="password-inline">
        <strong>${escapeHtml(data.password)}</strong>
        <button type="button" class="btn btn-secondary btn-sm" id="addCopyBtn">Copy</button>
      </div>`;
    const m = data.mail || {};
    let mailMsg;
    if (m.configured === false) {
      mailMsg = `<div class="hint" style="margin-top:10px;color:#b9770e;"><strong>Emails were not sent</strong> - ${escapeHtml(m.error || "the mail service is not set up")} Share the password with the candidates yourself.</div>`;
    } else if ((m.failed || []).length) {
      mailMsg = `<div class="hint" style="margin-top:10px;color:#b9770e;">Email sent to ${(m.sent || []).length} candidate(s). <strong>Could not email:</strong> ${m.failed.map(escapeHtml).join(", ")}. ${escapeHtml(m.error || "")} Share the password with them yourself.</div>`;
    } else {
      mailMsg = `<div class="hint" style="margin-top:10px;color:#0d7a70;"><strong>Email sent</strong> to ${(m.sent || []).length} candidate(s) with the quiz link and their login.</div>`;
    }
    successBox.innerHTML += mailMsg;
    successBox.style.display = "block";
    wireCopyButton("addCopyBtn", data.password);
    document.getElementById("addForm").reset();
    loadCandidates();
  } catch (err) {
    showError(errorBox, err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Add and generate password";
  }
});

// ---------------------------------------------------------------------------
// Regenerate password (bulk form)
// ---------------------------------------------------------------------------
document.getElementById("regenForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("regenError");
  const successBox = document.getElementById("regenSuccess");
  const btn = document.getElementById("regenBtn");
  hideError(errorBox);
  successBox.style.display = "none";

  const emails = parseEmailList(document.getElementById("regenEmails").value);

  if (emails.length === 0) { showError(errorBox, "Add at least one email"); return; }

  btn.disabled = true;
  btn.textContent = "Regenerating...";
  try {
    const data = await apiRequest("/api/hr/candidates/regenerate-password", {
      method: "POST",
      role: "hr",
      body: { emails },
    });
    successBox.innerHTML = `New password for ${escapeHtml(data.emails.join(", "))}:
      <div class="password-inline">
        <strong>${escapeHtml(data.password)}</strong>
        <button type="button" class="btn btn-secondary btn-sm" id="regenCopyBtn">Copy</button>
      </div>${mailNote(data.mail)}`;
    successBox.style.display = "block";
    wireCopyButton("regenCopyBtn", data.password);
    document.getElementById("regenForm").reset();
    loadCandidates();
  } catch (err) {
    showError(errorBox, err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Regenerate password";
  }
});

// ---------------------------------------------------------------------------
// Candidate attempt detail (question-by-question) modal
// ---------------------------------------------------------------------------
async function viewAttempt(email) {
  const root = document.getElementById("attemptModalRoot");
  try {
    const attempts = await apiRequest(`/api/hr/candidates/${encodeURIComponent(email)}/attempts`, { role: "hr" });
    const attempt = attempts.find((a) => a.status === "completed");
    if (!attempt) {
      alert("No completed attempt found for this candidate.");
      return;
    }

    const questionsHtml = (attempt.answers_detail || []).map((item, qi) => {
      const optionsHtml = item.options.map((opt, i) => {
        let cls = "";
        if (i === item.correct_index) cls = "option-correct";
        else if (i === item.selected_option) cls = "option-wrong";
        const tag = i === item.correct_index ? '<span class="option-tag tag-correct">Correct answer</span>'
          : (i === item.selected_option ? '<span class="option-tag tag-wrong">Candidate answer</span>' : "");
        return `<div class="option-row-static ${cls}">
          <div class="option-letter">${String.fromCharCode(65 + i)}</div>
          <div>${escapeHtml(opt)}</div>
          ${tag}
        </div>`;
      }).join("");

      return `
        <div class="question-review">
          <div class="question-review-header">
            <span class="question-review-num">Q${qi + 1}</span>
            ${item.document_title ? `<span class="cat-tag">${escapeHtml(item.document_title)}</span>` : ""}
            <span class="badge ${item.is_correct ? "badge-completed" : "badge-pending"}">${item.is_correct ? "Correct" : (item.selected_option === null ? "Unattempted" : "Incorrect")}</span>
          </div>
          <div class="question-text" style="font-size:15px; margin-bottom:14px;">${escapeHtml(item.question)}</div>
          ${optionsHtml}
        </div>`;
    }).join("");

    const breakdownHtml = (attempt.score_by_document || []).length > 1
      ? `<div class="score-breakdown">
          ${attempt.score_by_document.map((b) => `<span class="score-breakdown-item"><strong>${escapeHtml(b.document_title)}:</strong> ${b.correct}/${b.total}</span>`).join("")}
        </div>`
      : "";

    root.innerHTML = `
      <div class="modal-overlay" id="attemptModalOverlay">
        <div class="modal-box">
          <div class="modal-header">
            <div>
              <h3>${escapeHtml(email)}</h3>
              <div class="hint" style="margin-top:2px;">Score: ${attempt.score} / ${attempt.total_questions} - Submitted ${formatDateTime(attempt.submitted_at)}</div>
              ${breakdownHtml}
            </div>
            <button class="btn btn-ghost btn-sm" id="attemptModalClose">Close</button>
          </div>
          ${questionsHtml}
        </div>
      </div>
    `;

    document.getElementById("attemptModalClose").addEventListener("click", closeAttemptModal);
    document.getElementById("attemptModalOverlay").addEventListener("click", (e) => {
      if (e.target.id === "attemptModalOverlay") closeAttemptModal();
    });
  } catch (err) {
    alert(err.message);
  }
}

function closeAttemptModal() {
  document.getElementById("attemptModalRoot").innerHTML = "";
}

function wireCopyButton(buttonId, text) {
  const btn = document.getElementById(buttonId);
  if (!btn) return;
  btn.addEventListener("click", () => {
    navigator.clipboard.writeText(text).then(() => {
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = "Copy"; }, 1500);
    });
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

hrDashboardReady.then((ok) => {
  if (ok) {
    loadCandidates();
    loadDocuments().then(loadQuizSets);
  }
});
