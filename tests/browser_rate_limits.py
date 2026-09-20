"""Optional integration check: python tests/browser_rate_limits.py (Playwright + Chromium)."""
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
    calls = {'playback': 0, 'control': 0}
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def route(route):
        path = route.request.url.split('http://player.test', 1)[1]
        if path == '/api/playback':
            calls['playback'] += 1
            if calls['playback'] == 1:
                route.fulfill(status=429, headers={'Retry-After': '602'}, json={'error': 'Cooling down', 'retry_after_seconds': 602})
            else:
                route.fulfill(json={'state': 'ready', 'name': 'Song', 'playing': True,
                                    'controllable': True, 'can_like': True, 'duration_ms': 180000,
                                    'progress_ms': 1000, 'poll_after_ms': 45000})
        elif path.startswith('/api/control/'):
            calls['control'] += 1
            route.fulfill(status=429, headers={'Retry-After': '120'}, json={'error': 'Wait', 'retry_after_seconds': 120})
        else:
            response = web.get(path)
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)

    page.route('http://player.test/**', route)
    page.clock.install()
    page.goto('http://player.test/')
    page.wait_for_function('cooldownUntil > 0 && !polling')
    page.evaluate("command('next')")
    page.clock.fast_forward(601000)
    assert calls == {'playback': 1, 'control': 0}, calls
    page.clock.run_for(2000)
    page.wait_for_function('track !== null && !polling')
    assert calls['playback'] == 2
    page.clock.fast_forward(44000)
    assert calls['playback'] == 2
    page.clock.run_for(2000)
    page.wait_for_function('!polling')
    assert calls['playback'] == 3
    page.evaluate("command('next')")
    assert calls['control'] == 1
    assert page.locator('#next').is_disabled()
    page.clock.fast_forward(119000)
    assert calls['playback'] == 3
    page.evaluate("command('next')")
    assert calls['control'] == 1
    page.clock.run_for(2000)
    page.wait_for_function('!polling')
    assert calls['playback'] == 4
    assert page.locator('#next').is_enabled()
    assert not errors, errors
    page.unroute_all(behavior='wait')
    browser.close()
print('Browser rate checks passed: long cooldown, server polling hints, control cooldown, recovery.')
