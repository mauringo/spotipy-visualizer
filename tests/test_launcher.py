import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_install_and_repeated_start_share_data_directory(self):
        with tempfile.TemporaryDirectory(prefix='spotify launcher ') as temporary:
            root = Path(temporary)
            snap = root / 'snap'
            data = root / 'snap data'
            bundled = snap / 'bin' / 'Flask'
            bundled.mkdir(parents=True)
            template = (ROOT / 'Flask/spotify.ini.example').read_text()
            (bundled / 'spotify.ini.example').write_text(template)
            theme_template = (ROOT / 'Flask/theme.conf.example').read_text()
            (bundled / 'theme.conf.example').write_text(theme_template)
            interpreter = snap / 'bin/python3'
            interpreter.write_text('#!/bin/sh\npwd\nprintf "%s\\n" "$1"\n')
            interpreter.chmod(0o755)
            env = dict(os.environ, SNAP=str(snap), SNAP_COMMON=str(data), SNAP_DATA=str(root / 'revision'))
            subprocess.run(['sh', str(ROOT / 'snap/hooks/install')], env=env, check=True)
            config = data / 'Flask' / 'spotify.ini'
            self.assertEqual(config.read_text(), template)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            config.write_text('existing configuration\n')
            theme = data / 'Flask' / 'theme.conf'
            self.assertEqual(theme.read_text(), theme_template)
            self.assertEqual(theme.stat().st_mode & 0o777, 0o600)
            theme.write_text('[theme]\nmode = manual\nname = classic-light\n')
            for _ in range(2):
                result = subprocess.run(['sh', str(ROOT / 'shscripts/runserver.wrapper')],
                                        env=env, check=True, capture_output=True, text=True)
                self.assertEqual(result.stdout.splitlines(), [str(data), str(bundled / 'app.py')])
            subprocess.run(['sh', str(ROOT / 'snap/hooks/install')], env=env, check=True)
            self.assertEqual(config.read_text(), 'existing configuration\n')
            self.assertTrue((data / 'Flask').is_dir())
            self.assertEqual(theme.read_text(), '[theme]\nmode = manual\nname = classic-light\n')

    def test_install_migrates_both_legacy_config_locations(self):
        for subdirectory in ('Flask', ''):
            with self.subTest(subdirectory=subdirectory), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                revision = root / 'revision'
                legacy = revision / subdirectory
                legacy.mkdir(parents=True)
                for name in ('spotify.ini', 'theme.conf'):
                    (legacy / name).write_text('saved ' + name)
                common = root / 'common'
                env = dict(os.environ, SNAP=str(root / 'snap'), SNAP_DATA=str(revision), SNAP_COMMON=str(common))
                subprocess.run(['sh', str(ROOT / 'snap/hooks/install')], env=env, check=True)
                for name in ('spotify.ini', 'theme.conf'):
                    config = common / 'Flask' / name
                    self.assertEqual(config.read_text(), 'saved ' + name)
                    self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_desktop_browser_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            log = root / 'calls'
            for name, code in [('snapctl', 0), ('xdg-open', 1), ('gio', 0)]:
                script = root / name
                script.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ' $*" >> "$CALL_LOG"\nexit ' + str(code) + '\n')
                script.chmod(0o755)
            env = dict(PATH=str(root), CALL_LOG=str(log), SNAP='/test/snap', PORT='61234')
            subprocess.run(['/bin/sh', str(ROOT / 'shscripts/desktop-launch')], env=env, check=True)
            self.assertEqual(log.read_text().splitlines(), ['snapctl user-open http://127.0.0.1:61234'])
            log.unlink()
            del env['SNAP']
            subprocess.run(['/bin/sh', str(ROOT / 'shscripts/desktop-launch')], env=env, check=True)
            self.assertEqual(log.read_text().splitlines(), ['xdg-open http://127.0.0.1:61234', 'gio open http://127.0.0.1:61234'])
            log.unlink()
            (root / 'gio').unlink()
            result = subprocess.run(['/bin/sh', str(ROOT / 'shscripts/desktop-launch')], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('http://127.0.0.1:61234', result.stderr)
