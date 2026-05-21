import re
import subprocess
import sys
import tempfile
import threading

REPO = 'Yu5rin/Mouser'


def _parse_ver(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip('v').split('.'))


def _fetch_latest() -> tuple[str, str]:
    """Returns (tag, download_url) by scraping the releases HTML page."""
    import os
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.html')
    tmp.close()
    try:
        subprocess.run(
            ['curl.exe', '-s', '-k', '-L', '-o', tmp.name,
             '-H', 'User-Agent: Mozilla/5.0',
             f'https://github.com/{REPO}/releases'],
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        with open(tmp.name, encoding='utf-8', errors='replace') as f:
            body = f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
    m = re.search(r'/releases/tag/(v[\d.]+)', body)
    if not m:
        raise RuntimeError(f'page: {body[:60]!r}')
    tag = m.group(1)
    dl_url = f'https://github.com/{REPO}/releases/download/{tag}/Mouser.exe'
    return tag, dl_url


def check_and_prompt(current_version: str, on_update_available,
                     on_up_to_date=None) -> None:
    def _worker():
        try:
            tag, dl_url = _fetch_latest()
            if _parse_ver(tag) > _parse_ver(current_version):
                on_update_available(tag, dl_url)
            elif on_up_to_date:
                on_up_to_date(tag, None)
        except Exception as e:
            if on_up_to_date:
                on_up_to_date(None, str(e))
    threading.Thread(target=_worker, daemon=True).start()


def download_and_replace(dl_url: str) -> None:
    current_exe = sys.executable if getattr(sys, 'frozen', False) else None
    if not current_exe:
        return
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
    tmp.close()
    subprocess.run(
        ['curl.exe', '-s', '-k', '-L', '-o', tmp.name, dl_url],
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    bat = tempfile.NamedTemporaryFile(
        delete=False, suffix='.bat', mode='w', encoding='cp932'
    )
    bat.write('@echo off\n')
    bat.write('timeout /t 2 /nobreak >nul\n')
    bat.write(f'move /y "{tmp.name}" "{current_exe}"\n')
    bat.write(f'start "" "{current_exe}"\n')
    bat.write('del "%~f0"\n')
    bat.close()
    subprocess.Popen(
        ['cmd', '/c', bat.name],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.exit(0)
