from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Flask'))
from app import create_app
from idle_market import upgrade, load, Market


class IdleMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.app = create_app(self.path)
        self.web = self.app.test_client()
        self.market = self.app.extensions['idle_market']
        self.addCleanup(self.market.close)
        starter = patch.object(self.market, 'start')
        starter.start()
        self.addCleanup(starter.stop)

    def market_data(self):
        self.market.refresh_once(self.path / 'theme.conf')
        return self.web.get('/api/idle-market')

    def save(self, **settings):
        return self.web.post('/api/idle-settings', json=settings, headers={'X-Spotify-Control': '1'})

    def test_default_disabled_and_upgrade_preserves_theme(self):
        path = self.path / 'theme.conf'
        path.write_text('# personal theme\n[theme]\nname=classic-light\n[idle_display]\npage_seconds=25\n[other]\nx=y\n')
        upgrade(path)
        first = path.read_text()
        self.assertIn('# personal theme', first)
        self.assertIn('name=classic-light', first)
        self.assertEqual(load(path)['page_seconds'], 25)
        self.assertEqual(load(path)['rates_seconds'], 25)
        self.assertFalse(load(path)['enabled'])
        upgrade(path)
        self.assertEqual(path.read_text(), first)
        with patch.object(self.market, 'fetch') as fetch:
            self.assertTrue(self.market_data().json['disabled'])
            fetch.assert_not_called()

    def test_display_options_migrate_validate_and_persist(self):
        path = self.path / 'theme.conf'
        path.write_text('[theme]\nname=macos-dark\n[idle_display]\nstock_text_percent=115\n')
        upgrade(path)
        self.assertEqual(load(path)['stock_text_percent'], 115)
        self.assertEqual(load(path)['treasury_text_percent'], 100)
        self.assertEqual(load(path)['idle_checks'], 3)
        self.assertEqual(self.save(idle_checks=2).status_code, 200)
        self.assertEqual(load(path)['idle_checks'], 2)
        self.assertTrue(load(path)['recovery_enabled'])
        self.assertEqual(load(path)['recovery_stall_seconds'], 5)
        self.assertEqual(self.save(recovery_enabled=False, recovery_stall_seconds=20,
                                   treasury_text_percent=120).status_code, 200)
        self.assertFalse(load(path)['recovery_enabled'])
        self.assertEqual(load(path)['recovery_stall_seconds'], 20)
        for invalid in ({'idle_checks': 0}, {'idle_checks': 21}, {'idle_checks': True}, {'stock_text_percent': 131}, {'treasury_text_percent': 79},
                        {'recovery_stall_seconds': 0}, {'recovery_enabled': 'yes'}):
            self.assertEqual(self.save(**invalid).status_code, 400)
        self.assertEqual(load(path)['stock_text_percent'], 115)

    def test_rates_duration_independent_of_stocks(self):
        self.assertEqual(self.save(rates_seconds=25, page_seconds=8).status_code, 200)
        settings = load(self.path / 'theme.conf')
        self.assertEqual(settings['rates_seconds'], 25)
        self.assertEqual(settings['page_seconds'], 8)
        self.assertEqual(self.save(rates_seconds=4).status_code, 400)
        self.assertEqual(self.save(rates_seconds=301).status_code, 400)
        upgrade(self.path / 'theme.conf')
        self.assertEqual(load(self.path / 'theme.conf')['rates_seconds'], 25)

    def test_save_validation_and_cross_origin(self):
        self.assertEqual(self.save(enabled=True, page_seconds=10, symbols='AAPL,NVDA,OUST').status_code, 200)
        self.assertTrue(load(self.path / 'theme.conf')['enabled'])
        self.assertEqual(self.save(page_seconds=0).status_code, 400)
        self.assertEqual(self.save(symbols='https://bad.test').status_code, 400)
        self.assertEqual(self.save(enabled=True, show_clock=False, show_rates=False, show_stocks=False).status_code, 400)
        self.assertEqual(self.web.post('/api/idle-settings', json={}).status_code, 403)
        self.assertEqual(self.web.post('/api/idle-settings', json={}, headers={'X-Spotify-Control':'1','Origin':'https://bad.test'}).status_code, 403)
        self.assertEqual((self.path / 'theme.conf').stat().st_mode & 0o777, 0o600)
        with self.web.get('/settings') as response:
            self.assertEqual(response.status_code, 200)

    def test_cache_partial_failure_and_stale_data(self):
        self.save(enabled=True, show_rates=False)
        def quote(symbol):
            if symbol == 'OUST':
                raise requests.Timeout()
            return {'symbol': symbol, 'name': symbol, 'price': 100, 'as_of': 1700000000}
        with patch.object(self.market, 'fetch', side_effect=quote) as fetch, patch('idle_market.time.monotonic', return_value=100) as clock:
            first = self.market_data().json
            self.assertEqual(len(first['stocks']), 3)
            self.assertTrue(first['stocks'][2]['unavailable'])
            self.market_data()
            self.assertEqual(fetch.call_count, 3)
            clock.return_value = 1901
            fetch.side_effect = requests.Timeout()
            result = self.market_data().json
            self.assertEqual(result['stocks'][0]['price'], 100)
            self.assertTrue(result['stocks'][0]['stale'])

    def test_rates_and_yahoo_units(self):
        self.save(enabled=True, show_stocks=False)
        with patch.object(self.market, 'fetch', side_effect=lambda symbol: {'symbol':symbol,'price':4.25,'as_of':1700000000}):
            rates = self.market_data().json['rates']
            self.assertEqual([r['symbol'] for r in rates], ['2YY=F','^FVX','^TNX','^TYX'])
            self.assertIn('futures', rates[0]['label'])
            self.assertEqual(rates[1]['price'], 4.25)
        response = Mock()
        response.json.return_value = {'chart':{'result':[{'meta':{'regularMarketPrice':110,'regularMarketTime':1700000000,'previousClose':100}}]}}
        with patch('idle_market.requests.get', return_value=response) as get:
            self.assertAlmostEqual(self.market.fetch('AAPL')['change_percent'], 10)
            self.assertEqual(get.call_args.kwargs['params']['range'], '1d')

    def test_concurrent_reader_does_not_block(self):
        with self.market.lock:
            rows = self.market.quotes(['AAPL'], 300)
        self.assertTrue(rows[0]['unavailable'])

    def test_malformed_config_is_not_overwritten(self):
        path = self.path / 'theme.conf'
        path.write_text('broken config')
        upgrade(path)
        self.assertEqual(path.read_text(), 'broken config')
        self.assertEqual(self.save(enabled=True).status_code, 409)
        self.assertFalse(load(path)['enabled'])

    def test_thirty_minute_cache_and_independent_clock_duration(self):
        self.assertEqual(load(self.path / 'theme.conf')['refresh_seconds'], 1800)
        self.assertEqual(self.save(clock_seconds=90).json['clock_seconds'], 90)
        self.assertEqual(self.save(clock_seconds=0).status_code, 400)
        self.save(enabled=True, show_rates=False, symbols='AAPL')
        with patch.object(self.market, 'fetch', return_value={'symbol':'AAPL','price':100,'as_of':1700000000}) as fetch, patch('idle_market.time.monotonic', return_value=100) as clock:
            self.market.refresh_once(self.path / 'theme.conf')
            clock.return_value = 1899
            self.market.refresh_once(self.path / 'theme.conf')
            self.web.get('/api/idle-market')
            self.assertEqual(fetch.call_count, 1)
            clock.return_value = 1900
            self.web.get('/api/idle-market')  # HTTP reads never refresh Yahoo.
            self.assertEqual(fetch.call_count, 1)
            self.market.refresh_once(self.path / 'theme.conf')
            self.assertEqual(fetch.call_count, 2)

    def test_yahoo_429_stops_batch_and_honors_long_retry(self):
        self.save(enabled=True, show_rates=False)
        response = requests.Response()
        response.status_code = 429
        response.headers['Retry-After'] = '3600'
        with patch.object(self.market, 'fetch', side_effect=requests.HTTPError(response=response)) as fetch, patch('idle_market.time.monotonic', return_value=100) as clock:
            self.market.refresh_once(self.path / 'theme.conf')
            self.assertEqual(fetch.call_count, 1)
            clock.return_value = 3701
            self.market.refresh_once(self.path / 'theme.conf')
            self.assertEqual(fetch.call_count, 1)
            clock.return_value = 3702
            self.market.refresh_once(self.path / 'theme.conf')
            self.assertEqual(fetch.call_count, 2)

    def test_enabled_startup_refreshes_without_browser(self):
        import threading
        self.save(enabled=True, show_rates=False, symbols='AAPL')
        fetched = threading.Event()
        def quote(symbol):
            fetched.set()
            return {'symbol':symbol,'price':100,'as_of':1700000000}
        with patch('idle_market.Market.fetch', side_effect=quote):
            second = create_app(self.path).extensions['idle_market']
            try:
                self.assertTrue(fetched.wait(2))
            finally:
                second.close()

    def test_upgrade_changes_old_default_but_preserves_custom_refresh(self):
        path = self.path / 'theme.conf'
        for old, expected in [('300',1800),('900',900)]:
            path.write_text('[theme]\nname=macos-dark\n[idle_display]\nrefresh_seconds='+old+'\n')
            upgrade(path)
            self.assertEqual(load(path)['refresh_seconds'], expected)
            self.assertIn('name=macos-dark', path.read_text())

    def test_theme_editor_validation_conflict_and_preservation(self):
        original = self.web.get('/api/theme-config').json['config']
        updated = original.replace('name = macos-light', 'name = classic-light')
        headers = {'X-Spotify-Control': '1'}
        response = self.web.post('/api/theme-config', json={'config':updated, 'original':original}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['config'], (self.path / 'theme.conf').read_text())
        self.assertIn('[idle_display]', response.json['config'])
        self.assertEqual(self.web.post('/api/theme-config', json={'config':updated, 'original':original}, headers=headers).status_code, 409)
        original = response.json['config']
        for invalid in ['no section', '[theme]\nmode=bad', '[theme]\nbackground=red', '[theme]\ntimezone=not/a/zone', '[theme]\nlight_start=25:00']:
            self.assertEqual(self.web.post('/api/theme-config', json={'config':invalid,'original':original}, headers=headers).status_code, 400)
            self.assertEqual((self.path / 'theme.conf').read_text(), original)
        self.assertEqual(self.web.post('/api/theme-config', json={'config':updated,'original':original}).status_code, 403)
        response = self.web.post('/api/theme-config', json={'config':'# custom\n[theme]\nname=macos-dark\n','original':original}, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn('# custom', response.json['config'])
        self.assertFalse(load(self.path / 'theme.conf')['enabled'])
