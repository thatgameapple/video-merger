import sys
import os
import re
import json
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog,
    QProgressBar, QLineEdit, QMessageBox, QAbstractItemView, QCheckBox,
    QDialog, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction

VERSION = '1.6.1'
AUTHOR = 'thatgameapple'
APP_NAME = 'Video Merge'
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mts', '.m2ts'}
CONFIG_FILE = Path.home() / '.video_merger_config.json'
DEFAULT_OUT_NAME = '合并输出.mp4'
PATH_ROLE = Qt.ItemDataRole.UserRole          # 行里存的完整路径
BATCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # 行里存的批次号（供「撤销」）
PARAMS_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # 视频+音频关键参数，合并前校验一致性
SECS_ROLE = int(Qt.ItemDataRole.UserRole) + 3   # 时长（秒），求和得总时长供真实进度


IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
# Windows 打包成无控制台的窗口程序后，每起一个 ffmpeg/ffprobe 都会闪一个黑框，
# 拖 30 个片段就闪 30 下。CREATE_NO_WINDOW 让子进程不开控制台。
NO_WINDOW = {'creationflags': subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
UI_FONT = 'Microsoft YaHei UI' if IS_WIN else 'PingFang SC'


def _resolve_binary(name: str) -> str:
    if IS_WIN:
        name += '.exe'
    candidates = []
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(Path(meipass) / name)
        candidates.append(Path(sys.executable).parent / name)
        candidates.append(Path(sys.executable).parent.parent / 'Frameworks' / name)
        candidates.append(Path(sys.executable).parent.parent / 'Resources' / name)
    candidates.append(Path(__file__).parent / 'bin' / name)
    for p in candidates:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    found = shutil.which(name)
    if found:
        return found
    for p in (f'/opt/homebrew/bin/{name}', f'/usr/local/bin/{name}'):
        if os.access(p, os.X_OK):
            return p
    return name


FFMPEG = _resolve_binary('ffmpeg')
FFPROBE = _resolve_binary('ffprobe')

# ── Purple Loop 色板 ──────────────────────────────────────────────
C = {
    'bg':         '#1c1e1f',
    'bg_panel':   '#161819',
    'bg_input':   '#252729',
    'bg_sel':     '#1e3d6e',
    'fg':         '#dfe3df',
    'fg_dim':     '#5a5e5a',
    'fg_hint':    '#3e423e',
    'border':     '#2a2d30',
    'accent':     '#5b9cf6',
    'btn_bg':     '#2a2d30',
    'btn_fg':     '#dfe3df',
    'btn_hover':  '#909090',
    'save_bg':    '#1db070',
    'save_hover': '#25c97e',
    'save_fg':    '#ffffff',
    'danger':     '#c05878',
}

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {C['bg']};
    color: {C['fg']};
    font-family: "{UI_FONT}";
    font-size: 13px;
}}
QLabel {{
    color: {C['fg']};
    background: transparent;
}}
QListWidget {{
    background-color: {C['bg_input']};
    color: {C['fg']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{
    padding: 5px 4px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: {C['bg_sel']};
    color: {C['accent']};
}}
QListWidget::item:alternate {{
    background-color: #202224;
}}
QLineEdit {{
    background-color: {C['bg_input']};
    color: {C['fg']};
    border: 1px solid {C['border']};
    border-radius: 5px;
    padding: 5px 8px;
}}
QLineEdit:focus {{
    border: 1px solid {C['accent']};
}}
QLineEdit:disabled {{
    color: {C['fg_dim']};
    background-color: {C['bg_panel']};
}}
QPushButton {{
    background-color: {C['btn_bg']};
    color: {C['btn_fg']};
    border: 1px solid {C['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: #343739;
    color: {C['fg']};
}}
QPushButton:disabled {{
    color: {C['fg_dim']};
    background-color: {C['bg_input']};
}}
QPushButton#btn_merge {{
    background-color: {C['save_bg']};
    color: {C['save_fg']};
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: bold;
    padding: 10px;
}}
QPushButton#btn_merge:hover {{
    background-color: {C['save_hover']};
}}
QPushButton#btn_merge:disabled {{
    background-color: #1a4035;
    color: #4a7a68;
}}
/* 合并进行中，同一个按钮切成「取消合并」 */
QPushButton#btn_cancel {{
    background-color: {C['btn_bg']};
    color: {C['danger']};
    border: 1px solid {C['danger']};
    border-radius: 8px;
    font-size: 15px;
    font-weight: bold;
    padding: 10px;
}}
QPushButton#btn_cancel:hover {{
    background-color: #3a2a30;
}}
QPushButton#btn_cancel:disabled {{
    color: {C['fg_dim']};
    border-color: {C['border']};
    background-color: {C['bg_input']};
}}
QCheckBox {{
    color: {C['danger']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {C['border']};
    border-radius: 3px;
    background: {C['bg_input']};
}}
QCheckBox::indicator:checked {{
    background-color: {C['danger']};
    border-color: {C['danger']};
}}
QProgressBar {{
    background-color: {C['bg_input']};
    border: 1px solid {C['border']};
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {C['accent']};
    border-radius: 4px;
}}
QScrollBar:vertical {{
    background: {C['bg_input']};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {C['border']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(data):
    try:
        CONFIG_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def get_video_info(path):
    cmd = [
        FFPROBE, '-v', 'quiet', '-print_format', 'json',
        '-show_streams', '-show_format', str(path)
    ]
    # ffprobe 缺失、文件损坏、输出不是 JSON 都只当「读不出信息」，
    # 一律返回 None 让上层显示「?」，不能让拖入动作整个崩掉。
    # 加超时：外接盘半掉线时 ffprobe 会一直挂着，整个拖入动作跟着卡死。
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                encoding='utf-8', errors='replace', **NO_WINDOW)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def format_duration(info):
    try:
        secs = float(info['format']['duration'])
        m, s = divmod(int(secs), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
    except Exception:
        return "?"


def duration_secs(info):
    try:
        return float(info['format']['duration'])
    except Exception:
        return 0.0


def stream_params(info):
    """取视频流 (codec, 宽, 高, 像素格式, 时间基) + 音频流 (codec, 采样率, 声道) + 音轨条数，
    供合并前比对一致性。FFmpeg concat demuxer 的原话是
    "All files must have the same streams (same codecs, same time base, etc.)"——
    时间基（time_base）也在必须一致之列，漏掉它会出静默事故：
    实测同 codec/分辨率/像素格式、仅帧率不同（25fps 时基 1/12800 + 30fps 时基 1/15360）
    的两段各 10 秒素材，合出来视频轨 24 秒、音轨 20 秒，音画错开 4 秒，
    而 ffmpeg 只吐 1 条 DTS 警告（在正常阈值内），事前事后两道防线全放行。

    注意只比时间基、不比帧率：真实素材里 r_frame_rate 是噪声
    （同一堂课的两条片段实测报出 95/4 和 90000/1），拿它做判据会天天误报。"""
    if not info:
        return None
    video = audio = None
    n_audio = 0
    for s in info.get('streams', []):
        kind = s.get('codec_type')
        if kind == 'video' and video is None:
            video = (s.get('codec_name'), s.get('width'), s.get('height'),
                     s.get('pix_fmt'), s.get('time_base'))
        elif kind == 'audio':
            n_audio += 1
            if audio is None:
                audio = (s.get('codec_name'), s.get('sample_rate'),
                         s.get('channels'))
    return (video, audio, n_audio)


def describe_params(p):
    if not p:
        return '未知'
    video, audio, n_audio = p
    if video:
        codec, w, h, pix, tb = video
        vs = f'{codec or "?"}  {w or "?"}×{h or "?"}  {pix or "?"}  时基{tb or "?"}'
    else:
        vs = '无视频轨'
    if audio:
        codec, rate, ch = audio
        vs += f'   ·   {codec or "?"}  {rate or "?"}Hz  {ch or "?"}声道'
        if n_audio > 1:
            vs += f'（{n_audio} 条音轨）'
    else:
        vs += '   ·   无音频轨'
    return vs


def diff_kind(kinds):
    """一组不同的参数里，到底是哪一类对不上？用来把弹窗话说准。
    返回 'timebase'（画面参数全同、只有时间基/帧率不同）/ 'audio' / 'video'。"""
    videos = {k[0] for k in kinds}
    if len(videos) == 1:
        return 'audio'
    # 去掉时间基再比一次：画面参数其实一致，那问题就出在时间基上
    if len({v[:4] if v else None for v in videos}) == 1:
        return 'timebase'
    return 'video'


def list_mismatch(kinds, params, names, per_kind=6):
    """把「参数不一致」弹窗的正文列出来：每种参数下面跟着属于它的文件，
    片段少的那种排前面——混进来的多半就是那一两个，用户一眼看出该撤哪几个。
    只列参数不列文件的话，他还得回清单里挨个猜。"""
    groups = [(k, [n for pp, n in zip(params, names) if pp == k]) for k in kinds]
    groups.sort(key=lambda g: len(g[1]))
    out = []
    for k, ns in groups:
        out.append(f'· {describe_params(k)}   ({len(ns)} 个)')
        out.extend(f'      {n}' for n in ns[:per_kind])
        if len(ns) > per_kind:
            out.append(f'      … 还有 {len(ns) - per_kind} 个')
    return '\n'.join(out)


def plan_timebase_fix(params, files):
    """只有时间基对不上时，能不能无损修？能就返回 (目标 timescale, 要重封装的下标)。

    实测（ffmpeg 8.1）：把少数派片段用 `-c copy -video_track_timescale N` 重封装成
    和大多数一样的时基，视频数据逐字节不变（md5 相同），再 concat 就是对的：
    30fps 两段 + 24fps 一段，直接拼视频轨 4.8s/音轨 6.0s；统一时基后 5.98s/6.02s。
    25fps 混 30fps（15360/25 不整除）同样正确，时间戳只有亚毫秒级舍入。

    目标取多数派的时基（重封装最少）；平手取排最前的。
    只在所有片段的时基都是 1/N、容器都是 mp4/mov 系（-video_track_timescale 是
    mov 系 muxer 的选项，mkv 没有）时才给方案，否则返回 None 不逞强。"""
    tbs = []
    for p, f in zip(params, files):
        if not p or not p[0] or Path(f).suffix.lower() not in ('.mp4', '.m4v', '.mov'):
            return None
        m = re.fullmatch(r'1/(\d+)', str(p[0][4] or ''))
        if not m:
            return None
        tbs.append(m.group(1))
    if len(set(tbs)) < 2:
        return None
    target = max(dict.fromkeys(tbs), key=tbs.count)   # 多数派；平手取最先出现的
    idxs = [i for i, tb in enumerate(tbs) if tb != target]
    return int(target), idxs


def _short_path(p):
    """外接盘路径太长，界面上只显示末两级，全路径挂 tooltip。"""
    parts = Path(p).parts
    return '…' + os.sep + os.path.join(*parts[-2:]) if len(parts) > 3 else str(p)


def _parse_hms(s):
    """'00:00:12.345000' → 12.345 秒；解析失败返回 None。"""
    try:
        h, m, rest = s.split(':')
        return int(h) * 3600 + int(m) * 60 + float(rest)
    except Exception:
        return None


# ── 懂「第几期·第几天·上午/下午/晚上」的智能排序 ───────────────────
# 周老师课程文件名里时段词位置不统一（「左机位第二天下午」「第二天上午A」），
# 纯文件名排序会把上午挤到后面。这里按 期→天→时段→原名 排，得到自然时间序。
_CN_NUM = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
           '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

# 时段词 → 先后秩；同一时段内再按文件名排
_PERIODS = [('凌晨', 0), ('清晨', 1), ('早晨', 2), ('早上', 2),
            ('上午', 3), ('午前', 3), ('中午', 4), ('正午', 4), ('午间', 4),
            ('下午', 5), ('午后', 5), ('傍晚', 6), ('黄昏', 6),
            ('晚上', 7), ('晚间', 7), ('夜里', 7), ('夜晚', 7), ('深夜', 8)]


def _cn_to_int(s):
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if '十' in s:                       # 十一、二十、二十三 …
        a, _, b = s.partition('十')
        return (_CN_NUM.get(a, 1) if a else 1) * 10 + (_CN_NUM.get(b, 0) if b else 0)
    return None


def _num_before(name, unit):
    """取「第X<unit>」「X<unit>」里的数字（阿拉伯或中文），无则 None。
    有多处匹配时取**最后**一处：越靠近文件名越具体。上级文件夹叫
    「三天两夜课程」时，头一处匹配是那个「三天」，会把底下「第一天/第二天」
    全判成第 3 天，天序整个失效。"""
    ms = re.findall(r'第?\s*([0-9零一二三四五六七八九十两]+)\s*' + unit, name)
    return _cn_to_int(ms[-1]) if ms else None


def _period_rank(parts):
    """按路径从深到浅找时段词，最深一级说了算（文件名 > 子文件夹 > 上级）。"""
    for seg in reversed(parts):
        ranks = [r for kw, r in _PERIODS if kw in seg]
        if ranks:
            return min(ranks)
    return 50   # 没有时段词的排在有时段词的之后


def smart_sort_key(path):
    # 用整条路径而非仅文件名：时段词常写在子文件夹名上
    # （如「第3天/上午/clip01.mp4」「第3天/晚上/clip01.mp4」），
    # 只看文件名会把不同时段的同名片段排到一起。
    s = str(path)
    qi = _num_before(s, '期')
    day = _num_before(s, '天')
    return (qi if qi is not None else 0,
            day if day is not None else 0,
            _period_rank(Path(path).parts),
            _natural(s))


def _natural(s):
    """同一时段内按文件名排时，数字按数值比：「上午2」排在「上午10」前面。"""
    return [(0, int(t), '') if t.isdigit() else (1, 0, t)
            for t in re.split(r'(\d+)', s) if t]


# ffmpeg 返回 0 也未必干净。事前的参数校验拦不住未知情况，这是第二道防线。
# 这些一出现就是真问题，不看条数。
_HARD_PATTERNS = ('corrupt', 'Invalid data found', 'could not find codec parameters',
                  'Application provided invalid')
_DTS_PATTERNS = ('non-monotonic dts', 'dts out of order', 'invalid timestamp')


def scan_warnings(err, junctions=0):
    """从 ffmpeg stderr 里挑出值得报的警告，最多 5 条。

    时间戳警告要按条数判，不能见一条就报：AAC 帧长和视频时长对不齐，
    每个拼接点冒 1 条是正常的（实测干净素材 2 片段=1 条、3 片段=2 条），
    见一条就弹框等于每次正常合并都喊狼来了。真出事时是每个音频包都报
    （同样 2 片段，音频参数不一致实测 12 条）。按拼接点放行正常量，超了才报。"""
    lines = err.splitlines()
    hits = []
    dts = [l.strip() for l in lines
           if any(p in l.lower() for p in _DTS_PATTERNS)]
    if len(dts) > max(2 * junctions, 2):
        hits.append(f'{len(dts)} 条时间戳警告，音画可能不同步。例如：\n{dts[0]}')
    for pat in _HARD_PATTERNS:
        for l in lines:
            if pat.lower() in l.lower():
                hits.append(l.strip())
                break
    return hits[:5]


def _fmt_secs(s):
    m, sec = divmod(int(round(s)), 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def verify_output(path, expect_dur=0.0):
    """跑完 ffmpeg 后 ffprobe 复核成片——第三道也是最靠得住的一道防线。
    返回 (硬伤, 警告)：硬伤 = 这次合并算失败，警告 = 交付但要提醒。

    扫 stderr 数警告条数是猜谜，会漏（时间基不一致只吐 1 条，落在正常阈值内）。
    直接量成片本身不会漏，两个判据实测互补：
      · 成片总时长 vs 素材时长之和 —— 短了=有片段没合进去（硬伤）；
        长了=时间基/帧率对不齐（警告，实测 24.0s vs 应有 20.0s）
      · 成片内 视频轨时长 vs 音轨时长 —— 抓音频参数不一致（实测音轨 18.4s vs 视频 20.0s，
        这种情况总时长是对的，只看总时长看不出来）

    「短了」单独判成硬伤，因为它跟另外两种性质不同：
    长了/不同步是**内容都在、但有毛病**，而且多半是用户在事前弹窗里按了「仍要合并」，
    他知情；短了是**内容根本没合进去**（素材损坏、外接盘中途断开），
    ffmpeg 对此不报错、退出码仍是 0，用户从没同意过要一条缺胳膊少腿的成片。

    干净素材实测误差恒为 +0.02 秒左右（末尾音频帧），从不会短，所以
    「短过 1 秒 / 0.5%」判失败不会误伤。"""
    info = get_video_info(path)
    if not info:
        return [], ['成片生成了，但 ffprobe 读不出它的信息，建议手动打开确认一下。']
    bad, warn = [], []
    total = duration_secs(info)
    if expect_dur > 0 and total > 0:
        diff = total - expect_dur
        if diff < -max(1.0, expect_dur * 0.005):
            bad.append(
                f'成片只有 {_fmt_secs(total)}，素材合计应为 {_fmt_secs(expect_dur)}，'
                f'少了 {_fmt_secs(-diff)}。\n'
                '有片段没被合进去——素材损坏，或外接盘中途断开了。\n'
                'ffmpeg 碰到这种情况不会报错、退出码照样是 0，所以这里替它判为失败。')
        elif diff > max(1.0, expect_dur * 0.01):
            warn.append(
                f'成片时长 {_fmt_secs(total)}，素材合计应为 {_fmt_secs(expect_dur)}，'
                f'多了 {_fmt_secs(diff)}。\n'
                '这通常是各片段的时间基 / 帧率不一致，音画会从第二段开始越错越多。')
    v = a = None
    for s in info.get('streams', []):
        try:
            d = float(s.get('duration'))
        except (TypeError, ValueError):
            continue                       # mkv 等容器常没有单流时长，跳过即可
        if s.get('codec_type') == 'video' and v is None:
            v = d
        elif s.get('codec_type') == 'audio' and a is None:
            a = d
    if v and a and abs(v - a) > 1.0:
        warn.append(
            f'成片里视频轨 {_fmt_secs(v)}、音轨 {_fmt_secs(a)}，相差 {abs(v - a):.1f} 秒，'
            '音画不同步。')
    return bad, warn


# ffmpeg 靠输出文件的扩展名猜容器格式。成片先写成临时名再改名，临时名的后缀
# 它认不出来（实测直接报 Error initializing the muxer: Invalid argument），
# 所以必须按目标扩展名显式给 -f。
MUX_FORMAT = {'.mp4': 'mp4', '.m4v': 'mp4', '.mov': 'mov', '.mkv': 'matroska'}


class MergeWorker(QThread):
    # 百分比 0-100；-1 表示无法估算总时长，走不确定进度（转圈）
    progress = pyqtSignal(int)
    status = pyqtSignal(str)                 # 阶段文字（统一时基 1/2：xxx）
    finished = pyqtSignal(bool, str, str)   # 成功?, 输出路径/错误, 警告文本

    def __init__(self, files, output, total_dur=0.0, expect_dur=0.0, fix_tb=None,
                 secs=None):
        super().__init__()
        self.files = files
        self.secs = secs or []          # 各片段时长，统一时基阶段报进度用
        self.output = Path(output)
        # (目标 timescale, 要先无损重封装的片段下标)，见 plan_timebase_fix；None = 不修
        self.fix_tb = fix_tb
        self.total_dur = total_dur      # 供进度条；有片段读不出时长也照用（只是不准）
        # 供成片复核。有片段读不出时长时它必须是 0：拿「少算了一段」的和去比，
        # 成片必然「多出一截」，会误报成时间基不一致，而且恰好是用户刚被告知
        # 「合并后会再复核一遍」的那种情况，误报最伤信任。
        self.expect_dur = expect_dur
        self._proc = None
        self._cancelled = False
        self._ok = False          # ffmpeg 真的跑成了？没成才允许清残片
        # 先写临时名、成了再改回去：ffmpeg 从头到尾碰不到目标文件，于是
        # 失败/取消/中途关窗都毁不掉已有的同名成片，也不会在素材目录留残片。
        # 临时名以「.」开头 + 非视频后缀：万一真留下了，既不显眼也不会被当素材扫进来。
        self.tmp = self.output.with_name('.' + self.output.name + '.vmpart')

    def stop(self):
        self._cancelled = True
        p = self._proc
        if p and p.poll() is None:
            p.terminate()
            # 不理 SIGTERM 就补一刀，免得关窗后留个孤儿 ffmpeg 继续写盘
            t = threading.Timer(3.0, lambda: p.poll() is None and p.kill())
            t.daemon = True
            t.start()

    def _run_ffmpeg(self, cmd, dur=0.0):
        """跑一个 ffmpeg，返回 (returncode, stderr 全文)。
        dur > 0 时按 -progress pipe:1 吐出的 out_time 报百分比；stderr 另存文件，
        失败时读回尾部报错（避免 PIPE 塞满死锁）。
        errors='replace'：素材带非 UTF-8 元数据（摄像机的 GBK 中文 tag 等）时，
        ffmpeg 会把原始字节刷进 stderr，严格解码会在这里抛 UnicodeDecodeError。"""
        errf = tempfile.NamedTemporaryFile(mode='w+', suffix='.log', delete=False,
                                           encoding='utf-8', errors='replace')
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=errf, text=True, **NO_WINDOW)
            if self._cancelled:
                # stop() 赶在 Popen 之前到了（点取消/关窗极快时会撞上）：那时
                # _proc 还是 None、没东西可 terminate，ffmpeg 会照常跑完整场。
                self._proc.terminate()
            last = 0
            for line in self._proc.stdout:
                if dur <= 0:
                    continue
                line = line.strip()
                sec = None
                if line.startswith(('out_time_us=', 'out_time_ms=')):
                    v = line.split('=', 1)[1]
                    if v.isdigit():           # 这两个键单位都是微秒
                        sec = int(v) / 1_000_000
                elif line.startswith('out_time='):
                    sec = _parse_hms(line.split('=', 1)[1])
                if sec is not None:
                    pct = max(0, min(99, int(sec / dur * 100)))
                    if pct != last:
                        last = pct
                        self.progress.emit(pct)
            self._proc.stdout.close()
            self._proc.wait()
            try:
                errf.seek(0)
                err = errf.read()
            except Exception:
                err = ''     # 读不出 stderr 只是少了警告线索，绝不能因此把成片判成失败
            return self._proc.returncode, err
        finally:
            errf.close()
            try:
                os.unlink(errf.name)
            except Exception:
                pass

    def run(self):
        list_file = None
        fixed = []      # 统一时基时重封装出的临时文件，不管成败最后都清
        files = list(self.files)
        try:
            # ── 阶段一（可选）：把少数派片段无损重封装成多数派的时基 ──
            # 临时文件放输出目录（跟成片同盘，几个 GB 的课程录像放系统盘 tmp 会塞满），
            # 「.」开头 + 视频后缀前插 vmfix：隐藏，且下次拖入文件夹不会被扫到。
            if self.fix_tb:
                scale, idxs = self.fix_tb
                for k, i in enumerate(idxs, 1):
                    src = files[i]
                    dst = self.output.with_name(
                        f'.{self.output.stem}.vmfix{i}{src.suffix.lower()}')
                    fixed.append(dst)
                    self.status.emit(f'正在统一时基 {k}/{len(idxs)}：{src.name}')
                    d = self.secs[i] if i < len(self.secs) else 0.0
                    self.progress.emit(0 if d > 0 else -1)
                    # 只带视频+音频：concat 关心的就这两种；摄像机的 tmcd 之类数据轨
                    # 换容器时会让 muxer 报错，不值得为它冒险。
                    rc, err = self._run_ffmpeg([
                        FFMPEG, '-nostdin', '-y', '-i', str(src),
                        '-map', '0:v', '-map', '0:a?', '-c', 'copy',
                        '-video_track_timescale', str(scale),
                        '-progress', 'pipe:1', '-nostats',
                        '-f', MUX_FORMAT.get(src.suffix.lower(), 'mp4'), str(dst)
                    ], dur=d)
                    if rc != 0:
                        if self._cancelled:
                            self.finished.emit(False, '已取消', '')
                        else:
                            self.finished.emit(
                                False, f'统一时基失败（{src.name}）：\n'
                                       + (err[-500:] or '未知错误'), '')
                        return
                    files[i] = dst

            # ── 阶段二：concat ──
            self.status.emit('正在合并')
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                             delete=False, encoding='utf-8') as f:
                for fp in files:
                    # 统一用正斜杠：Windows 的 ffmpeg 认 C:/a/b.mp4，反斜杠在清单语法里是转义符
                    escaped = Path(fp).as_posix().replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")
                list_file = f.name

            self.progress.emit(0 if self.total_dur > 0 else -1)
            # -nostdin：ffmpeg 默认会去抢父进程的 stdin，标准做法是关掉。
            mux = MUX_FORMAT.get(self.output.suffix.lower(), 'mp4')
            rc, err = self._run_ffmpeg([
                FFMPEG, '-nostdin', '-y', '-f', 'concat', '-safe', '0',
                '-i', list_file, '-c', 'copy', '-progress', 'pipe:1',
                '-nostats', '-f', mux, str(self.tmp)
            ], dur=self.total_dur)

            if rc == 0:
                # 复核放在改名之前，验的是临时文件：查出硬伤就根本不改名，
                # 目标位置（可能是上一条成片）连碰都没碰过。
                self.status.emit('正在复核成片')
                self.progress.emit(-1)
                bad, warns = verify_output(self.tmp, self.expect_dur)
                if bad:
                    # 缺内容 = 这次合并没成，别当成功交付，也别让它走到「删原文件」那一步。
                    # 半成品不删：万一判断有偏差，东西还在，路径一并告诉用户。
                    self._ok = True      # 借这个标记挡住 finally 里的清理，别删它
                    self.finished.emit(
                        False, '\n\n'.join(bad) +
                        f'\n\n目标位置没有被改动。这次的半成品留在：\n{self.tmp}\n'
                        '（隐藏文件，不会被下次拖入当素材；重合一次就会自动覆盖掉）',
                        'incomplete')
                    return
                self._ok = True          # 从这里起，那份成片不许再被任何异常清掉
                try:
                    os.replace(self.tmp, self.output)   # 同目录，原子且瞬间完成
                except Exception as e:
                    self.finished.emit(
                        False, f'合并本身成功了，但改名到目标位置失败：{e}\n\n'
                               f'成片还在这里，可自己改名取走：\n{self.tmp}', '')
                    return
                self.progress.emit(100)
                self.finished.emit(True, str(self.output),
                                   '\n\n'.join(scan_warnings(err, len(files) - 1)
                                               + warns))
            else:
                # 失败/取消时 ffmpeg 留下的是临时文件，清掉它，目标位置从没被碰过
                self._discard_partial()
                if self._cancelled:
                    self.finished.emit(False, '已取消', '')
                else:
                    self.finished.emit(False, (err[-500:] or '未知错误'), '')
        except Exception as e:
            self._discard_partial()
            self.finished.emit(False, str(e), '')
        finally:
            for p in [list_file] + fixed:
                if p:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass

    def _discard_partial(self):
        """只清临时文件，且只在 ffmpeg 没成功时清。
        以前是无条件删 self.output——ffmpeg 明明成功了、只是收尾环节抛了个异常，
        也会把刚合好的成片删掉，然后报「合并失败」。"""
        if self._ok:
            return
        try:
            self.tmp.unlink(missing_ok=True)
        except Exception:
            pass


class DropListWidget(QListWidget):
    """行内拖动可调序；外部文件/文件夹拖入则转交回调（add_paths）处理。"""

    def __init__(self, on_external, on_remove):
        super().__init__()
        self._on_external = on_external
        self._on_remove = on_remove
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        # 可多选（⇧/⌘ 点选）：一次移除好几个混进来的片段
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._on_remove()
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        if not self.selectedItems() or self.dragDropMode() == \
                QAbstractItemView.DragDropMode.NoDragDrop:   # 合并中锁着
            return
        menu = QMenu(self)
        n = len(self.selectedItems())
        menu.addAction(f'从清单移除{f"（{n} 个）" if n > 1 else ""}', self._on_remove)
        menu.exec(event.globalPos())

    def _is_external(self, event):
        return event.mimeData().hasUrls() and event.source() is not self

    def dragEnterEvent(self, event):
        if self._is_external(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._is_external(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self._is_external(event):
            paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
            if paths:
                self._on_external(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Video Merge')
        self.setMinimumSize(720, 520)
        self.config = load_config()
        self._next_batch = 0   # 递增批次号，每次拖入/添加一批 +1，供「撤销」
        self._merging = False  # 合并中：拦住「开始合并」，否则两个 ffmpeg 会抢写同一输出
        self._adding = False   # 读取信息中：拦住重入，否则两批会共用一个批次号
        self._src_name = ''       # 第一批拖入的来源名，仅供顶部显示
        self._out_dir = None      # 输出目录；None = 还没有清单，等第一批拖入来定
        self._dir_chosen = False  # 用户自己选过输出目录 → 后续拖入不再改动它
        self._name_edited = False # 用户手打过输出名 → 不再套默认名
        self._name_auto = ''      # 上次自动套上的名字；只有它才允许被下一批顶掉
        self._closing = False     # 关窗了：读取信息的循环要立刻停，别拖着进程不退
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_appmenu()

    def _build_appmenu(self):
        """「帮助」菜单里放「关于 Video Merge」→ 弹品牌卡片。用 NoRole 显式阻止 Qt 的
        文本启发式把它当 AboutRole 合并进应用菜单——实测打包版合并后那个项反而
        不触发我们的槽（关于卡片打不开），且帮助菜单会整个消失。NoRole 让它老实
        留在帮助菜单，纯 Qt signal 触发，开发/打包都稳定（PL 也是从帮助菜单打开
        关于）。原生的「服务/隐藏/退出」由系统提供。"""
        mb = self.menuBar()
        hm = mb.addMenu('帮助')
        about = QAction(f'关于 {APP_NAME}', self)
        about.setMenuRole(QAction.MenuRole.NoRole)
        about.triggered.connect(self._open_about)
        hm.addAction(about)
        # 删掉 Qt 往应用菜单塞的英文/无用默认项（About Qt、首选项）；Windows 没有应用菜单
        if IS_MAC:
            QTimer.singleShot(0, self._localize_native_appmenu)

    def _open_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f'关于 {APP_NAME}')
        dlg.setFixedWidth(340)
        dlg.setStyleSheet(f"QDialog {{ background: {C['bg']}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(30, 28, 30, 26)
        lay.setSpacing(5)

        def _lbl(text, size, color, family=UI_FONT):
            l = QLabel(text)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setStyleSheet(f"color:{color}; font-size:{size}px; font-family:'{family}';")
            return l

        lay.addWidget(_lbl(APP_NAME, 21, C['accent']))
        lay.addWidget(_lbl(f'v{VERSION}', 12, C['fg_dim']))
        lay.addSpacing(12)
        lay.addWidget(_lbl('专为剪辑设计的视频无损合并工具', 12, C['fg']))
        lay.addWidget(_lbl('无损拼接 · 编码校验 · 服务 PR 剪辑', 11, C['fg_dim']))
        lay.addSpacing(14)
        lay.addWidget(_lbl(f'© 2026 · {AUTHOR}', 10, C['fg_dim']))
        dlg.exec()

    def _localize_native_appmenu(self):
        """删掉 Qt 往 macOS 应用菜单塞的英文/无用默认项（About Qt、首选项），并整理分隔线。
        纯锦上添花——用 ObjC 运行时直接改原生菜单；任何异常都静默跳过，绝不影响启动。"""
        try:
            import ctypes, ctypes.util
            objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc'))
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]

            def msg(o, s, *a, rt=ctypes.c_void_p, at=None):
                objc.objc_msgSend.restype = rt
                objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + (at or [])
                return objc.objc_msgSend(o, objc.sel_registerName(s.encode()), *a)

            NSApp = msg(objc.objc_getClass(b'NSApplication'), 'sharedApplication')
            appmenu = msg(msg(msg(NSApp, 'mainMenu'),
                              'itemAtIndex:', 0, at=[ctypes.c_long]), 'submenu')
            if not appmenu:
                return

            def titles():
                n = msg(appmenu, 'numberOfItems', rt=ctypes.c_long)
                out = []
                for i in range(n):
                    u = msg(msg(msg(appmenu, 'itemAtIndex:', i, at=[ctypes.c_long]),
                                'title'), 'UTF8String', rt=ctypes.c_char_p)
                    out.append(u.decode() if u else '')
                return out

            for target in ('About Qt', '首选项...', 'Preferences...'):
                for i, t in enumerate(titles()):
                    if t == target:
                        msg(appmenu, 'removeItemAtIndex:', i, at=[ctypes.c_long])
                        break

            # 整理分隔线：去掉开头的、以及连续重复的分隔线
            i = 0
            while i < msg(appmenu, 'numberOfItems', rt=ctypes.c_long):
                it = msg(appmenu, 'itemAtIndex:', i, at=[ctypes.c_long])
                is_sep = bool(msg(it, 'isSeparatorItem', rt=ctypes.c_bool))
                prev_sep = (i == 0)
                if i > 0:
                    pit = msg(appmenu, 'itemAtIndex:', i - 1, at=[ctypes.c_long])
                    prev_sep = bool(msg(pit, 'isSeparatorItem', rt=ctypes.c_bool))
                if is_sep and prev_sep:
                    msg(appmenu, 'removeItemAtIndex:', i, at=[ctypes.c_long])
                else:
                    i += 1
        except Exception:
            pass

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 顶部：文件夹路径 + 选择按钮
        top = QHBoxLayout()
        self.folder_label = QLabel('把视频或文件夹拖进来（或点右边添加文件夹）')
        self.folder_label.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        self.folder_label.setWordWrap(False)
        self.btn_folder = QPushButton('添加文件夹')
        self.btn_folder.clicked.connect(self.choose_folder)
        top.addWidget(self.folder_label, 1)
        top.addWidget(self.btn_folder)
        layout.addLayout(top)

        # 分割线
        line = QWidget()
        line.setFixedHeight(1)
        line.setStyleSheet(f'background: {C["border"]};')
        layout.addWidget(line)

        # 操作按钮行
        btn_row = QHBoxLayout()
        self.btn_undo = QPushButton('撤销')
        self.btn_undo.setToolTip('去掉最近添加的一批')
        self.btn_clear = QPushButton('清空')
        self.btn_clear.setToolTip('清空整个待合并清单')
        self.btn_undo.clicked.connect(self.undo)
        # 走 lambda：clicked 会把 checked=False 当成 reset_output 传进去
        self.btn_clear.clicked.connect(lambda: self.clear_list(reset_output=True))
        self.btn_undo.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.count_label = QLabel('共 0 个待合并')
        self.count_label.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        btn_row.addWidget(self.btn_undo)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(self.count_label)
        layout.addLayout(btn_row)

        # 文件列表
        self.list_widget = DropListWidget(self.add_paths, self.remove_selected)
        self.list_widget.setAlternatingRowColors(True)
        # 手动拖动调序后，刷新状态（首个文件决定输出目录）
        self.list_widget.model().rowsMoved.connect(lambda *a: self._refresh_state())
        layout.addWidget(self.list_widget, 1)

        # 分割线
        line2 = QWidget()
        line2.setFixedHeight(1)
        line2.setStyleSheet(f'background: {C["border"]};')
        layout.addWidget(line2)

        # 输出到（目录）
        dir_row = QHBoxLayout()
        dir_lbl = QLabel('输出到')
        dir_lbl.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        dir_row.addWidget(dir_lbl)
        self.out_dir_label = QLabel('—')
        self.out_dir_label.setStyleSheet(f'color: {C["fg"]}; font-size: 12px;')
        dir_row.addWidget(self.out_dir_label, 1)
        self.btn_out_dir = QPushButton('更改')
        self.btn_out_dir.setToolTip('自己选一个输出位置')
        self.btn_out_dir.clicked.connect(self.choose_out_dir)
        dir_row.addWidget(self.btn_out_dir)
        layout.addLayout(dir_row)

        # 输出文件名
        out_row = QHBoxLayout()
        lbl = QLabel('输出文件名')
        lbl.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        out_row.addWidget(lbl)
        self.out_name = QLineEdit(DEFAULT_OUT_NAME)
        # 只认手打（setText 不触发 textEdited），手改过就不再被默认名覆盖
        self.out_name.textEdited.connect(lambda *_: setattr(self, '_name_edited', True))
        out_row.addWidget(self.out_name, 1)
        layout.addLayout(out_row)

        # 删除原文件选项
        self.delete_check = QCheckBox('合并完成后删除原文件')
        layout.addWidget(self.delete_check)

        # 合并按钮
        self.btn_merge = QPushButton('开始合并')
        self.btn_merge.setObjectName('btn_merge')
        self.btn_merge.setEnabled(False)
        self.btn_merge.setFixedHeight(46)
        self.btn_merge.clicked.connect(self._on_merge_clicked)
        layout.addWidget(self.btn_merge)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 状态文字
        self.status = QLabel('')
        self.status.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        layout.addWidget(self.status)

        # 底部署名
        footer = QLabel(f'v{VERSION}  ·  {AUTHOR}')
        footer.setStyleSheet(f'color: {C["fg_hint"]}; font-size: 11px;')
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(footer)

    def choose_folder(self):
        start = self.config.get('last_folder', str(Path.home()))
        start_path = Path(start)
        while start_path != start_path.parent and not start_path.exists():
            start_path = start_path.parent
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹', str(start_path))
        if not folder:
            return
        if self.add_paths([Path(folder)]) == 0:
            self.status.setText('该文件夹没有可添加的视频（或已在清单里）')

    def choose_out_dir(self):
        start = str(self._out_dir) if self._out_dir else self.config.get(
            'last_out_dir', str(Path.home()))
        start_path = Path(start)
        while start_path != start_path.parent and not start_path.exists():
            start_path = start_path.parent
        folder = QFileDialog.getExistingDirectory(self, '输出到哪个文件夹', str(start_path))
        if not folder:
            return
        self._out_dir = Path(folder)
        self._dir_chosen = True          # 自己选过就别再被拖入的默认值顶掉
        self.config['last_out_dir'] = folder
        save_config(self.config)
        self._refresh_state()

    # 合并中一律不收新素材：合的是点下按钮那一刻的清单快照，这时候拖进来的
    # 既进不了这次合并，还会在合完自动清空时被一并抹掉，等于白拖。
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self._merging:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() and not self._merging:
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self._merging:
            return
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return
        self.add_paths(paths)
        event.acceptProposedAction()

    def _gather_videos(self, paths):
        """把拖入/选中的路径展开成 (拖入的根, 视频文件)，按时段智能排序。
        文件夹会递归到所有子文件夹（周老师课程常按机位/天分子目录），
        排除所有「.」开头的隐藏文件：macOS 的 ._ 资源叉，以及本工具万一崩溃
        留下的 .xxx.vmfix0.mp4（后缀是 .mp4，只排 ._ 会被当素材扫进来）。带上「根」是为了在清单里显示
        相对路径（同名的「上午/clip01」「晚上/clip01」才分得清），
        并据此决定默认输出位置。直接拖文件的根为 None。"""
        found = []
        for p in paths:
            if p.is_dir():
                found.extend(
                    (p, f) for f in p.rglob('*')
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTS
                    and not f.name.startswith('.'))
            elif (p.is_file() and p.suffix.lower() in VIDEO_EXTS
                  and not p.name.startswith('.')):
                found.append((None, p))
        return sorted(found, key=lambda rf: smart_sort_key(rf[1]))

    @staticmethod
    def _row_label(root, f, dur):
        """清单行文字。拖文件夹进来的按相对根的路径显示——
        「第3天/上午/clip01.mp4」「第3天/晚上/clip01.mp4」只显示文件名会一模一样。"""
        try:
            name = str(f.relative_to(root)) if root else f.name
        except Exception:
            name = f.name
        return f'  {name}    {dur}'

    def add_paths(self, paths):
        """把拖入/选中的视频追加到清单末尾，去重；返回本次实际新增的数量。"""
        if self._adding or self._merging:  # 读取信息时 processEvents 会让新的拖入重入这里
            return 0
        self._adding = True
        self._refresh_state()      # 读取期间先按住「开始合并」，清单还没长齐
        try:
            return self._add_paths(paths)
        finally:
            self._adding = False
            self._refresh_state()

    def _add_paths(self, paths):
        videos = self._gather_videos(paths)
        # 这批是往空清单里加的？是的话默认输出名/位置该重新按它算
        was_empty = self.list_widget.count() == 0
        existing = {self.list_widget.item(i).data(PATH_ROLE)
                    for i in range(self.list_widget.count())}
        self.status.setText('正在读取文件信息...')
        QApplication.processEvents()
        added = 0
        bid = self._next_batch
        todo = list({str(f): (root, f) for root, f in videos
                     if str(f) not in existing}.values())
        # ffprobe 放进后台线程池，几个一起读：以前是主线程一个一个读，
        # 外接盘慢的时候每读一个界面就僵一下，半掉线时能僵到 ffprobe 超时（120 秒）。
        # 结果仍按清单顺序逐个收，排序不受谁先读完影响。
        pool = ThreadPoolExecutor(max_workers=4)
        futs = [pool.submit(get_video_info, f) for _, f in todo]
        try:
            for idx, ((root, f), fut) in enumerate(zip(todo, futs), 1):
                self.status.setText(f'正在读取文件信息... {idx}/{len(todo)}')
                info = self._wait_future(fut)
                if self._closing:
                    break      # 窗口已关，剩下的不读了，让 app 立刻退出
                added += self._append_item(root, f, info, bid)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        self.status.setText('')
        if added:
            self._next_batch += 1
            # 记拖入文件夹的上一级：下次点「添加文件夹」正好落在「第3天」「第4天」并排处
            r0, f0 = todo[0]
            self.config['last_folder'] = str(r0.parent if r0 else f0.parent)
            save_config(self.config)
            self._apply_default_output(todo[0][0], todo[0][1], was_empty)
        return added

    def _wait_future(self, fut):
        """等后台 ffprobe 出结果，等的时候一直让出事件循环，界面不僵。"""
        while not self._closing:
            try:
                return fut.result(timeout=0.03)
            except FutTimeout:
                QApplication.processEvents()
            except Exception:
                return None
        return None

    def _append_item(self, root, f, info, bid):
        dur = format_duration(info) if info else '?'
        item = QListWidgetItem(self._row_label(root, f, dur))
        item.setData(PATH_ROLE, str(f))
        item.setData(BATCH_ROLE, bid)
        item.setData(PARAMS_ROLE, stream_params(info))
        item.setData(SECS_ROLE, duration_secs(info))
        self.list_widget.addItem(item)
        return 1

    def _apply_default_output(self, root, first, was_empty):
        """定默认输出位置/文件名：拖「第3天」文件夹 → 输出「第3天.mp4」到它的上一级
        （跟文件夹并排，不混进素材、也不会被下次拖入扫到）；直接拖文件 → 落文件旁边。

        往空清单里加时才重算——合完一批后清单会自动清空但输出名留着，这时候拖入
        「第3天」，名字若还挂在上一批的「第2天.mp4」上，点合并就只弹一句
        「第2天.mp4 已存在，覆盖吗」，顺手一点昨天的成片就没了。
        往非空清单里追加则不动，免得两个文件夹合成一条时名字被后拖的那个顶掉。

        用户手打过的名字（_name_edited）永远不碰——「左机位改成右机位接着合」
        那套用法正是靠它保住的。"""
        if not self._src_name:
            self._src_name = root.name if root else first.parent.name
        if not self._dir_chosen and (self._out_dir is None or was_empty):
            self._out_dir = root.parent if root else first.parent
        if (root and was_empty and not self._name_edited
                and self.out_name.text() in (DEFAULT_OUT_NAME, self._name_auto)):
            self._name_auto = f'{root.name}.mp4'
            self.out_name.setText(self._name_auto)

    def undo(self):
        """删掉最近添加的那一批（按批次号，手动调过序也准）。"""
        n = self.list_widget.count()
        ids = [b for i in range(n)
               if (b := self.list_widget.item(i).data(BATCH_ROLE)) is not None]
        if not ids:
            return
        last = max(ids)
        for i in range(n - 1, -1, -1):
            if self.list_widget.item(i).data(BATCH_ROLE) == last:
                self.list_widget.takeItem(i)
        if self.list_widget.count() == 0:
            self._src_name = ''    # 撤到空了，别让下一批还顶着上一批的来源名
        self._refresh_state()

    def remove_selected(self):
        """移除选中的几行（只是移出清单，不碰文件）。批次「撤销」管不到的情况靠它：
        一个文件夹里混进一条学员分享 / 别的机位，单独拿掉就行，不用整批撤了重拖。"""
        if self._merging or self._adding:
            return
        rows = sorted((self.list_widget.row(it) for it in self.list_widget.selectedItems()),
                      reverse=True)
        for r in rows:
            self.list_widget.takeItem(r)
        if self.list_widget.count() == 0:
            self._src_name = ''
        self._refresh_state()

    def clear_list(self, reset_output=True):
        """清空清单。reset_output=False 用于合并成功后的自动清空——那时要留住
        输出位置和文件名，好让「第3期第2天 左机位」改两个字接着合右机位。"""
        self.list_widget.clear()
        self._next_batch = 0
        self._src_name = ''
        if reset_output:
            self._out_dir = None
            self._dir_chosen = False
            self._name_edited = False
            self._name_auto = ''
            self.out_name.setText(DEFAULT_OUT_NAME)
        self._refresh_state()

    def _refresh_state(self):
        n = self.list_widget.count()
        secs = [self.list_widget.item(i).data(SECS_ROLE) or 0 for i in range(n)]
        total = (f' · 合计 {_fmt_secs(sum(secs))}' + ('+?' if not all(secs) else '')
                 if n and any(secs) else '')
        self.count_label.setText(f'共 {n} 个待合并{total}')
        self.count_label.setToolTip('可上下拖动调序；选中后按 Delete 或右键可单独移除'
                                    if n else '')
        if self._merging:
            self.btn_merge.setEnabled(True)      # 合并中它是「取消」，永远可点
        else:
            self.btn_merge.setEnabled(n >= 2 and not self._adding)
        # 合并中锁住清单：改了也影响不到这次合并，合完还会被自动清空
        self.btn_undo.setEnabled(n > 0 and not self._merging)
        self.btn_clear.setEnabled(n > 0 and not self._merging)
        # 读取中也锁：读取时 processEvents 会放行点击，这时点开文件夹对话框
        # 会被 add_paths 的重入保护挡回去，白选一趟还提示「没有可添加的视频」
        self.btn_folder.setEnabled(not self._merging and not self._adding)
        self.folder_label.setText(
            f'来自「{self._src_name}」 · 可拖动调序，Delete 移除选中' if n and self._src_name
            else ('可拖动调序，Delete 移除选中' if n
                  else '把视频或文件夹拖进来（或点右边添加文件夹）'))
        self.out_dir_label.setText(_short_path(self._out_dir) if self._out_dir else '—')
        self.out_dir_label.setToolTip(str(self._out_dir) if self._out_dir else '')

    def _set_merge_mode(self, merging):
        """合并中把「开始合并」这一个按钮切成「取消合并」——不另加控件占地方。"""
        self.btn_merge.setText('取消合并' if merging else '开始合并')
        self.btn_merge.setObjectName('btn_cancel' if merging else 'btn_merge')
        self.btn_merge.style().unpolish(self.btn_merge)
        self.btn_merge.style().polish(self.btn_merge)
        self.btn_out_dir.setEnabled(not merging)
        self.out_name.setEnabled(not merging)
        # 连列表本身的拖入/调序一起锁掉，不然拖进去的会在合完自动清空时被抹掉
        self.list_widget.setDragDropMode(
            QAbstractItemView.DragDropMode.NoDragDrop if merging
            else QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setAcceptDrops(not merging)
        self._refresh_state()

    def _on_merge_clicked(self):
        if self._merging:
            self.btn_merge.setEnabled(False)   # 防连点，等 worker 收尾
            self.status.setText('正在取消…')
            self.worker.stop()
        else:
            self.start_merge()

    @staticmethod
    def _same_file(a, b):
        """同一个文件？output 通常还不存在，samefile 会抛，退回比对绝对路径。"""
        try:
            return a.resolve() == b.resolve()
        except Exception:
            return os.path.abspath(a) == os.path.abspath(b)

    def start_merge(self):
        # _adding 期间清单还在长（读取时 processEvents 会放行点击），
        # 这时候合出来的会是半份清单。
        n = self.list_widget.count()
        if n < 2 or self._merging or self._adding:
            return
        files = [Path(self.list_widget.item(i).data(PATH_ROLE))
                 for i in range(n)]
        # 开工前确认素材都还在。实测 ffmpeg 8.1 碰到读不到的片段并不报错，
        # stderr 里只留一句 Error during demuxing，**退出码仍是 0**，
        # 后面所有片段被直接跳过，产出一条被截断的成片却显示「合并成功」。
        # 外接盘中途断开、素材被移走/改名都会撞上，所以拦在这里。
        missing = [f for f in files if not f.exists()]
        if missing:
            QMessageBox.critical(
                self, '有素材读不到了',
                f'{len(missing)} 个片段现在读不到（外接盘断开？被移走或改名了？）：\n\n'
                + '\n'.join(f'· {f.name}' for f in missing[:8])
                + ('\n…' if len(missing) > 8 else '')
                + '\n\n这种情况 ffmpeg 不会报错，会跳过它们照样合出一条短片子，'
                  '所以先拦住。请确认硬盘和素材都在，再重新拖入。')
            return
        out_dir = self._out_dir or files[0].parent
        if not out_dir.is_dir():
            QMessageBox.critical(
                self, '输出位置不可用',
                f'输出文件夹不存在或已断开：\n{out_dir}\n\n请点「更改」重新选一个。')
            return
        # 拖的是外接盘根目录时，默认输出位置会落到 /Volumes 这种写不进的地方，
        # 不拦的话要等 ffmpeg 跑起来才报一句 Permission denied。
        if not os.access(out_dir, os.W_OK):
            QMessageBox.critical(
                self, '输出位置不可写',
                f'没有权限往这个文件夹写文件：\n{out_dir}\n\n请点「更改」换一个。')
            return

        out_name = self.out_name.text().strip() or DEFAULT_OUT_NAME
        # 认后缀要不分大小写：手打「第3天.MP4」不该变成「第3天.MP4.mp4」
        if Path(out_name).suffix.lower() not in MUX_FORMAT:
            out_name += '.mp4'
        output = out_dir / out_name

        # 输出名撞上清单里的素材 → ffmpeg 会边读边写，把这个原文件毁掉。
        # 拦在这里，不给「覆盖吗」的机会。
        if any(self._same_file(f, output) for f in files):
            QMessageBox.critical(
                self, '输出名与素材重名',
                f'「{out_name}」正是待合并清单里的一个原文件，'
                '这样合并会把它边读边写、直接损坏。\n\n请换一个输出文件名。')
            return

        if output.exists():
            reply = QMessageBox.question(
                self, '文件已存在',
                f'{out_name} 已存在，覆盖吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # 编码一致性校验：concat -c copy 要求各片段视频+音频参数一致。
        # 视频不一致会失败或花屏；音频不一致更阴——ffmpeg 照样报成功，
        # 产出的音轨比视频短，音画不同步，剪到一半才发现。
        params = [self.list_widget.item(i).data(PARAMS_ROLE) for i in range(n)]
        kinds = []
        for p in params:
            if p and p not in kinds:
                kinds.append(p)
        unknown = sum(1 for p in params if not p)
        # 读不出参数的片段（清单里时长显示「?」）校验不了，得说清楚，不能装作查过
        tail = (f'\n\n另有 {unknown} 个片段读不出编码信息（清单里时长显示「?」），'
                '这几个没法校验。' if unknown else '')
        names = [self.list_widget.item(i).text().strip().rsplit('    ', 1)[0]
                 for i in range(n)]
        fix_tb = None
        if len(kinds) > 1:
            listed = list_mismatch(kinds, params, names)
            head = {
                'audio': '这些片段的音频参数不一致（画面参数是一致的），'
                         '无损合并会产出音画不同步的成片：',
                'timebase': '这些片段的时间基不一致（编码 / 分辨率 / 像素格式都是一致的，'
                            '通常是帧率不同或换了机器录）。ffmpeg 对这种情况照样报成功，'
                            '但成片会比素材长出一截、音画从第二段起越错越多：',
                'video': '这些片段的编码 / 分辨率 / 像素格式 / 音频参数不完全一致，'
                         '无损合并（-c copy）可能失败、花屏或音画不同步：',
            }[diff_kind(kinds)]
            fix = (plan_timebase_fix(params, files)
                   if diff_kind(kinds) == 'timebase' and not unknown else None)
            if fix:
                # 只有时基不同 → 能无损修：先把少数派重封装成多数派的时基再拼。
                # 这里把「修」放成默认键，「直接合并」是明知会出坏片的那条路。
                n_fix = len(fix[1])
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle('参数不一致')
                box.setText(
                    f'{head}\n\n{listed}\n\n'
                    f'可以先把少数的那 {n_fix} 个片段无损重封装成一样的时基再合并：'
                    '不重编码、画面数据逐字节不变，只多花一次读写的时间。'
                    '临时文件放在输出文件夹里（隐藏），合完自动删。')
                b_fix = box.addButton('统一时基后合并', QMessageBox.ButtonRole.AcceptRole)
                b_raw = box.addButton('仍要直接合并', QMessageBox.ButtonRole.DestructiveRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.setDefaultButton(b_fix)
                box.exec()
                if box.clickedButton() is b_fix:
                    fix_tb = fix
                elif box.clickedButton() is b_raw:
                    fix_tb = None
                else:
                    return
            else:
                reply = QMessageBox.warning(
                    self, '参数不一致',
                    f'{head}\n\n{listed}{tail}\n\n'
                    '建议只合并同一次录制切出的片段。仍要合并吗？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        elif unknown:
            reply = QMessageBox.warning(
                self, '有片段读不出信息',
                f'有 {unknown} 个片段读不出编码信息（清单里时长显示「?」），'
                '没法在合并前校验它们跟其他片段是否匹配，成片可能有问题。\n\n'
                '仍要合并吗？（合并后会再复核一遍成片）',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        secs = [self.list_widget.item(i).data(SECS_ROLE) or 0 for i in range(n)]
        total_dur = sum(secs)
        # 有片段读不出时长 → 复核时不比总时长（见 MergeWorker.expect_dur）
        expect_dur = total_dur if all(x > 0 for x in secs) else 0.0
        # 上一个 worker 线程可能还在收尾（信号是先发出、后清临时文件），
        # 这时换掉引用让它被回收 = QThread 运行中被销毁，直接崩
        old = getattr(self, 'worker', None)
        if old is not None:
            old.wait()
        self._merged_files = files
        self._delete_after = self.delete_check.isChecked()
        self._merging = True
        self._set_merge_mode(True)
        self.progress_bar.setVisible(True)
        self._stage, self._pct, self._t0 = '正在合并', -1, None
        self.status.setText('正在合并…')

        self.worker = MergeWorker(files, output, total_dur, expect_dur, fix_tb, secs)
        self.worker.progress.connect(self.on_progress)
        self.worker.status.connect(self.on_stage)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_stage(self, text):
        """换阶段（统一时基 k/n → 合并 → 复核）：剩余时间按新阶段重算。"""
        self._stage, self._pct, self._t0 = text, -1, None   # 上一阶段的百分比别带过来
        self._show_progress()

    def on_progress(self, pct):
        if pct < 0:                       # 无法估算总时长 → 不确定进度（转圈）
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            if self._t0 is None:
                self._t0 = (time.monotonic(), pct)
        self._pct = pct
        self._show_progress()

    def _show_progress(self):
        if self._merging and not self.btn_merge.isEnabled():
            return                        # 正在取消，别把「正在取消…」顶掉
        pct, text = self._pct, self._stage + '…'
        if pct >= 0:
            text += f' {pct}%'
            # 几个 GB 的课程一合几分钟，光有百分比不知道要不要去倒杯水。
            # 跑满 5 秒、推进过 2% 再估，开头那几秒的速度不准。
            if self._t0:
                t0, p0 = self._t0
                dt, dp = time.monotonic() - t0, pct - p0
                if dt > 5 and dp >= 2:
                    left = dt / dp * (100 - pct)
                    text += (f'  ·  约剩 {int(left // 60) + 1} 分钟' if left >= 60
                             else '  ·  不到 1 分钟')
        self.status.setText(text)

    def closeEvent(self, event):
        self._closing = True
        if hasattr(self, 'worker') and self.worker.isRunning():
            # 先断信号：窗口马上就销毁了，晚到的 finished 打进来会崩。
            try:
                self.worker.progress.disconnect()
                self.worker.status.disconnect()
                self.worker.finished.disconnect()
            except TypeError:
                pass
            self.worker.stop()
            # 线程还在跑就走人 = QThread 被销毁时仍在运行，直接崩；而且孤儿 ffmpeg
            # 会继续写盘。stop() 里 3 秒补 kill，这里等够它收尾。
            if not self.worker.wait(10000):
                self.worker.terminate()      # 最后手段
                self.worker.wait(2000)
            self.worker._discard_partial()   # 兜底清临时文件
        event.accept()

    def _delete_originals(self):
        """删除原文件，返回 (成功数, 失败的文件名)。删不掉要如实说，不能谎报。"""
        failed = []
        ok = 0
        for f in self._merged_files:
            try:
                f.unlink()
                ok += 1
            except Exception:
                failed.append(f.name)
        return ok, failed

    def on_finished(self, success, msg, warn=''):
        self._merging = False
        self._set_merge_mode(False)
        self.progress_bar.setVisible(False)
        if success:
            done_note = f'合并完成：{Path(msg).name}'
            if warn:
                # 有问题要在删原文件之前说——先删后报等于把退路先断了。
                # ffmpeg 返回成功≠产出没问题，事前校验拦不住的在这里如实报出来。
                QMessageBox.warning(
                    self, '合并完成，但成片可能有问题',
                    f'成片已生成：\n{msg}\n\n'
                    '不过下面这些检查没通过，成片可能音画不同步或有坏帧，'
                    '建议进 PR 前先抽查一下：\n\n' + warn)
            if self._delete_after:
                extra = ('\n\n⚠️ 刚才的检查报了问题，强烈建议先确认成片没事再删。'
                         if warn else '')
                reply = QMessageBox.warning(
                    self, '确认删除',
                    f'合并成功！\n\n即将删除 {len(self._merged_files)} 个原始文件，'
                    f'此操作不可恢复，确认吗？{extra}',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    ok, failed = self._delete_originals()
                    if failed:
                        done_note = f'合并完成，已删除 {ok} 个，{len(failed)} 个没删掉'
                        QMessageBox.warning(
                            self, '部分原文件没删掉',
                            '这些文件删除失败（可能被占用或无权限），还在原处：\n\n'
                            + '\n'.join(f'· {n}' for n in failed[:10])
                            + ('\n…' if len(failed) > 10 else ''))
                    else:
                        done_note = f'合并完成，已删除 {ok} 个原文件'
            # 任务完成，清空清单准备下一批；输出位置/文件名与删除勾选保持不动
            # （如「第3期第2天 左机位」只需手改成「右机位」即可接着合并）。
            self.clear_list(reset_output=False)
            self.status.setText(done_note if not warn else done_note + '（有警告）')
            if not warn:
                QMessageBox.information(self, '完成', f'合并成功！\n{msg}')
        else:
            # 失败不清清单、也绝不会走到删原文件那一步：修好素材可以直接重合
            self._refresh_state()
            if msg == '已取消':
                self.status.setText('已取消')
                return
            if warn == 'incomplete':
                self.status.setText('合并失败：成片缺内容')
                QMessageBox.critical(
                    self, '合并没成功：成片缺内容',
                    msg + '\n\n清单原样留着，处理好素材（确认硬盘没断开、'
                          '有没有坏片）就能直接重合。')
            else:
                self.status.setText('合并失败')
                QMessageBox.critical(self, '错误', f'合并失败：\n{msg}')


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
