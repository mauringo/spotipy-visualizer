const $ = (id) => document.getElementById(id);
let track = null;
let receivedAt = 0;
let busy = false;
let timer;
let polling = false;
let errorUntil = 0;
let cooldownUntil = 0;
let nextPollMs = 15000;
let nextPollAt = Date.now();
let cooldownMessage = '';
let requestTimeoutMs = 60000;
let recoveryGraceMs = 15000;
let networkRetryMs = 30000;
const pendingRequests = new Set();

// Bound the complete response (including its body), even if fetch ignores abort.
async function fetchResource(url, options = {}, format = 'json') {
  const controller = new AbortController();
  let timeout;
  let pending;
  const deadline = new Promise((_, reject) => {
    pending = {until: Date.now() + requestTimeoutMs, expire() {
      controller.abort();
      reject(new Error('Request timed out. Retrying automatically.'));
    }};
    pendingRequests.add(pending);
    timeout = setTimeout(pending.expire, requestTimeoutMs);
  });
  try {
    return await Promise.race([
      (async () => {
        const response = await fetch(url, {...options, cache: 'no-store', signal: controller.signal});
        const data = await response[format]();
        return {response, data};
      })(), deadline,
    ]);
  } finally {
    clearTimeout(timeout);
    pendingRequests.delete(pending);
  }
}
function recoverPlayer(force = false) {
  const now = Date.now();
  // Repair local display timers independently of network state and cooldowns.
  if (typeof idlePages !== 'undefined') idlePages.recover();
  progress();
  for (const pending of pendingRequests) if (now >= pending.until) pending.expire();
  if (!polling && !busy && now >= cooldownUntil && (force || now >= nextPollAt + recoveryGraceMs)) poll();
}
async function refreshClientSettings() {
  if (refreshClientSettings.running) return;
  refreshClientSettings.running = true;
  try {
    const {response, data} = await fetchResource('/api/client-settings');
    if (response.ok) {
      requestTimeoutMs = boundedSetting(data.request_timeout_ms, 10000, 300000, requestTimeoutMs);
      recoveryGraceMs = boundedSetting(data.recovery_grace_ms, 5000, 120000, recoveryGraceMs);
      networkRetryMs = boundedSetting(data.network_retry_ms, 5000, 300000, networkRetryMs);
    }
  } catch (_) { /* Keep working with the last known settings. */ }
  finally { refreshClientSettings.running = false; }
}
function boundedSetting(value, minimum, maximum, fallback) {
  return Number.isFinite(value) && value >= minimum && value <= maximum ? value : fallback;
}

function pollDelay(value, fallback) {
  const delay = Number(value);
  return Number.isFinite(delay) && delay > 0 ? Math.min(2147483647, Math.max(1000, delay)) : fallback;
}
function rateLimit(response, data) {
  const seconds = Number(response.headers.get('Retry-After') || data.retry_after_seconds || 60);
  const delay = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 60000;
  cooldownUntil = Math.max(cooldownUntil, Date.now() + delay);
  errorUntil = Date.now() + delay;
  cooldownMessage = data.error || 'Spotify is cooling down.';
  updateCooldownStatus();
  screensaver.unavailable();
  controls();
}
function updateCooldownStatus() {
  const seconds = Math.ceil((cooldownUntil - Date.now()) / 1000);
  if (seconds > 0) $('status').textContent = `${cooldownMessage} Next check in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}.`;
}
function schedulePoll(delay) {
  clearTimeout(timer);
  const wait = pollDelay(Math.max(delay, cooldownUntil - Date.now()), 15000);
  nextPollAt = Date.now() + wait;
  timer = setTimeout(poll, wait);
}

