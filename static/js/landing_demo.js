/*
 * Landing-page demo: an autoplaying 6-step walkthrough of the AI exam flow.
 * Pure presentation — panels are plain markup toggled on a timer, with a
 * live countdown on the "exam" step and play/pause + clickable step dots.
 */
(function () {
  "use strict";

  var panels = Array.prototype.slice.call(document.querySelectorAll(".flow-panel"));
  var dots = Array.prototype.slice.call(document.querySelectorAll(".flow-dot"));
  var progress = document.getElementById("flow-progress");
  var count = document.getElementById("flow-count");
  var playBtn = document.getElementById("flow-play");
  var stage = document.getElementById("flow-stage");

  if (!panels.length || !progress || !playBtn) return;

  var STEP_MS = 3400;       // time per step
  var TICK_MS = 250;        // progress-bar tick
  var step = 0;
  var playing = true;
  var hoverPaused = false;
  var elapsed = 0;
  var countdownHandle = null;
  var secondsLeft = 20;

  function startCountdown() {
    stopCountdown();
    secondsLeft = 20;
    renderTimer();
    countdownHandle = setInterval(function () {
      secondsLeft = Math.max(0, secondsLeft - 1);
      renderTimer();
    }, 1000);
  }

  function stopCountdown() {
    if (countdownHandle) {
      clearInterval(countdownHandle);
      countdownHandle = null;
    }
  }

  function renderTimer() {
    var el = document.getElementById("demo-timer");
    if (!el) return;
    var mm = "00";
    var ss = String(secondsLeft).padStart(2, "0");
    el.textContent = mm + ":" + ss;
    el.className =
      "text-2xl font-extrabold tabular-nums " +
      (secondsLeft <= 10 ? "text-red-400" : "text-emerald-400");
  }

  function show(i) {
    step = (i + panels.length) % panels.length;
    panels.forEach(function (p, idx) {
      p.classList.toggle("hidden", idx !== step);
    });
    dots.forEach(function (d, idx) {
      d.classList.toggle("flow-dot-active", idx === step);
    });
    if (count) count.textContent = step + 1 + " / " + panels.length;
    elapsed = 0;
    progress.style.width = "0%";
    if (step === 4) {
      startCountdown();
    } else {
      stopCountdown();
    }
  }

  function tick() {
    if (!playing || hoverPaused) return;
    elapsed += TICK_MS;
    progress.style.width = Math.min(100, (elapsed / STEP_MS) * 100) + "%";
    if (elapsed >= STEP_MS) show(step + 1);
  }

  setInterval(tick, TICK_MS);

  playBtn.addEventListener("click", function () {
    playing = !playing;
    playBtn.textContent = playing ? "⏸" : "▶";
    if (playing && hoverPaused) hoverPaused = false;
  });

  // Pause while the pointer is over the demo so judges/visitors can read a step.
  if (stage) {
    stage.addEventListener("mouseenter", function () { hoverPaused = true; });
    stage.addEventListener("mouseleave", function () { hoverPaused = false; });
  }

  dots.forEach(function (d) {
    d.addEventListener("click", function () {
      show(parseInt(d.dataset.step, 10));
    });
  });

  show(0);
})();
