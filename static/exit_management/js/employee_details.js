/* employee_details.js - login token, API helper and Section A (employee details from the database). */
const ExApi = {
  base: '/api/exit-management',
  token: localStorage.getItem('access_token') || '',
  empId: localStorage.getItem('loggedInEmployeeId') || '',

  /** Redirect to the login page when there is no session. */
  requireLogin() {
    if (!this.token) { window.location.href = '/login'; return false; }
    return true;
  },

  logout() { localStorage.clear(); sessionStorage.clear(); window.location.href = '/login'; },

  /** Show the navbar links that fit this person: "Manager Dashboard" for Reporting Managers (with the number of
      applications waiting) and "Approvals" for IT / HR approvers. Returns the roles (or null). */
  async initNav() {
    try {
      let r;
      try { r = await this.call('/approver-status'); }
      catch (e) { await new Promise(res => setTimeout(res, 800)); r = await this.call('/approver-status'); }   // one retry for a transient error
      const mgr = document.getElementById('exNavManager'), appr = document.getElementById('exNavApprovals');
      if (mgr && r.is_reporting_manager) {
        mgr.hidden = false;
        mgr.lastChild.textContent = ' Manager Dashboard' + (r.pending_applications ? ` (${r.pending_applications})` : '');
      }
      ['exTabTeam', 'exTabApps'].forEach(id => { const t = document.getElementById(id); if (t && r.is_reporting_manager) t.hidden = false; });
      { const t = document.getElementById('exTabHr'); if (t && r.is_hr_manager) t.hidden = false; }
      { const t = document.getElementById('exTabIt'); if (t && r.is_it_manager) t.hidden = false; }
      if (appr && (r.is_it || r.is_hr)) appr.hidden = false;
      return r;
    } catch (e) { return null; }                       // the links simply stay hidden
  },

  /** Shared request: adds the token, turns failures into an Error with a readable message (and .errors list). */
  async _request(path, method, body) {
    let res;
    try {
      res = await fetch(this.base + path, {
        method,
        headers: Object.assign({ Authorization: 'Bearer ' + this.token }, body ? { 'Content-Type': 'application/json' } : {}),
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new Error('Cannot reach the server. Check your connection and try again.');
    }
    if (res.ok) return res;
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (res.status === 401) { this.logout(); throw new Error('Your session has expired. Please log in again.'); }
    const d = data && data.detail;
    const err = new Error(typeof d === 'string' ? d : (d && d.message) || `Request failed (HTTP ${res.status})`);
    err.status = res.status;
    err.errors = d && Array.isArray(d.errors) ? d.errors : (Array.isArray(d) ? d.map(x => x.msg) : []);
    throw err;
  },

  /** JSON API call. */
  async call(path, method = 'GET', body = null) {
    const res = await this._request(path, method, body);
    try { return await res.json(); } catch (e) { return null; }
  },

  /** Fetch a stored file (e.g. the signature) as a Blob, with the login token. */
  async blob(path) {
    return (await this._request(path, 'GET', null)).blob();
  },

  /** Upload one file as multipart form data; XMLHttpRequest is used because fetch cannot report upload progress. */
  upload(path, file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', this.base + path);
      xhr.setRequestHeader('Authorization', 'Bearer ' + this.token);
      xhr.upload.onprogress = e => { if (e.lengthComputable && onProgress) onProgress(Math.round(e.loaded * 100 / e.total)); };
      xhr.onerror = () => reject(new Error('Cannot reach the server. Check your connection and try again.'));
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { /* not JSON */ }
        if (xhr.status === 401) { this.logout(); reject(new Error('Your session has expired. Please log in again.')); return; }
        if (xhr.status >= 200 && xhr.status < 300) { resolve(data); return; }
        const d = data && data.detail;
        const err = new Error(typeof d === 'string' ? d : `Upload failed (HTTP ${xhr.status})`);
        err.status = xhr.status; reject(err);
      };
      const form = new FormData(); form.append('file', file);
      xhr.send(form);
    });
  },
};

const ExDetails = {
  /** Fill Section A from the server. The server reads the employee from the login token. */
  async load() {
    const d = await ExApi.call('/employee-details');
    const set = (id, v) => { document.getElementById(id).value = v || ''; };
    set('f_date', d.date); set('f_name', d.employee_name); set('f_code', d.code);
    set('f_designation', d.designation); set('f_joining', d.joining_date); set('f_reporting', d.reporting_to);
    const note = document.getElementById('exMissingNote');
    if (d.missing && d.missing.length) {
      note.style.display = 'block';
      note.textContent = 'Not available in the employee records: ' + d.missing.join(', ') + '. Please inform HR if this is wrong.';
    }
    return d;
  },
};
