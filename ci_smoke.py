"""CI 冒烟：在当前平台用 bin/ 里的 ffmpeg 现做几段测试片，走一遍真合并。
专挑 Windows 上容易出事的：中文路径、带单引号的文件夹、反斜杠路径进 concat 清单、
时基不一致的无损修复。任何一步不对就非 0 退出，构建跟着失败。"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import merger
from PyQt6.QtWidgets import QApplication

app = QApplication([])
root = Path(tempfile.mkdtemp()) / "周老师's 课" / '第2天'
root.mkdir(parents=True)


def make(name, fps):
    subprocess.run([merger.FFMPEG, '-v', 'error', '-f', 'lavfi', '-i',
                    f'testsrc=s=320x240:r={fps}:d=3', '-f', 'lavfi', '-i',
                    'sine=d=3:r=48000', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(root / name)], check=True,
                   **merger.NO_WINDOW)


make('上午1.mp4', 30)
make('上午10.mp4', 30)
make('上午2.mp4', 30)
make('下午1.mp4', 24)

w = merger.MainWindow()
w.add_paths([root])
names = [w.list_widget.item(i).data(merger.PATH_ROLE) for i in range(w.list_widget.count())]
assert [Path(n).name for n in names] == ['上午1.mp4', '上午2.mp4', '上午10.mp4', '下午1.mp4'], names

files = [Path(n) for n in names]
params = [w.list_widget.item(i).data(merger.PARAMS_ROLE) for i in range(len(files))]
fix = merger.plan_timebase_fix(params, files)
assert fix and fix[1] == [3], fix
secs = [w.list_widget.item(i).data(merger.SECS_ROLE) for i in range(len(files))]
out = root.parent / '第2天.mp4'
result = []
wk = merger.MergeWorker(files, out, sum(secs), sum(secs), fix, secs)
wk.finished.connect(lambda ok, msg, warn: result.append((ok, msg, warn)))
wk.run()                                   # 同步跑，不起线程
print(result)
assert result and result[0][0] and not result[0][2], result
info = merger.get_video_info(out)
durs = {s['codec_type']: float(s['duration']) for s in info['streams']}
print(durs)
assert abs(durs['video'] - 12) < 0.2 and abs(durs['audio'] - 12) < 0.2, durs
assert not list(root.parent.rglob('.*vm*')), '临时文件没清干净'
print('SMOKE OK on', sys.platform)
