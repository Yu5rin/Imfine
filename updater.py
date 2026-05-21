import json
import subprocess
import sys
import tempfile
import threading

REPO = 'Yu5rin/Mouser'


def _parse_ver(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip('v').split('.'))


def _fetch_latest() -> dict:
    result = subprocess.run(
        ['curl.exe', '-s', '-L',
         '-H', 'User-Agent: Mouser',
         f'https://api.github.com/repos/{REPO}/releases/latest'],
        capture_output=True, text=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    body = result.stdout.strip()
    if not body:
        raise RuntimeError(result.stderr.strip() or 'empty response')
    return json.loads(body)


def check_and_prompt(current_version: str, on_update_available,
                     on_up_to_date=None) -> None:
    def _worker():
        try:
            data = _fetch_latest()
            latest_tag = data['tag_name']
            dl_url = next(
                a['browser_download_url']
                for a in data['assets']
                if a['name'].endswith('.exe')
            )
            if _parse_ver(latest_tag) > _parse_ver(current_version):
                on_update_available(latest_tag, dl_url)
            elif on_up_to_date:
                on_up_to_date(latest_tag, None)
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
        ['curl.exe', '-s', '-L', '-o', tmp.name, dl_url],
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
