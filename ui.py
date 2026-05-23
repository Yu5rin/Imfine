import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import settings
from controller import Controller


VERSION = '1.7.0'

THEMES: dict = {
    'light': {
        'BG':       '#F5F5F5',
        'TEXT':     '#222222',
        'MUTED':    '#888888',
        'ENTRY_BG': '#FFFFFF',
        'BTN_BG':   '#E8E8E8',
        'BORDER':   '#CCCCCC',
    },
    'dark': {
        'BG':       '#1E1E1E',
        'TEXT':     '#D4D4D4',
        'MUTED':    '#666666',
        'ENTRY_BG': '#2D2D2D',
        'BTN_BG':   '#3C3C3C',
        'BORDER':   '#444444',
    },
}


def _res(name: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, name)
    return name


def _load_tray_image(running: bool):
    """Load icon.png and tint white body green when running.

    Use same load path as v1.3.2 (PILImage.open) since in-memory ImageDraw
    creation has been unreliable in PyInstaller windowed exe.
    """
    from PIL import Image as PILImage
    img = PILImage.open(_res('icon.png')).convert('RGBA')
    if running:
        pixels = img.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = pixels[x, y]
                if a > 100 and r > 200 and g > 200 and b > 200:
                    pixels[x, y] = (76, 175, 80, a)
    return img


class _Toggle(tk.Canvas):
    W, H = 200, 72
    R = 36

    def __init__(self, parent, command=None):
        super().__init__(parent, width=self.W, height=self.H,
                         bd=0, highlightthickness=0)
        self._on = False
        self._cmd = command
        self._bg = '#F5F5F5'
        self.bind('<Button-1>', lambda _: self._click())
        self._redraw()

    def _click(self) -> None:
        self._on = not self._on
        self._redraw()
        if self._cmd:
            self._cmd(self._on)

    def set_state(self, on: bool) -> None:
        if self._on != on:
            self._on = on
            self._redraw()

    def configure_bg(self, bg: str) -> None:
        self._bg = bg
        self.config(bg=bg)
        self._redraw()

    def _redraw(self) -> None:
        self.delete('all')
        color = '#4CAF50' if self._on else '#9E9E9E'
        W, H, R = self.W, self.H, self.R
        self._pill(color, 0, 0, W, H)
        pad = 5
        kx = W - R if self._on else R
        ky = H // 2
        self.create_oval(kx - R + pad, ky - R + pad,
                         kx + R - pad, ky + R - pad,
                         fill='white', outline='')
        lx = W // 4 if self._on else 3 * W // 4
        self.create_text(lx, H // 2,
                         text='ON' if self._on else 'OFF',
                         fill='white', font=('Helvetica', 16, 'bold'))

    def _pill(self, color: str, x0: int, y0: int, x1: int, y1: int) -> None:
        r = (y1 - y0) // 2
        self.create_oval(x0, y0, x0 + 2 * r, y1, fill=color, outline='')
        self.create_oval(x1 - 2 * r, y0, x1, y1, fill=color, outline='')
        self.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline='')


