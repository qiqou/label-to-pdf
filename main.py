#!/usr/bin/env python3
"""
快递单批量转PDF v2 — 图形界面版
"""
import sys, os, subprocess, shutil, tempfile
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QComboBox, QRadioButton, QButtonGroup,
    QCheckBox, QProgressBar, QLabel, QFileDialog, QMessageBox,
    QFrame, QAbstractItemView, QGroupBox, QSplitter, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal, QMutex
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont

import qdarkstyle


# ── 尺寸预设 ──────────────────────────────────────────────
PRESETS = [
    ("标准尺寸 945×945",  945, 945, 300, "原参数"),
    ("标准快递面单 100×150mm", 800, 1200, 203, "100×150mm 热敏纸"),
    ("小号面单 76×130mm",  608, 1040, 203, "76×130mm"),
    ("国际面单 100×100mm", 795, 795, 203, "100×100mm 正方形"),
    ("原图尺寸（不缩放）", 0, 0, 300, ""),
    ("自定义", -1, -1, 300, ""),
]


def get_base_dir() -> Path:
    """获取程序所在目录（兼容开发环境和打包后的 exe）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(sys.argv[0]).resolve().parent


def find_magick():
    """在程序目录下找 ImageMagick exe，返回 Path 或 None"""
    base = get_base_dir()
    for f in base.iterdir():
        name = f.name.lower()
        if 'imagemagick' in name and name.endswith('.exe') and f.is_file():
            return f
    return None


# ── 后台工作线程 ──────────────────────────────────────────
class ConvertWorker(QThread):
    """在子线程里跑转换，不卡界面"""
    progress = Signal(int, int, str, str)   # current, total, filename, status
    finished = Signal(str)                  # output_dir
    error = Signal(str)                     # error message

    def __init__(self, files, magick_path, width, height, dpi,
                 do_trim, do_bw, merge_mode, unsharp, fuzz):
        super().__init__()
        self.files = files
        self.magick = str(magick_path)
        self.width = width
        self.height = height
        self.dpi = dpi
        self.do_trim = do_trim
        self.do_bw = do_bw
        self.merge_mode = merge_mode
        self.unsharp = unsharp
        self.fuzz = fuzz
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            base = get_base_dir()
            today = date.today().strftime("%Y%m%d")
            outdir = base / f"PDF输出_{today}"
            outdir.mkdir(parents=True, exist_ok=True)

            total = len(self.files)
            if total == 0:
                self.error.emit("没有图片需要处理")
                return

            ok = False
            if self.merge_mode:
                ok = self._run_merge(total, outdir)
            else:
                ok = self._run_separate(total, outdir)

            if not self._cancelled and ok:
                self.finished.emit(str(outdir))

        except Exception as e:
            self.error.emit(f"处理出错: {e}")

    def _build_args(self, src, dst):
        """拼装 magick 命令行参数"""
        args = [self.magick, str(src)]

        if self.do_trim:
            args += ["-trim", f"-fuzz {self.fuzz}%"]

        if self.width and self.height:
            args += [f"-resize {self.width}x{self.height}"]

        args += [f"-unsharp {self.unsharp}"]

        if self.do_bw:
            args += ["-colorspace", "Gray", "-threshold", "50%", "-type", "Bilevel"]

        args += ["-density", str(self.dpi), "-units", "PixelsPerInch", str(dst)]
        return args

    def _run_separate(self, total, outdir):
        ok = True
        for i, f in enumerate(self.files, 1):
            if self._cancelled:
                return False
            name = Path(f).stem
            self.progress.emit(i, total, name, "处理中...")
            dst = outdir / f"{name}.pdf"
            args = self._build_args(f, dst)
            ret = subprocess.run(args, capture_output=True, text=True, timeout=300)
            if ret.returncode != 0:
                self.progress.emit(i, total, name, f"失败: {ret.stderr.strip()[:60]}")
                ok = False
            else:
                self.progress.emit(i, total, name, "✓ 完成")
        return ok

    def _run_merge(self, total, outdir):
        tmpdir = Path(tempfile.mkdtemp(prefix="label_"))
        try:
            # 1) 逐张处理成临时 PNG
            for i, f in enumerate(self.files, 1):
                if self._cancelled:
                    return False
                name = Path(f).stem
                self.progress.emit(i, total, name, "处理中...")
                dst = tmpdir / f"{name}.png"
                args = self._build_args(f, dst)
                ret = subprocess.run(args, capture_output=True, text=True, timeout=300)
                if ret.returncode != 0:
                    self.progress.emit(i, total, name, f"失败: {ret.stderr.strip()[:60]}")
                    return False
                self.progress.emit(i, total, name, "✓ 完成")

            # 2) 合并所有 PNG → 一个 PDF
            self.progress.emit(total, total, "合并", "正在合并为多页PDF...")
            pngs = sorted(tmpdir.glob("*.png"))
            if not pngs:
                self.error.emit("没有成功处理任何图片，无法合并")
                return False
            args = [self.magick] + [str(p) for p in pngs] + ["-adjoin", str(outdir / "全部面单.pdf")]
            subprocess.run(args, capture_output=True, text=True, timeout=300)
            return True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── 主窗口 ─────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.files: list[str] = []
        self.worker: ConvertWorker | None = None
        self.magick_path = find_magick()
        self._setup_ui()

    # ── UI 搭建 ──────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle("快递单批量转PDF v2")
        self.setMinimumSize(720, 620)
        self.setAcceptDrops(True)

        cw = QWidget()
        self.setCentralWidget(cw)
        vbox = QVBoxLayout(cw)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(10)

        # ── 标题 ──
        title = QLabel("📦 快递单批量转PDF")
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding-bottom: 4px;")
        vbox.addWidget(title)

        # ── 文件列表 ──
        self._build_file_area(vbox)

        # ── 设置区 ──
        self._build_settings(vbox)

        # ── 进度 ──
        self._build_progress(vbox)

        # ── 按钮 ──
        self._build_buttons(vbox)

        # ── 状态栏 ──
        self.status_label = QLabel("拖拽图片到窗口，或点「添加文件」开始")
        self.status_label.setStyleSheet("color: #888;")
        vbox.addWidget(self.status_label)

        # 检查 magick
        if not self.magick_path:
            QMessageBox.warning(self, "缺少依赖",
                "找不到 ImageMagick 程序！\n"
                f"请把它放在 {get_base_dir()} 目录下。")

    def _build_file_area(self, parent):
        gb = QGroupBox("待处理图片")
        vbox = QVBoxLayout(gb)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("📂 添加文件")
        btn_add.clicked.connect(self._add_files)
        btn_folder = QPushButton("📁 添加文件夹")
        btn_folder.clicked.connect(self._add_folder)
        btn_clear = QPushButton("🗑 清空列表")
        btn_clear.clicked.connect(self._clear_files)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_folder)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setMinimumHeight(160)
        self.file_list.installEventFilter(self)
        vbox.addWidget(self.file_list)

        parent.addWidget(gb)

    def _build_settings(self, parent):
        gb = QGroupBox("转换设置")
        hbox = QHBoxLayout(gb)

        # ── 左列：尺寸 ──
        left = QVBoxLayout()
        left.addWidget(QLabel("面单尺寸："))
        self.size_combo = QComboBox()
        for name, *_ in PRESETS:
            self.size_combo.addItem(name)
        self.size_combo.currentIndexChanged.connect(self._on_size_changed)
        left.addWidget(self.size_combo)

        self.custom_w = QLabel("")
        self.custom_w.setStyleSheet("color: #aaa; font-size: 12px;")
        left.addWidget(self.custom_w)
        left.addStretch()
        hbox.addLayout(left)

        # ── 中列：模式 ──
        mid = QVBoxLayout()
        mid.addWidget(QLabel("输出模式："))
        self.merge_btn = QRadioButton("合并为一个PDF（推荐）")
        self.merge_btn.setChecked(True)
        self.separate_btn = QRadioButton("每张单独PDF")
        mid.addWidget(self.merge_btn)
        mid.addWidget(self.separate_btn)
        btn_group = QButtonGroup(self)
        btn_group.addButton(self.merge_btn)
        btn_group.addButton(self.separate_btn)
        mid.addStretch()
        hbox.addLayout(mid)

        # ── 右列：开关 ──
        right = QVBoxLayout()
        right.addWidget(QLabel("图像优化："))
        self.trim_cb = QCheckBox("自动裁边 (去白边)")
        self.trim_cb.setChecked(True)
        self.bw_cb = QCheckBox("转纯黑白 (条码清晰)")
        self.bw_cb.setChecked(True)
        right.addWidget(self.trim_cb)
        right.addWidget(self.bw_cb)
        right.addStretch()
        hbox.addLayout(right)

        parent.addWidget(gb)

    def _build_progress(self, parent):
        gb = QGroupBox("进度")
        vbox = QVBoxLayout(gb)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_label = QLabel("就绪")
        self.progress_label.setStyleSheet("color: #aaa; font-size: 12px;")

        vbox.addWidget(self.progress_bar)
        vbox.addWidget(self.progress_label)
        parent.addWidget(gb)

    def _build_buttons(self, parent):
        row = QHBoxLayout()

        self.start_btn = QPushButton("🚀 开始转化")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d8cf0; color: white;
                font-size: 16px; font-weight: bold;
                padding: 10px 30px; border-radius: 6px;
            }
            QPushButton:hover { background-color: #3d9cf0; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.start_btn.clicked.connect(self._start_conversion)

        self.open_btn = QPushButton("📂 打开输出文件夹")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output)

        row.addWidget(self.start_btn)
        row.addWidget(self.open_btn)
        row.addStretch()
        parent.addLayout(row)

    # ── 文件操作 ──────────────────────────────────────────
    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff);;所有文件 (*.*)")
        if files:
            self._add_to_list(files)

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        exts = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
        files = []
        for f in sorted(Path(folder).iterdir()):
            if f.suffix.lower() in exts:
                files.append(str(f))
        if not files:
            QMessageBox.information(self, "提示", "该文件夹没有找到图片文件")
        else:
            self._add_to_list(files)

    def _add_to_list(self, files):
        existing = set(self.files)
        for f in files:
            if f not in existing:
                self.files.append(f)
                self.file_list.addItem(Path(f).name)
                existing.add(f)
        self._update_status()

    def _clear_files(self):
        self.files.clear()
        self.file_list.clear()
        self._update_status()

    def _remove_selected(self):
        for item in self.file_list.selectedItems():
            idx = self.file_list.row(item)
            self.file_list.takeItem(idx)
            self.files.pop(idx)
        self._update_status()

    def _update_status(self):
        n = len(self.files)
        self.status_label.setText(f"已添加 {n} 张图片" if n else "拖拽图片到窗口，或点「添加文件」开始")

    # ── 拖拽 ──────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        exts = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}
        files = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if not p:
                continue
            p = Path(p)
            if p.is_dir():
                # 拖的是文件夹，扫描里面的图片
                for f in sorted(p.iterdir()):
                    if f.suffix.lower() in exts:
                        files.append(str(f))
            elif p.suffix.lower() in exts:
                files.append(str(p))
        if files:
            self._add_to_list(files)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and self.file_list.hasFocus():
            self._remove_selected()
        super().keyPressEvent(event)

    # ── 尺寸变更 ──────────────────────────────────────────
    def _on_size_changed(self, idx):
        _, w, h, dpi, desc = PRESETS[idx]
        if w == -1:
            self.custom_w.setText("请在代码里修改 PRESETS 自定义项")
        elif w == 0:
            self.custom_w.setText("保持原始尺寸")
        else:
            self.custom_w.setText(f"{w}×{h}  @{dpi}DPI  ({desc})")

    # ── 窗口关闭 ──────────────────────────────────────────
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)

    # ── 转换逻辑 ──────────────────────────────────────────
    def _start_conversion(self):
        if not self.files:
            QMessageBox.information(self, "提示", "请先添加图片")
            return
        if not self.magick_path:
            QMessageBox.critical(self, "错误", "找不到 ImageMagick 程序")
            return

        # 读取设置
        size_idx = self.size_combo.currentIndex()
        _, w, h, dpi, _ = PRESETS[size_idx]
        if w == -1:
            # 自定义用默认值
            w, h, dpi = 945, 945, 300
        do_trim = self.trim_cb.isChecked()
        do_bw = self.bw_cb.isChecked()
        merge_mode = self.merge_btn.isChecked()

        # 禁用按钮
        self.start_btn.setEnabled(False)
        self.start_btn.setText("⏳ 转换中...")
        self.open_btn.setEnabled(False)
        self.progress_bar.setMaximum(len(self.files))
        self.progress_bar.setValue(0)

        # 启动线程
        self.worker = ConvertWorker(
            self.files.copy(), self.magick_path, w, h, dpi,
            do_trim, do_bw, merge_mode, "0x3.0", 5)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current, total, filename, status):
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"[{current}/{total}] {filename} — {status}")
        self.status_label.setText(f"正在处理 {current}/{total}：{filename}")

    def _on_finished(self, output_dir):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始转化")
        self.progress_label.setText("✓ 全部完成！")
        self.status_label.setText(f"完成！PDF 保存在：{output_dir}")
        self._last_output = output_dir
        self.open_btn.setEnabled(True)
        self.worker = None

    def _on_error(self, msg):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 开始转化")
        self.progress_label.setText(f"✗ 出错")
        QMessageBox.critical(self, "处理出错", msg)
        self.worker = None

    def _open_output(self):
        d = getattr(self, '_last_output', None)
        if d and Path(d).exists():
            if sys.platform == 'win32':
                os.startfile(d)
            elif sys.platform == 'darwin':
                subprocess.run(['open', d])
            else:
                subprocess.run(['xdg-open', d])


# ── 启动 ───────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet())
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
