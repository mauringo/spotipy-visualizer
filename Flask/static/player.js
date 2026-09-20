const $ = (id) => document.getElementById(id);
let track = null;
let receivedAt = 0;
let busy = false;
let timer;
let polling = false;
let errorUntil = 0;
let cooldownUntil = 0;
let nextPollMs = 15000;

function pollDelay(value, fallback) {
  const delay = Number(value);
  return Number.isFinite(delay) && delay > 0 ? Math.min(2147483647, Math.max(1000, delay)) : fallback;
}
function rateLimit(response, data) {
  const seconds = Number(response.headers.get('Retry-After') || data.retry_after_seconds || 60);
  const delay = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 60000;
  cooldownUntil = Math.max(cooldownUntil, performance.now() + delay);
  errorUntil = Date.now() + delay;
  $('status').textContent = data.error || 'Spotify is cooling down. Retrying automatically.';
  screensaver.unavailable();
  controls();
}
function schedulePoll(delay) {
  clearTimeout(timer);
  timer = setTimeout(poll, pollDelay(Math.max(delay, cooldownUntil - performance.now()), 15000));
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
  const waiting = performance.now() < cooldownUntil;
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
  screensaver.unavailable();
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
  if (performance.now() < cooldownUntil) { schedulePoll(cooldownUntil - performance.now()); return; }
  if (polling || busy) { schedulePoll(1000); return; }
  polling = true;
  let delay = nextPollMs;
  try {
    const response = await fetch('/api/playback', {signal: AbortSignal.timeout(15000)});
    const data = await response.json();
    if (response.ok) {
      nextPollMs = pollDelay(data.poll_after_ms, 15000);
      delay = nextPollMs;
      render(data);
    } else if (response.status === 429) {
      rateLimit(response, data);
      delay = cooldownUntil - performance.now();
    } else { failure(data); delay = 30000; }
  } catch (_) { failure({error: 'Server unavailable. Retrying shortly.'}); delay = 30000; }
  finally { polling = false; schedulePoll(delay); }
}
async function command(action, body = {}) {
  if (busy || performance.now() < cooldownUntil) return;
  let delay = 2000;
  busy = true;
  controls();
  try {
    const response = await fetch(`/api/control/${action}`, {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Spotify-Control': '1'},
      body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
    });
    const data = await response.json();
    if (response.status === 429) { rateLimit(response, data); delay = cooldownUntil - performance.now(); return; }
    if (!response.ok) throw new Error(data.error);
    delay = pollDelay(data.poll_after_ms, 2000);
    $('status').textContent = '';
    errorUntil = 0;
  } catch (error) {
    $('status').textContent = error.message || 'Control failed. Try again.';
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
    const response = await fetch('/theme.css', {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    if (!response.ok) return;
    const css = await response.text();
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
  if (!document.hidden) refreshTheme();
});

refreshTheme();
