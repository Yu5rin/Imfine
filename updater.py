import datetime
import glob
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

import settings

REQUEST_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 60

# 更新直後に新プロセス側が起動する際に付与する引数と、その待機時間。
# main.py 側で解釈される (updater.py からは import して使うだけ)。
# 起動中に更新を確認する間隔 (秒)。常駐ツールで何日も起動しっぱなしになるため。
RUNTIME_CHECK_INTERVAL_SEC = 6 * 60 * 60

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


def _log(message: str) -> None:
    """update.log に1行追記する。

    ログ出力自体の失敗 (ディスクフル・権限なし・APPDATA が不正なパス等) で
    アプリを落とさないよう、あらゆる例外をここで握りつぶす。
    """
    try:
        d = str(settings.data_dir())
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

    # API の値は null のこともあるため、文字列として受ける
    tag = str(release.get('tag_name') or '')
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
        if str(asset.get('name') or '').lower().endswith('.exe'):
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
    digest = str(asset.get('digest') or '')  # GitHub が付与する 'sha256:xxxx' 形式
    if not digest.startswith('sha256:'):
        _log('ダウンロード失敗: digestが無い/形式が不正')
        return None
    expected = digest.split(':', 1)[1].lower()

    url = str(asset.get('browser_download_url') or '')
    if not _is_allowed_url(url, ALLOWED_DOWNLOAD_HOSTS):
        _log(f'ダウンロード失敗: 許可されていないホスト url={url}')
        return None

    _log(f'ダウンロード開始: url={url}')
    fd, tmp_path = tempfile.mkstemp(prefix=DOWNLOAD_PREFIX, suffix='.exe', dir=dest_dir)
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


