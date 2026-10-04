/* L&D Calendar modal — opens static/timesheet/calendar.html in a full-screen overlay */
(function () {
  function build() {
    if (document.getElementById("ldCalendarModal")) return;
    const style = document.createElement("style");
    style.textContent =
      "#ldCalendarModal{display:none;position:fixed;inset:0;z-index:2000;background:rgba(15,20,32,.75);}" +
      "#ldCalendarModal.open{display:block;}" +
      "#ldCalendarModal .ldc-box{position:absolute;inset:3vh 3vw;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 20px 40px rgba(0,0,0,.35);display:flex;flex-direction:column;}" +
      "#ldCalendarModal .ldc-bar{background:#2c3e50;color:#fff;padding:.7rem 1.2rem;display:flex;align-items:center;justify-content:space-between;font-weight:600;}" +
      "#ldCalendarModal .ldc-close{background:rgba(255,255,255,.15);border:none;color:#fff;width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:1rem;}" +
      "#ldCalendarModal .ldc-close:hover{background:#ee5a52;}" +
      "#ldCalendarModal iframe{flex:1;width:100%;border:0;background:#fff;}" +
      "@media(max-width:600px){#ldCalendarModal .ldc-box{inset:0;border-radius:0;}}";
    document.head.appendChild(style);

    const modal = document.createElement("div");
    modal.id = "ldCalendarModal";
    modal.innerHTML =
      '<div class="ldc-box"><div class="ldc-bar"><span><i class="fas fa-calendar-days"></i> L&amp;D Calendar FY 2026–27</span>' +
      '<button class="ldc-close" type="button" aria-label="Close calendar"><i class="fas fa-times"></i></button></div>' +
      '<iframe title="L&D Calendar" loading="lazy"></iframe></div>';
    document.body.appendChild(modal);
    modal.addEventListener("click", function (e) {
      if (e.target === modal) closeLdCalendar();
    });
    modal.querySelector(".ldc-close").addEventListener("click", closeLdCalendar);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeLdCalendar();
    });
  }

  window.openLdCalendar = function () {
    build();
    const modal = document.getElementById("ldCalendarModal");
    const frame = modal.querySelector("iframe");
    if (!frame.getAttribute("src")) frame.setAttribute("src", "/static/timesheet/calendar.html");
    modal.classList.add("open");
    const menu = document.getElementById("navMenu");
    if (menu) menu.classList.remove("active");
  };

  window.closeLdCalendar = function () {
    const modal = document.getElementById("ldCalendarModal");
    if (modal) modal.classList.remove("open");
  };
})();
