import threading
import time
import tkinter as tk

import pyautogui

import settings
from controller import Controller

VERSION = '1.2.0'

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


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Mouser')
        self.geometry('360x375')
        self.resizable(False, False)
        try:
            self.iconbitmap('icon.ico')
            img = tk.PhotoImage(file='icon.png')
            self.iconphoto(True, img)
            self._icon_img = img
        except Exception:
            pass

        self._loading = False
        self._cfg = settings.load()
        self._dark = self._cfg.get('theme', 'light') == 'dark'

        self._tw: dict[str, list] = {
            'bg_frames': [],
            'labels':    [],
            'muted':     [],
            'entries':   [],
            'spinboxes': [],
            'borders':   [],
            'btns':      [],
        }

        self._build()
        self._apply_theme()

        self._loading = True
        self._load_settings()
        self._loading = False

        self._ctrl = Controller({
            'status': lambda msg: self.after(0, lambda m=msg: self._status.set(m)),
            'on_emergency': lambda: self.after(0, self._on_emergency_ui),
        })

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._section('座標設定')
        self._ax, self._ay = self._coord_row('地点 A')
        self._bx, self._by = self._coord_row('地点 B')

        self._section('往復間隔')
        self._build_interval()

        self._section('移動速度')
        self._build_speed()

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
            var.trace_add('write', lambda *_: self._save_if_valid())

        btn = tk.Button(
            row, text='現在地取得',
            relief='solid', bd=1, padx=6, pady=1, font=('Helvetica', 9),
            cursor='hand2',
            command=lambda lbl=label, x=xv, y=yv: self._capture(lbl, x, y),
        )
        btn.pack(side='left', padx=(8, 0))
        self._tw['btns'].append(btn)
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

        ul = tk.Label(row, text='秒', font=('Helvetica', 10))
        ul.pack(side='left', padx=(4, 0))
        self._tw['labels'].append(ul)
        self._duration.trace_add('write', lambda *_: self._save_if_valid())

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
        f.pack(fill='x', padx=12, pady=(0, 5))
        self._tw['bg_frames'].append(f)

        el = tk.Label(f, text='緊急停止: 画面左上コーナーへ移動',
                      font=('Helvetica', 8))
        el.pack(side='left')
        self._tw['muted'].append(el)

        vl = tk.Label(f, text=f'v{VERSION}', font=('Helvetica', 8))
        vl.pack(side='right')
        self._tw['muted'].append(vl)

        self._toggle_btn = tk.Button(
            f, text='ダーク', font=('Helvetica', 8),
            relief='flat', bd=0, padx=4, pady=0,
            cursor='hand2', command=self._toggle_theme,
        )
        self._toggle_btn.pack(side='right', padx=4)
        self._tw['muted'].append(self._toggle_btn)

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
        self._ax.set(str(c['x1']))
        self._ay.set(str(c['y1']))
        self._bx.set(str(c['x2']))
        self._by.set(str(c['y2']))
        self._interval.set(str(c['interval']))
        self._duration.set(str(c['duration']))

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
            }
        except ValueError:
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
        self._ctrl.start(cfg['x1'], cfg['y1'], cfg['x2'], cfg['y2'], cfg['duration'], cfg['interval'])
        self._start_btn.config(state='disabled')
        self._stop_btn.config(state='normal')

    def _on_stop(self) -> None:
        self._ctrl.stop()
        self._start_btn.config(state='normal')
        self._stop_btn.config(state='disabled')

    def _on_emergency_ui(self) -> None:
        self._start_btn.config(state='normal')
        self._stop_btn.config(state='disabled')
