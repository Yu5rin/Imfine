import http.client
import json
import subprocess
import sys
import tempfile
import threading

REPO = 'Yu5rin/Mouser'


def _parse_ver(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip('v').split('.'))


def _fetch_latest() -> dict:
    import ssl
    ctx = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection('api.github.com', context=ctx, timeout=5)
    conn.request('GET', f'/repos/{REPO}/releases/latest',
                 headers={'User-Agent': 'Mouser'})
    resp = conn.getresponse()
    return json.loads(resp.read())


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
                on_up_to_date(latest_tag)
        except Exception:
            if on_up_to_date:
                on_up_to_date(None)
    threading.Thread(target=_worker, daemon=True).start()


def download_and_replace(dl_url: str) -> None:
    import ssl
    current_exe = sys.executable if getattr(sys, 'frozen', False) else None
    if not current_exe:
        return
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
    tmp.close()
    ctx = ssl._create_unverified_context()
    from urllib.request import build_opener, HTTPSHandler, install_opener, urlretrieve
    opener = build_opener(HTTPSHandler(context=ctx))
    install_opener(opener)
    urlretrieve(dl_url, tmp.name)
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
