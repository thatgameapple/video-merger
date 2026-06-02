#!/usr/bin/env bash
# 视频合并 — pyinstaller 打 .app + create-dmg 出 dmg。
# 用法：./build_dmg.sh
set -e
cd "$(dirname "$0")"

APP_NAME="视频合并"
VERSION="1.1"
DMG="${APP_NAME}_${VERSION}_macos.dmg"
PY="/opt/homebrew/bin/python3.11"

echo "→ 准备 bin/（arm64 native 静态 ffmpeg/ffprobe，首次缺就从 osxexperts 下载）"
mkdir -p bin
fetch_bin() {
    local name="$1"; local url="$2"
    if [ -x "bin/${name}" ]; then return 0; fi
    echo "  下载 ${name} arm64 (osxexperts)…"
    curl -fL -o "/tmp/${name}-arm.zip" "$url"
    unzip -o -q "/tmp/${name}-arm.zip" -x "__MACOSX/*" -d bin/ && rm -f "/tmp/${name}-arm.zip"
    xattr -cr "bin/${name}"
    codesign -fs - "bin/${name}"
}
fetch_bin ffmpeg  'https://www.osxexperts.net/ffmpeg81arm.zip'
fetch_bin ffprobe 'https://www.osxexperts.net/ffprobe81arm.zip'
rm -rf bin/__MACOSX 2>/dev/null

echo "→ 清理上次构建 + 所有旧版 dmg（只留本次要出的版本）"
rm -rf build dist
find . -maxdepth 1 -name "${APP_NAME}_*_macos.dmg" -delete 2>/dev/null
find . -maxdepth 1 -name "._${APP_NAME}_*_macos.dmg" -delete 2>/dev/null

echo "→ pyinstaller 打 .app"
"$PY" -m PyInstaller merger.spec --noconfirm

if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo "✗ dist/${APP_NAME}.app 没产出，pyinstaller 失败"
    exit 1
fi

echo "→ create-dmg 出镜像"
create-dmg \
    --volname "$APP_NAME" \
    --volicon AppIcon.icns \
    --window-size 660 400 \
    --icon-size 100 \
    --icon "${APP_NAME}.app" 180 170 \
    --app-drop-link 480 170 \
    --hide-extension "${APP_NAME}.app" \
    --no-internet-enable \
    "$DMG" \
    "dist/${APP_NAME}.app"

echo "✓ $DMG"
ls -lh "$DMG"
