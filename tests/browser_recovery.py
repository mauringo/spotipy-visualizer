"""Browser recovery regression checks; requires Playwright and Chromium."""
from pathlib import Path
import shutil
import sys
import tempfile
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Flask'))
from app import create_app

with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
    web = create_app(directory).test_client()
    browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])
    page = browser.new_page()
    counts = {'playback': 0, 'control': 0}
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route(route):
        path = route.request.url.split('http://player.test', 1)[1]
        if path == '/api/playback':
            counts['playback'] += 1
            route.fulfill(json={'state': 'ready', 'name': 'Current song', 'playing': True,
                                'controllable': True, 'can_like': True, 'duration_ms': 180000,
                                'progress_ms': 1000, 'poll_after_ms': 15000})
        elif path.startswith('/api/control/'):
            counts['control'] += 1
            route.fulfill(json={'ok': True})
        else:
            response = web.get(path)
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
    page.route('http://player.test/**', route)
    page.clock.install()
    # The recovery helper works on browsers without AbortSignal.timeout as well.
    page.add_init_script('AbortSignal.timeout = undefined;')
    page.goto('http://player.test/')
    page.wait_for_function('track !== null && !polling')
    page.evaluate('''() => {
      window.originalFetch = window.fetch;
      window.fetch = (url, options) => url === '/api/playback'
        ? new Promise(resolve => { window.latePlayback = resolve; })
        : window.originalFetch(url, options);
      void poll();
    }''')
    page.clock.run_for(61000)
    page.wait_for_function('!polling')
    assert 'Retrying automatically' in page.locator('#status').inner_text()
    page.evaluate('window.fetch = window.originalFetch')
    page.clock.run_for(31000)
    page.wait_for_function('track !== null && !polling')
    page.evaluate('''latePlayback(new Response(JSON.stringify({name: 'Stale song', playing: false}),
                         {headers: {'Content-Type': 'application/json'}}))''')
    assert page.locator('#title').inner_text() == 'Current song'
    # Repair a lost scheduled timeout instead of requiring a page reload.
    before = counts['playback']
    page.evaluate('clearTimeout(timer); nextPollAt = Date.now() - 20000')
    page.clock.run_for(5000)
    page.wait_for_function('!polling')
    assert counts['playback'] > before
    # Returning to the page and restored connectivity each request fresh state.
    for event in ('online', 'pageshow'):
        before = counts['playback']
        page.evaluate(f"window.dispatchEvent(new Event('{event}'))")
        page.wait_for_function('!polling')
        assert counts['playback'] == before + 1
    # A hanging response body is bounded too; never replay a timed-out command.
    page.evaluate('''() => {
      window.fetch = (url, options) => url.startsWith('/api/control/')
        ? Promise.resolve({ok: true, json: () => new Promise(() => {})})
        : window.originalFetch(url, options);
      void command('next');
    }''')
    page.clock.run_for(61000)
    page.wait_for_function('!busy')
    assert 'will not be repeated' in page.locator('#status').inner_text()
    assert counts['control'] == 0
    page.evaluate('window.fetch = window.originalFetch')
    # Resume/watchdog checks cannot skip Spotify's cooldown.
    before = counts['playback']
    page.evaluate("rateLimit({headers: new Headers({'Retry-After': '3600'})}, {error: 'Cooling down'}); schedulePoll(1000)")
    page.evaluate("window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('pageshow'))")
    page.clock.run_for(10000)
    assert counts['playback'] == before
    assert 'Next check in' in page.locator('#status').inner_text()
    assert not errors, errors
    page.unroute_all(behavior='wait')
    browser.close()
print('Recovery checks passed: stalled fetch/body, late response, lost timer, resume, cooldown, no control replay.')
