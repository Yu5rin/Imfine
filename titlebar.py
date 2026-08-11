import sys

# DwmSetWindowAttribute 属性値
_DWMWA_USE_IMMERSIVE_DARK_MODE     = 20  # Windows 10 20H1 (build 18985) 以降
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19  # Windows 10 1809-1909 (未文書化の旧値)
_DWMWA_CAPTION_COLOR               = 35  # Windows 11 22H2 (build 22621) 以降
_DWMWA_TEXT_COLOR                  = 36  # 同上

_BUILD_DARK_MODE     = 18985
_BUILD_CAPTION_COLOR = 22621


def _os_build() -> int:
    if sys.platform != 'win32':
        return 0
    try:
        import platform
        return int(platform.version().split('.')[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


def _to_colorref(hex_color: str) -> int:
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (b << 16) | (g << 8) | r  # COLORREF は 0x00BBGGRR


class TitleBarThemeHelper:
    """DWM API でタイトルバーをアプリのテーマに連動させる静的ヘルパー。

    Windows 11 未満やビルドが対応していない環境では何もせず、
    標準タイトルバーのまま動作する (例外は内部で握りつぶす)。
    呼び出し側はウィンドウハンドルの取得方法だけ実装に合わせればよい。
    """

    @staticmethod
    def apply(hwnd: int, is_dark: bool,
              caption_color: str | None = None,
              text_color: str | None = None) -> None:
        if sys.platform != 'win32' or not hwnd:
            return

        import ctypes
        import ctypes.wintypes as wt

        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

        def _set(attr: int, value: int) -> bool:
            v = ctypes.c_int(value)
            hr = dwmapi.DwmSetWindowAttribute(
                wt.HWND(hwnd), wt.DWORD(attr),
                ctypes.byref(v), wt.DWORD(ctypes.sizeof(v)))
            return hr == 0

        build = _os_build()

        if build >= _BUILD_DARK_MODE:
            try:
                if not _set(_DWMWA_USE_IMMERSIVE_DARK_MODE, int(is_dark)):
                    _set(_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, int(is_dark))
            except OSError:
                pass

        if build >= _BUILD_CAPTION_COLOR:
            try:
                if caption_color:
                    _set(_DWMWA_CAPTION_COLOR, _to_colorref(caption_color))
                if text_color:
                    _set(_DWMWA_TEXT_COLOR, _to_colorref(text_color))
            except OSError:
                pass
