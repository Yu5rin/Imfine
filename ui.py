import datetime
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

import pyautogui

import settings
from controller import Controller


VERSION = '1.4.3'

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
        self._current_interval = settings.DEFAULTS['interval']
        self._tray_minimize: tk.BooleanVar  # set in _build_footer

        self._lockable: list = []       # disabled while running
        self._coord_entries: list = []  # also disabled in wiggle mode
        self._coord_btns: list = []     # also disabled in wiggle mode

        self._tw: dict[str, list] = {
            'bg_frames': [],
            'labels':    [],
            'muted':     [],
            'entries':   [],
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

        # ウィジェット描画後に必要な高さを取得して確定
        self.update_idletasks()
        self.geometry(f'{int(360 * self._scale)}x{self.winfo_reqheight()}')

        self._ctrl = Controller({
            'status': lambda msg: self.after(0, lambda m=msg: self._status.set(m)),
        })

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Unmap>', self._on_unmap)
        self.after(1000, self._check_stop_timer)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._section('座標設定')
        self._build_mode()
        self._ax, self._ay = self._coord_row('地点 A')
        self._bx, self._by = self._coord_row('地点 B')

        self._section('往復間隔')
        self._build_interval()

        self._section('移動速度')
        self._build_speed()

        self._section('停止時刻')
        self._build_stop_timer()

        self._build_controls()
        self._build_status()
        self._build_footer()

    def _section(self, title: str) -> None:
        lbl = tk.Label(self, text=title, font=('Helvetica', 9))
        lbl.pack(anchor='w', padx=14, pady=(8, 1))
        self._tw['muted'].append(lbl)
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12)
        self._tw['borders'].append(sep)

    def _build_mode(self) -> None:
        row = tk.Frame(self)
        row.pack(fill='x', padx=12, pady=(3, 1))
        self._tw['bg_frames'].append(row)

        self._move_mode = tk.StringVar(value='ab')

        rb_ab = tk.Radiobutton(
            row, text='A-B往復', variable=self._move_mode, value='ab',
            font=('Helvetica', 9), command=self._on_mode_change,
        )
        rb_ab.pack(side='left')
        self._tw['checks'].append(rb_ab)
        self._lockable.append(rb_ab)

        rb_w = tk.Radiobutton(
            row, text='その場でふりこ', variable=self._move_mode, value='wiggle',
            font=('Helvetica', 9), command=self._on_mode_change,
        )
        rb_w.pack(side='left', padx=(8, 0))
        self._tw['checks'].append(rb_w)
        self._lockable.append(rb_w)

        dist_lbl = tk.Label(row, text='距離:', font=('Helvetica', 9))
        dist_lbl.pack(side='left', padx=(12, 2))
        self._tw['muted'].append(dist_lbl)

        self._wiggle_px = tk.StringVar(value='5')
        self._wiggle_sp = tk.Spinbox(
            row, from_=1, to=200, increment=1,
            textvariable=self._wiggle_px, width=4,
            relief='solid', bd=1, font=('Helvetica', 9),
            state='disabled',
        )
        self._wiggle_sp.pack(side='left')
        self._tw['spinboxes'].append(self._wiggle_sp)

        px_lbl = tk.Label(row, text='px', font=('Helvetica', 9))
        px_lbl.pack(side='left', padx=(2, 0))
        self._tw['muted'].append(px_lbl)

        self._wiggle_px.trace_add('write', lambda *_: self._save_if_valid())
        self._move_mode.trace_add('write', lambda *_: self._save_if_valid())

    def _coord_row(self, label: str) -> tuple[tk.StringVar, tk.StringVar]:
        row = tk.Frame(self)
        row.pack(fill='x', padx=12, pady=3)
        self._tw['bg_frames'].append(row)

        lbl = tk.Label(row, text=label, width=7, anchor='w', font=('Helvetica', 10))
        lbl.pack(side='left')
        self._tw['labels'].append(lbl)

        xv, yv = tk.StringVar(), tk.StringVar()
        for axis, var in (('X', xv), ('Y', yv)):
            al = tk.Label(row, text=axis, font=('Helvetica', 10))
            al.pack(side='left', padx=(6, 2))
            self._tw['muted'].append(al)

            e = tk.Entry(row, textvariable=var, width=6,
                         relief='solid', bd=1, font=('Helvetica', 10),
                         highlightthickness=0)
            e.pack(side='left')
            self._tw['entries'].append(e)
            self._coord_entries.append(e)
            var.trace_add('write', lambda *_: self._save_if_valid())

        btn = tk.Button(
            row, text='現在地取得',
            relief='solid', bd=1, padx=6, pady=1, font=('Helvetica', 9),
            cursor='hand2',
            command=lambda lbl=label, x=xv, y=yv: self._capture(lbl, x, y),
        )
        btn.pack(side='left', padx=(8, 0))
        self._tw['btns'].append(btn)
        self._coord_btns.append(btn)
        return xv, yv

    def _build_interval(self) -> None:
        outer = tk.Frame(self)
        outer.pack(fill='x', padx=12, pady=3)
        self._tw['bg_frames'].append(outer)

        self._interval = tk.StringVar()
        sp = tk.Spinbox(
            outer, from_=0.5, to=3600, increment=0.5,
            textvariable=self._interval, width=8,
            relief='solid', bd=1, font=('Helvetica', 10),
        )
        sp.pack(side='left')
        self._tw['spinboxes'].append(sp)
        self._lockable.append(sp)

        ul = tk.Label(outer, text='秒', font=('Helvetica', 10))
        ul.pack(side='left', padx=(4, 0))
        self._tw['labels'].append(ul)
        self._interval.trace_add('write', lambda *_: self._save_if_valid())

        presets = [
            ('30秒', 30), ('1分', 60), ('2分', 120), ('3分', 180),
            ('4分', 240), ('5分', 300), ('10分', 600), ('30分', 1800),
        ]
        for r in range(2):
            fr = tk.Frame(self)
            fr.pack(fill='x', padx=12, pady=1)
            self._tw['bg_frames'].append(fr)
            for lbl, val in presets[r * 4:(r + 1) * 4]:
                btn = tk.Button(
                    fr, text=lbl,
                    relief='solid', bd=1, padx=6, pady=2, font=('Helvetica', 9),
                    cursor='hand2',
                    command=lambda v=val: self._interval.set(str(float(v))),
                )
                btn.pack(side='left', padx=(0, 4))
                self._tw['btns'].append(btn)
                self._lockable.append(btn)

    def _build_speed(self) -> None:
        row = tk.Frame(self)
        row.pack(fill='x', padx=12, pady=3)
        self._tw['bg_frames'].append(row)

        self._duration = tk.StringVar()
        sp = tk.Spinbox(
            row, from_=0.0, to=5.0, increment=0.1,
            textvariable=self._duration, width=8,
            relief='solid', bd=1, font=('Helvetica', 10),
        )
        sp.pack(side='left')
        self._tw['spinboxes'].append(sp)
        self._lockable.append(sp)

        ul = tk.Label(row, text='秒', font=('Helvetica', 10))
        ul.pack(side='left', padx=(4, 0))
        self._tw['labels'].append(ul)
        self._duration.trace_add('write', lambda *_: self._save_if_valid())

    def _build_stop_timer(self) -> None:
        outer = tk.Frame(self)
        outer.pack(fill='x', padx=12, pady=3)
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
        self._stop_min = tk.StringVar(value='0')

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
        self._stop_min.trace_add('write', lambda *_: self._save_if_valid())
        self._stop_timer_enabled.trace_add('write', lambda *_: self._save_if_valid())

    def _build_controls(self) -> None:
        f = tk.Frame(self)
        f.pack(pady=(10, 6))
        self._tw['bg_frames'].append(f)

        self._start_btn = tk.Button(
            f, text='START', bg=START_BG, fg='white',
            font=('Helvetica', 12, 'bold'), padx=28, pady=6,
            relief='flat', cursor='hand2', command=self._on_start,
            activebackground='#3A7BC8', activeforeground='white',
        )
        self._start_btn.pack(side='left', padx=6)

        self._stop_btn = tk.Button(
            f, text='STOP',
            font=('Helvetica', 12, 'bold'), padx=28, pady=6,
            relief='solid', bd=1, cursor='hand2', command=self._on_stop,
            state='disabled',
        )
        self._stop_btn.pack(side='left', padx=6)

    def _build_status(self) -> None:
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12)
        self._tw['borders'].append(sep)

        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=4)
        self._tw['bg_frames'].append(f)

        self._status = tk.StringVar(value='待機中')
        lbl = tk.Label(f, textvariable=self._status,
                        font=('Helvetica', 10), anchor='center')
        lbl.pack(fill='x')
        self._tw['labels'].append(lbl)

    def _build_footer(self) -> None:
        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=(0, 6))
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

        self._toggle_btn = tk.Button(
            f, text='ダーク',
            font=('Helvetica', 8),
            relief='solid', bd=1, padx=8, pady=2,
            cursor='hand2', command=self._toggle_theme,
        )
        self._toggle_btn.pack(anchor='e', pady=(3, 0))
        self._tw['btns'].append(self._toggle_btn)

    # ── theme ─────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        t = THEMES['dark' if self._dark else 'light']
        self.configure(bg=t['BG'])
        for w in self._tw['bg_frames']: w.configure(bg=t['BG'])
        for w in self._tw['labels']:    w.configure(bg=t['BG'], fg=t['TEXT'])
        for w in self._tw['muted']:     w.configure(bg=t['BG'], fg=t['MUTED'])
        for w in self._tw['entries']:   w.configure(bg=t['ENTRY_BG'], fg=t['TEXT'],
                                                     insertbackground=t['TEXT'])
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

    # ── mode ──────────────────────────────────────────────────────────────

    def _on_mode_change(self) -> None:
        is_wiggle = self._move_mode.get() == 'wiggle'
        self._wiggle_sp.configure(state='normal' if is_wiggle else 'disabled')
        coord_state = 'disabled' if is_wiggle else 'normal'
        for w in self._coord_entries:
            w.configure(state=coord_state)
        for w in self._coord_btns:
            w.configure(state=coord_state)

    def _set_controls_running(self, running: bool) -> None:
        base = 'disabled' if running else 'normal'
        for w in self._lockable:
            w.configure(state=base)
        if running:
            for w in self._coord_entries: w.configure(state='disabled')
            for w in self._coord_btns:    w.configure(state='disabled')
            self._wiggle_sp.configure(state='disabled')
        else:
            is_ab = self._move_mode.get() == 'ab'
            coord_state = 'normal' if is_ab else 'disabled'
            for w in self._coord_entries: w.configure(state=coord_state)
            for w in self._coord_btns:    w.configure(state=coord_state)
            self._wiggle_sp.configure(state='disabled' if is_ab else 'normal')

    # ── logic ─────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        c = self._cfg
        self._ax.set(str(c['x1']))
        self._ay.set(str(c['y1']))
        self._bx.set(str(c['x2']))
        self._by.set(str(c['y2']))
        self._interval.set(str(c['interval']))
        self._duration.set(str(c['duration']))
        self._stop_timer_enabled.set(bool(c.get('stop_timer_enabled', False)))
        self._stop_hour.set(str(c.get('stop_hour', 17)))
        self._stop_min.set(str(c.get('stop_min', 0)))
        self._tray_minimize.set(bool(c.get('tray_minimize', True)))
        self._move_mode.set(c.get('move_mode', 'ab'))
        self._wiggle_px.set(str(c.get('wiggle_px', 5)))
        self._on_stop_timer_toggle()
        self._on_mode_change()

    def _on_stop_timer_toggle(self) -> None:
        state = 'normal' if self._stop_timer_enabled.get() else 'disabled'
        self._stop_hour_sp.configure(state=state)
        self._stop_min_sp.configure(state=state)

    def _get_cfg(self) -> dict | None:
        try:
            return {
                'x1': int(self._ax.get()),
                'y1': int(self._ay.get()),
                'x2': int(self._bx.get()),
                'y2': int(self._by.get()),
                'interval': float(self._interval.get()),
                'duration': float(self._duration.get()),
                'theme': 'dark' if self._dark else 'light',
                'stop_timer_enabled': self._stop_timer_enabled.get(),
                'stop_hour': int(self._stop_hour.get()),
                'stop_min': int(self._stop_min.get()),
                'tray_minimize': self._tray_minimize.get(),
                'move_mode': self._move_mode.get(),
                'wiggle_px': int(self._wiggle_px.get()),
            }
        except (ValueError, AttributeError):
            return None

    def _save_if_valid(self) -> None:
        if self._loading:
            return
        cfg = self._get_cfg()
        if cfg:
            settings.save(cfg)

    def _capture(self, label: str, xv: tk.StringVar, yv: tk.StringVar) -> None:
        threading.Thread(target=self._do_capture, args=(label, xv, yv), daemon=True).start()

    def _do_capture(self, label: str, xv: tk.StringVar, yv: tk.StringVar) -> None:
        for i in range(3, 0, -1):
            self.after(0, lambda i=i: self._status.set(f'{label} を{i}秒後に取得します…'))
            time.sleep(1)
        x, y = pyautogui.position()
        self.after(0, lambda: xv.set(str(x)))
        self.after(0, lambda: yv.set(str(y)))
        self.after(0, lambda: self._status.set(f'{label} を取得しました: ({x}, {y})'))

    def _on_start(self) -> None:
        cfg = self._get_cfg()
        if not cfg:
            self._status.set('入力値を確認してください')
            return
        self._stop_triggered = False
        self._current_interval = cfg['interval']
        self._ctrl.start(
            cfg['x1'], cfg['y1'], cfg['x2'], cfg['y2'],
            cfg['duration'], cfg['interval'],
            cfg['move_mode'], cfg['wiggle_px'],
        )
        self._set_controls_running(True)
        self._start_btn.config(state='disabled')
        self._stop_btn.config(state='normal')

    def _on_stop(self) -> None:
        self._ctrl.stop()
        self._set_controls_running(False)
        self._start_btn.config(state='normal')
        self._stop_btn.config(state='disabled')

    def _check_stop_timer(self) -> None:
        if (self._stop_timer_enabled.get()
                and not self._stop_triggered
                and hasattr(self, '_ctrl')
                and self._ctrl.state in (Controller.RUNNING, Controller.PAUSED)):
            try:
                now = datetime.datetime.now()
                h = int(self._stop_hour.get())
                m = int(self._stop_min.get())
                stop_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                trigger_dt = stop_dt - datetime.timedelta(seconds=self._current_interval)
                if now >= trigger_dt:
                    self._stop_triggered = True
                    self._on_stop()
            except (ValueError, AttributeError):
                pass
        self.after(1000, self._check_stop_timer)

    # ── window events ─────────────────────────────────────────────────────

    def _on_close(self) -> None:
        if hasattr(self, '_ctrl') and self._ctrl.state in (Controller.RUNNING, Controller.PAUSED):
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
            img = PILImage.new('RGBA', (64, 64), '#4A90D9')
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
