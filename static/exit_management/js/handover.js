/* handover.js - Project Related Details (handover) form for the Reporting Manager.
   Four rows, each with its OWN Yes/No, remarks and an optional signature (one file is chosen at the bottom; ticking a row's
   'Add signature' box uploads it for that row to GridFS, unticking removes it, until the form is submitted). The Reporting Manager stage only completes on Submit. */
if (new URLSearchParams(location.search).get('embed')) document.body.classList.add('ex-embed');   // shown inside the manager page's popup
const ExUI = { toast(msg) { const t = document.getElementById('exToast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 3200); } };

const ExHandover = {
  MAX: 5 * 1024 * 1024,
  EXT: ['pdf', 'jpg', 'jpeg', 'png'],
  formId: new URLSearchParams(location.search).get('form') || '',
  rows: {},                 // key -> {sig: metadata|null, busy: bool, previewUrl: string|null}
  editable: true,
  $(id) { return document.getElementById(id); },
  el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined && text !== null) e.textContent = text; return e; },
  asHr: new URLSearchParams(location.search).get('as') === 'hr',                                  // the HR manager looking at the form (read-only)
  base() { return this.asHr ? `/hr/applications/${encodeURIComponent(this.formId)}/handover` : `/manager/applications/${encodeURIComponent(this.formId)}/handover`; },
  fmtSize(n) { return n >= 1048576 ? (n / 1048576).toFixed(2) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; },

  async load() {
    if (!this.formId) { this.fatal('No exit application was selected. Please open the form from the dashboard.'); return; }
    try {
      const h = await ExApi.call(this.base());
      this.$('hoLoading').style.display = 'none'; this.$('hoForm').style.display = '';
      this.editable = h.editable;
      this.renderRows(h.items); this.syncCard(); this.restorePool(); this.renderSigView(h.items);
      if (!h.editable) this.$('hoSigCard').style.display = 'none';
      if (!h.editable) {
        this.$('hoActions').querySelector('.grp').style.display = 'none';
        this.banner('ok', 'This handover form has been submitted. The Reporting Manager stage is approved.');
      }
    } catch (e) { this.fatal(e.status === 409 || e.status === 403 || e.status === 404 ? e.message : e.message); }
  },

  /** Read-only view (submitted form, or HR reading it): the Reporting Manager's signature as "file name + View", like the Employee Signature of the exit form. */
  renderSigView(items) {
    const withSig = items.filter(i => i.signature);
    if (this.editable || !withSig.length) return;
    const first = withSig[0];
    this.$('hoSigView').style.display = '';
    const box = this.$('hoSigPreview'); box.innerHTML = '';
    box.appendChild(this.el('span', '', first.signature.filename + '  '));
    const v = this.el('button', 'ex-btn sm', 'View'); v.type = 'button'; v.addEventListener('click', () => this.view(first.key));
    box.appendChild(v);
  },

  fatal(msg) { this.$('hoLoading').style.display = 'none'; const b = this.$('hoFatal'); b.textContent = msg; b.classList.add('show'); },
  banner(kind, msg) { const b = this.$('hoBanner'); b.className = 'ex-alert show ' + kind; b.textContent = msg; },

  renderRows(items) {
    const tb = this.$('hoTable').querySelector('tbody'); tb.innerHTML = '';
    items.forEach(it => {
      this.rows[it.key] = { sig: it.signature, busy: false, previewUrl: null };
      const tr = document.createElement('tr'); tr.id = 'row_' + it.key;
      tr.appendChild(this.el('td', 'ex-ho-part', it.particular));

      const opt = this.el('td', 'c ex-ho-opt');
      ['Yes', 'No'].forEach(v => {
        const lab = this.el('label', ''), r = document.createElement('input');
        r.type = 'radio'; r.name = 'opt_' + it.key; r.value = v; r.checked = it.option === v; r.disabled = !this.editable;
        lab.append(r, document.createTextNode(' ' + v)); opt.appendChild(lab);
      });
      tr.appendChild(opt);

      const rem = this.el('td', ''), inp = document.createElement('input');
      inp.type = 'text'; inp.id = 'rem_' + it.key; inp.maxLength = 1000; inp.value = it.remarks || ''; inp.placeholder = 'Remarks'; inp.readOnly = !this.editable;
      inp.className = 'ex-ho-input'; inp.setAttribute('aria-label', 'Remarks: ' + it.particular); rem.appendChild(inp); tr.appendChild(rem);

      tr.appendChild(this.sigCell(it.key));
      tb.appendChild(tr);
      if (it.signature) this.showFile(it.key);
    });
  },

  // ── one signature cell (its own file input, preview, progress and Remove button)
  sigCell(key) {
    const td = this.el('td', 'ex-ho-sig'), box = this.el('div', 'ex-ho-sigbox'); box.id = 'sig_' + key;
    const lab = this.el('label', 'ex-ho-tick'), cb = document.createElement('input');
    cb.type = 'checkbox'; cb.id = 'tick_' + key; cb.disabled = !this.editable;
    cb.setAttribute('aria-label', 'Add the signature to this row');
    cb.addEventListener('change', () => this.toggle(key, cb.checked));
    lab.append(cb, document.createTextNode(' Add signature'));
    const info = this.el('div', 'ex-ho-file'); info.id = 'info_' + key; info.hidden = true;
    const thumb = this.el('div', 'ex-file-thumb'); thumb.id = 'thumb_' + key;
    const body = this.el('div', 'ex-file-body');
    body.append(this.el('div', 'ex-file-name', ''), this.el('div', 'ex-file-meta', ''), this.el('div', 'ex-file-status', ''));
    const prog = this.el('div', 'ex-progress'); prog.hidden = true; prog.appendChild(this.el('div', 'bar')); body.appendChild(prog);
    const acts = this.el('div', 'ex-file-actions');
    const view = this.el('button', 'ex-btn sm', 'View'); view.type = 'button'; view.addEventListener('click', () => this.view(key));
    acts.append(view); info.append(thumb, body, acts);
    const err = this.el('div', 'ex-ho-err'); err.id = 'err_' + key;
    box.append(lab, info, err);
    td.appendChild(box); return td;
  },

  rowEls(key) {
    const info = this.$('info_' + key);
    return { info, name: info.querySelector('.ex-file-name'), meta: info.querySelector('.ex-file-meta'), status: info.querySelector('.ex-file-status'),
             prog: info.querySelector('.ex-progress'), bar: info.querySelector('.bar'), thumb: this.$('thumb_' + key),
             err: this.$('err_' + key), box: this.$('sig_' + key), row: this.$('row_' + key) };
  },
  rowError(key, msg) { const e = this.rowEls(key).err; e.textContent = msg || ''; e.classList.toggle('show', !!msg); },

  /** Show whether a row carries a signature: only its checkbox (no preview). */
  async showFile(key) {
    const r = this.rows[key], el = this.rowEls(key);
    el.row.classList.remove('row-error');
    const cb = this.$('tick_' + key); if (cb) cb.checked = !!r.sig;
    this.syncCard();
  },

  validateFile(f) {
    const ext = (f.name.split('.').pop() || '').toLowerCase();
    if (!this.EXT.includes(ext)) return 'Unsupported file type. Please upload a PDF, JPG, JPEG or PNG file.';
    if (f.size === 0) return 'The selected file is empty.';
    if (f.size > this.MAX) return `File is too large (${(Math.ceil(f.size / 10485.76) / 100).toFixed(2)} MB). Maximum size is 5 MB.`;
    return '';
  },

  async select(key, file) {
    const r = this.rows[key], el = this.rowEls(key);
    if (r.busy || !this.editable) return;
    this.rowError(key, '');
    const err = this.validateFile(file);
    if (err) { this.rowError(key, err); return; }
    const pending = null;
    r.busy = true; el.prog.hidden = false; el.bar.style.width = '0%';
    el.name.textContent = file.name; el.meta.textContent = `${(file.name.split('.').pop() || '').toUpperCase()} · ${this.fmtSize(file.size)}`; el.status.textContent = 'Uploading…';
    el.info.querySelectorAll('button').forEach(b => { b.hidden = true; });
    try {
      const meta = await ExApi.upload(`${this.base()}/signature/${key}`, file, p => { el.bar.style.width = p + '%'; });
      if (r.previewUrl && r.previewUrl !== pending) URL.revokeObjectURL(r.previewUrl);
      r.sig = meta; r.previewUrl = pending;
      el.info.querySelectorAll('button').forEach(b => { b.hidden = false; });
      await this.showFile(key, pending);
    } catch (e) {
      if (pending) URL.revokeObjectURL(pending);
      this.rowError(key, e.message);
      el.info.querySelectorAll('button').forEach(b => { b.hidden = false; });
      await this.showFile(key);                                    // the previously saved file (if any) is still there
    } finally { r.busy = false; el.prog.hidden = true; }
  },

  async view(key) {
    try { const b = await ExApi.blob(`${this.base()}/signature/${key}`); window.open(URL.createObjectURL(b), '_blank', 'noopener'); }
    catch (e) { this.rowError(key, e.message); }
  },

  /** The signature card at the bottom picks ONE file (kept in memory as `pool`). Ticking a row's box uploads that file for
      the row (its own GridFS copy); unticking removes it again. */
  pool: null,
  anySig() { return Object.values(this.rows).some(r => r.sig); },
  syncCard() {
    const c = this.$('hoSigStatus'); if (!c) return;
    const f = this.pool;
    this.$('hoSigPick').innerHTML = f ? '<i class="fas fa-rotate"></i> Replace signature' : '<i class="fas fa-upload"></i> Upload signature';
    this.$('hoSigRemove').hidden = !this.editable || !(f || this.anySig());
    c.textContent = f ? `\u2713 ${f.name} (${this.fmtSize(f.size)}) - tick "Add signature" in each row that needs it.` : 'No signature uploaded yet.';
  },
  async setPool(file) {
    if (!this.editable || Object.values(this.rows).some(r => r.busy)) return;
    const err = this.validateFile(file), box = this.$('hoSigErr');
    box.textContent = err; box.classList.toggle('show', !!err);
    if (err) return;
    this.pool = file; this.syncCard();
    for (const key of Object.keys(this.rows)) if (this.rows[key].sig) await this.select(key, file);   // ticked rows get the new file
    this.syncCard();
  },
  async toggle(key, on) {
    const r = this.rows[key], cb = this.$('tick_' + key), box = this.$('hoSigErr');
    box.classList.remove('show');
    if (r.busy) { cb.checked = !on; return; }
    if (on) {
      if (!this.pool) { cb.checked = false; box.textContent = 'Upload a signature in the "Upload a Signature" card first, then tick the rows.'; box.classList.add('show'); return; }
      await this.select(key, this.pool);
    } else if (r.sig) {
      this.rowError(key, '');
      try {
        await ExApi.call(`${this.base()}/signature/${key}`, 'DELETE');
        if (r.previewUrl) URL.revokeObjectURL(r.previewUrl);
        r.sig = null; r.previewUrl = null;
      } catch (e) { this.rowError(key, e.message); }
      await this.showFile(key);
    }
    cb.checked = !!r.sig;
  },
  async removeAll() {
    if (Object.values(this.rows).some(r => r.busy) || !(this.pool || this.anySig()) || !confirm('Remove the uploaded signature from the page and from every row?')) return;
    for (const key of Object.keys(this.rows)) {
      const r = this.rows[key]; if (!r.sig) continue;
      try {
        await ExApi.call(`${this.base()}/signature/${key}`, 'DELETE');
        if (r.previewUrl) URL.revokeObjectURL(r.previewUrl);
        r.sig = null; r.previewUrl = null; await this.showFile(key);
      } catch (e) { this.rowError(key, e.message); }
    }
    this.pool = null; this.syncCard(); ExUI.toast('Signature removed.');
  },
  /** After a reload: rebuild the in-memory file from a row that already has one, so more rows can be ticked. */
  async restorePool() {
    const key = Object.keys(this.rows).find(k => this.rows[k].sig);
    if (!key || this.pool) return;
    try { const sg = this.rows[key].sig, blob = await ExApi.blob(`${this.base()}/signature/${key}`); this.pool = new File([blob], sg.filename, { type: sg.content_type }); this.syncCard(); } catch (e) { /* ticking just asks for a new upload */ }
  },

  // ── Save Draft / Submit
  collect() {
    return { items: Object.keys(this.rows).map(key => {
      const c = document.querySelector(`input[name="opt_${key}"]:checked`);
      return { key, option: c ? c.value : null, remarks: this.$('rem_' + key).value.trim() };
    }) };
  },
  showErrors(list, title) {
    const box = this.$('hoErrors'); box.innerHTML = '';
    box.appendChild(this.el('strong', '', title || 'Please fix the following:'));
    const ul = document.createElement('ul'); list.forEach(m => ul.appendChild(this.el('li', '', m))); box.appendChild(ul);
    box.classList.add('show'); box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  },
  clearErrors() { this.$('hoErrors').classList.remove('show'); document.querySelectorAll('#hoTable .row-error').forEach(e => e.classList.remove('row-error')); },
  busy(on) { this.$('hoActions').querySelectorAll('button').forEach(b => { b.disabled = on; }); },

  async saveDraft() {
    this.clearErrors(); this.busy(true);
    try { await ExApi.call(`${this.base()}/draft`, 'POST', this.collect()); ExUI.toast('Draft saved.'); }
    catch (e) { this.showErrors([e.message], 'Draft not saved'); }
    finally { this.busy(false); }
  },

  /** A popup in the page instead of the browser's confirm box. Resolves true on "Approve & Submit", false on Cancel / Esc / click outside. */
  askSubmit() {
    return new Promise(resolve => {
      const box = this.$('hoConfirm'), ok = this.$('hoConfirmOk'), no = this.$('hoConfirmCancel');
      const finish = answer => {
        box.hidden = true;
        ok.removeEventListener('click', onOk); no.removeEventListener('click', onNo);
        box.removeEventListener('mousedown', onBack); document.removeEventListener('keydown', onKey);
        resolve(answer);
      };
      const onOk = () => finish(true), onNo = () => finish(false);
      const onBack = e => { if (e.target === box) finish(false); };
      const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); finish(false); } };
      ok.addEventListener('click', onOk); no.addEventListener('click', onNo);
      box.addEventListener('mousedown', onBack); document.addEventListener('keydown', onKey);
      box.hidden = false; ok.focus();
    });
  },

  /** Popup (not the browser's alert): a signature is required for every row answered Yes. Resolves when the person presses OK. */
  alertSignature(names) {
    return new Promise(resolve => {
      const box = this.$('hoAlert'), list = this.$('hoAlertList'), ok = this.$('hoAlertOk');
      list.innerHTML = ''; names.forEach(n => list.appendChild(this.el('li', '', n)));
      const finish = () => { box.hidden = true; ok.removeEventListener('click', finish); document.removeEventListener('keydown', onKey); box.removeEventListener('mousedown', onBack); resolve(); };
      const onKey = e => { if (e.key === 'Escape' || e.key === 'Enter') { e.stopPropagation(); finish(); } };
      const onBack = e => { if (e.target === box) finish(); };
      ok.addEventListener('click', finish); document.addEventListener('keydown', onKey); box.addEventListener('mousedown', onBack);
      box.hidden = false; ok.focus();
    });
  },

  async submit() {
    this.clearErrors();
    const data = this.collect(), labels = {};
    document.querySelectorAll('#hoTable tbody tr').forEach(tr => { labels[tr.id.slice(4)] = tr.querySelector('.ex-ho-part').textContent; });
    const errors = [];
    data.items.forEach(it => {
      const row = this.$('row_' + it.key);
      if (!it.option) { errors.push(`'${labels[it.key]}': choose Yes or No`); row.classList.add('row-error'); }
      if (this.rows[it.key].busy) { errors.push(`'${labels[it.key]}': wait for the signature upload to finish`); row.classList.add('row-error'); }
    });
    // every row answered Yes needs a signature: tell the person in a popup and do not submit
    const unsigned = data.items.filter(it => it.option === 'Yes' && !this.rows[it.key].busy && !this.rows[it.key].sig);
    if (unsigned.length) {
      unsigned.forEach(it => { errors.push(`'${labels[it.key]}': a signature is required when the answer is Yes`); this.$('row_' + it.key).classList.add('row-error'); });
      this.showErrors(errors);
      await this.alertSignature(unsigned.map(it => labels[it.key]));
      return;
    }
    if (!errors.length && !this.anySig()) errors.push('Upload your signature and tick "Add signature" for at least one row');
    if (errors.length) { this.showErrors(errors); return; }
    if (!(await this.askSubmit())) return;
    this.busy(true);
    try {
      await ExApi.call(`${this.base()}/submit`, 'POST', data);          // resolves only after MongoDB has saved it
    } catch (e) {
      this.showErrors(e.errors && e.errors.length ? e.errors : [e.message], 'Submission failed'); this.busy(false); return;
    }
    this.$('hoModal').hidden = false; this.$('hoModalClose').focus();
  },
};

