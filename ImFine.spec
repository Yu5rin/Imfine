# -*- mode: python ; coding: utf-8 -*-
import os
import re

# exe に埋め込むバージョン情報 (エクスプローラーのプロパティの「詳細」に出る)。
# 版は ui.py の VERSION だけで管理し、ここではビルドのたびにそれを読んで
# version_info.txt を作る (生成物なので .gitignore に入れてある)。
_here = SPECPATH
with open(os.path.join(_here, 'ui.py'), encoding='utf-8') as _f:
    _m = re.search(r"^VERSION = '([^']+)'", _f.read(), re.M)
if not _m:
    raise SystemExit("ui.py から VERSION を読み取れません")
_ver = _m.group(1)
_nums = [int(re.sub(r'\D', '', p) or 0) for p in _ver.split('.')][:4]
_nums += [0] * (4 - len(_nums))
_ver_tuple = tuple(_nums)
_ver_text = '.'.join(str(n) for n in _nums)
_version_file = os.path.join(_here, 'version_info.txt')
with open(_version_file, 'w', encoding='utf-8') as _f:
    _f.write(f'''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_ver_tuple},
    prodvers={_ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '041104B0',
        [StringStruct('CompanyName', 'YUGO'),
         StringStruct('FileDescription', "I'm fine"),
         StringStruct('FileVersion', '{_ver_text}'),
         StringStruct('InternalName', 'ImFine'),
         StringStruct('LegalCopyright', 'Copyright (c) 2026 YUGO'),
         StringStruct('OriginalFilename', 'ImFine.exe'),
         StringStruct('ProductName', "I'm fine"),
         StringStruct('ProductVersion', '{_ver}')])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0411, 1200])])
  ]
)
''')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('icon.png', '.'), ('icon_off.png', '.')],
    hiddenimports=[
        'controller', 'settings', 'titlebar', 'updater',
        'applog', 'instance', 'startup', 'stoptimer', 'theme', 'tray',
        'PIL.BmpImagePlugin', 'PIL.PngImagePlugin',
        'PIL.ImageTk', 'PIL.ImageDraw', 'PIL.ImageFont',
        'pystray', 'pystray._win32', 'pystray._base',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'unittest', 'pydoc', 'doctest', 'test',
        'pkg_resources', 'setuptools', 'distutils',
        'sqlite3', 'csv',
        'difflib',
        'tarfile', 'gzip', 'bz2', 'lzma',
        'ftplib', 'smtplib', 'imaplib', 'poplib',
        'xmlrpc', 'pydoc_data', 'lib2to3',
        'asyncio', 'concurrent', 'multiprocessing',
        'PIL.GifImagePlugin',
        'PIL.JpegImagePlugin', 'PIL.Jpeg2KImagePlugin',
        'PIL.TiffImagePlugin', 'PIL.WebPImagePlugin',
        'PIL.SgiImagePlugin',  'PIL.TgaImagePlugin',
        'PIL.PcxImagePlugin',  'PIL.PpmImagePlugin',
        'PIL.XbmImagePlugin',  'PIL.XpmImagePlugin',
        'PIL.ImImagePlugin',   'PIL.MspImagePlugin',
        'PIL.FliImagePlugin',  'PIL.DdsImagePlugin',
        'PIL.BlpImagePlugin',  'PIL.CurImagePlugin',
        'PIL.EpsImagePlugin',  'PIL.WmfImagePlugin',
        'PIL.PsdImagePlugin',  'PIL.SpiderImagePlugin',
        'PIL.SunImagePlugin',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ImFine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
    version=_version_file,
)
