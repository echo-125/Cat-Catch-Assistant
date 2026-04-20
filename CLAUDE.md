# Cat Catch Assistant - M3U8 视频下载器

## 项目概述

M3U8 视频下载工具，支持多任务并行下载、断点续传、自动重试。

## 技术栈

- Python 3.x
- ttkbootstrap (GUI)
- requests (HTTP)
- ffmpeg (视频转码，可选)

## 核心文件

| 文件 | 说明 |
|------|------|
| m3u8_downloader.py | 核心下载器，处理 M3U8 解析、分片下载、合并转换 |
| m3u8_downloader_gui.py | GUI 界面，基于 ttkbootstrap |
| config_manager.py | 配置管理，JSON 格式存储 |
| build_exe.py | PyInstaller 打包脚本 |

## 开发命令

```bash
# 运行 GUI
python m3u8_downloader_gui.py

# 命令行下载
python m3u8_downloader.py <URL> [文件名] [路径]

# 语法检查
python -m py_compile *.py

# 打包 EXE
pip install pyinstaller
python build_exe.py
```

## 配置文件

配置存储在 `config.json`：

```json
{
  "download_path": "下载路径",
  "max_workers": 16,
  "max_concurrent_downloads": 3,
  "auto_cleanup": true,
  "window_geometry": "1000x680"
}
```

## GUI 功能

- 单个/批量添加任务
- 多任务并行下载
- 任务状态：等待中、下载中、已完成、已失败、已取消
- 快捷键：Ctrl+V 粘贴、Enter 开始、Delete 删除、F5 全部开始
- 右键菜单：开始、取消、重试、删除、复制链接、打开目录

## 下载流程

1. 下载 M3U8 播放列表
2. 解析提取 TS 分片 URL
3. 多线程并发下载分片
4. 合并所有分片
5. 转换为 MP4（需要 ffmpeg）
6. 清理临时文件
