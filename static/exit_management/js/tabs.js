/* tabs.js - switch between the tabs of Employee Exit Management WITHOUT leaving the page: the IT Clearance / HR Clearance /
   My Team Member Details tabs open in a frame under the tab bar, so the address bar stays on the page the person opened.
   The tab that is active when the page loads is the "home" tab; clicking it brings the page's own content back. */
(function () {
  const tabs = document.querySelector('.ex-tabs');
  if (!tabs || new URLSearchParams(location.search).get('embed')) return;

  // ── a popup that belongs to THIS (top) page. A tab frame cannot cover the whole screen, so it asks us to open the popup here
  //    (message {exitPopup: {title, url}}); when the form inside the popup is submitted, or the popup is closed, the tab frame is told to refresh.
  let popup = null;
  const tabFrame = () => document.querySelector('#exTabPanel iframe');
  const buildPopup = () => {
    popup = document.createElement('div'); popup.className = 'ex-popup ex-light'; popup.hidden = true;
    popup.innerHTML = '<div class="ex-popup-box" role="dialog" aria-modal="true"><div class="ex-popup-top"><h2></h2>' +
                      '<button type="button" class="ex-close-btn">Close</button></div><iframe title="Form"></iframe></div>';
    document.body.appendChild(popup);
    popup.querySelector('.ex-close-btn').addEventListener('click', () => closePopup(false));
    popup.addEventListener('mousedown', e => { if (e.target === popup) closePopup(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !popup.hidden) closePopup(false); });
  };
  const closePopup = done => {
    popup.hidden = true; popup.querySelector('iframe').src = 'about:blank';
    const f = tabFrame(); if (f && f.contentWindow) f.contentWindow.postMessage({ exitRefresh: true, done: !!done }, location.origin);
  };
  window.addEventListener('message', e => {
    if (e.origin !== location.origin || !e.data) return;
    const f = tabFrame();
    if (e.data.exitPopup && f && e.source === f.contentWindow) {                 // a tab frame wants a popup
      if (!popup) buildPopup();
      popup.querySelector('h2').textContent = e.data.exitPopup.title || '';
      popup.querySelector('iframe').src = e.data.exitPopup.url + '&embed=1';
      popup.hidden = false;
    } else if (e.data.exitEmbed === 'done' && popup && !popup.hidden && e.source === popup.querySelector('iframe').contentWindow) {
      closePopup(true);                                                         // the form in the popup was submitted
    }
  });
  const home = tabs.querySelector('.ex-tab.active');
  if (!home) return;
  const holder = tabs.parentElement;
  const panel = document.createElement('div'); panel.id = 'exTabPanel'; panel.hidden = true;
  const frame = document.createElement('iframe'); frame.title = 'Exit Management'; panel.appendChild(frame);
  tabs.after(panel);

  const inline = a => {                                           // tabs that open inside this page
    if (!a.matches('a.ex-tab[href]')) return false;
    const path = new URL(a.href, location.href).pathname;
    return /^\/exit-management\/(it-clearance|hr-clearance|manager)$/.test(path) && path !== location.pathname;
  };
  const setActive = el => { tabs.querySelectorAll('.ex-tab').forEach(t => t.classList.toggle('active', t === el)); };
  const showHome = () => {
    panel.hidden = true; frame.src = 'about:blank';
    [...holder.children].forEach(c => { if (c !== tabs && c !== panel) c.classList.remove('ex-tab-hidden'); });
    setActive(home);
  };
  const showPanel = a => {
    [...holder.children].forEach(c => { if (c !== tabs && c !== panel) c.classList.add('ex-tab-hidden'); });
    frame.src = new URL(a.href, location.href).pathname + '?embed=tab';
    panel.hidden = false; setActive(a);
  };

  tabs.addEventListener('click', e => {
    const a = e.target.closest('.ex-tab'); if (!a || !tabs.contains(a)) return;
    if (a === home || (a.matches('a[href]') && new URL(a.href, location.href).pathname === location.pathname)) { e.preventDefault(); showHome(); return; }
    if (inline(a)) { e.preventDefault(); showPanel(a); }
  });
})();
