"""Optional browser checks: Playwright + Chromium, mocked Yahoo data."""
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Flask'))
from app import create_app

with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
    app = create_app(directory)
    web = app.test_client()
    market = app.extensions['idle_market']
    browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1024,'height':600})
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    def route(route):
        path = route.request.url.split('http://player.test',1)[1]
        if path == '/api/playback':
            route.fulfill(json={'state':'idle','playing':False,'name':'Nothing playing','poll_after_ms':60000})
        else:
            if path == '/api/idle-market':
                market.refresh_once(Path(directory) / 'theme.conf')
            response=web.open(path, method=route.request.method, data=route.request.post_data,
                              headers=route.request.headers, base_url='http://player.test')
            route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.data)
            response.close()
    page.route('http://player.test/**', route)
    with patch.object(market,'fetch',side_effect=lambda symbol: {'symbol':symbol,'name':symbol,'price':4.25 if symbol.startswith('^') or symbol=='2YY=F' else 150,'as_of':1780000000,'currency':'USD','change_percent':1.5}) as fetch, patch.object(market, 'start'):
        page.goto('http://player.test/settings')
        page.wait_for_function('!document.getElementById("save-settings").disabled')
        page.wait_for_function('!document.getElementById("save-theme-config").disabled')
        config = page.locator('#theme-config').input_value()
        assert '[theme]' in config and '[idle_display]' in config
        page.locator('#theme-config').fill(config.replace('name = macos-light', 'name = classic-light'))
        page.locator('#save-theme-config').click()
        page.wait_for_function('document.getElementById("theme-config-status").textContent.startsWith("Saved")')
        assert not page.locator('#enabled').is_checked()
        assert page.locator('#symbols').input_value()=='AAPL,NVDA,OUST'
        assert page.locator('#recovery_enabled').is_checked()
        page.locator('#stock_text_percent').fill('110')
        page.locator('#treasury_text_percent').fill('110')
        page.locator('#rates_seconds').fill('20')
        page.locator('#enabled').check()
        page.locator('#save-settings').click()
        page.wait_for_function('document.getElementById("settings-status").textContent.startsWith("Saved")')
        page.clock.install()
        page.add_init_script('''
          window.displayTimers = [];
          const nativeInterval = window.setInterval;
          window.setInterval = (callback, delay, ...args) => {
            const id = nativeInterval(callback, delay, ...args);
            if (callback.name === 'tick') window.displayTimers.push(id);
            return id;
          };
        ''')
        page.goto('http://player.test/')
        page.wait_for_function('track !== null && !polling')
        page.clock.run_for(1000)
        page.evaluate('idlePages.tick()')
        assert page.locator('#screensaver').is_visible()
        assert page.locator('.clock-face').is_visible()
        page.wait_for_function('!polling')
        # Simulate lost display timers; watchdog restores both without a reload.
        page.evaluate('displayTimers.forEach(clearInterval)')
        page.clock.run_for(11000)
        assert page.evaluate('displayTimers.length') == 4, page.evaluate('displayTimers.length')
        page.clock.run_for(18000)
        assert page.locator('.clock-face').is_visible()
        page.clock.run_for(1000)
        assert page.locator('#idle-market-page h2').inner_text()=='US Treasury yields'
        page.wait_for_function('document.querySelector(".market-price").textContent.includes("4.25")')
        cards = page.locator('.market-grid .market-card')
        positions = [cards.nth(i).bounding_box() for i in range(4)]
        assert positions[0]['x'] < positions[1]['x'] and positions[2]['x'] < positions[3]['x']
        assert positions[0]['y'] < positions[2]['y'] and positions[1]['y'] < positions[3]['y']
        assert page.locator('.market-price').first.evaluate('(node) => parseFloat(getComputedStyle(node).fontSize)') >= 80
        assert page.locator('#idle-market-page').evaluate("node => node.style.getPropertyValue('--market-text-scale')") == '1.1'
        page.screenshot(path='/tmp/idle-treasury.png')
        page.mouse.move(100, 100)
        assert page.locator('#screensaver').is_visible()
        page.evaluate("failure({error: 'Temporary Spotify outage'})")
        assert page.locator('#screensaver').is_visible()
        page.clock.run_for(10000)
        assert page.locator('#idle-market-page h2').inner_text() == 'US Treasury yields'
        for symbol in ['AAPL','NVDA','OUST']:
            page.clock.run_for(10000)
            assert page.locator('#idle-market-page h2').inner_text()==symbol
        assert fetch.call_count==7, fetch.call_count
        assert page.locator('.market-price').evaluate('(node) => parseFloat(getComputedStyle(node).fontSize)') >= 75
        page.screenshot(path='/tmp/idle-stock.png')
        page.clock.run_for(10000)
        assert page.locator('.clock-face').is_visible()
        assert page.locator('#screensaver').is_visible()
        page.evaluate("rateLimit({headers: new Headers({'Retry-After': '60'})}, {error: 'Spotify cooldown'})")
        page.clock.run_for(30000)
        assert page.locator('#screensaver').is_visible()
        assert page.locator('#idle-market-page h2').inner_text() == 'US Treasury yields'
        page.set_viewport_size({'width': 320, 'height': 480})
        page.screenshot(path='/tmp/idle-treasury-small.png')
        page.set_viewport_size({'width':1024,'height':600})
        page.evaluate('screensaver.playback(true)')
        assert page.locator('#screensaver').is_hidden()
        page.goto('http://player.test/settings')
        page.wait_for_function('!document.getElementById("save-settings").disabled')
        page.locator('#recovery_enabled').uncheck()
        page.locator('#enabled').uncheck()
        page.locator('#save-settings').click()
        page.wait_for_function('document.getElementById("settings-status").textContent.startsWith("Saved")')
        assert not web.get('/api/idle-settings').json['enabled']
        page.goto('http://player.test/')
        page.wait_for_function('track !== null && !polling')
        page.clock.run_for(1000)
        page.evaluate('displayTimers.forEach(clearInterval)')
        page.clock.run_for(15000)
        assert page.evaluate('displayTimers.length') == 2
        assert not errors, errors
    page.unroute_all(behavior='wait')
    browser.close()
    market.pool.shutdown()
print('Idle market browser checks passed: defaults, save, clock/rates/stocks rotation, cache, wake, disable.')
