/* exit_view.js - read-only view of an employee's filled Exit Form for their Reporting Manager.
   The server only answers for the employee's own Reporting Manager; this page just displays what comes back. */
if (new URLSearchParams(location.search).get('embed')) document.body.classList.add('ex-embed');   // shown inside the manager page's popup
const ExView = {
  QUESTIONS: [
    ['would_rejoin', '17. Would you rejoin JHS any time in future?'],
    ['systems_and_processes', '18. Were you comfortable with all systems and processes used by your team? Suggest any changes that would have improved your efficiency.'],
    ['team_experience', '19. Did you feel comfortable working in your team? What would you miss the most about your department?'],
    ['resignation_reason', '20. What is the reason for your resignation?'],
    ['better_prospect', '21. Are you leaving because of a better prospect? If yes, would you like to mention the name of your new employer?'],
    ['new_employer', 'New employer'],
    ['pull_factors', '22. What are the pull factors of your new employer?'],
    ['recommend_company', '23. Would you recommend the company to a friend as a good organisation to work for?'],
    ['recommend_reason', 'Reason for not recommending the company'],
    ['jhs_memories', '24. List three things you would remember most about being a part of the JHS family.'],
    ['improvements', '25. List three things that would have made your life better at JHS.'],
    ['employee_benefits', '26. Do you think the employee benefits provided by the company were sufficient? (If not, do you have any suggestions?)'],
    ['departure_prevention', '27. What circumstances would have prevented your departure?'],
  ],
  formId: new URLSearchParams(location.search).get('form') || '',
  $(id) { return document.getElementById(id); },
  el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; },
  date(d) { return d ? new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'; },
  scope: new URLSearchParams(location.search).get('scope') === 'hr' ? '/hr' : '/manager',          // who is reading: the HR manager or the Reporting Manager
  base() { return `${this.scope}/applications/${encodeURIComponent(this.formId)}/exit-form`; },

  async load() {
    if (!this.formId) { this.fatal('No exit application was selected. Please open it from My Team Member Details.'); return; }
    try {
      const f = await ExApi.call(this.base());
      this.$('evLoading').style.display = 'none'; this.$('evMain').style.display = '';
      const det = f.employee_details || {};
      const box = this.$('evDetails'); box.innerHTML = '';
      [['Full Name', f.employee_name], ['Code', f.employee_id], ['Designation', det.designation || '—'], ['Joining Date', this.date(det.joining_date)],
       ['Reporting To', det.reporting_to || '—'], ['Resignation Date', this.date(det.resignation_date)], ['Last Working Date', this.date(det.last_working_date)]].forEach(([l, v]) => {
        const i = this.el('div', 'ex-info'); i.appendChild(this.el('b', '', l)); i.appendChild(this.el('span', '', v || '—')); box.appendChild(i);
      });
      this.ratings('evMgr', EX.MANAGER, f.manager_feedback || {});
      this.ratings('evCmp', EX.COMPANY, f.company_feedback || {});
      const ei = f.exit_interview || {}, qa = this.$('evQa'); qa.innerHTML = '';
      this.QUESTIONS.forEach(([k, q]) => {
        if ((k === 'new_employer' || k === 'pull_factors') && ei.better_prospect !== 'Yes') return;
        if (k === 'recommend_reason' && ei.recommend_company !== 'No') return;
        const wrap = this.el('div', 'ex-q'); wrap.appendChild(this.el('span', 'lbl', q));
        wrap.appendChild(this.el('div', 'ex-ans', ei[k] || '—')); qa.appendChild(wrap);
      });
      const sig = this.$('evSig'); sig.innerHTML = '';
      if (f.signature) {
        sig.appendChild(this.el('span', '', `${f.signature.filename}  `));
        const v = this.el('button', 'ex-btn sm', 'View'); v.type = 'button'; v.addEventListener('click', () => this.viewSig());
        sig.appendChild(v);
      } else sig.textContent = 'No signature uploaded.';
    } catch (e) { this.fatal(e.message); }
  },

  ratings(tableId, list, data) {
    const tb = this.$(tableId).querySelector('tbody'); tb.innerHTML = '';
    list.forEach(([k, label]) => { const tr = document.createElement('tr'); tr.append(this.el('td', '', label), this.el('td', '', data[k] || '—')); tb.appendChild(tr); });
  },

  async viewSig() {
    try { const b = await ExApi.blob(`${this.base()}/signature`); window.open(URL.createObjectURL(b), '_blank', 'noopener'); }
    catch (e) { ExUI.toast(e.message); }
  },

  fatal(msg) { this.$('evLoading').style.display = 'none'; const b = this.$('evFatal'); b.textContent = msg; b.classList.add('show'); },
};
const ExUI = { toast(msg) { const t = document.getElementById('exToast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3200); } };

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  ExView.load();
}
