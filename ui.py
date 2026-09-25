import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

import settings
import updater
from controller import Controller
from titlebar import TitleBarThemeHelper


VERSION = '1.13.3'

# フォントサイズ (役割ごとに統一する。8pt は小さすぎるため使わない)
FONT_SM = 9   # 補助的なラベル・ボタン
FONT_MD = 10  # チェックボックス・入力欄・ステータス表示

THEMES: dict = {
    'light': {
        'BG':       '#F5F5F5',
        'TEXT':     '#222222',
        'MUTED':    '#5F5F5F',
        'ENTRY_BG': '#FFFFFF',
        'BTN_BG':   '#E8E8E8',
        'BORDER':   '#CCCCCC',
        'WARN_BG':  '#F8D7DA',
        # タイトルバー (アクセントカラー導入時はここだけ差し替えればよい)
        'CAPTION':      '#F5F5F5',
        'CAPTION_TEXT': '#222222',
    },
    'dark': {
        'BG':       '#1E1E1E',
        'TEXT':     '#D4D4D4',
        'MUTED':    '#9E9E9E',
        'ENTRY_BG': '#2D2D2D',
        'BTN_BG':   '#3C3C3C',
        'BORDER':   '#444444',
        'WARN_BG':  '#5C2626',
        'CAPTION':      '#1E1E1E',
        'CAPTION_TEXT': '#D4D4D4',
    },
}


def _res(name: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, name)
    return name


def _load_tray_image(running: bool):
    import PIL.BmpImagePlugin  # noqa: F401  pystray HICON 生成に必要
    img = Image.open(_res('icon.png')).convert('RGBA')
    img = img.resize((64, 64), Image.LANCZOS)
    if not running:
        pixels = img.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b, a = pixels[x, y]
                if a > 100:
                    gray = int(r * 0.299 + g * 0.587 + b * 0.114)
                    pixels[x, y] = (gray, gray, gray, a)
    return img


