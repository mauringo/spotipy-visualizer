"""Rate tuning and non-destructive upgrades of existing Spotify configuration."""
import configparser
from pathlib import Path
import re

# Defaults are local safety settings, not published Spotify quotas.
OPTIONS = {
    'playback_poll_seconds': (15, 5, 3600, 'Seconds between playback reads while playing (5-3600).'),
    'idle_poll_seconds': (60, 5, 3600, 'Seconds between playback reads while paused or idle (5-3600).'),
    'liked_cache_seconds': (600, 30, 86400, 'Cache each track liked status for this many seconds (30-86400).'),
    'max_requests_per_30_seconds': (8, 2, 100, 'Local Web API budget shared by all displays and controls (2-100). Not a Spotify quota.'),
    'control_interval_seconds': (2, 1, 60, 'Minimum seconds between control commands (1-60); rejected commands are not queued.'),
    'retry_after_fallback_seconds': (60, 30, 86400, 'Initial cooldown if a 429 has no valid Retry-After (30-86400); repeated 429s increase it.'),
    'retry_after_buffer_seconds': (2, 1, 60, 'Extra seconds after Spotify Retry-After before trying again (1-60).'),
}
LIMIT_NOTE = '''# Spotify uses an app-wide rolling 30-second window; the allowance varies by quota mode.
# No fixed public request count guarantees freedom from 429s; endpoints may have extra limits.
# Other apps using the same client ID also consume its allowance.
# https://developer.spotify.com/documentation/web-api/concepts/rate-limits
# Increase polling/cache intervals or lower the local budget if limits recur.
# Spotify Retry-After is always honored, even when longer than configured defaults.
'''


def read_config(path):
    config = configparser.ConfigParser(interpolation=None)
    config.read(path)
    return config


def tuning(path):
    try:
        config = read_config(path)
    except (configparser.Error, OSError, UnicodeError):
        config = configparser.ConfigParser(interpolation=None)
    values = {}
    for key, (default, minimum, maximum, _) in OPTIONS.items():
        try:
            value = config.getint('rate_limit', key, fallback=default)
            values[key] = value if minimum <= value <= maximum else default
        except ValueError:
            values[key] = default
    return values


def upgraded_config(path):
    """Return updated text or None; preserve values, comments and other sections."""
    try:
        config = read_config(path)
        original = Path(path).read_text()
    except (configparser.Error, OSError, UnicodeError):
        return None  # Do not rewrite a malformed configuration.
    missing = [key for key in OPTIONS if not config.has_option('rate_limit', key)]
    if not missing:
        return None
    addition = '\n' + LIMIT_NOTE + ''.join(
        f'# {OPTIONS[key][3]}\n{key} = {OPTIONS[key][0]}\n' for key in missing)
    if not config.has_section('rate_limit'):
        return original.rstrip('\n') + '\n\n[rate_limit]\n' + addition
    sections = list(re.finditer(r'^\s*\[([^\]\n]+)\][^\n]*(?:\n|$)', original, re.MULTILINE))
    for index, section in enumerate(sections):
        if section.group(1) == 'rate_limit':
            end = sections[index + 1].start() if index + 1 < len(sections) else len(original)
            return original[:end].rstrip('\n') + '\n' + addition + '\n' + original[end:]
    return None
