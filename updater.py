import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

REQUEST_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 60


def _parse_version(v: str) -> tuple:
    v = v.lstrip('vV')
    parts = []
    for p in v.split('.'):
        digits = ''.join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _is_newer(remote: str, local: str) -> bool:
    # 文字列比較だと "1.0.10" < "1.0.9" のように誤判定するため、数値のタプルで比較する
    return _parse_version(remote) > _parse_version(local)


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _can_write(directory: str) -> bool:
    try:
        fd, p = tempfile.mkstemp(dir=directory)
        os.close(fd)
        os.remove(p)
        return True
    except OSError:
        return False


def check_latest(url: str) -> dict | None:
    """最新リリース情報を取得する。失敗時は None (起動をブロックしない)。"""
    req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def find_exe_asset(release: dict) -> dict | None:
    for asset in release.get('assets', []):
        if asset.get('name', '').lower().endswith('.exe'):
            return asset
    return None


def _sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def download_and_verify(asset: dict) -> str | None:
    """asset をダウンロードし SHA256 で検証する。
    digest が無い/一致しない場合は None を返し、更新を諦める
    (未検証のファイルで実行中の exe を置き換えることは絶対に行わない)。
    """
    digest = asset.get('digest', '')  # GitHub が付与する 'sha256:xxxx' 形式
    if not digest.startswith('sha256:'):
        return None
    expected = digest.split(':', 1)[1].lower()

    url = asset.get('browser_download_url', '')
    if not url.startswith('https://'):
        return None

    fd, tmp_path = tempfile.mkstemp(prefix='imfine_update_', suffix='.exe')
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/octet-stream'})
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, \
                open(tmp_path, 'wb') as out:
            shutil.copyfileobj(resp, out)
    except (urllib.error.URLError, OSError):
        _safe_remove(tmp_path)
        return None

    if _sha256_of(tmp_path).lower() != expected:
        _safe_remove(tmp_path)
        return None

    return tmp_path


def apply_update(new_exe_path: str) -> bool:
    """自分自身の exe を新しいものに差し替える (rename トリック)。

    実行中の exe は上書きできないため、いったん .old にリネームしてから
    新しいファイルを配置する。成功後、遅延起動する別プロセスを仕込んで
    True を返す (呼び出し側が自プロセスを終了させて初めて更新が反映される)。
    途中で失敗した場合は必ず元の状態にロールバックする。
    """
    if not getattr(sys, 'frozen', False):
        _safe_remove(new_exe_path)
        return False

    current_exe = sys.executable
    current_dir = os.path.dirname(current_exe)

    if not _can_write(current_dir):
        _safe_remove(new_exe_path)
        return False

    old_path = current_exe + '.old'
    _safe_remove(old_path)

    try:
        os.rename(current_exe, old_path)
    except OSError:
        _safe_remove(new_exe_path)
        return False

    try:
        shutil.move(new_exe_path, current_exe)
    except OSError:
        try:
            os.rename(old_path, current_exe)  # ロールバック
        except OSError:
            pass
        return False

    try:
        # 自プロセスが終了してミューテックスを解放するのを待ってから
        # 新しい exe を起動する別プロセスを、自分からは独立させて仕込む
        subprocess.Popen(
            ['cmd', '/c', f'ping 127.0.0.1 -n 3 >nul & start "" "{current_exe}"'],
            creationflags=subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except OSError:
        try:
            os.rename(current_exe, new_exe_path)
            os.rename(old_path, current_exe)
        except OSError:
            pass
        return False

    return True


def cleanup_old() -> None:
    """前回更新時の .old ファイルを削除する (次回起動時に呼ぶ)。"""
    if not getattr(sys, 'frozen', False):
        return
    _safe_remove(sys.executable + '.old')


def check_and_apply_async(current_version: str, url: str, cfg: dict,
                          save_cfg, on_ready_to_restart) -> None:
    """バックグラウンドで更新確認〜適用まで行う。UI をブロックしない。
    起動するたびに毎回チェックする。

    on_ready_to_restart は、置き換えが完了し自プロセスを終了してよく
    なった時にバックグラウンドスレッドから呼ばれる (呼び出し側で
    メインスレッドへ安全に伝播すること)。
    """
    if not url:
        return

    def _worker():
        cfg['last_update_check'] = time.time()
        try:
            save_cfg(cfg)
        except Exception:
            pass

        release = check_latest(url)
        if release is None:
            return
        tag = release.get('tag_name', '')
        if not _is_newer(tag, current_version):
            return
        asset = find_exe_asset(release)
        if asset is None:
            return
        new_path = download_and_verify(asset)
        if new_path is None:
            return
        if apply_update(new_path):
            on_ready_to_restart()

    threading.Thread(target=_worker, daemon=True).start()
