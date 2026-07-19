#!/usr/bin/env python3
"""
快递单批量转PDF v3 — 稳定版
"""
import sys, os, subprocess, shutil, tempfile
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QComboBox, QRadioButton, QButtonGroup,
    QCheckBox, QProgressBar, QLabel, QFileDialog, QMessageBox,
    QGroupBox, QAbstractItemView, QSpinBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent

import qdarkstyle


# ── 尺寸预设 ──────────────────────────────────────────────
PRESETS = [
    ("标准尺寸 945×945",       945, 945, 300),
    ("标准快递面单 100×150mm",  800, 1200, 203),
    ("小号面单 76×130mm",       608, 1040, 203),
    ("国际面单 100×100mm",      795, 795, 203),
    ("原图尺寸（不缩放）",      0, 0, 300),
]


def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(sys.argv[0]).resolve().parent


def find_magick():
    """找 ImageMagick：PATH → 注册表 → Program Files → rglob magick.exe"""
    for name in ("magick", "magick.exe", "convert"):
        p = shutil.which(name)
        if p:
            return Path(p)

    candidates = []
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\ImageMagick\Current") as key:
                bp = winreg.QueryValueEx(key, "BinPath")[0]
                candidates.append(Path(bp) / "magick.exe")
        except Exception:
            pass
        for pf in [r"C:\Program Files", r"C:\Program Files (x86)"]:
            base = Path(pf)
            if base.is_dir():
                for d in sorted(base.iterdir(), reverse=True):
                    if "imagemagick" in d.name.lower():
                        candidates.append(d / "magick.exe")

    for c in candidates:
        if c.is_file():
            return c

    base = get_base_dir()
    for f in base.rglob("magick.exe"):
        if f.is_file():
            return f
    return None


