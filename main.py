import sys


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


def _check_single_instance() -> None:
    global _mutex_handle
    if sys.platform != 'win32':
        return
    import ctypes
    # ctypes は内部で他の Win32 API を呼ぶことがあり、素朴に
    # GetLastError() を呼ぶとエラーコードが上書きされうる。
    # use_last_error=True で ctypes 自身にエラーコードを保持させ、
    # ctypes.get_last_error() で取り出すのが正しい作法。
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _mutex_handle = kernel32.CreateMutexW(None, False, 'ImFineSingleInstanceMutex_v1')
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
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
    _check_single_instance()
    updater.recover_or_cleanup()
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
