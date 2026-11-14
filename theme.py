"""配色と、Windows のアプリのテーマ (ライト/ダーク) の読み取り。

Tk に依存しない (tkinter の無い環境でもテストできるように)。
"""
import sys

# Windows 11 の設定アプリに寄せた、落ち着いた配色。
#   BG        ウィンドウの背景
#   SURFACE   カード (設定のまとまり) の面
#   TEXT      本文
#   MUTED     補助の文字 (補足・見出し・バージョン)
#   BORDER    カードの枠線・区切り線
#   ACCENT    ON を表す色 (状態表示の「ON」の文字色)
#   OFF       OFF を表す色
#   WARN_BG   入力が正しくない欄の背景
#   TOGGLE_ON / TOGGLE_OFF  トグルの地の色 (白い文字とのコントラスト比 4.5:1 以上)
THEMES: dict = {
    'light': {
        'BG':         '#F3F3F3',
        'SURFACE':    '#FFFFFF',
        'TEXT':       '#1B1B1B',
        'MUTED':      '#5C5C5C',
        'BORDER':     '#E0E0E0',
        'ACCENT':     '#2E7D32',
        'OFF':        '#6B7280',
        'WARN_BG':    '#FDE7E9',
        'ENTRY_BG':   '#FFFFFF',
        'BTN_BG':     '#E6E6E6',
        'BTN_HOVER':  '#D9D9D9',
        'DISABLED':   '#9E9E9E',
        'FOCUS':      '#1B1B1B',
        'TOGGLE_ON':  '#2E7D32',
        'TOGGLE_OFF': '#6B7280',
        # タイトルバー (Windows 11 22H2 以降)
        'CAPTION':      '#F3F3F3',
        'CAPTION_TEXT': '#1B1B1B',
    },
    'dark': {
        'BG':         '#202020',
        'SURFACE':    '#2B2B2B',
        'TEXT':       '#F2F2F2',
        'MUTED':      '#A6A6A6',
        'BORDER':     '#3A3A3A',
        'ACCENT':     '#43A047',
        'OFF':        '#5A5F66',
        'WARN_BG':    '#5C2626',
        'ENTRY_BG':   '#202020',
        'BTN_BG':     '#3A3A3A',
        'BTN_HOVER':  '#474747',
        'DISABLED':   '#6E6E6E',
        'FOCUS':      '#F2F2F2',
        # #43A047 は白い文字とのコントラスト比が 3.3:1 しかないため、
        # トグルの地はダークでも濃い緑にする (5.1:1)。
        'TOGGLE_ON':  '#2E7D32',
        'TOGGLE_OFF': '#5A5F66',
        'CAPTION':      '#202020',
        'CAPTION_TEXT': '#F2F2F2',
    },
}

THEME_CHOICES = ('system', 'light', 'dark')


def hex_to_rgb(color: str) -> tuple:
    h = color.lstrip('#')
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _relative_luminance(color: str) -> float:
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_to_rgb(color)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.x のコントラスト比。"""
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def system_prefers_dark() -> bool:
    """Windows の「アプリのモード」がダークなら True。読めなければ False (ライト)。

    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize の
    AppsUseLightTheme が 0 ならダーク。
    """
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return int(value) == 0
    except (OSError, ValueError, TypeError):
        return False


def resolve_dark(choice: str) -> bool:
    """設定のテーマ ('system' / 'light' / 'dark') から、ダークで描くかを決める。"""
    if choice == 'dark':
        return True
    if choice == 'light':
        return False
    return system_prefers_dark()