# ── 后台工作线程 ──────────────────────────────────────────
class ConvertWorker(QThread):
    progress = Signal(int, int, str, str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, files, magick_path, output_dir, width, height, dpi,
                 do_trim, do_bw, merge_mode, unsharp, fuzz, log_path):
        super().__init__()
        self.files = files
        self.magick = str(magick_path)
        self.outdir = Path(output_dir)
        self.width = width
        self.height = height
        self.dpi = dpi
        self.do_trim = do_trim
        self.do_bw = do_bw
        self.merge_mode = merge_mode
        self.unsharp = unsharp
        self.fuzz = fuzz
        self.log_path = log_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _log(self, msg: str):
        try:
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(msg + "\n")
        except Exception as e:
            print(f"[日志写入失败] {e}", file=sys.stderr)

    def run(self):
        try:
            outdir = self.outdir
            outdir.mkdir(parents=True, exist_ok=True)
            self._outdir = str(outdir)

            with open(self.log_path, 'w', encoding='utf-8') as f:
                f.write(f"快递单转PDF 日志 — {date.today()}\n{'='*40}\n")

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
            elif not self._cancelled and not ok:
                self.error.emit("部分文件处理失败，详情见日志文件")

        except Exception as e:
            self._log(f"[崩溃] {e}")
            self.error.emit(f"程序崩溃: {e}")

    def _build_args(self, src, dst):
        """每个参数独立元素，不拼接"""
        args = [self.magick, str(src)]
        if self.do_trim:
            args += ["-trim", "-fuzz", f"{self.fuzz}%"]
        if self.width and self.height:
            args += ["-resize", f"{self.width}x{self.height}"]
        args += ["-unsharp", self.unsharp]
        if self.do_bw:
            args += ["-colorspace", "Gray", "-threshold", "50%", "-type", "Bilevel"]
        args += ["-density", str(self.dpi), "-units", "PixelsPerInch", str(dst)]
        return args

    def _call_magick(self, args, label="") -> tuple[bool, str]:
        cmd_display = " ".join(str(a) if " " not in str(a) else f'"{a}"' for a in args)
        self._log(f"[{label}] {cmd_display}")
        try:
            ret = subprocess.run(args, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            self._log("[超时] 超过600秒")
            return False, "处理超时（超过10分钟），图片可能太大"
        except Exception as e:
            self._log(f"[异常] {e}")
            return False, f"程序异常: {e}"

        if ret.returncode == 0:
            self._log("[OK]")
            return True, ""

        self._log(f"[失败] exit code={ret.returncode}")
        err_full = (ret.stderr or "").strip()
        if err_full:
            self._log(f"[stderr]\n{err_full}")
        else:
            err_full = (ret.stdout or "").strip()
            if err_full:
                self._log(f"[stdout]\n{err_full}")

        lines = err_full.split("\n")
        brief = "\n".join(lines[-5:]).strip()
        if len(brief) > 200:
            brief = brief[:200] + "..."
        return False, brief or f"magick 退出码 {ret.returncode}"

    def _run_separate(self, total, outdir) -> bool:
        all_ok = True
        name_count: dict[str, int] = {}
        for i, f in enumerate(self.files, 1):
            if self._cancelled:
                return False
            raw_name = Path(f).stem
            name_count[raw_name] = name_count.get(raw_name, 0) + 1
            cnt = name_count[raw_name]
            name = f"{raw_name}_{cnt}" if cnt > 1 else raw_name
            self.progress.emit(i, total, name, "处理中...")
            dst = outdir / f"{name}.pdf"
            ok, err = self._call_magick(self._build_args(f, dst), f"{i}/{total} {name}")
            if ok:
                self.progress.emit(i, total, name, "✓")
            else:
                self.progress.emit(i, total, name, f"✗ {err[:50]}")
                all_ok = False
        return all_ok

    def _run_merge(self, total, outdir) -> bool:
        tmpdir = Path(tempfile.mkdtemp(prefix="label_"))
        name_count: dict[str, int] = {}
        skipped = 0
        try:
            for i, f in enumerate(self.files, 1):
                if self._cancelled:
                    return False
                raw_name = Path(f).stem
                name_count[raw_name] = name_count.get(raw_name, 0) + 1
                cnt = name_count[raw_name]
                label = f"{raw_name}_{cnt}" if cnt > 1 else raw_name
                self.progress.emit(i, total, label, "处理中...")
                dst = tmpdir / f"{label}.png"
                ok, err = self._call_magick(self._build_args(f, dst), f"{i}/{total} {label}")
                if not ok:
                    self.progress.emit(i, total, label, f"✗ 跳过 ({err[:40]})")
                    skipped += 1
                    continue
                self.progress.emit(i, total, label, "✓")

            if skipped == total:
                self._log("[合并] 所有图片都处理失败，无法合并")
                return False

            self.progress.emit(total, total, "合并", "正在合并为多页PDF...")
            pngs = []
            for f in self.files:
                raw_name = Path(f).stem
                cnt = name_count.get(raw_name, 0)
                if cnt > 1:
                    for n in range(1, cnt + 1):
                        p = tmpdir / f"{raw_name}_{n}.png"
                        if p.exists():
                            pngs.append(str(p))
                else:
                    p = tmpdir / f"{raw_name}.png"
                    if p.exists():
                        pngs.append(str(p))
            if not pngs:
                self._log("[合并] 没有可合并的图片")
                return False

            merge_args = [self.magick] + [str(p) for p in pngs] + ["-adjoin", str(outdir / "merged_labels.pdf")]
            ok, err = self._call_magick(merge_args, "合并PDF")
            if not ok:
                self._log(f"[合并失败] {err}")
                return False
            return True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── 主窗口 ─────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.files: list[str] = []
        self.worker: ConvertWorker | None = None
        self._last_output: str | None = None
        self.magick_path = find_magick()
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("快递单批量转PDF v3")
        self.setMinimumSize(720, 620)
        self.setAcceptDrops(True)

        cw = QWidget()
        self.setCentralWidget(cw)
        vbox = QVBoxLayout(cw)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(10)

        title = QLabel("📦 快递单批量转PDF")
        title.setStyleSheet("font-size: 20px; font-weight: bold; padding-bottom: 4px;")
        vbox.addWidget(title)

        self._build_file_area(vbox)
        self._build_settings(vbox)
        self._build_progress(vbox)
        self._build_buttons(vbox)

        self.status_label = QLabel("拖拽图片到窗口，或点「添加文件」开始")
        self.status_label.setStyleSheet("color: #888;")
        vbox.addWidget(self.status_label)

        if not self.magick_path:
            QMessageBox.warning(self, "缺少依赖",
                "找不到 ImageMagick！\n\n"
                "你桌面上那个 ImageMagick-xxx-static.exe 是安装包，不是命令本身。\n\n"
                "方式一（推荐）：双击安装包安装一次，之后 magick 命令自动生效\n"
                "方式二：从安装目录（如 C:\\Program Files\\ImageMagick-xxx）\n"
                "        复制 magick.exe 到本程序同目录下\n"
                "安装包下载：https://imagemagick.org/script/download.php#windows")

        # 初始化默认输出路径
        self._reset_output_path()

    def _build_file_area(self, parent):
        gb = QGroupBox("待处理图片")
        vbox = QVBoxLayout(gb)
        btn_row = QHBoxLayout()
        self._file_btns = []
        for text, cb in [("📂 添加文件", self._add_files),
                         ("📁 添加文件夹", self._add_folder),
                         ("🗑 清空列表", self._clear_files)]:
            btn = QPushButton(text)
            btn.clicked.connect(cb)
            btn_row.addWidget(btn)
            self._file_btns.append(btn)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        self.file_list = QListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_list.setMinimumHeight(160)
        vbox.addWidget(self.file_list)
        parent.addWidget(gb)

    def _build_settings(self, parent):
        gb = QGroupBox("转换设置")
        hbox = QHBoxLayout(gb)

        # 尺寸
        left = QVBoxLayout()
        left.addWidget(QLabel("面单尺寸："))
        self.size_combo = QComboBox()
        for name, *_ in PRESETS:
            self.size_combo.addItem(name)
        self.size_combo.addItem("自定义...")
        self.size_combo.currentIndexChanged.connect(self._on_size_changed)
        left.addWidget(self.size_combo)
        self.size_hint = QLabel("")
        self.size_hint.setStyleSheet("color: #aaa; font-size: 12px;")
        left.addWidget(self.size_hint)

        # 自定义尺寸输入框（默认隐藏）
        spin_row = QHBoxLayout()
        self.custom_width = QSpinBox()
        self.custom_width.setRange(1, 9999)
        self.custom_width.setValue(945)
        self.custom_width.setSuffix(" px")
        self.custom_w_label = QLabel("宽")
        self.custom_w_label.setStyleSheet("color: #aaa;")
        self.custom_height = QSpinBox()
        self.custom_height.setRange(1, 9999)
        self.custom_height.setValue(945)
        self.custom_height.setSuffix(" px")
        self.custom_x_label = QLabel("×")
        self.custom_x_label.setStyleSheet("color: #aaa;")
        self.custom_dpi = QSpinBox()
        self.custom_dpi.setRange(72, 1200)
        self.custom_dpi.setValue(300)
        self.custom_dpi.setSuffix(" DPI")
        self.custom_dpi_label = QLabel("@")
        self.custom_dpi_label.setStyleSheet("color: #aaa;")
        spin_row.addWidget(self.custom_w_label)
        spin_row.addWidget(self.custom_width)
        spin_row.addWidget(self.custom_x_label)
        spin_row.addWidget(self.custom_height)
        spin_row.addWidget(self.custom_dpi_label)
        spin_row.addWidget(self.custom_dpi)
        spin_row.addStretch()
        left.addLayout(spin_row)
        self._hide_custom_spin()

        left.addStretch()
        hbox.addLayout(left)

        # 模式
        mid = QVBoxLayout()
        mid.addWidget(QLabel("输出模式："))
        self.merge_btn = QRadioButton("合并为一个PDF（推荐）")
        self.merge_btn.setChecked(True)
        self.separate_btn = QRadioButton("每张单独PDF")
        mid.addWidget(self.merge_btn)
        mid.addWidget(self.separate_btn)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.merge_btn)
        self.mode_group.addButton(self.separate_btn)
        mid.addStretch()
        hbox.addLayout(mid)

        # 开关
        right = QVBoxLayout()
        right.addWidget(QLabel("图像优化："))
        self.trim_cb = QCheckBox("自动裁边（去白边）")
        self.trim_cb.setChecked(True)
        self.bw_cb = QCheckBox("转纯黑白（条码清晰）")
        self.bw_cb.setChecked(True)
        right.addWidget(self.trim_cb)
        right.addWidget(self.bw_cb)
        right.addStretch()
        hbox.addLayout(right)
        parent.addWidget(gb)

        # ── 输出位置 ──
        dirbox = QHBoxLayout()
        dirbox.addWidget(QLabel("输出位置："))
        self.output_path = QLabel("")
        self.output_path.setStyleSheet("color: #ccc; padding: 4px 8px; "
                                        "border: 1px solid #555; border-radius: 4px;")
        self.output_path.setWordWrap(True)
        dirbox.addWidget(self.output_path, 1)
        self.browse_btn = QPushButton("浏览...")
        self.browse_btn.clicked.connect(self._browse_output)
        dirbox.addWidget(self.browse_btn)
        parent.addLayout(dirbox)

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

        self.cancel_btn = QPushButton("⏹ 取消")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f; color: white;
                font-size: 14px; padding: 10px 20px; border-radius: 6px;
            }
            QPushButton:hover { background-color: #e53935; }
            QPushButton:disabled { background-color: #555; color: #999; }
        """)
        self.cancel_btn.clicked.connect(self._cancel_conversion)
        self.cancel_btn.hide()

        self.open_btn = QPushButton("📂 打开输出文件夹")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_output)

        row.addWidget(self.start_btn)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.open_btn)
        row.addStretch()
        parent.addLayout(row)

    # ── 文件操作 ──────────────────────────────────────────
    IMG_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff'}

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
        files = [str(f) for f in sorted(Path(folder).iterdir())
                 if f.suffix.lower() in self.IMG_EXTS]
        if not files:
            QMessageBox.information(self, "提示", "该文件夹没有找到图片文件")
        else:
            self._add_to_list(files)

    def _add_to_list(self, files):
        existing = {Path(f).resolve() for f in self.files}
        for f in files:
            p = Path(f).resolve()
            if p not in existing:
                self.files.append(str(p))
                self.file_list.addItem(p.name)
                existing.add(p)
        self._update_status()

    def _clear_files(self):
        self.files.clear()
        self.file_list.clear()
        self._update_status()

    def _remove_selected(self):
        rows = sorted(set(self.file_list.row(item)
                          for item in self.file_list.selectedItems()), reverse=True)
        for idx in rows:
            self.file_list.takeItem(idx)
            self.files.pop(idx)
        self._update_status()

    def _update_status(self):
        n = len(self.files)
        self.status_label.setText(
            f"已添加 {n} 张图片" if n else "拖拽图片到窗口，或点「添加文件」开始")

    # ── 拖拽 ──────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        files = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if not p:
                continue
            p = Path(p)
            if p.is_dir():
                files.extend(str(f) for f in sorted(p.iterdir())
                             if f.suffix.lower() in self.IMG_EXTS)
            elif p.suffix.lower() in self.IMG_EXTS:
                files.append(str(p))
        if files:
            self._add_to_list(files)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete and self.file_list.hasFocus():
            self._remove_selected()
        super().keyPressEvent(event)

    # ── 尺寸变更 ──────────────────────────────────────────
    def _on_size_changed(self, idx):
        if idx < len(PRESETS):
            self._hide_custom_spin()
            _, w, h, dpi = PRESETS[idx]
            if w == 0:
                self.size_hint.setText("保持原始尺寸")
            else:
                self.size_hint.setText(f"{w}×{h}  @{dpi}DPI")
        else:
            self.size_hint.setText("")
            self._show_custom_spin()

    def _show_custom_spin(self):
        self.custom_width.show()
        self.custom_height.show()
        self.custom_dpi.show()
        self.custom_w_label.show()
        self.custom_x_label.show()
        self.custom_dpi_label.show()

    def _hide_custom_spin(self):
        self.custom_width.hide()
        self.custom_height.hide()
        self.custom_dpi.hide()
        self.custom_w_label.hide()
        self.custom_x_label.hide()
        self.custom_dpi_label.hide()

    # ── 窗口关闭 ──────────────────────────────────────────
    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            if not self.worker.wait(3000):
                self.worker.terminate()
                self.worker.wait(2000)
        super().closeEvent(event)

    # ── 转换逻辑 ──────────────────────────────────────────
    def _reset_output_path(self):
        """重置为默认输出路径"""
        today = date.today().strftime("%Y%m%d")
        self._selected_output = str(get_base_dir() / f"PDF输出_{today}")
        self.output_path.setText(self._selected_output)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹",
                                                   self._selected_output)
        if folder:
            self._selected_output = folder
            self.output_path.setText(folder)

    def _set_busy(self, busy: bool):
        self.start_btn.setVisible(not busy)
        self.cancel_btn.setVisible(busy)
        self.open_btn.setEnabled(not busy)
        for btn in self._file_btns:
            btn.setEnabled(not busy)
        self.size_combo.setEnabled(not busy)
        self.merge_btn.setEnabled(not busy)
        self.separate_btn.setEnabled(not busy)
        self.trim_cb.setEnabled(not busy)
        self.bw_cb.setEnabled(not busy)
        self.custom_width.setEnabled(not busy)
        self.custom_height.setEnabled(not busy)
        self.custom_dpi.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)

    def _cancel_conversion(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        self.progress_label.setText("⏹ 已取消")
        self.status_label.setText("用户取消转换")
        self._set_busy(False)
        self.worker = None

    def _start_conversion(self):
        if not self.files:
            QMessageBox.information(self, "提示", "请先添加图片")
            return
        if not self.magick_path:
            QMessageBox.critical(self, "错误", "找不到 ImageMagick 程序")
            return

        size_idx = self.size_combo.currentIndex()
        if size_idx < len(PRESETS):
            _, w, h, dpi = PRESETS[size_idx]
        else:
            w = self.custom_width.value()
            h = self.custom_height.value()
            dpi = self.custom_dpi.value()

        today = date.today().strftime("%Y%m%d")
        log_path = get_base_dir() / f"转换日志_{today}.txt"

        self._set_busy(True)
        self.progress_bar.setMaximum(len(self.files))
        self.progress_bar.setValue(0)
        self.progress_label.setText("启动中...")

        self.worker = ConvertWorker(
            self.files.copy(), self.magick_path, self._selected_output,
            w, h, dpi,
            self.trim_cb.isChecked(), self.bw_cb.isChecked(),
            self.merge_btn.isChecked(), "0x3.0", 5, str(log_path))
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current, total, filename, status):
        self.progress_bar.setValue(current)
        self.progress_label.setText(f"[{current}/{total}] {filename} — {status}")

    def _on_finished(self, output_dir):
        self._set_busy(False)
        self.progress_label.setText("✓ 全部完成！")
        self.status_label.setText(f"完成！PDF 保存在：{output_dir}")
        self._last_output = output_dir
        self.open_btn.setEnabled(True)
        self.worker = None

    def _on_error(self, msg):
        self._set_busy(False)
        self.progress_label.setText("✗ 出错")
        log_path = get_base_dir() / f"转换日志_{date.today().strftime('%Y%m%d')}.txt"
        full_msg = msg
        if log_path.exists():
            full_msg += f"\n\n详细日志：{log_path}"
        QMessageBox.critical(self, "处理出错", full_msg)
        self._last_output = getattr(self.worker, '_outdir', str(get_base_dir()))
        self.open_btn.setEnabled(True)
        self.worker = None

    def _open_output(self):
        d = self._last_output
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
