"""二重起動したとき、すでに動いている I'm fine のウィンドウを前に出すための仕組み。

名前付きイベントを使う。2つ目に起動されたプロセスはイベントを立てて
黙って終了し、すでに動いている側はメインスレッドの定期処理でイベントを
見つけてウィンドウを表示する。Windows 以外では何もしない。
"""
import sys

EVENT_NAME = 'ImFineShowWindowEvent_v1'
ASFW_ANY = 0xFFFFFFFF  # AllowSetForegroundWindow の「どのプロセスでも」
WAIT_OBJECT_0 = 0


def _kernel32():
    import ctypes
    import ctypes.wintypes as wt
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    k.CreateEventW.restype = wt.HANDLE
    k.SetEvent.argtypes = [wt.HANDLE]
    k.ResetEvent.argtypes = [wt.HANDLE]
    k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k.WaitForSingleObject.restype = wt.DWORD
    k.CloseHandle.argtypes = [wt.HANDLE]
    return k


def open_event():
    """名前付きイベント (自動リセット) を作るか開く。失敗・Windows 以外なら None。

    すでに動いている側はハンドルを終了まで持ち続ける。
    """
    if sys.platform != 'win32':
        return None
    try:
        handle = _kernel32().CreateEventW(None, False, False, EVENT_NAME)
        return handle or None
    except Exception:
        return None


def reset(handle) -> None:
    """起動した時点で立っていた古い合図を捨てる。"""
    if not handle or sys.platform != 'win32':
        return
    try:
        _kernel32().ResetEvent(handle)
    except Exception:
        pass


def signal_existing(handle) -> bool:
    """すでに動いている側へ「ウィンドウを出して」と伝える。伝えられたら True。"""
    if not handle or sys.platform != 'win32':
        return False
    try:
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        user32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
        # 前面に出す権限はユーザーが起動したこのプロセスが持っている。
        # すでに動いている側が SetForegroundWindow できるよう譲る。
        user32.AllowSetForegroundWindow(ASFW_ANY)
        return bool(_kernel32().SetEvent(handle))
    except Exception:
        return False


def poll(handle) -> bool:
    """合図が来ていれば True (自動リセットなので1回だけ True になる)。待たない。"""
    if not handle or sys.platform != 'win32':
        return False
    try:
        return _kernel32().WaitForSingleObject(handle, 0) == WAIT_OBJECT_0
    except Exception:
        return False


def close(handle) -> None:
    if not handle or sys.platform != 'win32':
        return
    try:
        _kernel32().CloseHandle(handle)
    except Exception:
        pass
