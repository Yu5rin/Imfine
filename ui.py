import threading
import time
import tkinter as tk

import pyautogui

import settings
from controller import Controller

BG = '#1A1A2E'
PANEL = '#16213E'
ACCENT = '#E94560'
TEXT = '#EAEAEA'
BTN = '#0F3460'
STOP_COLOR = '#4A4A6A'
SEP_COLOR = '#2A2A4E'


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title('Mouser')
        self.geometry('440x600')
        self.resizable(False, False)
        self.configure(bg=BG)
        try:
            self.iconbitmap('icon.ico')
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
        self._build_header()
        self._sep()
        self._build_coords()
        self._sep()
        self._build_interval()
        self._sep()
        self._build_speed()
        self._sep()
        self._build_controls()
        self._sep()
        self._build_status()
        self._sep()
        self._build_footer()

    def _sep(self) -> None:
        tk.Frame(self, bg=SEP_COLOR, height=1).pack(fill='x', padx=10, pady=2)

    def _panel(self, title: str) -> tk.Frame:
        outer = tk.Frame(self, bg=PANEL, padx=8, pady=5)
        outer.pack(fill='x', padx=10, pady=2)
        tk.Label(outer, text=title, fg=ACCENT, bg=PANEL, font=('Helvetica', 10, 'bold')).pack(anchor='w', pady=(0, 3))
        return outer

    def _build_header(self) -> None:
        h = tk.Frame(self, bg=BG, pady=10)
        h.pack(fill='x')
        try:
            img = tk.PhotoImage(file='icon.png').subsample(6)
            lbl = tk.Label(h, image=img, bg=BG)
            lbl.image = img
            lbl.pack(side='left', padx=(20, 8))
        except Exception:
            tk.Label(h, text='M', font=('Helvetica', 26, 'bold'), bg=BG, fg=ACCENT).pack(side='left', padx=(20, 8))
        tf = tk.Frame(h, bg=BG)
        tf.pack(side='left')
        tk.Label(tf, text='Mouser', font=('Helvetica', 22, 'bold'), fg=ACCENT, bg=BG).pack(anchor='w')
        tk.Label(tf, text='マウス自動移動ツール', font=('Helvetica', 9), fg=TEXT, bg=BG).pack(anchor='w')

    def _build_coords(self) -> None:
        p = self._panel('座標設定')
        self._ax, self._ay = self._coord_row(p, '地点 A')
        self._bx, self._by = self._coord_row(p, '地点 B')

    def _coord_row(self, parent: tk.Frame, label: str) -> tuple[tk.StringVar, tk.StringVar]:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill='x', pady=2)
        tk.Label(row, text=label, fg=TEXT, bg=PANEL, width=7, anchor='w', font=('Helvetica', 10)).pack(side='left')
        xv = tk.StringVar()
        yv = tk.StringVar()
        for axis, var in (('X', xv), ('Y', yv)):
            tk.Label(row, text=axis, fg=TEXT, bg=PANEL, font=('Helvetica', 10)).pack(side='left', padx=(3, 1))
            tk.Entry(row, textvariable=var, width=6, bg=BTN, fg=TEXT,
                     insertbackground=TEXT, relief='flat', font=('Helvetica', 10)).pack(side='left', padx=(0, 2))
            var.trace_add('write', lambda *_: self._save_if_valid())
        tk.Button(
            row, text='現在地取得', bg=BTN, fg=TEXT, relief='flat',
            padx=5, pady=2, font=('Helvetica', 9),
            activebackground=ACCENT, activeforeground='white', cursor='hand2',
            command=lambda lbl=label, x=xv, y=yv: self._capture(lbl, x, y),
        ).pack(side='left', padx=6)
        return xv, yv

    def _build_interval(self) -> None:
        p = self._panel('往復間隔')
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill='x', pady=(0, 3))
        self._interval = tk.StringVar()
        tk.Spinbox(
            row, from_=0.5, to=3600, increment=0.5, textvariable=self._interval,
            width=10, bg=BTN, fg=TEXT, insertbackground=TEXT, buttonbackground=BTN,
            relief='flat', font=('Helvetica', 11),
        ).pack(side='left', padx=4)
        tk.Label(row, text='秒', fg=TEXT, bg=PANEL, font=('Helvetica', 10)).pack(side='left')
        self._interval.trace_add('write', lambda *_: self._save_if_valid())

        presets = [
            ('30秒', 30), ('1分', 60), ('2分', 120), ('3分', 180),
            ('4分', 240), ('5分', 300), ('10分', 600), ('30分', 1800),
        ]
        for r in range(2):
            fr = tk.Frame(p, bg=PANEL)
            fr.pack(fill='x', pady=1)
            for lbl, val in presets[r * 4:(r + 1) * 4]:
                tk.Button(
                    fr, text=lbl, bg=BTN, fg=TEXT, relief='flat',
                    padx=7, pady=3, font=('Helvetica', 9),
                    activebackground=ACCENT, activeforeground='white', cursor='hand2',
                    command=lambda v=val: self._interval.set(str(float(v))),
                ).pack(side='left', padx=2)

    def _build_speed(self) -> None:
        p = self._panel('移動速度')
        row = tk.Frame(p, bg=PANEL)
        row.pack(fill='x', pady=(0, 2))
        self._duration = tk.StringVar()
        tk.Spinbox(
            row, from_=0.0, to=5.0, increment=0.1, textvariable=self._duration,
            width=10, bg=BTN, fg=TEXT, insertbackground=TEXT, buttonbackground=BTN,
            relief='flat', font=('Helvetica', 11),
        ).pack(side='left', padx=4)
        tk.Label(row, text='秒', fg=TEXT, bg=PANEL, font=('Helvetica', 10)).pack(side='left')
        self._duration.trace_add('write', lambda *_: self._save_if_valid())

    def _build_controls(self) -> None:
        f = tk.Frame(self, bg=BG, pady=8)
        f.pack()
        self._start_btn = tk.Button(
            f, text='START', bg=ACCENT, fg='white',
            font=('Helvetica', 13, 'bold'), padx=28, pady=7, relief='flat',
            activebackground='#C73652', activeforeground='white',
            cursor='hand2', command=self._on_start,
        )
        self._start_btn.pack(side='left', padx=10)
        self._stop_btn = tk.Button(
            f, text='STOP', bg=STOP_COLOR, fg=TEXT,
            font=('Helvetica', 13, 'bold'), padx=28, pady=7, relief='flat',
            activebackground='#6A6A8A', activeforeground='white',
            cursor='hand2', command=self._on_stop, state='disabled',
        )
        self._stop_btn.pack(side='left', padx=10)

    def _build_status(self) -> None:
        f = tk.Frame(self, bg=PANEL, pady=8)
        f.pack(fill='x', padx=10)
        self._status = tk.StringVar(value='待機中')
        tk.Label(f, textvariable=self._status, fg=TEXT, bg=PANEL,
                 font=('Helvetica', 10), wraplength=400, justify='center').pack()

    def _build_footer(self) -> None:
        tk.Label(
            self, text='緊急停止: マウスを画面左上コーナーへ移動',
            fg='#666688', bg=BG, font=('Helvetica', 9),
        ).pack(pady=5)

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
            self.after(0, lambda i=i: self._status.set(f'{label} を{i}秒後に取得します… マウスを移動してください'))
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
