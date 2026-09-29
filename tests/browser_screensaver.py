from pathlib import Path
import sys
import shutil
import tempfile
from playwright.sync_api import sync_playwright
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'Flask'))
from app import create_app

with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
    app = create_app(directory)
    web = app.test_client()
    browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1024, 'height': 600}, has_touch=True)
    playback = {'state': 'idle', 'name': 'Nothing playing', 'artists': '', 'album': '', 'playing': False, 'shuffle': False, 'duration_ms': 0, 'progress_ms': 0}
    unavailable = False
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route(request):
        path = request.request.url.split('http://player.test', 1)[1].split('?')[0]
        if path == '/api/playback':
            if unavailable:
                request.fulfill(status=503, json={'error': 'Server unavailable'})
            else:
                request.fulfill(json=playback)
        else:
            response = web.get(path)
            request.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
    page.route('http://player.test/**', route)
    page.clock.install()
    page.goto('http://player.test/')
    page.wait_for_function('track !== null && !polling')
    assert page.locator('#screensaver').is_visible()
    def check_idle(count=3):
        for index in range(count):
            page.evaluate('poll()')
            assert page.locator('#screensaver').is_visible() == (index == count - 1)

    page.keyboard.press('Space')
    assert page.locator('#screensaver').is_hidden()
    check_idle()
    assert page.locator('main').evaluate('(node) => node.inert')
    assert page.locator('#clock-time').inner_text()
    page.screenshot(path='/tmp/clock-macos-light.png')
    playback['playing'] = True
    page.evaluate('poll()')
    assert page.locator('#screensaver').is_hidden()
    playback['playing'] = False
    page.evaluate('poll()')
    page.evaluate('poll()')
    assert page.locator('#screensaver').is_hidden()
    # Failed checks break the consecutive-idle streak.
    unavailable = True
    page.evaluate('poll()')
    unavailable = False
    check_idle()
    unavailable = True
    page.evaluate('poll()')
    assert page.locator('#screensaver').is_visible()
    page.evaluate("failure({state: 'authorization_required', error: 'Reconnect Spotify'})")
    assert page.locator('#screensaver').is_hidden()
    page.evaluate('poll()')
    assert page.locator('#screensaver').is_hidden()
    unavailable = False
    check_idle()
    # Live settings can change the threshold without reloading.
    config_path = Path(directory) / 'theme.conf'
    config_path.write_text(config_path.read_text().replace('idle_checks = 3', 'idle_checks = 2'))
    page.clock.run_for(31000)
    page.keyboard.press('Space')
    check_idle(2)
    for name in ['macos-light', 'macos-dark', 'classic-light', 'classic-dark']:
        (Path(directory) / 'theme.conf').write_text(f'[theme]\nmode=manual\nname={name}\ntimezone=Europe/Rome\n')
        page.evaluate('refreshTheme()')
        assert page.locator('#screensaver').is_visible()
        scheme = page.evaluate('getComputedStyle(document.documentElement).colorScheme')
        assert scheme == ('light' if name.endswith('light') else 'dark'), (name, scheme)
        page.screenshot(path=f'/tmp/clock-{name}.png')
    page.evaluate("screensaver.syncClock('2026-09-20T06:23:00+02:00')")
    assert page.locator('#clock-time').inner_text() == '06:23'
    page.mouse.click(512, 300)
    assert page.locator('#screensaver').is_hidden()
    # A touch gesture also wakes without propagating the click to the player.
    unavailable = False
    playback['playing'] = False
    check_idle(2)
    page.touchscreen.tap(512, 300)
    assert page.locator('#screensaver').is_hidden()
    page.set_viewport_size({'width': 320, 'height': 480})
    unavailable = False
    playback['playing'] = False
    check_idle(2)
    assert page.locator('#screensaver').is_visible()
    bounds = page.locator('#clock-time').bounding_box()
    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 321
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.clock-face').evaluate('(node) => getComputedStyle(node).animationName') == 'none'
    assert not errors, errors
    browser.close()
print('Browser checks passed: consecutive idle checks, live threshold, wake, resume, errors, timezone and palettes.')