def _restart_env() -> dict:
    """新しいプロセスに渡す環境変数。

    PyInstaller の単一 exe は、起動時に自分用の一時フォルダ (_MEIxxxx) へ展開し、
    その場所を _PYI_ARCHIVE_FILE / _PYI_APPLICATION_HOME_DIR などの環境変数で
    子プロセスへ伝える。環境変数をそのまま引き継ぐと、新しい exe のブートローダは
    「自分は子プロセスだ」とみなして展開をやり直さず、旧プロセスの一時フォルダを
    使い回す。旧プロセスが終わるとそのフォルダは消されるため、新プロセスで
    ファイルが見つからなくなる。PyInstaller 6.9 以降は、別のアプリとして
    起動し直すときに PYINSTALLER_RESET_ENVIRONMENT=1 を渡すことが必要とされている
    (公式ドキュメント「Implementing application restart」)。
    """
    return {**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'}


def _spawn_restart(current_exe: str, old_pid: int) -> bool:
    """新しい exe を直接起動する。

    以前は PowerShell の Wait-Process 経由で待たせてから起動していたが、
    親プロセス (自分) が死んだ後に外部プロセスが生き残って正しく動くことに
    依存しており壊れやすかった。参考実装 (VoiceDock/Pane) はいずれも
    Process.Start で新しい exe を直接起動し、旧プロセスの終了待ちは
    新プロセス側 (--after-update 引数) に委ねている。それに合わせる。
    """
    # DETACHED_PROCESS は Windows にしか無い (それ以外では creationflags は 0 でなければならない)
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0) if sys.platform == 'win32' else 0
    try:
        subprocess.Popen(
            [current_exe, AFTER_UPDATE_ARG, str(old_pid)],
            creationflags=flags,
            cwd=os.path.dirname(current_exe),
            close_fds=True,
            env=_restart_env(),
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


# ダウンロード途中のファイル名の形 (download_and_verify の mkstemp と合わせる)
DOWNLOAD_PREFIX = 'imfine_update_'


def recover_or_cleanup() -> None:
    """前回更新時の .old ファイルと、ダウンロード途中のファイルを削除する (起動時に呼ぶ)。

    この関数が呼ばれている時点で現在の exe は正常に起動できているため、
    .old が残っていれば前回更新の残骸として削除する。
    (「exe 自体が消えて起動できない」状態からの自動復旧はアプリ自身では
    不可能なので、apply_update 側で危険な時間帯を極小化する方針としている)
    ダウンロードの途中でアプリを終了すると、exe と同じフォルダに
    imfine_update_*.exe が残るため、これも消す。
    削除に失敗しても無視する。
    """
    if not getattr(sys, 'frozen', False):
        return
    old_path = sys.executable + '.old'
    if os.path.exists(old_path):
        _safe_remove(old_path)
        _log(f'前回更新の残骸を削除した: {old_path}')
    exe_dir = os.path.dirname(sys.executable)
    for path in glob.glob(os.path.join(glob.escape(exe_dir), DOWNLOAD_PREFIX + '*.exe')):
        _safe_remove(path)
        if not os.path.exists(path):
            _log(f'ダウンロード途中の残骸を削除した: {path}')


# 更新の確認〜ダウンロードを同時に1つしか走らせないためのロック。
# 手動の「更新を確認」を連打したり、定期確認と重なったりしても、並行して
# ダウンロード・置き換えが走らないようにする。
_RUN_LOCK = threading.Lock()


def is_running() -> bool:
    """更新の確認〜ダウンロードが実行中なら True。"""
    return _RUN_LOCK.locked()


def check_and_apply_async(current_version: str, url: str,
                          on_state=None, on_ready_to_restart=None,
                          apply: bool = True) -> bool:
    """バックグラウンドで更新確認〜適用まで行う。UI をブロックしない。

    すでに実行中なら何もせず False を返す (並行して走らせない)。
    開始したら True を返す。

    on_state は進捗を UI に伝えるためのコールバックで、
    バックグラウンドスレッドから on_state(state, info) の形で呼ばれる
    (呼び出し側で Tk 操作などを行う場合は必ずメインスレッドへ安全に伝播すること)。
    info は dict で、分かる範囲で 'latest' (最新の版のタグ) を含む。
    state は次のいずれか:
      'checking'    最新版を確認中
      'up_to_date'  最新版だった (何もしない)。info['latest'] に最新の版
      'downloading' ダウンロード中。info['latest'] に新しい版
      'ready'       ダウンロードと検証が済んだ (apply=False のときだけ)。
                    info['path'] にダウンロードしたファイル、info['latest'] に版。
                    置き換え (apply_update) は呼び出し側が行う
      'applying'    置き換え中 (apply=True のときだけ)
      'failed'      確認・ダウンロード・検証・適用のいずれかに失敗

    on_ready_to_restart は、apply=True のとき、置き換えが完了し自プロセスを
    終了してよくなった時にバックグラウンドスレッドから呼ばれる。

    設定ファイルへの書き込みはここでは一切行わない
    (メインスレッドの保存処理と競合させないため)。
    """
    if not url:
        return False
    if not _RUN_LOCK.acquire(blocking=False):
        _log('更新の確認はすでに実行中のため、今回は何もしない')
        return False

    def _notify(state: str, **info) -> None:
        if on_state is None:
            return
        try:
            on_state(state, info)
        except Exception:
            pass

    user_agent = f'ImFine/{current_version}'

    def _run():
        _notify('checking')
        _log(f'現在のバージョン: {current_version}')
        release = check_latest(url, user_agent=user_agent)
        if release is None:
            _notify('failed')
            return
        tag = str(release.get('tag_name') or '')
        if not tag:
            _log('確認失敗: tag_name が無い')
            _notify('failed')
            return
        if not _is_newer(tag, current_version):
            _log(f'最新版です (現在 {current_version}, 最新 {tag})')
            _notify('up_to_date', latest=tag)
            return
        _log(f'新しい版があります (現在 {current_version} -> {tag})')
        asset = find_exe_asset(release)
        if asset is None:
            _log('確認失敗: exeアセットが見つからない')
            _notify('failed', latest=tag)
            return

        if not getattr(sys, 'frozen', False):
            _log('確認失敗: frozen (PyInstaller exe) 実行ではないため更新をスキップ')
            _notify('failed', latest=tag)
            return
        current_dir = os.path.dirname(sys.executable)
        if not _can_write(current_dir):
            _log(f'確認失敗: 書き込み権限なし dir={current_dir}')
            _notify('failed', latest=tag)
            return

        _notify('downloading', latest=tag)
        new_path = download_and_verify(asset, current_dir, user_agent=user_agent)
        if new_path is None:
            _notify('failed', latest=tag)
            return

        if not apply:
            _notify('ready', latest=tag, path=new_path)
            return

        _notify('applying', latest=tag)
        if apply_update(new_path):
            _log('更新完了。新プロセスへ引き継ぐ')
            if on_ready_to_restart is not None:
                try:
                    on_ready_to_restart()
                except Exception:
                    pass
        else:
            _notify('failed', latest=tag)

    def _worker():
        # 想定外の例外 (API の値の型が違う、など) でスレッドが黙って死ぬと、
        # UI が「確認中」「ダウンロード中」のまま固まる。必ず failed を伝え、
        # ロックも必ず外す。
        try:
            _run()
        except Exception as e:
            _log(f'更新処理で想定外のエラー: {type(e).__name__}: {e}')
            _notify('failed')
        finally:
            _RUN_LOCK.release()

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        _RUN_LOCK.release()
        raise
    return True