class _Toggle(tk.Canvas):
    # 基準サイズ (DPI スケールを掛けてインスタンス属性として保持する)
    W, H = 200, 72
    R = 36
    S = 4
    ANIM_MS = 16
    ANIM_EASE = 0.22

    OFF_BG = (158, 158, 158)
    ON_BG  = (76, 175, 80)
    OFF_E  = (110, 110, 110)
    ON_E   = (50, 130, 55)

    _font_cache = None

    def __init__(self, parent, command=None, scale: float = 1.0):
        # DPI に追従させるため、クラス既定値をスケールしてインスタンス属性にする
        self.W = max(1, round(_Toggle.W * scale))
        self.H = max(1, round(_Toggle.H * scale))
        self.R = max(1, round(_Toggle.R * scale))
        super().__init__(parent, width=self.W, height=self.H,
                         bd=0, highlightthickness=0, cursor='hand2')
        self._on = False
        self._pos = 0.0
        self._cmd = command
        self._anim_id: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.bind('<Button-1>', lambda _: self._click())
        self._redraw()

    @classmethod
    def _font(cls):
        if cls._font_cache is not None:
            return cls._font_cache
        size = 14 * cls.S
        for name in ('arialbd.ttf', 'segoeuib.ttf', 'DejaVuSans-Bold.ttf'):
            try:
                cls._font_cache = ImageFont.truetype(name, size)
                return cls._font_cache
            except OSError:
                pass
        cls._font_cache = ImageFont.load_default()
        return cls._font_cache

    def _click(self) -> None:
        self._on = not self._on
        if self._cmd:
            self._cmd(self._on)
        self._animate()

    def set_state(self, on: bool) -> None:
        if self._on != on:
            self._on = on
            self._animate()

    def configure_bg(self, bg: str) -> None:
        self.config(bg=bg)
        self._redraw()

    def _animate(self) -> None:
        if self._anim_id is not None:
            self.after_cancel(self._anim_id)
            self._anim_id = None
        self._step_anim()

    def _step_anim(self) -> None:
        target = 1.0 if self._on else 0.0
        diff = target - self._pos
        if abs(diff) < 0.005:
            self._pos = target
            self._redraw()
            self._anim_id = None
            return
        self._pos += diff * self.ANIM_EASE
        self._redraw()
        self._anim_id = self.after(self.ANIM_MS, self._step_anim)

    @staticmethod
    def _mix(c0: tuple, c1: tuple, t: float) -> tuple:
        return tuple(int(a + (b - a) * t) for a, b in zip(c0, c1))

    def _redraw(self) -> None:
        s = self.S
        W, H, R = self.W * s, self.H * s, self.R * s
        t = self._pos
        img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        bg = self._mix(self.OFF_BG, self.ON_BG, t) + (255,)
        edge = self._mix(self.OFF_E, self.ON_E, t) + (255,)

        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=bg)
        d.rounded_rectangle([s, s, W - 1 - s, H - 1 - s],
                            radius=R - s, outline=edge, width=s)

        kx = R + t * (W - 2 * R)
        ky = H / 2
        kr = R - 6 * s

        d.ellipse([kx - kr, ky - kr + 3 * s,
                   kx + kr, ky + kr + 5 * s],
                  fill=(0, 0, 0, 90))
        d.ellipse([kx - kr, ky - kr, kx + kr, ky + kr],
                  fill=(255, 255, 255, 255),
                  outline=(200, 200, 200, 255), width=s)
        d.arc([kx - kr + 4 * s, ky - kr + 4 * s,
               kx + kr - 4 * s, ky + kr - 4 * s],
              200, 320, fill=(255, 255, 255, 220), width=2 * s)

        text = 'ON' if t > 0.5 else 'OFF'
        tx = R + (W - 2 * R) * (0.25 if t > 0.5 else 0.75)
        ty = H / 2
        font = self._font()
        d.text((tx, ty + s), text, font=font, anchor='mm',
               fill=(26, 74, 31, 255) if t > 0.5 else (85, 85, 85, 255))
        d.text((tx, ty), text, font=font, anchor='mm',
               fill=(255, 255, 255, 255))

        img = img.resize((self.W, self.H), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.delete('all')
        self.create_image(0, 0, anchor='nw', image=self._photo)


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
        self.title(f"I'm fine  v{VERSION}")
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
        self._start_time: datetime.datetime | None = None
        self._time_invalid = False
        self._update_pending = False
        self._update_state: str | None = None
        self._update_status_override: str | None = None
        self._tray_minimize: tk.BooleanVar

        # 更新適用直前に記録された ON 状態を、起動時に一度だけ復元するためのフラグ。
        # 復元するかどうかに関わらず、フラグの立ちっぱなしを防ぐため必ずクリアする。
        self._resume_after_update = bool(self._cfg.get('resume_after_update'))
        if self._cfg.get('resume_after_update'):
            self._cfg = settings.update(resume_after_update=False)

        self._tw: dict[str, list] = {
            'bg_frames': [],
            'labels':    [],
            'muted':     [],
            'spinboxes': [],
            'borders':   [],
            'btns':      [],
            'checks':    [],
            'radios':    [],
        }
        self._settings_win: tk.Toplevel | None = None
        self._settings_tw: dict[str, list] = {
            'bg_frames': [],
            'labels':    [],
            'muted':     [],
            'spinboxes': [],
            'borders':   [],
            'btns':      [],
            'checks':    [],
            'radios':    [],
        }

        self._build()
        self._apply_theme()

        self._loading = True
        self._load_settings()
        self._loading = False

        self.update_idletasks()
        self.geometry(f'{int(260 * self._scale)}x{self.winfo_reqheight()}')
        self._restore_position()

        self._ctrl = Controller()

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Unmap>', self._on_unmap)
        self.after(1000, self._check_stop_timer)

        if self._cfg.get('auto_on') or self._resume_after_update:
            self.after(300, self._on_start)

        self.after(3000, self._check_for_updates)

        # 「起動時にタスクトレイへ格納」が有効なら、レイアウト確定後に格納する。
        if self._cfg.get('start_in_tray'):
            self.update_idletasks()
            self.after(200, self._minimize_to_tray)

    # ── layout ────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._init_option_vars()
        self._build_header()
        self._build_stop_timer()
        self._build_separator()
        self._build_controls()

    def _build_header(self) -> None:
        f = tk.Frame(self)
        f.pack(fill='x', padx=12, pady=(6, 2))
        self._tw['bg_frames'].append(f)

        lbl = tk.Label(f, text='停止時刻', font=('Helvetica', FONT_SM))
        lbl.pack(side='left')
        self._tw['muted'].append(lbl)

        self._settings_btn = tk.Button(
            f, text='設定',
            font=('Helvetica', FONT_SM),
            relief='solid', bd=1, padx=8, pady=2,
            cursor='hand2', command=self._open_settings,
            highlightthickness=0,
        )
        self._settings_btn.pack(side='right')
        self._tw['btns'].append(self._settings_btn)

    def _build_stop_timer(self) -> None:
        outer = tk.Frame(self)
        outer.pack(fill='x', padx=12, pady=2)
        self._tw['bg_frames'].append(outer)

        self._stop_timer_enabled = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(
            outer, variable=self._stop_timer_enabled,
            text='有効', font=('Helvetica', FONT_MD),
            highlightthickness=0,
        )
        cb.pack(side='left')
        self._tw['checks'].append(cb)

        self._stop_hour = tk.StringVar(value='17')
        self._stop_min  = tk.StringVar(value='00')

        self._stop_hour_sp = tk.Spinbox(
            outer, from_=0, to=23, increment=1,
            textvariable=self._stop_hour, width=4,
            relief='solid', bd=1, font=('Helvetica', FONT_MD),
            highlightthickness=0,
        )
        self._stop_hour_sp.pack(side='left', padx=(8, 2))
        self._tw['spinboxes'].append(self._stop_hour_sp)

        colon = tk.Label(outer, text=':', font=('Helvetica', FONT_MD))
        colon.pack(side='left')
        self._tw['labels'].append(colon)

        self._stop_min_sp = tk.Spinbox(
            outer, from_=0, to=59, increment=1,
            textvariable=self._stop_min, width=4,
            relief='solid', bd=1, font=('Helvetica', FONT_MD),
            highlightthickness=0,
        )
        self._stop_min_sp.pack(side='left', padx=(2, 0))
        self._tw['spinboxes'].append(self._stop_min_sp)

        self._stop_hour.trace_add(
            'write', lambda *_: self._fmt_time_and_save(self._stop_hour, 23))
        self._stop_min.trace_add(
            'write', lambda *_: self._fmt_time_and_save(self._stop_min, 59))
        self._stop_timer_enabled.trace_add('write', lambda *_: self._save_if_valid())

    def _build_separator(self) -> None:
        sep = tk.Frame(self, height=1)
        sep.pack(fill='x', padx=12, pady=(4, 4))
        self._tw['borders'].append(sep)

    def _build_controls(self) -> None:
        f = tk.Frame(self)
        f.pack(pady=(4, 0))
        self._tw['bg_frames'].append(f)
        self._toggle_sw = _Toggle(f, command=self._on_toggle, scale=self._scale)
        self._toggle_sw.pack()
        # 動作状態はこのアプリの最重要情報のため、視認性の低い muted 色ではなく
        # 通常の TEXT 色を使うグループに入れる。
        # 文言が伸びてもウィンドウ幅からはみ出さないよう折り返し、
        # 折り返しで行数が変わってもウィンドウ高さがずれないよう
        # 高さを常に2行分に固定する。
        self._status_lbl = tk.Label(
            f, text='停止中', font=('Helvetica', FONT_MD),
            wraplength=int(230 * self._scale), justify='center',
            height=2,
        )
        self._status_lbl.pack(pady=(4, 8))
        self._tw['labels'].append(self._status_lbl)

    def _init_option_vars(self) -> None:
        """設定ウィンドウで使う BooleanVar 類をメイン画面の構築時に用意する。

        変数自体はウィンドウの開閉と無関係に生き続ける必要があるため、
        設定ウィンドウを開くたびに作り直すのではなくここで一度だけ作る。
        """
        self._tray_minimize = tk.BooleanVar(value=True)
        self._auto_on = tk.BooleanVar(value=False)
        self._startup = tk.BooleanVar(value=False)
        self._start_in_tray = tk.BooleanVar(value=False)
        self._auto_update_enabled = tk.BooleanVar(value=True)

    # ── settings window ──────────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return

        win = tk.Toplevel(self)
        self._settings_win = win
        win.title('設定')
        win.resizable(False, False)
        win.transient(self)
        try:
            win.iconbitmap(_res('icon.ico'))
        except Exception:
            pass

        self._settings_tw = {
            'bg_frames': [], 'labels': [], 'muted': [], 'spinboxes': [],
            'borders': [], 'btns': [], 'checks': [], 'radios': [],
        }
        self._theme_var = tk.StringVar(value='dark' if self._dark else 'light')

        self._build_settings_content(win)

        win.update_idletasks()
        x = self.winfo_x() + self.winfo_width() + 10
        y = self.winfo_y()
        win.geometry(f'+{x}+{y}')

        win.protocol('WM_DELETE_WINDOW', self._close_settings_window)
        self._apply_theme()
        win.lift()
        win.focus_force()

    def _build_settings_content(self, win: tk.Toplevel) -> None:
        tw = self._settings_tw

        def heading(parent: tk.Widget, text: str) -> None:
            lbl = tk.Label(parent, text=text, font=('Helvetica', FONT_SM))
            lbl.pack(anchor='w', pady=(0, 2))
            tw['muted'].append(lbl)

        def separator(parent: tk.Widget) -> None:
            sep = tk.Frame(parent, height=1)
            sep.pack(fill='x', pady=(8, 8))
            tw['borders'].append(sep)

        def checkbox(parent: tk.Widget, var: tk.BooleanVar, text: str, cmd) -> None:
            cb = tk.Checkbutton(
                parent, variable=var, text=text,
                font=('Helvetica', FONT_MD), command=cmd,
                highlightthickness=0,
            )
            cb.pack(anchor='w')
            tw['checks'].append(cb)

        outer = tk.Frame(win)
        outer.pack(fill='both', expand=True, padx=14, pady=12)
        tw['bg_frames'].append(outer)

        # テーマ
        heading(outer, 'テーマ')
        theme_row = tk.Frame(outer)
        theme_row.pack(fill='x')
        tw['bg_frames'].append(theme_row)
        for value, text in (('light', 'ライト'), ('dark', 'ダーク')):
            rb = tk.Radiobutton(
                theme_row, variable=self._theme_var, value=value, text=text,
                font=('Helvetica', FONT_MD),
                command=lambda: self._apply_theme_choice(self._theme_var.get()),
                highlightthickness=0,
            )
            rb.pack(side='left', padx=(0, 12))
            tw['radios'].append(rb)

        separator(outer)

        # 起動と常駐
        heading(outer, '起動と常駐')
        for var, text, cmd in (
            (self._tray_minimize, '最小化でタスクトレイ格納', self._save_if_valid),
            (self._start_in_tray, '起動時にタスクトレイへ格納', self._save_if_valid),
            (self._auto_on, '起動時に自動でON', self._save_if_valid),
            (self._startup, 'Windows起動時に起動', self._on_startup_toggle),
        ):
            checkbox(outer, var, text, cmd)

        separator(outer)

        # 更新
        heading(outer, '更新')
        checkbox(outer, self._auto_update_enabled, '自動アップデート', self._save_if_valid)
        update_btn = tk.Button(
            outer, text='今すぐ更新を確認',
            font=('Helvetica', FONT_SM),
            relief='solid', bd=1, padx=8, pady=2,
            cursor='hand2', command=lambda: self._check_for_updates(force=True),
            highlightthickness=0,
        )
        update_btn.pack(anchor='w', pady=(4, 0))
        tw['btns'].append(update_btn)

        separator(outer)

        version_lbl = tk.Label(
            outer, text=f'v{VERSION}', font=('Helvetica', FONT_SM))
        version_lbl.pack(anchor='e')
        tw['muted'].append(version_lbl)

    def _close_settings_window(self) -> None:
        win = self._settings_win
        if win is None:
            return
        self._settings_win = None
        if win.winfo_exists():
            win.destroy()

    # ── theme ─────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        t = THEMES['dark' if self._dark else 'light']
        self.configure(bg=t['BG'])
        self._apply_theme_group(self._tw, t)
        if hasattr(self, '_toggle_sw'):
            self._toggle_sw.configure_bg(t['BG'])
        self._apply_titlebar_theme()

        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.configure(bg=t['BG'])
            self._apply_theme_group(self._settings_tw, t)
            self._apply_settings_titlebar_theme()

    @staticmethod
    def _apply_theme_group(tw: dict, t: dict) -> None:
        # 設定ウィンドウが閉じられた直後など、破棄済みウィジェットへの
        # configure() で例外にならないよう、必ず winfo_exists() で確認する。
        for w in tw['bg_frames']:
            if w.winfo_exists(): w.configure(bg=t['BG'])
        for w in tw['labels']:
            if w.winfo_exists(): w.configure(bg=t['BG'], fg=t['TEXT'])
        for w in tw['muted']:
            if w.winfo_exists(): w.configure(bg=t['BG'], fg=t['MUTED'])
        for w in tw['spinboxes']:
            if not w.winfo_exists():
                continue
            # 入力が無効と判定されている間は警告色を維持し、テーマ切替で
            # 元に戻ってしまわないようにする。
            bg = t['WARN_BG'] if getattr(w, '_invalid', False) else t['ENTRY_BG']
            w.configure(bg=bg, fg=t['TEXT'],
                       buttonbackground=t['BTN_BG'],
                       insertbackground=t['TEXT'],
                       highlightbackground=t['BG'], highlightcolor=t['BG'])
        for w in tw['borders']:
            if w.winfo_exists(): w.configure(bg=t['BORDER'])
        for w in tw['btns']:
            if w.winfo_exists():
                w.configure(bg=t['BTN_BG'], fg=t['TEXT'],
                           activebackground=t['ENTRY_BG'],
                           activeforeground=t['TEXT'],
                           highlightbackground=t['BG'],
                           highlightcolor=t['BG'])
        for w in tw['checks']:
            if w.winfo_exists():
                w.configure(bg=t['BG'], fg=t['TEXT'],
                           selectcolor=t['ENTRY_BG'],
                           activebackground=t['BG'],
                           activeforeground=t['TEXT'],
                           highlightbackground=t['BG'],
                           highlightcolor=t['BG'])
        for w in tw['radios']:
            if w.winfo_exists():
                w.configure(bg=t['BG'], fg=t['TEXT'],
                           selectcolor=t['ENTRY_BG'],
                           activebackground=t['BG'],
                           activeforeground=t['TEXT'],
                           highlightbackground=t['BG'],
                           highlightcolor=t['BG'])

    def _apply_titlebar_theme(self) -> None:
        if sys.platform != 'win32':
            return
        t = THEMES['dark' if self._dark else 'light']
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
        except Exception:
            return
        TitleBarThemeHelper.apply(
            hwnd, self._dark, t['CAPTION'], t['CAPTION_TEXT'])

    def _apply_settings_titlebar_theme(self) -> None:
        if sys.platform != 'win32':
            return
        win = self._settings_win
        if win is None or not win.winfo_exists():
            return
        t = THEMES['dark' if self._dark else 'light']
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        except Exception:
            return
        TitleBarThemeHelper.apply(
            hwnd, self._dark, t['CAPTION'], t['CAPTION_TEXT'])

    def _apply_theme_choice(self, choice: str) -> None:
        """設定ウィンドウのラジオボタンから、指定されたテーマを適用する。"""
        self._dark = (choice == 'dark')
        self._apply_theme()
        # settings.update() は他のキーを一切壊さずに theme だけを更新する。
        self._cfg = settings.update(theme='dark' if self._dark else 'light')

    # ── logic ─────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        c = self._cfg
        self._stop_timer_enabled.set(bool(c.get('stop_timer_enabled', False)))
        self._stop_hour.set(f"{c.get('stop_hour', 17):02d}")
        self._stop_min.set(f"{c.get('stop_min', 0):02d}")
        self._tray_minimize.set(bool(c.get('tray_minimize', True)))
        self._auto_on.set(bool(c.get('auto_on', False)))
        self._start_in_tray.set(bool(c.get('start_in_tray', False)))
        self._auto_update_enabled.set(bool(c.get('auto_update_enabled', True)))
        self._startup.set(self._startup_registered())

    def _get_cfg(self) -> dict | None:
        """UIが管理する項目だけを現在値で上書きした設定全体を返す。

        self._cfg のコピーをベースにすることで、update_check_url や
        auto_update_enabled / resume_after_update のような UI 側で
        持っていないキーを保存のたびに消してしまわないようにする。
        """
        try:
            cfg = dict(self._cfg)
            cfg.update({
                'theme': 'dark' if self._dark else 'light',
                'stop_timer_enabled': self._stop_timer_enabled.get(),
                'stop_hour': int(self._stop_hour.get()),
                'stop_min':  int(self._stop_min.get()),
                'tray_minimize': self._tray_minimize.get(),
                'auto_on': self._auto_on.get(),
                'start_in_tray': self._start_in_tray.get(),
                'auto_update_enabled': self._auto_update_enabled.get(),
            })
            return cfg
        except (ValueError, AttributeError):
            return None

    def _save_if_valid(self) -> None:
        if self._loading:
            return
        self._check_time_validity()
        cfg = self._get_cfg()
        if cfg is not None:
            settings.save(cfg)
            self._cfg = cfg
        self._refresh_stop_target()
        self._update_status()

    def _fmt_time_and_save(self, var: tk.StringVar, maxval: int) -> None:
        if self._loading:
            return
        try:
            v = max(0, min(maxval, int(var.get())))
            fmt = f'{v:02d}'
            if var.get() != fmt:
                # Tcl の variable trace は、trace 実行中に同じ変数へ書き込んでも
                # 再入しない仕様のため、ここで set した後も自分で
                # 保存・検証まで続けて行う必要がある。
                var.set(fmt)
        except ValueError:
            pass
        self._save_if_valid()

    # ── 入力検証 ──────────────────────────────────────────────────────────

    @staticmethod
    def _time_field_valid(var: tk.StringVar, maxval: int) -> bool:
        try:
            return 0 <= int(var.get()) <= maxval
        except ValueError:
            return False

    def _mark_spinbox_invalid(self, widget: tk.Spinbox, invalid: bool) -> None:
        widget._invalid = invalid
        t = THEMES['dark' if self._dark else 'light']
        widget.configure(bg=t['WARN_BG'] if invalid else t['ENTRY_BG'])

    def _check_time_validity(self) -> None:
        hour_ok = self._time_field_valid(self._stop_hour, 23)
        min_ok = self._time_field_valid(self._stop_min, 59)
        self._mark_spinbox_invalid(self._stop_hour_sp, not hour_ok)
        self._mark_spinbox_invalid(self._stop_min_sp, not min_ok)
        self._time_invalid = not (hour_ok and min_ok)

    # ── startup / position ────────────────────────────────────────────────

    _RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
    _RUN_NAME = 'ImFine'

    @classmethod
    def _startup_registered(cls) -> bool:
        if sys.platform != 'win32':
            return False
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls._RUN_KEY) as key:
                winreg.QueryValueEx(key, cls._RUN_NAME)
                return True
        except OSError:
            return False

    def _on_startup_toggle(self) -> None:
        if sys.platform != 'win32':
            return
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._RUN_KEY,
                                0, winreg.KEY_SET_VALUE) as key:
                if self._startup.get():
                    if getattr(sys, 'frozen', False):
                        cmd = f'"{sys.executable}"'
                    else:
                        cmd = (f'"{sys.executable}"'
                               f' "{os.path.abspath(sys.argv[0])}"')
                    winreg.SetValueEx(key, self._RUN_NAME, 0,
                                      winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, self._RUN_NAME)
                    except FileNotFoundError:
                        pass
        except OSError:
            messagebox.showwarning(
                "I'm fine", 'スタートアップ登録の変更に失敗しました。', parent=self)
            self._startup.set(self._startup_registered())
        self._save_if_valid()

    def _restore_position(self) -> None:
        x, y = self._cfg.get('win_x'), self._cfg.get('win_y')
        if isinstance(x, int) and isinstance(y, int) and self._position_on_screen(x, y):
            self.geometry(f'+{x}+{y}')

    def _position_on_screen(self, x: int, y: int) -> bool:
        """保存された座標が、いずれかのモニタを含む表示可能領域に
        収まっているかを判定する。マルチモニタ環境ではサブモニタ上の
        座標 (負の x や、プライマリ画面幅を超える x) もあり得るため、
        Windows では仮想デスクトップ全体の範囲で判定する。
        取得できない場合やWindows以外では、従来通りプライマリ画面基準で判定する。
        """
        if sys.platform == 'win32':
            try:
                import ctypes
                u32 = ctypes.windll.user32
                SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
                SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
                vx = u32.GetSystemMetrics(SM_XVIRTUALSCREEN)
                vy = u32.GetSystemMetrics(SM_YVIRTUALSCREEN)
                vw = u32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
                vh = u32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
                if vw > 0 and vh > 0:
                    return (vx - 50 < x < vx + vw - 100
                            and vy - 50 < y < vy + vh - 100)
            except Exception:
                pass
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        return -50 < x < sw - 100 and 0 <= y < sh - 100

    def _save_position(self) -> None:
        try:
            x, y = self.winfo_x(), self.winfo_y()
        except Exception:
            return
        self._cfg = settings.update(win_x=x, win_y=y)

    def _refresh_stop_target(self) -> None:
        if (hasattr(self, '_ctrl')
                and self._ctrl.state == Controller.RUNNING
                and not self._stop_triggered):
            self._stop_target = self._calc_stop_target()

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
        self._check_time_validity()
        self._stop_target = self._calc_stop_target()
        if self._stop_timer_enabled.get() and self._stop_target is None:
            messagebox.showwarning(
                "I'm fine", '停止時刻が不正なため停止タイマーは動作しません。',
                parent=self)
        self._start_time = datetime.datetime.now()
        self._ctrl.start()
        self._toggle_sw.set_state(True)
        self._update_tray_icon()
        self._update_status()

    def _on_stop(self) -> None:
        self._start_time = None
        self._ctrl.stop()
        self._toggle_sw.set_state(False)
        self._update_tray_icon()
        self._update_status()

    def _update_status(self) -> None:
        if not hasattr(self, '_status_lbl'):
            return
        if self._update_status_override:
            self._status_lbl.config(text=self._update_status_override)
            return
        running = hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING
        if not running:
            if self._stop_timer_enabled.get() and self._time_invalid:
                self._status_lbl.config(text='停止時刻が不正です')
            else:
                self._status_lbl.config(text='停止中')
            return
        parts = ['動作中']
        if self._start_time is not None:
            sec = int((datetime.datetime.now()
                       - self._start_time).total_seconds())
            h, rem = divmod(sec, 3600)
            m, s = divmod(rem, 60)
            parts.append(f'{h:d}:{m:02d}:{s:02d}')
        if self._stop_timer_enabled.get():
            if self._stop_target is not None:
                parts.append(f'({self._stop_target:%H:%M} に自動停止)')
            elif self._time_invalid:
                # 動作中に停止時刻が無効化され、停止タイマーが効かなくなったことを明示する。
                parts.append('(自動停止は無効)')
        self._status_lbl.config(text=' '.join(parts))

    def _check_stop_timer(self) -> None:
        if self._update_pending:
            self._perform_update_shutdown()
            return
        if self._update_state is not None:
            state, self._update_state = self._update_state, None
            self._apply_update_state(state)
        if (self._stop_timer_enabled.get()
                and not self._stop_triggered
                and hasattr(self, '_ctrl')
                and self._ctrl.state == Controller.RUNNING
                and self._stop_target is not None):
            if datetime.datetime.now() >= self._stop_target:
                self._stop_triggered = True
                self._on_stop()
                if self._tray_icon is not None:
                    try:
                        self._tray_icon.notify('停止時刻になったため停止しました')
                    except Exception:
                        pass
        self._update_status()
        self.after(1000, self._check_stop_timer)

    # ── auto update ───────────────────────────────────────────────────────

    def _check_for_updates(self, force: bool = False) -> None:
        if not getattr(sys, 'frozen', False):
            return  # ソースから実行時は自己置き換えできないので対象外
        if not force and not self._auto_update_enabled.get():
            return
        updater.check_and_apply_async(
            VERSION, self._cfg.get('update_check_url'),
            on_state=self._on_update_state,
            on_ready_to_restart=self._on_update_ready)

    def _on_update_state(self, state: str) -> None:
        # updater のバックグラウンドスレッドから呼ばれるため、Tk の操作は
        # 一切行わずフラグに格納するだけにする。実際の反映は
        # _check_stop_timer (メインスレッド、1秒ごと) 側で行う。
        self._update_state = state

    def _apply_update_state(self, state: str) -> None:
        messages = {
            'downloading': '更新をダウンロード中…',
            'applying': '更新を適用しています…',
        }
        msg = messages.get(state)
        # 'checking' はすぐ終わるうえ毎起動出るとうるさいので表示しない。
        # 'up_to_date' / 'failed' も、失敗を毎回出すとうるさいため通常表示に戻すだけにする。
        self._update_status_override = msg
        if msg is not None and self._tray_icon is not None:
            try:
                self._tray_icon.notify(msg)
            except Exception:
                pass

    def _on_update_ready(self) -> None:
        # updater のバックグラウンドスレッドから呼ばれるため、
        # Tk の操作は必ず _check_stop_timer (メインスレッド) 側で行う。
        self._update_pending = True

    def _perform_update_shutdown(self) -> None:
        # ユーザーがONにしてトレイに格納していた場合、更新後に黙ってOFFへ
        # 戻ってしまうと (モニタが消える・在席状態が誤表示される等)
        # アプリの存在意義に関わる事故になるため、適用直前のON/OFF状態を
        # 必ず記録してから終了する。
        self._close_settings_window()
        running = hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING
        self._cfg = settings.update(resume_after_update=running)
        self._save_position()
        icon_ref = self._tray_icon
        self._tray_icon = None
        self._stop_tray_icon(icon_ref)
        if hasattr(self, '_ctrl'):
            self._ctrl.stop()
        self.destroy()

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
        # 常駐ツールとしては × = トレイ格納が一般的。動作を止めるわけではないので
        # 確認は不要 (終了はトレイメニューの「終了」から行う)。
        if self._tray_minimize.get():
            self._minimize_to_tray()
            return
        if hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING:
            if not messagebox.askyesno(
                    "I'm fine", '動作中です。終了しますか？', parent=self):
                return
        self._close_settings_window()
        self._save_position()
        icon_ref = self._tray_icon
        self._tray_icon = None
        self._stop_tray_icon(icon_ref)
        if hasattr(self, '_ctrl'):
            self._ctrl.stop()
        self.destroy()

    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget is self and not self._going_to_tray:
            self.after(50, self._check_iconify)

    def _check_iconify(self) -> None:
        # destroy() 後にもこの after コールバックが発火しうるため、
        # ウィンドウが既に無い場合や wm_state() が例外を投げる場合は無視する。
        if not self.winfo_exists():
            return
        try:
            state = self.wm_state()
        except tk.TclError:
            return
        if state == 'iconic' and self._tray_minimize.get():
            self._minimize_to_tray()

    def _minimize_to_tray(self) -> None:
        # メインが隠れているのに設定ウィンドウだけ浮いている状態を避ける。
        self._close_settings_window()
        try:
            import pystray
            import pystray._win32
        except ImportError:
            return
        self._save_position()
        if self._tray_icon is not None:
            self._going_to_tray = True
            self.withdraw()
            self._going_to_tray = False
            return

        _WM_LBUTTONUP     = 0x0202
        _WM_LBUTTONDBLCLK = 0x0203

        class _TrayIcon(pystray._win32.Icon):
            def __init__(self, *args, on_left_click=None, on_left_dblclick=None, **kwargs):
                super().__init__(*args, **kwargs)
                self._left_click_cb    = on_left_click
                self._left_dblclick_cb = on_left_dblclick
                self._click_timer      = None
                self._ignore_next_up   = False

            def cancel_click_timer(self):
                if self._click_timer is not None:
                    self._click_timer.cancel()
                    self._click_timer = None

            def _on_notify(self, wparam, lparam):
                if lparam == _WM_LBUTTONDBLCLK:
                    self.cancel_click_timer()
                    self._ignore_next_up = True
                    if self._left_dblclick_cb:
                        self._left_dblclick_cb()
                elif lparam == _WM_LBUTTONUP:
                    if self._ignore_next_up:
                        self._ignore_next_up = False
                        return
                    if self._left_click_cb:
                        import ctypes
                        delay = ctypes.windll.user32.GetDoubleClickTime() / 1000.0
                        self.cancel_click_timer()
                        self._click_timer = threading.Timer(delay, self._fire_click)
                        self._click_timer.start()
                    else:
                        super()._on_notify(wparam, lparam)
                else:
                    super()._on_notify(wparam, lparam)

            def _fire_click(self):
                self._click_timer = None
                if self._left_click_cb:
                    try:
                        self._left_click_cb()
                    except Exception:
                        pass

        running = hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING
        try:
            img = _load_tray_image(running)
        except Exception:
            img = Image.new('RGB', (64, 64),
                            '#4CAF50' if running else '#9E9E9E')
        menu = pystray.Menu(
            pystray.MenuItem('タスクトレイから出す',
                             self._tray_restore, default=True),
            pystray.MenuItem('更新を確認', self._tray_check_update),
            pystray.MenuItem('終了', self._tray_quit),
        )
        try:
            self._tray_icon = _TrayIcon(
                "I'm fine", img, "I'm fine", menu,
                on_left_click=lambda: self.after(0, self._tray_toggle),
                on_left_dblclick=lambda: self.after(0, self._tray_restore),
            )
            self._tray_icon.run_detached()
            self._tray_icon.visible = True
        except Exception:
            self._tray_icon = None
            return
        self._going_to_tray = True
        self.withdraw()
        self._going_to_tray = False

    def _tray_toggle(self) -> None:
        if hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING:
            self._on_stop()
            msg = '停止しました'
        else:
            self._on_start()
            msg = '開始しました'
        if self._tray_icon is not None:
            try:
                self._tray_icon.notify(msg)
            except Exception:
                pass

    @staticmethod
    def _stop_tray_icon(icon_ref) -> None:
        if icon_ref is None:
            return
        if hasattr(icon_ref, 'cancel_click_timer'):
            icon_ref.cancel_click_timer()
        icon_ref.stop()

    def _tray_restore(self, icon=None, item=None) -> None:
        icon_ref = self._tray_icon
        self._tray_icon = None
        self._stop_tray_icon(icon_ref)
        self.after(0, self.deiconify)
        self.after(0, self._apply_titlebar_theme)

    def _tray_check_update(self, icon=None, item=None) -> None:
        # auto_update_enabled の値に関わらず、手動要求は即座にチェックする。
        self.after(0, lambda: self._check_for_updates(force=True))

    def _tray_quit(self, icon=None, item=None) -> None:
        self.after(0, self._confirm_tray_quit)

    def _confirm_tray_quit(self) -> None:
        if hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING:
            if not messagebox.askyesno(
                    "I'm fine", '動作中です。終了しますか？', parent=self):
                return
        self._close_settings_window()
        self._save_position()
        icon_ref = self._tray_icon
        self._tray_icon = None
        self._stop_tray_icon(icon_ref)
        if hasattr(self, '_ctrl'):
            self._ctrl.stop()
        self.destroy()
