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
// Candidate table + stats
// ---------------------------------------------------------------------------
async function loadCandidates() {
  const rows = await apiRequest("/api/hr/candidates", { role: "hr" });
  const tbody = document.getElementById("candidateTableBody");
  const empty = document.getElementById("candidateEmpty");
  tbody.innerHTML = "";

  if (rows.length === 0) {
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
  }

  let completed = 0, inProgress = 0, scoreSum = 0, scoreCount = 0;

  rows.forEach((r) => {
    if (r.status === "completed") { completed++; scoreSum += r.score; scoreCount++; }
    if (r.status === "in_progress") inProgress++;

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
      <td>${escapeHtml(r.document_title || "-")}</td>
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
    const res = await fetch(`${API_BASE}/api/hr/candidates/export.${format}`, {
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
        showPasswordModal(email, data.password);
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

function showPasswordModal(email, password) {
  const root = document.getElementById("attemptModalRoot");
  root.innerHTML = `
    <div class="modal-overlay" id="passwordModalOverlay">
      <div class="modal-box" style="max-width:420px;">
        <div class="modal-header">
          <h3>New password generated</h3>
          <button class="btn btn-ghost btn-sm" id="passwordModalClose">Close</button>
        </div>
        <p class="hint" style="margin-bottom:14px;">For <strong>${escapeHtml(email)}</strong>. Their old password stopped working - share this with them directly.</p>
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
async function loadDocuments() {
  const docs = await apiRequest("/api/hr/documents", { role: "hr" });
  const tbody = document.getElementById("documentTableBody");
  const empty = document.getElementById("documentEmpty");
  const select = document.getElementById("docSelect");

  tbody.innerHTML = "";
  select.innerHTML = "";
  empty.style.display = docs.length === 0 ? "block" : "none";

  docs.forEach((d) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(d.title)}</td>
      <td>${escapeHtml(d.filename)}</td>
      <td>${formatDateTime(d.uploaded_at)}</td>
      <td><button class="btn btn-ghost btn-sm" data-action="delete-doc">Delete</button></td>
    `;
    tr.querySelector('[data-action="delete-doc"]').addEventListener("click", () => deleteDocument(d.document_id, d.title));
    tbody.appendChild(tr);

    const opt = document.createElement("option");
    opt.value = d.document_id;
    opt.textContent = d.title;
    select.appendChild(opt);
  });

  if (docs.length === 0) {
    const opt = document.createElement("option");
    opt.textContent = "Upload a document first";
    opt.disabled = true;
    select.appendChild(opt);
  }
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
// Add candidates
// ---------------------------------------------------------------------------
document.getElementById("addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errorBox = document.getElementById("addError");
  const successBox = document.getElementById("addSuccess");
  const btn = document.getElementById("addBtn");
  hideError(errorBox);
  successBox.style.display = "none";

  const emails = document.getElementById("emails").value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const documentId = document.getElementById("docSelect").value;

  if (emails.length === 0) { showError(errorBox, "Add at least one email"); return; }
  if (!documentId) { showError(errorBox, "Choose a document to assign"); return; }

  btn.disabled = true;
  btn.textContent = "Adding...";
  try {
    const data = await apiRequest("/api/hr/candidates", {
      method: "POST",
      role: "hr",
      body: { emails, document_id: documentId },
    });
    successBox.innerHTML = `Added ${data.emails.length} candidate(s) for "${data.document_title}".
      <div class="password-inline">
        <strong>${escapeHtml(data.password)}</strong>
        <button type="button" class="btn btn-secondary btn-sm" id="addCopyBtn">Copy</button>
      </div>`;
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

  const emails = document.getElementById("regenEmails").value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

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
      </div>`;
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
            <span class="badge ${item.is_correct ? "badge-completed" : "badge-pending"}">${item.is_correct ? "Correct" : (item.selected_option === null ? "Unattempted" : "Incorrect")}</span>
          </div>
          <div class="question-text" style="font-size:15px; margin-bottom:14px;">${escapeHtml(item.question)}</div>
          ${optionsHtml}
        </div>`;
    }).join("");

    root.innerHTML = `
      <div class="modal-overlay" id="attemptModalOverlay">
        <div class="modal-box">
          <div class="modal-header">
            <div>
              <h3>${escapeHtml(email)}</h3>
              <div class="hint" style="margin-top:2px;">Score: ${attempt.score} / ${attempt.total_questions} - Submitted ${formatDateTime(attempt.submitted_at)}</div>
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
    loadDocuments();
  }
});
