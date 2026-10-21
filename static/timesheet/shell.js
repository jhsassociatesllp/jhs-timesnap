// static/timesheet/shell.js - the one navigation bar for every new timesheet screen.
// Uses the existing app theme (.navbar / .hamburger / .nav-menu from styles.css). Put
//   <div id="appNav" data-active="myday"></div>   at the top of <body>, then load this script.
// The menu only hides links the person has no use for; every endpoint checks the role again.
(function () {
  "use strict";

  const host = document.getElementById("appNav");
  if (!host) return;
  const active = host.getAttribute("data-active") || "";
  const emp = (localStorage.getItem("loggedInEmployeeId") || "").trim().toUpperCase();
  const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");

  const ITEMS = [
    { id: "myday", href: "/timesheet", icon: "fa-clock", label: "My day" },
    { id: "review", href: "/static/timesheet/review.html", icon: "fa-clipboard-check", label: "Review team",
      when: (m) => m.is_admin || m.has_reportees },
    { id: "team", href: "/static/timesheet/manager.html", icon: "fa-gauge-high", label: "Team dashboard",
      when: (m) => m.is_manager || m.is_admin || m.is_partner },
    { id: "portfolio", href: "/static/timesheet/portfolio.html", icon: "fa-chart-pie", label: "Portfolio",
      when: (m) => m.is_admin || m.is_partner },
    { id: "reco", href: "/static/timesheet/reco.html", icon: "fa-scale-balanced", label: "Reconciliation",
      when: (m) => m.is_admin || m.is_manager },
    { id: "hrms", href: "/static/timesheet/hrms.html", icon: "fa-upload", label: "HRMS upload", when: (m) => m.is_admin },
    { id: "classic", href: "/static/timesheet/index.html", icon: "fa-table-list", label: "Classic timesheet & approvals" },
    { id: "modules", href: "/modules", icon: "fa-th-large", label: "Modules" },
  ];

  function el(tag, cls, attrs) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    Object.entries(attrs || {}).forEach(([k, v]) => { if (k === "text") e.textContent = v; else e.setAttribute(k, v); });
    return e;
  }

  const bar = el("div", "navbar");
  const left = el("div", "nav-left");
  const burger = el("button", "hamburger", { type: "button", "aria-label": "Menu", "aria-expanded": "false" });
  burger.append(el("i", "fas fa-bars"));
  const brand = el("a", "nav-brand", { href: "/modules", text: "JHS Timesnap" });
  left.append(burger, brand);
  const user = el("div", "nav-user", { text: emp });
  const menu = el("div", "nav-menu", { id: "navMenu", role: "menu" });
  bar.append(left, user, menu);
  host.replaceWith(bar);

  function build(m) {
    menu.textContent = "";
    ITEMS.filter((i) => !i.when || i.when(m)).forEach((i) => {
      const a = el("a", i.id === active ? "active" : "", { href: i.href, role: "menuitem" });
      a.append(el("i", "fas " + i.icon), document.createTextNode(" " + i.label));
      menu.append(a);
    });
    const out = el("button", "", { type: "button", role: "menuitem" });
    out.append(el("i", "fas fa-sign-out-alt"), document.createTextNode(" Logout"));
    out.addEventListener("click", () => {
      if (!confirm("Log out of JHS Timesnap?")) return;
      const h = { Authorization: `Bearer ${token}` };
      fetch("/logout", { method: "POST", headers: h }).finally(() => {
        localStorage.clear(); sessionStorage.clear();
        window.location.href = "/static/login.html";
      });
    });
    menu.append(out);
    if (m.name) user.textContent = `${m.name} · ${emp}`;
  }

  function setOpen(open) {
    menu.classList.toggle("active", open);
    burger.setAttribute("aria-expanded", open ? "true" : "false");
  }
  burger.addEventListener("click", (e) => { e.stopPropagation(); setOpen(!menu.classList.contains("active")); });
  document.addEventListener("click", (e) => { if (!bar.contains(e.target)) setOpen(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });

  build({});                                        // basic menu at once, role links appear when /me answers
  if (token && emp) {
    fetch("/timesheet/v2/me", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => { if (m) build(m); })
      .catch(() => { /* keep the basic menu */ });
  }
})();
