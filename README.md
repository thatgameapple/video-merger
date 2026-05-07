# 视频合并工具 VM

> Purple Loop 配套小工具。批量把分段录制的视频文件按文件名顺序无损拼成一个，方便后续做字幕识别和剪辑。

PyQt6 + FFmpeg。macOS（Apple Silicon）。

## 适用场景

录屏 / 摄像机 / 行车记录仪 类的设备常会把一段长视频切成 `00000.mp4`、`00001.mp4`、`00002.mp4`…… 一堆分段。在做字幕识别或丢进剪辑软件之前，先合成一整条会舒服很多。

VM 用 FFmpeg 的 concat demuxer（`-c copy`）直接拼，不重编码，几乎只受硬盘读写速度限制。

> 前提：所有分段是同一台设备同一次录制切出来的（编码 / 分辨率 / 帧率一致）。混合不同来源的视频请用别的工具。

## 安装

从 [Releases](https://github.com/thatgameapple/video-merger/releases) 下载 `视频合并_x.x_macos.dmg`，拖进 Applications。

FFmpeg 已内置，**无需额外安装任何东西**。

首次打开如果被 Gatekeeper 拦，去「系统设置 → 隐私与安全性」点「仍要打开」。

## 使用

1. 选文件夹，左侧列表会按文件名排序列出该文件夹里的视频（`._` 元数据文件已过滤）
2. 多选要合并的文件
3. 设置输出文件名
4. 点「开始合并」
5. （可选）勾选「合并后删除原文件」，会有二次确认

支持格式：`.mp4` `.mov` `.mkv` `.avi` `.m4v` `.mts` `.m2ts`

## 从源码运行

```bash
brew install python@3.11
/opt/homebrew/bin/python3.11 -m pip install PyQt6

# 下载内置用的 ffmpeg/ffprobe 二进制到 bin/
./download_ffmpeg.sh

/opt/homebrew/bin/python3.11 merger.py
```

如果本机已装 ffmpeg（`brew install ffmpeg`），跳过 `download_ffmpeg.sh` 也能跑——程序会按以下顺序找：

1. `.app` 内置的二进制
2. 项目目录下 `bin/ffmpeg`
3. 系统 `PATH`（`shutil.which`）
4. `/opt/homebrew/bin/`、`/usr/local/bin/`

## 打包 DMG

```bash
./download_ffmpeg.sh
/opt/homebrew/bin/python3.11 -m PyInstaller merger.spec
# 然后用 create-dmg 出 dmg
```

## 配置

上次打开的文件夹路径记在 `~/.video_merger_config.json`。删掉这个文件即可重置。

## 同系列工具

- Purple Loop —— 主工具
- VM（本项目）—— 视频合并

## License

个人工具，自用为主。内置的 FFmpeg 二进制来自 [osxexperts.net](https://www.osxexperts.net/)，遵循 GPL/LGPL。

---

**v1.1** · thatgameapple
