#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将 PNG 图标转换为 ICO 格式
"""

from PIL import Image

# 打开 PNG 图标
img = Image.open('icon.png')

# 转换为 RGBA 模式（确保透明通道）
if img.mode != 'RGBA':
    img = img.convert('RGBA')

# 创建多个尺寸的图标（Windows 推荐尺寸）
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# 保存为 ICO 格式
img.save('icon.ico', format='ICO', sizes=sizes)

print("✅ 图标转换成功: icon.ico")
print(f"   原始尺寸: {img.size}")
print(f"   包含尺寸: {sizes}")
