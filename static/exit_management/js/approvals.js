/* approvals.js - for Reporting Managers, IT and HR: list the exit forms waiting for them, review one, approve it.
   The server decides who may approve what; this page only shows what the server allows. */
const ExApprovals = {
  QUESTIONS: [
    ['would_rejoin', '17. Would you rejoin JHS any time in future?'],
    ['systems_and_processes', '18. Were you comfortable with all systems and processes used by your team? Suggest any changes that would have improved your efficiency.'],
    ['team_experience', '19. Did you feel comfortable working in your team? What would you miss the most about your department?'],
    ['resignation_reason', '20. What is the reason for your resignation?'],
    ['better_prospect', '21. Are you leaving because of a better prospect?'],
    ['new_employer', '    New employer'],
    ['pull_factors', '22. What are the pull factors of your new employer?'],
    ['recommend_company', '23. Would you recommend the company to a friend as a good organisation to work for?'],
    ['recommend_reason', '    Reason for not recommending the company'],
    ['jhs_memories', '24. List three things you would remember most about being a part of the JHS family.'],
    ['improvements', '25. List three things that would have made your life better at JHS.'],
    ['employee_benefits', '26. Do you think the employee benefits provided by the company were sufficient?'],
    ['departure_prevention', '27. What circumstances would have prevented your departure?'],
  ],
  $(id) { return document.getElementById(id); },
  el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; },
  fmt(iso) { return iso ? new Date(iso).toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'; },
  niceDate(d) { return d ? new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'; },
  error(msg) { const b = this.$('apError'); b.textContent = msg || ''; b.classList.toggle('show', !!msg); },

  async loadQueue() {
    this.error('');
    try {
      const { items } = await ExApi.call('/approvals');
      this.$('apLoading').style.display = 'none'; this.$('apMain').style.display = '';
      this.$('apCount').textContent = items.length ? `(${items.length})` : '';
      const list = this.$('apList'); list.innerHTML = '';
      if (!items.length) { list.appendChild(this.el('p', 'ex-empty', 'Nothing is waiting for your approval right now.')); return; }
      items.forEach(it => {
        const row = this.el('div', 'ex-aprow');
        const who = this.el('div', 'ex-apwho');
        who.append(this.el('strong', '', it.employee_name || it.employee_id),
                   this.el('span', '', `${it.employee_id} · ${it.designation || '—'}`),
                   this.el('span', '', `Last working date: ${this.niceDate(it.last_working_date)} · Submitted ${this.fmt(it.submitted_at)}`));
        const stage = this.el('span', 'ex-pill draft', `${it.stage_label} approval`);
        const btn = this.el('button', 'ex-btn sm gold', 'Review'); btn.type = 'button';
        btn.addEventListener('click', () => this.review(it.id));
        row.append(who, stage, btn); list.appendChild(row);
      });
    } catch (e) {
      this.$('apLoading').style.display = 'none';
      this.error(e.status === 403 ? 'You are not an approver for exit forms.' : e.message);
    }
  },

  section(title) { return this.el('h3', 'ex-apsec', title); },

  async review(id) {
    this.error('');
    let f;
    try { f = await ExApi.call('/approvals/' + encodeURIComponent(id)); }
    catch (e) { this.error(e.message); return; }
    const card = this.$('apReviewCard'); card.innerHTML = '';
    card.appendChild(this.el('h2', '', `${f.employee_name} (${f.employee_id})`));

    const det = f.employee_details || {};
    const grid = this.el('div', 'ex-grid');
    [['Code', det.code], ['Designation', det.designation], ['Joining Date', this.niceDate(det.joining_date)],
     ['Reporting to', det.reporting_to], ['Resignation Date', this.niceDate(det.resignation_date)],
     ['Last Working Date', this.niceDate(det.last_working_date)]].forEach(([k, v]) => {
      const box = this.el('div', 'ex-info'); box.append(this.el('b', '', k), document.createTextNode(v || '—')); grid.appendChild(box);
    });
    card.appendChild(grid);

    card.appendChild(this.section('Approval progress'));
    const prog = this.el('div', 'ex-approg');
    f.stages.forEach(s => prog.appendChild(this.el('span', `ex-pill ${s.status === 'approved' ? 'submitted' : (s.state === 'active' ? 'draft' : 'none')}`,
      `${s.label}: ${s.status === 'approved' ? 'Approved' : 'Pending'}`)));
    card.appendChild(prog);

    if (f.project_handover) {
      card.appendChild(this.section('Project Related Details (handover form) - completed by the Reporting Manager'));
      const t = this.el('table', 'ex-table'); t.innerHTML = '<thead><tr><th>Particulars</th><th>Option</th><th>Remarks</th><th>Signature</th></tr></thead>';
      const tb = document.createElement('tbody');
      f.project_handover.items.forEach(it => {
        const tr = document.createElement('tr'), sigTd = this.el('td', '');
        if (it.signature) {
          const a = this.el('button', 'ex-btn sm', it.signature.filename); a.type = 'button';
          a.addEventListener('click', async () => {
            try { const blob = await ExApi.blob(`/manager/applications/${encodeURIComponent(f.id)}/handover/signature/${it.key}`); window.open(URL.createObjectURL(blob), '_blank', 'noopener'); }
            catch (e) { this.error(e.message); }
          });
          sigTd.appendChild(a);
        } else sigTd.textContent = '—';
        tr.append(this.el('td', '', it.particular), this.el('td', '', it.option || '—'), this.el('td', '', it.remarks || '—'), sigTd);
        tb.appendChild(tr);
      });
      t.appendChild(tb); const w = this.el('div', 'ex-table-wrap'); w.appendChild(t); card.appendChild(w);
    }

    if (f.feedback_visible) {
      [['About Reporting Manager', EX.MANAGER, f.manager_feedback, 1], ['About JHS', EX.COMPANY, f.company_feedback, 9]].forEach(([title, list, data, start]) => {
        card.appendChild(this.section(title));
        const t = this.el('table', 'ex-table'); t.innerHTML = '<thead><tr><th>#</th><th>Question</th><th>Rating</th></tr></thead>';
        const tb = document.createElement('tbody');
        list.forEach(([key, label], i) => {
          const tr = document.createElement('tr');
          tr.append(this.el('td', 'n', start + i), this.el('td', '', label), this.el('td', '', (data || {})[key] || 'Not answered'));
          tb.appendChild(tr);
        });
        t.appendChild(tb); const w = this.el('div', 'ex-table-wrap'); w.appendChild(t); card.appendChild(w);
      });
      card.appendChild(this.section('Employee Feedback / Exit Interview'));
      const ei = f.exit_interview || {};
      this.QUESTIONS.forEach(([key, label]) => {
        if (key === 'new_employer' && ei.better_prospect !== 'Yes') return;
        if (key === 'recommend_reason' && ei.recommend_company !== 'No') return;
        const q = this.el('div', 'ex-q');
        q.appendChild(this.el('span', 'lbl', label.trim()));
        q.appendChild(this.el('div', 'ex-apans', ei[key] || 'Not answered'));
        card.appendChild(q);
      });
    } else {
      card.appendChild(this.el('div', 'ex-note', 'The feedback sections (ratings and exit interview answers) are visible to HR only.'));
    }

    const actions = this.el('div', 'ex-actions');
    const close = this.el('button', 'ex-btn', 'Close'); close.type = 'button';
    close.addEventListener('click', () => { this.$('apReview').style.display = 'none'; });
    const grp = this.el('div', 'grp'); grp.appendChild(close);
    if (f.can_approve_now) {
      const label = f.stages.find(s => s.state === 'active').label;
      const ok = this.el('button', 'ex-btn success', `Approve (${label})`); ok.type = 'button';
      ok.addEventListener('click', () => this.approve(f, label, ok));
      grp.appendChild(ok);
    } else {
      grp.appendChild(this.el('span', 'ex-track-note', 'It is not your turn to approve this form.'));
    }
    actions.append(document.createElement('span'), grp); card.appendChild(actions);
    this.$('apReview').style.display = '';
    this.$('apReview').scrollIntoView({ behavior: 'smooth', block: 'start' });
  },

  async approve(f, label, btn) {
    if (!confirm(`Approve the ${label} stage of ${f.employee_name}'s exit form?`)) return;
    btn.disabled = true;
    try {
      const r = await ExApi.call(`/approvals/${encodeURIComponent(f.id)}/approve`, 'POST');
      ExUI.toast(r.complete ? 'Approved. The exit form is now complete.' : 'Approved. It moves to the next stage.');
      this.$('apReview').style.display = 'none';
      await this.loadQueue();
    } catch (e) { this.error(e.message); btn.disabled = false; }
  },
};

/* the shared toast helper used by other pages of this module */
const ExUI = { toast(msg) { const t = document.getElementById('exToast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3200); } };

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  document.getElementById('apRefresh').addEventListener('click', () => ExApprovals.loadQueue());
  ExApprovals.loadQueue();
}
