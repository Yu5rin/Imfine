# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('icon.png', '.')],
    hiddenimports=['controller', 'settings', 'updater'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # unused stdlib (PyInstaller内部依存を避けた安全なもののみ)
        'unittest', 'pydoc', 'doctest', 'test',
        'pkg_resources', 'setuptools', 'distutils',
        'sqlite3', 'csv',
        'difflib', 'fractions',
        'calendar',
        'tarfile', 'gzip', 'bz2', 'lzma',
        'ftplib', 'smtplib', 'imaplib', 'poplib',
        # PIL format plugins (不使用 — アイコンは描画生成)
        'PIL.BmpImagePlugin', 'PIL.GifImagePlugin',
        'PIL.JpegImagePlugin', 'PIL.Jpeg2KImagePlugin',
        'PIL.TiffImagePlugin', 'PIL.WebPImagePlugin',
        'PIL.IcoImagePlugin',  'PIL.PngImagePlugin',
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
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Mouser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
