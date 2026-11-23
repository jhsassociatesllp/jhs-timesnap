/* signature.js - signature FILE upload (PDF / JPG / JPEG / PNG, max 5 MB).
   The file is uploaded to the server as soon as it is chosen and stored in MongoDB GridFS; the browser only
   ever holds its metadata (ExSignature.current). The form is not submittable without an uploaded signature. */
const ExSignature = {
  MAX: 5 * 1024 * 1024,
  EXTENSIONS: ['pdf', 'jpg', 'jpeg', 'png'],
  current: null,      // metadata of the signature saved on the server: {file_id, filename, content_type, file_size, ...}
  busy: false,        // an upload is in progress
  previewUrl: null,   // object URL of the image preview for `current` (images only)

  $(id) { return document.getElementById(id); },

  init() {
    const drop = this.$('sigDrop'), input = this.$('sigFile');
    this.$('sigBrowse').addEventListener('click', e => { e.stopPropagation(); input.click(); });
    this.$('sigReplace').addEventListener('click', () => input.click());
    drop.addEventListener('click', () => input.click());
    drop.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    input.addEventListener('change', () => { if (input.files[0]) this.select(input.files[0]); input.value = ''; });
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) this.select(f); });
    this.$('sigRemove').addEventListener('click', () => this.remove());
    this.$('sigView').addEventListener('click', () => this.view());
  },

  /** Browser-side check (the server repeats it on the real file content). Returns an error message or ''. */
  validate(file) {
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!this.EXTENSIONS.includes(ext)) return 'Unsupported file type. Please upload a PDF, JPG, JPEG or PNG file.';
    if (file.size === 0) return 'The selected file is empty.';
    if (file.size > this.MAX) return `File is too large (${(Math.ceil(file.size / 10485.76) / 100).toFixed(2)} MB). Maximum size is 5 MB.`;
    return '';
  },

  fmtSize(n) { return n >= 1048576 ? (n / 1048576).toFixed(2) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; },
  fmtType(name, type) {
    const ext = (name.split('.').pop() || '').toUpperCase();
    return `${ext} (${type || 'unknown'})`;
  },

  showError(msg) {
    const box = this.$('sigError');
    box.textContent = msg; box.classList.add('show');
  },
  clearError() { this.$('sigError').classList.remove('show'); },

  /** Draw the file-info card for `meta` (+ optional image preview URL). */
  render(meta, previewUrl, status) {
    const info = this.$('sigInfo'), thumb = this.$('sigThumb');
    info.hidden = !meta;
    this.$('sigDrop').classList.toggle('has-file', !!meta);
    document.getElementById('sigCard').classList.remove('row-error');
    if (!meta) return;
    this.$('sigName').textContent = meta.filename;
    this.$('sigMeta').textContent = `${this.fmtType(meta.filename, meta.content_type)} · ${this.fmtSize(meta.file_size)}`;
    thumb.innerHTML = '';
    if (previewUrl) {
      const img = document.createElement('img'); img.src = previewUrl; img.alt = 'Signature preview'; thumb.appendChild(img);
    } else {
      thumb.innerHTML = (meta.content_type === 'application/pdf')
        ? '<i class="fas fa-file-pdf" style="color:#c0392b"></i>' : '<i class="fas fa-file-image"></i>';
    }
    this.$('sigStatus').textContent = status || '';
    this.$('sigView').hidden = false; this.$('sigReplace').hidden = false; this.$('sigRemove').hidden = false;
  },

  /** A file was chosen (browse or drop): validate, upload, show progress. */
  async select(file) {
    if (this.busy) return;
    this.clearError();
    const err = this.validate(file);
    if (err) { this.showError(err); return; }

    const isImage = /^image\//.test(file.type);
    const pending = isImage ? URL.createObjectURL(file) : null;
    const fake = { filename: file.name, content_type: file.type, file_size: file.size };
    this.render(fake, pending, 'Uploading…');
    this.$('sigView').hidden = this.$('sigReplace').hidden = this.$('sigRemove').hidden = true;
    const bar = this.$('sigBar'), prog = this.$('sigProgress');
    bar.style.width = '0%'; prog.hidden = false; this.busy = true;
    try {
      const meta = await ExApi.upload('/upload-signature', file, pct => { bar.style.width = pct + '%'; });
      if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
      this.previewUrl = pending; this.current = meta;
      this.render(meta, this.previewUrl, '✓ Signature uploaded successfully');
      ExUI.toast('Signature uploaded.');
    } catch (e) {
      if (pending) URL.revokeObjectURL(pending);
      this.showError(e.message);
      this.render(this.current, this.previewUrl, this.current ? '✓ Previous signature kept' : '');   // the old file is still saved on the server
    } finally {
      this.busy = false; prog.hidden = true;
    }
  },

  /** Show a signature already saved on the server (when a draft is reopened). */
  async load(meta) {
    this.current = meta || null;
    if (!meta) { this.render(null); return; }
    this.render(meta, null, '✓ Signature uploaded');
    if (/^image\//.test(meta.content_type || '')) {
      try {
        const blob = await ExApi.blob('/signature');
        this.previewUrl = URL.createObjectURL(blob);
        this.render(meta, this.previewUrl, '✓ Signature uploaded');
      } catch (e) { /* the file info is still shown without a preview */ }
    }
  },

  /** Open the stored signature (image or PDF) in a new tab. */
  async view() {
    try {
      const blob = await ExApi.blob('/signature');
      window.open(URL.createObjectURL(blob), '_blank', 'noopener');
    } catch (e) { this.showError(e.message); }
  },

  async remove() {
    if (this.busy || !this.current) return;
    if (!confirm('Remove the uploaded signature?')) return;
    this.clearError();
    try {
      await ExApi.call('/signature', 'DELETE');
      if (this.previewUrl) URL.revokeObjectURL(this.previewUrl);
      this.previewUrl = null; this.current = null; this.render(null);
      ExUI.toast('Signature removed.');
    } catch (e) { this.showError(e.message); }
  },
};
