"""Optional Yahoo market pages and safe theme.conf settings updates."""
import configparser
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests
from flask import jsonify, request
from spotify_player import private_write

DEFAULTS = {'enabled': 'false', 'show_clock': 'true', 'show_rates': 'true',
            'show_stocks': 'true', 'page_seconds': '10', 'rates_seconds': '10', 'clock_seconds': '30', 'refresh_seconds': '1800',
            'symbols': 'AAPL,NVDA,OUST', 'idle_checks': '3', 'recovery_enabled': 'true',
            'recovery_stall_seconds': '5', 'stock_text_percent': '100', 'treasury_text_percent': '100'}
COMMENTS = {'idle_checks': 'Consecutive successful paused/stopped playback checks before showing the clock (1-20). Startup idle still opens immediately.','recovery_enabled': 'Repair stalled clock and market timers while browser JavaScript is running.',
            'recovery_stall_seconds': 'Display timer stall threshold (5-120 seconds), checked every 5 seconds. Does not change API retries.',
            'stock_text_percent': 'Stock text size as a percentage of the responsive default (80-130).',
            'treasury_text_percent': 'Treasury text size as a percentage of the responsive default (80-130).',
            'enabled': 'Optional idle-page rotation. Disabled on new installs and upgrades.',
            'show_clock': 'Include the clock in the rotation.',
            'show_rates': 'Include 2Y yield futures and 5Y/10Y/30Y Treasury yield indices (not Fed policy rates).',
            'show_stocks': 'Include one page per Yahoo stock symbol.',
            'clock_seconds': 'Seconds to show the clock per rotation (5-3600), independent of market pages.',
            'rates_seconds': 'Seconds on the Treasury rates page (5-300), independent of stock pages.',
            'page_seconds': 'Seconds per stock page (5-300). Page changes do not trigger Yahoo requests.',
            'refresh_seconds': 'Yahoo refresh interval (300-86400 seconds); default 1800 = 30 minutes. Refresh at startup, then cache. No guaranteed Yahoo quota.',
            'symbols': 'Comma-separated Yahoo symbols, maximum 12. Defaults: Apple, Nvidia, Ouster.'}
RATES = [('2YY=F', '2Y · yield futures'), ('^FVX', '5Y Treasury'),
         ('^TNX', '10Y Treasury'), ('^TYX', '30Y Treasury')]
SYMBOL = re.compile(r'[A-Z0-9^][A-Z0-9.^=\-]{0,19}')


def read(path):
    config = configparser.ConfigParser(interpolation=None)
    config.read(path)
    return config


def edit_section(original, changes):
    lines = original.splitlines(keepends=True)
    start = end = None
    for i, line in enumerate(lines):
        match = re.match(r'^\s*\[([^]]+)\]', line)
        if match:
            if start is not None:
                end = i
                break
            if match[1] == 'idle_display':
                start = i + 1
    if start is None:
        return original.rstrip() + '\n\n[idle_display]\n' + ''.join(
            f'# {COMMENTS[key]}\n{key} = {value}\n' for key, value in changes.items())
    end = len(lines) if end is None else end
    remaining = dict(changes)
    for i in range(start, end):
        match = re.match(r'^\s*([\w]+)\s*[=:]', lines[i])
        if match and match[1].lower() in remaining:
            key = match[1].lower()
            lines[i] = f'{key} = {remaining.pop(key)}\n'
    addition = ''.join(f'# {COMMENTS[key]}\n{key} = {value}\n' for key, value in remaining.items())
    return ''.join(lines[:end]).rstrip('\n') + '\n' + addition + ''.join(lines[end:])


def upgrade(path):
    try:
        config = read(path)
        missing = {key: value for key, value in DEFAULTS.items() if not config.has_option('idle_display', key)}
        if 'rates_seconds' in missing:
            previous = config.get('idle_display', 'page_seconds', fallback='10')
            if re.fullmatch(r'\d+', previous) and 5 <= int(previous) <= 300:
                missing['rates_seconds'] = previous
        # Replace the previous shipped 5-minute default when introducing clock timing.
        if 'clock_seconds' in missing and config.get('idle_display', 'refresh_seconds', fallback='') == '300':
            missing['refresh_seconds'] = '1800'
        if 'clock_seconds' in missing:
            try:
                old_refresh = config.getint('idle_display', 'refresh_seconds', fallback=1800)
                if old_refresh < 300:
                    missing['refresh_seconds'] = '300'
            except ValueError:
                pass
        if missing:
            private_write(path, edit_section(path.read_text(), missing))
    except (configparser.Error, UnicodeError):
        pass  # A malformed user file must never be overwritten.


