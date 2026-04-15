#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
功能：保存和加载用户设置
"""

import json
import os
from pathlib import Path
from typing import Dict, Any


class ConfigManager:
    """配置管理器"""

    def __init__(self, config_file: str = "config.json"):
        """
        初始化配置管理器

        参数:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config_path = Path(config_file)

        # 默认配置
        self.default_config = {
            "download_path": str(Path.cwd()),  # 默认下载路径
            "max_workers": 16,                 # 默认并发线程数
            "max_concurrent_downloads": 3,     # 最大同时下载数
            "auto_cleanup": True,              # 自动清理临时文件
            "auto_generate_name": True,        # 自动生成文件名
            "window_geometry": "900x700",      # 窗口大小
        }

        # 当前配置
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """
        加载配置文件

        返回:
            配置字典
        """
        if not self.config_path.exists():
            # 配置文件不存在，创建默认配置
            self.save_config(self.default_config)
            return self.default_config.copy()

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 合并默认配置（防止缺少新添加的配置项）
            merged_config = self.default_config.copy()
            merged_config.update(config)

            return merged_config

        except Exception as e:
            print(f"加载配置失败: {e}，使用默认配置")
            return self.default_config.copy()

    def save_config(self, config: Dict[str, Any] = None):
        """
        保存配置到文件

        参数:
            config: 要保存的配置字典，None则保存当前配置
        """
        if config is None:
            config = self.config

        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

            self.config = config

        except Exception as e:
            print(f"保存配置失败: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项

        参数:
            key: 配置键
            default: 默认值

        返回:
            配置值
        """
        return self.config.get(key, default)

    def set(self, key: str, value: Any):
        """
        设置配置项

        参数:
            key: 配置键
            value: 配置值
        """
        self.config[key] = value
        self.save_config()

    def update(self, config_dict: Dict[str, Any]):
        """
        批量更新配置

        参数:
            config_dict: 配置字典
        """
        self.config.update(config_dict)
        self.save_config()

    def reset(self):
        """重置为默认配置"""
        self.config = self.default_config.copy()
        self.save_config()
