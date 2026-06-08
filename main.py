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


def _check_single_instance() -> None:
    if sys.platform != 'win32':
        return
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, 'ImFineSingleInstanceMutex_v1')
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("I'm fine", "I'm fineはすでに起動しています。")
        root.destroy()
        sys.exit(0)


from ui import App


def main() -> None:
    _set_dpi_aware()
    _check_single_instance()
    app = App()
    app.mainloop()


if __name__ == '__main__':
    main()
