from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Flask'))
from app import create_app
from spotify_player import PrivateCache
from spotipy import SpotifyException

URI = 'spotify:track:1234567890123456789012'
HEADERS = {'X-Spotify-Control': '1'}


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.app = create_app(self.directory)
        self.app.testing = True
        self.web = self.app.test_client()
        self.player = self.app.extensions['spotify_player']

    def configured(self):
        (self.directory / 'spotify.ini').write_text(
            '[spotify]\nclient_id = example\nclient_secret = secret\n'
            'redirect_uri = http://127.0.0.1:60123/auth/callback\n')

    def test_private_config_created_and_not_overwritten(self):
        config = self.directory / 'spotify.ini'
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.configured()
        key = self.app.secret_key
        self.assertEqual(create_app(self.directory).secret_key, key)
        self.assertIn('client_id = example', config.read_text())
        self.assertEqual(self.web.get('/api/playback').status_code, 401)
        self.assertEqual(self.web.get('/spotify.ini').status_code, 404)

    def test_missing_credentials(self):
        response = self.web.get('/api/playback')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['state'], 'configuration_required')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_default_configuration_locations(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.register_player') as register:
            create_app()
            self.assertEqual(register.call_args.args[1], Path(__file__).resolve().parents[1] / 'Flask')
        with patch.dict(os.environ, {'SNAP_COMMON': self.temp.name}), patch('app.register_player') as register:
            create_app()
            self.assertEqual(register.call_args.args[1], self.directory / 'Flask')

    def test_common_storage_migrates_and_survives_revision_change(self):
        legacy = self.directory / 'revision-1' / 'Flask'
        legacy.mkdir(parents=True)
        (legacy / 'spotify.ini').write_text('old configuration')
        (legacy / '.session-key').write_text('persistent-key')
        (legacy / '.spotify-token.json').write_text('{"access_token": "saved-token"}')
        common = self.directory / 'common'
        with patch.dict(os.environ, {'SNAP_COMMON': str(common), 'SNAP_DATA': str(legacy.parent)}):
            app = create_app()
            self.assertEqual(app.secret_key, 'persistent-key')
            for name in ('spotify.ini', '.session-key', '.spotify-token.json'):
                target = common / 'Flask' / name
                self.assertEqual(target.read_text(), (legacy / name).read_text())
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            (common / 'Flask' / 'spotify.ini').write_text('updated configuration')
            create_app()
            self.assertEqual((common / 'Flask' / 'spotify.ini').read_text(), 'updated configuration')
        with patch.dict(os.environ, {'SNAP_COMMON': str(common), 'SNAP_DATA': str(self.directory / 'revision-2')}):
            self.assertEqual(create_app().secret_key, 'persistent-key')

    def test_cache_private_and_readable(self):
        path = self.directory / '.spotify-token.json'
        cache = PrivateCache(path)
        self.assertIsNone(cache.get_cached_token())
        cache.save_token_to_cache({'access_token': 'example'})
        self.assertEqual(cache.get_cached_token()['access_token'], 'example')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_callback_rejects_missing_wrong_and_expired_state(self):
        for expected, age in [(None, 0), ('different', 0), ('test', 601)]:
            with self.web.session_transaction() as session:
                session['oauth_state'] = expected
                session['oauth_started'] = time.time() - age
            with patch.object(self.player, 'oauth') as oauth:
                response = self.web.get('/auth/callback?state=test&code=code')
                self.assertEqual(response.status_code, 400)
                oauth.assert_not_called()

    def test_login_and_callback(self):
        self.configured()
        response = self.web.get('/auth/login', base_url='http://127.0.0.1:60123')
        self.assertTrue(response.location.startswith('https://accounts.spotify.com/authorize?'))
        with self.web.session_transaction() as session:
            session['oauth_state'] = 'test'
            session['oauth_started'] = time.time()
        with patch.object(self.player, 'oauth') as oauth:
            response = self.web.get('/auth/callback?state=test&code=code')
            self.assertEqual(response.status_code, 302)
            oauth.return_value.get_access_token.assert_called_once_with('code', check_cache=False)
        self.assertEqual(self.web.get('/auth/callback?state=test&code=code').status_code, 400)

    def test_playback_and_controls(self):
        spotify = Mock()
        spotify.current_playback.return_value = {
            'item': {'name': 'Song', 'type': 'track', 'uri': URI, 'duration_ms': 100000,
                     'artists': [{'name': 'Artist'}], 'album': {'name': 'Album', 'images': [{'url': 'https://example.com/art.jpg'}]}},
            'device': {'name': 'Speaker'}, 'is_playing': True, 'progress_ms': 1234,
        }
        spotify.current_user_saved_tracks_contains.return_value = [True]
        with patch.object(self.player, 'client', return_value=spotify):
            response = self.web.get('/api/playback')
            self.assertEqual(response.json['album'], 'Album')
            self.assertTrue(response.json['liked'])
            self.web.get('/api/playback')
            spotify.current_playback.assert_called_once()
            for action, method in [('next', 'next_track'), ('previous', 'previous_track'), ('play', 'start_playback'), ('pause', 'pause_playback')]:
                self.assertEqual(self.web.post('/api/control/' + action, headers=HEADERS).status_code, 200)
                getattr(spotify, method).assert_called_once()
            for liked, method in [(True, 'current_user_saved_tracks_add'), (False, 'current_user_saved_tracks_delete')]:
                self.assertEqual(self.web.post('/api/control/like', headers=HEADERS, json={'uri': URI, 'liked': liked}).status_code, 200)
                getattr(spotify, method).assert_called_once_with([URI])
            self.assertEqual(self.web.post('/api/control/like', headers=HEADERS, json={'uri': URI, 'liked': 'false'}).status_code, 400)
            self.assertEqual(self.web.post('/api/control/unknown', headers=HEADERS).status_code, 404)

    def test_shuffle_state_and_validation(self):
        spotify = Mock()
        spotify.current_playback.return_value = {'shuffle_state': True}
        with patch.object(self.player, 'client', return_value=spotify):
            self.assertTrue(self.web.get('/api/playback').json['shuffle'])
            for state in (False, True):
                response = self.web.post('/api/control/shuffle', headers=HEADERS, json={'state': state})
                self.assertEqual(response.status_code, 200)
                spotify.shuffle.assert_called_with(state)
                self.assertIsNone(self.player.snapshot)
            spotify.shuffle.reset_mock()
            for body in ({}, {'state': 'false'}, {'state': 1}, ['invalid']):
                self.assertEqual(self.web.post('/api/control/shuffle', headers=HEADERS, json=body).status_code, 400)
            spotify.shuffle.assert_not_called()

    def test_theme_reload_validation_and_preservation(self):
        config = self.directory / 'theme.conf'
        self.assertTrue(config.exists())
        config.write_text('[theme]\nmode = manual\nname = macos-light\n')
        response = self.web.get('/theme.css')
        self.assertIn('--accent:#007aff', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        config.write_text('[theme]\nname = classic\naccent = #abcdef\nartwork_radius = 12\n')
        create_app(self.directory)
        css = self.web.get('/theme.css').text
        self.assertIn('--accent:#abcdef', css)
        self.assertIn('border-radius:12px', css)
        self.assertNotIn('color-scheme:light', css)
        config.write_text('[theme]\naccent = red;}body{display:none\nartwork_radius = 999\n')
        css = self.web.get('/theme.css').text
        self.assertNotIn('display:none', css)
        self.assertNotIn('999px', css)
        config.write_text('invalid configuration')
        self.assertEqual(self.web.get('/theme.css').status_code, 200)
        self.assertEqual(self.web.get('/theme.conf').status_code, 404)

    def test_cross_origin_and_get_cannot_control(self):
        with patch.object(self.player, 'client') as client:
            self.assertEqual(self.web.post('/api/control/next').status_code, 403)
            self.assertEqual(self.web.post('/api/control/next', headers={**HEADERS, 'Origin': 'https://other.example'}).status_code, 403)
            self.assertEqual(self.web.get('/api/control/next').status_code, 405)
            client.assert_not_called()

    def test_idle_and_rate_limit(self):
        spotify = Mock()
        spotify.current_playback.return_value = None
        with patch.object(self.player, 'client', return_value=spotify):
            response = self.web.get('/api/playback')
            self.assertEqual(response.json['state'], 'idle')
            self.assertFalse(response.json['can_like'])
            spotify.current_user_saved_tracks_contains.assert_not_called()
            spotify.next_track.side_effect = SpotifyException(429, -1, 'slow down', headers={'Retry-After': '60'})
            response = self.web.post('/api/control/next', headers=HEADERS)
            self.assertEqual(response.status_code, 429)
        self.assertGreater(self.player.retry_at, time.monotonic() + 50)
        self.assertEqual(self.web.get('/api/playback').status_code, 429)

    def test_refresh_uses_cached_token_without_interactive_login(self):
        self.configured()
        with patch('spotify_player.SpotifyOAuth') as oauth, patch('spotify_player.spotipy.Spotify') as spotify:
            oauth.return_value.validate_token.return_value = {'access_token': 'refreshed'}
            self.player.client()
            self.assertEqual(spotify.call_args.kwargs['auth'], 'refreshed')
            oauth.return_value.get_access_token.assert_not_called()

    def test_only_player_routes_remain(self):
        with self.web.get('/') as response:
            self.assertEqual(response.status_code, 200)
        for path in ['/usagedata', '/listDevices', '/systemdevices', '/static/games/snake/index.html']:
            self.assertEqual(self.web.get(path).status_code, 404)


if __name__ == '__main__':
    unittest.main()
