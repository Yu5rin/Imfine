import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

REQUEST_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 60

# 更新確認先として許可するホスト (settings.json は同一ユーザー権限の他プロセスから
# 書き換えられうるため、任意のホストを更新元にできてしまわないよう固定する)
ALLOWED_API_HOST = 'api.github.com'
# ダウンロードURL (browser_download_url) として許可するホスト。
# GitHub の Release asset は github.com から objects.githubusercontent.com へ
# リダイレクトされるため、両方を許可する。
ALLOWED_DOWNLOAD_HOSTS = ('github.com', 'objects.githubusercontent.com')

# ダウンロードサイズの上限。フィードが汚染された場合にディスクを
# 埋め尽くされないようにするための安全弁。
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


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


def _is_allowed_url(url: str, allowed_hosts) -> bool:
    """スキームが https で、ホスト名が allowed_hosts のいずれかに
    完全一致する場合のみ True を返す。
    'evil-api.github.com.attacker.com' のような部分一致は通さない。
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != 'https':
        return False
    return parsed.hostname in allowed_hosts


def check_latest(url: str) -> dict | None:
    """最新リリース情報を取得する。失敗時は None (起動をブロックしない)。
    URL のホストが api.github.com でない場合は何もせず None を返す。
    """
    if not _is_allowed_url(url, (ALLOWED_API_HOST,)):
        return None

    req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            release = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return None

    if not isinstance(release, dict):
        return None
    return release


def find_exe_asset(release: dict) -> dict | None:
    assets = release.get('assets')
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get('name', '').lower().endswith('.exe'):
            return asset
    return None


def _sha256_of(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        _safe_remove(path)
        return None


def download_and_verify(asset: dict, dest_dir: str) -> str | None:
    """asset を dest_dir 内にダウンロードし SHA256 で検証する。
    digest が無い/一致しない、ダウンロードURLが許可されたホストでない、
    サイズが上限を超える、などの場合は None を返し、更新を諦める
    (未検証のファイルで実行中の exe を置き換えることは絶対に行わない)。

    dest_dir は最終的に置き換え先となる exe と同じディレクトリを渡すこと。
    同一ボリュームにダウンロードしておくことで、最後の置き換えを
    os.replace() (同一ボリューム内で高速かつアトミック) で行える。
    """
    digest = asset.get('digest', '')  # GitHub が付与する 'sha256:xxxx' 形式
    if not digest.startswith('sha256:'):
        return None
    expected = digest.split(':', 1)[1].lower()

    url = asset.get('browser_download_url', '')
    if not _is_allowed_url(url, ALLOWED_DOWNLOAD_HOSTS):
        return None

    fd, tmp_path = tempfile.mkstemp(prefix='imfine_update_', suffix='.exe', dir=dest_dir)
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/octet-stream'})
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp, \
                open(tmp_path, 'wb') as out:
            total = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise OSError('download exceeds size limit')
                out.write(chunk)
    except (urllib.error.URLError, OSError):
        _safe_remove(tmp_path)
        return None

    actual = _sha256_of(tmp_path)
    if actual is None:
        return None
    if actual.lower() != expected:
        _safe_remove(tmp_path)
        return None

    return tmp_path


def _spawn_restart(current_exe: str, old_pid: int) -> bool:
    """自プロセスの終了を待ってから新しい exe を起動する別プロセスを仕込む。

    PowerShell の Wait-Process で旧プロセスの終了を実際に待つため、
    固定の待ち時間 (旧: 2秒) に依存しない。単一引用符文字列を使うことで
    環境変数展開による '%' パス破損 (例 C:\\100%done\\) も回避する。
    PowerShell の起動に失敗した場合は、従来の cmd 方式にフォールバックする。
    """
    def _q(path: str) -> str:
        # PowerShell の単一引用符文字列内でのエスケープは '' に二重化する
        return path.replace("'", "''")

    ps_cmd = (
        f"Wait-Process -Id {old_pid} -Timeout 30 -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath '{_q(current_exe)}'"
    )
    try:
        subprocess.Popen(
            ['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
             '-Command', ps_cmd],
            creationflags=subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        return True
    except OSError:
        pass

    try:
        subprocess.Popen(
            ['cmd', '/c', f'ping 127.0.0.1 -n 3 >nul & start "" "{current_exe}"'],
            creationflags=subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def apply_update(new_exe_path: str) -> bool:
    """自分自身の exe を新しいものに差し替える (rename トリック)。

    実行中の exe は上書きできないため、いったん .old にリネームしてから
    新しいファイルを配置する。成功後、遅延起動する別プロセスを仕込んで
    True を返す (呼び出し側が自プロセスを終了させて初めて更新が反映される)。
    途中で失敗した場合は必ず元の状態にロールバックする。

    new_exe_path は current_exe と同じディレクトリにあることを前提とする
    (download_and_verify に dest_dir として current_dir を渡しておくこと)。
    同一ボリューム内であれば os.replace() は高速かつアトミックなので、
    「exe が存在しない」危険な時間帯を最小化できる。
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
        os.replace(new_exe_path, current_exe)
    except OSError:
        try:
            os.rename(old_path, current_exe)  # ロールバック
        except OSError:
            pass
        _safe_remove(new_exe_path)  # replace が部分的に失敗しても残骸を残さない
        return False

    if not _spawn_restart(current_exe, os.getpid()):
        try:
            os.rename(current_exe, new_exe_path)  # 新しい exe をいったん退避
            os.rename(old_path, current_exe)      # ロールバック
        except OSError:
            pass
        else:
            _safe_remove(new_exe_path)  # 退避させた新しい exe の残骸を削除
        return False

    return True


