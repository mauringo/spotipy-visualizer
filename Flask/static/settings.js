const fields = ['idle_checks', 'enabled', 'show_clock', 'show_rates', 'show_stocks', 'page_seconds', 'rates_seconds', 'clock_seconds', 'refresh_seconds', 'symbols', 'recovery_enabled', 'recovery_stall_seconds', 'stock_text_percent', 'treasury_text_percent'];
const form = document.getElementById('idle-settings');
const status = document.getElementById('settings-status');
const save = document.getElementById('save-settings');
async function settingsRequest(options, url = '/api/idle-settings') {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Settings could not be saved.');
    return data;
  } finally { clearTimeout(timeout); }
}
function fill(data) {
  for (const key of fields) {
    const input = document.getElementById(key);
    if (input.type === 'checkbox') input.checked = data[key];
    else input.value = Array.isArray(data[key]) ? data[key].join(',') : data[key];
  }
}
form.addEventListener('submit', async event => {
  event.preventDefault();
  save.disabled = true;
  const values = {};
  for (const key of fields) {
    const input = document.getElementById(key);
    values[key] = input.type === 'checkbox' ? input.checked : input.value;
  }
  try {
    fill(await settingsRequest({method: 'POST', headers: {'Content-Type': 'application/json', 'X-Spotify-Control': '1'}, body: JSON.stringify(values)}));
    status.textContent = 'Saved. Open displays update within 30 seconds.';
    if (!configDirty) await loadThemeConfig();
  } catch (error) { status.textContent = error.message; }
  finally { save.disabled = false; }
});
settingsRequest().then(data => { fill(data); save.disabled = false; status.textContent = ''; })
  .catch(() => { status.textContent = 'Cannot load settings. Reload this page to retry.'; });

const configEditor = document.getElementById('theme-config');
const configStatus = document.getElementById('theme-config-status');
const configSave = document.getElementById('save-theme-config');
let originalConfig = '';
let configDirty = false;
configEditor.addEventListener('input', () => { configDirty = true; });
async function loadThemeConfig() {
  try {
    const data = await settingsRequest({}, '/api/theme-config');
    originalConfig = data.config;
    configEditor.value = data.config;
    configDirty = false;
    configEditor.disabled = false;
    configSave.disabled = false;
    configStatus.textContent = '';
  } catch (error) { configStatus.textContent = error.message; }
}
document.getElementById('reload-theme-config').onclick = () => {
  if (!configDirty || window.confirm('Discard unsaved configuration edits?')) void loadThemeConfig();
};
document.getElementById('theme-config-form').addEventListener('submit', async event => {
  event.preventDefault();
  configSave.disabled = true;
  try {
    const data = await settingsRequest({method: 'POST', headers: {'Content-Type': 'application/json', 'X-Spotify-Control': '1'}, body: JSON.stringify({config: configEditor.value, original: originalConfig})}, '/api/theme-config');
    originalConfig = data.config;
    configEditor.value = data.config;
    configDirty = false;
    fill(await settingsRequest());
    document.querySelector('link[href^="/theme.css"]').href = `/theme.css?updated=${Date.now()}`;
    configStatus.textContent = 'Saved. Theme applied here; other displays update within 30 seconds.';
  } catch (error) { configStatus.textContent = error.message; }
  finally { configSave.disabled = false; }
});
void loadThemeConfig();
