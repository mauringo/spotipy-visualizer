import configparser
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Flask'))
from app import create_app
from spotify_config import OPTIONS
from spotify_player import initialize
from spotipy import SpotifyException

HEADERS = {'X-Spotify-Control': '1'}
URI = 'spotify:track:1234567890123456789012'


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.app = create_app(self.path)
        self.web = self.app.test_client()
        self.player = self.app.extensions['spotify_player']
        self.spotify = Mock()
        self.spotify.current_playback.return_value = {
            'item': {'type': 'track', 'uri': URI, 'duration_ms': 180000},
            'device': {'name': 'Speaker'}, 'is_playing': True, 'progress_ms': 1000,
        }
        self.spotify.current_user_saved_tracks_contains.return_value = [True]
        self.client = patch.object(self.player, 'client', return_value=self.spotify).start()
        self.addCleanup(patch.stopall)

    def configure(self, values):
        (self.path / 'spotify.ini').write_text('[spotify]\nclient_id=example\n[rate_limit]\n' + values)

    def test_upgrade_preserves_credentials_comments_and_other_sections(self):
        config = self.path / 'spotify.ini'
        config.write_text('# Keep this comment\n[spotify]\nclient_id = mine\nclient_secret = a%secret\n'
                          '[rate_limit]\n# custom interval\nplayback_poll_seconds = 45\n'
                          '[other]\nsetting = keep\n')
        initialize(self.path)
        text = config.read_text()
        parsed = configparser.ConfigParser(interpolation=None)
        parsed.read(config)
        self.assertEqual(parsed['spotify']['client_secret'], 'a%secret')
        self.assertEqual(parsed['rate_limit']['playback_poll_seconds'], '45')
        self.assertEqual(parsed['other']['setting'], 'keep')
        self.assertIn('# custom interval', text)
        for key in OPTIONS:
            self.assertIn(key, parsed['rate_limit'])
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        initialize(self.path)
        self.assertEqual(config.read_text(), text)
        config.write_text('[spotify]\nclient_id=mine\n')
        initialize(self.path)
        self.assertIn('[rate_limit]', config.read_text())
        config.write_text('malformed file')
        initialize(self.path)
        self.assertEqual(config.read_text(), 'malformed file')

    def test_invalid_tuning_falls_back_and_edits_reload(self):
        self.configure('playback_poll_seconds=0\nidle_poll_seconds=NaN\nliked_cache_seconds=999999\n')
        settings = self.player.settings()
        self.assertEqual(settings['playback_poll_seconds'], 15)
        self.assertEqual(settings['idle_poll_seconds'], 60)
        self.assertEqual(settings['liked_cache_seconds'], 600)
        self.configure('playback_poll_seconds=30\n')
        self.assertEqual(self.player.settings()['playback_poll_seconds'], 30)

    def test_displays_share_cache_and_progress_does_not_rewind(self):
        with patch('spotify_player.time.monotonic', return_value=100) as clock:
            first = self.web.get('/api/playback')
            self.assertEqual(first.json['poll_after_ms'], 15000)
            clock.return_value = 105
            second = self.app.test_client().get('/api/playback')
            self.assertEqual(second.json['progress_ms'], 6000)
            self.assertEqual(second.json['poll_after_ms'], 10000)
            self.client.assert_called_once()
            self.spotify.current_playback.assert_called_once()
            clock.return_value = 115
            self.web.get('/api/playback')
            self.assertEqual(self.spotify.current_playback.call_count, 2)
            self.spotify.current_user_saved_tracks_contains.assert_called_once()
            clock.return_value = 701
            self.web.get('/api/playback')
            self.assertEqual(self.spotify.current_user_saved_tracks_contains.call_count, 2)

    def test_idle_polling_and_like_control_cache(self):
        self.spotify.current_playback.return_value['is_playing'] = False
        with patch('spotify_player.time.monotonic', return_value=100) as clock:
            self.assertEqual(self.web.get('/api/playback').json['poll_after_ms'], 60000)
            response = self.web.post('/api/control/like', json={'uri': URI, 'liked': False}, headers=HEADERS)
            self.assertEqual(response.status_code, 200)
            clock.return_value = 102
            self.assertFalse(self.web.get('/api/playback').json['liked'])
            self.spotify.current_user_saved_tracks_contains.assert_called_once()

    def test_global_budget_and_control_spacing(self):
        self.configure('max_requests_per_30_seconds=2\n')
        with patch('spotify_player.time.monotonic', return_value=100) as clock:
            self.web.get('/api/playback')  # playback + liked status exhaust the budget
            response = self.web.post('/api/control/next', headers=HEADERS)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.json['state'], 'throttled')
            self.assertEqual(response.headers['Retry-After'], '30')
            self.spotify.next_track.assert_not_called()
            clock.return_value = 130
            self.assertEqual(self.web.post('/api/control/next', headers=HEADERS).status_code, 200)
            self.assertEqual(self.web.post('/api/control/pause', headers=HEADERS).status_code, 429)
            self.spotify.pause_playback.assert_not_called()
            clock.return_value = 132
            self.assertEqual(self.web.post('/api/control/pause', headers=HEADERS).status_code, 200)

    def test_retry_after_blocks_all_calls_survives_restart_and_slows_polling(self):
        with patch('spotify_player.time.monotonic', return_value=100) as clock:
            self.spotify.current_playback.side_effect = SpotifyException(429, -1, 'slow down', headers={'Retry-After': '3600'})
            response = self.web.get('/api/playback')
            self.assertEqual(response.headers['Retry-After'], '3602')
            self.assertEqual(response.json['retry_after_seconds'], 3602)
            for _ in range(3):
                self.assertEqual(self.web.get('/api/playback').status_code, 429)
                self.assertEqual(self.web.post('/api/control/next', headers=HEADERS).status_code, 429)
            self.spotify.current_playback.assert_called_once()
            self.spotify.next_track.assert_not_called()
            restarted = create_app(self.path)
            self.assertEqual(restarted.test_client().get('/api/playback').status_code, 429)
            self.assertEqual((self.path / '.spotify-rate-limit.json').stat().st_mode & 0o777, 0o600)
            clock.return_value = 3702
            self.spotify.current_playback.side_effect = None
            self.assertEqual(self.web.get('/api/playback').json['poll_after_ms'], 30000)

    def test_fallback_increases_and_header_case_is_ignored(self):
        with patch('spotify_player.time.monotonic', return_value=100):
            self.assertEqual(self.player.rate_limited({'retry-after': '12'}), 14)
            self.assertEqual(self.player.rate_limited({'Retry-After': 'NaN'}), 122)
            self.assertEqual(self.player.rate_limited(None), 242)
            self.assertEqual(self.player.rate_limited({'Retry-After': '-3'}), 482)

    def test_optional_like_read_is_deferred_when_budget_is_full(self):
        self.configure('max_requests_per_30_seconds=2\n')
        with patch('spotify_player.time.monotonic', return_value=100) as clock:
            self.player.calls.append(99)
            response = self.web.get('/api/playback')
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json['can_like'])
            self.spotify.current_user_saved_tracks_contains.assert_not_called()
            clock.return_value = 130
            response = self.web.get('/api/playback')
            self.assertTrue(response.json['can_like'])
            self.assertTrue(response.json['liked'])

    def test_public_recovery_settings_are_safe_and_allow_slow_upstream(self):
        self.configure('spotify_request_timeout_seconds=20\nbrowser_request_timeout_seconds=10\nnetwork_retry_seconds=45\n')
        response = self.web.get('/api/client-settings')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'request_timeout_ms': 120000, 'recovery_grace_ms': 15000, 'network_retry_ms': 45000})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.client.assert_not_called()
        self.assertNotIn('client_id', response.text)

    def test_invalid_controls_do_not_consume_budget(self):
        response = self.web.post('/api/control/shuffle', json={'state': 'false'}, headers=HEADERS)
        self.assertEqual(response.status_code, 400)
        self.client.assert_not_called()
        self.assertEqual(len(self.player.calls), 0)
