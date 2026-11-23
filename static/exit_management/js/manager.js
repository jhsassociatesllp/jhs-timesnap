/* manager.js - Reporting Manager dashboard. Who the manager is, who is in the team and which applications they may
   act on are all decided by the server from the login; this page only displays and calls the actions. */
if (new URLSearchParams(location.search).get('embed')) document.body.classList.add('ex-embed');   // shown inside a tab of another page
const ExUI = { toast(msg) { const t = document.getElementById('exToast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3200); } };

const ExManager = {
  team: [],
  apps: [],
  $(id) { return document.getElementById(id); },
  el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; },
  date(d) { return d ? new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'; },
  stamp(iso) { return iso ? new Date(iso).toLocaleString(undefined, { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'; },
  error(msg) { const b = this.$('mgError'); b.textContent = msg || ''; b.classList.toggle('show', !!msg); },

  async load() {
    this.error('');
    try {
      const d = await ExApi.call('/manager/dashboard');
      this.$('mgLoading').style.display = 'none'; this.$('mgMain').style.display = '';
      this.team = d.team; this.apps = d.applications; this.renderTeam();
    } catch (e) {
      this.$('mgLoading').style.display = 'none';
      this.$('mgMain').style.display = 'none';
      this.error(e.status === 403 ? 'You are not a Reporting Manager: no employee reports to you.' : e.message);
    }
  },

  // ── team members who filled the exit form: their details + their application (status, Approve / Reject)
  renderTeam() {
    const q = this.$('mgSearch').value.trim().toLowerCase();
    const byId = Object.fromEntries(this.team.map(t => [t.employee_id, t]));
    const all = this.apps.map(a => ({ a, t: byId[a.employee_id] || {} }));
    const rows = all.filter(({ a }) => !q || `${a.employee_id} ${a.employee_name} ${a.designation}`.toLowerCase().includes(q));
    this.$('mgTeamCount').textContent = `(${all.length} total${q ? `, ${rows.length} shown` : ''})`;
    const tb = this.$('mgTeamTable').querySelector('tbody'); tb.innerHTML = '';
    if (!rows.length) {
      const tr = document.createElement('tr'), td = this.el('td', 'ex-empty', all.length ? 'No team members match.' : 'None of your team members has filled the exit form yet.');
      td.colSpan = 12; tr.appendChild(td); tb.appendChild(tr); return;
    }
    rows.forEach(({ a, t }, i) => {
      const tr = document.createElement('tr');
      const eye = this.el('td', 'c'); const eb = this.el('button', 'ex-eye', ''); eb.type = 'button'; eb.title = 'View all details'; eb.setAttribute('aria-label', 'View all details');
      eb.innerHTML = '<i class="fas fa-eye"></i>'; eb.addEventListener('click', () => this.openDetails(a, t)); eye.appendChild(eb);
      tr.append(this.el('td', 'c', String(i + 1)), eye);
      this.columns(a, t).forEach(([, node]) => tr.appendChild(this.cell(node)));
      tb.appendChild(tr);
    });
  },

  /** The columns Employee ID .. Action of one row as [label, value]; the same list feeds the table and the vertical details popup. */
  columns(a, t) {
    return [
      ['Employee ID', a.employee_id], ['Employee Name', a.employee_name || ''], ['Designation', a.designation || '—'],
      ['Branch', t.branch || '—'], ['Joining Date', this.date(t.joining_date)], ['Resignation Date', this.date(a.resignation_date)],
      ['Last Working Date', this.date(a.last_working_date)], ['Submitted On', this.stamp(a.submitted_at)],
      ['Application Status', this.statusNode(a)], ['Action', this.actionNode(a)],
    ];
  },
  cell(node) {
    const td = this.el('td', node instanceof Node && node.classList && node.classList.contains('ex-actbox') ? 'ex-actcell' : '');
    if (node instanceof Node) td.appendChild(node); else td.textContent = node;
    return td;
  },
  statusNode(a) {
    const box = this.el('div', '');
    box.appendChild(this.statusPill(a));
    if (a.application_status === 'Rejected' && a.rejection_reason) box.appendChild(this.el('div', 'ex-twhen', 'Reason: ' + a.rejection_reason));
    if (a.unassigned) box.appendChild(this.el('div', 'ex-twhen', 'No manager on record - handled by HR'));
    return box;
  },
  actionNode(a) {
    const act = this.el('div', 'ex-actbox');
    const form = this.el('button', 'ex-btn sm', 'Employee Exit Form'); form.type = 'button';
    form.addEventListener('click', () => { this.closeDetails(); this.openPopup(`Employee Exit Form - ${a.employee_name}`, `/exit-management/exit-form-view?form=${encodeURIComponent(a.id)}`); });
    act.appendChild(form);
    if (a.can_decide || a.decision === 'approved') {            // Project Details: first click starts the Reporting Manager stage, then the form opens in the popup
      const pd = this.el('button', 'ex-btn sm gold', 'Project Details'); pd.type = 'button';
      pd.addEventListener('click', () => { this.closeDetails(); this.openProject(a, pd); });
      act.appendChild(pd);
    }
    return act;
  },

  // ── eye icon: all columns of one employee, stacked vertically (phone, tablet and laptop alike)
  openDetails(a, t) {
    this.$('mgDetailTitle').textContent = `${a.employee_name} (${a.employee_id})`;
    const box = this.$('mgDetailBody'); box.innerHTML = '';
    this.columns(a, t).forEach(([label, node]) => {
      const f = this.el('div', 'ex-vfield'); f.appendChild(this.el('label', '', label));
      const v = this.el('div', 'ex-vval'); if (node instanceof Node) v.appendChild(node); else v.textContent = node; f.appendChild(v); box.appendChild(f);
    });
    this.$('mgDetail').hidden = false;
  },
  closeDetails() { this.$('mgDetail').hidden = true; },

  // ── section 3
  statusPill(a) {
    const cls = a.application_status === 'Rejected' ? 'rejected' : (a.application_status === 'Completed' ? 'submitted' : (a.decision === 'pending' || a.can_handover ? 'draft' : 'none'));
    return this.el('span', `ex-pill ${cls}`, a.application_status.replace(/^Approved - h/, 'H'));      // "Approved - handover form pending" -> "Handover form pending"
  },

  // ── popup (the form opens on this page; nothing redirects)
  openPopup(title, url) {
    if (window.parent !== window && new URLSearchParams(location.search).get('embed')) {         // inside a tab frame: the top page shows the popup (covers the screen)
      window.parent.postMessage({ exitPopup: { title, url } }, location.origin); return;
    }
    this.$('mgPopupTitle').textContent = title;
    this.$('mgFrame').src = url + '&embed=1';
    this.$('mgPopup').hidden = false;
  },
  closePopup() { this.$('mgPopup').hidden = true; this.$('mgFrame').src = 'about:blank'; },

  async openProject(a, btn) {
    btn.disabled = true;
    try {
      if (a.can_decide) await ExApi.call(`/manager/applications/${encodeURIComponent(a.id)}/approve`, 'POST');   // creates the Project Details (handover) draft
      this.openPopup(`Project Details - ${a.employee_name}`, `/exit-management/handover?form=${encodeURIComponent(a.id)}`);
      if (a.can_decide) this.load();                                                                            // refresh the status behind the popup
    } catch (e) { this.error(e.message); this.load(); }
    finally { btn.disabled = false; }
  },

};

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  document.getElementById('mgSearch').addEventListener('input', () => ExManager.renderTeam());
  document.getElementById('mgDetailClose').addEventListener('click', () => ExManager.closeDetails());
  document.getElementById('mgDetail').addEventListener('mousedown', e => { if (e.target.id === 'mgDetail') ExManager.closeDetails(); });
  document.getElementById('mgPopupClose').addEventListener('click', () => { ExManager.closePopup(); ExManager.load(); });
  document.getElementById('mgPopup').addEventListener('mousedown', e => { if (e.target.id === 'mgPopup') { ExManager.closePopup(); ExManager.load(); } });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !document.getElementById('mgDetail').hidden) { ExManager.closeDetails(); }
    else if (e.key === 'Escape' && !document.getElementById('mgPopup').hidden) { ExManager.closePopup(); ExManager.load(); } });
  window.addEventListener('message', e => {
    if (e.origin === location.origin && e.data && e.data.exitRefresh) {                           // the top page closed its popup
      if (e.data.done) ExUI.toast('Project Details submitted. The Reporting Manager stage is approved.');
      ExManager.load(); return;
    }                       // the Project Details form was submitted inside the popup
    if (e.origin === location.origin && e.data && e.data.exitEmbed === 'done') { ExManager.closePopup(); ExUI.toast('Project Details submitted. The Reporting Manager stage is approved.'); ExManager.load(); }
  });
  ExApi.initNav();                                  // shows the IT / HR Clearance tab for people who have that access
  ExManager.load();
}
