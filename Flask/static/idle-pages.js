// Page rotation is local; only the shared server cache contacts Yahoo.
const idlePages = (() => {
  const clock = document.querySelector('.clock-face');
  const market = document.getElementById('idle-market-page');
  let settings = {enabled: false};
  let data = {rates: [], stocks: []};
  let startedAt = null;
  let visiblePage = '';
  let nextFetchAt = 0;
  let fetching = false;
  let configuring = false;
  let lastTick = performance.now();

  function text(tag, content, className) {
    const node = document.createElement(tag);
    node.textContent = content;
    if (className) node.className = className;
    return node;
  }
  function pages() {
    if (!settings.enabled) return ['clock'];
    return [...(settings.show_clock ? ['clock'] : []), ...(settings.show_rates ? ['rates'] : []),
      ...(settings.show_stocks ? settings.symbols.map(symbol => `stock:${symbol}`) : [])];
  }
  function quoteContent(row, yieldQuote = false) {
    const card = document.createElement('div');
    card.className = 'market-card';
    card.append(text('p', row.label || row.name || row.symbol, 'market-label'));
    const value = Number.isFinite(row.price) ? `${row.price.toLocaleString([], {minimumFractionDigits: 2, maximumFractionDigits: yieldQuote ? 3 : 2})}${yieldQuote ? '%' : ` ${row.currency || ''}`}` : 'Unavailable';
    card.append(text('p', value, Number.isFinite(row.price) ? 'market-price' : 'market-price quote-missing'));
    if (!yieldQuote && Number.isFinite(row.change_percent)) {
      card.append(text('p', `${row.change_percent >= 0 ? '+' : ''}${row.change_percent.toFixed(2)}% vs previous close`, 'market-change'));
    }
    const date = row.as_of ? new Date(row.as_of * 1000).toLocaleString() : 'No quote available';
    card.append(text('p', `${row.stale ? 'Cached · ' : ''}${date}`, 'market-asof'));
    return card;
  }
  function render(page) {
    market.classList.toggle('rates-page', page === 'rates');
    market.style.setProperty('--market-text-scale', (page === 'rates' ? settings.treasury_text_percent || 100 : settings.stock_text_percent || 100) / 100);
    clock.hidden = page !== 'clock';
    market.hidden = page === 'clock';
    if (page === 'clock') return;
    market.replaceChildren();
    if (page === 'rates') {
      market.append(text('h2', 'US Treasury yields'));
      const grid = document.createElement('div');
      grid.className = 'market-grid';
      const rows = data.rates.length ? data.rates : ['2Y · yield futures', '5Y Treasury', '10Y Treasury', '30Y Treasury'].map(label => ({label}));
      rows.forEach(row => grid.append(quoteContent(row, true)));
      market.append(grid, text('p', '2Y is a yield-futures quote. These are not Fed policy rates.', 'market-asof'));
    } else {
      const symbol = page.slice(6);
      market.append(text('h2', symbol), quoteContent(data.stocks.find(row => row.symbol === symbol) || {symbol}));
    }
    market.append(text('p', 'Yahoo Finance · Quotes may be delayed', 'market-source'));
  }
  async function fetchData() {
    if (fetching || !settings.enabled || (!settings.show_rates && !settings.show_stocks) || Date.now() < nextFetchAt) return;
    fetching = true;
    // Read the local cache periodically; Yahoo refresh is owned by the server.
    nextFetchAt = Date.now() + 30000;
    try {
      const result = await fetchResource('/api/idle-market');
      if (result.response.ok) data = result.data;
    } catch (_) {
      data = {rates: data.rates.map(row => ({...row, stale: true})), stocks: data.stocks.map(row => ({...row, stale: true}))};
    } finally {
      fetching = false;
      if (startedAt !== null) render(visiblePage);
    }
  }
  async function configure() {
    if (configuring) return;
    configuring = true;
    try {
      const result = await fetchResource('/api/idle-settings');
      if (result.response.ok && JSON.stringify(settings) !== JSON.stringify(result.data)) {
        settings = result.data;
        screensaver.configure(settings);
        startedAt = startedAt === null ? null : Date.now();
        nextFetchAt = 0;
        visiblePage = '';
      }
    } catch (_) { /* Retain the last working settings, disabled by default. */ }
    finally { configuring = false; }
  }
  function tick() {
    lastTick = performance.now();
    if (document.getElementById('screensaver').hidden) { startedAt = null; visiblePage = ''; return; }
    if (startedAt === null) startedAt = Date.now();
    const list = pages();
    const duration = page => (page === 'clock' ? (settings.clock_seconds || 30) : page === 'rates' ? (settings.rates_seconds || settings.page_seconds || 10) : (settings.page_seconds || 10)) * 1000;
    const cycle = list.reduce((sum, page) => sum + duration(page), 0);
    let elapsed = (Date.now() - startedAt) % cycle;
    let page = 'clock';
    for (const candidate of list) {
      if (elapsed < duration(candidate)) { page = candidate; break; }
      elapsed -= duration(candidate);
    }
    if (page !== visiblePage) { visiblePage = page; render(page); }
    void fetchData();
  }
  let tickTimer = setInterval(tick, 1000);
  setInterval(configure, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void configure(); });
  void configure();
  return {tick, recover() {
    if (settings.recovery_enabled === false) return;
    const stallMs = (settings.recovery_stall_seconds || 5) * 1000;
    screensaver.recover(stallMs);
    if (performance.now() - lastTick < stallMs) return;
    clearInterval(tickTimer);
    tickTimer = setInterval(tick, 1000);
    // Restore the currently due page without restarting the idle cycle.
    visiblePage = '';
    tick();
  }};
})();
