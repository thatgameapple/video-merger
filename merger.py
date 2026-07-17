import sys
import os
import re
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QFileDialog,
    QProgressBar, QLineEdit, QMessageBox, QAbstractItemView, QCheckBox,
    QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor, QAction

VERSION = '1.5.0'
AUTHOR = 'thatgameapple'
APP_NAME = 'Video Merge'
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mts', '.m2ts'}
CONFIG_FILE = Path.home() / '.video_merger_config.json'
DEFAULT_OUT_NAME = '合并输出.mp4'
PATH_ROLE = Qt.ItemDataRole.UserRole          # 行里存的完整路径
BATCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # 行里存的批次号（供「撤销」）
PARAMS_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # 视频+音频关键参数，合并前校验一致性
SECS_ROLE = int(Qt.ItemDataRole.UserRole) + 3   # 时长（秒），求和得总时长供真实进度


def _resolve_binary(name: str) -> str:
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
    font-family: "PingFang SC";
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
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
    """取视频流 (codec, 宽, 高, 像素格式) + 音频流 (codec, 采样率, 声道)，
    供合并前比对一致性。concat -c copy 要求这些参数一致：
    视频不一致会失败或花屏；音频不一致更阴——ffmpeg 照样返回成功，
    只在 stderr 刷 Non-monotonic DTS，产出音轨比视频短，音画不同步。"""
    if not info:
        return None
    video = audio = None
    for s in info.get('streams', []):
        kind = s.get('codec_type')
        if kind == 'video' and video is None:
            video = (s.get('codec_name'), s.get('width'),
                     s.get('height'), s.get('pix_fmt'))
        elif kind == 'audio' and audio is None:
            audio = (s.get('codec_name'), s.get('sample_rate'),
                     s.get('channels'))
    return (video, audio)


def describe_params(p):
    if not p:
        return '未知'
    video, audio = p
    if video:
        codec, w, h, pix = video
        vs = f'{codec or "?"}  {w or "?"}×{h or "?"}  {pix or "?"}'
    else:
        vs = '无视频轨'
    if audio:
        codec, rate, ch = audio
        vs += f'   ·   {codec or "?"}  {rate or "?"}Hz  {ch or "?"}声道'
    else:
        vs += '   ·   无音频轨'
    return vs


def _short_path(p):
    """外接盘路径太长，界面上只显示末两级，全路径挂 tooltip。"""
    parts = Path(p).parts
    return '…/' + '/'.join(parts[-2:]) if len(parts) > 3 else str(p)


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
    """取「第X<unit>」「X<unit>」里的数字（阿拉伯或中文），无则 None。"""
    m = re.search(r'第?\s*([0-9零一二三四五六七八九十两]+)\s*' + unit, name)
    return _cn_to_int(m.group(1)) if m else None


def _period_rank(name):
    ranks = [r for kw, r in _PERIODS if kw in name]
    return min(ranks) if ranks else 50   # 没有时段词的排在有时段词的之后


def smart_sort_key(path):
    # 用整条路径而非仅文件名：时段词常写在子文件夹名上
    # （如「第3天/上午/clip01.mp4」「第3天/晚上/clip01.mp4」），
    # 只看文件名会把不同时段的同名片段排到一起。
    s = str(path)
    qi = _num_before(s, '期')
    day = _num_before(s, '天')
    return (qi if qi is not None else 0,
            day if day is not None else 0,
            _period_rank(s),
            s)


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


