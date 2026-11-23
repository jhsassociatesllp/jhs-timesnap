/* tracker.js - Exit Status Tracker: Reporting Manager -> IT -> HR -> Form Complete (read-only view for the employee). */
const ExTracker = {
  ICONS: { done: 'fa-check', active: 'fa-hourglass-half', waiting: 'fa-circle', rejected: 'fa-xmark', blocked: 'fa-minus' },

  fmt(iso) {
    return iso ? new Date(iso).toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  },
  el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  },

  /** One connected step: icon, label, status badge, who, timestamp. */
  step(s, previousDone) {
    const li = this.el('li', `ex-tstep ${s.state}${previousDone ? ' linked' : ''}`);
    const icon = this.el('div', 'ex-ticon'); icon.innerHTML = `<i class="fas ${this.ICONS[s.state]}"></i>`;
    const body = this.el('div', 'ex-tbody');
    body.appendChild(this.el('div', 'ex-tlabel', s.label));
    const cls = s.status === 'approved' ? 'submitted' : (s.status === 'rejected' ? 'rejected' : (s.state === 'active' ? 'draft' : 'none'));
    const text = s.status === 'approved' ? 'Approved' : (s.status === 'rejected' ? 'Rejected' : 'Pending');
    body.appendChild(this.el('span', `ex-pill ${cls}`, text));

    let who = '', when = '';
    if (s.status === 'rejected') {
      who = `Rejected by ${s.approver_name || (s.expected_approver_name || (s.key === 'reporting_manager' ? 'the Reporting Manager' : s.label))}`;
      when = s.rejected_at ? `On ${this.fmt(s.rejected_at)}` : '';
    } else if (s.state === 'blocked') {
      who = 'Not applicable - the application was rejected';
    } else if (s.status === 'approved') {
      if (s.key === 'form_complete') who = 'All approvals are complete';
      else who = `Approved by ${s.approver_name || s.approver_code || '—'}`;
      when = s.approved_at ? `On ${this.fmt(s.approved_at)}` : '';
    } else if (s.state === 'active') {
      who = s.detail || (s.key === 'reporting_manager' && s.expected_approver_name ? `Awaiting ${s.expected_approver_name}` : 'Awaiting approval');
      when = s.pending_since ? `Pending since ${this.fmt(s.pending_since)}` : '';
    } else {
      who = 'Waiting for the previous approval';
    }
    if (who) body.appendChild(this.el('div', 'ex-twho', who));
    if (when) body.appendChild(this.el('div', 'ex-twhen', when));
    if (s.status === 'rejected' && s.rejection_reason) {                  // the reason is shown to the employee
      const box = this.el('div', 'ex-treason');
      box.append(this.el('b', '', 'Reason: '), document.createTextNode(s.rejection_reason));
      body.appendChild(box);
    }
    li.append(icon, body);
    return li;
  },

  async load() {
    const show = id => document.getElementById(id);
    try {
      const t = await ExApi.call('/tracker');
      show('trLoading').style.display = 'none';
      show('trError').classList.remove('show');
      if (!t.submitted) { show('trNone').style.display = ''; show('trMain').style.display = 'none'; return; }
      show('trNone').style.display = 'none'; show('trMain').style.display = '';
      const sum = show('trSummary');
      if (!t.approval_available) {
        sum.className = 'ex-alert info show';
        sum.textContent = 'Your exit form was submitted, but it has no approval tracking. Please contact HR.';
        show('trSteps').innerHTML = ''; return;
      }
      const when = t.submitted_at ? new Date(t.submitted_at).toLocaleString() : '';
      const current = t.stages.find(s => s.state === 'active');
      sum.className = 'ex-alert show ' + (t.complete ? 'ok' : (t.rejected ? 'error' : 'info'));
      sum.textContent = t.complete
        ? `Your exit form (submitted ${when}) is fully approved. The exit process is complete.`
        : (t.rejected
          ? (() => { const r = t.stages.find(x => x.status === 'rejected'); return r && r.key === 'hr' ? `Your exit application (submitted ${when}) was rejected at the HR Clearance stage.` : r && r.key === 'it' ? `Your exit application (submitted ${when}) was rejected at the IT Clearance stage. It will not move to HR.` : `Your exit application (submitted ${when}) was rejected by the Reporting Manager. It will not move to IT or HR.`; })()
          : `Your exit form was submitted on ${when}. It is currently with: ${current ? current.label : '—'}.`);
      const ol = show('trSteps'); ol.innerHTML = '';
      t.stages.forEach((s, i) => ol.appendChild(this.step(s, i > 0 && t.stages[i - 1].state === 'done')));
      show('trUpdated').textContent = 'Last updated ' + new Date().toLocaleTimeString();
    } catch (e) {
      show('trLoading').style.display = 'none';
      const box = show('trError'); box.textContent = e.message; box.classList.add('show');
    }
  },
};

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  document.getElementById('trRefresh').addEventListener('click', () => ExTracker.load());
  ExApi.initNav().then(r => {
    if (!r) return;
    // people with IT / HR / Reporting Manager access get the tab bar, and "Back to Dashboard" goes to their own page instead of the modules list
    const back = r.is_it_manager ? '/exit-management/it-clearance' : r.is_hr_manager ? '/exit-management/hr-clearance' : r.is_reporting_manager ? '/exit-management/manager' : '';
    if (back) { document.getElementById('trBack').href = back; document.getElementById('trTabs').hidden = false; }
  });
  ExTracker.load();
  setInterval(() => { if (!document.hidden) ExTracker.load(); }, 60000);     // pick up approvals without a manual refresh
}