def validate(values):
    result = {}
    for key in ('enabled', 'show_clock', 'show_rates', 'show_stocks', 'recovery_enabled'):
        value = values.get(key, DEFAULTS[key])
        if isinstance(value, bool):
            result[key] = value
        elif isinstance(value, str) and value.lower() in ('true', 'false'):
            result[key] = value.lower() == 'true'
        else:
            raise ValueError(f'{key} must be true or false.')
    for key, low, high in [('idle_checks', 1, 20), ('page_seconds', 5, 300), ('rates_seconds', 5, 300), ('clock_seconds', 5, 3600), ('refresh_seconds', 300, 86400), ('recovery_stall_seconds', 5, 120), ('stock_text_percent', 80, 130), ('treasury_text_percent', 80, 130)]:
        value = values.get(key, values.get('page_seconds', DEFAULTS[key]) if key == 'rates_seconds' else DEFAULTS[key])
        if isinstance(value, bool) or not re.fullmatch(r'\d+', str(value)) or not low <= int(value) <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}.')
        result[key] = int(value)
    symbols = values.get('symbols', DEFAULTS['symbols'])
    if isinstance(symbols, str):
        symbols = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    if not isinstance(symbols, list) or len(symbols) > 12 or any(not isinstance(s, str) or not SYMBOL.fullmatch(s) for s in symbols):
        raise ValueError('Enter up to 12 valid Yahoo symbols, separated by commas.')
    result['symbols'] = list(dict.fromkeys(symbols))
    if result['enabled'] and not (result['show_clock'] or result['show_rates'] or (result['show_stocks'] and symbols)):
        raise ValueError('Enable at least one page with content.')
    return result


def load(path):
    try:
        config = read(path)
        return validate(dict(config['idle_display']) if config.has_section('idle_display') else {})
    except (configparser.Error, ValueError, OSError, UnicodeError):
        return validate({})


class Market:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}
        self.retry_at = 0
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='yahoo')
        self.stop = threading.Event()
        self.worker = None
        self.path = None
        self.start_lock = threading.Lock()

    def refresh_once(self, path):
        settings = load(path)
        if settings['enabled']:
            symbols = ([s for s, _ in RATES] if settings['show_rates'] else []) + (settings['symbols'] if settings['show_stocks'] else [])
            self.quotes(list(dict.fromkeys(symbols)), settings['refresh_seconds'])

    def start(self, path):
        with self.start_lock:
            if self.worker is not None:
                return
            self.path = path
            def run():
                while not self.stop.is_set():
                    self.refresh_once(path)
                    self.stop.wait(5)
            self.worker = threading.Thread(target=run, name='yahoo-refresh', daemon=True)
            self.worker.start()

    def close(self):
        self.stop.set()
        if self.worker is not None:
            self.worker.join(timeout=15)
        self.pool.shutdown(wait=True, cancel_futures=True)

    def fetch(self, symbol):
        response = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe=''),
                                params={'interval': '1d', 'range': '1d'},
                                headers={'User-Agent': 'Mozilla/5.0 SpotipyVisualizer'}, timeout=(3, 5))
        response.raise_for_status()
        payload = response.json()['chart']['result'][0]['meta']
        price = payload.get('regularMarketPrice')
        timestamp = payload.get('regularMarketTime')
        if not isinstance(price, (int, float)) or not math.isfinite(price) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError('No current quote')
        previous = payload.get('previousClose', payload.get('chartPreviousClose'))
        change = ((price / previous - 1) * 100) if isinstance(previous, (int, float)) and previous > 0 else None
        return {'symbol': symbol, 'name': payload.get('shortName') or payload.get('longName') or symbol,
                'price': price, 'currency': payload.get('currency', ''),
                'change_percent': change if change is not None and math.isfinite(change) else None,
                'as_of': timestamp}

    def quotes(self, symbols, refresh):
        # Shared across displays, independent of the Spotify lock and rate budget.
        if not self.lock.acquire(blocking=False):
            return self.rows(symbols, refresh)
        try:
            now = time.monotonic()
            due = [s for s in symbols if now - self.cache.get(s, {}).get('checked', -float('inf')) >= refresh]
            if now < self.retry_at:
                due = []
            # Issue sequential requests so a 429 stops the rest of this batch.
            for symbol in due:
                if self.stop.is_set() or time.monotonic() < self.retry_at or (self.path is not None and not load(self.path)['enabled']):
                    break
                future = self.pool.submit(self.fetch, symbol)
                old = self.cache.get(symbol, {})
                try:
                    self.cache[symbol] = {'checked': now, 'quote': future.result(), 'error': False}
                except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as error:
                    if isinstance(error, requests.HTTPError) and error.response is not None and error.response.status_code == 429:
                        try:
                            wait = max(refresh, int(error.response.headers.get('Retry-After', '1800'))) + 2
                        except ValueError:
                            wait = max(refresh, 1800) + 2
                        self.retry_at = max(self.retry_at, now + wait)
                    self.cache[symbol] = {**old, 'checked': now, 'error': True}
            # Bound memory when the stock list changes repeatedly.
            for symbol in list(self.cache):
                if symbol not in symbols:
                    del self.cache[symbol]
            return self.rows(symbols, refresh)
        finally:
            self.lock.release()

    def rows(self, symbols, refresh):
        now = time.monotonic()
        results = []
        for symbol in symbols:
            item = self.cache.get(symbol, {})
            row = dict(item.get('quote', {'symbol': symbol, 'name': symbol, 'price': None, 'as_of': None}))
            row['stale'] = bool(item.get('error')) or now - item.get('checked', 0) >= refresh
            row['unavailable'] = row['price'] is None
            results.append(row)
        return results


