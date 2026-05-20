import json
import os
import pathlib

DEFAULTS: dict = {
    'x1': 100,
    'y1': 300,
    'x2': 900,
    'y2': 300,
    'interval': 60.0,
    'duration': 0.5,
    'theme': 'light',
    'stop_timer_enabled': False,
    'stop_hour': 17,
    'stop_min': 0,
    'tray_minimize': True,
    'move_mode': 'ab',
    'wiggle_px': 5,
}


def _get_path() -> pathlib.Path:
    if os.name == 'nt':
        base = pathlib.Path(os.environ.get('APPDATA', pathlib.Path.home() / 'AppData' / 'Roaming'))
    else:
        base = pathlib.Path.home() / '.config'
    d = base / 'Mouser'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'settings.json'


def load() -> dict:
    try:
        with open(_get_path(), encoding='utf-8') as f:
            return {**DEFAULTS, **json.load(f)}
    except Exception:
        return dict(DEFAULTS)


def save(data: dict) -> None:
    with open(_get_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
