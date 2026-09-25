import datetime
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

# 更新直後に新プロセス側が起動する際に付与する引数と、その待機時間。
# main.py 側で解釈される (updater.py からは import して使うだけ)。
AFTER_UPDATE_ARG = '--after-update'
AFTER_UPDATE_WAIT_SEC = 30   # 更新直後にミューテックス取得を粘る上限
PREV_PROCESS_WAIT_SEC = 15  # 旧プロセスの終了を待つ上限

# GitHub API は User-Agent の送信を要求する (無いと 403 を返されることがある)。
# ui.py から VERSION を import すると循環 import の懸念があるため、
# 呼び出し元 (check_and_apply_async) から実際のバージョンを渡してもらい、
# 直接 check_latest()/download_and_verify() を呼ぶ場合のためにデフォルト値を用意する。
DEFAULT_USER_AGENT = 'ImFine-Updater'

# update.log の上限サイズ。これを超えたら古い方を捨てて切り詰める。
LOG_MAX_BYTES = 256 * 1024


def _log_dir() -> str:
    """ログの保存先ディレクトリ。settings.py の _get_path() と同じ
    フォルダ (%APPDATA%\\ImFine もしくは ~/.config/ImFine) を指すよう、
    フォルダ決定ロジックだけを小さく複製する
    (settings.py を import しても循環はしないが、
    settings._get_path() は settings.json 用の副作用 (旧フォルダからの
    コピー) を持つ private 関数のため、ログ専用に独立させておく)。
    """
    if os.name == 'nt':
        base = os.environ.get(
            'APPDATA', os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming'))
    else:
        base = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'ImFine')