def register_market(app, data_dir):
    path = data_dir / 'theme.conf'
    upgrade(path)
    lock = threading.Lock()
    market = Market()
    app.extensions['idle_market'] = market
    if load(path)['enabled']:
        market.start(path)

    @app.get('/settings')
    def settings_page():
        return app.send_static_file('settings.html')

    @app.get('/api/idle-settings')
    def settings_get():
        return jsonify(load(path))

    @app.post('/api/idle-settings')
    def settings_save():
        if request.headers.get('X-Spotify-Control') != '1' or (request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/')):
            return jsonify(error='Invalid settings request.'), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - set(DEFAULTS):
            return jsonify(error='Invalid settings.'), 400
        with lock:
            try:
                config = read(path)
                current = dict(config['idle_display']) if config.has_section('idle_display') else {}
                values = validate({**current, **body})
                changes = {k: ','.join(v) if isinstance(v, list) else str(v).lower() for k, v in values.items()}
                private_write(path, edit_section(path.read_text(), changes))
            except ValueError as error:
                return jsonify(error=str(error)), 400
            except (configparser.Error, OSError, UnicodeError):
                return jsonify(error='Cannot update theme.conf. Check its syntax and permissions.'), 409
        if values['enabled']:
            market.start(path)
        return jsonify(values)

    @app.get('/api/theme-config')
    def theme_config_get():
        try:
            return jsonify(config=path.read_text())
        except (OSError, UnicodeError):
            return jsonify(error='Cannot read theme.conf.'), 409

    @app.post('/api/theme-config')
    def theme_config_save():
        if request.headers.get('X-Spotify-Control') != '1' or (request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/')):
            return jsonify(error='Invalid settings request.'), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get('config'), str) or not isinstance(body.get('original'), str) or len(body['config']) > 32768:
            return jsonify(error='A configuration and its original text are required (maximum 32 KB).'), 400
        with lock:
            try:
                if path.read_text() != body['original']:
                    return jsonify(error='theme.conf changed since loading. Reload the configuration before saving.'), 409
                config = configparser.ConfigParser(interpolation=None)
                config.read_string(body['config'])
                if not config.has_section('theme'):
                    raise ValueError('The [theme] section is required.')
                from theme import PALETTES, MACOS
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
                values = config['theme']
                if values.get('mode', 'manual').strip() not in ('auto', 'manual'):
                    raise ValueError('Theme mode must be auto or manual.')
                for key in ('name', 'light_theme', 'dark_theme'):
                    if key in values and values[key].strip() not in {*PALETTES, 'macos', 'classic'}:
                        raise ValueError(f'Unknown theme: {key}.')
                for key in ('light_start', 'dark_start'):
                    if key in values and not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', values[key].strip()):
                        raise ValueError(f'{key} must use HH:MM (24-hour time).')
                for key in MACOS:
                    if values.get(key, '').strip() and not re.fullmatch(r'#[0-9a-fA-F]{6}', values[key].strip()):
                        raise ValueError(f'{key} must be blank or a six-digit hex color.')
                radius = values.get('artwork_radius', '').strip()
                if radius and (not radius.isascii() or not radius.isdigit() or not 0 <= int(radius) <= 48):
                    raise ValueError('artwork_radius must be blank or 0–48.')
                zone = values.get('timezone', '').strip()
                if zone:
                    try:
                        ZoneInfo(zone)
                    except (ZoneInfoNotFoundError, ValueError):
                        raise ValueError('Unknown timezone. Use an IANA name such as Europe/Rome.')
                idle = dict(config['idle_display']) if config.has_section('idle_display') else {}
                settings = validate(idle)
                text = body['config'].rstrip() + '\n'
                missing = {key: value for key, value in DEFAULTS.items() if key not in idle}
                if 'rates_seconds' in missing:
                    missing['rates_seconds'] = str(settings['rates_seconds'])
                if missing:
                    text = edit_section(text, missing)
                private_write(path, text)
            except (ValueError, configparser.Error) as error:
                return jsonify(error=str(error)), 400
            except (OSError, UnicodeError):
                return jsonify(error='Cannot write theme.conf. Check file permissions.'), 409
        if settings['enabled']:
            market.start(path)
        return jsonify(config=text)

    @app.get('/api/idle-market')
    def market_data():
        settings = load(path)
        if not settings['enabled']:
            return jsonify(rates=[], stocks=[], disabled=True)
        market.start(path)
        symbols = ([s for s, _ in RATES] if settings['show_rates'] else []) + (settings['symbols'] if settings['show_stocks'] else [])
        rows = {r['symbol']: r for r in market.rows(list(dict.fromkeys(symbols)), settings['refresh_seconds'])}
        return jsonify(rates=[{**rows[s], 'label': label} for s, label in RATES] if settings['show_rates'] else [],
                       stocks=[rows[s] for s in settings['symbols']] if settings['show_stocks'] else [],
                       source='Yahoo Finance', refresh_seconds=settings['refresh_seconds'])
