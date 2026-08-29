/* Live refresh for the Replies page.
   The page is a static server render, so after the hourly task or a dashboard
   "Scan replies" run drafts something new the operator would otherwise see
   nothing until a manual reload. This polls /replies/count every ~4s:
     - when the pending count differs from what the page rendered with, show a
       "click to refresh" affordance (auto-reload if the list was empty);
     - while a dashboard reply-scan job is running, show a subtle indicator;
     - keep the sidebar "Replies" badge in sync with reality.
   Fail-soft, like run.js: after 4 consecutive errors polling stops; never throws. */
(function () {
  var rendered = typeof window.__repliesRendered === "number"
    ? window.__repliesRendered : null;
  if (rendered === null) return;

  var refreshBtn = document.getElementById("repliesRefresh");
  var checking = document.getElementById("repliesChecking");
  var navCount = document.getElementById("replyNavCount");
  var failures = 0;
  var timer = null;
  var offered = false;

  function stop() {
    if (timer) { clearInterval(timer); timer = null; }
  }

  function updateNav(n) {
    if (!navCount || typeof n !== "number") return;
    navCount.textContent = String(n);
    navCount.hidden = !n;
  }

  function offerRefresh() {
    if (offered) return;
    offered = true;
    if (rendered === 0) { window.location.reload(); return; }
    if (refreshBtn) refreshBtn.hidden = false;
    stop();
  }

  function poll() {
    fetch("/replies/count", { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        failures = 0;
        if (checking) checking.hidden = !data.job_running;
        updateNav(data.pending);
        if (typeof data.pending === "number" && data.pending !== rendered) {
          offerRefresh();
        }
      })
      .catch(function () {
        failures++;
        if (failures >= 4) stop();
      });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", function () { window.location.reload(); });
  }

  timer = setInterval(poll, 4000);
  poll();
})();
