# -*- mode: python ; coding: utf-8 -*-
import os

# arm64 静态 ffmpeg/ffprobe 太大不进 git（见 .gitignore 的 bin/）。换机或重新
# clone 后 bin/ 是空的，若不检查，PyInstaller 只会 warning 然后静默打出「缺
# ffmpeg 的残包」——装上后才发现合并失败。这里构建前先 fail-fast。
_binaries = []
for _fb in ('ffmpeg', 'ffprobe'):
    _fp = os.path.join(SPECPATH, 'bin', _fb)
    if not os.path.exists(_fp):
        raise SystemExit(
            f'缺少 bin/{_fb}（arm64 静态版）。先放好再打包，'
            f'否则打出的包缺 ffmpeg、合并功能会失效。')
    _binaries.append((_fp, '.'))

a = Analysis(
    ['merger.py'],
    pathex=[],
    binaries=_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='视频合并',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='视频合并',
)

app = BUNDLE(
    coll,
    name='视频合并.app',
    icon='AppIcon.icns',
    bundle_identifier='com.purpleloop.videomerger',
    info_plist={
        'CFBundleShortVersionString': '1.0',
        'CFBundleVersion': '1.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '12.0',
    },
)
