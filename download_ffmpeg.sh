#!/bin/bash
# 下载 ffmpeg + ffprobe 静态二进制（macOS arm64）到 bin/，供打包时内置
# 来源：https://www.osxexperts.net/
set -e

cd "$(dirname "$0")"
mkdir -p bin

echo "→ 下载 ffmpeg (arm64)..."
curl -L --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
    -o /tmp/ffmpeg.zip "https://www.osxexperts.net/ffmpeg711arm.zip"

echo "→ 下载 ffprobe (arm64)..."
curl -L --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
    -o /tmp/ffprobe.zip "https://www.osxexperts.net/ffprobe711arm.zip"

unzip -o /tmp/ffmpeg.zip -d bin/
unzip -o /tmp/ffprobe.zip -d bin/
chmod +x bin/ffmpeg bin/ffprobe
rm -f /tmp/ffmpeg.zip /tmp/ffprobe.zip

echo "✓ 完成"
ls -lh bin/
