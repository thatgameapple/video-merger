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
    QProgressBar, QLineEdit, QMessageBox, QAbstractItemView, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPalette, QColor

VERSION = '1.3'
AUTHOR = 'thatgameapple'
VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mts', '.m2ts'}
CONFIG_FILE = Path.home() / '.video_merger_config.json'
PATH_ROLE = Qt.ItemDataRole.UserRole          # 行里存的完整路径
BATCH_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # 行里存的批次号（供「撤销」）


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
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


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
    name = path.name
    qi = _num_before(name, '期')
    day = _num_before(name, '天')
    return (qi if qi is not None else 0,
            day if day is not None else 0,
            _period_rank(name),
            name)


class MergeWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, files, output):
        super().__init__()
        self.files = files
        self.output = output
        self._proc = None

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self):
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt',
                                             delete=False, encoding='utf-8') as f:
                for fp in self.files:
                    escaped = str(fp).replace("'", "'\\''")
                    f.write(f"file '{escaped}'\n")
                list_file = f.name

            self.progress.emit('正在合并...')
            cmd = [
                FFMPEG, '-y', '-f', 'concat', '-safe', '0',
                '-i', list_file, '-c', 'copy', str(self.output)
            ]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = self._proc.communicate()
            os.unlink(list_file)

            if self._proc.returncode == 0:
                self.finished.emit(True, str(self.output))
            else:
                self.finished.emit(False, stderr.decode()[-500:])
        except Exception as e:
            self.finished.emit(False, str(e))


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
        self.setWindowTitle('视频合并')
        self.setMinimumSize(720, 520)
        self.config = load_config()
        self._next_batch = 0   # 递增批次号，每次拖入/添加一批 +1，供「撤销」
        self.setAcceptDrops(True)
        self._build_ui()

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
        self.btn_clear.clicked.connect(self.clear_list)
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

        # 输出文件名
        out_row = QHBoxLayout()
        lbl = QLabel('输出文件名')
        lbl.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        out_row.addWidget(lbl)
        self.out_name = QLineEdit('合并输出.mp4')
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
        self.btn_merge.clicked.connect(self.start_merge)
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
        """把拖入/选中的路径展开成视频文件（文件夹取其中的视频），按时段智能排序。"""
        videos = []
        for p in paths:
            if p.is_dir():
                videos.extend(
                    f for f in p.iterdir()
                    if f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._'))
            elif (p.is_file() and p.suffix.lower() in VIDEO_EXTS
                  and not p.name.startswith('._')):
                videos.append(p)
        return sorted(videos, key=smart_sort_key)

    def add_paths(self, paths):
        """把拖入/选中的视频追加到清单末尾，去重；返回本次实际新增的数量。"""
        videos = self._gather_videos(paths)
        existing = {self.list_widget.item(i).data(PATH_ROLE)
                    for i in range(self.list_widget.count())}
        self.status.setText('正在读取文件信息...')
        QApplication.processEvents()
        added = 0
        bid = self._next_batch
        for f in videos:
            key = str(f)
            if key in existing:
                continue
            existing.add(key)
            info = get_video_info(f)
            dur = format_duration(info) if info else '?'
            item = QListWidgetItem(f'  {f.name}    {dur}')
            item.setData(PATH_ROLE, key)
            item.setData(BATCH_ROLE, bid)
            self.list_widget.addItem(item)
            added += 1
        self.status.setText('')
        if added:
            self._next_batch += 1
            self.config['last_folder'] = str(videos[0].parent)
            save_config(self.config)
        self._refresh_state()
        return added

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

    def clear_list(self):
        self.list_widget.clear()
        self._next_batch = 0
        self._refresh_state()

    def _refresh_state(self):
        n = self.list_widget.count()
        self.count_label.setText(
            f'共 {n} 个待合并 · 可上下拖动调序' if n >= 2 else f'共 {n} 个待合并')
        self.btn_merge.setEnabled(n >= 2)
        self.btn_undo.setEnabled(n > 0)
        self.btn_clear.setEnabled(n > 0)
        if n:
            first = Path(self.list_widget.item(0).data(PATH_ROLE))
            self.folder_label.setText(f'输出到：{first.parent}')
        else:
            self.folder_label.setText('把视频或文件夹拖进来（或点右边添加文件夹）')

    def start_merge(self):
        n = self.list_widget.count()
        if n < 2:
            return
        files = [Path(self.list_widget.item(i).data(PATH_ROLE))
                 for i in range(n)]
        out_dir = files[0].parent

        out_name = self.out_name.text().strip() or '合并输出.mp4'
        if not out_name.endswith(('.mp4', '.mov', '.mkv')):
            out_name += '.mp4'
        output = out_dir / out_name

        if output.exists():
            reply = QMessageBox.question(
                self, '文件已存在',
                f'{out_name} 已存在，覆盖吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._merged_files = files
        self._delete_after = self.delete_check.isChecked()
        self.btn_merge.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status.setText('正在合并，请稍候...')

        self.worker = MergeWorker(files, output)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def closeEvent(self, event):
        if hasattr(self, 'worker') and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
        event.accept()

    def on_finished(self, success, msg):
        self.progress_bar.setVisible(False)
        if success:
            deleted = False
            if self._delete_after:
                reply = QMessageBox.warning(
                    self, '确认删除',
                    f'合并成功！\n\n即将删除 {len(self._merged_files)} 个原始文件，此操作不可恢复，确认吗？',
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    for f in self._merged_files:
                        try:
                            f.unlink()
                        except Exception:
                            pass
                    deleted = True
            # 任务完成，清空清单准备下一批；输出名与删除勾选保持不动
            # （如「第3期第2天 左机位」只需手改成「右机位」即可接着合并）。
            self.clear_list()
            if deleted:
                self.status.setText('合并完成，已删除原文件')
            else:
                self.status.setText(f'合并完成：{Path(msg).name}')
            QMessageBox.information(self, '完成', f'合并成功！\n{msg}')
        else:
            self.status.setText('合并失败')
            self.btn_merge.setEnabled(self.list_widget.count() >= 2)
            QMessageBox.critical(self, '错误', f'合并失败：\n{msg}')


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
