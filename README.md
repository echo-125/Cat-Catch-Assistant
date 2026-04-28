# Cat Catch Assistant

M3U8 视频下载工具，支持多任务并行下载、断点续传、自动重试。

## 技术栈

- **Python 3.x** - 核心语言
- **ttkbootstrap** - 现代化 GUI 框架（基于 Bootstrap 风格）
- **requests** - HTTP 请求库
- **ffmpeg** - 视频转码工具（可选）

## 功能特点

- 自动解析 M3U8 播放列表
- 支持主播放列表和嵌套 M3U8 自动解析
- 多线程并发下载（可配置 1-64 线程）
- 多任务并行下载（可配置最大并发数）
- 断点续传、失败自动重试
- 实时进度、速度显示
- 自动合并 TS 分片并转换为 MP4

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行 GUI

```bash
python m3u8_downloader_gui.py
```

### 命令行使用

```bash
python m3u8_downloader.py <M3U8_URL> [文件名] [保存路径]
```

### 运行测试

```bash
python -m unittest discover -s tests
```

## 项目结构

```
├── m3u8_downloader.py       # 核心下载器
├── m3u8_downloader_gui.py   # GUI 界面
├── config_manager.py        # 配置管理
├── build_exe.py             # EXE 打包脚本
├── requirements.txt         # 依赖列表
└── icon.ico                 # 应用图标
```

## EXE 打包

```bash
pip install pyinstaller
python build_exe.py
```

默认输出文件为 `dist/M3U8下载器.exe`，打包配置使用 `M3U8下载器.spec`。

## 常见问题

**Q: 如何获取 M3U8 链接？**

使用浏览器插件（如 cat-catch、Video DownloadHelper）或开发者工具 Network 面板查找 `.m3u8` 请求。

**Q: 提示未找到 ffmpeg？**

安装 ffmpeg 并添加到系统 PATH，或手动转换：`ffmpeg -i merged.ts -c copy output.mp4`

**Q: 下载速度慢？**

在设置中增加并发线程数（默认 16，可增加到 32 或 64）。
