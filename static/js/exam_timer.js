/*
 * Exam timer client.
 *
 * DISPLAY ONLY — the server is authoritative. Every timer shown here is
 * derived from server-written timestamps, and every submission/heartbeat is
 * validated server-side (see exams/services.py). The client can neither
 * extend a deadline nor decide what happens when one expires.
 */
(function () {
  "use strict";

  var csrf = getCookie("csrftoken");
  var timerHandle = null;
  var inFlight = false;

  function getCookie(name) {
    var match = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[2]) : "";
  }

  function fmt(seconds) {
    seconds = Math.max(0, Math.ceil(seconds));
    var m = Math.floor(seconds / 60);
    var s = seconds % 60;
    return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf,
      },
      body: body ? JSON.stringify(body) : "{}",
      credentials: "same-origin",
    }).then(function (r) {
      if (!r.ok) throw new Error("Request failed: " + r.status);
      return r.json();
    });
  }

  function showFlash(text, ok) {
    var el = document.getElementById("flash");
    if (!el || !text) return;
    el.textContent = text;
    el.className =
      "fixed top-6 left-1/2 -translate-x-1/2 px-6 py-3 rounded-xl font-bold text-sm shadow-2xl z-50 " +
      (ok === false
        ? "bg-red-900/90 border border-red-600 text-red-100"
        : "bg-emerald-900/90 border border-emerald-600 text-emerald-100");
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.classList.add("hidden"); }, 2600);
  }

  function attachCard() {
    var card = document.getElementById("question-card");
    if (!card) return;
    var questionDeadline =
      parseInt(card.dataset.questionDeadline, 10) * 1000 +
      parseInt(card.dataset.timeLimit, 10) * 1000;
    var overallDeadline = parseInt(card.dataset.overallDeadline, 10);
    var timeLimit = parseInt(card.dataset.timeLimit, 10);

    var qTimer = document.getElementById("q-timer");
    var qProgress = document.getElementById("q-progress");
    var overallTimer = document.getElementById("overall-timer");

    clearInterval(timerHandle);
    timerHandle = setInterval(function () {
      var now = Date.now();
      var qLeft = (questionDeadline - now) / 1000;
      var oLeft = (overallDeadline - now) / 1000;

      if (qTimer) qTimer.textContent = fmt(qLeft);
      if (qProgress) qProgress.style.width = Math.max(0, Math.min(100, (qLeft / timeLimit) * 100)) + "%";
      if (overallTimer) overallTimer.textContent = fmt(oLeft);

      // Colour shift as time runs out (display only).
      if (qTimer) {
        qTimer.className = "text-3xl font-extrabold tabular-nums " +
          (qLeft > timeLimit * 0.4 ? "text-emerald-400" : qLeft > 10 ? "text-amber-400" : "text-red-400");
      }
      if (qProgress) {
        qProgress.className = "h-full rounded-full transition-all duration-300 " +
          (qLeft > timeLimit * 0.4 ? "bg-emerald-500" : qLeft > 10 ? "bg-amber-500" : "bg-red-500");
      }

      if (qLeft <= 0 || oLeft <= 0) {
        submitAnswer(true);
      }
    }, 250);
  }

  function gatherAnswer() {
    var checked = document.querySelector('input[name="answer"]:checked');
    if (checked) return checked.value;
    var textarea = document.querySelector('textarea[name="answer"]');
    if (textarea) return textarea.value;
    return null;
  }

  function submitAnswer(expired) {
    if (inFlight) return;
    inFlight = true;
    var card = document.getElementById("question-card");
    var attemptId = card.dataset.attemptId;
    var btn = document.getElementById("submit-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Submitting…"; }

    post("/student/exam-attempts/" + attemptId + "/answer/", { answer: gatherAnswer() })
      .then(function (data) {
        inFlight = false;
        if (data.status === "finished") {
          window.location.href = data.url;
          return;
        }
        document.getElementById("question-container").innerHTML = data.html;
        showFlash(data.flash, !(data.flash && data.flash.indexOf("✗") === 0));
        attachCard();
      })
      .catch(function (err) {
        inFlight = false;
        if (btn) { btn.disabled = false; btn.textContent = "Submit answer →"; }
        showFlash("Connection issue — retrying…", false);
      });
  }

  document.addEventListener("submit", function (e) {
    if (e.target && e.target.id === "answer-form") {
      e.preventDefault();
      submitAnswer(false);
    }
  });

  // Heartbeat: even if the tab is backgrounded, the server independently
  // checks expiry and force-advances when a question's time has lapsed.
  setInterval(function () {
    var card = document.getElementById("question-card");
    if (!card || inFlight) return;
    post("/student/exam-attempts/" + card.dataset.attemptId + "/heartbeat/")
      .then(function (data) {
        if (data.status === "finished") {
          window.location.href = data.url;
          return;
        }
        if (data.changed) {
          document.getElementById("question-container").innerHTML = data.html;
          showFlash("⏱ Time's up — auto-advanced by the server.", false);
          attachCard();
        }
      })
      .catch(function () { /* transient — next beat will retry */ });
  }, 5000);

  attachCard();
})();
