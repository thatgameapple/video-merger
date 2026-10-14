# -*- mode: python ; coding: utf-8 -*-
# 同一份 spec 两个平台用：macOS 出 .app（再由 build_dmg.sh 包 dmg），
# Windows 出「Video Merge」文件夹（里面是 Video Merge.exe + ffmpeg.exe/ffprobe.exe），
# 由 GitHub Actions 的 windows 构建打成 zip。PyInstaller 不能跨平台交叉编译。
import os
import sys
_WIN = sys.platform == 'win32'

# arm64 静态 ffmpeg/ffprobe 太大不进 git（见 .gitignore 的 bin/）。换机或重新
# clone 后 bin/ 是空的，若不检查，PyInstaller 只会 warning 然后静默打出「缺
# ffmpeg 的残包」——装上后才发现合并失败。这里构建前先 fail-fast。
# 版本号以 merger.py 的 VERSION 为唯一来源，避免 plist 与界面页脚漂移。
import re
with open(os.path.join(SPECPATH, 'merger.py'), encoding='utf-8') as _vf:
    _VERSION = re.search(r"^VERSION = '([^']+)'", _vf.read(), re.M).group(1)

_binaries = []
for _fb in ('ffmpeg', 'ffprobe'):
    if _WIN:
        _fb += '.exe'
    _fp = os.path.join(SPECPATH, 'bin', _fb)
    if not os.path.exists(_fp):
        raise SystemExit(
            f'缺少 bin/{_fb}（{"Windows x64" if _WIN else "arm64"} 静态版）。先放好再打包，'
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
    name='Video Merge',
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
    icon='AppIcon.ico' if _WIN else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Video Merge',
)

if not _WIN:
    app = BUNDLE(
        coll,
        name='Video Merge.app',
        icon='AppIcon.icns',
        bundle_identifier='com.purpleloop.videomerger',
        info_plist={
            'CFBundleShortVersionString': _VERSION,
            'CFBundleVersion': _VERSION,
            'NSHighResolutionCapable': True,
            'LSMinimumSystemVersion': '12.0',
        },
    )
