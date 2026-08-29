/* Templates tab — Gmail-style message library.
   - left rail switches the visible message with a quick fade (no reload)
   - a dirty message warns before you navigate away from it
   - variable chips insert {{ var }} at the caret of the last-focused field
   - the preview panel re-renders from /templates/preview as you type
   Saving is a normal form POST (redirects back to ?m=<key>); everything here is
   progressive enhancement over a page that already works without JS. */
(function () {
  var rail = document.querySelector(".tmpl-list");
  var pane = document.querySelector(".tmpl-pane");
  if (!rail || !pane) return;

  var links = Array.prototype.slice.call(rail.querySelectorAll(".tmpl-link"));
  var panels = Array.prototype.slice.call(pane.querySelectorAll(".tmpl-msg"));

  function panel(key) {
    return panels.filter(function (p) { return p.dataset.msg === key; })[0];
  }
  function currentKey() {
    var active = panels.filter(function (p) { return !p.hidden; })[0];
    return active ? active.dataset.msg : (panels[0] && panels[0].dataset.msg);
  }

  // ---- dirty tracking -------------------------------------------------
  var submitting = false;
  panels.forEach(function (p) {
    var form = p.querySelector(".tmpl-form");
    var flag = p.querySelector(".tmpl-dirty");
    if (!form) return;
    form.addEventListener("input", function () {
      form.dataset.dirty = "1";
      if (flag) flag.hidden = false;
    });
    form.addEventListener("submit", function () {
      submitting = true;
      delete form.dataset.dirty;
    });
  });
  window.addEventListener("beforeunload", function (e) {
    if (submitting) return;
    var dirty = panels.some(function (p) {
      var f = p.querySelector(".tmpl-form");
      return f && f.dataset.dirty;
    });
    if (dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  // ---- switching messages -------------------------------------------
  function show(key) {
    if (key === currentKey()) return;
    var from = panel(currentKey());
    var to = panel(key);
    if (!to) return;

    var fromForm = from && from.querySelector(".tmpl-form");
    if (fromForm && fromForm.dataset.dirty) {
      var ask = window.confirmDialog
        ? window.confirmDialog({
            title: "Unsaved changes",
            body: "This message has edits you haven't saved. Switch anyway and lose them?",
            ok: "Discard & switch", danger: true,
          })
        : Promise.resolve(window.confirm("Discard unsaved changes to this message?"));
      ask.then(function (go) {
        if (!go) return;
        delete fromForm.dataset.dirty;
        var flag = from.querySelector(".tmpl-dirty");
        if (flag) flag.hidden = true;
        fromForm.reset();
        commit(key, to);
      });
      return;
    }
    commit(key, to);
  }

  function commit(key, to) {
    panels.forEach(function (p) { p.hidden = p.dataset.msg !== key; });
    links.forEach(function (l) {
      var on = l.dataset.msg === key;
      l.classList.toggle("active", on);
      l.setAttribute("aria-pressed", on ? "true" : "false");
    });
    try { history.replaceState(null, "", "?m=" + encodeURIComponent(key)); } catch (err) {}
    autosize(to);
    refreshPreview(to);
    var h = to.querySelector("h2");
    if (h) h.setAttribute("tabindex", "-1"), h.focus();
  }

  links.forEach(function (l) {
    l.addEventListener("click", function () { show(l.dataset.msg); });
  });

  // ---- textarea autosize (hidden panels report scrollHeight 0) ------
  function autosize(p) {
    p.querySelectorAll("textarea.tmpl-body").forEach(function (t) {
      t.style.height = "auto";
      t.style.height = Math.min(t.scrollHeight + 2, window.innerHeight * 0.6) + "px";
    });
  }

  // ---- variable chips ---------------------------------------------
  var lastField = new WeakMap(); // panel -> last focused input/textarea
  panels.forEach(function (p) {
    p.querySelectorAll(".tmpl-subject, .tmpl-body").forEach(function (f) {
      f.addEventListener("focus", function () { lastField.set(p, f); });
    });
    p.querySelectorAll(".varchip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var f = lastField.get(p) || p.querySelector(".tmpl-body") || p.querySelector(".tmpl-subject");
        if (!f) return;
        var token = "{{ " + chip.dataset.var + " }}";
        var s = f.selectionStart != null ? f.selectionStart : f.value.length;
        var e = f.selectionEnd != null ? f.selectionEnd : f.value.length;
        f.value = f.value.slice(0, s) + token + f.value.slice(e);
        f.focus();
        f.selectionStart = f.selectionEnd = s + token.length;
        f.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
  });

  // ---- live preview ---------------------------------------------
  var timers = new WeakMap();
  function refreshPreview(p) {
    var subjEl = p.querySelector(".tmpl-subject");
    var bodyEl = lastFocusedBody(p) || p.querySelector(".tmpl-body");
    var outSubj = p.querySelector("[data-preview-subject]");
    var outBody = p.querySelector("[data-preview-body]");
    if (!outSubj || !outBody) return;
    var data = new URLSearchParams();
    if (subjEl) data.set("subject", subjEl.value);
    if (bodyEl) data.set("body", bodyEl.value);
    fetch("/templates/preview", { method: "POST", body: data })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        var err = res.errors || {};
        outSubj.textContent = err.subject ? "Template error: " + err.subject : (res.subject || "");
        outSubj.classList.toggle("is-error", !!err.subject);
        outBody.textContent = err.body ? "Template error: " + err.body : (res.body || "");
        outBody.classList.toggle("is-error", !!err.body);
      })
      .catch(function () { /* preview is best-effort */ });
  }
  function lastFocusedBody(p) {
    var f = lastField.get(p);
    return f && f.classList.contains("tmpl-body") ? f : null;
  }
  panels.forEach(function (p) {
    p.querySelectorAll(".tmpl-subject, .tmpl-body").forEach(function (f) {
      f.addEventListener("input", function () {
        clearTimeout(timers.get(p));
        timers.set(p, setTimeout(function () { refreshPreview(p); }, 350));
      });
    });
  });

  // ---- initial paint ----------------------------------------------
  var open = panel(currentKey());
  if (open) { autosize(open); refreshPreview(open); }
})();
