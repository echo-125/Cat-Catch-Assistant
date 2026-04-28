#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本 - 将 M3U8 下载器 GUI 打包为 Windows exe
"""

import PyInstaller.__main__
from pathlib import Path

current_dir = Path(__file__).resolve().parent
spec_path = current_dir / "M3U8下载器.spec"

if not spec_path.exists():
    raise FileNotFoundError(f"未找到打包配置文件: {spec_path}")

PyInstaller.__main__.run([
    str(spec_path),
    '--clean',
    '--noconfirm',
])

print("\n" + "="*60)
print("✅ 打包完成！")
print("="*60)
print(f"📁 输出目录: {current_dir / 'dist'}")
print(f"🎮 exe 文件: {current_dir / 'dist' / 'M3U8下载器.exe'}")
print("="*60)
