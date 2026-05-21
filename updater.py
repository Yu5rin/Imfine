import json
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.request

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

REPO = 'Yu5rin/Mouser'
API  = f'https://api.github.com/repos/{REPO}/releases/latest'


def _parse_ver(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip('v').split('.'))


def check_and_prompt(current_version: str, on_update_available,
                     on_up_to_date=None) -> None:
    def _worker():
        try:
            req = urllib.request.Request(API, headers={'User-Agent': 'Mouser'})
            with urllib.request.urlopen(req, timeout=5, context=_SSL_CTX) as r:
                data = json.loads(r.read())
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
    current_exe = sys.executable if getattr(sys, 'frozen', False) else None
    if not current_exe:
        return
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
    tmp.close()
    urllib.request.urlretrieve(dl_url, tmp.name)
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
