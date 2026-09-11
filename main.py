import sys
import time


def _parse_after_update_pid(argv: list) -> int | None:
    """コマンドライン引数から --after-update に続く旧プロセスのPIDを読み取る。
    存在しない/値が無い/数値でない、いずれの場合も None を返す (落とさない)。
    """
    try:
        idx = argv.index(updater.AFTER_UPDATE_ARG)
    except ValueError:
        return None
    if idx + 1 >= len(argv):
        return None
    try:
        return int(argv[idx + 1])
    except (TypeError, ValueError):
        return None


def _wait_for_previous_process_exit(pid: int, timeout_sec: float) -> None:
    """更新直後、渡された PID のプロセスが終了するのを最大 timeout_sec 秒待つ。

    旧プロセスの終了を待たずに次へ進むと、ミューテックスやウィンドウの
    状態がまだ旧プロセス側にあるうちに新プロセスが動き出し
    「更新したらアプリが消える」ように見える (詳細は updater.py 参照)。
    例外はすべて握りつぶし、待てなくても先へ進む
    (起動できないままになるよりはマシなため)。
    """
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            # 既に終了しているとみなし、待たずに進む
            updater._log(f'更新直後の起動: 旧プロセス(PID={pid})は既に終了していた')
            return
        try:
            timeout_ms = max(0, int(timeout_sec * 1000))
            WAIT_TIMEOUT = 0x00000102
            result = kernel32.WaitForSingleObject(handle, timeout_ms)
            if result == WAIT_TIMEOUT:
                updater._log(
                    f'更新直後の起動: 旧プロセス(PID={pid})が'
                    f'{timeout_sec}秒待っても終わらないため、待たずに続行する')
            else:
                updater._log(f'更新直後の起動: 旧プロセス(PID={pid})の終了を確認した')
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass


def _set_dpi_aware() -> None:
    if sys.platform != 'win32':
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ミューテックスのハンドルはプロセス終了まで保持しておく必要があるため、
# モジュールレベルの変数に保持する (GC対策というよりコードの意図を明確にするため)。
_mutex_handle = None


def _try_create_mutex(kernel32, ctypes):
    """ミューテックスの取得を1回だけ試みる。
    (handle, already_exists) を返す。handle は取得できなければ 0/None。
    """
    handle = kernel32.CreateMutexW(None, False, 'ImFineSingleInstanceMutex_v1')
    already_exists = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    return handle, already_exists


def _check_single_instance(after_update: bool = False) -> None:
    """多重起動をミューテックスで防ぐ。

    通常起動 (after_update=False) では、既に他インスタンスが起動していれば
    即座に案内を出して終了する (従来通り)。

    更新直後 (after_update=True) は、旧プロセスがまだミューテックスを
    保持したまま終了処理中の可能性があるため、最大 AFTER_UPDATE_WAIT_SEC 秒
    リトライしてから判定する (参考実装 VoiceDock の SingleInstanceGuard.TryAcquire
    と同じ考え方)。

    重要: CreateMutexW は同名のミューテックスが既にあってもハンドル自体は
    返す (ERROR_ALREADY_EXISTS が設定されるだけ)。リトライの際は、取得した
    ハンドルを CloseHandle で閉じてから再度 CreateMutexW を呼ばないと、
    自分が持っているハンドルのせいでいつまでも解放されない。
    """
    global _mutex_handle
    if sys.platform != 'win32':
        return
    import ctypes
    # ctypes は内部で他の Win32 API を呼ぶことがあり、素朴に
    # GetLastError() を呼ぶとエラーコードが上書きされうる。
    # use_last_error=True で ctypes 自身にエラーコードを保持させ、
    # ctypes.get_last_error() で取り出すのが正しい作法。
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    handle, already_exists = _try_create_mutex(kernel32, ctypes)

    if already_exists and after_update:
        deadline = time.monotonic() + updater.AFTER_UPDATE_WAIT_SEC
        while already_exists and time.monotonic() < deadline:
            try:
                if handle:
                    kernel32.CloseHandle(handle)
            except Exception:
                pass
            time.sleep(0.2)
            handle, already_exists = _try_create_mutex(kernel32, ctypes)
        if already_exists:
            updater._log('更新直後の起動: ミューテックス取得を待ったが取得できなかった')
        else:
            updater._log('更新直後の起動: 旧プロセスの終了を待ってミューテックスを取得できた')

    _mutex_handle = handle

    if already_exists:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("I'm fine", "I'm fineはすでに起動しています。")
        root.destroy()
        sys.exit(0)


from ui import App
import updater


def main() -> None:
    _set_dpi_aware()
    pid = _parse_after_update_pid(sys.argv[1:])
    after_update = pid is not None
    if after_update:
        _wait_for_previous_process_exit(pid, updater.PREV_PROCESS_WAIT_SEC)
    _check_single_instance(after_update=after_update)
    updater.recover_or_cleanup()
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
