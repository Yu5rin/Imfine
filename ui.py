import datetime
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

import applog
import instance
import settings
import startup
import stoptimer
import theme
import tray
import updater
from controller import Controller
from theme import THEMES
from titlebar import TitleBarThemeHelper


VERSION = '1.16.0'

APP_NAME = "I'm fine"

# フォントの大きさ (pt)。役割ごとにここだけで決める。
FONT_HEADING = 9   # 見出し (太字)
FONT_BODY = 10     # 本文・チェックボックス・入力欄
FONT_STATUS = 12   # 状態表示 (太字)
FONT_SMALL = 9     # 補足・バージョン・ボタン

# メイン画面の幅 (96 DPI のときの px)
MAIN_WIDTH = 300

# 設定「Windows に合わせる」のとき、Windows のテーマを読み直す間隔 (秒)
SYSTEM_THEME_POLL_SEC = 3

# トレイ・更新・二重起動の合図を取り出す間隔 (ミリ秒)
PUMP_MS = 100

TRAY_HINT = 'タスクトレイで動作しています。アイコンを右クリックするとメニューが開きます'


def _res(name: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)


def _load_tray_image(running: bool):
    """トレイアイコンの絵。ON はチェック、OFF は一時停止の二本線 (色だけでなく形でも区別する)。"""
    import PIL.BmpImagePlugin  # noqa: F401  pystray の HICON 生成に必要
    name = 'icon.png' if running else 'icon_off.png'
    try:
        img = Image.open(_res(name)).convert('RGBA')
    except OSError:
        img = Image.new('RGBA', (64, 64), '#2E7D32' if running else '#6B7280')
    return img.resize((64, 64), Image.LANCZOS)


def _pick_font_family(root: tk.Misc) -> str:
    """UI のフォント。Windows は Yu Gothic UI、無ければ Meiryo UI。それ以外の OS は既定の UI フォント。"""
    if sys.platform == 'win32':
        try:
            families = set(tkfont.families(root))
        except tk.TclError:
            families = set()
        for name in ('Yu Gothic UI', 'Meiryo UI'):
            if name in families:
                return name
    try:
        return tkfont.nametofont('TkDefaultFont', root).actual('family')
    except (tk.TclError, RuntimeError):
        return 'TkDefaultFont'


def _open_path(path: str) -> bool:
    """フォルダやファイルを既定のアプリで開く。"""
    try:
        if sys.platform == 'win32':
            os.startfile(path)  # noqa: S606  利用者のデータフォルダを開くだけ
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _rgb(color: str) -> tuple:
    return theme.hex_to_rgb(color)


