/* Live timer counter — elapsed from server start time (survives background tabs). */
(function () {
  const el = document.getElementById('timer-elapsed');
  if (!el) return;

  const startedAt = el.dataset.startedAt;
  if (!startedAt) return;

  const startMs = Date.parse(startedAt.replace('Z', '+00:00'));
  if (Number.isNaN(startMs)) return;

  function elapsedSeconds() {
    return Math.max(0, Math.floor((Date.now() - startMs) / 1000));
  }

  function fmt(s) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const mm = String(m).padStart(2, '0');
    const ss = String(sec).padStart(2, '0');
    return h > 0 ? h + ':' + mm + ':' + ss : mm + ':' + ss;
  }

  function render() {
    el.textContent = fmt(elapsedSeconds());
  }

  render();
  setInterval(render, 1000);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) render();
  });
})();
