import json
import os
import pathlib
import shutil
import sys
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
    'resume_in_tray': False,       # 更新再起動後にトレイ格納を復元するための内部フラグ
    'win_x': None,
    'win_y': None,
    'update_check_url': 'https://api.github.com/repos/Yu5rin/Imfine/releases/latest',
}

# save()/update() を複数スレッドから同時に呼んでも安全にするためのロック。
# update() が内部で load()+save() を行うため、同一スレッドからの再入
# (デッドロック) を避ける目的で RLock を使う。
_LOCK = threading.RLock()


# data_dir() の結果のキャッシュ。書き込み可否の判定を起動ごとに繰り返さないため。
_DATA_DIR = None


def _appdata_base() -> pathlib.Path:
    """従来の保存先の親フォルダ (Windows は %APPDATA%、それ以外は ~/.config)。"""
    if os.name == 'nt':
        return pathlib.Path(os.environ.get('APPDATA', pathlib.Path.home() / 'AppData' / 'Roaming'))
    return pathlib.Path.home() / '.config'


def _can_write_dir(d: pathlib.Path) -> bool:
    """d を作成し、実際に一時ファイルを作って消せるかで書き込み可否を判定する。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        fd, p = tempfile.mkstemp(prefix='.write-test-', dir=str(d))
        os.close(fd)
        os.remove(p)
        return True
    except OSError:
        return False


def data_dir() -> pathlib.Path:
    """設定とログの保存先フォルダを返す (無ければ作る)。

    exe と同じフォルダの data サブフォルダを使う (ポータブル形式)。
    ソース実行時はこのファイルのあるフォルダ (リポジトリ直下) の data。
    書き込めない場所 (Program Files 配下など) では従来の
    %APPDATA%\\ImFine (Windows 以外は ~/.config/ImFine) にフォールバックする。
    """
    global _DATA_DIR
    with _LOCK:
        if _DATA_DIR is not None:
            return _DATA_DIR
        if getattr(sys, 'frozen', False):
            root = pathlib.Path(os.path.dirname(sys.executable))
        else:
            root = pathlib.Path(__file__).resolve().parent
        d = root / 'data'
        if not _can_write_dir(d):
            d = _appdata_base() / 'ImFine'
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        _DATA_DIR = d
        return d


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a == b


def _get_path() -> pathlib.Path:
    d = data_dir()
    path = d / 'settings.json'
    if not path.exists():
        # 新しい保存先にまだ無ければ、従来の保存先から「コピー」する
        # (元のファイルは巻き戻しに備えて消さない)。
        base = _appdata_base()
        for old in (base / 'ImFine' / 'settings.json',
                    base / 'Mouser' / 'settings.json'):
            if _same_file(old, path) or not old.exists():
                continue
            try:
                shutil.copy2(old, path)
                break
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
                'start_in_tray', 'auto_update_enabled', 'resume_after_update',
                'resume_in_tray'):
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