function icons() { if (window.lucide) lucide.createIcons(); }
function icon(button, name, label) {
  button.replaceChildren();
  const node = document.createElement('i');
  node.dataset.lucide = name;
  button.append(node);
  button.title = label;
  button.setAttribute('aria-label', label);
  icons();
}
function time(ms) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function controls() {
  const waiting = Date.now() < cooldownUntil;
  const allowed = track?.controllable && !busy && !waiting;
  const denied = track?.disallows || {};
  $('previous').disabled = !allowed || !!denied.skipping_prev;
  $('next').disabled = !allowed || !!denied.skipping_next;
  $('play').disabled = !allowed || !!denied[track?.playing ? 'pausing' : 'resuming'];
  $('like').disabled = !track?.can_like || busy || waiting;
  $('shuffle').disabled = !allowed || !!denied.toggling_shuffle;
}
function render(data) {
  track = data;
  screensaver.playback(data.playing);
  receivedAt = performance.now();
  $('connect').hidden = true;
  $('title').textContent = data.name;
  $('artist').textContent = data.artists;
  $('album').textContent = data.album;
  $('device').textContent = data.device ? `${data.playing ? 'Playing' : 'Paused'} on ${data.device}` : 'Spotify';
  const cover = $('cover');
  cover.hidden = !data.image;
  $('placeholder').style.display = data.image ? 'none' : '';
  if (data.image && cover.getAttribute('src') !== data.image) cover.src = data.image;
  if (!data.image) cover.removeAttribute('src');
  cover.alt = data.album ? `${data.album} album artwork` : '';
  $('shuffle').setAttribute('aria-pressed', String(data.shuffle));
  $('shuffle').title = data.shuffle ? 'Disable shuffle' : 'Enable shuffle';
  $('shuffle').setAttribute('aria-label', $('shuffle').title);
  $('like').setAttribute('aria-pressed', String(data.liked));
  $('like').title = data.liked ? 'Unlike song' : 'Like song';
  $('like').setAttribute('aria-label', $('like').title);
  icon($('play'), data.playing ? 'pause' : 'play', data.playing ? 'Pause' : 'Play');
  $('duration').textContent = time(data.duration_ms);
  if (Date.now() > errorUntil) $('status').textContent = data.state === 'idle' ? 'Start a song on your Spotify device.' : '';
  controls();
  progress();
}
function progress() {
  const position = Math.min(track?.duration_ms || 0, (track?.progress_ms || 0) + (track?.playing ? performance.now() - receivedAt : 0));
  $('progress').max = track?.duration_ms || 1;
  $('progress').value = position;
  $('elapsed').textContent = time(position);
}
function failure(data) {
  screensaver.unavailable(data.state === 'configuration_required' || data.state === 'authorization_required');
  track = null;
  controls();
  $('status').textContent = data.error || 'Server unavailable. Retrying shortly.';
  if (data.state === 'configuration_required' || data.state === 'authorization_required') {
    $('title').textContent = data.state === 'configuration_required' ? 'Spotify setup' : 'Your music, here.';
    $('connect').hidden = data.state !== 'authorization_required';
    $('artist').textContent = '';
    $('album').textContent = '';
    $('cover').hidden = true;
    $('placeholder').style.display = '';
  }
}
async function poll() {
  clearTimeout(timer);
  if (Date.now() < cooldownUntil) { schedulePoll(cooldownUntil - Date.now()); return; }
  if (polling || busy) { schedulePoll(1000); return; }
  polling = true;
  let delay = nextPollMs;
  try {
    const {response, data} = await fetchResource('/api/playback');
    if (response.ok) {
      nextPollMs = pollDelay(data.poll_after_ms, 15000);
      delay = nextPollMs;
      render(data);
    } else if (response.status === 429) {
      rateLimit(response, data);
      delay = cooldownUntil - Date.now();
    } else { failure(data); delay = networkRetryMs; }
  } catch (_) { failure({error: 'Connection interrupted. Retrying automatically.'}); delay = networkRetryMs; }
  finally { polling = false; schedulePoll(delay); }
}
async function command(action, body = {}) {
  if (busy || Date.now() < cooldownUntil) return;
  let delay = 2000;
  busy = true;
  controls();
  try {
    const {response, data} = await fetchResource(`/api/control/${action}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Spotify-Control': '1'},
      body: JSON.stringify(body),
    });
    if (response.status === 429) { rateLimit(response, data); delay = cooldownUntil - Date.now(); return; }
    if (!response.ok) throw new Error(data.error);
    delay = pollDelay(data.poll_after_ms, 2000);
    $('status').textContent = '';
    errorUntil = 0;
  } catch (error) {
    $('status').textContent = 'Control could not be confirmed. Checking playback; the command will not be repeated.';
    delay = networkRetryMs;
    errorUntil = Date.now() + 8000;
  } finally {
    busy = false;
    controls();
    schedulePoll(delay);
  }
}
$('previous').onclick = () => command('previous');
$('next').onclick = () => command('next');
$('shuffle').onclick = () => command('shuffle', {state: !track.shuffle});
$('play').onclick = () => command(track?.playing ? 'pause' : 'play');
$('like').onclick = () => command('like', {uri: track.uri, liked: !track.liked});
$('cover').onerror = () => { $('cover').hidden = true; $('placeholder').style.display = ''; };
$('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch (_) { $('status').textContent = 'Fullscreen is unavailable in this browser.'; }
};
document.addEventListener('fullscreenchange', () => icon($('fullscreen'), document.fullscreenElement ? 'minimize' : 'maximize', document.fullscreenElement ? 'Exit fullscreen' : 'Enter fullscreen'));
if (!document.fullscreenEnabled) $('fullscreen').hidden = true;
icons();
if (new URLSearchParams(location.search).get('auth') === 'denied') {
  $('status').textContent = 'Spotify authorization was cancelled.';
  history.replaceState({}, '', '/');
}
setInterval(progress, 1000);
poll();

// Keep an unattended display in sync with the schedule and configuration edits.
let themeRefreshing = false;
async function refreshTheme() {
  if (themeRefreshing) return;
  themeRefreshing = true;
  try {
    const {response, data: css} = await fetchResource('/theme.css', {}, 'text');
    if (!response.ok) return;
    screensaver.syncClock(response.headers.get('X-Clock-Time'));
    let style = $('theme-styles');
    if (style.tagName === 'LINK') {
      const replacement = document.createElement('style');
      replacement.id = 'theme-styles';
      replacement.textContent = css;
      style.replaceWith(replacement);
    } else if (style.textContent !== css) {
      style.textContent = css;
    }
  } catch (_) { /* Keep the current theme when the server is unavailable. */ }
  finally { themeRefreshing = false; }
}
setInterval(refreshTheme, 30000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) { recoverPlayer(true); refreshTheme(); refreshClientSettings(); }
});

refreshTheme();

// Resume immediately after restored connectivity or browser back/forward cache.
window.addEventListener('online', () => recoverPlayer(true));
window.addEventListener('pageshow', () => recoverPlayer(true));
setInterval(() => recoverPlayer(), 5000);
setInterval(updateCooldownStatus, 1000);
setInterval(refreshClientSettings, 60000);
refreshClientSettings();
