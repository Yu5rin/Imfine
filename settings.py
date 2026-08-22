import json
import os
import pathlib
import shutil

DEFAULTS: dict = {
    'theme': 'light',
    'stop_timer_enabled': False,
    'stop_hour': 17,
    'stop_min': 0,
    'tray_minimize': True,
    'auto_on': False,
    'win_x': None,
    'win_y': None,
    'update_check_url': 'https://api.github.com/repos/Yu5rin/Imfine/releases/latest',
    'last_update_check': 0,
}


def _get_path() -> pathlib.Path:
    if os.name == 'nt':
        base = pathlib.Path(os.environ.get('APPDATA', pathlib.Path.home() / 'AppData' / 'Roaming'))
    else:
        base = pathlib.Path.home() / '.config'
    d = base / 'ImFine'
    path = d / 'settings.json'
    d.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        old = base / 'Mouser' / 'settings.json'
        if old.exists():
            try:
                shutil.copy2(old, path)
            except OSError:
                pass
    return path


def load() -> dict:
    try:
        with open(_get_path(), encoding='utf-8') as f:
            return {**DEFAULTS, **json.load(f)}
    except Exception:
        return dict(DEFAULTS)


def save(data: dict) -> None:
    with open(_get_path(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
