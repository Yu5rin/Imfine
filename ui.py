import threading
import time
import tkinter as tk
from tkinter import ttk

import pyautogui

import settings
from controller import Controller

VERSION = '1.1.0'

BG = '#F5F5F5'
TEXT = '#222222'
MUTED = '#888888'
ENTRY_BG = '#FFFFFF'
BTN_BG = '#E8E8E8'
START_BG = '#4A90D9'
STOP_BG = '#E8E8E8'
BORDER = '#CCCCCC'


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Mouser')
        self.geometry('360x375')
        self.resizable(False, False)
        self.configure(bg=BG)
        try:
            self.iconbitmap('icon.ico')
            img = tk.PhotoImage(file='icon.png')
            self.iconphoto(True, img)
            self._icon_img = img
        except Exception:
            pass

        self._loading = False
        self._cfg = settings.load()
        self._build()
        self._loading = True
        self._load_settings()
        self._loading = False

        self._ctrl = Controller({
            'status': lambda msg: self.after(0, lambda m=msg: self._status.set(m)),
            'on_emergency': lambda: self.after(0, self._on_emergency_ui),
        })

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # 座標設定
        self._section('座標設定')
        self._ax, self._ay = self._coord_row('地点 A')
        self._bx, self._by = self._coord_row('地点 B')

        # 往復間隔
        self._section('往復間隔')
        self._build_interval()

        # 移動速度
        self._section('移動速度')
        self._build_speed()

        # ボタン
        self._build_controls()

        # ステータス
        self._build_status()

        # フッター
        self._build_footer()

    def _section(self, title: str) -> None:
        tk.Label(self, text=title, bg=BG, fg=MUTED,
                 font=('Helvetica', 9)).pack(anchor='w', padx=14, pady=(8, 1))
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x', padx=12)

    def _coord_row(self, label: str) -> tuple[tk.StringVar, tk.StringVar]:
        row = tk.Frame(self, bg=BG)
        row.pack(fill='x', padx=12, pady=3)
        tk.Label(row, text=label, bg=BG, fg=TEXT, width=7,
                 anchor='w', font=('Helvetica', 10)).pack(side='left')
        xv, yv = tk.StringVar(), tk.StringVar()
        for axis, var in (('X', xv), ('Y', yv)):
            tk.Label(row, text=axis, bg=BG, fg=MUTED,
                     font=('Helvetica', 10)).pack(side='left', padx=(6, 2))
            tk.Entry(row, textvariable=var, width=6, bg=ENTRY_BG, fg=TEXT,
                     relief='solid', bd=1, font=('Helvetica', 10),
                     highlightthickness=0).pack(side='left')
            var.trace_add('write', lambda *_: self._save_if_valid())
        tk.Button(
            row, text='現在地取得', bg=BTN_BG, fg=TEXT,
            relief='solid', bd=1, padx=6, pady=1, font=('Helvetica', 9),
            cursor='hand2', command=lambda lbl=label, x=xv, y=yv: self._capture(lbl, x, y),
        ).pack(side='left', padx=(8, 0))
        return xv, yv

    def _build_interval(self) -> None:
        outer = tk.Frame(self, bg=BG)
        outer.pack(fill='x', padx=12, pady=3)

        self._interval = tk.StringVar()
        tk.Spinbox(
            outer, from_=0.5, to=3600, increment=0.5,
            textvariable=self._interval, width=8,
            bg=ENTRY_BG, fg=TEXT, relief='solid', bd=1,
            font=('Helvetica', 10), buttonbackground=BTN_BG,
        ).pack(side='left')
        tk.Label(outer, text='秒', bg=BG, fg=TEXT,
                 font=('Helvetica', 10)).pack(side='left', padx=(4, 0))
        self._interval.trace_add('write', lambda *_: self._save_if_valid())

        presets = [
            ('30秒', 30), ('1分', 60), ('2分', 120), ('3分', 180),
            ('4分', 240), ('5分', 300), ('10分', 600), ('30分', 1800),
        ]
        for r in range(2):
            fr = tk.Frame(self, bg=BG)
            fr.pack(fill='x', padx=12, pady=1)
            for lbl, val in presets[r * 4:(r + 1) * 4]:
                tk.Button(
                    fr, text=lbl, bg=BTN_BG, fg=TEXT,
                    relief='solid', bd=1, padx=6, pady=2, font=('Helvetica', 9),
                    cursor='hand2',
                    command=lambda v=val: self._interval.set(str(float(v))),
                ).pack(side='left', padx=(0, 4))

    def _build_speed(self) -> None:
        row = tk.Frame(self, bg=BG)
        row.pack(fill='x', padx=12, pady=3)
        self._duration = tk.StringVar()
        tk.Spinbox(
            row, from_=0.0, to=5.0, increment=0.1,
            textvariable=self._duration, width=8,
            bg=ENTRY_BG, fg=TEXT, relief='solid', bd=1,
            font=('Helvetica', 10), buttonbackground=BTN_BG,
        ).pack(side='left')
        tk.Label(row, text='秒', bg=BG, fg=TEXT,
                 font=('Helvetica', 10)).pack(side='left', padx=(4, 0))
        self._duration.trace_add('write', lambda *_: self._save_if_valid())

    def _build_controls(self) -> None:
        f = tk.Frame(self, bg=BG)
        f.pack(pady=(10, 6))
        self._start_btn = tk.Button(
            f, text='START', bg=START_BG, fg='white',
            font=('Helvetica', 12, 'bold'), padx=28, pady=6,
            relief='flat', cursor='hand2', command=self._on_start,
            activebackground='#3A7BC8', activeforeground='white',
        )
        self._start_btn.pack(side='left', padx=6)
        self._stop_btn = tk.Button(
            f, text='STOP', bg=STOP_BG, fg=TEXT,
            font=('Helvetica', 12, 'bold'), padx=28, pady=6,
            relief='solid', bd=1, cursor='hand2', command=self._on_stop,
            state='disabled',
        )
        self._stop_btn.pack(side='left', padx=6)

    def _build_status(self) -> None:
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x', padx=12)
        f = tk.Frame(self, bg=BG)
        f.pack(fill='x', padx=12, pady=4)
        self._status = tk.StringVar(value='待機中')
        tk.Label(f, textvariable=self._status, bg=BG, fg=TEXT,
                 font=('Helvetica', 10), anchor='center').pack(fill='x')

    def _build_footer(self) -> None:
        f = tk.Frame(self, bg=BG)
        f.pack(fill='x', padx=12, pady=(0, 5))
        tk.Label(f, text='緊急停止: 画面左上コーナーへ移動',
                 bg=BG, fg=MUTED, font=('Helvetica', 8)).pack(side='left')
        tk.Label(f, text=f'v{VERSION}',
                 bg=BG, fg=MUTED, font=('Helvetica', 8)).pack(side='right')

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
