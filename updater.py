import json
import os
import re
import subprocess
import sys
import tempfile
import threading

REPO = 'Yu5rin/Mouser'

_URLS = [
    f'https://github.com/{REPO}/releases',
    f'https://api.github.com/repos/{REPO}/releases/latest',
]


def _parse_ver(tag: str) -> tuple:
    return tuple(int(x) for x in tag.lstrip('v').split('.'))


def _parse_body(body: str) -> 'tuple[str, str] | None':
    m = re.search(r'/releases/tag/(v[\d.]+)', body)
    if m:
        tag = m.group(1)
        return tag, f'https://github.com/{REPO}/releases/download/{tag}/Mouser.exe'
    try:
        data = json.loads(body)
        if 'tag_name' in data:
            tag = data['tag_name']
            dl_url = next(
                a['browser_download_url'] for a in data.get('assets', [])
                if a['name'].endswith('.exe')
            )
            return tag, dl_url
    except Exception:
        pass
    return None


def _fetch_urllib() -> 'tuple[str, str]':
    """Use urllib with system proxy (reads Windows registry) + unverified SSL."""
    import ssl
    import urllib.request
    ctx = ssl._create_unverified_context()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(urllib.request.getproxies()),
        urllib.request.HTTPSHandler(context=ctx),
    )
    last_err = 'no url tried'
    for url in _URLS:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with opener.open(req, timeout=15) as r:
                body = r.read().decode('utf-8', errors='replace')
            result = _parse_body(body)
            if result:
                return result
            last_err = f'no tag in body: {body[:40]!r}'
        except Exception as e:
            last_err = str(e)
    raise RuntimeError(f'urllib: {last_err}')


def _fetch_powershell() -> 'tuple[str, str]':
    """Use PowerShell WebRequest (WinHTTP, uses system proxy) writing to temp file."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.txt')
    tmp.close()
    try:
        last_err = 'no url tried'
        for url in _URLS:
            try:
                ps = (
                    '[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;'
                    f'$req=[System.Net.WebRequest]::Create("{url}");'
                    '$req.UserAgent="Mozilla/5.0";$req.Timeout=12000;'
                    'try{$resp=$req.GetResponse()}'
                    'catch[System.Net.WebException]{$resp=$_.Exception.Response};'
                    'if($resp){'
                    '$sr=New-Object System.IO.StreamReader($resp.GetResponseStream(),'
                    '[System.Text.Encoding]::UTF8);'
                    f'[System.IO.File]::WriteAllText("{tmp.name}",$sr.ReadToEnd(),'
                    '[System.Text.Encoding]::UTF8)}'
                )
                subprocess.run(
                    ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                    timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                with open(tmp.name, encoding='utf-8', errors='replace') as f:
                    body = f.read()
                result = _parse_body(body)
                if result:
                    return result
                last_err = f'no tag in body: {body[:40]!r}'
            except Exception as e:
                last_err = str(e)
        raise RuntimeError(f'powershell: {last_err}')
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def _fetch_latest() -> 'tuple[str, str]':
    errors = []
    for strategy in (_fetch_urllib, _fetch_powershell):
        try:
            return strategy()
        except Exception as e:
            errors.append(str(e))
    raise RuntimeError(' | '.join(errors))


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
    # Use urllib with system proxy for download
    try:
        import ssl
        import urllib.request
        ctx = ssl._create_unverified_context()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(urllib.request.getproxies()),
            urllib.request.HTTPSHandler(context=ctx),
        )
        urllib.request.install_opener(opener)
        urllib.request.urlretrieve(dl_url, tmp.name)
    except Exception:
        # Fallback: PowerShell download
        ps = (
            '[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;'
            f'Invoke-WebRequest -Uri "{dl_url}" -OutFile "{tmp.name}" -UseBasicParsing'
        )
        subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
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
