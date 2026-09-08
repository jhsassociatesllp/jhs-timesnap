/**
 * JHS Library explorer — library.js
 *
 * Ported from the standalone JHS Library app's frontend/app.js, adapted to:
 *   - call the platform-mounted API at /chatbot/library/* (Bearer-authed)
 *     instead of the standalone app's bare /facets, /ask, etc.
 *   - drive the renamed lib-tab-btn/lib-tab-panel elements (avoids clashing
 *     with the module page's own outer HR/RCM/Library tab bar)
 *   - persist Ask-tab chat history per user (session id + a small history
 *     dropdown), since the standalone app had no history at all
 *
 * Everything else — facet filtering, the browse grid, the detail drawer,
 * draft-a-finding — is unchanged behavior from the original.
 */
(function () {
  "use strict";

  const API = "/chatbot/library";

  function authHeaders() {
    const token = (window.JHSChatCore && window.JHSChatCore.getToken()) || "";
    return { Authorization: `Bearer ${token}` };
  }

  async function libFetch(path, opts = {}) {
    const headers = Object.assign({}, opts.headers, authHeaders());
    return fetch(`${API}${path}`, Object.assign({}, opts, { headers }));
  }

  // ── State ─────────────────────────────────────────────────────────────────
  const FACET_FIELDS = ['sector', 'audit_type', 'risk', 'process_area', 'risk_theme', 'coso_component', 'fs_assertion', 'fraud_risk_indicator'];
  const FACET_LABELS = {
    sector: 'Sector', audit_type: 'Audit Type', risk: 'Risk',
    process_area: 'Process Area', risk_theme: 'Risk Theme',
    coso_component: 'COSO Component', fs_assertion: 'FS Assertion',
    fraud_risk_indicator: 'Fraud Risk Indicator',
  };

  const state = {
    facets: {},
    filters: Object.fromEntries(FACET_FIELDS.map(f => [f, []])),
    q: '',
    page: 1,
    pageSize: 20,
    total: 0,
  };

  // Separate, never-cascaded facet snapshot for the Draft tab's Sector/
  // Process Area dropdowns — see initLibraryTab()'s comment.
  let draftFacets = {};

  let searchDebounce = null;
  let librarySessionId =
    sessionStorage.getItem("library_chat_session_id") || crypto.randomUUID();
  sessionStorage.setItem("library_chat_session_id", librarySessionId);

  let initialized = false;

  function initLibraryTab() {
    if (initialized) return;
    initialized = true;
    loadFacets();
    // Draft's Sector/Process Area dropdowns want the FULL global list
    // (drafting a brand-new finding, not filtered by whatever the user
    // later selects in Browse) — populate them once, separately, from
    // their own unfiltered fetch rather than off loadFacets()'s state,
    // which cascades/narrows once Browse filters are active.
    libFetch('/facets').then(r => r.json()).then(data => {
      draftFacets = data;
      populateDraftSelects();
    });
    loadStats();
    fetchObservations();

    document.getElementById('questionInput')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') askQuestion();
    });
  }
  window.initLibraryTab = initLibraryTab;

  // ─────────────────────────────────────────────────────────────
  // Sub-tabs (Browse / Ask — Draft still exists in the DOM, just not
  // reachable from the nav; see index.html)
  // ─────────────────────────────────────────────────────────────
  function switchLibTab(name) {
    document.querySelectorAll('.lib-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.libtab === name));
    document.querySelectorAll('.lib-tab-panel').forEach(p => p.classList.toggle('active', p.id === `libtab-${name}`));
    if (name === 'ask') {
      window.CbSidebar?.hideBrowseFilters();
      window.CbSidebar?.showAskSearch();
      libraryActivateSidebar();
    } else {
      window.CbSidebar?.showBrowseFilters();
      window.CbSidebar?.hideAskSearch();
      hideAskSearchResults();
      window.CbSidebar?.hide();
    }
  }
  window.switchLibTab = switchLibTab;

  // Filters now live in the sidebar (see index.html's #cb-sidebar-browsefilters),
  // which is already a fixed-position overlay on mobile whenever it's shown
  // (chatbot.css's @media (max-width:900px) rule) — no separate mobile
  // toggle needed, so the old rail-open/close mechanism is gone.

  // ─────────────────────────────────────────────────────────────
  // Facets + filtering — cascading: once any filter or search term is
  // active, each facet's own OPTIONS are refetched conditioned on every
  // OTHER active filter (see backend data_access.get_facets), so picking
  // a Sector narrows what Risk/Process Area/etc. even show as choices.
  // ─────────────────────────────────────────────────────────────
  async function loadFacets() {
    const res = await libFetch(`/facets?${buildQuery()}`);
    state.facets = await res.json();
    renderFacetGroups();
  }

  function slug(s) {
    return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  }

  function renderFacetGroups() {
    const container = document.getElementById('facetGroups');
    // Preserve which groups the user already had open across a cascading
    // re-render — otherwise every filter click would re-collapse everything
    // back to the field==='sector'||'risk' default, which is jarring.
    const openFields = new Set(
      Array.from(container.querySelectorAll('details.facet-group[open]')).map(d => d.dataset.field)
    );
    const hasRenderedBefore = container.dataset.rendered === '1';
    container.innerHTML = '';
    container.dataset.rendered = '1';

    FACET_FIELDS.forEach(field => {
      const values = state.facets[field] || [];
      if (!values.length) return;

      const details = document.createElement('details');
      details.className = 'facet-group';
      details.dataset.field = field;
      details.open = hasRenderedBefore
        ? openFields.has(field)
        : (field === 'sector' || field === 'risk');

      const summary = document.createElement('summary');
      summary.textContent = FACET_LABELS[field];
      details.appendChild(summary);

      const list = document.createElement('div');
      list.className = 'facet-options';
      const selected = new Set(state.filters[field] || []);
      values.forEach(v => {
        const id = `f-${field}-${slug(v)}`;
        const row = document.createElement('label');
        row.className = 'checkbox-row';
        row.setAttribute('for', id);
        const checkedAttr = selected.has(v) ? 'checked' : '';
        row.innerHTML = `<input type="checkbox" id="${id}" data-field="${field}" value="${escapeAttr(v)}" ${checkedAttr} /><span>${escapeHtml(v)}</span>`;
        row.querySelector('input').addEventListener('change', onFacetToggle);
        list.appendChild(row);
      });
      details.appendChild(list);
      container.appendChild(details);
    });
  }

  function onFacetToggle(e) {
    const field = e.target.dataset.field;
    const value = e.target.value;
    const set = new Set(state.filters[field]);
    if (e.target.checked) set.add(value); else set.delete(value);
    state.filters[field] = Array.from(set);
    state.page = 1;
    fetchObservations();
    loadFacets();
  }

  function clearFilters() {
    FACET_FIELDS.forEach(f => (state.filters[f] = []));
    document.getElementById('textSearch').value = '';
    state.q = '';
    state.page = 1;
    fetchObservations();
    loadFacets();
  }
  window.clearFilters = clearFilters;

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('textSearch')?.addEventListener('input', (e) => {
      clearTimeout(searchDebounce);
      const value = e.target.value;
      searchDebounce = setTimeout(() => {
        state.q = value;
        state.page = 1;
        fetchObservations();
        loadFacets();
      }, 350);
    });
  });

  // ─────────────────────────────────────────────────────────────
  // Ask mode's sidebar quick-search — a standalone typeahead lookup,
  // completely separate from chat state and Browse's filters. Debounced
  // fetch against the same /observations endpoint Browse uses (just a
  // text query, small page size), rendered as a dropdown under the box;
  // picking a result opens its full detail popup directly, no need to
  // leave Ask or ask the chatbot a question just to look one thing up.
  // ─────────────────────────────────────────────────────────────
  let askSearchDebounce = null;

  function hideAskSearchResults() {
    const results = document.getElementById('askSidebarSearchResults');
    if (!results) return;
    results.innerHTML = '';
    results.classList.add('hidden');
  }

  async function runAskSidebarSearch(query) {
    const results = document.getElementById('askSidebarSearchResults');
    if (!results) return;
    if (!query.trim()) {
      hideAskSearchResults();
      return;
    }
    try {
      const res = await libFetch(`/observations?q=${encodeURIComponent(query)}&page=1&page_size=8`);
      const data = await res.json();
      const rows = data.rows || [];
      if (!rows.length) {
        results.innerHTML = `<div class="cb-sidebar-search-empty">No matching observations</div>`;
        results.classList.remove('hidden');
        return;
      }
      results.innerHTML = rows.map(r => `
        <button class="cb-sidebar-search-result" data-sr="${r.sr_no}">
          <span class="cb-sidebar-search-result-title">${escapeHtml(r.headline || 'Untitled finding')}</span>
          <span class="cb-sidebar-search-result-meta">${escapeHtml(r.sector || '')}${r.sector ? ' · ' : ''}${escapeHtml(r.risk || '')}</span>
        </button>`).join('');
      results.querySelectorAll('[data-sr]').forEach(btn => {
        btn.addEventListener('click', () => {
          openObsPopup(Number(btn.dataset.sr));
          hideAskSearchResults();
        });
      });
      results.classList.remove('hidden');
    } catch (err) {
      console.error(err);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('askSidebarSearch')?.addEventListener('input', (e) => {
      clearTimeout(askSearchDebounce);
      const value = e.target.value;
      askSearchDebounce = setTimeout(() => runAskSidebarSearch(value), 300);
    });
    // Click outside the search box/dropdown closes the dropdown, same
    // click-outside-to-close convention as the drawer/panel/popup.
    document.addEventListener('click', (e) => {
      const wrap = document.getElementById('cb-sidebar-asksearch');
      if (wrap && !wrap.contains(e.target)) hideAskSearchResults();
    });
  });

  // ─────────────────────────────────────────────────────────────
  // Results fetch + render
  // ─────────────────────────────────────────────────────────────
  function buildQuery() {
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    params.set('page', state.page);
    params.set('page_size', state.pageSize);
    FACET_FIELDS.forEach(f => state.filters[f].forEach(v => params.append(f, v)));
    return params.toString();
  }

  async function fetchObservations() {
    const grid = document.getElementById('obsGrid');
    grid.innerHTML = renderSkeletons(6);
    try {
      const res = await libFetch(`/observations?${buildQuery()}`);
      const data = await res.json();
      state.total = data.total;
      renderObsGrid(data.rows);
      renderResultsToolbar();
    } catch (err) {
      grid.innerHTML = `<p class="empty-state">Couldn't load observations. Please try again.</p>`;
      console.error(err);
    }
  }

  function renderSkeletons(n) {
    return Array.from({ length: n }).map(() => `<div class="obs-card skeleton"></div>`).join('');
  }

  function renderResultsToolbar() {
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    document.getElementById('resultsCount').textContent =
      state.total === 0 ? 'No observations match these filters' : `${state.total.toLocaleString()} observation${state.total === 1 ? '' : 's'}`;
    document.getElementById('pageIndicator').textContent = `Page ${state.page} of ${totalPages}`;
    document.getElementById('prevPage').disabled = state.page <= 1;
    document.getElementById('nextPage').disabled = state.page >= totalPages;
  }

  function changePage(delta) {
    const totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));
    const next = state.page + delta;
    if (next < 1 || next > totalPages) return;
    state.page = next;
    fetchObservations();
    document.querySelector('.results-area')?.scrollTo({ top: 0, behavior: 'smooth' });
  }
  window.changePage = changePage;

  function riskBadgeClass(risk) {
    const known = ['critical', 'high', 'medium', 'low'];
    const s = slug(risk);
    if (known.includes(s)) return s;
    if (s === 'n-a') return 'na';
    return 'other';
  }

  function renderObsGrid(rows) {
    const grid = document.getElementById('obsGrid');
    if (!rows.length) {
      grid.innerHTML = `<p class="empty-state">No observations match these filters.</p>`;
      return;
    }
    grid.innerHTML = rows.map(cardHtml).join('');
    grid.querySelectorAll('.obs-card[data-sr]').forEach(card => {
      card.addEventListener('click', () => openDrawer(Number(card.dataset.sr)));
    });
  }

  function cardHtml(r) {
    return `
      <article class="obs-card" data-sr="${r.sr_no}" tabindex="0">
        <div class="obs-card-badges">
          <span class="risk-badge ${riskBadgeClass(r.risk)}">${escapeHtml(r.risk || 'N/A')}</span>
          <span class="tag-chip">${escapeHtml(r.sector || '—')}</span>
          <span class="tag-chip">${escapeHtml(r.audit_type || '—')}</span>
        </div>
        <h3 class="obs-card-title">${escapeHtml(r.headline || 'Untitled finding')}</h3>
        <p class="obs-card-snippet">${escapeHtml(truncate(r.observation, 160))}</p>
        <div class="obs-card-footer">
          <span class="sr-tag">Sr. No. ${r.sr_no}</span>
          <span class="obs-card-more">View details →</span>
        </div>
      </article>`;
  }

  // ─────────────────────────────────────────────────────────────
  // Detail drawer
  // ─────────────────────────────────────────────────────────────
  async function openDrawer(srNo) {
    const backdrop = document.getElementById('drawerBackdrop');
    const drawer = document.getElementById('drawer');
    const body = document.getElementById('drawerBody');
    backdrop.classList.add('show');
    drawer.classList.add('show');
    body.innerHTML = renderSkeletons(1);

    try {
      const [detailRes, similarRes] = await Promise.all([
        libFetch(`/observations/${srNo}`),
        libFetch(`/observations/${srNo}/similar`),
      ]);
      if (!detailRes.ok) throw new Error('Not found');
      const r = await detailRes.json();
      const similar = (await similarRes.json()).rows || [];
      body.innerHTML = drawerHtml(r, similar);
      body.querySelectorAll('[data-sr]').forEach(el => {
        el.addEventListener('click', () => openDrawer(Number(el.dataset.sr)));
      });
    } catch (err) {
      body.innerHTML = `<p class="empty-state">Couldn't load this observation.</p>`;
      console.error(err);
    }
  }
  window.openDrawer = openDrawer;

  function closeDrawer() {
    document.getElementById('drawerBackdrop').classList.remove('show');
    document.getElementById('drawer').classList.remove('show');
  }
  window.closeDrawer = closeDrawer;

  function drawerHtml(r, similar) {
    const field = (label, value) => value ? `<div class="drawer-field"><div class="drawer-field-label">${label}</div><p>${escapeHtml(value)}</p></div>` : '';
    const similarHtml = similar.length
      ? similar.map(s => `
          <div class="similar-card" data-sr="${s.sr_no}">
            <span class="risk-badge ${riskBadgeClass(s.risk)} sm">${escapeHtml(s.risk || 'N/A')}</span>
            <div class="similar-title">${escapeHtml(s.headline || 'Untitled')}</div>
            <div class="similar-meta">${escapeHtml(s.sector || '')} · Sr. No. ${s.sr_no}</div>
          </div>`).join('')
      : `<p class="empty-state sm">No similar observations found.</p>`;

    return `
      <div class="drawer-header">
        <span class="risk-badge ${riskBadgeClass(r.risk)}">${escapeHtml(r.risk || 'N/A')}</span>
        <span class="sr-tag">Sr. No. ${r.sr_no}</span>
      </div>
      <h2 class="drawer-title">${escapeHtml(r.headline || 'Untitled finding')}</h2>
      <div class="obs-card-badges">
        <span class="tag-chip">${escapeHtml(r.sector || '—')}</span>
        <span class="tag-chip">${escapeHtml(r.audit_type || '—')}</span>
        <span class="tag-chip">${escapeHtml(r.process_area || '—')}</span>
        <span class="tag-chip">${escapeHtml(r.risk_theme || '—')}</span>
      </div>

      ${field('Observation', r.observation)}
      ${field('Root Cause', r.root_cause)}
      ${field('Recommendation', r.recommendation)}
      ${field('Management Action Plan', r.management_action)}

      <h4 class="drawer-section-title">Classification</h4>
      <div class="drawer-grid">
        ${field('Financial Caption Bucket', r.financial_caption_bucket)}
        ${field('Financial Statement Caption', r.financial_statement_caption)}
        ${field('Root Cause Category', r.root_cause_category)}
        ${field('IFC Control Objective', r.ifc_control_objective)}
        ${field('COSO Component', r.coso_component)}
        ${field('Fraud Risk Indicator', r.fraud_risk_indicator)}
        ${field('FS Assertion', r.fs_assertion)}
      </div>

      <h4 class="drawer-section-title">Similar observations</h4>
      <div class="similar-strip">${similarHtml}</div>
    `;
  }

  // ─────────────────────────────────────────────────────────────
  // "View N observations" panel — right-side, headline-only list for the
  // rows behind one Ask answer. Deliberately lighter than the full obs-grid
  // cards (no risk badge/snippet/sector chips) so a long result set stays
  // scannable; clicking an item opens obsPopup for that one record's detail.
  // ─────────────────────────────────────────────────────────────
  function openObsListPanel(rows) {
    document.getElementById('obsListPanelTitle').textContent =
      `${rows.length} observation${rows.length !== 1 ? 's' : ''}`;
    const body = document.getElementById('obsListPanelBody');
    body.innerHTML = rows.map(r => `
      <button class="obs-list-item" data-sr="${r.sr_no}">
        ${escapeHtml(r.headline || 'Untitled finding')}
      </button>`).join('');
    body.querySelectorAll('.obs-list-item[data-sr]').forEach(item => {
      item.addEventListener('click', () => openObsPopup(Number(item.dataset.sr)));
    });
    document.getElementById('obsListBackdrop').classList.add('show');
    document.getElementById('obsListPanel').classList.add('show');
  }
  window.openObsListPanel = openObsListPanel;

  function closeObsListPanel() {
    document.getElementById('obsListBackdrop').classList.remove('show');
    document.getElementById('obsListPanel').classList.remove('show');
  }
  window.closeObsListPanel = closeObsListPanel;

  // ─────────────────────────────────────────────────────────────
  // Single-observation popup — opened from an obsListPanel item. A native
  // <dialog> (see index.html's comment) so it needs no z-index of its own.
  // Reuses drawerHtml() for the actual content, same as the main drawer.
  // ─────────────────────────────────────────────────────────────
  async function openObsPopup(srNo) {
    const dialog = document.getElementById('obsPopup');
    const body = document.getElementById('obsPopupBody');
    body.innerHTML = renderSkeletons(1);
    if (!dialog.open) dialog.showModal();

    try {
      const [detailRes, similarRes] = await Promise.all([
        libFetch(`/observations/${srNo}`),
        libFetch(`/observations/${srNo}/similar`),
      ]);
      if (!detailRes.ok) throw new Error('Not found');
      const r = await detailRes.json();
      const similar = (await similarRes.json()).rows || [];
      body.innerHTML = drawerHtml(r, similar);
      body.querySelectorAll('[data-sr]').forEach(el => {
        el.addEventListener('click', () => openObsPopup(Number(el.dataset.sr)));
      });
    } catch (err) {
      body.innerHTML = `<p class="empty-state">Couldn't load this observation.</p>`;
      console.error(err);
    }
  }
  window.openObsPopup = openObsPopup;

  function closeObsPopup() {
    const dialog = document.getElementById('obsPopup');
    if (dialog.open) dialog.close();
  }
  window.closeObsPopup = closeObsPopup;

  // Click on the <dialog>'s own backdrop area (outside its content box)
  // closes it too, matching the drawer/panel's click-outside-to-close.
  document.getElementById('obsPopup')?.addEventListener('click', (e) => {
    if (e.target.id === 'obsPopup') closeObsPopup();
  });

  // ─────────────────────────────────────────────────────────────
  // Chat ("Ask" tab) — now with per-user persisted history
  // ─────────────────────────────────────────────────────────────
  async function askQuestion() {
    const input = document.getElementById('questionInput');
    const question = input.value.trim();
    if (!question) return;
    input.value = '';

    document.querySelector('#libtab-ask .welcome-card')?.remove();
    addMessage(question, 'user');
    const loadingMsg = addLoadingMessage();

    try {
      const res = await libFetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: librarySessionId, question, page: 1, page_size: 20 }),
      });
      const data = await res.json();
      loadingMsg.remove();
      addMessage(data.answer, 'bot', data.rows || [], data.follow_ups || [], { filters: data.filters, keywords: data.keywords });
    } catch (err) {
      loadingMsg.remove();
      addMessage('<p>Sorry, I encountered an error. Please try again.</p>', 'bot');
      console.error(err);
    }
  }
  window.askQuestion = askQuestion;

  function startNewLibraryChat() {
    librarySessionId = crypto.randomUUID();
    sessionStorage.setItem("library_chat_session_id", librarySessionId);
    const chatWindow = document.getElementById('chatWindow');
    chatWindow.innerHTML = `
      <div class="welcome-card gpt-welcome">
        <div class="welcome-icon"><svg viewBox="0 0 120 60" xmlns="http://www.w3.org/2000/svg"><text x="60" y="43" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-weight="800" font-size="40" letter-spacing="-1" fill="#ffffff">JHS</text></svg></div>
        <h2>What would you like to explore?</h2>
        <p>Ask in plain language — I'll find matching observations, cite the exact rows I used, and summarize patterns across them.</p>
        <div class="suggestion-chips">
          <button class="chip" onclick="askSuggestion('How many high risk observations are there in the Banking sector?')">📊 High risk in banking</button>
          <button class="chip" onclick="askSuggestion('What are the common root causes for inventory findings?')">🔍 Common root causes — inventory</button>
          <button class="chip" onclick="askSuggestion('Summarize the recurring themes in IT and cyber control findings')">🧵 Summarize IT/cyber themes</button>
        </div>
      </div>`;
    if (window.CbSidebar) window.CbSidebar.refreshActiveItem(librarySessionId);
  }
  window.startNewLibraryChat = startNewLibraryChat;

  // Populates the SHARED sidebar (module.js) with this bot's sessions and
  // wires its "New chat" button — called by module.js whenever the Library
  // tab's Ask sub-tab becomes the active view.
  async function libraryActivateSidebar() {
    if (!window.CbSidebar) return;
    window.CbSidebar.attach({
      activeSessionId: librarySessionId,
      onNewChat: startNewLibraryChat,
      fetchSessions: () => libFetch('/sessions').then(r => r.json()),
      onSelect: loadLibrarySession,
    });
  }
  window.libraryActivateSidebar = libraryActivateSidebar;

  async function loadLibrarySession(sessionId) {
    librarySessionId = sessionId;
    sessionStorage.setItem("library_chat_session_id", sessionId);
    try {
      const res = await libFetch(`/session/${sessionId}/messages`);
      const msgs = await res.json();
      const chatWindow = document.getElementById('chatWindow');
      chatWindow.innerHTML = '';
      msgs.forEach(m => addMessage(m.content, m.role === 'user' ? 'user' : 'bot', m.rows || []));
    } catch {
      // leave whatever was on screen
    }
  }

  // Reopens the Browse tab scoped to exactly the filters/search text a chat
  // answer was grounded in — the chat panel only ever shows a small capped
  // sample (rows[], a "View N observations" panel at most), so this is how
  // "show me ALL of them" actually gets fulfilled: Browse's own paginated,
  // filterable grid, not trying to cram everything into the chat itself.
  function viewAllInBrowse(browseFilters, keywords) {
    FACET_FIELDS.forEach(f => (state.filters[f] = (browseFilters && browseFilters[f]) || []));
    state.q = keywords || '';
    state.page = 1;
    const searchInput = document.getElementById('textSearch');
    if (searchInput) searchInput.value = state.q;
    switchLibTab('browse');
    loadFacets();
    fetchObservations();
  }
  window.viewAllInBrowse = viewAllInBrowse;

  function addMessage(text, type, rows = [], followUps = [], browseScope = null) {
    const chatWindow = document.getElementById('chatWindow');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;

    const avatar = document.createElement('div');
    avatar.className = 'gpt-avatar';
    avatar.textContent = type === 'bot' ? 'J' : 'Y';
    messageDiv.appendChild(avatar);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    // Deliberately no Sr. No. citation links in the answer text — the
    // conversation stays plain-answer only, no reference clutter. The
    // observation grid below (when there are matching rows) still lets
    // someone open the actual record if they want to.
    if (type === 'bot') {
      contentDiv.innerHTML = text;
    } else {
      contentDiv.textContent = text;
    }

    if (rows.length > 0) {
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'view-data';
      toggleBtn.textContent = `View ${rows.length} observation${rows.length !== 1 ? 's' : ''}`;
      toggleBtn.onclick = () => openObsListPanel(rows);
      // Appended inside contentDiv, not messageDiv — messageDiv is a flex
      // ROW (avatar | content), so anything appended there directly becomes
      // a THIRD flex item squeezed into leftover space instead of flowing
      // naturally below the message text (this is exactly what was making
      // the follow-up chips visually overlap the answer text).
      contentDiv.appendChild(toggleBtn);
    }

    // A filter/search scope worth reopening in Browse — only when it's
    // actually non-empty (an unscoped question has nothing meaningful to
    // jump to) and only on a fresh answer (browseScope is null when
    // replaying history — see loadLibrarySession).
    const hasScope = browseScope && (
      Object.values(browseScope.filters || {}).some(v => v && v.length) || browseScope.keywords
    );
    if (hasScope) {
      const viewAllBtn = document.createElement('button');
      viewAllBtn.className = 'view-data view-all-browse';
      viewAllBtn.innerHTML = 'View all in Browse <i class="fas fa-arrow-right"></i>';
      viewAllBtn.onclick = () => viewAllInBrowse(browseScope.filters, browseScope.keywords);
      contentDiv.appendChild(viewAllBtn);
    }

    messageDiv.appendChild(contentDiv);

    if (type === 'bot' && window.JHSChatCore) {
      window.JHSChatCore.renderFollowUps(contentDiv, followUps, (q) => askSuggestion(q));
    }

    chatWindow.appendChild(messageDiv);
    messageDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return messageDiv;
  }

  function addLoadingMessage() {
    const chatWindow = document.getElementById('chatWindow');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot';
    messageDiv.innerHTML = `<div class="gpt-avatar">J</div><div class="message-content"><div class="loading-dots"><span></span><span></span><span></span></div></div>`;
    chatWindow.appendChild(messageDiv);
    messageDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    return messageDiv;
  }

  function askSuggestion(question) {
    document.getElementById('questionInput').value = question;
    askQuestion();
  }
  window.askSuggestion = askSuggestion;

  // ─────────────────────────────────────────────────────────────
  // Draft-a-finding tab
  // ─────────────────────────────────────────────────────────────
  function populateDraftSelects() {
    const sectorSel = document.getElementById('draftSector');
    const paSel = document.getElementById('draftProcessArea');
    const opt = (v) => `<option value="${escapeAttr(v)}">${escapeHtml(v)}</option>`;
    sectorSel.innerHTML = `<option value="">Any sector</option>` + (draftFacets.sector || []).map(opt).join('');
    paSel.innerHTML = `<option value="">Any process area</option>` + (draftFacets.process_area || []).map(opt).join('');
  }

  async function generateDraft() {
    const sector = document.getElementById('draftSector').value;
    const process_area = document.getElementById('draftProcessArea').value;
    const description = document.getElementById('draftDescription').value.trim();
    const resultBox = document.getElementById('draftResult');
    const btn = document.getElementById('draftSubmitBtn');

    if (!description && !sector && !process_area) {
      resultBox.innerHTML = `<p class="empty-state">Give at least a sector, process area, or description to ground the draft.</p>`;
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Drafting…';
    resultBox.innerHTML = renderSkeletons(1);

    try {
      const res = await libFetch('/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sector, process_area, description }),
      });
      const draft = await res.json();
      renderDraftResult(draft);
    } catch (err) {
      resultBox.innerHTML = `<p class="empty-state">Couldn't generate a draft. Please try again.</p>`;
      console.error(err);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Generate draft';
    }
  }
  window.generateDraft = generateDraft;

  function renderDraftResult(draft) {
    const resultBox = document.getElementById('draftResult');
    if (draft.error) {
      resultBox.innerHTML = `<p class="empty-state">${escapeHtml(draft.error)}</p>`;
      return;
    }
    const grounded = (draft.grounded_on || []);
    const groundedHtml = grounded.length
      ? grounded.map(sr => `<span class="tag-chip clickable" data-sr="${sr}">Sr. No. ${sr}</span>`).join('')
      : `<span class="empty-state sm">Drafted without a close historical match — review carefully.</span>`;

    resultBox.innerHTML = `
      <div class="draft-card">
        <div class="draft-field-row"><label>Headline</label><textarea rows="1" id="dHeadline">${escapeHtml(draft.headline)}</textarea></div>
        <div class="draft-field-row"><label>Observation</label><textarea rows="4" id="dObservation">${escapeHtml(draft.observation)}</textarea></div>
        <div class="draft-field-row"><label>Root Cause</label><textarea rows="3" id="dRootCause">${escapeHtml(draft.root_cause)}</textarea></div>
        <div class="draft-field-row"><label>Recommendation</label><textarea rows="3" id="dRecommendation">${escapeHtml(draft.recommendation)}</textarea></div>
        <div class="draft-field-row"><label>Management Action Plan</label><textarea rows="3" id="dManagementAction">${escapeHtml(draft.management_action)}</textarea></div>
        <div class="draft-grounded"><span class="drawer-field-label">Grounded on</span><div class="grounded-chips">${groundedHtml}</div></div>
        <button class="secondary-btn" onclick="copyDraft()">Copy draft to clipboard</button>
      </div>`;

    resultBox.querySelectorAll('.tag-chip.clickable[data-sr]').forEach(el => {
      el.addEventListener('click', () => openDrawer(Number(el.dataset.sr)));
    });
  }

  function copyDraft() {
    const ids = ['dHeadline', 'dObservation', 'dRootCause', 'dRecommendation', 'dManagementAction'];
    const labels = ['Headline', 'Observation', 'Root Cause', 'Recommendation', 'Management Action Plan'];
    const text = ids.map((id, i) => `${labels[i]}: ${document.getElementById(id).value}`).join('\n\n');
    navigator.clipboard.writeText(text).then(() => {
      const btn = document.querySelector('.draft-card .secondary-btn');
      const original = btn.textContent;
      btn.textContent = 'Copied ✓';
      setTimeout(() => (btn.textContent = original), 1500);
    });
  }
  window.copyDraft = copyDraft;

  // ─────────────────────────────────────────────────────────────
  // Stats
  // ─────────────────────────────────────────────────────────────
  async function loadStats() {
    try {
      const res = await libFetch('/stats');
      if (!res.ok) return;
      const s = await res.json();
      const chips = document.getElementById('statChips');
      const riskOrder = ['Critical', 'High', 'Medium', 'Low', 'Improvement Opportunity', 'N.A.'];
      const riskChips = riskOrder
        .filter(r => s.risk_counts && s.risk_counts[r])
        .map(r => `<span class="stat-chip"><span class="risk-badge ${riskBadgeClass(r)} sm">${r}</span> ${s.risk_counts[r].toLocaleString()}</span>`)
        .join('');
      chips.innerHTML = `<span class="stat-chip total"><b>${(s.total || 0).toLocaleString()}</b> total</span>${riskChips}`;
    } catch (e) {
      console.log('Stats not available:', e);
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────────────────────────
  function truncate(text, n) {
    if (!text) return '';
    return text.length > n ? text.slice(0, n).trim() + '…' : text;
  }
  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function escapeAttr(s) {
    return escapeHtml(s);
  }
})();
