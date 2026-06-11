import datetime
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

import settings
from controller import Controller


VERSION = '1.9.2'

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

    def __init__(self, parent, command=None):
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
        )
        cb.pack(side='left')
        self._tw['checks'].append(cb)

        self._stop_hour = tk.StringVar(value='17')
        self._stop_min  = tk.StringVar(value='00')

        self._stop_hour_sp = tk.Spinbox(
            outer, from_=0, to=23, increment=1,
            textvariable=self._stop_hour, width=4,
            relief='solid', bd=1, font=('Helvetica', 10),
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
        self._stop_hour.set(f"{c.get('stop_hour', 17):02d}")
        self._stop_min.set(f"{c.get('stop_min', 0):02d}")
        self._tray_minimize.set(bool(c.get('tray_minimize', True)))

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
        self._refresh_stop_target()

    def _fmt_time_and_save(self, var: tk.StringVar, maxval: int) -> None:
        if self._loading:
            return
        try:
            v = max(0, min(maxval, int(var.get())))
            fmt = f'{v:02d}'
            if var.get() != fmt:
                var.set(fmt)
                return  # set で trace が再発火し、そちらで保存される
        except ValueError:
            pass
        self._save_if_valid()

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
        self._stop_target = self._calc_stop_target()
        if self._stop_timer_enabled.get() and self._stop_target is None:
            messagebox.showwarning(
                "I'm fine", '停止時刻が不正なため停止タイマーは動作しません。')
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
            if not messagebox.askyesno("I'm fine", '動作中です。終了しますか？'):
                return
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
        if self.wm_state() == 'iconic' and self._tray_minimize.get():
            self._minimize_to_tray()

    def _minimize_to_tray(self) -> None:
        try:
            import pystray
            import pystray._win32
        except ImportError:
            return
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
                    # ダブルクリックは DOWN→UP→DBLCLK→UP の順で届くため、
                    # 直後の UP を無視しないと単クリック判定が再発火する
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
                        pass  # アプリ終了直後にタイマーが発火した場合

        running = hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING
        try:
            img = _load_tray_image(running)
        except Exception:
            img = Image.new('RGB', (64, 64),
                            '#4CAF50' if running else '#9E9E9E')
        menu = pystray.Menu(
            pystray.MenuItem('タスクトレイから出す',
                             self._tray_restore, default=True),
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
            msg = '動作中'
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

    def _tray_quit(self, icon=None, item=None) -> None:
        self.after(0, self._confirm_tray_quit)

    def _confirm_tray_quit(self) -> None:
        if hasattr(self, '_ctrl') and self._ctrl.state == Controller.RUNNING:
            if not messagebox.askyesno("I'm fine", '動作中です。終了しますか？'):
                return
        icon_ref = self._tray_icon
        self._tray_icon = None
        self._stop_tray_icon(icon_ref)
        if hasattr(self, '_ctrl'):
            self._ctrl.stop()
        self.destroy()
