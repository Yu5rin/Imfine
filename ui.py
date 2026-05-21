import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

import settings
import updater
from controller import Controller


VERSION = '1.6.5'

THEMES: dict = {
    'light': {
        'BG':       '#F5F5F5',
        'TEXT':     '#222222',
        'MUTED':    '#888888',
        'ENTRY_BG': '#FFFFFF',
        'BTN_BG':   '#E8E8E8',
        'BORDER':   '#CCCCCC',
        'STOP_BG':  '#E8E8E8',
    },
    'dark': {
        'BG':       '#1E1E1E',
        'TEXT':     '#D4D4D4',
        'MUTED':    '#666666',
        'ENTRY_BG': '#2D2D2D',
        'BTN_BG':   '#3C3C3C',
        'BORDER':   '#444444',
        'STOP_BG':  '#3C3C3C',
    },
}
START_BG = '#4A90D9'


def _res(name: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, name)
    return name


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
        self._tray_minimize: tk.BooleanVar  # set in _build_footer

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

        self._ctrl = Controller({
            'status': lambda msg: self.after(0, lambda m=msg: self._status.set(m)),
        })

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Unmap>', self._on_unmap)
        self.after(1000, self._check_stop_timer)
        self.after(2000, self._check_update)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_theme_toggle()
        self._section('停止時刻')
        self._build_stop_timer()
        self._build_controls()
        self._build_status()
        self._build_tray_setting()

    def _section(self, title: str) -> None:
        lbl = tk.Label(self, text=title, font=('Helvetica', 9))
        lbl.pack(anchor='w', padx=14, pady=(4, 1))
        self._tw['muted'].append(lbl)
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12)
        self._tw['borders'].append(sep)

    def _build_theme_toggle(self) -> None:
        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=(6, 2))
        self._tw['bg_frames'].append(f)

        update_btn = tk.Button(
            f, text='更新',
            font=('Helvetica', 8),
            relief='solid', bd=1, padx=8, pady=2,
            cursor='hand2', command=lambda: self._check_update(manual=True),
        )
        update_btn.pack(side='right', padx=(4, 0))
        self._tw['btns'].append(update_btn)

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

    def _build_controls(self) -> None:
        f = tk.Frame(self)
        f.pack(pady=(6, 4))
        self._tw['bg_frames'].append(f)

        self._start_btn = tk.Button(
            f, text='START', bg=START_BG, fg='white',
            font=('Helvetica', 12, 'bold'), padx=20, pady=4,
            relief='flat', cursor='hand2', command=self._on_start,
            activebackground='#3A7BC8', activeforeground='white',
        )
        self._start_btn.pack(side='left', padx=6)

        self._stop_btn = tk.Button(
            f, text='STOP',
            font=('Helvetica', 12, 'bold'), padx=20, pady=4,
            relief='solid', bd=1, cursor='hand2', command=self._on_stop,
            state='disabled',
        )
        self._stop_btn.pack(side='left', padx=6)

    def _build_status(self) -> None:
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12)
        self._tw['borders'].append(sep)

        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=3)
        self._tw['bg_frames'].append(f)

        self._status = tk.StringVar(value='待機中')
        lbl = tk.Label(f, textvariable=self._status,
                        font=('Helvetica', 10), anchor='center')
        lbl.pack(fill='x')
        self._tw['labels'].append(lbl)

    def _build_tray_setting(self) -> None:
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12)
        self._tw['borders'].append(sep)

        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=(4, 6))
        self._tw['bg_frames'].append(f)

        self._tray_minimize = tk.BooleanVar(value=True)
        tray_cb = tk.Checkbutton(
            f, variable=self._tray_minimize,
            text='最小化時にタスクトレイに格納する',
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
        self._stop_btn.configure(bg=t['STOP_BG'], fg=t['TEXT'],
                                  activebackground=t['ENTRY_BG'],
                                  activeforeground=t['TEXT'])
        self._toggle_btn.configure(text='ライト' if self._dark else 'ダーク')

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

    def _check_update(self, manual: bool = False) -> None:
        if manual:
            self._status.set('更新を確認中...')
        def on_available(tag: str, url: str) -> None:
            self.after(0, lambda: self._prompt_update(tag, url))
        def on_up_to_date(tag) -> None:
            if manual:
                msg = '最新版です。' if tag else '確認に失敗しました。'
                self.after(0, lambda: self._status.set(msg))
        updater.check_and_prompt(VERSION, on_available,
                                 on_up_to_date=on_up_to_date if manual else None)

    def _prompt_update(self, tag: str, url: str) -> None:
        if messagebox.askyesno('Mouser',
                f'新しいバージョン {tag} があります。\n今すぐアップデートしますか？'):
            self._status.set('ダウンロード中...')
            threading.Thread(
                target=lambda: updater.download_and_replace(url),
                daemon=True,
            ).start()

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

    def _on_start(self) -> None:
        self._stop_triggered = False
        self._stop_target = self._calc_stop_target()
        self._ctrl.start()
        self._start_btn.config(state='disabled')
        self._stop_btn.config(state='normal')

    def _on_stop(self) -> None:
        self._ctrl.stop()
        self._start_btn.config(state='normal')
        self._stop_btn.config(state='disabled')

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
        self._going_to_tray = True
        self.withdraw()
        self._going_to_tray = False
        if self._tray_icon is not None:
            return
        try:
            img = PILImage.open(_res('icon.png'))
        except Exception:
            img = PILImage.new('RGB', (64, 64), '#4A90D9')
        menu = pystray.Menu(
            pystray.MenuItem('タスクトレイから出す', self._tray_restore, default=True),
            pystray.MenuItem('終了', self._tray_quit),
        )
        self._tray_icon = pystray.Icon('Mouser', img, 'Mouser', menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

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
