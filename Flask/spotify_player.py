from collections import deque
import math
import configparser
import functools
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import jsonify, redirect, request, session
from spotify_config import tuning, upgraded_config
import requests
import spotipy
from spotipy.cache_handler import CacheHandler
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError


SCOPES = 'user-read-playback-state user-modify-playback-state user-library-read user-library-modify'
TEMPLATE = Path(__file__).with_name('spotify.ini.example').read_text()


def default_data_dir():
    if os.environ.get('SNAP_COMMON'):
        return Path(os.environ['SNAP_COMMON']) / 'Flask'
    return Path(__file__).resolve().parent


def private_write(path, text):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(text)
    temporary.chmod(0o600)
    temporary.replace(path)


def initialize(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    # Preserve credentials from revisions that used revision-specific storage.
    if os.environ.get('SNAP_COMMON') and os.environ.get('SNAP_DATA') and data_dir == default_data_dir():
        for name in ('spotify.ini', '.spotify-token.json', '.session-key'):
            destination = data_dir / name
            for legacy in (Path(os.environ['SNAP_DATA']) / 'Flask' / name,
                           Path(os.environ['SNAP_DATA']) / name):
                if not destination.exists() and legacy.is_file():
                    private_write(destination, legacy.read_text())
    config = data_dir / 'spotify.ini'
    if not config.exists():
        private_write(config, TEMPLATE)
    updated = upgraded_config(config)
    if updated is not None:
        private_write(config, updated)
    config.chmod(0o600)
    key = data_dir / '.session-key'
    if not key.exists():
        private_write(key, secrets.token_hex(32))
    key.chmod(0o600)
    return key.read_text().strip()


class PrivateCache(CacheHandler):
    def __init__(self, path):
        self.path = path

    def get_cached_token(self):
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return None

    def save_token_to_cache(self, token_info):
        private_write(self.path, json.dumps(token_info))


class PlayerError(Exception):
    def __init__(self, message, status=400, state='error', retry_after=0):
        self.message, self.status, self.state = message, status, state
        self.retry_after = retry_after


class Player:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.lock = threading.RLock()
        self.snapshot = None
        self.snapshot_at = 0
        self.retry_at = 0
        self.calls = deque()
        self.control_at = -float('inf')
        self.liked = {}
        self.backoff = 1
        self.cooldown_file = data_dir / '.spotify-rate-limit.json'
        try:
            saved = json.loads(self.cooldown_file.read_text())
            remaining = float(saved['until']) - time.time()
            if math.isfinite(remaining) and remaining > 0:
                self.retry_at = time.monotonic() + remaining
                self.backoff = max(1, min(8, int(saved.get('backoff', 1))))
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            pass

    def settings(self):
        return tuning(self.data_dir / 'spotify.ini')

    def check_cooldown(self):
        remaining = self.retry_at - time.monotonic()
        if remaining > 0:
            raise PlayerError('Spotify is cooling down. Playback will refresh automatically.',
                              429, 'rate_limited', math.ceil(remaining))

    def budget_wait(self):
        now = time.monotonic()
        while self.calls and now - self.calls[0] >= 30:
            self.calls.popleft()
        limit = self.settings()['max_requests_per_30_seconds']
        return max(0, self.calls[-limit] + 30 - now) if len(self.calls) >= limit else 0

    def call(self, method, *args):
        self.check_cooldown()
        wait = self.budget_wait()
        if wait:
            raise PlayerError('Request budget reached. Please wait before trying again.',
                              429, 'throttled', math.ceil(wait))
        self.calls.append(time.monotonic())
        return method(*args)

    def rate_limited(self, headers):
        settings = self.settings()
        fallback = settings['retry_after_fallback_seconds'] * self.backoff
        try:
            value = next((v for k, v in (headers or {}).items() if k.lower() == 'retry-after'), None)
            delay = float(value)
            if not math.isfinite(delay) or delay < 0:
                raise ValueError()
        except (TypeError, ValueError):
            delay = fallback
        delay = math.ceil(delay) + settings['retry_after_buffer_seconds']
        self.backoff = min(8, self.backoff * 2)
        self.retry_at = time.monotonic() + delay
        private_write(self.cooldown_file, json.dumps({'until': time.time() + delay, 'backoff': self.backoff}))
        return delay

    def poll_seconds(self):
        settings = self.settings()
        key = 'playback_poll_seconds' if self.snapshot and self.snapshot['playing'] else 'idle_poll_seconds'
        return settings[key] * self.backoff

    def cached_playback(self):
        result = dict(self.snapshot)
        age = max(0, time.monotonic() - self.snapshot_at)
        if result['playing']:
            result['progress_ms'] = min(result['duration_ms'], result['progress_ms'] + int(age * 1000))
        result['poll_after_ms'] = math.ceil(max(1, self.poll_seconds() - age) * 1000)
        return result

    def oauth(self):
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(self.data_dir / 'spotify.ini')
            settings = config['spotify']
            client_id = settings.get('client_id', '').strip()
            client_secret = settings.get('client_secret', '').strip()
            uri = settings.get('redirect_uri', '').strip()
            parsed = urlsplit(uri)
            if not client_id or not client_secret:
                raise ValueError()
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                    or parsed.path != '/auth/callback' or parsed.query or parsed.fragment
                    or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', '::1'))):
                raise ValueError()
        except (configparser.Error, KeyError, ValueError):
            raise PlayerError('Configure client_id, client_secret and redirect_uri in spotify.ini.',
                              503, 'configuration_required')
        return SpotifyOAuth(client_id=client_id, client_secret=client_secret,
                            redirect_uri=uri, scope=SCOPES, open_browser=False,
                            cache_handler=PrivateCache(self.data_dir / '.spotify-token.json'),
                            requests_timeout=10)

    def client(self):
        self.check_cooldown()
        oauth = self.oauth()
        token = oauth.validate_token(oauth.cache_handler.get_cached_token())
        if not token:
            raise PlayerError('Connect your Spotify account.', 401, 'authorization_required')
        return spotipy.Spotify(auth=token['access_token'], requests_timeout=10, retries=0,
                             status_retries=0)

    def playback(self):
        self.check_cooldown()
        if self.snapshot is not None and time.monotonic() - self.snapshot_at < self.poll_seconds():
            return self.cached_playback()
        client = self.client()
        playback = self.call(client.current_playback) or {}
        item = playback.get('item') or {}
        album = item.get('album') or item.get('show') or {}
        images = album.get('images') or item.get('images') or []
        uri = item.get('uri', '')
        can_like = item.get('type') == 'track' and not item.get('is_local') and bool(uri)
        device = playback.get('device') or {}
        liked = None
        if can_like:
            cached = self.liked.get(uri)
            if cached:
                liked = cached[0]
            if (not cached or time.monotonic() - cached[1] >= self.settings()['liked_cache_seconds']) and not self.budget_wait():
                liked = self.call(client.current_user_saved_tracks_contains, [uri])[0]
                if len(self.liked) >= 256:
                    self.liked.pop(next(iter(self.liked)))
                self.liked[uri] = (liked, time.monotonic())
        self.snapshot = {
            'state': 'ready' if item else 'idle',
            'name': item.get('name', 'Nothing playing'),
            'artists': ', '.join(a['name'] for a in item.get('artists', [])) or album.get('publisher', ''),
            'album': album.get('name', ''),
            'image': images[0]['url'] if images else None,
            'url': (item.get('external_urls') or {}).get('spotify'),
            'uri': uri, 'playing': bool(playback.get('is_playing')),
            'shuffle': bool(playback.get('shuffle_state')),
            'progress_ms': playback.get('progress_ms') or 0,
            'duration_ms': item.get('duration_ms') or 0,
            'device': device.get('name', ''),
            'controllable': bool(device) and not device.get('is_restricted', False),
            'disallows': (playback.get('actions') or {}).get('disallows', {}),
            'can_like': can_like and liked is not None,
            'liked': bool(liked),
        }
        self.snapshot_at = time.monotonic()
        return self.cached_playback()


def register_player(app, data_dir):
    app.secret_key = initialize(data_dir)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    player = Player(data_dir)
    app.extensions['spotify_player'] = player

    def guarded(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with player.lock:
                try:
                    return fn(*args, **kwargs)
                except PlayerError as error:
                    response = jsonify(state=error.state, error=error.message, retry_after_seconds=error.retry_after)
                    if error.retry_after:
                        response.headers['Retry-After'] = str(error.retry_after)
                    return response, error.status
                except SpotifyOauthError:
                    return jsonify(state='authorization_required', error='Spotify authorization failed. Check your credentials and reconnect.'), 401
                except spotipy.SpotifyException as error:
                    status = error.http_status
                    messages = {401: 'Reconnect your Spotify account.',
                                403: 'Spotify denied this action. Check Premium, app access and playback restrictions.',
                                404: 'No active Spotify device. Start playback in Spotify.',
                                429: 'Spotify is rate limiting requests. Retrying shortly.'}
                    if status == 429:
                        delay = player.rate_limited(error.headers)
                        response = jsonify(state='rate_limited', error=messages[429], retry_after_seconds=delay)
                        response.headers['Retry-After'] = str(delay)
                        return response, 429
                    return jsonify(state='authorization_required' if status == 401 else 'error',
                                   error=messages.get(status, 'Spotify could not complete this request.')), status if status in messages else 502
                except requests.RequestException:
                    return jsonify(state='error', error='Cannot reach Spotify. Retrying shortly.'), 502
        return wrapped

    @app.after_request
    def no_cache(response):
        if request.path.startswith(('/api/', '/auth/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/auth/login')
    @guarded
    def login():
        oauth = player.oauth()
        # Keep the session cookie on the same host as the registered callback.
        target = urlsplit(oauth.redirect_uri)
        if request.host != target.netloc or request.scheme != target.scheme:
            return redirect(f'{target.scheme}://{target.netloc}/auth/login')
        session['oauth_state'] = secrets.token_urlsafe(32)
        session['oauth_started'] = time.time()
        return redirect(oauth.get_authorize_url(state=session['oauth_state']))

    @app.get('/auth/callback')
    @guarded
    def callback():
        expected = session.pop('oauth_state', None)
        started = session.pop('oauth_started', 0)
        if not expected or not secrets.compare_digest(expected, request.args.get('state', '')) or time.time() - started > 600:
            raise PlayerError('Authorization expired or invalid. Connect again.')
        if request.args.get('error') or not request.args.get('code'):
            return redirect('/?auth=denied')
        player.oauth().get_access_token(request.args['code'], check_cache=False)
        player.snapshot = None
        return redirect('/')

    @app.get('/api/playback')
    @guarded
    def playback():
        return jsonify(player.playback())

    @app.post('/api/control/<action>')
    @guarded
    def control(action):
        if request.headers.get('X-Spotify-Control') != '1' or (request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/')):
            raise PlayerError('Invalid control request.', 403)
        body = request.get_json(silent=True) or {}
        actions = {'previous': 'previous_track', 'next': 'next_track',
                   'play': 'start_playback', 'pause': 'pause_playback'}
        if action == 'shuffle':
            if not isinstance(body, dict) or type(body.get('state')) is not bool:
                raise PlayerError('A shuffle state boolean is required.')
        elif action == 'like':
            if not isinstance(body, dict) or not re.fullmatch(r'spotify:track:[A-Za-z0-9]{22}', str(body.get('uri', ''))) or type(body.get('liked')) is not bool:
                raise PlayerError('A track URI and liked boolean are required.')
        elif action not in actions:
            raise PlayerError('Unknown action.', 404)
        player.check_cooldown()
        wait = player.settings()['control_interval_seconds'] - (time.monotonic() - player.control_at)
        if wait > 0:
            raise PlayerError('Please wait before the next control command.', 429, 'throttled', math.ceil(wait))
        client = player.client()
        if action in actions:
            player.call(getattr(client, actions[action]))
        elif action == 'shuffle':
            player.call(client.shuffle, body['state'])
        else:
            method = client.current_user_saved_tracks_add if body['liked'] else client.current_user_saved_tracks_delete
            player.call(method, [body['uri']])
            player.liked[body['uri']] = (body['liked'], time.monotonic())
        player.control_at = time.monotonic()
        player.snapshot = None
        return jsonify(ok=True, poll_after_ms=2000)



if __name__ == '__main__':
    initialize(default_data_dir())
