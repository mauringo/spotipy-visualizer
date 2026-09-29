// Playback must be confirmed idle; failed requests never count as stopped music.
class IdleClock {
  constructor(checks = 3) {
    this.checks = checks;
    this.idleChecks = 0;
    this.firstPlayback = true;
  }
  playback(playing) {
    if (playing) this.idleChecks = 0;
    else this.idleChecks = this.firstPlayback ? this.checks : Math.min(this.checks, this.idleChecks + 1);
    this.firstPlayback = false;
  }
  reset() { this.idleChecks = 0; }
  unavailable() { this.reset(); }
  due() { return this.idleChecks >= this.checks; }
}

const screensaver = (() => {
  const idle = new IdleClock();
  const overlay = document.getElementById('screensaver');
  const playerParts = [document.querySelector('body > header'), document.querySelector('main')];
  const clock = document.getElementById('clock-time');
  const date = document.getElementById('clock-date');
  let previousFocus = null;
  let serverClock = null;
  let observedAt = 0;
  let offset = 0;
  let lastTick = performance.now();

  function updateClock() {
    // Use the schedule's server/configured timezone, even on remote displays.
    const now = serverClock === null ? new Date() : new Date(serverClock + performance.now() - observedAt + offset);
    const zone = serverClock === null ? {} : {timeZone: 'UTC'};
    clock.textContent = now.toLocaleTimeString([], {...zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
    date.textContent = now.toLocaleDateString([], {...zone, weekday: 'long', month: 'long', day: 'numeric'});
    clock.dateTime = new Date(serverClock === null ? Date.now() : serverClock + performance.now() - observedAt).toISOString();
  }
  function hide() {
    if (overlay.hidden) return;
    overlay.hidden = true;
    document.body.classList.remove('screensaver-active');
    playerParts.forEach(part => { part.inert = false; });
    if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
  }
  function tick() {
    lastTick = performance.now();
    if (!idle.due(performance.now())) return;
    updateClock();
    if (!overlay.hidden) return;
    previousFocus = document.activeElement;
    overlay.hidden = false;
    document.body.classList.add('screensaver-active');
    playerParts.forEach(part => { part.inert = true; });
    overlay.focus({preventScroll: true});
  }
  function activity(event) {
    const visible = !overlay.hidden;
    if (visible && ['keydown', 'pointerdown', 'click', 'wheel'].includes(event.type)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
    idle.reset(performance.now());
    hide();
  }
  // Consume the wake-up click so it cannot accidentally activate playback controls.
  // Pointer-down only records activity; the overlay stays until click/touch release.
  document.addEventListener('pointerdown', event => {
    idle.reset(performance.now());
    if (!overlay.hidden) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);
  for (const event of ['click', 'keydown', 'wheel']) document.addEventListener(event, activity, {capture: true, passive: false});
  document.addEventListener('pointermove', event => {
    // Pointer jitter must not dismiss a rotating unattended display.
    if (overlay.hidden && event.pointerType === 'mouse' && (event.movementX || event.movementY)) idle.reset(performance.now());
  }, true);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { updateClock(); tick(); } });
  let tickTimer = setInterval(tick, 1000);
  return {
    configure(settings) {
      const checks = settings.idle_checks;
      if (Number.isInteger(checks) && checks >= 1 && checks <= 20) idle.checks = checks;
    },
    recover(stallMs = 5000) {
      if (performance.now() - lastTick < stallMs) return;
      clearInterval(tickTimer);
      tickTimer = setInterval(tick, 1000);
      tick();
    },
    playback(playing) { idle.playback(playing, performance.now()); if (playing) hide(); tick(); },
    unavailable(force = false) {
      // A temporary Spotify error is not evidence that music resumed.
      if (!overlay.hidden && !force) return;
      idle.unavailable();
      hide();
    },
    syncClock(iso) {
      const timestamp = Date.parse(iso);
      const match = iso?.match(/([+-])(\d{2}):(\d{2})$/);
      if (!Number.isFinite(timestamp)) return;
      offset = match ? (Number(match[2]) * 60 + Number(match[3])) * 60000 * (match[1] === '+' ? 1 : -1) : 0;
      serverClock = timestamp;
      observedAt = performance.now();
      if (!overlay.hidden) updateClock();
    },
  };
})();