def _log(message: str) -> None:
    """update.log に1行追記する。

    ログ出力自体の失敗 (ディスクフル・権限なし・APPDATA が不正なパス等) で
    アプリを落とさないよう、あらゆる例外をここで握りつぶす。
    """
    try:
        d = _log_dir()
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, 'update.log')

        try:
            if os.path.getsize(path) > LOG_MAX_BYTES:
                with open(path, 'rb') as f:
                    f.seek(-LOG_MAX_BYTES // 2, os.SEEK_END)
                    tail = f.read()
                with open(path, 'wb') as f:
                    f.write(tail)
        except OSError:
            pass

        ts = datetime.datetime.now().isoformat(timespec='seconds')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {message}\n')
    except Exception:
        pass

# 更新確認先として許可するホスト (settings.json は同一ユーザー権限の他プロセスから
# 書き換えられうるため、任意のホストを更新元にできてしまわないよう固定する)。
# リポジトリ名の変更などで API が 301 を返しても、行き先は api.github.com のままなので
# リダイレクト先もこのホストに限る。
ALLOWED_API_HOST = 'api.github.com'
# ダウンロードURL (browser_download_url) として許可するホスト。
ALLOWED_DOWNLOAD_HOSTS = ('github.com',)
# ダウンロードのリダイレクト先として許可するホスト。
# GitHub の Release asset は github.com から配信用のホストへ 302 でリダイレクトされる。
#
# 以前はここに objects.githubusercontent.com を並べて「リダイレクトされるため許可する」と
# 書いていたが、実装は最初の URL しか確かめておらず、リダイレクトは urllib が黙って
# 辿っていた (コメントと実装がずれていた)。いまはリダイレクトのたびに
# _AllowedHostRedirectHandler で行き先を確かめる。
#
# 2026-09-25 に v1.13.2 の exe で実際に確かめたところ、行き先は
# objects.githubusercontent.com ではなく release-assets.githubusercontent.com だった。
# コメントの記述どおりに objects... だけを許可して検査を足すと、更新が必ず失敗する。
# objects.githubusercontent.com は以前の配信先で、GitHub が戻す可能性もあるため残す。
ALLOWED_DOWNLOAD_REDIRECT_HOSTS = ALLOWED_DOWNLOAD_HOSTS + (
    'release-assets.githubusercontent.com',
    'objects.githubusercontent.com',
)

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


class DisallowedRedirect(urllib.error.HTTPError):
    """許可されていない行き先へのリダイレクトを断ったことを表す。"""


class _AllowedHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """リダイレクトのたびに、行き先が https で allowed_hosts のいずれかかを確かめる。

    urllib の既定の HTTPRedirectHandler は、http / https / ftp なら行き先を
    確かめずに辿る。最初の URL だけを確かめても、リダイレクト先で別のホストへ
    誘導されれば意味がないため、行き先ごとに _is_allowed_url を通す。
    """

    def __init__(self, allowed_hosts):
        super().__init__()
        self._allowed_hosts = tuple(allowed_hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # newurl は呼び出し元 (http_error_302) で絶対 URL に直されている
        if not _is_allowed_url(newurl, self._allowed_hosts):
            raise DisallowedRedirect(
                newurl, code,
                f'redirect to a disallowed location: {newurl}', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _without_query(url: str) -> str:
    """ログに残す用。配信先の URL は署名付きのクエリを持つので、そこを落とす。"""
    try:
        return urllib.parse.urlsplit(url)._replace(query='', fragment='').geturl()
    except ValueError:
        return '(URL を読めない)'


def _open(url: str, headers: dict, timeout: float, redirect_hosts):
    """url を開く。リダイレクト先は redirect_hosts に限る。

    最初の url が許可されたものかどうかは呼び出し側で確かめておくこと。
    """
    opener = urllib.request.build_opener(_AllowedHostRedirectHandler(redirect_hosts))
    req = urllib.request.Request(url, headers=headers)
    return opener.open(req, timeout=timeout)


def check_latest(url: str, user_agent: str = DEFAULT_USER_AGENT) -> dict | None:
    """最新リリース情報を取得する。失敗時は None (起動をブロックしない)。
    URL のホストが api.github.com でない場合は何もせず None を返す。
    draft / prerelease のリリースは更新対象にしないため None を返す。
    """
    _log(f'確認開始: url={url}')
    if not _is_allowed_url(url, (ALLOWED_API_HOST,)):
        _log(f'確認失敗: 許可されていないホスト url={url}')
        return None

    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': user_agent,
    }
    try:
        with _open(url, headers, REQUEST_TIMEOUT, (ALLOWED_API_HOST,)) as resp:
            release = json.loads(resp.read().decode('utf-8'))
    except DisallowedRedirect as e:
        _log(f'確認失敗: 許可されていないリダイレクト先 url={_without_query(e.filename)}')
        return None
    except urllib.error.HTTPError as e:
        _log(f'確認失敗: HTTPエラー status={e.code}')
        return None
    except (urllib.error.URLError, OSError, ValueError) as e:
        _log(f'確認失敗: {type(e).__name__}: {e}')
        return None

    if not isinstance(release, dict):
        _log('確認失敗: レスポンスがオブジェクトではない')
        return None

    tag = release.get('tag_name', '')
    _log(f'取得したtag_name: {tag}')

    if release.get('draft'):
        _log('確認結果: draftリリースのため対象外とする')
        return None
    if release.get('prerelease'):
        _log('確認結果: prereleaseリリースのため対象外とする')
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


def download_and_verify(asset: dict, dest_dir: str,
                        user_agent: str = DEFAULT_USER_AGENT) -> str | None:
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
        _log('ダウンロード失敗: digestが無い/形式が不正')
        return None
    expected = digest.split(':', 1)[1].lower()

    url = asset.get('browser_download_url', '')
    if not _is_allowed_url(url, ALLOWED_DOWNLOAD_HOSTS):
        _log(f'ダウンロード失敗: 許可されていないホスト url={url}')
        return None

    _log(f'ダウンロード開始: url={url}')
    fd, tmp_path = tempfile.mkstemp(prefix='imfine_update_', suffix='.exe', dir=dest_dir)
    os.close(fd)
    try:
        headers = {
            'Accept': 'application/octet-stream',
            'User-Agent': user_agent,
        }
        with _open(url, headers, DOWNLOAD_TIMEOUT, ALLOWED_DOWNLOAD_REDIRECT_HOSTS) as resp, \
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
    except DisallowedRedirect as e:
        _log(f'ダウンロード失敗: 許可されていないリダイレクト先 url={_without_query(e.filename)}')
        _safe_remove(tmp_path)
        return None
    except urllib.error.HTTPError as e:
        _log(f'ダウンロード失敗: HTTPエラー status={e.code}')
        _safe_remove(tmp_path)
        return None
    except (urllib.error.URLError, OSError) as e:
        _log(f'ダウンロード失敗: {type(e).__name__}: {e}')
        _safe_remove(tmp_path)
        return None

    _log(f'ダウンロード完了: {total} バイト')

    actual = _sha256_of(tmp_path)
    if actual is None:
        _log('検証失敗: ダウンロードしたファイルの読み込みに失敗')
        return None
    if actual.lower() != expected:
        _log(f'検証失敗: SHA256不一致 expected={expected} actual={actual}')
        _safe_remove(tmp_path)
        return None

    _log('検証成功: SHA256が一致')
    return tmp_path


def _spawn_restart(current_exe: str, old_pid: int) -> bool:
    """新しい exe を直接起動する。

    以前は PowerShell の Wait-Process 経由で待たせてから起動していたが、
    親プロセス (自分) が死んだ後に外部プロセスが生き残って正しく動くことに
    依存しており壊れやすかった。参考実装 (VoiceDock/Pane) はいずれも
    Process.Start で新しい exe を直接起動し、旧プロセスの終了待ちは
    新プロセス側 (--after-update 引数) に委ねている。それに合わせる。
    """
    try:
        subprocess.Popen(
            [current_exe, AFTER_UPDATE_ARG, str(old_pid)],
            creationflags=subprocess.DETACHED_PROCESS,
            cwd=os.path.dirname(current_exe),
            close_fds=True,
        )
        _log(f'新プロセスの起動: {current_exe} {AFTER_UPDATE_ARG} {old_pid}')
        return True
    except OSError as e:
        _log(f'新プロセスの起動に失敗: {type(e).__name__}: {e}')
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
        _log('適用失敗: frozen (PyInstaller exe) 実行ではない')
        _safe_remove(new_exe_path)
        return False

    current_exe = sys.executable
    current_dir = os.path.dirname(current_exe)

    if not _can_write(current_dir):
        _log(f'適用失敗: 書き込み権限なし dir={current_dir}')
        _safe_remove(new_exe_path)
        return False

    old_path = current_exe + '.old'
    _safe_remove(old_path)

    try:
        os.rename(current_exe, old_path)
    except OSError as e:
        _log(f'適用失敗: .oldへのリネームに失敗 {type(e).__name__}: {e}')
        _safe_remove(new_exe_path)
        return False
    _log(f'適用: .oldへのリネーム完了 ({old_path})')

    try:
        os.replace(new_exe_path, current_exe)
    except OSError as e:
        _log(f'適用失敗: 新exeの配置に失敗 {type(e).__name__}: {e}')
        try:
            os.rename(old_path, current_exe)  # ロールバック
        except OSError:
            pass
        _safe_remove(new_exe_path)  # replace が部分的に失敗しても残骸を残さない
        return False
    _log('適用: 新exeの配置完了')

    if not _spawn_restart(current_exe, os.getpid()):
        _log('適用失敗: 新プロセスの起動に失敗したためロールバックする')
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
    old_path = sys.executable + '.old'
    if os.path.exists(old_path):
        _safe_remove(old_path)
        _log(f'前回更新の残骸を削除した: {old_path}')


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

    user_agent = f'ImFine/{current_version}'

    def _worker():
        _notify('checking')
        _log(f'現在のバージョン: {current_version}')
        release = check_latest(url, user_agent=user_agent)
        if release is None:
            _notify('failed')
            return
        tag = release.get('tag_name', '')
        if not _is_newer(tag, current_version):
            _log(f'最新版です (現在 {current_version}, 最新 {tag})')
            _notify('up_to_date')
            return
        _log(f'新しい版があります (現在 {current_version} -> {tag})')
        asset = find_exe_asset(release)
        if asset is None:
            _log('確認失敗: exeアセットが見つからない')
            _notify('failed')
            return

        if not getattr(sys, 'frozen', False):
            _log('確認失敗: frozen (PyInstaller exe) 実行ではないため更新をスキップ')
            _notify('failed')
            return
        current_dir = os.path.dirname(sys.executable)
        if not _can_write(current_dir):
            _log(f'確認失敗: 書き込み権限なし dir={current_dir}')
            _notify('failed')
            return

        _notify('downloading')
        new_path = download_and_verify(asset, current_dir, user_agent=user_agent)
        if new_path is None:
            _notify('failed')
            return

        _notify('applying')
        if apply_update(new_path):
            _log('更新完了。新プロセスへ引き継ぐ')
            if on_ready_to_restart is not None:
                try:
                    on_ready_to_restart()
                except Exception:
                    pass
        else:
            _notify('failed')

    threading.Thread(target=_worker, daemon=True).start()
