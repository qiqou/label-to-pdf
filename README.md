# 快递单转PDF

电商快递单图片批量转PDF工具。自动裁边、转黑白（热敏优化）、合并多页、批次区分。

## 用法

[下载最新 exe](https://github.com/qiqou/label-to-pdf/actions) → Actions → 最新绿色 ✓ → Artifacts

解压 `快递单转PDF.exe` 到 `ImageMagick` 旁边，双击即用。

## 功能

- 📂 拖拽/选择图片（PNG、JPG、BMP、WEBP、TIFF）
- 📐 尺寸预设（945×945 / 100×150mm / 76×130mm / 自定义）
- ✂️ 自动裁边去白边
- ⚫ 转纯黑白（热敏打印机条码清晰）
- 📑 合并单PDF / 每张单独PDF
- 📁 自定义输出位置
- 🔢 同名文件自动编号不覆盖
- 🌙 暗色界面（qdarkstyle）

## 自行打包

```bash
pip install PySide6 qdarkstyle pyinstaller
pyinstaller --onefile --windowed --name "快递单转PDF" main.py
```

打包后 exe 在 `dist/`，和 `magick.exe` 放一起运行。
