from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Flask'))
from app import create_app
from theme import selected_theme


class ThemeTests(unittest.TestCase):
    def selected_at(self, hour, minute=0, **overrides):
        settings = {'mode': 'auto', **overrides}
        with patch('theme.datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 19, hour, minute, tzinfo=ZoneInfo('UTC'))
            return selected_theme(settings)

    def test_default_schedule_boundaries(self):
        for hour, minute, name in [(5, 59, 'macos-dark'), (6, 0, 'macos-light'),
                                   (17, 59, 'macos-light'), (18, 0, 'macos-dark'),
                                   (0, 0, 'macos-dark')]:
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(self.selected_at(hour, minute, timezone='UTC'), name)

    def test_custom_overnight_and_equal_windows(self):
        settings = dict(light_start='22:30', dark_start='07:15',
                        light_theme='classic-light', dark_theme='classic-dark', timezone='UTC')
        for hour, minute, name in [(22, 29, 'classic-dark'), (22, 30, 'classic-light'),
                                   (0, 0, 'classic-light'), (7, 14, 'classic-light'),
                                   (7, 15, 'classic-dark')]:
            self.assertEqual(self.selected_at(hour, minute, **settings), name)
        self.assertEqual(self.selected_at(0, timezone='UTC', light_start='06:00', dark_start='06:00'), 'macos-light')

    def test_manual_and_legacy_names(self):
        for name, expected in [('macos', 'macos-light'), ('classic', 'classic-dark'),
                               ('macos-dark', 'macos-dark'), ('classic-light', 'classic-light')]:
            self.assertEqual(selected_theme({'name': name}), expected)
            self.assertEqual(selected_theme({'mode': 'manual', 'name': name}), expected)

    def test_invalid_settings_and_timezone(self):
        self.assertEqual(self.selected_at(12, timezone='UTC', light_start='25:00', dark_start='noon', light_theme='invalid'), 'macos-light')
        with patch('theme.datetime') as clock:
            clock.now.return_value.astimezone.return_value = datetime(2026, 9, 19, 20)
            self.assertEqual(selected_theme({'mode': 'auto', 'timezone': 'No/Such_Zone'}), 'macos-dark')
        with patch('theme.datetime') as clock:
            clock.now.return_value = datetime(2026, 9, 19, 6)
            self.assertEqual(selected_theme({'mode': 'auto', 'timezone': 'Europe/Rome'}), 'macos-light')
            clock.now.assert_called_once_with(ZoneInfo('Europe/Rome'))

    def test_clock_uses_theme_timezone_in_manual_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            (Path(directory) / 'theme.conf').write_text('[theme]\nmode=manual\nname=classic-dark\ntimezone=Europe/Rome\n')
            with patch('theme.datetime') as clock:
                clock.now.return_value = datetime(2026, 9, 20, 6, 23, tzinfo=ZoneInfo('Europe/Rome'))
                response = app.test_client().get('/theme.css')
                self.assertEqual(response.headers['X-Clock-Time'], '2026-09-20T06:23:00+02:00')
                clock.now.assert_called_once_with(ZoneInfo('Europe/Rome'))
                self.assertIn('color-scheme:dark', response.text)

    def test_all_palettes_and_live_schedule_css(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            client = app.test_client()
            config = Path(directory) / 'theme.conf'
            for name, scheme, background in [
                ('macos-light', 'light', '#f2f2f7'), ('macos-dark', 'dark', '#1c1c1e'),
                ('classic-light', 'light', '#f7faf8'), ('classic-dark', 'dark', None),
            ]:
                config.write_text(f'[theme]\nmode = manual\nname = {name}\n')
                css = client.get('/theme.css').text
                self.assertIn(f'color-scheme:{scheme}', css)
                if background:
                    self.assertIn(f'--background:{background}', css)
                self.assertEqual('font-family:-apple-system' in css, name.startswith('macos'))
            config.write_text('[theme]\nmode = auto\ntimezone = UTC\n')
            with patch('theme.datetime') as clock:
                clock.now.return_value = datetime(2026, 9, 19, 12)
                self.assertIn('color-scheme:light', client.get('/theme.css').text)
                clock.now.return_value = datetime(2026, 9, 19, 20)
                self.assertIn('color-scheme:dark', client.get('/theme.css').text)
