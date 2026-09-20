"""Small, validated appearance configuration independent of Spotify credentials."""
import configparser
from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Response

from spotify_player import private_write

MACOS = {
    'accent': '#007aff', 'background': '#f2f2f7', 'foreground': '#1d1d1f',
    'muted': '#6e6e73', 'surface': '#ffffff', 'border': '#d1d1d6',
    'hover': '#e3e3ea',
}

MACOS_DARK = {
    'accent': '#0a84ff', 'background': '#1c1c1e', 'foreground': '#f5f5f7',
    'muted': '#aeaeb2', 'surface': '#2c2c2e', 'border': '#48484a',
    'hover': '#3a3a3c',
}
CLASSIC_LIGHT = {
    'accent': '#087f3e', 'background': '#f7faf8', 'foreground': '#14251b',
    'muted': '#58675e', 'surface': '#e7efe9', 'border': '#c4d1c8',
    'hover': '#dce8e0',
}
PALETTES = {'macos-light': MACOS, 'macos-dark': MACOS_DARK,
            'classic-light': CLASSIC_LIGHT, 'classic-dark': {}}


def theme_name(value, fallback):
    value = value.strip().lower()
    value = {'macos': 'macos-light', 'classic': 'classic-dark'}.get(value, value)
    return value if value in PALETTES else fallback


def minutes(value, fallback):
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
        value = fallback
    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute


def selected_theme(settings):
    # Old configurations without a mode retain their manually selected theme.
    if settings.get('mode', 'manual').strip().lower() != 'auto':
        return theme_name(settings.get('name', 'macos'), 'macos-light')
    zone = settings.get('timezone', '').strip()
    try:
        now = datetime.now(ZoneInfo(zone)) if zone else datetime.now().astimezone()
    except (ZoneInfoNotFoundError, ValueError):
        now = datetime.now().astimezone()
    start = minutes(settings.get('light_start', '06:00').strip(), '06:00')
    end = minutes(settings.get('dark_start', '18:00').strip(), '18:00')
    current = now.hour * 60 + now.minute
    # Equal times mean light all day; reversed times allow an overnight window.
    light = (start <= current < end) if start < end else (current >= start or current < end)
    key = 'light_theme' if light else 'dark_theme'
    return theme_name(settings.get(key, ''), 'macos-light' if light else 'macos-dark')


def register_theme(app, data_dir):
    path = data_dir / 'theme.conf'
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        private_write(path, Path(__file__).with_name('theme.conf.example').read_text())

    @app.get('/theme.css')
    def theme_css():
        config = configparser.ConfigParser(interpolation=None)
        try:
            config.read(path)
            settings = dict(config['theme']) if config.has_section('theme') else {}
        except (configparser.Error, OSError, UnicodeError):
            settings = {}
        name = selected_theme(settings)
        macos = name.startswith('macos-')
        colors = dict(PALETTES[name])
        for key in MACOS:
            value = settings.get(key, '').strip()
            if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                colors[key] = value
        variables = ''.join(f'--{key}:{value};' for key, value in colors.items())
        scheme = 'light' if name.endswith('-light') else 'dark'
        css = ':root{' + variables + f'color-scheme:{scheme};' + ('font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;' if macos else '') + '}\n'
        if macos:
            css += '''
header { border-bottom: 1px solid var(--border); background: var(--surface); }
.artwork { border-radius: 20px; box-shadow: 0 20px 55px #00000024; }
h1 { letter-spacing: -.035em; font-weight: 700; }
.eyebrow { text-transform: none; font-weight: 600; }
.controls .primary { background: var(--accent); color: #fff; box-shadow: 0 4px 14px #00000018; }
.connect { background: var(--accent); color: #fff; border-radius: 12px; }
progress, progress::-webkit-progress-bar { border-radius: 8px; }
'''
        radius = settings.get('artwork_radius', '').strip()
        if radius.isascii() and radius.isdigit() and 0 <= int(radius) <= 48:
            css += f'.artwork{{border-radius:{int(radius)}px;}}'
        return Response(css, mimetype='text/css', headers={'Cache-Control': 'no-store'})