class MergeWorker(QThread):
    # 百分比 0-100；-1 表示无法估算总时长，走不确定进度（转圈）
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str, str)   # 成功?, 输出路径/错误, 警告文本

    def __init__(self, files, output, total_dur=0.0):
        super().__init__()
        self.files = files
        self.output = output
        self.total_dur = total_dur
        self._proc = None
        self._cancelled = False

    def stop(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self):
        list_file = err_file = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                             delete=False, encoding='utf-8') as f:
                for fp in self.files:
                    escaped = str(fp).replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")
                list_file = f.name

            self.progress.emit(0 if self.total_dur > 0 else -1)
            # -progress pipe:1 让 ffmpeg 周期性吐出 out_time；stderr 另存文件，
            # 失败时读回尾部报错（避免 PIPE 塞满死锁）。
            cmd = [
                FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
                '-c', 'copy', '-progress', 'pipe:1', '-nostats', str(self.output)
            ]
            errf = tempfile.NamedTemporaryFile(mode='w+', suffix='.log',
                                               delete=False, encoding='utf-8')
            err_file = errf.name
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=errf, text=True)

            last = 0
            for line in self._proc.stdout:
                line = line.strip()
                sec = None
                if line.startswith(('out_time_us=', 'out_time_ms=')):
                    v = line.split('=', 1)[1]
                    if v.isdigit():           # 这两个键单位都是微秒
                        sec = int(v) / 1_000_000
                elif line.startswith('out_time='):
                    sec = _parse_hms(line.split('=', 1)[1])
                if sec is not None and self.total_dur > 0:
                    pct = max(0, min(99, int(sec / self.total_dur * 100)))
                    if pct != last:
                        last = pct
                        self.progress.emit(pct)
            self._proc.stdout.close()
            self._proc.wait()

            errf.seek(0)
            err = errf.read()
            errf.close()

            if self._proc.returncode == 0:
                self.progress.emit(100)
                self.finished.emit(True, str(self.output),
                                   '\n'.join(scan_warnings(err, len(self.files) - 1)))
            else:
                # 失败/取消时 ffmpeg 已经写了个残缺文件在素材目录里，
                # 留着会被下次拖入当成素材，直接清掉。
                self._discard_partial()
                if self._cancelled:
                    self.finished.emit(False, '已取消', '')
                else:
                    self.finished.emit(False, (err[-500:] or '未知错误'), '')
        except Exception as e:
            self._discard_partial()
            self.finished.emit(False, str(e), '')
        finally:
            for p in (list_file, err_file):
                if p:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass

    def _discard_partial(self):
        try:
            Path(self.output).unlink(missing_ok=True)
        except Exception:
            pass


