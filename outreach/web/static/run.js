/* Shared background-job runner UI for the Dashboard and the Send page.
   Expects on the page:
     #runButtons  - container with <button data-action="cold|followups|reminders|replies">
     #runStatus   - status region (role="status" aria-live="polite"), may start hidden
     #runStatusText - text node inside it
     #activityList - optional; refreshed from /activity when a job finishes
   All network calls fail soft: after 4 consecutive errors polling stops and the
   status line says contact with the app was lost. */
(function () {
  var statusBox = document.getElementById("runStatus");
  var statusText = document.getElementById("runStatusText");
  var activityList = document.getElementById("activityList");
  if (!statusBox || !statusText) return;

  var buttons = document.querySelectorAll("button[data-action]");
  if (!buttons.length) return;
  var polling = null;
  var failures = 0;
  var startedThisSession = false;

  var ICONS = {
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/></svg>',
    nudge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3 21 7l-4 4M3 11V9a4 4 0 0 1 4-4h14M7 21l-4-4 4-4M21 13v2a4 4 0 0 1-4 4H3"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    reply: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
  };
  var ICON_TONE = { clock: "amber", nudge: "slate" };

  function setButtons(disabled) {
    buttons.forEach(function (b) { b.disabled = disabled; });
  }

  function stopPolling() {
    if (polling) { clearInterval(polling); polling = null; }
  }

  function ensurePolling() {
    if (!polling) polling = setInterval(poll, 2000);
  }

  function refreshActivity() {
    if (!activityList) return;
    fetch("/activity").then(function (r) { return r.json(); })
      .then(function (items) {
        if (!items.length) {
          activityList.innerHTML = '<div class="activity-empty">Nothing has been sent yet.</div>';
          return;
        }
        activityList.innerHTML = items.slice(0, 6).map(function (it) {
          var tone = ICON_TONE[it.icon] ? " " + ICON_TONE[it.icon] : "";
          var row = document.createElement("div");
          row.className = "activity-row";
          var txt = document.createElement("span");
          txt.className = "txt";
          txt.textContent = it.text;
          row.innerHTML = '<span class="ic' + tone + '">' + (ICONS[it.icon] || ICONS.send) + '</span>';
          row.appendChild(txt);
          var ago = document.createElement("span");
          ago.className = "ago";
          ago.textContent = it.ago;
          row.appendChild(ago);
          return row.outerHTML;
        }).join("");
      })
      .catch(function () {});
  }

  function render(job) {
    if (!job || job.status === "idle") {
      statusBox.style.display = "none";
      setButtons(false);
      stopPolling();
      return;
    }
    statusBox.style.display = "flex";
    statusBox.className = "runstatus " + job.status;
    if (job.status === "running") {
      var known = startedThisSession
        ? (job.action || "job") + " — running… started " + (job.started || "")
        : "A job (" + (job.action || "?") + ") is already running — started " + (job.started || "") + ". Buttons are disabled until it finishes.";
      statusText.textContent = known;
      setButtons(true);
      ensurePolling();
    } else {
      // terminal: success / failed
      if (!startedThisSession && job.status === "success") {
        // a finished job from an earlier visit — don't nag
        statusBox.style.display = "none";
        setButtons(false);
        stopPolling();
        return;
      }
      statusText.textContent = (job.summary || job.status) + (job.finished ? "  ·  " + job.finished : "");
      setButtons(false);
      stopPolling();
      refreshActivity();
    }
  }

  function poll() {
    fetch("/run/status").then(function (r) { return r.json(); })
      .then(function (job) { failures = 0; render(job); })
      .catch(function () {
        failures++;
        if (failures >= 4) {
          stopPolling();
          statusBox.style.display = "flex";
          statusBox.className = "runstatus failed";
          statusText.textContent = "Lost contact with the app — reload the page to reconnect.";
          setButtons(false);
        }
      });
  }

  function startRun(btn) {
    startedThisSession = true;
    failures = 0;
    setButtons(true);
    fetch("/run/" + btn.getAttribute("data-action"), { method: "POST" })
      .then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
      })
      .then(function (res) {
        if (!res.ok && res.status === 409) {
          statusBox.style.display = "flex";
          statusBox.className = "runstatus running";
          statusText.textContent = "A job is already running — try again once it finishes.";
          if (res.data && res.data.job) render(res.data.job); else ensurePolling();
          return;
        }
        render(res.data.job);
        ensurePolling();
      })
      .catch(function () {
        statusBox.style.display = "flex";
        statusBox.className = "runstatus failed";
        statusText.textContent = "Couldn't start that run — lost contact with the app. Reload and try again.";
        setButtons(false);
      });
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var msg = btn.getAttribute("data-confirm");
      if (!msg) { startRun(btn); return; }
      confirmDialog({
        body: msg,
        ok: btn.getAttribute("data-confirm-ok")
      }).then(function (go) { if (go) startRun(btn); });
    });
  });

  poll();
  refreshActivity();
})();
