import json
import os
import pathlib
import shutil
import tempfile
import threading

DEFAULTS: dict = {
    'theme': 'light',
    'stop_timer_enabled': False,
    'stop_hour': 17,
    'stop_min': 0,
    'tray_minimize': True,
    'auto_on': False,
    'start_in_tray': False,        # 起動時に直接トレイへ格納する
    'auto_update_enabled': True,   # 自動アップデートの有効/無効
    'resume_after_update': False,  # 更新再起動後に ON を復元するための内部フラグ
    'win_x': None,
    'win_y': None,
    'update_check_url': 'https://api.github.com/repos/Yu5rin/Imfine/releases/latest',
}

# save()/update() を複数スレッドから同時に呼んでも安全にするためのロック。
# update() が内部で load()+save() を行うため、同一スレッドからの再入
# (デッドロック) を避ける目的で RLock を使う。
_LOCK = threading.RLock()


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


def _to_bool(v) -> bool:
    return bool(v)


def _to_int_or(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def _validate(data: dict) -> dict:
    """読み込んだ設定の型・範囲を検証し、不正な値はデフォルトへ差し戻す。
    未知のキーはそのまま保持する (手動編集や将来の拡張を壊さないため)。
    """
    out = dict(data)

    if out.get('theme') not in ('light', 'dark'):
        out['theme'] = DEFAULTS['theme']

    for key in ('stop_timer_enabled', 'tray_minimize', 'auto_on',
                'start_in_tray', 'auto_update_enabled', 'resume_after_update'):
        out[key] = _to_bool(out.get(key, DEFAULTS[key]))

    out['stop_hour'] = _clamp(_to_int_or(out.get('stop_hour'), DEFAULTS['stop_hour']), 0, 23)
    out['stop_min'] = _clamp(_to_int_or(out.get('stop_min'), DEFAULTS['stop_min']), 0, 59)

    out['win_x'] = _to_int_or_none(out.get('win_x'))
    out['win_y'] = _to_int_or_none(out.get('win_y'))

    url = out.get('update_check_url')
    if not isinstance(url, str) or not url.startswith('https://api.github.com/'):
        out['update_check_url'] = DEFAULTS['update_check_url']

    return out


def load() -> dict:
    try:
        with open(_get_path(), encoding='utf-8') as f:
            data = {**DEFAULTS, **json.load(f)}
    except Exception:
        data = dict(DEFAULTS)
    return _validate(data)


def save(data: dict) -> None:
    """設定全体をアトミックに書き込む。

    同じディレクトリに一時ファイルを作成し os.replace() で置き換えることで、
    書き込み途中の電源断・クラッシュでも既存の設定ファイルが壊れないように
    している。GUIアプリのため書き込み失敗 (OSError) は静かに無視する
    (呼び出し元やユーザーに例外を見せてアプリを落とさないため)。
    """
    path = _get_path()
    with _LOCK:
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                prefix='.settings-', suffix='.tmp', dir=str(path.parent))
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
            tmp_path = None
        except OSError:
            pass
        finally:
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def update(**kwargs) -> dict:
    """現在の設定を読み込み、指定されたキーだけ更新して保存する。
    他のキーを消さずに済むため、部分的な更新にはこちらを使う。
    更新後の設定全体を返す。
    """
    with _LOCK:
        cfg = load()
        cfg.update(kwargs)
        save(cfg)
        return cfg