class _Toggle(tk.Canvas):
    """ON/OFF のトグル。クリック・Space・Enter で切り替える。"""

    # 基準の大きさ (96 DPI のときの px)。描くときに scale を掛ける。
    W, H = 200, 64
    MARGIN = 4      # フォーカスの枠を描くための余白
    S = 4           # なめらかに描くための拡大率 (描いてから縮小する)
    ANIM_MS = 16
    ANIM_EASE = 0.22

    _font_cache: dict = {}

    def __init__(self, parent, command=None, scale: float = 1.0):
        self._scale = scale
        self.W = max(1, round(_Toggle.W * scale))
        self.H = max(1, round(_Toggle.H * scale))
        self.M = max(2, round(_Toggle.MARGIN * scale))
        super().__init__(parent, width=self.W + 2 * self.M, height=self.H + 2 * self.M,
                         bd=0, highlightthickness=0, cursor='hand2', takefocus=1)
        self._on = False
        self._pos = 0.0
        self._cmd = command
        self._focused = False
        self._colors = {'on': '#2E7D32', 'off': '#6B7280', 'focus': '#1B1B1B'}
        self._anim_id: str | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self.bind('<Button-1>', lambda _: self._click())
        self.bind('<space>', lambda _: self._click())
        self.bind('<Return>', lambda _: self._click())
        self.bind('<FocusIn>', lambda _: self._set_focus(True))
        self.bind('<FocusOut>', lambda _: self._set_focus(False))
        self._redraw()

    @classmethod
    def _font(cls, size: int):
        if size in cls._font_cache:
            return cls._font_cache[size]
        font = None
        for name in ('segoeuib.ttf', 'arialbd.ttf', 'DejaVuSans-Bold.ttf'):
            try:
                font = ImageFont.truetype(name, size)
                break
            except OSError:
                pass
        if font is None:
            font = ImageFont.load_default()
        cls._font_cache[size] = font
        return font

    def _set_focus(self, focused: bool) -> None:
        self._focused = focused
        self._redraw()

    def _click(self) -> None:
        self._on = not self._on
        self._animate()
        if self._cmd:
            self._cmd(self._on)

    @property
    def on(self) -> bool:
        return self._on

    def set_state(self, on: bool) -> None:
        if self._on != on:
            self._on = on
            self._animate()

    def set_colors(self, bg: str, on: str, off: str, focus: str) -> None:
        self.config(bg=bg)
        self._colors = {'on': on, 'off': off, 'focus': focus}
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
        s, sc = self.S, self._scale
        M = self.M * s
        W, H = self.W * s, self.H * s
        R = H // 2
        t = self._pos
        img = Image.new('RGBA', (W + 2 * M, H + 2 * M), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        if self._focused:
            ring = max(1, round(2 * sc)) * s
            d.rounded_rectangle([0, 0, W + 2 * M - 1, H + 2 * M - 1],
                                radius=R + M, outline=_rgb(self._colors['focus']) + (255,),
                                width=ring)

        bg = self._mix(_rgb(self._colors['off']), _rgb(self._colors['on']), t) + (255,)
        d.rounded_rectangle([M, M, M + W - 1, M + H - 1], radius=R, fill=bg)

        pad = round(6 * sc) * s
        kr = R - pad
        kx = M + R + t * (W - 2 * R)
        ky = M + H / 2
        shadow = max(1, round(2 * sc)) * s
        d.ellipse([kx - kr, ky - kr + shadow, kx + kr, ky + kr + shadow],
                  fill=(0, 0, 0, 60))
        d.ellipse([kx - kr, ky - kr, kx + kr, ky + kr], fill=(255, 255, 255, 255))

        text = 'ON' if t > 0.5 else 'OFF'
        # 文字はつまみと反対側の、つまみを除いた領域の中央に置く
        if t > 0.5:
            tx = M + (W - 2 * kr - pad) / 2
        else:
            tx = M + W - (W - 2 * kr - pad) / 2
        font = self._font(round(18 * sc) * s)
        d.text((tx, ky), text, font=font, anchor='mm', fill=(255, 255, 255, 255))

        img = img.resize((self.W + 2 * self.M, self.H + 2 * self.M), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img, master=self)
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

    def __init__(self, show_event=None) -> None:
        super().__init__()
        # 「起動時はトレイに格納する」でもウィンドウが一瞬出ないよう、組み立て前に隠す
        self.withdraw()

        dpi = self._get_system_dpi()
        self.tk.call('tk', 'scaling', dpi / 72.0)
        self._scale = dpi / 96.0
        self._ff = _pick_font_family(self)
        self.title(APP_NAME)
        self.resizable(False, False)
        try:
            self.iconbitmap(_res('icon.ico'))
        except Exception:
            pass
        try:
            img = tk.PhotoImage(file=_res('icon.png'), master=self)
            self.iconphoto(True, img)
            self._icon_img = img
        except Exception:
            pass

        self._closing = False
        self._loading = False
        self._modal = 0                       # 表示中のダイアログの数 (更新の適用を待つため)
        self._cmds: queue.Queue = queue.Queue()  # 別スレッドからの命令 (トレイ・更新)
        self._show_event = show_event
        self._going_to_tray = False
        self._themed: list = []               # (ウィジェット, 役割) テーマを当てる対象
        self._settings_win: tk.Toplevel | None = None
        self._update_btn: tk.Button | None = None
        self._update_lbl: tk.Label | None = None

        self._ctrl = Controller()
        self._start_time: datetime.datetime | None = None
        self._stop_target: datetime.datetime | None = None
        self._auto_stopped_at: datetime.datetime | None = None

        # 更新の状態
        self._update_busy = False
        self._update_manual = False           # 手動で確認したか (結果を知らせる)
        self._update_from_tray = False        # トレイから手動で確認したか (結果を通知する)
        self._update_note: str | None = None  # メイン画面の補足行に出す更新の状態
        self._update_label_text = ''          # 設定ウィンドウの「今すぐ確認」の横に出す文言
        self._update_ready: dict | None = None  # ダウンロード・検証済みで適用を待っている更新
        self._next_update_check = time.time() + updater.RUNTIME_CHECK_INTERVAL_SEC

        self._cfg = settings.load()
        self._theme_choice = self._cfg.get('theme', 'system')
        self._dark = theme.resolve_dark(self._theme_choice)
        self._last_theme_poll = time.monotonic()

        # 更新して再起動した直後の引き継ぎ。フラグの立ちっぱなしを防ぐため、読んだら必ず消す。
        cfg = self._cfg
        just_updated = bool(cfg.get('just_updated'))
        resume = {
            'running': bool(cfg.get('resume_after_update')),
            'in_tray': bool(cfg.get('resume_in_tray')),
            'stop_target': cfg.get('resume_stop_target'),
            'start_time': cfg.get('resume_start_time'),
        }
        if (just_updated or resume['running'] or resume['in_tray']
                or resume['stop_target'] or resume['start_time']):
            self._cfg = settings.update(
                just_updated=False, resume_after_update=False, resume_in_tray=False,
                resume_stop_target=None, resume_start_time=None)

        self._build()
        self._loading = True
        self._load_settings()
        self._loading = False
        self._apply_theme()

        self.update_idletasks()
        width = max(self._px(MAIN_WIDTH), self.winfo_reqwidth())
        self.geometry(f'{width}x{self.winfo_reqheight()}')
        self._restore_position()

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.bind('<Unmap>', self._on_unmap)

        # トレイアイコンは起動から終了まで出したままにする
        self._tray = tray.Tray(self._post_tray, VERSION, _load_tray_image)
        running, stop_label, title = self._tray_state()
        tray_ok = self._tray.start(running, stop_label, title)
        if not tray_ok:
            applog.write('タスクトレイを使えないため、トレイに格納せずに動作する')

        # 起動時に ON にするか
        if just_updated or resume['running']:
            if resume['running']:
                decision = stoptimer.resume_decision(
                    datetime.datetime.now(), resume['stop_target'], resume['start_time'])
                if decision['start']:
                    self._start(start_time=decision['start_time'],
                                stop_target=decision['stop_target'])
                else:
                    # 再起動が停止時刻をまたいだ: その日の自動停止として扱う
                    self._auto_stopped_at = decision['stopped_at']
                    self._tray.notify(stoptimer.stopped_note(decision['stopped_at']))
        elif self._cfg.get('auto_on'):
            self._start()

        # ウィンドウを出すか、トレイに格納したままにするか
        in_tray = (self._cfg.get('start_in_tray') or resume['in_tray']) and tray_ok
        if in_tray:
            self._show_tray_hint_once()
        else:
            self._show_window()

        if just_updated:
            self._tray.notify(f'v{VERSION} に更新しました')

        self._refresh_view()
        self.after(PUMP_MS, self._pump)
        self.after(1000, self._tick)
        self.after(3000, self._check_for_updates)

    # ── 共通 ─────────────────────────────────────────────────────────────

    def _px(self, n: float) -> int:
        """96 DPI のときの px を、今の DPI の px にする。"""
        return round(n * self._scale)

    def _font(self, size: int, bold: bool = False) -> tuple:
        return (self._ff, size, 'bold') if bold else (self._ff, size)

    def _t(self) -> dict:
        return THEMES['dark' if self._dark else 'light']

    def _running(self) -> bool:
        return self._ctrl.state == Controller.RUNNING

    def report_callback_exception(self, exc, val, tb) -> None:
        """Tk のコールバック内の想定外の例外を app.log に残す (落とさない)。"""
        applog.log_exception(exc, val, tb, '画面の処理')

    def _reg(self, widget: tk.Widget, role: str) -> tk.Widget:
        self._themed.append((widget, role))
        return widget

    def _dialog(self, fn, *args, **kwargs):
        """messagebox を出す。表示中は更新の適用を待つ。"""
        self._modal += 1
        try:
            return fn(*args, **kwargs)
        finally:
            self._modal -= 1

    def _button(self, parent, text: str, command, on_surface: bool = False) -> tk.Button:
        """平らなボタン (背景色だけで、ホバーで色が変わる)。"""
        b = tk.Button(parent, text=text, command=command,
                      font=self._font(FONT_SMALL), relief='flat', bd=0,
                      padx=self._px(12), pady=self._px(4), cursor='hand2',
                      highlightthickness=1, takefocus=1)
        b._on_surface = on_surface

        def enter(_):
            if str(b['state']) != 'disabled':
                b.configure(bg=self._t()['BTN_HOVER'])

        def leave(_):
            b.configure(bg=self._t()['BTN_BG'])

        b.bind('<Enter>', enter)
        b.bind('<Leave>', leave)
        return self._reg(b, 'button')

    # ── 画面の組み立て ────────────────────────────────────────────────────

    def _build(self) -> None:
        self._init_vars()
        px = self._px
        outer = self._reg(tk.Frame(self), 'bg')
        outer.pack(fill='both', expand=True, padx=px(16), pady=px(16))

        self._toggle_sw = _Toggle(outer, command=self._on_toggle, scale=self._scale)
        self._toggle_sw.pack()
        self._reg(self._toggle_sw, 'toggle')

        # 状態 (ON/OFF と経過時間)
        self._state_lbl = self._reg(
            tk.Label(outer, text='OFF', font=self._font(FONT_STATUS, bold=True)), 'state')
        self._state_lbl.pack(pady=(px(8), 0))

        # 補足 (いつ自動で OFF にするか、など)。文言が変わっても高さがずれないよう1行に固定する
        self._note_lbl = self._reg(
            tk.Label(outer, text='', font=self._font(FONT_SMALL),
                     wraplength=px(MAIN_WIDTH - 32), justify='center'), 'muted_bg')
        self._note_lbl.pack(pady=(px(2), 0))

        # 停止時刻のカード
        card = self._reg(tk.Frame(outer, highlightthickness=1, bd=0), 'card')
        card.pack(fill='x', pady=(px(12), 0))
        inner = self._reg(tk.Frame(card), 'surface')
        inner.pack(fill='x', padx=px(12), pady=px(10))

        cb = self._reg(tk.Checkbutton(
            inner, variable=self._stop_timer_enabled,
            text='決まった時刻に自動で OFF にする', font=self._font(FONT_BODY),
            command=self._on_timer_toggle, anchor='w', highlightthickness=1,
            takefocus=1), 'check')
        cb.pack(fill='x')

        row = self._reg(tk.Frame(inner), 'surface')
        row.pack(anchor='w', padx=(px(24), 0), pady=(px(6), 0))
        vcmd = (self.register(stoptimer.is_time_input_allowed), '%P')
        self._stop_hour_sp = self._time_spinbox(row, self._stop_hour, 23, vcmd)
        self._stop_hour_sp.pack(side='left')
        colon = self._reg(tk.Label(row, text=':', font=self._font(FONT_BODY)), 'text_surface')
        colon.pack(side='left', padx=px(4))
        self._stop_min_sp = self._time_spinbox(row, self._stop_min, 59, vcmd)
        self._stop_min_sp.pack(side='left')

        # 下の段: バージョン (左) と設定ボタン (右)
        bottom = self._reg(tk.Frame(outer), 'bg')
        bottom.pack(fill='x', pady=(px(12), 0))
        ver = self._reg(tk.Label(bottom, text=f'v{VERSION}', font=self._font(FONT_SMALL)),
                        'muted_bg')
        ver.pack(side='left', anchor='s')
        self._settings_btn = self._button(bottom, '設定', self._open_settings)
        self._settings_btn.pack(side='right')

    def _time_spinbox(self, parent, var: tk.StringVar, maxval: int, vcmd) -> tk.Spinbox:
        sp = tk.Spinbox(
            parent, from_=0, to=maxval, increment=1, wrap=True, format='%02.0f',
            textvariable=var, width=3, justify='center',
            font=self._font(FONT_BODY), relief='flat', bd=0,
            highlightthickness=1, validate='key', validatecommand=vcmd,
            command=self._commit_time)
        sp._invalid = False
        # 入力中は整形しない。確定 (フォーカスが外れた・Enter) で丸めて2桁にして保存する
        sp.bind('<FocusOut>', lambda _: self._commit_time())
        sp.bind('<Return>', lambda _: self._commit_time())
        return self._reg(sp, 'spin')

    def _init_vars(self) -> None:
        """画面と設定ウィンドウで使う変数。ウィンドウの開閉と関係なく生き続ける。"""
        self._stop_timer_enabled = tk.BooleanVar(value=False)
        self._stop_hour = tk.StringVar(value='17')
        self._stop_min = tk.StringVar(value='00')
        self._stop_hour.trace_add('write', lambda *_: self._on_time_edit())
        self._stop_min.trace_add('write', lambda *_: self._on_time_edit())
        self._startup = tk.BooleanVar(value=False)
        self._auto_on = tk.BooleanVar(value=False)
        self._start_in_tray = tk.BooleanVar(value=False)
        self._minimize_to_tray = tk.BooleanVar(value=True)
        self._close_to_tray = tk.BooleanVar(value=True)
        self._notify_toggle = tk.BooleanVar(value=False)
        self._auto_update_enabled = tk.BooleanVar(value=True)
        self._theme_var = tk.StringVar(value='system')

    # ── 設定ウィンドウ ────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._closing:
            return
        if self._settings_win is not None and self._settings_win.winfo_exists():
            win = self._settings_win
            win.deiconify()
            win.lift()
            win.focus_force()
            return

        win = tk.Toplevel(self)
        win.withdraw()
        self._settings_win = win
        win.title('設定')
        win.resizable(False, False)
        # メインが隠れている (トレイから開いた) ときに transient にすると、
        # 設定ウィンドウまで表示されなくなるため、メインが見えているときだけにする
        if self._main_visible():
            win.transient(self)
        try:
            win.iconbitmap(_res('icon.ico'))
        except Exception:
            pass

        self._build_settings_content(win)
        win.protocol('WM_DELETE_WINDOW', self._close_settings_window)
        win.bind('<Escape>', lambda _: self._close_settings_window())
        self._apply_theme()
        self._place_settings(win)
        win.deiconify()
        self._apply_titlebar(win)
        win.lift()
        win.focus_force()

    def _build_settings_content(self, win: tk.Toplevel) -> None:
        px = self._px
        outer = self._reg(tk.Frame(win), 'bg')
        outer.pack(fill='both', expand=True, padx=px(16), pady=px(16))

        def section(title: str, first: bool = False) -> tk.Frame:
            h = self._reg(tk.Label(outer, text=title, font=self._font(FONT_HEADING, bold=True)),
                          'heading')
            h.pack(anchor='w', pady=(0 if first else px(12), px(4)))
            card = self._reg(tk.Frame(outer, highlightthickness=1, bd=0), 'card')
            card.pack(fill='x')
            inner = self._reg(tk.Frame(card), 'surface')
            inner.pack(fill='x', padx=px(12), pady=px(8))
            return inner

        def check(parent, var, text, cmd, enabled=True) -> tk.Checkbutton:
            cb = self._reg(tk.Checkbutton(
                parent, variable=var, text=text, font=self._font(FONT_BODY),
                command=cmd, anchor='w', highlightthickness=1, takefocus=1), 'check')
            if not enabled:
                cb.configure(state='disabled')
            cb.pack(fill='x', pady=px(2))
            return cb

        s = section('起動', first=True)
        check(s, self._startup, f'Windows の起動時に {APP_NAME} を起動する',
              self._on_startup_toggle, enabled=(sys.platform == 'win32'))
        check(s, self._auto_on, f'{APP_NAME} の起動時に自動で ON にする', self._save)
        check(s, self._start_in_tray, '起動時はウィンドウを出さずタスクトレイに格納する', self._save)

        s = section('タスクトレイ')
        check(s, self._minimize_to_tray, '最小化したらタスクトレイに格納する', self._save)
        check(s, self._close_to_tray, '閉じる（×）でタスクトレイに格納する', self._save)
        check(s, self._notify_toggle, 'ON/OFF を切り替えたとき通知する', self._save)

        s = section('表示')
        row = self._reg(tk.Frame(s), 'surface')
        row.pack(fill='x', pady=px(2))
        lbl = self._reg(tk.Label(row, text='テーマ', font=self._font(FONT_BODY)), 'text_surface')
        lbl.pack(side='left', padx=(0, px(12)))
        for value, text in (('system', 'Windows に合わせる'), ('light', 'ライト'), ('dark', 'ダーク')):
            rb = self._reg(tk.Radiobutton(
                row, variable=self._theme_var, value=value, text=text,
                font=self._font(FONT_BODY), highlightthickness=1, takefocus=1,
                command=lambda: self._set_theme_choice(self._theme_var.get())), 'radio')
            rb.pack(side='left', padx=(0, px(8)))

        s = section('更新')
        check(s, self._auto_update_enabled, '自動で更新する', self._save)
        row = self._reg(tk.Frame(s), 'surface')
        row.pack(fill='x', pady=(px(6), px(2)))
        self._update_btn = self._button(row, '今すぐ確認',
                                        lambda: self._check_for_updates(force=True),
                                        on_surface=True)
        self._update_btn.pack(side='left')
        self._update_lbl = self._reg(
            tk.Label(row, text=self._update_label_text, font=self._font(FONT_SMALL),
                     anchor='w'), 'muted_surface')
        self._update_lbl.pack(side='left', padx=(px(8), 0), fill='x', expand=True)

        sep = self._reg(tk.Frame(outer, height=1), 'sep')
        sep.pack(fill='x', pady=(px(16), px(12)))

        ver = self._reg(tk.Label(outer, text=f'{APP_NAME}  v{VERSION}',
                                 font=self._font(FONT_SMALL)), 'muted_bg')
        ver.pack(anchor='w')

        buttons = self._reg(tk.Frame(outer), 'bg')
        buttons.pack(fill='x', pady=(px(8), 0))
        self._button(buttons, 'データフォルダを開く', self._open_data_dir).pack(side='left')
        self._button(buttons, '更新の記録を開く', self._open_update_log).pack(
            side='left', padx=(px(8), 0))
        self._button(buttons, '閉じる', self._close_settings_window).pack(side='right')

        self._refresh_update_controls()

    def _close_settings_window(self) -> None:
        win = self._settings_win
        if win is None:
            return
        self._settings_win = None
        self._update_btn = None
        self._update_lbl = None
        try:
            if win.winfo_exists():
                win.destroy()
        except tk.TclError:
            pass
        self._themed = [(w, r) for w, r in self._themed if self._alive(w)]

    def _place_settings(self, win: tk.Toplevel) -> None:
        """メインの右に出す。画面からはみ出すならメインの左。どちらにしても画面内に収める。"""
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        vx, vy, vw, vh = self._virtual_screen()
        gap = self._px(12)
        frame = self._px(16)  # 枠とタイトルバーのぶんの余裕
        if self._main_visible():
            mx, my = self.winfo_x(), self.winfo_y()
            mw = self.winfo_width() + frame
            x = mx + mw + gap
            if x + w + frame > vx + vw:
                x = mx - w - frame - gap
            y = my
        else:
            x = vx + (vw - w) // 2
            y = vy + (vh - h) // 2
        x = max(vx, min(x, vx + vw - w - frame))
        y = max(vy, min(y, vy + vh - h - frame * 3))
        win.geometry(f'+{x}+{y}')

    def _open_data_dir(self) -> None:
        _open_path(str(settings.data_dir()))

    def _open_update_log(self) -> None:
        path = os.path.join(str(settings.data_dir()), 'update.log')
        if not os.path.exists(path):
            parent = self._settings_win if self._settings_win is not None else self
            self._dialog(messagebox.showinfo, APP_NAME, 'まだ記録はありません', parent=parent)
            return
        _open_path(path)

    # ── テーマ ────────────────────────────────────────────────────────────

    @staticmethod
    def _alive(w) -> bool:
        try:
            return bool(w.winfo_exists())
        except tk.TclError:
            return False

    def _apply_theme(self) -> None:
        t = self._t()
        self.configure(bg=t['BG'])
        if self._settings_win is not None and self._alive(self._settings_win):
            self._settings_win.configure(bg=t['BG'])
        for w, role in self._themed:
            if self._alive(w):
                try:
                    self._style(w, role, t)
                except tk.TclError:
                    pass
        self._style_state_label()
        self._apply_titlebar(self)
        if self._settings_win is not None:
            self._apply_titlebar(self._settings_win)

    def _style(self, w, role: str, t: dict) -> None:
        if role == 'bg':
            w.configure(bg=t['BG'])
        elif role == 'surface':
            w.configure(bg=t['SURFACE'])
        elif role == 'card':
            w.configure(bg=t['SURFACE'], highlightbackground=t['BORDER'],
                        highlightcolor=t['BORDER'])
        elif role == 'sep':
            w.configure(bg=t['BORDER'])
        elif role == 'heading':
            w.configure(bg=t['BG'], fg=t['MUTED'])
        elif role == 'muted_bg':
            w.configure(bg=t['BG'], fg=t['MUTED'])
        elif role == 'text_surface':
            w.configure(bg=t['SURFACE'], fg=t['TEXT'])
        elif role == 'muted_surface':
            w.configure(bg=t['SURFACE'], fg=t['MUTED'])
        elif role == 'state':
            w.configure(bg=t['BG'])
        elif role in ('check', 'radio'):
            w.configure(bg=t['SURFACE'], fg=t['TEXT'], selectcolor=t['ENTRY_BG'],
                        activebackground=t['SURFACE'], activeforeground=t['TEXT'],
                        disabledforeground=t['DISABLED'],
                        highlightbackground=t['SURFACE'], highlightcolor=t['FOCUS'])
        elif role == 'button':
            parent_bg = t['SURFACE'] if getattr(w, '_on_surface', False) else t['BG']
            w.configure(bg=t['BTN_BG'], fg=t['TEXT'], activebackground=t['BTN_HOVER'],
                        activeforeground=t['TEXT'], disabledforeground=t['DISABLED'],
                        highlightbackground=parent_bg, highlightcolor=t['FOCUS'])
        elif role == 'spin':
            bg = t['WARN_BG'] if getattr(w, '_invalid', False) else t['ENTRY_BG']
            w.configure(bg=bg, fg=t['TEXT'], buttonbackground=t['BTN_BG'],
                        insertbackground=t['TEXT'], disabledbackground=t['SURFACE'],
                        disabledforeground=t['DISABLED'], readonlybackground=t['SURFACE'],
                        highlightbackground=t['BORDER'], highlightcolor=t['ACCENT'],
                        selectbackground=t['TOGGLE_ON'], selectforeground='#FFFFFF')
        elif role == 'toggle':
            w.set_colors(t['BG'], t['TOGGLE_ON'], t['TOGGLE_OFF'], t['FOCUS'])

    def _style_state_label(self) -> None:
        t = self._t()
        self._state_lbl.configure(fg=t['ACCENT'] if self._running() else t['MUTED'])

    def _apply_titlebar(self, win) -> None:
        if sys.platform != 'win32' or win is None:
            return
        t = self._t()
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        except Exception:
            return
        TitleBarThemeHelper.apply(hwnd, self._dark, t['CAPTION'], t['CAPTION_TEXT'])

    def _set_theme_choice(self, choice: str) -> None:
        if choice not in theme.THEME_CHOICES:
            choice = 'system'
        self._theme_choice = choice
        if self._theme_var.get() != choice:
            self._theme_var.set(choice)
        self._dark = theme.resolve_dark(choice)
        self._apply_theme()
        self._cfg = settings.update(theme=choice)

    def _poll_system_theme(self) -> None:
        if self._theme_choice != 'system':
            return
        now = time.monotonic()
        if now - self._last_theme_poll < SYSTEM_THEME_POLL_SEC:
            return
        self._last_theme_poll = now
        dark = theme.system_prefers_dark()
        if dark != self._dark:
            self._dark = dark
            self._apply_theme()

    # ── 設定の読み書き ────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        c = self._cfg
        self._stop_timer_enabled.set(bool(c.get('stop_timer_enabled', False)))
        self._stop_hour.set(f"{c.get('stop_hour', 17):02d}")
        self._stop_min.set(f"{c.get('stop_min', 0):02d}")
        self._minimize_to_tray.set(bool(c.get('minimize_to_tray', True)))
        self._close_to_tray.set(bool(c.get('close_to_tray', True)))
        self._notify_toggle.set(bool(c.get('notify_toggle', False)))
        self._auto_on.set(bool(c.get('auto_on', False)))
        self._start_in_tray.set(bool(c.get('start_in_tray', False)))
        self._auto_update_enabled.set(bool(c.get('auto_update_enabled', True)))
        self._theme_var.set(self._theme_choice)
        # 登録されていて exe の場所がずれていれば、今の場所で書き直す
        self._startup.set(startup.sync())
        self._update_time_fields_state()

    def _save(self) -> None:
        """画面で扱う項目だけを保存する (ほかの項目は settings.update が残す)。"""
        if self._loading or self._closing:
            return
        self._cfg = settings.update(
            theme=self._theme_choice,
            stop_timer_enabled=self._stop_timer_enabled.get(),
            stop_hour=self._committed_hour(),
            stop_min=self._committed_min(),
            minimize_to_tray=self._minimize_to_tray.get(),
            close_to_tray=self._close_to_tray.get(),
            notify_toggle=self._notify_toggle.get(),
            auto_on=self._auto_on.get(),
            start_in_tray=self._start_in_tray.get(),
            auto_update_enabled=self._auto_update_enabled.get(),
        )
        self._refresh_view()

    # ── 停止時刻 ──────────────────────────────────────────────────────────

    def _committed_hour(self) -> int:
        return int(stoptimer.normalize_time_field(
            self._stop_hour.get(), 23, self._cfg.get('stop_hour', 17)))

    def _committed_min(self) -> int:
        return int(stoptimer.normalize_time_field(
            self._stop_min.get(), 59, self._cfg.get('stop_min', 0)))

    def _time_invalid(self) -> bool:
        return not (stoptimer.time_field_valid(self._stop_hour.get(), 23)
                    and stoptimer.time_field_valid(self._stop_min.get(), 59))

    def _on_time_edit(self) -> None:
        """入力中: 整形も保存もせず、正しくない値の欄に色を付けるだけ。"""
        for sp, var, maxval in ((getattr(self, '_stop_hour_sp', None), self._stop_hour, 23),
                                (getattr(self, '_stop_min_sp', None), self._stop_min, 59)):
            if sp is None:
                continue
            invalid = not stoptimer.time_field_valid(var.get(), maxval)
            if sp._invalid != invalid:
                sp._invalid = invalid
                self._style(sp, 'spin', self._t())
        if hasattr(self, '_note_lbl'):
            self._refresh_view()

    def _commit_time(self, *_):
        """確定: 範囲内に丸めて2桁にし、保存する。"""
        if self._loading or self._closing:
            return
        h = f'{self._committed_hour():02d}'
        m = f'{self._committed_min():02d}'
        if self._stop_hour.get() != h:
            self._stop_hour.set(h)
        if self._stop_min.get() != m:
            self._stop_min.set(m)
        changed = (int(h) != self._cfg.get('stop_hour') or int(m) != self._cfg.get('stop_min'))
        if changed and self._running():
            self._stop_target = self._calc_stop_target()
        if changed:
            self._save()

    def _on_timer_toggle(self) -> None:
        self._update_time_fields_state()
        if self._running():
            self._commit_time()
            self._stop_target = self._calc_stop_target()
        self._save()

    def _update_time_fields_state(self) -> None:
        state = 'normal' if self._stop_timer_enabled.get() else 'disabled'
        for sp in (self._stop_hour_sp, self._stop_min_sp):
            sp.configure(state=state)

    def _calc_stop_target(self) -> datetime.datetime:
        return stoptimer.calc_stop_target(
            datetime.datetime.now(), self._committed_hour(), self._committed_min())

    def _timer_active(self) -> bool:
        return bool(self._stop_timer_enabled.get())

    # ── ON / OFF ──────────────────────────────────────────────────────────

    def _on_toggle(self, on: bool) -> None:
        if on:
            self._start(notify=True)
        else:
            self._stop(notify=True)

    def _start(self, start_time=None, stop_target=None, notify: bool = False) -> None:
        if self._closing:
            return
        self._commit_time()
        self._auto_stopped_at = None
        self._start_time = start_time or datetime.datetime.now()
        self._stop_target = stop_target or self._calc_stop_target()
        if not self._running():
            self._ctrl.start()
        self._toggle_sw.set_state(True)
        self._refresh_view()
        if notify and self._notify_toggle.get():
            self._tray.notify('ON にしました')

    def _stop(self, auto: bool = False, notify: bool = False) -> None:
        target = self._stop_target
        self._ctrl.stop()
        self._start_time = None
        self._auto_stopped_at = target if auto else None
        self._toggle_sw.set_state(False)
        self._refresh_view()
        if notify and self._notify_toggle.get():
            self._tray.notify('OFF にしました')

    def _toggle_running(self) -> None:
        if self._running():
            self._stop(notify=True)
        else:
            self._start(notify=True)

    def _check_auto_stop(self) -> None:
        if not (self._running() and self._timer_active() and self._stop_target is not None):
            return
        if datetime.datetime.now() >= self._stop_target:
            target = self._stop_target
            self._stop(auto=True)
            # 自動停止は設定に関係なく通知する
            self._tray.notify(stoptimer.stopped_note(target))

    # ── 表示の更新 ────────────────────────────────────────────────────────

    def _note_text(self, now: datetime.datetime) -> str:
        if self._update_note:
            return self._update_note
        if self._timer_active() and self._time_invalid():
            return '時刻は 0〜23 時、0〜59 分で入力してください'
        if self._running():
            if self._timer_active() and self._stop_target is not None:
                return stoptimer.stop_note(self._stop_target, now)
            return 'クリックで OFF にします'
        if self._auto_stopped_at is not None:
            return stoptimer.stopped_note(self._auto_stopped_at)
        return 'クリックで ON にします'

    def _tray_state(self) -> tuple:
        running = self._running()
        stop_label = None
        if self._timer_active():
            stop_label = stoptimer.tray_stop_label(
                self._stop_target if running else None, datetime.datetime.now(),
                self._committed_hour(), self._committed_min())
        return running, stop_label, stoptimer.tray_title(running, stop_label)

    def _refresh_view(self) -> None:
        if self._closing or not hasattr(self, '_state_lbl'):
            return
        now = datetime.datetime.now()
        if self._running():
            text = 'ON'
            if self._start_time is not None:
                text += '  ' + stoptimer.format_elapsed((now - self._start_time).total_seconds())
        else:
            text = 'OFF'
        if self._state_lbl.cget('text') != text:
            self._state_lbl.configure(text=text)
        self._style_state_label()
        note = self._note_text(now)
        if self._note_lbl.cget('text') != note:
            self._note_lbl.configure(text=note)
        if self._toggle_sw.on != self._running():
            self._toggle_sw.set_state(self._running())
        if hasattr(self, '_tray'):
            self._tray.refresh(*self._tray_state())

    # ── 定期処理 (メインスレッド) ─────────────────────────────────────────

    def _pump(self) -> None:
        """別スレッドから積まれた命令を、メインスレッドで実行する。"""
        try:
            if self._closing:
                return
            while True:
                try:
                    item = self._cmds.get_nowait()
                except queue.Empty:
                    break
                try:
                    if item[0] == 'tray':
                        self._handle_tray_command(item[1])
                    elif item[0] == 'update':
                        self._on_update_state(item[1], item[2])
                except Exception:
                    applog.log_exception(*sys.exc_info(), where=f'命令 {item!r}')
                if self._closing:
                    return
            if instance.poll(self._show_event):
                self._show_window()
            self._tray.flush()
            self._maybe_apply_update()
        finally:
            if not self._closing:
                self.after(PUMP_MS, self._pump)

    def _tick(self) -> None:
        """1秒ごとの処理。例外が起きても必ず次を予約する。"""
        try:
            if self._closing:
                return
            self._check_auto_stop()
            self._poll_system_theme()
            # 起動中の定期的な更新確認。確認するたびに次の時刻が先送りされる。
            if time.time() >= self._next_update_check:
                self._check_for_updates()
            self._refresh_view()
        finally:
            if not self._closing:
                self.after(1000, self._tick)

    # ── トレイ ────────────────────────────────────────────────────────────

    def _post_tray(self, cmd: str) -> None:
        # トレイのスレッドから呼ばれる。Tk には触らず、キューに積むだけ。
        self._cmds.put(('tray', cmd))

    def _handle_tray_command(self, cmd: str) -> None:
        if cmd == tray.TOGGLE:
            self._toggle_running()
        elif cmd == tray.OPEN:
            self._show_window()
        elif cmd == tray.SETTINGS:
            self._open_settings()
        elif cmd == tray.CHECK_UPDATE:
            self._check_for_updates(force=True, from_tray=True)
        elif cmd == tray.OPEN_DATA:
            self._open_data_dir()
        elif cmd == tray.QUIT:
            self._request_quit()

    def _show_tray_hint_once(self) -> None:
        if self._cfg.get('tray_hint_shown'):
            return
        self._tray.notify(TRAY_HINT)
        self._cfg = settings.update(tray_hint_shown=True)

    def _go_to_tray(self) -> bool:
        """ウィンドウを隠してトレイだけにする。トレイが使えなければ False。"""
        if not self._tray.available:
            return False
        # メインが隠れているのに設定ウィンドウだけ浮いている状態を避ける
        self._close_settings_window()
        self._save_position()
        self._going_to_tray = True
        try:
            self.withdraw()
        finally:
            self._going_to_tray = False
        self._show_tray_hint_once()
        return True

    def _main_visible(self) -> bool:
        try:
            return bool(self.winfo_viewable()) and self.wm_state() == 'normal'
        except tk.TclError:
            return False

    def _show_window(self) -> None:
        if self._closing:
            return
        self.deiconify()
        try:
            self.state('normal')
        except tk.TclError:
            pass
        self.lift()
        self._apply_titlebar(self)
        try:
            self.focus_force()
        except tk.TclError:
            pass
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.user32.SetForegroundWindow(
                    ctypes.windll.user32.GetParent(self.winfo_id()))
            except Exception:
                pass

    # ── 更新 ──────────────────────────────────────────────────────────────

    def _post_update_state(self, state: str, info: dict) -> None:
        # 更新のスレッドから呼ばれる。Tk には触らず、キューに積むだけ。
        self._cmds.put(('update', state, dict(info or {})))

    def _check_for_updates(self, force: bool = False, from_tray: bool = False) -> None:
        # どの経路 (起動直後 / 定期 / 手動) から呼ばれても、ここから一定時間後を次回とする。
        self._next_update_check = time.time() + updater.RUNTIME_CHECK_INTERVAL_SEC
        if self._closing:
            return
        if self._update_ready is not None:
            return  # ダウンロード済みで適用を待っている
        if not getattr(sys, 'frozen', False):
            if force:
                self._set_update_label('ソースから実行しているため、更新はしません')
                if from_tray:
                    self._tray.notify('ソースから実行しているため、更新はしません')
            return
        if not force and not self._auto_update_enabled.get():
            return
        if self._update_busy or updater.is_running():
            return  # 実行中は何もしない (ボタンは無効になっている)
        started = updater.check_and_apply_async(
            VERSION, self._cfg.get('update_check_url'),
            on_state=self._post_update_state, apply=False)
        if started:
            self._update_busy = True
            self._update_manual = force
            self._update_from_tray = from_tray
            if force:
                self._set_update_label('確認しています…')
        self._refresh_update_controls()

    def _set_update_label(self, text: str) -> None:
        self._update_label_text = text
        if self._update_lbl is not None and self._alive(self._update_lbl):
            self._update_lbl.configure(text=text)

    def _refresh_update_controls(self) -> None:
        btn = self._update_btn
        if btn is None or not self._alive(btn):
            return
        busy = self._update_busy or self._update_ready is not None
        btn.configure(state='disabled' if busy else 'normal',
                      cursor='arrow' if busy else 'hand2')
        if busy:
            btn.configure(bg=self._t()['BTN_BG'])

    def _on_update_state(self, state: str, info: dict) -> None:
        latest = info.get('latest') or ''
        manual = self._update_manual
        from_tray = self._update_from_tray
        if state == 'checking':
            if manual:
                self._set_update_label('確認しています…')
        elif state == 'up_to_date':
            self._update_busy = False
            self._update_note = None
            text = f'最新版です（{latest or "v" + VERSION}）'
            self._set_update_label(text)
            if from_tray:
                self._tray.notify(text)
        elif state == 'downloading':
            self._update_note = '更新をダウンロード中…'
            self._set_update_label('新しい版をダウンロードしています…')
            # 更新の通知は設定に関係なく出す
            self._tray.notify(f'新しい版（{latest}）をダウンロードしています。'
                              '終わると自動で再起動します')
        elif state == 'ready':
            self._update_busy = False
            self._update_ready = {'path': info.get('path'), 'latest': latest}
            self._update_note = '更新の準備ができました'
            self._set_update_label('設定を閉じると更新して再起動します')
        elif state == 'failed':
            self._update_busy = False
            self._update_note = None
            self._set_update_label('確認できませんでした')
            if from_tray:
                self._tray.notify('更新を確認できませんでした')
        if state in ('up_to_date', 'failed', 'ready'):
            self._update_manual = False
            self._update_from_tray = False
        self._refresh_update_controls()
        self._refresh_view()

    def _maybe_apply_update(self) -> None:
        """ダウンロード済みの更新を当てて再起動する。

        終了の確認などのダイアログや設定ウィンドウを表示している間は待つ
        (操作の途中でいきなり終わらないように。終了処理が二重に走らないように)。
        """
        ready = self._update_ready
        if ready is None or self._closing:
            return
        if self._modal > 0:
            return
        if self._settings_win is not None and self._alive(self._settings_win):
            return
        self._update_ready = None
        # 再起動後に今の状態へ戻すための記録。適用 (新プロセスの起動) より前に書く
        running = self._running()
        target = self._stop_target if (running and self._timer_active()) else None
        self._cfg = settings.update(
            just_updated=True,
            resume_after_update=running,
            resume_in_tray=not self._main_visible(),
            resume_stop_target=target.isoformat() if target else None,
            resume_start_time=(self._start_time.isoformat()
                               if running and self._start_time else None),
        )
        if updater.apply_update(ready['path']):
            self._shutdown('update')
            return
        # 失敗: 記録を消して、このまま動き続ける
        self._cfg = settings.update(
            just_updated=False, resume_after_update=False, resume_in_tray=False,
            resume_stop_target=None, resume_start_time=None)
        self._update_note = None
        self._set_update_label('更新できませんでした')
        self._refresh_update_controls()
        self._refresh_view()

    # ── 位置 ──────────────────────────────────────────────────────────────

    def _virtual_screen(self) -> tuple:
        """(x, y, 幅, 高さ)。Windows ではすべてのモニタを含む仮想デスクトップ。"""
        if sys.platform == 'win32':
            try:
                import ctypes
                u32 = ctypes.windll.user32
                vx, vy = u32.GetSystemMetrics(76), u32.GetSystemMetrics(77)
                vw, vh = u32.GetSystemMetrics(78), u32.GetSystemMetrics(79)
                if vw > 0 and vh > 0:
                    return vx, vy, vw, vh
            except Exception:
                pass
        return 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()

    def _restore_position(self) -> None:
        x, y = self._cfg.get('win_x'), self._cfg.get('win_y')
        if isinstance(x, int) and isinstance(y, int) and self._position_on_screen(x, y):
            self.geometry(f'+{x}+{y}')

    def _position_on_screen(self, x: int, y: int) -> bool:
        """保存された座標が、いずれかのモニタを含む表示可能領域に収まっているか。"""
        vx, vy, vw, vh = self._virtual_screen()
        return vx - 50 < x < vx + vw - 100 and vy - 50 < y < vy + vh - 100

    def _save_position(self) -> None:
        try:
            if not self._main_visible():
                return
            x, y = self.winfo_x(), self.winfo_y()
        except tk.TclError:
            return
        self._cfg = settings.update(win_x=x, win_y=y)

    # ── スタートアップ ────────────────────────────────────────────────────

    def _on_startup_toggle(self) -> None:
        if sys.platform != 'win32':
            return
        try:
            if self._startup.get():
                startup.write(startup.current_command())
            else:
                startup.remove()
        except OSError:
            self._dialog(messagebox.showwarning, APP_NAME,
                         'Windows の起動時に起動する設定を変更できませんでした。',
                         parent=self._settings_win or self)
            self._startup.set(startup.read_registered() is not None)

    # ── ウィンドウの操作と終了 ────────────────────────────────────────────

    def _on_close(self) -> None:
        if self._close_to_tray.get() and self._go_to_tray():
            return
        # トレイに格納しない設定か、トレイが使えない: 通常の終了
        self._request_quit()

    def _on_unmap(self, event: tk.Event) -> None:
        if event.widget is self and not self._going_to_tray and not self._closing:
            self.after(50, self._check_iconify)

    def _check_iconify(self) -> None:
        if self._closing or not self._alive(self):
            return
        try:
            state = self.wm_state()
        except tk.TclError:
            return
        if state == 'iconic' and self._minimize_to_tray.get():
            self._go_to_tray()

    def _request_quit(self) -> None:
        """終了する。ON のときだけ確認する。"""
        if self._closing:
            return
        if self._running():
            ok = self._dialog(messagebox.askyesno, APP_NAME,
                              'ON のままです。終了すると OFF になります。終了しますか？',
                              parent=self)
            if not ok or self._closing:
                return
        self._shutdown('user')

    def _shutdown(self, reason: str) -> None:
        """終了処理はすべてここを通す。二重に走らないようにする。"""
        if self._closing:
            return
        self._closing = True
        try:
            if reason != 'update':
                self._save_position()
            self._close_settings_window()
            self._tray.stop()
            self._ctrl.stop()
            ready = self._update_ready
            if ready and ready.get('path'):
                # 当てずに終わる更新ファイルは残さない
                try:
                    os.remove(ready['path'])
                except OSError:
                    pass
            instance.close(self._show_event)
        except Exception:
            applog.log_exception(*sys.exc_info(), where='終了処理')
        finally:
            # 予約済みの定期処理・アニメーションを取り消してから壊す
            try:
                for after_id in self.tk.splitlist(self.tk.call('after', 'info')):
                    self.after_cancel(after_id)
            except tk.TclError:
                pass
            try:
                self.destroy()
            except tk.TclError:
                pass
