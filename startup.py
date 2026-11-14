"""Windows の起動時に I'm fine を起動するための登録 (HKCU の Run キー)。"""
import os
import sys

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'ImFine'


def expected_command(frozen: bool, executable: str, argv0: str) -> str:
    """登録すべきコマンドライン。exe ならその exe、ソース実行なら python とスクリプト。"""
    if frozen:
        return f'"{executable}"'
    return f'"{executable}" "{os.path.abspath(argv0)}"'


def current_command() -> str:
    return expected_command(bool(getattr(sys, 'frozen', False)),
                            sys.executable, sys.argv[0])


def _norm(cmd: str) -> str:
    # Windows のパスは大文字小文字を区別しないため、比べるときはそろえる
    return ' '.join(str(cmd).split()).casefold()


def needs_rewrite(registered: str | None, expected: str) -> bool:
    """登録されているが、今の exe の場所と違う (exe を移動した、など) なら True。"""
    if not registered:
        return False
    return _norm(registered) != _norm(expected)


def read_registered() -> str | None:
    """登録されている値。無い・読めない・Windows 以外なら None。"""
    if sys.platform != 'win32':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
        return str(value) if value else None
    except OSError:
        return None


def write(command: str) -> None:
    """登録する。失敗したら OSError。"""
    if sys.platform != 'win32':
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY,
                        0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)


def remove() -> None:
    """登録を消す。失敗したら OSError。"""
    if sys.platform != 'win32':
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY,
                        0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, RUN_NAME)
        except FileNotFoundError:
            pass


def sync() -> bool:
    """登録の有無を返す。登録されていて場所がずれていれば、今の場所で書き直す。

    書き直すのは exe で動いているときだけ (ソースから試しに動かしただけで、
    登録が python のコマンドに書き換わってしまわないように)。
    """
    registered = read_registered()
    if registered is None:
        return False
    expected = current_command()
    if getattr(sys, 'frozen', False) and needs_rewrite(registered, expected):
        try:
            write(expected)
        except OSError:
            pass
    return True
