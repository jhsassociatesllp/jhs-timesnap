/* it.js - IT Clearance dashboard for an IT approver. Who may use it is decided by the server (it_clearance_approvers + the login);
   this page lists the submitted applications. The eye icon shows one row stacked vertically; the IT Clearance button opens the form
   in a popup on this page (nothing redirects). */
if (new URLSearchParams(location.search).get('embed')) document.body.classList.add('ex-embed');   // shown inside a tab of another page
const ExITDash = {
  apps: [],
  $(id) { return document.getElementById(id); },
  el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; },
  date(d) { return d ? new Date(d + 'T00:00:00').toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—'; },
  pill(text) {
    const cls = { Approved: 'submitted', Pending: 'draft', Rejected: 'rejected', 'Not applicable': 'none', Waiting: 'none' }[text] || 'draft';
    return this.el('span', `ex-pill ${cls}`, text);
  },

  async load() {
    const err = this.$('itError'); err.classList.remove('show');
    try {
      const d = await ExApi.call('/it/dashboard');
      this.$('itLoading').style.display = 'none'; this.$('itMain').style.display = '';
      this.apps = d.applications; this.renderApps();
    } catch (e) {
      this.$('itLoading').style.display = 'none'; this.$('itMain').style.display = 'none';
      err.textContent = e.status === 403 ? 'You are not an IT manager for exit clearance.' : e.message; err.classList.add('show');
    }
  },

  /** Employee ID .. Action of one application as [label, value]; the same list feeds the table and the vertical details popup. */
  columns(a) {
    return [
      ['Employee ID', a.employee_id], ['Employee Name', a.employee_name || ''], ['Designation', a.designation || '—'],
      ['Resignation Date', this.date(a.resignation_date)], ['Last Working Date', this.date(a.last_working_date)],
      ['Reporting Manager Approval', this.pill(a.reporting_manager_status)], ['IT Clearance', this.pill(a.it_status)], ['Action', this.actionNode(a)],
    ];
  },
  actionNode(a) {
    const box = this.el('div', 'ex-actbox');
    if (a.action) {
      const b = this.el('button', 'ex-btn sm' + (a.action === 'fill' ? ' gold' : ''), a.action === 'fill' ? 'IT Clearance' : 'View'); b.type = 'button';
      b.addEventListener('click', () => { this.closeDetails(); this.openPopup(`IT Clearance - ${a.employee_name}`, `/exit-management/it-form?form=${encodeURIComponent(a.id)}`); });
      box.appendChild(b);
    } else box.appendChild(this.el('span', 'ex-muted', a.note || '—'));
    return box;
  },

  renderApps() {
    const apps = this.apps;
    this.$('itAppCount').textContent = `(${apps.length})`;
    this.$('itNoApps').style.display = apps.length ? 'none' : '';
    this.$('itAppsWrap').style.display = apps.length ? '' : 'none';
    const tb = this.$('itAppTable').querySelector('tbody'); tb.innerHTML = '';
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
    this.$('itDetailTitle').textContent = `${a.employee_name} (${a.employee_id})`;
    const box = this.$('itDetailBody'); box.innerHTML = '';
    this.columns(a).forEach(([label, v]) => {
      const f = this.el('div', 'ex-vfield'); f.appendChild(this.el('label', '', label));
      const val = this.el('div', 'ex-vval'); if (v instanceof Node) val.appendChild(v); else val.textContent = v; f.appendChild(val); box.appendChild(f);
    });
    this.$('itDetail').hidden = false;
  },
  closeDetails() { this.$('itDetail').hidden = true; },

  // ── popup: the IT Clearance form opens on this page
  openPopup(title, url) {
    if (window.parent !== window && new URLSearchParams(location.search).get('embed')) {         // inside a tab frame: the top page shows the popup (covers the screen)
      window.parent.postMessage({ exitPopup: { title, url } }, location.origin); return;
    }
    this.$('itPopupTitle').textContent = title;
    this.$('itFrame').src = url + '&embed=1';
    this.$('itPopup').hidden = false;
  },
  closePopup() { this.$('itPopup').hidden = true; this.$('itFrame').src = 'about:blank'; this.load(); },
  toast(msg) { const t = this.$('exToast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3200); },
};

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  document.getElementById('itDetailClose').addEventListener('click', () => ExITDash.closeDetails());
  document.getElementById('itDetail').addEventListener('mousedown', e => { if (e.target.id === 'itDetail') ExITDash.closeDetails(); });
  document.getElementById('itPopupClose').addEventListener('click', () => ExITDash.closePopup());
  document.getElementById('itPopup').addEventListener('mousedown', e => { if (e.target.id === 'itPopup') ExITDash.closePopup(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (!document.getElementById('itDetail').hidden) ExITDash.closeDetails(); else if (!document.getElementById('itPopup').hidden) ExITDash.closePopup();
  });
  window.addEventListener('message', e => {
    if (e.origin === location.origin && e.data && e.data.exitRefresh) {                           // the top page closed its popup
      if (e.data.done) ExITDash.toast('IT Clearance submitted. The IT stage is approved.');
      ExITDash.load(); return;
    }                       // the IT Clearance form was submitted inside the popup
    if (e.origin === location.origin && e.data && e.data.exitEmbed === 'done') { ExITDash.closePopup(); ExITDash.toast('IT Clearance submitted. The IT stage is approved.'); }
  });
  ExITDash.load();
}
