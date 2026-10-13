/* JHS Resume Ranker — front end. Plain JS, no build step.
   Everything that comes from a resume is untrusted text: it only ever goes into the DOM through esc().
   No "job opening" concept here on purpose: upload CVs, every one is ranked automatically
   (parser.general_score, computed for free from what parsing already extracted), and search
   shows the highest-ranked first by default. "AI Rank" is an optional deeper semantic pass
   over the current search — capped server-side and only ever run on an explicit click. */
(() => {
  'use strict';

  const API = '/resume-ranker';
  const token = localStorage.getItem('access_token') || '';
  const empId = localStorage.getItem('loggedInEmployeeId') || '';
  if (!token) { window.location.href = '/login'; return; }
  document.getElementById('empBadge').textContent = empId;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const CRIT = { skills: 'Skills', experience: 'Experience', education: 'Education', certifications: 'Certs', achievements: 'Achievements' };
  const EDU_LABEL = { none: 'Not specified', high_school: 'High school', diploma: 'Diploma', bachelor: "Bachelor's", professional: 'Professional qualification', master: "Master's", doctorate: 'Doctorate' };

  const state = { page: 1, pageSize: 25, total: 0, rows: [], selected: new Set(), batch: null, aiRank: false };

  // ── api ───────────────────────────────────────────────────────────────────
  async function api(path, opts = {}) {
    const res = await fetch(API + path, {
      ...opts,
      headers: { Authorization: `Bearer ${token}`, ...(opts.body && !(opts.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...(opts.headers || {}) },
      body: opts.body && !(opts.body instanceof FormData) ? JSON.stringify(opts.body) : opts.body,
    });
    if (res.status === 401) { window.location.href = '/login'; throw new Error('Session expired'); }
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail || []).map((d) => `${(d.loc || []).slice(-1)}: ${d.msg}`).join('; ') || msg; } catch (_) { /* keep statusText */ }
      const err = new Error(msg); err.status = res.status; throw err;
    }
    return res;
  }
  const getJSON = async (p) => (await api(p)).json();
  const sendJSON = async (p, method, body) => (await api(p, { method, body })).json();

  let toastTimer;
  function toast(msg, isErr) {
    const t = $('toast'); t.textContent = msg; t.className = 'toast show' + (isErr ? ' err' : '');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = 'toast' + (isErr ? ' err' : ''); }, isErr ? 6000 : 2800);
  }
  const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : '—');
  const fmtSize = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB');
  const scoreClass = (n) => (n >= 75 ? 'good' : n >= 50 ? 'mid' : 'low');
  const num = (v, d = 1) => (v == null ? '—' : Number(v).toFixed(d).replace(/\.0+$/, ''));

  // ── init ──────────────────────────────────────────────────────────────────
  async function init() {
    try {
      const chk = await getJSON('/access-check');
      if (!chk.allowed) { $('gate').innerHTML = '<div><i class="fas fa-lock" style="font-size:2rem"></i><h3 style="margin:.6rem 0">No access to Resume Ranker</h3><p>Ask a super admin to enable the <b>resume_ranker</b> module for your employee code.</p></div>'; return; }
      $('aiBanner').style.display = chk.ai_configured ? 'none' : 'flex';
      $('startBtn').disabled = !chk.ai_configured;
    } catch (e) { $('gate').textContent = 'Could not load: ' + e.message; return; }
    $('gate').style.display = 'none'; $('app').style.display = 'block';
    pollQueue();
  }

  async function pollQueue() {
    try {
      const o = await getJSON('/overview'); const q = o.queue; const pill = $('queuePill');
      if (q.queued + q.running > 0) { pill.style.display = ''; pill.innerHTML = `<i class="fas fa-gear fa-spin"></i> ${q.running} running · ${q.queued} queued`; } else pill.style.display = 'none';
    } catch (_) { /* transient */ }
    setTimeout(pollQueue, 4000);
  }

  // ── tabs ──────────────────────────────────────────────────────────────────
  function showTab(name) {
    document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    ['upload', 'candidates'].forEach((t) => { $('tab-' + t).style.display = t === name ? '' : 'none'; });
    if (name === 'candidates') search(true);
  }
  document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => showTab(b.dataset.tab)));

  // ══════════════════════════════ UPLOAD ═════════════════════════════════════
  const ALLOWED = ['.pdf', '.docx', '.doc'], MAX_BYTES = 10 * 1024 * 1024, CHUNK = 10;
  let queue = [];   // {file, status, note}

  function addFiles(list) {
    const rej = [];
    [...list].forEach((f) => {
      const ext = '.' + f.name.split('.').pop().toLowerCase();
      if (!ALLOWED.includes(ext)) rej.push(`${f.name}: not a PDF/DOCX/DOC`);
      else if (f.size > MAX_BYTES) rej.push(`${f.name}: larger than 10 MB`);
      else if (f.size === 0) rej.push(`${f.name}: empty file`);
      else if (!queue.some((q) => q.file.name === f.name && q.file.size === f.size)) queue.push({ file: f, status: 'ready', note: '' });
    });
    const box = $('queueRejects');
    if (rej.length) { box.style.display = 'flex'; box.innerHTML = `<i class="fas fa-triangle-exclamation"></i><div><b>${rej.length} file(s) skipped:</b><br>${rej.slice(0, 8).map(esc).join('<br>')}${rej.length > 8 ? `<br>…and ${rej.length - 8} more` : ''}</div>`; } else box.style.display = 'none';
    renderQueue();
  }
  function renderQueue() {
    $('fileQueue').style.display = queue.length || $('queueRejects').style.display !== 'none' ? '' : 'none';
    $('queueCount').textContent = `${queue.length} file(s) ready · ${fmtSize(queue.reduce((a, q) => a + q.file.size, 0))}`;
    $('queueBody').innerHTML = queue.map((q) => `<tr><td>${esc(q.file.name)}</td><td>${fmtSize(q.file.size)}</td><td>${statusChip(q)}</td></tr>`).join('');
  }
  function statusChip(q) {
    const m = { ready: ['gray', 'Ready'], uploading: ['blue', 'Uploading…'], queued: ['blue', 'Queued for AI'], duplicate: ['amber', 'Duplicate file'], rejected: ['red', 'Rejected'], failed: ['red', 'Upload failed'] }[q.status];
    return `<span class="chip ${m[0]}">${m[1]}</span>${q.note ? ` <span class="sub">${esc(q.note)}</span>` : ''}`;
  }
  const dz = $('dropzone');
  ['dragenter', 'dragover'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove('over'); }));
  dz.addEventListener('drop', async (e) => { addFiles(await filesFromDrop(e.dataTransfer)); });
  dz.addEventListener('click', (e) => { if (!e.target.closest('button')) $('fileInput').click(); });
  $('pickBtn').addEventListener('click', () => $('fileInput').click());
  $('pickFolderBtn').addEventListener('click', () => $('folderInput').click());
  $('fileInput').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
  $('folderInput').addEventListener('change', (e) => { addFiles([...e.target.files].filter((f) => ALLOWED.includes('.' + f.name.split('.').pop().toLowerCase()))); e.target.value = ''; });
  $('clearBtn').addEventListener('click', () => { queue = []; $('queueRejects').style.display = 'none'; renderQueue(); });

  async function filesFromDrop(dt) {   // supports dropping whole folders
    const items = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
    if (!items.length) return dt.files;
    const out = [];
    const walk = async (entry) => {
      if (entry.isFile) out.push(await new Promise((res, rej) => entry.file(res, rej)));
      else if (entry.isDirectory) { const r = entry.createReader(); let batch; do { batch = await new Promise((res, rej) => r.readEntries(res, rej)); for (const e of batch) await walk(e); } while (batch.length); }
    };
    for (const it of items) await walk(it);
    return out;
  }

  function xhrUpload(url, files, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData(); files.forEach((f) => fd.append('files', f, f.name));
      const x = new XMLHttpRequest(); x.open('POST', url); x.setRequestHeader('Authorization', `Bearer ${token}`);
      x.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded);
      x.onload = () => { if (x.status >= 200 && x.status < 300) resolve(JSON.parse(x.responseText)); else { let m = x.statusText; try { m = JSON.parse(x.responseText).detail || m; } catch (_) { /* ignore */ } reject(new Error(m)); } };
      x.onerror = () => reject(new Error('Network error')); x.send(fd);
    });
  }

  $('startBtn').addEventListener('click', async () => {
    const todo = queue.filter((q) => q.status === 'ready'); if (!todo.length) return;
    $('startBtn').disabled = true; $('progressCard').style.display = ''; $('doneActions').style.display = 'none'; $('failuresBox').style.display = 'none';
    let batchId;
    try { batchId = (await sendJSON('/batches', 'POST', { job_ids: [], expected_files: todo.length })).batch_id; }
    catch (e) { toast(e.message, true); $('startBtn').disabled = false; return; }
    state.batch = batchId;

    const totalBytes = todo.reduce((a, q) => a + q.file.size, 0); let doneBytes = 0; const inflight = {};
    const paint = () => { const cur = doneBytes + Object.values(inflight).reduce((a, b) => a + b, 0); const pct = Math.min(100, Math.round((cur * 100) / totalBytes)); $('upBar').style.width = pct + '%'; $('upLabel').textContent = `${pct}% · ${fmtSize(cur)} of ${fmtSize(totalBytes)}`; };
    paint();
    const chunks = []; for (let i = 0; i < todo.length; i += CHUNK) chunks.push(todo.slice(i, i + CHUNK));
    let next = 0;
    const lane = async () => {
      while (next < chunks.length) {
        const idx = next++, chunk = chunks[idx]; chunk.forEach((q) => { q.status = 'uploading'; }); renderQueue();
        const size = chunk.reduce((a, q) => a + q.file.size, 0);
        try {
          const { results } = await xhrUpload(`${API}/batches/${batchId}/files`, chunk.map((q) => q.file), (loaded) => { inflight[idx] = Math.min(loaded, size); paint(); });
          results.forEach((r, i) => { chunk[i].status = r.status; chunk[i].note = r.reason || ''; });
        } catch (e) { chunk.forEach((q) => { q.status = 'failed'; q.note = e.message; }); }
        delete inflight[idx]; doneBytes += size; paint(); renderQueue();
      }
    };
    await Promise.all([lane(), lane()]);
    $('upBar').style.width = '100%';
    pollBatch(batchId);
  });

  async function pollBatch(id) {
    let p;
    try { p = await getJSON(`/batches/${id}`); } catch (e) { setTimeout(() => pollBatch(id), 3000); return; }
    const c = p.counts, handled = c.parsed + c.failed + c.duplicate, denom = Math.max(p.expected - p.rejected_count, 1);
    const pct = Math.round((handled * 100) / denom);
    $('parseBar').style.width = pct + '%'; $('parseLabel').textContent = `${handled} of ${denom} files`;
    $('progSummary').innerHTML = `<span class="chip green">${c.parsed} ranked</span>` + (c.queued + c.processing ? `<span class="chip blue">${c.queued + c.processing} in progress</span>` : '') + (c.duplicate ? `<span class="chip amber">${c.duplicate} duplicate file(s)</span>` : '') + (c.failed ? `<span class="chip red">${c.failed} failed</span>` : '') + (p.rejected_count ? `<span class="chip red">${p.rejected_count} rejected</span>` : '');
    const fails = [...(p.rejected || []).map((r) => ({ filename: r.filename, error: r.reason })), ...(p.failures || [])];
    $('failuresBox').style.display = fails.length ? '' : 'none';
    $('failBody').innerHTML = fails.map((f) => `<tr><td>${esc(f.filename)}</td><td>${esc(f.error || 'Unknown error')}</td></tr>`).join('');
    $('retryBtn').style.display = (p.failures || []).length ? '' : 'none';
    if (p.finished) { $('doneActions').style.display = ''; $('startBtn').disabled = false; queue = queue.filter((q) => q.status === 'ready'); renderQueue(); return; }
    setTimeout(() => pollBatch(id), 2000);
  }
  $('retryBtn').addEventListener('click', async () => { try { const r = await sendJSON(`/batches/${state.batch}/retry`, 'POST'); toast(`Retrying ${r.requeued} file(s)`); $('doneActions').style.display = 'none'; pollBatch(state.batch); } catch (e) { toast(e.message, true); } });
  $('viewResultsBtn').addEventListener('click', () => { showTab('candidates'); search(true); });

  // Show a CV's location as "City, State" only. The parsed text can be a full address
  // ("Flat 4, Andheri East, Mumbai, Maharashtra 400069"); drop street/locality bits, pin codes and
  // East/West/North/South, keeping the city and (when the CV has one) the state.
  const STATES = ['andhra pradesh', 'arunachal pradesh', 'assam', 'bihar', 'chhattisgarh', 'goa', 'gujarat', 'haryana', 'himachal pradesh', 'jharkhand', 'karnataka', 'kerala', 'madhya pradesh', 'maharashtra', 'manipur', 'meghalaya', 'mizoram', 'nagaland', 'odisha', 'orissa', 'punjab', 'rajasthan', 'sikkim', 'tamil nadu', 'telangana', 'tripura', 'uttar pradesh', 'uttarakhand', 'west bengal', 'delhi', 'new delhi', 'jammu and kashmir', 'jammu & kashmir', 'ladakh', 'chandigarh', 'puducherry', 'pondicherry', 'andaman and nicobar islands', 'dadra and nagar haveli', 'daman and diu', 'lakshadweep'];
  const STATE_ABBR = { ap: 'Andhra Pradesh', br: 'Bihar', cg: 'Chhattisgarh', gj: 'Gujarat', hr: 'Haryana', hp: 'Himachal Pradesh', jh: 'Jharkhand', ka: 'Karnataka', kl: 'Kerala', mp: 'Madhya Pradesh', mh: 'Maharashtra', od: 'Odisha', pb: 'Punjab', rj: 'Rajasthan', tn: 'Tamil Nadu', ts: 'Telangana', tg: 'Telangana', up: 'Uttar Pradesh', uk: 'Uttarakhand', wb: 'West Bengal', dl: 'Delhi' };
  const titleCase = (t) => t.replace(/\b([a-z])([a-z]*)/gi, (_, a, b) => a.toUpperCase() + b.toLowerCase());
  function cityState(loc) {
    if (!loc) return '';
    const isState = (x) => STATES.includes(x.toLowerCase()) || !!STATE_ABBR[x.toLowerCase()];
    const clean = (x) => {
      const base = x.replace(/\b\d{5,6}\b/g, '').replace(/[()\-–]+/g, ' ').replace(/\s+/g, ' ').trim();
      if (isState(base)) return base;                      // "West Bengal" keeps its West
      return base.replace(/\b(east|west|north|south|e|w)\b\.?/gi, '').replace(/\s+/g, ' ').trim();
    };
    const parts = String(loc).split(/[,\n|/]+/).map(clean).filter(Boolean);
    if (!parts.length) return '';
    const stateIdx = parts.map(isState).lastIndexOf(true);
    let state = '', city = '';
    if (stateIdx >= 0) {
      state = STATE_ABBR[parts[stateIdx].toLowerCase()] || titleCase(parts[stateIdx]);
      city = stateIdx > 0 ? parts[stateIdx - 1] : '';
    } else {
      city = parts[parts.length - 1];            // no state in the CV: the last part is the city
    }
    if (city && city.toLowerCase() === state.toLowerCase()) city = '';
    return [city && titleCase(city), state].filter(Boolean).join(', ');
  }

  // ══════════════════════════════ CANDIDATES ═════════════════════════════════
  const F = ['fQ', 'fLocation', 'fState', 'fEducation', 'fCertification', 'fSkills', 'fMinExp', 'fMaxExp'];
  function resetFilters() {
    F.forEach((id) => { const el = $(id); if (el) el.value = ''; });
    state.aiRank = false;
  }
  function params() {
    const p = new URLSearchParams(); const set = (k, v) => { if (v !== '' && v != null) p.set(k, v); };
    set('q', $('fQ').value.trim()); set('location', $('fLocation').value.trim()); set('state', $('fState').value.trim()); set('education', $('fEducation').value.trim()); set('certification', $('fCertification').value.trim());
    set('skills', $('fSkills').value.trim());
    set('min_exp', $('fMinExp').value); set('max_exp', $('fMaxExp').value);
    // ai_rank costs real money per search (the server caps it) — search() turns it on only when
    // a keyword/filter is present. With nothing typed the free general_score ranking is shown.
    if (state.aiRank) p.set('ai_rank', 'true');
    return p;
  }
  // Suggestion dropdown for Education / Certification: a clean list under the box that narrows as you
  // type. Picking one fills the box and searches.
  function makeSuggest(inputId, listId, noun) {
    const input = $(inputId), box = $(listId); let items = [];
    const render = () => {
      const q = input.value.trim().toLowerCase();
      const hits = items.filter((i) => !q || i.name.toLowerCase().includes(q)).slice(0, 60);
      if (!hits.length) { box.hidden = true; return; }
      box.innerHTML = hits.map((i) => `<button type="button" class="suggest-item" data-v="${esc(i.name)}"><span class="s-name">${esc(i.name)}</span></button>`).join('');
      box.hidden = false;
    };
    input.addEventListener('focus', render);
    input.addEventListener('input', render);
    input.addEventListener('keydown', (e) => { if (e.key === 'Escape') box.hidden = true; });
    box.addEventListener('mousedown', (e) => {
      const b = e.target.closest('.suggest-item'); if (!b) return;
      e.preventDefault(); input.value = b.dataset.v; box.hidden = true; search(true);
    });
    document.addEventListener('click', (e) => { if (!box.contains(e.target) && e.target !== input) box.hidden = true; });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') box.hidden = true; });
    return { set(list) { items = list || []; if (document.activeElement === input) render(); } };
  }
  const suggestEdu = makeSuggest('fEducation', 'educationSuggest', 'Education');
  const suggestCert = makeSuggest('fCertification', 'certSuggest', 'Certifications');
  const suggestCity = makeSuggest('fLocation', 'citySuggest', 'Cities');
  const suggestState = makeSuggest('fState', 'stateSuggest', 'States');
  // Cities and states come from the uploaded CVs' own locations, cleaned to "City, State" (no East/West, no localities).
  async function loadLocations() {
    try {
      const { locations } = await getJSON('/locations');
      const cities = new Map(), states = new Map();
      locations.forEach((l) => {
        const [city, state] = (() => { const x = cityState(l.location).split(', '); return x.length > 1 ? [x[0], x[1]] : (STATES.includes((x[0] || '').toLowerCase()) ? ['', x[0]] : [x[0], '']); })();
        if (city) cities.set(city.toLowerCase(), { name: city });
        if (state) states.set(state.toLowerCase(), { name: state });
      });
      const sorted = (m) => [...m.values()].sort((a, b) => a.name.localeCompare(b.name));
      suggestCity.set(sorted(cities)); suggestState.set(sorted(states));
    } catch (_) { /* dropdown is optional */ }
  }

  async function loadEducation() {
    try {
      const { education } = await getJSON('/education-options');
      suggestEdu.set(education);
    } catch (_) { /* dropdown is optional */ }
  }
  async function loadCerts() {
    try {
      const { certifications } = await getJSON('/certification-options');
      suggestCert.set(certifications);
    } catch (_) { /* dropdown is optional */ }
  }

  async function search(resetPage) {
    if (resetPage) state.page = 1;
    loadLocations(); loadEducation(); loadCerts();
    // Search IS the AI rank: any keyword/filter turns the AI evaluation on (the server still caps
    // how many CVs go to the model). With nothing typed there is nothing to judge, so the free
    // automatic ranking is shown instead.
    state.aiRank = F.some((id) => $(id) && $(id).value.trim() !== '');
    const p = params(); p.set('page', state.page); p.set('page_size', state.pageSize);
    let d;
    try { d = await getJSON('/resumes?' + p); } catch (e) { toast(e.message, true); return; }
    state.rows = d.resumes; state.total = d.total; state.selected.clear(); updateBulk();
    renderHead(); renderRows();
    $('candEmpty').style.display = d.total ? 'none' : '';
    $('candEmpty').innerHTML = 'No resumes match your criteria. Try adjusting keywords or skills.';
    const from = d.total ? (state.page - 1) * state.pageSize + 1 : 0;
    $('pagerInfo').textContent = `${from}–${Math.min(state.page * state.pageSize, d.total)} of ${d.total}`;
    $('prevBtn').disabled = state.page <= 1; $('nextBtn').disabled = state.page * state.pageSize >= d.total;
    const filtering = ['fQ', 'fLocation', 'fState', 'fEducation', 'fCertification', 'fSkills', 'fMinExp', 'fMaxExp'].some((id) => $(id).value.trim());
    $('candSub').textContent = state.aiRank
      ? `AI-evaluated search results (${d.total}) — highest match first.`
      : (filtering ? `${d.total} CV${d.total === 1 ? ' matches' : 's match'} your search — highest-ranked first.`
                   : 'Every uploaded CV is ranked automatically — highest-ranked first.');
  }
  $('applyBtn').addEventListener('click', async () => {
    const b = $('applyBtn'); const html = b.innerHTML; b.disabled = true; b.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Searching…';
    try { await search(true); } finally { b.disabled = false; b.innerHTML = html; }
  });
  $('resetBtn').addEventListener('click', () => { resetFilters(); search(true); });
  F.filter((id) => ['fQ', 'fLocation', 'fState', 'fEducation', 'fCertification', 'fSkills', 'fMinExp', 'fMaxExp'].includes(id)).forEach((id) => $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') search(true); }));
  $('prevBtn').addEventListener('click', () => { state.page--; search(false); });
  $('nextBtn').addEventListener('click', () => { state.page++; search(false); });

  function renderHead() {
    $('candHead').innerHTML = '<tr><th><input type="checkbox" id="selAll" /></th><th>#</th><th>Candidate</th><th>Top skills</th><th>Exp.</th><th>Education</th><th>Rank score</th><th>Breakdown</th><th>Uploaded</th><th></th></tr>';
    $('selAll').addEventListener('change', (e) => { state.rows.forEach((r) => (e.target.checked ? state.selected.add(r.id) : state.selected.delete(r.id))); renderRows(); updateBulk(); $('selAll').checked = e.target.checked; });
  }
  // "Top 5" section: only when the list is sorted by rank (highest first) and on page 1 — the
  // top 5 get their own heading and everyone else follows under "Other candidates". Purely a
  // display grouping (free): it doesn't change what is scored or what anything costs.
  const TOP_N = 5, COLS = 10;
  function sectionRow(idx) {
    const byRank = state.page === 1;   // the list is always ranked highest-first
    if (!byRank || !state.rows.length) return '';
    if (idx === 0) return `<tr class="section-row top"><td colspan="${COLS}"><i class="fas fa-trophy"></i> Top ${Math.min(TOP_N, state.rows.length)} ranked candidates</td></tr>`;
    if (idx === TOP_N) return `<tr class="section-row"><td colspan="${COLS}">Other candidates — all details below, ranked</td></tr>`;
    return '';
  }
  function renderRows() {
    $('candBody').innerHTML = state.rows.map((r, idx) => {
      const s = r.score;                       // present only when "AI Rank" was used for this search
      const dup = r.duplicate_of;
      const badges = (dup ? `<span class="chip amber" title="${esc(r.duplicate_reason || '')}"><i class="fas fa-clone"></i> ${r.duplicate_confidence === 'possible' ? 'Possible duplicate' : 'Duplicate'}</span> ` : '');
      const cand = `<div class="cand-name"><a data-view="${r.id}">${esc(r.name || r.filename)}</a></div><div class="sub">${esc([r.current_title, r.current_company].filter(Boolean).join(' · ') || r.headline || '')}</div><div class="sub">${esc([r.email, cityState(r.location)].filter(Boolean).join(' · '))}</div>${badges}`;
      const skills = `<div class="tagline">${(r.skills || []).slice(0, 5).map((k) => `<span class="chip">${esc(k)}</span>`).join('')}</div>`;

      let scoreCell, breakdownCell;
      if (s && s.total != null) {
        const flags = (s.flags || []).filter((f) => f.severity === 'critical');
        const mini = Object.entries(s.sub_scores || {}).map(([k, v]) => `<span class="mini">${CRIT[k] || k} <b>${Math.round(v.score)}</b></span>`).join('');
        scoreCell = `<div class="score-num t-${scoreClass(s.total)}">${num(s.total)}</div><div class="sbar"><div class="s-${scoreClass(s.total)}" style="width:${s.total}%"></div></div><div class="sub" style="font-size:.72rem;color:var(--brand-d)">AI evaluated</div>`;
        breakdownCell = `<div class="minis">${mini}</div>${flags.map((f) => `<div class="chip red" style="margin-top:.25rem"><i class="fas fa-triangle-exclamation"></i> ${esc(f.message)}</div>`).join('')}`;
      } else {
        const gs = r.general_score; const b = r.general_breakdown || {};
        const mini = Object.entries(b).map(([k, v]) => `<span class="mini">${CRIT[k] || (k.charAt(0).toUpperCase() + k.slice(1))} <b>${Math.round(v)}</b></span>`).join('');
        scoreCell = gs != null ? `<div class="score-num t-${scoreClass(gs)}">${num(gs)}</div><div class="sbar"><div class="s-${scoreClass(gs)}" style="width:${gs}%"></div></div><div class="sub" title="Free, from experience/education/skills/certifications">profile strength</div>` : '—';
        breakdownCell = mini ? `<div class="minis">${mini}</div>` : '';
      }
      let rankCell = '—';
      if (r.rank != null) {
        rankCell = r.rank === 1 ? '<span class="rank-badge rank-1"><i class="fas fa-trophy"></i> #1</span>'
          : r.rank === 2 ? '<span class="rank-badge rank-2"><i class="fas fa-medal"></i> #2</span>'
          : r.rank === 3 ? '<span class="rank-badge rank-3"><i class="fas fa-award"></i> #3</span>'
          : `<span class="rank-badge">#${r.rank}</span>`;
      }
      return `${sectionRow(idx)}<tr class="${dup ? 'is-dup' : ''} ${state.page === 1 && idx < TOP_N ? 'top-row' : ''}">
        <td><input type="checkbox" data-sel="${r.id}" ${state.selected.has(r.id) ? 'checked' : ''} /></td>
        <td class="rank">${rankCell}</td>
        <td>${cand}</td><td>${skills}</td>
        <td class="nowrap">${num(r.total_years)}${r.total_years != null ? ' y' : ''}</td>
        <td>${esc(r.education || '—')}</td>
        <td class="score-cell">${scoreCell}</td>
        <td>${breakdownCell}</td>
        <td>${fmtDate(r.uploaded_at)}</td>
        <td class="actions"><button class="btn btn-ghost btn-sm" data-view="${r.id}">View details</button></td>
      </tr>`;
    }).join('');
  }
  $('candBody').addEventListener('click', (e) => {
    const v = e.target.closest('[data-view]'); if (v) { openDetail(v.dataset.view); return; }
  });
  $('candBody').addEventListener('change', (e) => {
    const sel = e.target.closest('[data-sel]');
    if (sel) { sel.checked ? state.selected.add(sel.dataset.sel) : state.selected.delete(sel.dataset.sel); updateBulk(); }
  });
  function updateBulk() {
    const n = state.selected.size; $('bulkBar').style.display = n ? '' : 'none'; $('bulkCount').textContent = `${n} selected`;
  }
  $('bulkClear').addEventListener('click', () => { state.selected.clear(); renderRows(); updateBulk(); });

  // Permanent: removes the CV, its stored file and its scores. Always asks first.
  async function deleteCvs(ids) {
    if (!ids.length) return;
    const msg = ids.length === 1
      ? 'Delete this CV permanently? The file, its ranking and any tags or notes will be removed. This cannot be undone.'
      : `Delete ${ids.length} CVs permanently? Their files, rankings, tags and notes will be removed. This cannot be undone.`;
    if (!confirm(msg)) return;
    try {
      const r = ids.length === 1 ? (await sendJSON(`/resumes/${ids[0]}`, 'DELETE'), { deleted: 1 }) : await sendJSON('/resumes/bulk-delete', 'POST', { ids });
      toast(`${r.deleted} CV${r.deleted === 1 ? '' : 's'} deleted`);
      closeDrawer(); state.selected.clear();
      if (state.page > 1 && ids.length >= state.rows.length) state.page--;
      await search(false);
    } catch (e) { toast(e.message, true); }
  }

  // export
  $('exportBtn').addEventListener('click', (e) => { e.stopPropagation(); $('exportMenu').classList.toggle('open'); });
  document.addEventListener('click', () => $('exportMenu').classList.remove('open'));
  $('exportMenu').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-x]'); if (!b) return; const [fmt, what] = b.dataset.x.split('|');
    const p = new URLSearchParams({ format: fmt }); if (what === 'top10') p.set('top', 10);
    if (what === 'selected') { if (!state.selected.size) { toast('Tick some rows first', true); return; } p.set('ids', [...state.selected].join(',')); }
    if ($('fQ').value.trim()) p.set('q', $('fQ').value.trim());
    if ($('fLocation').value.trim()) p.set('location', $('fLocation').value.trim());
    if ($('fState').value.trim()) p.set('state', $('fState').value.trim());
    if ($('fEducation').value.trim()) p.set('education', $('fEducation').value.trim());
    if ($('fCertification').value.trim()) p.set('certification', $('fCertification').value.trim());
    if ($('fSkills').value.trim()) p.set('skills', $('fSkills').value.trim());
    if ($('fMinExp').value) p.set('min_exp', $('fMinExp').value);
    if ($('fMaxExp').value) p.set('max_exp', $('fMaxExp').value);
    if (state.aiRank) p.set('ai_rank', 'true');
    try {
      const res = await api(`/export?${p}`); const blob = await res.blob();
      const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || `ranking.${fmt}`;
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (er) { toast(er.message, true); }
  });

  // ══════════════════════════════ DETAIL DRAWER ══════════════════════════════
  const drawer = $('drawer'), mask = $('drawerMask');
  const closeDrawer = () => { drawer.classList.remove('open'); mask.classList.remove('open'); };
  $('dClose').addEventListener('click', closeDrawer); mask.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

  async function openDetail(id) {
    $('dTitle').textContent = 'Loading…'; $('dBody').innerHTML = '<div class="gate"><i class="fas fa-spinner fa-spin"></i></div>'; drawer.classList.add('open'); mask.classList.add('open');
    try { renderDetail(await getJSON('/resumes/' + id)); } catch (e) { $('dBody').innerHTML = `<div class="banner warn">${esc(e.message)}</div>`; }
  }

  function critDetail(k, v) {
    if (k === 'skills' || k === 'certifications') {
      const matchList = (items, cls) => (items || []).map((m) => `<span class="chip ${cls}" title="${esc(m.evidence || '')}">${esc(m.name)}</span>`).join('');
      return `<div class="crit-d"><div class="tagline">${matchList(v.matched, 'green')}${matchList(v.partial, 'amber')}${(v.missing || []).map((m) => `<span class="chip red"><i class="fas fa-xmark"></i> ${esc(m.name)}</span>`).join('')}</div></div>`;
    }
    if (k === 'experience') return `<div class="crit-d">${num(v.relevant_years)} relevant years vs ${num(v.required_years)} requested</div>`;
    if (k === 'education') return `<div class="crit-d">Has ${esc(EDU_LABEL[v.highest] || v.highest)}</div>`;
    return '';
  }

  function generalScoreBlock(r) {
    const gs = r.general_score; const b = r.general_breakdown || {};
    if (gs == null) return '<p class="muted">Not yet ranked.</p>';
    const rows = Object.entries(b).map(([k, v]) => `<div class="crit"><div class="crit-h"><span>${CRIT[k] || k}</span><span class="t-${scoreClass(v * 5)}">${num(v)}</span></div><div class="sbar"><div class="s-${scoreClass(v * 5)}" style="width:${Math.min(v * 5, 100)}%"></div></div></div>`).join('');
    return `<div class="big-score"><div class="n t-${scoreClass(gs)}">${num(gs)}</div><div><div><b>profile strength</b></div><div class="sub">Free — computed from experience, education, skills, certifications and achievements. Not tied to any specific job.</div></div></div>${rows}`;
  }

  function aiScoreBlock(s) {
    const crit = Object.entries(s.sub_scores || {}).map(([k, v]) => `<div class="crit"><div class="crit-h"><span>${CRIT[k] || k}</span><span class="t-${scoreClass(v.score)}">${num(v.score)}%</span></div><div class="sbar"><div class="s-${scoreClass(v.score)}" style="width:${v.score}%"></div></div>${critDetail(k, v)}</div>`).join('');
    const flags = (s.flags || []).map((f) => `<div class="flag ${f.severity}"><i class="fas fa-${f.severity === 'critical' ? 'circle-xmark' : 'triangle-exclamation'}"></i> ${esc(f.message)}</div>`).join('');
    return `<div class="big-score"><div class="n t-${scoreClass(s.total)}">${num(s.total)}</div><div><div><b>AI match score</b></div><div class="sub">Evaluated against your search</div></div></div>
      ${flags}${s.summary ? `<p style="margin:.7rem 0;font-size:.9rem">${esc(s.summary)}</p>` : ''}
      ${(s.strengths || []).length ? `<b class="small">Strengths</b><ul class="tight">${s.strengths.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      ${(s.concerns || []).length ? `<b class="small">Concerns</b><ul class="tight">${s.concerns.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      <hr style="border:none;border-top:1px solid var(--border);margin:.8rem 0">${crit}`;
  }

  function renderDetail(r) {
    const p = r.parsed || {};
    const aiScores = (r.scores || []).filter((s) => String(s.job_id || '').startsWith('adhoc_'));
    $('dTitle').textContent = r.name || r.filename;
    const dupBanner = r.duplicate_of ? `<div class="banner warn"><i class="fas fa-clone"></i> ${r.duplicate_confidence === 'possible' ? 'Possible duplicate' : 'Duplicate'} of <a class="link" data-open="${esc(r.duplicate_of)}">${esc(r.duplicate_of_name || 'another resume')}</a> — ${esc(r.duplicate_reason || '')}</div>` : (r.duplicates?.length ? `<div class="banner info"><span><i class="fas fa-clone"></i> ${r.duplicates.length} later upload(s) look like the same candidate: ${r.duplicates.map((d) => `<a class="link" data-open="${d.id}">${esc(d.filename)}</a>`).join(', ')}</span></div>` : '');
    $('dBody').innerHTML = `${dupBanner}
      ${r.status === 'failed' ? `<div class="banner warn">This file could not be processed: ${esc(r.error)}</div>` : ''}
      <div class="d-cols">
        <div>
          <div class="d-card"><h4>Ranking</h4>${generalScoreBlock(r)}</div>
          ${aiScores.length ? `<div class="d-card"><h4>AI Rank evaluation</h4>${aiScoreBlock(aiScores[0])}</div>` : ''}
          ${(p.skills || []).length ? `<div class="d-card"><h4>Skills</h4><div class="tagline">${p.skills.map((s) => `<span class="chip">${esc(s)}</span>`).join('')}</div></div>` : ''}
          ${(p.certifications || []).length ? `<div class="d-card"><h4>Certifications</h4><div class="tagline">${p.certifications.map((s) => `<span class="chip green">${esc(s)}</span>`).join('')}</div></div>` : ''}
          ${(p.achievements || []).length ? `<div class="d-card"><h4>Key achievements</h4><ul class="tight">${p.achievements.map((a) => `<li>${esc(a)}</li>`).join('')}</ul></div>` : ''}
        </div>
        <div>
          <div class="d-card"><h4>Candidate</h4><dl class="kv">
            <dt>Name</dt><dd>${esc(p.name || r.name || '—')}</dd><dt>Email</dt><dd>${esc(p.email || '—')}</dd><dt>Phone</dt><dd>${esc(p.phone || '—')}</dd>
            <dt>Location</dt><dd>${esc(cityState(p.location) || '—')}</dd><dt>Experience</dt><dd>${num(p.total_years_experience)} years${p.stated_years_experience != null ? ` <span class="sub">(CV states ${num(p.stated_years_experience)})</span>` : ''}</dd>
            <dt>Education</dt><dd>${esc(EDU_LABEL[p.highest_education_level] || '—')}</dd><dt>File</dt><dd>${esc(r.filename)}</dd></dl><div class="file-actions"><button class="btn btn-primary btn-sm" id="dView"><i class="fas fa-eye"></i> View original CV</button><button class="btn btn-ghost btn-sm" id="dDownload"><i class="fas fa-download"></i> Download CV</button></div></div>
          ${(p.experience || []).length ? `<div class="d-card"><h4>Work history</h4>${p.experience.map((e) => `<div class="exp-item"><b>${esc(e.title || '')}</b>${e.company ? ` · ${esc(e.company)}` : ''}<div class="sub">${esc(e.start || '?')} – ${esc(e.end || '?')}${e.industry ? ' · ' + esc(e.industry) : ''}</div>${e.summary ? `<div style="font-size:.84rem">${esc(e.summary)}</div>` : ''}</div>`).join('')}</div>` : ''}
          ${(p.education || []).length ? `<div class="d-card"><h4>Education</h4>${p.education.map((e) => `<div class="exp-item"><b>${esc(e.degree)}</b>${e.field ? ` · ${esc(e.field)}` : ''}<div class="sub">${esc([e.institution, e.year].filter(Boolean).join(' · '))}</div></div>`).join('')}</div>` : ''}
          <div class="d-card"><h4>Full extracted text</h4><details><summary class="link">Show the raw text the AI read</summary><div class="raw-text" style="margin-top:.5rem">${esc(r.text || '(none)')}</div></details></div>
        </div>
      </div>`;

    $('dBody').querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', () => openDetail(a.dataset.open)));

    const saveBlob = (blob) => { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = r.filename; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); };
    $('dDownload').addEventListener('click', async () => { try { const res = await api(`/resumes/${r.id}/file`); saveBlob(await res.blob()); } catch (e) { toast(e.message, true); } });
    // View = open the original in a new tab. Browsers only render PDFs; a Word file can't be shown, so it is downloaded instead.
    $('dView').addEventListener('click', async () => {
      const isPdf = /\.pdf$/i.test(r.filename || '');
      const w = isPdf ? window.open('', '_blank') : null;   // opened now (inside the click) so the popup isn't blocked
      try {
        const res = await api(`/resumes/${r.id}/file?inline=true`); const blob = await res.blob();
        if (w) { w.location.href = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' })); }
        else { saveBlob(blob); toast('Word files cannot be previewed in the browser — downloaded instead'); }
      } catch (e) { if (w) w.close(); toast(e.message, true); }
    });
  }

  init();
})();
