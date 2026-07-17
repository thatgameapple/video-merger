# Video Merge（VM）

> Purple Loop 配套小工具。把分段录制的视频拖进来即成「待合并清单」，按时段智能排序后无损拼成一个，方便后续做字幕识别和剪辑。

PyQt6 + FFmpeg。macOS（Apple Silicon）。

## 适用场景

录屏 / 摄像机 / 行车记录仪 类的设备常会把一段长视频切成 `00000.mp4`、`00001.mp4`、`00002.mp4`…… 一堆分段。在做字幕识别或丢进剪辑软件之前，先合成一整条会舒服很多。

VM 用 FFmpeg 的 concat demuxer（`-c copy`）直接拼，不重编码，几乎只受硬盘读写速度限制。

> 前提：所有分段是同一台设备同一次录制切出来的（编码 / 分辨率 / 帧率一致）。混合不同来源的视频请用别的工具。

## 安装

从 [Releases](https://github.com/thatgameapple/video-merger/releases) 下载 `Video Merge_x.x_macos.dmg`，拖进 Applications。

FFmpeg 已内置，**无需额外安装任何东西**。

首次打开如果被 Gatekeeper 拦，去「系统设置 → 隐私与安全性」点「仍要打开」。

## 使用

把视频或文件夹**拖进窗口**即可——列表就是「待合并清单」，里面有什么就按顺序合并什么，不用再勾选。

1. 拖入视频 / 文件夹（或点「添加文件夹」）。拖文件夹会**递归**把里面（含子文件夹，如「某天/上午、下午、晚上」）的视频整批加进来；`._` 元数据文件已过滤。清单里显示的是相对拖入文件夹的路径，所以「上午/clip01」和「晚上/clip01」这种同名片段分得清
2. 清单按 **第几期 → 第几天 → 上午/下午/晚上** 智能排序（认中文数字）；排不准时**直接上下拖动行**手动调序
3. 拖错 / 多拖了点「撤销」去掉最近一批；想重来点「清空」
4. 确认「输出到」和输出文件名 → 点「开始合并」；合并时进度条按时长实时推进，按钮变成「取消合并」，随时可停（半成品会自动清掉）
5. （可选）勾选「合并后删除原文件」，会有二次确认；有文件没删掉会如实告诉你是哪些

**输出位置**：默认落在你拖进来的那个文件夹的**上一级**（跟它并排），文件名默认就是那个文件夹的名字——拖「第3天」进来，默认输出「第3天.mp4」到它旁边。这样成片不会混进素材堆、也不会被下次拖入扫成素材。想放别处点「更改」自己选，选过之后就不再被默认值顶掉。

> 点合并时会先比对各片段的编码 / 分辨率 / 像素格式 / **音频参数**，不一致会弹窗列出差异让你决定。音频参数（采样率 / 声道）不一致尤其要留意：`-c copy` 照样会「合并成功」，但产出的音轨比视频短，音画不同步。
>
> 合并完成后还会扫一遍 FFmpeg 的输出，有时间戳异常 / 坏帧一类的警告会如实报出来——返回成功不等于成片没问题。

合并成功后清单自动清空、准备下一批，**输出位置和文件名保留不动**（如「第3期第2天 左机位」只需手改成「右机位」即可接着合并）。点「清空」才会连输出设置一起重置。

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

上次打开的文件夹、上次选过的输出位置记在 `~/.video_merger_config.json`。删掉这个文件即可重置。

## 同系列工具

- Purple Loop —— 主工具
- Video Merge / VM（本项目）—— 无损把分段视频拼成一条

## License

个人工具，自用为主。内置的 FFmpeg 二进制来自 [osxexperts.net](https://www.osxexperts.net/)，遵循 GPL/LGPL。

---

**v1.5.0** · thatgameapple