if (ExApi.requireLogin()) {
  document.getElementById('exEmpBadge').textContent = ExApi.empId;
  document.getElementById('exLogout').addEventListener('click', () => ExApi.logout());
  document.getElementById('hoSaveDraft').addEventListener('click', () => ExHandover.saveDraft());
  document.getElementById('hoForm').addEventListener('submit', e => { e.preventDefault(); ExHandover.submit(); });
  const done = () => {
    if (new URLSearchParams(location.search).get('embed')) { window.parent.postMessage({ exitEmbed: 'done' }, location.origin); return; }   // popup: close it, no page change
    window.location.replace('/exit-management/manager');
  };
  document.getElementById('hoModalClose').addEventListener('click', done);
  document.getElementById('hoModal').addEventListener('mousedown', e => { if (e.target.id === 'hoModal') done(); });
  const sf = document.getElementById('hoSigFile');
  document.getElementById('hoSigPick').addEventListener('click', () => sf.click());
  sf.addEventListener('change', () => { if (sf.files[0]) ExHandover.setPool(sf.files[0]); sf.value = ''; });
  document.getElementById('hoSigRemove').addEventListener('click', () => ExHandover.removeAll());
  const dz = document.getElementById('hoSigDrop');
  ['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) ExHandover.setPool(f); });
  ExHandover.load();
}