class DropListWidget(QListWidget):
    """行内拖动可调序；外部文件/文件夹拖入则转交回调（add_paths）处理。"""

    def __init__(self, on_external):
        super().__init__()
        self._on_external = on_external
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

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
        # 删掉 Qt 往应用菜单塞的英文/无用默认项（About Qt、首选项）
        QTimer.singleShot(0, self._localize_native_appmenu)

    def _open_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f'关于 {APP_NAME}')
        dlg.setFixedWidth(340)
        dlg.setStyleSheet(f"QDialog {{ background: {C['bg']}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(30, 28, 30, 26)
        lay.setSpacing(5)

        def _lbl(text, size, color, family='PingFang SC'):
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
        btn_folder = QPushButton('添加文件夹')
        btn_folder.clicked.connect(self.choose_folder)
        top.addWidget(self.folder_label, 1)
        top.addWidget(btn_folder)
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
        self.list_widget = DropListWidget(self.add_paths)
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

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return
        self.add_paths(paths)
        event.acceptProposedAction()

    def _gather_videos(self, paths):
        """把拖入/选中的路径展开成 (拖入的根, 视频文件)，按时段智能排序。
        文件夹会递归到所有子文件夹（周老师课程常按机位/天分子目录），
        排除 macOS 的 ._ 资源叉文件。带上「根」是为了在清单里显示
        相对路径（同名的「上午/clip01」「晚上/clip01」才分得清），
        并据此决定默认输出位置。直接拖文件的根为 None。"""
        found = []
        for p in paths:
            if p.is_dir():
                found.extend(
                    (p, f) for f in p.rglob('*')
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTS
                    and not f.name.startswith('._'))
            elif (p.is_file() and p.suffix.lower() in VIDEO_EXTS
                  and not p.name.startswith('._')):
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
        if self._adding:            # 读取信息时 processEvents 会让新的拖入重入这里
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
        existing = {self.list_widget.item(i).data(PATH_ROLE)
                    for i in range(self.list_widget.count())}
        self.status.setText('正在读取文件信息...')
        QApplication.processEvents()
        added = 0
        bid = self._next_batch
        todo = [(root, f) for root, f in videos if str(f) not in existing]
        for idx, (root, f) in enumerate(todo, 1):
            key = str(f)
            if key in existing:
                continue
            existing.add(key)
            # 每个文件跑一次 ffprobe（实测每个几十毫秒），报进度 + 让出事件循环，
            # 免得几十个片段时看起来像卡死。
            self.status.setText(f'正在读取文件信息... {idx}/{len(todo)}')
            QApplication.processEvents()
            info = get_video_info(f)
            dur = format_duration(info) if info else '?'
            item = QListWidgetItem(self._row_label(root, f, dur))
            item.setData(PATH_ROLE, key)
            item.setData(BATCH_ROLE, bid)
            item.setData(PARAMS_ROLE, stream_params(info))
            item.setData(SECS_ROLE, duration_secs(info))
            self.list_widget.addItem(item)
            added += 1
        self.status.setText('')
        if added:
            self._next_batch += 1
            self.config['last_folder'] = str(todo[0][1].parent)
            save_config(self.config)
            self._apply_default_output(todo[0][0], todo[0][1])
        return added

    def _apply_default_output(self, root, first):
        """定默认输出位置/文件名：拖「第3天」文件夹 → 输出「第3天.mp4」到它的上一级
        （跟文件夹并排，不混进素材、也不会被下次拖入扫到）；直接拖文件 → 落文件旁边。
        只在用户还没自己选过/改过时套用，且只认第一批。"""
        if not self._src_name:
            self._src_name = root.name if root else first.parent.name
        if self._out_dir is None and not self._dir_chosen:
            self._out_dir = root.parent if root else first.parent
        if root and not self._name_edited and self.out_name.text() == DEFAULT_OUT_NAME:
            self.out_name.setText(f'{root.name}.mp4')

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
            self.out_name.setText(DEFAULT_OUT_NAME)
        self._refresh_state()

    def _refresh_state(self):
        n = self.list_widget.count()
        self.count_label.setText(
            f'共 {n} 个待合并 · 可上下拖动调序' if n >= 2 else f'共 {n} 个待合并')
        if self._merging:
            self.btn_merge.setEnabled(True)      # 合并中它是「取消」，永远可点
        else:
            self.btn_merge.setEnabled(n >= 2 and not self._adding)
        self.btn_undo.setEnabled(n > 0)
        self.btn_clear.setEnabled(n > 0)
        self.folder_label.setText(
            f'共 {n} 个片段，来自「{self._src_name}」' if n and self._src_name
            else (f'共 {n} 个片段' if n
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
        out_dir = self._out_dir or files[0].parent
        if not out_dir.is_dir():
            QMessageBox.critical(
                self, '输出位置不可用',
                f'输出文件夹不存在或已断开：\n{out_dir}\n\n请点「更改」重新选一个。')
            return

        out_name = self.out_name.text().strip() or DEFAULT_OUT_NAME
        if not out_name.endswith(('.mp4', '.mov', '.mkv')):
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
        if len(kinds) > 1:
            listed = '\n'.join(f'· {describe_params(p)}' for p in kinds)
            audio_only = len({tuple(k[0]) if k[0] else None for k in kinds}) == 1
            head = ('这些片段的音频参数不一致（视频部分是一致的），'
                    '无损合并会产出音画不同步的成片：'
                    if audio_only else
                    '这些片段的编码 / 分辨率 / 像素格式 / 音频参数不完全一致，'
                    '无损合并（-c copy）可能失败、花屏或音画不同步：')
            reply = QMessageBox.warning(
                self, '编码不一致',
                f'{head}\n\n{listed}\n\n'
                '建议只合并同一次录制切出的片段。仍要合并吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        total_dur = sum(self.list_widget.item(i).data(SECS_ROLE) or 0
                        for i in range(n))
        self._merged_files = files
        self._delete_after = self.delete_check.isChecked()
        self._merging = True
        self._set_merge_mode(True)
        self.progress_bar.setVisible(True)
        self.status.setText('正在合并，请稍候...')

        self.worker = MergeWorker(files, output, total_dur)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, pct):
        if pct < 0:                       # 无法估算总时长 → 不确定进度（转圈）
            self.progress_bar.setRange(0, 0)
            self.status.setText('正在合并，请稍候...')
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.status.setText(f'正在合并… {pct}%')

    def closeEvent(self, event):
        if hasattr(self, 'worker') and self.worker.isRunning():
            # 先断信号：窗口马上就销毁了，晚到的 finished 打进来会崩。
            try:
                self.worker.progress.disconnect()
                self.worker.finished.disconnect()
            except TypeError:
                pass
            self.worker.stop()
            self.worker.wait(2000)
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
            if self._delete_after:
                reply = QMessageBox.warning(
                    self, '确认删除',
                    f'合并成功！\n\n即将删除 {len(self._merged_files)} 个原始文件，此操作不可恢复，确认吗？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
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
            if warn:
                # ffmpeg 返回成功≠产出没问题。事前校验拦不住的，这里如实报出来。
                QMessageBox.warning(
                    self, '合并完成，但 ffmpeg 报了警告',
                    f'成片已生成：\n{msg}\n\n'
                    '但 ffmpeg 报了下面的警告，成片可能音画不同步或有坏帧，'
                    '建议进 PR 前先抽查一下：\n\n' + warn)
            else:
                QMessageBox.information(self, '完成', f'合并成功！\n{msg}')
        else:
            self._refresh_state()
            if msg == '已取消':
                self.status.setText('已取消')
                return
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
