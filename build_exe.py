#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本 - 将 M3U8 下载器 GUI 打包为 Windows exe
"""

import PyInstaller.__main__
import os
import sys

# 获取当前目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# PyInstaller 参数
PyInstaller.__main__.run([
    'm3u8_downloader_gui.py',           # 主程序
    '--name=CatCatchAssistant',          # 输出的 exe 名称
    '--onefile',                         # 打包成单个 exe 文件
    '--windowed',                        # 窗口模式（不显示控制台）
    '--icon=icon.ico',                   # 应用图标
    '--clean',                           # 清理临时文件
    '--noconfirm',                       # 不询问确认

    # 添加数据文件（配置文件模板）
    '--add-data=icon.ico;.',

    # 隐藏导入（确保所有依赖都被包含）
    '--hidden-import=tkinter',
    '--hidden-import=tkinter.ttk',
    '--hidden-import=tkinter.scrolledtext',
    '--hidden-import=tkinter.filedialog',
    '--hidden-import=tkinter.messagebox',
    '--hidden-import=requests',
    '--hidden-import=bs4',
    '--hidden-import=m3u8_downloader',
    '--hidden-import=config_manager',

    # 排除不需要的模块以减小体积
    '--exclude-module=matplotlib',
    '--exclude-module=numpy',
    '--exclude-module=pandas',
    '--exclude-module=IPython',
    '--exclude-module=jupyter',
    '--exclude-module=selenium',
    '--exclude-module=webdriver_manager',
])

print("\n" + "="*60)
print("✅ 打包完成！")
print("="*60)
print(f"📁 输出目录: {os.path.join(current_dir, 'dist')}")
print(f"🎮 exe 文件: {os.path.join(current_dir, 'dist', 'CatCatchAssistant.exe')}")
print("="*60)
