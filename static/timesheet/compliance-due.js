/* Compliance due-date reminders: scrolling marquee (due within 5 days), the due-dates modal
   (all dates of one compliance, or everything due this week) and the once-per-login popup. */
(function () {
  var MARQUEE_DAYS = 7, WEEK_DAYS = 7;
  var MN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var itemsPromise = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function startOfToday() { var n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); }
  function daysLeft(iso) {
    var p = iso.split("-");
    return Math.round((new Date(+p[0], p[1] - 1, +p[2]) - startOfToday()) / 86400000);
  }
  function fmtDate(iso) { var p = iso.split("-"); return +p[2] + " " + MN[p[1] - 1] + " " + p[0]; }
  function leftText(n) { return n === 0 ? "Due today" : n === 1 ? "1 day left" : n + " days left"; }
  function urgency(n) { return n <= 1 ? "hot" : n <= 3 ? "warm" : "cool"; }

  function loadItems() {
    if (!itemsPromise) {
      var token = localStorage.getItem("access_token") || "";
      itemsPromise = fetch("/compliance-calendar/items", { headers: { Authorization: "Bearer " + token } })
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .then(function (d) { return d.items || []; })
        .catch(function () { return []; });
    }
    return itemsPromise;
  }
  function upcoming(items, maxDays) {
    return items.map(function (i) { return Object.assign({ left: daysLeft(i.date) }, i); })
      .filter(function (i) { return i.left >= 0 && i.left <= maxDays; });
  }

  var styled = false;
  function addStyle() {
    if (styled) return; styled = true;
    var s = document.createElement("style");
    s.textContent =
      "#complianceMarquee{display:none;background:#fff7e6;border-bottom:2px solid #f5b041;overflow:hidden;position:relative;white-space:nowrap}" +
      "#complianceMarquee.show{display:flex;align-items:center}" +
      "#complianceMarquee .cm-label{flex:none;z-index:1;background:#e67e22;color:#fff;font-weight:700;font-size:.8rem;padding:.55rem 1rem;letter-spacing:.04em;display:flex;align-items:center;gap:.4rem}" +
      "#complianceMarquee .cm-track{flex:1;overflow:hidden}" +
      "#complianceMarquee .cm-move{display:inline-flex;padding-left:100%;animation:cmScroll var(--cm-dur,20s) linear infinite}" +
      "#complianceMarquee:hover .cm-move{animation-play-state:paused}" +
      "@keyframes cmScroll{from{transform:translateX(0)}to{transform:translateX(-100%)}}" +
      "#complianceMarquee .cm-item{background:none;border:0;font:inherit;font-size:.86rem;color:#5d3a00;padding:.5rem 0;margin-right:5rem;cursor:pointer;display:inline-flex;align-items:center;gap:.45rem}" +
      "#complianceMarquee .cm-item:hover .cm-txt{text-decoration:underline}" +
      ".cd-pill{display:inline-block;font-size:.72rem;font-weight:700;padding:.12rem .6rem;border-radius:20px;color:#fff;white-space:nowrap}" +
      ".cd-pill.hot{background:#c0392b}.cd-pill.warm{background:#e67e22}.cd-pill.cool{background:#2e86c1}" +
      ".cd-law{font-size:.7rem;font-weight:700;padding:.1rem .5rem;border-radius:6px;background:#5d3a00;color:#fff}" +
      "@media(prefers-reduced-motion:reduce){#complianceMarquee .cm-move{animation:none}#complianceMarquee .cm-track{overflow-x:auto}}" +
      "#complianceModal{display:none;position:fixed;inset:0;z-index:2100;background:rgba(15,20,32,.6);align-items:center;justify-content:center;padding:1rem}" +
      "#complianceModal.open{display:flex}" +
      "#complianceModal .cd-box{background:#fff;border-radius:16px;width:100%;max-width:640px;max-height:86vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 50px rgba(0,0,0,.35);color:#2c3e50;font-family:'Inter','Segoe UI',sans-serif}" +
      "#complianceModal .cd-head{background:linear-gradient(135deg,#f39c12,#e67e22);color:#fff;padding:1rem 1.3rem;display:flex;gap:1rem;align-items:flex-start;justify-content:space-between}" +
      "#complianceModal .cd-head h3{margin:0;font-size:1.05rem;line-height:1.35}" +
      "#complianceModal .cd-head p{margin:.2rem 0 0;font-size:.82rem;opacity:.92}" +
      "#complianceModal .cd-x{flex:none;background:rgba(255,255,255,.22);border:0;color:#fff;width:32px;height:32px;border-radius:50%;cursor:pointer}" +
      "#complianceModal .cd-list{list-style:none;margin:0;padding:.5rem 1.1rem 1rem;overflow:auto}" +
      "#complianceModal .cd-row{display:flex;gap:.9rem;align-items:center;justify-content:space-between;padding:.7rem .2rem;border-bottom:1px solid #eef1f5}" +
      "#complianceModal .cd-row:last-child{border-bottom:0}" +
      "#complianceModal .cd-main{min-width:0}" +
      "#complianceModal .cd-date{font-weight:700;font-size:.92rem}" +
      "#complianceModal .cd-sub{font-size:.82rem;color:#5b6b7a;margin-top:.15rem;display:flex;gap:.5rem;align-items:flex-start}" +
      "#complianceModal .cd-empty{padding:2rem 1rem;text-align:center;color:#7f8c8d}" +
      "#complianceModal .cd-foot{padding:.8rem 1.3rem;border-top:1px solid #eef1f5;text-align:right}" +
      "#complianceModal .cd-ok{background:linear-gradient(135deg,#f39c12,#e67e22);color:#fff;border:0;border-radius:9px;padding:.55rem 1.4rem;font-weight:600;cursor:pointer;font-family:inherit}";
    document.head.appendChild(s);
  }

  function buildModal() {
    var m = document.getElementById("complianceModal");
    if (m) return m;
    addStyle();
    m = document.createElement("div");
    m.id = "complianceModal";
    m.innerHTML =
      '<div class="cd-box" role="dialog" aria-modal="true" aria-labelledby="cdTitle"><div class="cd-head"><div><h3 id="cdTitle"></h3><p id="cdSub"></p></div>' +
      '<button class="cd-x" type="button" aria-label="Close"><i class="fas fa-times"></i></button></div>' +
      '<ul class="cd-list" id="cdList"></ul><div class="cd-foot"><button class="cd-ok" type="button">Got it</button></div></div>';
    document.body.appendChild(m);
    m.addEventListener("click", function (e) { if (e.target === m) closeComplianceModal(); });
    m.querySelector(".cd-x").addEventListener("click", closeComplianceModal);
    m.querySelector(".cd-ok").addEventListener("click", closeComplianceModal);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeComplianceModal(); });
    return m;
  }

  function row(i, showCompliance) {
    var n = i.left;
    return '<li class="cd-row"><div class="cd-main"><div class="cd-date">' + esc(fmtDate(i.date)) + "</div>" +
      (showCompliance ? '<div class="cd-sub"><span class="cd-law">' + esc(i.law) + "</span><span>" + esc(i.compliance) + "</span></div>" : "") +
      '</div><span class="cd-pill ' + urgency(n) + '">' + leftText(n) + "</span></li>";
  }

  /* opts: {group} -> every upcoming due date of that compliance; {week:true} -> all due within 7 days */
  window.openComplianceModal = function (opts) {
    opts = opts || {};
    var m = buildModal();
    loadItems().then(function (items) {
      var title, sub, rows, withText = true;
      if (opts.group) {
        var all = items.filter(function (i) { return i.group === opts.group; })
          .map(function (i) { return Object.assign({ left: daysLeft(i.date) }, i); })
          .filter(function (i) { return i.left >= 0; });
        title = all.length ? all[0].compliance : "Compliance";
        sub = all.length ? all[0].law + " · all upcoming due dates" : "";
        rows = all; withText = false;
      } else {
        rows = upcoming(items, WEEK_DAYS);
        title = "Compliance due this week";
        sub = "Due in the next " + WEEK_DAYS + " days";
      }
      m.querySelector("#cdTitle").textContent = title;
      m.querySelector("#cdSub").textContent = sub;
      m.querySelector("#cdList").innerHTML = rows.length ? rows.map(function (r) { return row(r, withText); }).join("")
        : '<li class="cd-empty">No upcoming due dates.</li>';
      m.classList.add("open");
    });
  };
  window.closeComplianceModal = function () {
    var m = document.getElementById("complianceModal");
    if (m) m.classList.remove("open");
  };

  /* Marquee: items due within MARQUEE_DAYS (today included). */
  window.initComplianceMarquee = function () {
    var host = document.getElementById("complianceMarquee");
    if (!host) return Promise.resolve();
    addStyle();
    return loadItems().then(function (items) {
      var due = upcoming(items, MARQUEE_DAYS);
      if (!due.length) { host.className = ""; return; }
      var html = due.map(function (i, idx) {
        var txt = i.compliance.length > 90 ? i.compliance.slice(0, 88) + "…" : i.compliance;
        return '<button type="button" class="cm-item" data-g="' + esc(i.group) + '" title="' + esc(i.compliance) + '">' +
          '<span class="cd-law">' + esc(i.law) + '</span><span class="cm-txt">' + esc(txt) + "</span>" +
          '<span class="cd-pill ' + urgency(i.left) + '">' + esc(fmtDate(i.date).slice(0, -5)) + " · " + leftText(i.left) + "</span></button>";
      }).join("");
      host.innerHTML = '<div class="cm-label"><i class="fas fa-bell"></i> COMPLIANCE DUE</div><div class="cm-track"><div class="cm-move">' + html + "</div></div>";
      host.className = "show";
      // constant speed (px/s): enters at the right edge, leaves past the left edge, then repeats
      var mv = host.querySelector(".cm-move");
      host.style.setProperty("--cm-dur", Math.max(5, mv.scrollWidth / 160) + "s");
      host.onclick = function (e) {
        var b = e.target.closest(".cm-item");
        if (b) window.openComplianceModal({ group: b.dataset.g });
      };
    });
  };

  /* Once per login: show everything due this week, if there is anything. */
  window.showWeeklyComplianceOnLogin = function () {
    var flag = "complianceWeekShown";
    try { if (sessionStorage.getItem(flag)) return; } catch (e) {}
    loadItems().then(function (items) {
      try { sessionStorage.setItem(flag, "1"); } catch (e) {}
      if (upcoming(items, WEEK_DAYS).length) window.openComplianceModal({ week: true });
    });
  };
})();