def recover_or_cleanup() -> None:
    """前回更新時の .old ファイルを削除する (次回起動時に呼ぶ)。

    この関数が呼ばれている時点で現在の exe は正常に起動できているため、
    .old が残っていれば前回更新の残骸として削除する。
    (「exe 自体が消えて起動できない」状態からの自動復旧はアプリ自身では
    不可能なので、apply_update 側で危険な時間帯を極小化する方針としている)
    削除に失敗しても無視する。
    """
    if not getattr(sys, 'frozen', False):
        return
    _safe_remove(sys.executable + '.old')


def check_and_apply_async(current_version: str, url: str,
                          on_state=None, on_ready_to_restart=None) -> None:
    """バックグラウンドで更新確認〜適用まで行う。UI をブロックしない。
    起動するたびに毎回チェックする。

    on_state は進捗を UI に伝えるためのコールバックで、
    バックグラウンドスレッドから呼ばれる (呼び出し側で Tk 操作などを
    行う場合は必ずメインスレッドへ安全に伝播すること)。
    渡される値は次のいずれか:
      'checking'    最新版を確認中
      'downloading' ダウンロード中
      'applying'    置き換え中
      'up_to_date'  最新版だった (何もしない)
      'failed'      確認・ダウンロード・検証・適用のいずれかに失敗

    on_ready_to_restart は、置き換えが完了し自プロセスを終了してよく
    なった時にバックグラウンドスレッドから呼ばれる (呼び出し側で
    メインスレッドへ安全に伝播すること)。

    設定ファイルへの書き込みはここでは一切行わない
    (メインスレッドの保存処理と競合させないため)。
    """
    if not url:
        return

    def _notify(state: str) -> None:
        if on_state is None:
            return
        try:
            on_state(state)
        except Exception:
            pass

    def _worker():
        _notify('checking')
        release = check_latest(url)
        if release is None:
            _notify('failed')
            return
        tag = release.get('tag_name', '')
        if not _is_newer(tag, current_version):
            _notify('up_to_date')
            return
        asset = find_exe_asset(release)
        if asset is None:
            _notify('failed')
            return

        if not getattr(sys, 'frozen', False):
            _notify('failed')
            return
        current_dir = os.path.dirname(sys.executable)
        if not _can_write(current_dir):
            _notify('failed')
            return

        _notify('downloading')
        new_path = download_and_verify(asset, current_dir)
        if new_path is None:
            _notify('failed')
            return

        _notify('applying')
        if apply_update(new_path):
            if on_ready_to_restart is not None:
                try:
                    on_ready_to_restart()
                except Exception:
                    pass
        else:
            _notify('failed')

    threading.Thread(target=_worker, daemon=True).start()
