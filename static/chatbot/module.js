/**
 * JHS Chatbot module page controller — auth gate, the ONE header's tab
 * switcher, and the shared ChatGPT-style sidebar (new chat / chat history /
 * employee card) that HR Policy and the Library's Ask sub-tab both plug
 * into. Each tab's own content is initialized lazily the first time it's
 * opened (hr-tab.js / library.js), so a user who only ever opens HR Policy
 * never pays for loading the Library explorer's facets/stats.
 */
(function () {
  "use strict";

  const token = localStorage.getItem("access_token") || "";
  const empId = localStorage.getItem("loggedInEmployeeId") || "";

  if (!token) {
    window.location.href = "/login";
    return;
  }

  document.getElementById("logoutBtn").addEventListener("click", () => {
    localStorage.clear();
    sessionStorage.clear();
    window.location.href = "/login";
  });

  document.getElementById("loading-screen").style.display = "none";
  document.getElementById("main-content").style.display = "flex";

  // ── Shared sidebar controller ────────────────────────────────────────────
  // A single sidebar instance shows whichever bot's history is relevant to
  // the currently-active tab. Callers (hr-tab.js, library.js) hand it a
  // small config — how to fetch sessions, what to do on "new chat"/select —
  // and it owns the DOM/rendering so neither tab controller duplicates it.
  window.CbSidebar = (function () {
    const el = document.getElementById("cb-sidebar");
    const chatSection = document.getElementById("cb-sidebar-chatsection");
    const libTabsEl = document.getElementById("cb-sidebar-libtabs");
    const browseFiltersEl = document.getElementById("cb-sidebar-browsefilters");
    const askSearchEl = document.getElementById("cb-sidebar-asksearch");
    const newChatBtn = document.getElementById("cb-sidebar-newchat");
    const list = document.getElementById("cb-sidebar-list");
    let current = null;
    // Bumped on every attach()/renderList() call so a slow fetchSessions()
    // from a bot the user has since switched away from can't paint its
    // (now stale) results into the sidebar after a faster switch to a
    // different bot already rendered — without this a quick HR->RCM->HR
    // tab switch could show RCM's sessions on the HR tab if RCM's request
    // happened to resolve last.
    let renderGeneration = 0;

    async function renderList() {
      if (!current) return;
      const myGeneration = ++renderGeneration;
      list.innerHTML = '<div class="cb-sidebar-empty">Loading…</div>';
      let sessions;
      try {
        sessions = await current.fetchSessions();
      } catch {
        if (myGeneration !== renderGeneration) return;
        list.innerHTML = '<div class="cb-sidebar-empty">Couldn\'t load history</div>';
        return;
      }
      if (myGeneration !== renderGeneration) return; // superseded by a newer attach()/select while this was in flight
      if (!sessions || !sessions.length) {
        list.innerHTML = '<div class="cb-sidebar-empty">No chats yet</div>';
        return;
      }
      list.innerHTML = "";
      sessions.forEach((s) => {
        const item = document.createElement("div");
        item.className = "cb-sidebar-item" + (s.id === current.activeSessionId ? " active" : "");
        item.textContent = s.title;
        item.title = s.title;
        item.addEventListener("click", () => {
          if (!current) return;
          current.activeSessionId = s.id;
          current.onSelect(s.id);
          renderList();
        });
        list.appendChild(item);
      });
    }

    newChatBtn.addEventListener("click", () => {
      if (!current || !current.onNewChat) return;
      current.onNewChat();
      renderList();
    });

    return {
      // config: { activeSessionId, onNewChat(), fetchSessions() -> Promise<[{id,title}]>, onSelect(id) }
      attach(config) {
        current = config;
        el.classList.remove("hidden");
        chatSection.classList.remove("hidden");
        renderList();
      },
      // Hides just the chat-history section (new chat / history / account) —
      // NOT the whole sidebar, since Observation Library's Browse/Ask switch
      // (libTabsEl) can still need to stay visible (e.g. while Browse, not
      // Ask, is the active sub-tab). Which OUTER tab is active — and whether
      // the sidebar shows at all — is managed separately by switchCbTab
      // below via showOuter()/hideOuter().
      hide() {
        chatSection.classList.add("hidden");
        current = null;
        renderGeneration++; // discard any in-flight fetchSessions() from before this hide()
      },
      showOuter() {
        el.classList.remove("hidden");
      },
      hideOuter() {
        el.classList.add("hidden");
      },
      showLibTabs() {
        libTabsEl.classList.remove("hidden");
      },
      hideLibTabs() {
        libTabsEl.classList.add("hidden");
      },
      showBrowseFilters() {
        browseFiltersEl?.classList.remove("hidden");
      },
      hideBrowseFilters() {
        browseFiltersEl?.classList.add("hidden");
      },
      showAskSearch() {
        askSearchEl?.classList.remove("hidden");
      },
      hideAskSearch() {
        askSearchEl?.classList.add("hidden");
      },
      refreshActiveItem(newActiveId) {
        if (!current) return;
        current.activeSessionId = newActiveId;
        renderList();
      },
      setUser(name, empid) {
        const initial = (name || empid || "?").trim().charAt(0).toUpperCase();
        document.getElementById("cb-sidebar-avatar").textContent = initial;
        document.getElementById("cb-sidebar-name").textContent = name || empid || "—";
        document.getElementById("cb-sidebar-empid").textContent = empid || "—";
      },
    };
  })();
  window.CbSidebar.setUser(null, empId);

  // Personalized greeting — handed off to hr-tab.js's welcome + the sidebar's
  // account card once resolved.
  window.jhsUserName = null;
  (async function loadGreeting() {
    try {
      const data = await window.JHSChatCore.api("GET", "/chatbot/me");
      if (data && data.name) {
        window.jhsUserName = data.name;
        window.CbSidebar.setUser(data.name, empId);
        window.onJhsGreetingReady && window.onJhsGreetingReady(data.name);
      }
    } catch {
      // not logged in yet, or endpoint unavailable — generic state stays
    }
  })();

  const initialized = { hr: false, rcm: false, library: false };

  function switchCbTab(name) {
    document.querySelectorAll(".cb-tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.cbtab === name));
    document.querySelectorAll(".cb-panel").forEach((p) => p.classList.toggle("active", p.id === `cbtab-${name}`));

    if (name === "hr") {
      if (!initialized.hr) {
        initialized.hr = true;
        window.initHrTab && window.initHrTab();
      }
      window.CbSidebar.showOuter();
      window.CbSidebar.hideLibTabs();
      window.CbSidebar.hideBrowseFilters();
      window.CbSidebar.hideAskSearch();
      window.hrActivateSidebar && window.hrActivateSidebar();
    } else if (name === "rcm") {
      if (!initialized.rcm) {
        initialized.rcm = true;
        window.initRcmTab && window.initRcmTab();
      }
      window.CbSidebar.showOuter();
      window.CbSidebar.hideLibTabs();
      window.CbSidebar.hideBrowseFilters();
      window.CbSidebar.hideAskSearch();
      window.rcmActivateSidebar && window.rcmActivateSidebar();
    } else if (name === "library") {
      if (!initialized.library) {
        initialized.library = true;
        window.initLibraryTab && window.initLibraryTab();
      }
      // The Library tab owns its own sub-tabs (Browse/Ask) — the Browse/Ask
      // switch itself (libTabs) stays visible either way; only the chat
      // history section (and the Browse-only search/filters block, and the
      // Ask-only quick-search box) depends on which sub-tab is current.
      window.CbSidebar.showOuter();
      window.CbSidebar.showLibTabs();
      const askActive = document.getElementById("libtab-ask")?.classList.contains("active");
      if (askActive) {
        window.CbSidebar.hideBrowseFilters();
        window.CbSidebar.showAskSearch();
        window.libraryActivateSidebar && window.libraryActivateSidebar();
      } else {
        window.CbSidebar.showBrowseFilters();
        window.CbSidebar.hideAskSearch();
        window.CbSidebar.hide();
      }
    } else {
      window.CbSidebar.hideOuter();
    }
  }
  window.switchCbTab = switchCbTab;

  // HR Policy opens by default
  switchCbTab("hr");
})();
