/* hr.js - HR Clearance dashboard for an HR approver. Who may use it is decided by the server (hr_clearance_approvers + the login);
   this page lists the submitted applications. The eye icon shows one row stacked vertically; the IT Clearance button opens the form
   in a popup on this page (nothing redirects). */
if (new URLSearchParams(location.search).get('embed')) document.body.classList.add('ex-embed');   // shown inside a tab of another page
const ExHRDash = {
  apps: [],
  $(id) { return document.getElementById(id); },
  el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; },
  date(d) { return d ? new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'; },
  pill(text) {
    const cls = { Approved: 'submitted', Pending: 'draft', Rejected: 'rejected', 'Not applicable': 'none', Waiting: 'none' }[text] || 'draft';
    return this.el('span', `ex-pill ${cls}`, text);
  },

  async load() {
    const err = this.$('hrError'); err.classList.remove('show');
    try {
      const d = await ExApi.call('/hr/dashboard');
      this.$('hrLoading').style.display = 'none'; this.$('hrMain').style.display = '';
      this.apps = d.applications; this.renderApps();
    } catch (e) {
      this.$('hrLoading').style.display = 'none'; this.$('hrMain').style.display = 'none';
      err.textContent = e.status === 403 ? 'You are not an HR manager for exit clearance.' : e.message; err.classList.add('show');
    }
  },

  /** Employee ID .. Action of one application as [label, value]; the same list feeds the table and the vertical details popup. */
  columns(a) {
    return [
      ['Employee ID', a.employee_id], ['Employee Name', a.employee_name || ''], ['Designation', a.designation || '—'],
      ['Resignation Date', this.date(a.resignation_date)], ['Last Working Date', this.date(a.last_working_date)],
      ['Reporting Manager Approval', this.pill(a.reporting_manager_status)], ['IT Clearance', this.pill(a.it_status)],
      ['HR Clearance', this.pill(a.hr_status)], ['Action', this.actionNode(a)],
    ];
  },
  actionNode(a) {
    const box = this.el('div', 'ex-actbox');
    const btn = (label, cls, title, url) => {
      const b = this.el('button', 'ex-btn sm' + cls, label); b.type = 'button';
      b.addEventListener('click', () => { this.closeDetails(); this.openPopup(`${title} - ${a.employee_name}`, url); });
      box.appendChild(b);
    };
    const id = encodeURIComponent(a.id);
    btn('Employee Exit Form', '', 'Employee Exit Form', `/exit-management/exit-form-view?form=${id}&scope=hr`);              // what the employee filled in (read-only)
    if (a.reporting_manager_status === 'Approved') btn('Project Details', '', 'Project Details', `/exit-management/handover?form=${id}&as=hr`);   // the Reporting Manager's handover form (read-only)
    if (a.it_status === 'Approved') btn('IT Clearance', '', 'IT Clearance', `/exit-management/it-form?form=${id}&as=hr`);   // the completed IT Clearance (read-only)
    if (a.action) btn('HR Clearance', a.action === 'fill' ? ' gold' : '', 'HR Clearance', `/exit-management/hr-form?form=${id}`);   // fill (or view once completed)
    if (a.stage === 'complete') {                                   // the exit process is complete: the same PDF the employee gets
      const pdf = this.el('button', 'ex-btn sm gold', ''); pdf.type = 'button'; pdf.innerHTML = '<i class="fas fa-file-pdf"></i> Export PDF';
      pdf.addEventListener('click', () => this.exportPdf(a, pdf)); box.appendChild(pdf);
    }
    if (!a.action) box.appendChild(this.el('div', 'ex-muted', a.note || ''));
    return box;
  },

  renderApps() {
    const apps = this.apps;
    this.$('hrAppCount').textContent = `(${apps.length})`;
    this.$('hrNoApps').style.display = apps.length ? 'none' : '';
    this.$('hrAppsWrap').style.display = apps.length ? '' : 'none';
    const tb = this.$('hrAppTable').querySelector('tbody'); tb.innerHTML = '';
    apps.forEach((a, i) => {
      const tr = document.createElement('tr');
      const eye = this.el('td', 'c'); const eb = this.el('button', 'ex-eye', ''); eb.type = 'button'; eb.title = 'View all details'; eb.setAttribute('aria-label', 'View all details');
      eb.innerHTML = '<i class="fas fa-eye"></i>'; eb.addEventListener('click', () => this.openDetails(a)); eye.appendChild(eb);
      tr.append(this.el('td', 'c', String(i + 1)), eye);
      this.columns(a).forEach(([, v]) => { const td = this.el('td', v instanceof Node && v.classList.contains('ex-actbox') ? 'ex-actcell' : ''); if (v instanceof Node) td.appendChild(v); else td.textContent = v; tr.appendChild(td); });
      tb.appendChild(tr);
    });
  },

  // ── eye icon: every column of one application stacked vertically (phone, tablet and laptop alike)
  openDetails(a) {
    this.$('hrDetailTitle').textContent = `${a.employee_name} (${a.employee_id})`;
    const box = this.$('hrDetailBody'); box.innerHTML = '';
    this.columns(a).forEach(([label, v]) => {
      const f = this.el('div', 'ex-vfield'); f.appendChild(this.el('label', '', label));
      const val = this.el('div', 'ex-vval'); if (v instanceof Node) val.appendChild(v); else val.textContent = v; f.appendChild(val); box.appendChild(f);
    });
    this.$('hrDetail').hidden = false;
  },
  closeDetails() { this.$('hrDetail').hidden = true; },

  /** Download the same exit-form PDF the employee gets (only offered once the exit process is complete). */
  async exportPdf(a, btn) {
    btn.disabled = true;
    try {
      const blob = await ExApi.blob(`/hr/applications/${encodeURIComponent(a.id)}/export-pdf`);
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `Employee_Exit_Form_${a.employee_id}.pdf`;
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 4000);
    } catch (e) { this.toast(e.message); }
    finally { btn.disabled = false; }
  },

  // ── popup: the HR Clearance form opens on this page
  openPopup(title, url) {
    if (window.parent !== window && new URLSearchParams(location.search).get('embed')) {         // inside a tab frame: the top page shows the popup (covers the screen)
      window.parent.postMessage({ exitPopup: { title, url } }, location.origin); return;
    }
    this.$('hrPopupTitle').textContent = title;
    this.$('hrFrame').src = url + '&embed=1';
    this.$('hrPopup').hidden = false;
  },
  closePopup() { this.$('hrPopup').hidden = true; this.$('hrFrame').src = 'about:blank'; this.load(); },
  toast(msg) { const t = this.$('exToast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3200); },
};

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  document.getElementById('hrDetailClose').addEventListener('click', () => ExHRDash.closeDetails());
  document.getElementById('hrDetail').addEventListener('mousedown', e => { if (e.target.id === 'hrDetail') ExHRDash.closeDetails(); });
  document.getElementById('hrPopupClose').addEventListener('click', () => ExHRDash.closePopup());
  document.getElementById('hrPopup').addEventListener('mousedown', e => { if (e.target.id === 'hrPopup') ExHRDash.closePopup(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!document.getElementById('hrDetail').hidden) ExHRDash.closeDetails(); else if (!document.getElementById('hrPopup').hidden) ExHRDash.closePopup();
  });
  window.addEventListener('message', e => {
    if (e.origin === location.origin && e.data && e.data.exitRefresh) {                           // the top page closed its popup
      if (e.data.done) ExHRDash.toast('HR Clearance submitted. The HR stage is approved and the exit process is complete.');
      ExHRDash.load(); return;
    }                       // the IT Clearance form was submitted inside the popup
    if (e.origin === location.origin && e.data && e.data.exitEmbed === 'done') { ExHRDash.closePopup(); ExHRDash.toast('HR Clearance submitted. The HR stage is approved and the exit process is complete.'); }
  });
  ExApi.initNav();                                  // shows My Team Member Details only for Reporting Managers
  ExHRDash.load();
}