class App(tk.Tk):
    @staticmethod
    def _get_system_dpi() -> int:
        if sys.platform == 'win32':
            import ctypes
            try:
                return ctypes.windll.user32.GetDpiForSystem()
            except Exception:
                pass
        return 96

    def __init__(self) -> None:
        super().__init__()
        dpi = self._get_system_dpi()
        self.tk.call('tk', 'scaling', dpi / 72.0)
        self._scale = dpi / 96.0
        self.title(f'Mouser  v{VERSION}')
        self.resizable(False, False)
        try:
            self.iconbitmap(_res('icon.ico'))
            img = tk.PhotoImage(file=_res('icon.png'))
            self.iconphoto(True, img)
            self._icon_img = img
        except Exception:
            pass

        self._loading = False
        self._cfg = settings.load()
        self._dark = self._cfg.get('theme', 'light') == 'dark'
        self._tray_icon = None
        self._going_to_tray = False
        self._stop_triggered = False
        self._stop_target: datetime.datetime | None = None
        self._tray_minimize: tk.BooleanVar

        self._tw: dict[str, list] = {
            'bg_frames': [],
            'labels':    [],
            'muted':     [],
            'spinboxes': [],
            'borders':   [],
            'btns':      [],
            'checks':    [],
        }

        self._build()
        self._apply_theme()

        self._loading = True
        self._load_settings()
        self._loading = False

        self.update_idletasks()
        self.geometry(f'{int(260 * self._scale)}x{self.winfo_reqheight()}')

        self._ctrl = Controller({})

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Unmap>', self._on_unmap)
        self.after(1000, self._check_stop_timer)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_header()
        self._build_stop_timer()
        self._build_separator()
        self._build_controls()
        self._build_separator()
        self._build_tray_setting()

    def _build_header(self) -> None:
        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=(6, 2))
        self._tw['bg_frames'].append(f)

        lbl = tk.Label(f, text='停止時刻', font=('Helvetica', 9))
        lbl.pack(side='left')
        self._tw['muted'].append(lbl)

        self._toggle_btn = tk.Button(
            f, text='ダーク',
            font=('Helvetica', 8),
            relief='solid', bd=1, padx=8, pady=2,
            cursor='hand2', command=self._toggle_theme,
        )
        self._toggle_btn.pack(side='right')
        self._tw['btns'].append(self._toggle_btn)

    def _build_stop_timer(self) -> None:
        outer = tk.Frame(self)
        outer.pack(fill='x', padx=12, pady=2)
        self._tw['bg_frames'].append(outer)

        self._stop_timer_enabled = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(
            outer, variable=self._stop_timer_enabled,
            text='有効', font=('Helvetica', 10),
            command=self._on_stop_timer_toggle,
        )
        cb.pack(side='left')
        self._tw['checks'].append(cb)

        self._stop_hour = tk.StringVar(value='17')
        self._stop_min  = tk.StringVar(value='00')

        self._stop_hour_sp = tk.Spinbox(
            outer, from_=0, to=23, increment=1,
            textvariable=self._stop_hour, width=4,
            relief='solid', bd=1, font=('Helvetica', 10),
            state='disabled',
        )
        self._stop_hour_sp.pack(side='left', padx=(8, 2))
        self._tw['spinboxes'].append(self._stop_hour_sp)

        colon = tk.Label(outer, text=':', font=('Helvetica', 10))
        colon.pack(side='left')
        self._tw['labels'].append(colon)

        self._stop_min_sp = tk.Spinbox(
            outer, from_=0, to=59, increment=1,
            textvariable=self._stop_min, width=4,
            relief='solid', bd=1, font=('Helvetica', 10),
            state='disabled',
        )
        self._stop_min_sp.pack(side='left', padx=(2, 0))
        self._tw['spinboxes'].append(self._stop_min_sp)

        self._stop_hour.trace_add('write', lambda *_: self._save_if_valid())
        self._stop_min.trace_add('write', lambda *_: self._fmt_min_and_save())
        self._stop_timer_enabled.trace_add('write', lambda *_: self._save_if_valid())

    def _build_separator(self) -> None:
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12, pady=(4, 4))
        self._tw['borders'].append(sep)

    def _build_controls(self) -> None:
        f = tk.Frame(self)
        f.pack(pady=(4, 4))
        self._tw['bg_frames'].append(f)
        self._toggle_sw = _Toggle(f, command=self._on_toggle)
        self._toggle_sw.pack()

    def _build_tray_setting(self) -> None:
        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=(2, 8))
        self._tw['bg_frames'].append(f)

        self._tray_minimize = tk.BooleanVar(value=True)
        tray_cb = tk.Checkbutton(
            f, variable=self._tray_minimize,
            text='最小化でタスクトレイ格納',
            font=('Helvetica', 8),
            command=self._save_if_valid,
        )
        tray_cb.pack(anchor='w')
        self._tw['checks'].append(tray_cb)

    # ── theme ─────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        t = THEMES['dark' if self._dark else 'light']
        self.configure(bg=t['BG'])
        for w in self._tw['bg_frames']: w.configure(bg=t['BG'])
        for w in self._tw['labels']:    w.configure(bg=t['BG'], fg=t['TEXT'])
        for w in self._tw['muted']:     w.configure(bg=t['BG'], fg=t['MUTED'])
        for w in self._tw['spinboxes']: w.configure(bg=t['ENTRY_BG'], fg=t['TEXT'],
                                                     buttonbackground=t['BTN_BG'],
                                                     insertbackground=t['TEXT'])
        for w in self._tw['borders']:   w.configure(bg=t['BORDER'])
        for w in self._tw['btns']:      w.configure(bg=t['BTN_BG'], fg=t['TEXT'],
                                                     activebackground=t['ENTRY_BG'],
                                                     activeforeground=t['TEXT'])
        for w in self._tw['checks']:    w.configure(bg=t['BG'], fg=t['TEXT'],
                                                     selectcolor=t['ENTRY_BG'],
                                                     activebackground=t['BG'],
                                                     activeforeground=t['TEXT'])
        self._toggle_btn.configure(text='ライト' if self._dark else 'ダーク')
        if hasattr(self, '_toggle_sw'):
            self._toggle_sw.configure_bg(t['BG'])

    def _toggle_theme(self) -> None:
        self._dark = not self._dark
        self._apply_theme()
        cfg = self._get_cfg() or {}
        cfg['theme'] = 'dark' if self._dark else 'light'
        settings.save(cfg)

    # ── logic ─────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        c = self._cfg
        self._stop_timer_enabled.set(bool(c.get('stop_timer_enabled', False)))
        self._stop_hour.set(str(c.get('stop_hour', 17)))
        self._stop_min.set(f"{c.get('stop_min', 0):02d}")
        self._tray_minimize.set(bool(c.get('tray_minimize', True)))
        self._on_stop_timer_toggle()

    def _on_stop_timer_toggle(self) -> None:
        state = 'normal' if self._stop_timer_enabled.get() else 'disabled'
        self._stop_hour_sp.configure(state=state)
        self._stop_min_sp.configure(state=state)

    def _get_cfg(self) -> dict | None:
        try:
            return {
                'theme': 'dark' if self._dark else 'light',
                'stop_timer_enabled': self._stop_timer_enabled.get(),
                'stop_hour': int(self._stop_hour.get()),
                'stop_min':  int(self._stop_min.get()),
                'tray_minimize': self._tray_minimize.get(),
            }
        except (ValueError, AttributeError):
            return None

    def _save_if_valid(self) -> None:
        if self._loading:
            return
        cfg = self._get_cfg()
        if cfg:
            settings.save(cfg)

    def _fmt_min_and_save(self) -> None:
        if self._loading:
            return
        try:
            v = int(self._stop_min.get())
            fmt = f'{v:02d}'
            if self._stop_min.get() != fmt:
                self._stop_min.set(fmt)
                return
        except ValueError:
            pass
        self._save_if_valid()

    def _calc_stop_target(self) -> 'datetime.datetime | None':
        try:
            now = datetime.datetime.now()
            h = int(self._stop_hour.get())
            m = int(self._stop_min.get())
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if dt <= now:
                dt += datetime.timedelta(days=1)
            return dt
        except (ValueError, AttributeError):
            return None

    def _on_toggle(self, on: bool) -> None:
        if on:
            self._on_start()
        else:
            self._on_stop()

    def _on_start(self) -> None:
        self._stop_triggered = False
        self._stop_target = self._calc_stop_target()
        self._ctrl.start()
        self._toggle_sw.set_state(True)
        self._update_tray_icon()

    def _on_stop(self) -> None:
        self._ctrl.stop()
        self._toggle_sw.set_state(False)
        self._update_tray_icon()

    def _check_stop_timer(self) -> None:
        if (self._stop_timer_enabled.get()
                and not self._stop_triggered
                and hasattr(self, '_ctrl')
                and self._ctrl.state == Controller.RUNNING
                and self._stop_target is not None):
            if datetime.datetime.now() >= self._stop_target:
                self._stop_triggered = True
                self._on_stop()
        self.after(1000, self._check_stop_timer)

    def _update_tray_icon(self) -> None:
        if self._tray_icon is None:
            return
        running = hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING
        try:
            self._tray_icon.icon = _load_tray_image(running)
        except Exception:
            pass

    # ── window events ─────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING:
            if not messagebox.askyesno('Mouser', '動作中です。終了しますか？'):
                return
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
        if hasattr(self, '_ctrl'):
            self._ctrl.stop()
        self.destroy()

    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget is self and not self._going_to_tray:
            self.after(50, self._check_iconify)

    def _check_iconify(self) -> None:
        if self.wm_state() == 'iconic' and self._tray_minimize.get():
            self._minimize_to_tray()

    def _minimize_to_tray(self) -> None:
        try:
            import pystray
            from PIL import Image as PILImage
        except ImportError:
            return
        if self._tray_icon is not None:
            self._going_to_tray = True
            self.withdraw()
            self._going_to_tray = False
            return
        running = hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING
        try:
            img = _load_tray_image(running)
        except Exception:
            img = PILImage.new('RGB', (64, 64),
                               '#4CAF50' if running else '#4A90D9')
        menu = pystray.Menu(
            pystray.MenuItem('タスクトレイから出す',
                             self._tray_restore, default=True),
            pystray.MenuItem('終了', self._tray_quit),
        )
        try:
            self._tray_icon = pystray.Icon('Mouser', img, 'Mouser', menu)
            threading.Thread(target=self._tray_icon.run,
                             daemon=True).start()
        except Exception:
            self._tray_icon = None
            return
        self._going_to_tray = True
        self.withdraw()
        self._going_to_tray = False

    def _tray_restore(self, icon=None, item=None) -> None:
        icon_ref = self._tray_icon
        self._tray_icon = None
        if icon_ref:
            icon_ref.stop()
        self.after(0, self.deiconify)

    def _tray_quit(self, icon=None, item=None) -> None:
        icon_ref = self._tray_icon
        self._tray_icon = None
        if icon_ref:
            icon_ref.stop()
        if hasattr(self, '_ctrl'):
            self._ctrl.stop()
        self.after(0, self.destroy)
