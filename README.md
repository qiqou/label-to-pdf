# 快递单转PDF

电商快递单图片批量转PDF工具。自动裁边、转黑白（热敏优化）、合并多页。

## 使用方式

### 方式一：下载打包好的 exe（推荐）

1. 打开本仓库的 **Actions** 页面
2. 点最新的绿色 ✓ 工作流 → 底部 **Artifacts** → 下载 `快递单转PDF-vxxx.zip`
3. 解压，把 `快递单转PDF.exe` 和 `ImageMagick-...exe` 放在同一文件夹
4. 双击 `快递单转PDF.exe` 运行

> 需要 ImageMagick？点 [这里](https://imagemagick.org/script/download.php#windows) 下载 Windows 版
> 或者用本目录下的 `ImageMagick-7.1.1-29-Q16-HDRI-x64-static.exe`（静态版，免安装）

### 方式二：自己打包

```bash
pip install PySide6 qdarkstyle pyinstaller
pyinstaller --onefile --windowed --name "快递单转PDF" main.py
```

---

## 功能

- 📂 拖拽/选择图片（PNG、JPG、BMP、WEBP、TIFF）
- 📐 预设面单尺寸（945×945 / 100×150mm / 76×130mm / 原图）
- ✂️ 自动裁边去白边
- ⚫ 转纯黑白（热敏打印机条码更清晰）
- 📑 合并成一个多页PDF / 每张单独PDF
- 🌙 暗色界面
