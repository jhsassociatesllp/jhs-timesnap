/* employee_exit.js - page wiring for the single-page form: tables, conditional fields, Save Draft, Submit + success popup. */
const ExUI = {
  toast(msg) {
    const t = document.getElementById('exToast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(this._t); this._t = setTimeout(() => t.classList.remove('show'), 3200);
  },
  banner(kind, msg) {
    const b = document.getElementById('exBanner');
    b.className = 'ex-alert show ' + kind; b.textContent = msg;
  },
  showErrors(list, title) {
    const box = document.getElementById('exErrors');
    box.innerHTML = '';
    const head = document.createElement('strong'); head.textContent = title || 'Please fix the following:'; box.appendChild(head);
    const ul = document.createElement('ul');
    list.forEach(m => { const li = document.createElement('li'); li.textContent = m; ul.appendChild(li); });
    box.appendChild(ul); box.classList.add('show');
    box.scrollIntoView({ behavior: 'smooth', block: 'center' });   // the box sits just above the buttons
  },
  clearErrors() { document.getElementById('exErrors').classList.remove('show'); ExValidation.clearMarks(); },
  TRACKER_URL: '/exit-management/tracker',
  /** The submitted form is never shown again: after submit (or when reopening) the employee goes to the status tracker. */
  goToTracker() { window.location.replace(this.TRACKER_URL); },
  openModal() {
    document.getElementById('exForm').style.display = 'none';       // hide the form behind the popup
    document.getElementById('exDone').style.display = '';
    const m = document.getElementById('exModal'); m.hidden = false; document.getElementById('btnModalClose').focus();
  },
  /** Closing the success popup (Close, Esc or a click outside) opens the Exit Status Tracker. */
  closeModal() {
    if (document.getElementById('exModal').hidden) return;
    document.getElementById('exModal').hidden = true;
    this.goToTracker();
  },
  busy(on) { document.querySelectorAll('#exitForm .ex-actions button').forEach(b => { b.disabled = on; }); },
};

/** Build one rating table (Good / Satisfactory / Poor radios) like the paper form. */
function renderRatingTable(tableId, list, prefix, startNumber) {
  const table = document.getElementById(tableId);
  const thead = document.createElement('thead');
  thead.innerHTML = '<tr><th>#</th><th>Question</th>' + EX.RATINGS.map(r => `<th class="c">${r}</th>`).join('') + '</tr>';
  const tbody = document.createElement('tbody');
  list.forEach(([key, label], i) => {
    const tr = document.createElement('tr'); tr.id = prefix + key;
    const n = document.createElement('td'); n.className = 'n'; n.textContent = startNumber + i;
    const q = document.createElement('td'); q.textContent = label;
    tr.append(n, q);
    EX.RATINGS.forEach(r => {
      const td = document.createElement('td'); td.className = 'c';
      const input = document.createElement('input');
      input.type = 'radio'; input.name = prefix + key; input.value = r; input.setAttribute('aria-label', `${label}: ${r}`);
      td.appendChild(input); tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
}

/** Q23: the reason box opens when the answer is No. */
function syncRecommend() {
  const no = (document.querySelector('input[name="ei_recommend_company"]:checked') || {}).value === 'No';
  document.getElementById('recommendWrap').style.display = no ? '' : 'none';
}

/** Show the employer-name box (and make Q22 required) only when "better prospect" = Yes. */
function syncProspect() {
  const yes = (document.querySelector('input[name="ei_better_prospect"]:checked') || {}).value === 'Yes';
  document.getElementById('employerWrap').style.display = yes ? '' : 'none';
}

async function saveDraft() {
  ExUI.clearErrors(); ExUI.busy(true);
  try {
    await ExDraft.save();
    ExUI.toast('Draft saved. You can continue later.');
  } catch (e) {
    ExUI.showErrors([e.message], 'Draft not saved');
    if (e.status === 409) ExUI.banner('info', e.message);
  } finally { ExUI.busy(false); }
}

/** A popup in the page instead of the browser's confirm box. Resolves true on "Yes, Submit", false on Cancel / Esc / click outside. */
function askSubmit() {
  return new Promise(resolve => {
    const box = document.getElementById('exConfirm'), ok = document.getElementById('exConfirmOk'), no = document.getElementById('exConfirmCancel');
    const finish = answer => {
      box.hidden = true;
      ok.removeEventListener('click', onOk); no.removeEventListener('click', onNo);
      box.removeEventListener('mousedown', onBack); document.removeEventListener('keydown', onKey);
      resolve(answer);
    };
    const onOk = () => finish(true), onNo = () => finish(false);
    const onBack = e => { if (e.target === box) finish(false); };
    const onKey = e => { if (e.key === 'Escape') finish(false); };
    ok.addEventListener('click', onOk); no.addEventListener('click', onNo);
    box.addEventListener('mousedown', onBack); document.addEventListener('keydown', onKey);
    box.hidden = false; ok.focus();
  });
}

async function submitForm() {
  ExUI.clearErrors();
  const data = ExDraft.collect();
  const errors = [...ExValidation.dates(data), ...ExValidation.answers(data)];
  if (errors.length) { ExUI.showErrors(errors); return; }
  if (!(await askSubmit())) return;
  ExUI.busy(true);
  try {
    await ExApi.call('/submit', 'POST', data);          // resolves only after MongoDB has saved the submission
  } catch (e) {
    if (e.status === 409 && /already submitted/i.test(e.message)) { ExUI.goToTracker(); return; }   // double click / second tab
    ExUI.showErrors(e.errors && e.errors.length ? e.errors : [e.message], 'Submission failed');
    return;
  } finally { ExUI.busy(false); }
  ExUI.openModal();                                      // success popup: only reached after a successful save
}

async function initPage() {
  if (!ExApi.requireLogin()) return;
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());

  renderRatingTable('tblManager', EX.MANAGER, 'rm_', 1);
  renderRatingTable('tblCompany', EX.COMPANY, 'rc_', 9);
  ExSignature.init();
  syncProspect(); syncRecommend();

  document.querySelectorAll('input[name="ei_better_prospect"]').forEach(r => r.addEventListener('change', syncProspect));
  document.querySelectorAll('input[name="ei_recommend_company"]').forEach(r => r.addEventListener('change', syncRecommend));
  document.getElementById('btnSaveDraft').addEventListener('click', saveDraft);
  document.getElementById('exitForm').addEventListener('submit', e => { e.preventDefault(); submitForm(); });
  document.getElementById('btnModalClose').addEventListener('click', () => ExUI.closeModal());
  document.getElementById('exModal').addEventListener('mousedown', e => { if (e.target.id === 'exModal') ExUI.closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') ExUI.closeModal(); });
  ExApi.initNav();                                   // shows the extra tabs; the page stays where the person opened it (no redirect to /manager)

  try {
    const [, draft] = await Promise.all([ExDetails.load(), ExApi.call('/draft')]);
    if (draft.status === 'submitted') { ExUI.goToTracker(); return; }   // already submitted: show the tracker, not the form
    else {
      if (draft.status === 'draft') {
        ExDraft.apply(draft.form); syncProspect(); syncRecommend();
        ExUI.banner('info', 'Your saved draft has been loaded. Continue where you left off.');
      }
      document.getElementById('exForm').style.display = '';
    }
  } catch (e) {
    document.getElementById('exLoading').innerHTML = '';
    const p = document.createElement('div'); p.className = 'ex-alert error show'; p.textContent = e.message;
    document.getElementById('exLoading').appendChild(p);
    return;
  }
  document.getElementById('exLoading').style.display = 'none';
}

initPage();
