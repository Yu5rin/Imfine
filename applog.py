"""想定外の例外を data\\app.log に記録する。

Tk のコールバック・メインスレッド・ほかのスレッドのどこで起きた例外も、
ここに日時つきで書く。exe はコンソールを持たないため、記録しないと
利用者の環境で何が起きたか後から分からない。
ログの書き込み自体の失敗 (ディスクフル・権限なしなど) は握りつぶし、
アプリを落とさない。
"""
import datetime
import os
import sys
import threading
import traceback

import settings

LOG_NAME = 'app.log'
# app.log の上限サイズ。これを超えたら古い方を捨てて後ろ半分だけ残す。
LOG_MAX_BYTES = 256 * 1024

_LOCK = threading.Lock()


def log_path() -> str:
    return os.path.join(str(settings.data_dir()), LOG_NAME)


def _truncate_if_large(path: str, max_bytes: int) -> None:
    try:
        if os.path.getsize(path) > max_bytes:
            with open(path, 'rb') as f:
                f.seek(-(max_bytes // 2), os.SEEK_END)
                tail = f.read()
            # 行の途中から始まらないよう、最初の改行までを捨てる
            nl = tail.find(b'\n')
            if nl != -1:
                tail = tail[nl + 1:]
            with open(path, 'wb') as f:
                f.write(tail)
    except OSError:
        pass


def write(message: str) -> None:
    """app.log に日時つきで書く。失敗しても例外を出さない。"""
    try:
        with _LOCK:
            path = log_path()
            _truncate_if_large(path, LOG_MAX_BYTES)
            ts = datetime.datetime.now().isoformat(timespec='seconds')
            text = message.rstrip('\n')
            with open(path, 'a', encoding='utf-8') as f:
                f.write(f'[{ts}] {text}\n')
    except Exception:
        pass


def log_exception(exc_type, exc, tb, where: str = '') -> None:
    """例外とトレースバックを app.log に書く。"""
    try:
        detail = ''.join(traceback.format_exception(exc_type, exc, tb))
        head = f'想定外のエラー ({where})' if where else '想定外のエラー'
        write(f'{head}\n{detail}')
    except Exception:
        pass


def _sys_hook(exc_type, exc, tb) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log_exception(exc_type, exc, tb, 'メインスレッド')


def _thread_hook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = getattr(args.thread, 'name', '?')
    log_exception(args.exc_type, args.exc_value, args.exc_traceback, f'スレッド {name}')


def install_hooks() -> None:
    """sys.excepthook と threading.excepthook を差し替える。

    Tk のコールバック内の例外は Tk 側で捕まるため、App の
    report_callback_exception からも log_exception を呼ぶこと。
    """
    sys.excepthook = _sys_hook
    threading.excepthook = _thread_hook
