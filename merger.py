import sys
import os
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

VIDEO_EXTS = {'.mp4', '.mov', '.mkv', '.avi', '.m4v', '.mts', '.m2ts'}
CONFIG_FILE = Path.home() / '.video_merger_config.json'


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('视频合并')
        self.setMinimumSize(720, 520)
        self.folder = None
        self.file_infos = {}
        self.config = load_config()
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 顶部：文件夹路径 + 选择按钮
        top = QHBoxLayout()
        self.folder_label = QLabel('尚未选择文件夹')
        self.folder_label.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        self.folder_label.setWordWrap(False)
        btn_folder = QPushButton('选择文件夹')
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
        btn_all = QPushButton('全选')
        btn_none = QPushButton('取消全选')
        btn_all.clicked.connect(self.select_all)
        btn_none.clicked.connect(self.select_none)
        self.sel_label = QLabel('已选 0 个文件')
        self.sel_label.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        btn_row.addWidget(self.sel_label)
        layout.addLayout(btn_row)

        # 文件列表
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.list_widget, 1)

        # 状态（文件数量）
        self.file_count_label = QLabel('')
        self.file_count_label.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        layout.addWidget(self.file_count_label)

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

    def choose_folder(self):
        start = self.config.get('last_folder', str(Path.home()))
        start_path = Path(start)
        while start_path != start_path.parent and not start_path.exists():
            start_path = start_path.parent
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹', str(start_path))
        if not folder:
            return
        self.folder = Path(folder)
        self.config['last_folder'] = str(self.folder)
        save_config(self.config)
        self.folder_label.setText(str(self.folder))
        self.folder_label.setStyleSheet(f'color: {C["fg_dim"]}; font-size: 12px;')
        self.load_files()

    def load_files(self):
        self.list_widget.clear()
        self.file_infos = {}
        self.status.setText('正在读取文件信息...')
        QApplication.processEvents()

        files = sorted(
            [f for f in self.folder.iterdir()
             if f.suffix.lower() in VIDEO_EXTS and not f.name.startswith('._')],
            key=lambda f: f.name
        )

        for f in files:
            info = get_video_info(f)
            self.file_infos[f.name] = (f, info)
            dur = format_duration(info) if info else '?'
            item = QListWidgetItem(f'  {f.name}    {dur}')
            item.setData(Qt.ItemDataRole.UserRole, f.name)
            self.list_widget.addItem(item)

        self.file_count_label.setText(f'共 {len(files)} 个视频文件')
        self.status.setText('')

    def select_all(self):
        self.list_widget.selectAll()

    def select_none(self):
        self.list_widget.clearSelection()

    def on_selection_changed(self):
        n = len(self.list_widget.selectedItems())
        self.sel_label.setText(f'已选 {n} 个文件')
        self.btn_merge.setEnabled(n >= 2)

    def start_merge(self):
        selected = self.list_widget.selectedItems()
        names = sorted(item.data(Qt.ItemDataRole.UserRole) for item in selected)
        files = [self.file_infos[name][0] for name in names]

        out_name = self.out_name.text().strip() or '合并输出.mp4'
        if not out_name.endswith(('.mp4', '.mov', '.mkv')):
            out_name += '.mp4'
        output = self.folder / out_name

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
        self.btn_merge.setEnabled(True)
        if success:
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
                    self.load_files()
                    self.status.setText(f'合并完成，已删除原文件')
                    return
            self.status.setText(f'合并完成：{Path(msg).name}')
            QMessageBox.information(self, '完成', f'合并成功！\n{msg}')
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
