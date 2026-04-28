#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8 视频下载器 - GUI 版本
支持多任务并行下载
"""

__version__ = "2.0.0"

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.widgets.scrolled import ScrolledText
from ttkbootstrap.widgets import ToolTip
import threading
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from queue import Queue, Empty

from m3u8_downloader import M3U8Downloader
from config_manager import ConfigManager


class MsgBox:
    """自定义消息框"""

    ICON_MAP = {
        'info': ('ℹ', 'info'),
        'warning': ('⚠', 'warning'),
        'error': ('✗', 'danger'),
        'question': ('?', 'primary')
    }

    def __init__(self, parent: ttk.Window):
        self.parent = parent
        self._icon_path = self._get_icon_path()

    def _get_icon_path(self) -> Optional[str]:
        """获取图标路径"""
        try:
            base_path = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
            icon_path = os.path.join(base_path, 'icon.ico')
            return icon_path if os.path.exists(icon_path) else None
        except OSError:
            return None

    def _create_dialog(self, title: str, height: int) -> ttk.Toplevel:
        """创建对话框基础框架"""
        dialog = ttk.Toplevel(self.parent)
        dialog.withdraw()
        dialog.title(title)
        dialog.geometry(f"400x{height}")
        dialog.resizable(False, False)
        dialog.transient(self.parent)
        dialog.grab_set()

        if self._icon_path:
            try:
                dialog.iconbitmap(self._icon_path)
            except OSError:
                pass

        self.parent.update_idletasks()
        x = self.parent.winfo_x() + (self.parent.winfo_width() - 400) // 2
        y = self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2
        dialog.geometry(f"+{x}+{y}")

        return dialog

    def _show(self, title: str, message: str, icon_type: str, buttons: List[Tuple[str, str, Optional[callable]]] = None) -> Optional[bool]:
        """显示对话框"""
        lines = message.count('\n') + 1
        height = max(200, 170 + lines * 26)
        dialog = self._create_dialog(title, height)

        result = [None]

        frame = ttk.Frame(dialog, padding=28)
        frame.pack(fill=BOTH, expand=YES)

        msg_frame = ttk.Frame(frame)
        msg_frame.pack(fill=BOTH, expand=YES)

        icon_char, bootstyle = self.ICON_MAP.get(icon_type, ('ℹ', 'info'))
        ttk.Label(msg_frame, text=icon_char, font=('Segoe UI', 28), bootstyle=bootstyle).pack(side=LEFT, padx=(0, 18))
        ttk.Label(msg_frame, text=message, font=('Segoe UI', 11), wraplength=300).pack(side=LEFT, fill=X, expand=YES)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=24)

        if buttons is None:
            buttons = [("确定", 'primary', None)]

        for i, (text, style, callback) in enumerate(buttons):
            def on_click(cb=callback, idx=i):
                if cb:
                    cb()
                result[0] = idx == 0
                dialog.destroy()

            ttk.Button(btn_frame, text=text, command=on_click, bootstyle=style, width=10).pack(side=LEFT, padx=6)

        dialog.deiconify()
        dialog.wait_window()
        return result[0]

    def show_info(self, message: str, title: str = "提示"):
        self._show(title, message, 'info')

    def show_warning(self, message: str, title: str = "警告"):
        self._show(title, message, 'warning')

    def show_error(self, message: str, title: str = "错误"):
        self._show(title, message, 'error')

    def yesno(self, message: str, title: str = "确认") -> bool:
        return self._show(title, message, 'question', [
            ("是", 'primary', None),
            ("否", 'secondary', None)
        ]) or False


class DownloadTask:
    """下载任务"""

    __slots__ = ('task_id', 'url', 'output_name', 'output_dir', 'max_workers', 'request_headers',
                 'status', 'progress', 'downloaded', 'total', 'message',
                 'downloader', 'thread', '_stop_flag')

    def __init__(self, task_id: int, url: str, output_name: str, output_dir: str, max_workers: int, request_headers: Optional[dict[str, str]] = None):
        self.task_id = task_id
        self.url = url
        self.output_name = output_name
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.request_headers = request_headers or {}
        self.status = "等待中"
        self.progress = 0.0
        self.downloaded = 0
        self.total = 0
        self.message = ""
        self.downloader: Optional[M3U8Downloader] = None
        self.thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

    def reset(self):
        """重置任务状态"""
        self.status = "等待中"
        self.progress = 0.0
        self.downloaded = 0
        self.total = 0
        self.message = ""
        self._stop_flag.clear()


class M3U8DownloaderGUI:
    """M3U8 下载器图形界面"""

    MAX_LOG_LINES = 500
    STARTABLE_STATUSES = ("等待中", "已失败", "已取消")
    FINISHED_STATUSES = ("已完成", "已失败", "已取消")
    RETRYABLE_STATUSES = ("已失败", "已取消")

    # 状态颜色配置
    STATUS_COLORS = {
        "等待中": "#64748b",
        "下载中": "#0ea5e9",
        "取消中": "#f59e0b",
        "已完成": "#22c55e",
        "已失败": "#ef4444",
        "已取消": "#f97316",
    }

    def __init__(self, root: ttk.Window):
        self.root = root
        self.root.title(f"M3U8 视频下载器 v{__version__}")

        self._set_window_icon(self.root)

        self.config_manager = ConfigManager()
        config = self.config_manager.config

        self.root.geometry(config.get('window_geometry', '1100x750'))
        self.root.minsize(900, 600)

        self.tasks: Dict[int, DownloadTask] = {}
        self.task_counter = 0
        self.max_concurrent = config.get('max_concurrent_downloads', 3)
        self.active_downloads = 0
        self._lock = threading.Lock()

        self.message_queue: Queue = Queue()
        self.msgbox = MsgBox(root)

        self._configure_styles()
        self._create_widgets()
        self._bind_shortcuts()
        self._process_messages()

    def _configure_styles(self):
        """配置界面样式"""
        style = ttk.Style()

        # 任务列表样式
        style.configure('Task.Treeview', rowheight=36, font=('Segoe UI', 10))
        style.configure('Task.Treeview.Heading', font=('Segoe UI', 10, 'bold'))

        # 标题样式
        style.configure('Header.TLabel', font=('Segoe UI', 20, 'bold'))
        style.configure('SubHeader.TLabel', font=('Segoe UI', 10))
        style.configure('Hint.TLabel', font=('Segoe UI', 9))
        style.configure('Stats.TLabel', font=('Segoe UI', 9, 'bold'))

        # 进度条样式
        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor='#e2e8f0',
            background='#0ea5e9',
            thickness=8
        )

    def _create_widgets(self):
        """创建所有界面组件"""
        # 主容器
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=BOTH, expand=YES)

        self._create_header(main_frame)
        self._create_input_section(main_frame)

        # 内容区域
        content_pane = ttk.Panedwindow(main_frame, orient=VERTICAL)
        content_pane.pack(fill=BOTH, expand=YES)

        task_panel = ttk.Frame(content_pane)
        log_panel = ttk.Frame(content_pane)
        content_pane.add(task_panel, weight=5)
        content_pane.add(log_panel, weight=2)

        self._create_task_section(task_panel)
        self._create_log_section(log_panel)

    def _create_header(self, parent: ttk.Frame):
        """创建标题栏"""
        header = ttk.Frame(parent)
        header.pack(fill=X, pady=(0, 16))

        # 左侧标题
        title_frame = ttk.Frame(header)
        title_frame.pack(side=LEFT)

        ttk.Label(
            title_frame,
            text=f"M3U8 视频下载器 v{__version__}",
            style='Header.TLabel',
            bootstyle='primary'
        ).pack(anchor=W)

        ttk.Label(
            title_frame,
            text="多任务并行下载 · 自动重试 · 支持主播放列表递归解析",
            style='SubHeader.TLabel',
            bootstyle='secondary'
        ).pack(anchor=W, pady=(4, 0))

        # 右侧操作区
        action_frame = ttk.Frame(header)
        action_frame.pack(side=RIGHT, anchor=NE)

        ttk.Label(
            action_frame,
            text="F5 全部开始  ·  Ctrl+Enter 添加任务",
            style='Hint.TLabel',
            bootstyle='secondary'
        ).pack(anchor=E, pady=(2, 8))

        ttk.Button(
            action_frame,
            text="设置",
            command=self._open_settings,
            width=8,
            bootstyle='secondary-outline'
        ).pack(anchor=E)

    def _create_input_section(self, parent: ttk.Frame):
        """创建输入区域"""
        input_card = ttk.LabelFrame(parent, text="  新建任务  ")
        input_card.pack(fill=X, pady=(0, 16))

        input_inner = ttk.Frame(input_card, padding=16)
        input_inner.pack(fill=X, expand=YES)

        notebook = ttk.Notebook(input_inner)
        notebook.pack(fill=X, expand=YES)

        self._create_single_task_tab(notebook)
        self._create_batch_task_tab(notebook)

    def _create_single_task_tab(self, notebook: ttk.Notebook):
        """创建单个任务标签页"""
        single_frame = ttk.Frame(notebook, padding=16)
        notebook.add(single_frame, text="单个任务")

        # 第一行：链接
        row1 = ttk.Frame(single_frame)
        row1.pack(fill=X, pady=(0, 12))

        ttk.Label(row1, text="链接", width=6, bootstyle='secondary').pack(side=LEFT)
        self.url_entry = ttk.Entry(row1, font=('Segoe UI', 10))
        self.url_entry.pack(side=LEFT, fill=X, expand=YES, padx=(8, 8))
        self.url_entry.bind('<Control-v>', lambda e: self._paste_from_clipboard())

        paste_btn = ttk.Button(row1, text="粘贴", command=self._paste_from_clipboard, width=8, bootstyle='secondary-outline')
        paste_btn.pack(side=LEFT)
        ToolTip(paste_btn, text="从剪贴板粘贴 (Ctrl+V)")

        # 第二行：路径和文件名
        row2 = ttk.Frame(single_frame)
        row2.pack(fill=X, pady=(0, 12))

        ttk.Label(row2, text="路径", width=6, bootstyle='secondary').pack(side=LEFT)
        self.path_entry = ttk.Entry(row2, font=('Segoe UI', 10), width=40)
        self.path_entry.pack(side=LEFT, padx=(8, 8))
        self.path_entry.insert(0, self.config_manager.get('download_path', os.getcwd()))

        browse_btn = ttk.Button(row2, text="浏览", command=self._browse_path, width=6, bootstyle='secondary-outline')
        browse_btn.pack(side=LEFT)
        ToolTip(browse_btn, text="选择保存路径")

        ttk.Label(row2, text="文件名", width=6).pack(side=LEFT, padx=(10, 0))
        self.output_entry = ttk.Entry(row2, font=('Segoe UI', 10))
        self.output_entry.pack(side=LEFT, fill=X, expand=YES, padx=(8, 0))

        # 第三行：线程数
        row_threads = ttk.Frame(single_frame)
        row_threads.pack(fill=X, pady=(0, 12))

        ttk.Label(row_threads, text="线程", width=6, bootstyle='secondary').pack(side=LEFT)
        self.thread_var = ttk.IntVar(value=self.config_manager.get('max_workers', 16))
        thread_spin = ttk.Spinbox(row_threads, from_=1, to=64, textvariable=self.thread_var, width=8, font=('Segoe UI', 10))
        thread_spin.pack(side=LEFT, padx=(8, 0))
        ToolTip(thread_spin, text="下载线程数 (建议 8-32)")

        # 请求头区域
        row_headers = ttk.Frame(single_frame)
        row_headers.pack(fill=X, pady=(0, 12))

        ttk.Label(row_headers, text="请求头", width=6, bootstyle='secondary').pack(side=LEFT, anchor=N, pady=(8, 0))
        self.headers_text = ScrolledText(row_headers, height=3, autohide=True)
        self.headers_text.pack(side=LEFT, fill=X, expand=YES, padx=(8, 0))
        ToolTip(self.headers_text, text='JSON 格式，例如 {"origin":"https://xxx","referer":"https://xxx"}')

        # 底部按钮行
        row3 = ttk.Frame(single_frame)
        row3.pack(fill=X)

        ttk.Label(
            row3,
            text='支持粘贴格式: 链接|文件名|{"origin":"...","referer":"..."}',
            style='Hint.TLabel',
            bootstyle='secondary'
        ).pack(side=LEFT)

        btn_frame = ttk.Frame(row3)
        btn_frame.pack(side=RIGHT)
        ttk.Button(btn_frame, text="粘贴添加", command=self._paste_and_add, width=10, bootstyle='secondary-outline').pack(side=LEFT, padx=(0, 8))
        ttk.Button(btn_frame, text="添加任务", command=self._add_task, bootstyle='primary', width=10).pack(side=LEFT)

    def _create_batch_task_tab(self, notebook: ttk.Notebook):
        """创建批量任务标签页"""
        batch_frame = ttk.Frame(notebook, padding=16)
        notebook.add(batch_frame, text="批量添加")

        ttk.Label(
            batch_frame,
            text='每行一个任务，格式: 链接|文件名|请求头JSON (后两项可选)',
            bootstyle='secondary'
        ).pack(anchor=W, pady=(0, 8))

        self.batch_text = ScrolledText(batch_frame, height=5, autohide=True)
        self.batch_text.pack(fill=X, expand=YES, pady=(0, 12))

        batch_btn_row = ttk.Frame(batch_frame)
        batch_btn_row.pack(fill=X)

        self.batch_path_label = ttk.Label(
            batch_btn_row,
            text=f"保存至: {self.path_entry.get()}",
            bootstyle='secondary'
        )
        self.batch_path_label.pack(side=LEFT)

        ttk.Button(
            batch_btn_row,
            text="批量添加",
            command=self._batch_add_tasks,
            bootstyle='primary',
            width=12
        ).pack(side=RIGHT)

    def _create_task_section(self, parent: ttk.Frame):
        """创建任务列表区域"""
        task_card = ttk.LabelFrame(parent, text="  下载任务  ")
        task_card.pack(fill=BOTH, expand=YES)

        task_inner = ttk.Frame(task_card, padding=14)
        task_inner.pack(fill=BOTH, expand=YES)

        # 工具栏
        toolbar = ttk.Frame(task_inner)
        toolbar.pack(fill=X, pady=(0, 12))

        # 左侧按钮组
        left_btns = ttk.Frame(toolbar)
        left_btns.pack(side=LEFT)

        # 主要操作按钮
        ttk.Button(
            left_btns, text="开始",
            command=self._start_selected, width=8, bootstyle='primary'
        ).pack(side=LEFT, padx=(0, 6))

        ttk.Button(
            left_btns, text="全部开始",
            command=self._start_all, width=10, bootstyle='success'
        ).pack(side=LEFT, padx=(0, 12))

        ttk.Separator(left_btns, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        # 次要操作按钮
        ttk.Button(
            left_btns, text="取消",
            command=self._pause_selected, width=6, bootstyle='warning-outline'
        ).pack(side=LEFT, padx=(0, 6))

        ttk.Button(
            left_btns, text="重试",
            command=self._retry_failed, width=6, bootstyle='info-outline'
        ).pack(side=LEFT, padx=(0, 12))

        ttk.Separator(left_btns, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        # 删除按钮
        ttk.Button(
            left_btns, text="删除",
            command=self._remove_selected, width=6, bootstyle='danger-outline'
        ).pack(side=LEFT, padx=(0, 6))

        ttk.Button(
            left_btns, text="清除",
            command=self._clear_completed, width=6, bootstyle='secondary-outline'
        ).pack(side=LEFT)

        # 统计信息
        self.stats_label = ttk.Label(
            toolbar, text="",
            style='Stats.TLabel',
            bootstyle='secondary',
            padding=(12, 6)
        )
        self.stats_label.pack(side=RIGHT, padx=(12, 0))
        self._update_stats()

        # 任务列表
        tree_frame = ttk.Frame(task_inner)
        tree_frame.pack(fill=BOTH, expand=YES)

        columns = ('id', 'filename', 'status', 'progress', 'speed')
        self.task_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show='headings',
            height=8,
            style='Task.Treeview',
            bootstyle='info',
            selectmode='extended'
        )

        col_configs = [
            ('id', '#', CENTER, 50),
            ('filename', '文件名', W, 380),
            ('status', '状态', CENTER, 90),
            ('progress', '进度', CENTER, 120),
            ('speed', '速度 / 信息', W, 200),
        ]
        for col_id, text, anchor, width in col_configs:
            self.task_tree.heading(col_id, text=text, anchor=anchor)
            self.task_tree.column(col_id, width=width, anchor=anchor)

        self._setup_task_tree_tags()

        scrollbar = ttk.Scrollbar(tree_frame, orient=VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=scrollbar.set)

        self.task_tree.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.task_tree.bind('<Double-1>', self._on_task_double_click)
        self.task_tree.bind('<Delete>', lambda e: self._remove_selected())
        self.task_tree.bind('<Return>', lambda e: self._start_selected())

        self._create_context_menu()

    def _setup_task_tree_tags(self):
        """配置任务列表状态配色"""
        for status, color in self.STATUS_COLORS.items():
            self.task_tree.tag_configure(f'status_{status}', foreground=color)

    def _create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = ttk.Menu(self.root, tearoff=0)
        menu_items = [
            ("开始", self._start_selected),
            ("取消", self._pause_selected),
            None,
            ("重试", self._retry_failed),
            ("删除", self._remove_selected),
            None,
            ("复制链接", self._copy_task_url),
            ("打开目录", self._open_task_folder),
        ]
        for item in menu_items:
            if item is None:
                self.context_menu.add_separator()
            else:
                self.context_menu.add_command(label=item[0], command=item[1])

        self.task_tree.bind('<Button-3>', self._show_context_menu)

    def _show_context_menu(self, event):
        """显示右键菜单"""
        item = self.task_tree.identify_row(event.y)
        if item:
            self.task_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def _on_task_double_click(self, event):
        """双击任务"""
        task = self._get_selected_task()
        if task:
            if task.status in self.STARTABLE_STATUSES:
                self._start_selected()
            elif task.status == "下载中":
                self._pause_selected()

    def _get_selected_task(self) -> Optional[DownloadTask]:
        """获取单个选中的任务"""
        selection = self.task_tree.selection()
        if selection:
            return self.tasks.get(int(selection[0]))
        return None

    def _copy_task_url(self):
        """复制任务链接"""
        task = self._get_selected_task()
        if task:
            self.root.clipboard_clear()
            self.root.clipboard_append(task.url)
            self._log(f"已复制链接: {task.url[:50]}...")

    def _open_task_folder(self):
        """打开任务目录"""
        task = self._get_selected_task()
        if task and os.path.exists(task.output_dir):
            os.startfile(task.output_dir)

    def _create_log_section(self, parent: ttk.Frame):
        """创建日志区域"""
        log_card = ttk.LabelFrame(parent, text="  运行日志  ")
        log_card.pack(fill=BOTH, expand=YES)

        log_inner = ttk.Frame(log_card, padding=12)
        log_inner.pack(fill=BOTH, expand=YES)

        self.log_text = ScrolledText(log_inner, height=5, autohide=True)
        self.log_text.pack(fill=BOTH, expand=YES)

        footer = ttk.Frame(log_inner)
        footer.pack(fill=X, pady=(10, 0))

        ttk.Label(
            footer,
            text="日志保留最近 500 行",
            style='Hint.TLabel',
            bootstyle='secondary'
        ).pack(side=LEFT)

        self.status_label = ttk.Label(
            footer,
            text="就绪",
            bootstyle='secondary',
            font=('Segoe UI', 9, 'bold')
        )
        self.status_label.pack(side=RIGHT)

    def _bind_shortcuts(self):
        """绑定快捷键"""
        shortcuts = [
            ('<Control-v>', lambda e: self._paste_from_clipboard()),
            ('<Control-Return>', lambda e: self._add_task()),
            ('<F5>', lambda e: self._start_all()),
            ('<Escape>', lambda e: self._pause_selected()),
        ]
        for key, cmd in shortcuts:
            self.root.bind(key, cmd)

    def _update_stats(self):
        """更新统计信息"""
        status_counts = {}
        for t in self.tasks.values():
            status_counts[t.status] = status_counts.get(t.status, 0) + 1

        self.stats_label.config(
            text=f"共 {len(self.tasks)} 个任务  ·  下载中: {status_counts.get('下载中', 0)}  ·  "
                 f"等待: {status_counts.get('等待中', 0)}  ·  完成: {status_counts.get('已完成', 0)}  ·  "
                 f"失败: {status_counts.get('已失败', 0)}"
        )

    def _set_window_icon(self, window):
        """设置窗口图标"""
        try:
            base_path = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
            icon_path = os.path.join(base_path, 'icon.ico')
            if os.path.exists(icon_path):
                window.iconbitmap(icon_path)
        except OSError:
            pass

    def _browse_path(self):
        """浏览下载路径"""
        from tkinter import filedialog
        path = filedialog.askdirectory(title="选择下载目录")
        if path:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, path)
            self.batch_path_label.config(text=f"保存至: {path}")
            self.config_manager.set('download_path', path)

    def _paste_from_clipboard(self):
        """从剪贴板粘贴URL"""
        try:
            clipboard_content = self.root.clipboard_get()
            if clipboard_content:
                parsed_task, _ = self._parse_task_line(clipboard_content.strip())
                if parsed_task:
                    url, output_name, request_headers = parsed_task
                    self.url_entry.delete(0, 'end')
                    self.url_entry.insert(0, url)
                    self.output_entry.delete(0, 'end')
                    if output_name:
                        self.output_entry.insert(0, output_name)
                    self.headers_text.delete("1.0", 'end')
                    if request_headers:
                        self.headers_text.insert('1.0', json.dumps(request_headers, ensure_ascii=False, indent=2))
                    self.output_entry.focus()
                else:
                    self.url_entry.delete(0, 'end')
                    self.url_entry.insert(0, clipboard_content.strip())
                    self.output_entry.focus()
        except OSError:
            pass

    def _log(self, message: str):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert('end', f"[{timestamp}] {message}\n")
        self.log_text.see('end')

        line_count = int(self.log_text.index('end-1c').split('.')[0])
        if line_count > self.MAX_LOG_LINES:
            self.log_text.delete('1.0', f'{line_count - self.MAX_LOG_LINES}.0')

    def _summarize_task_message(self, message: str, limit: int = 50) -> str:
        """压缩任务列表中的长消息"""
        if not message:
            return "-"
        compact = " ".join(message.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1] + "…"

    def _parse_request_headers(self, raw_text: str) -> tuple[Optional[dict[str, str]], Optional[str]]:
        """解析请求头 JSON 文本"""
        text = raw_text.strip()
        if not text:
            return {}, None

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, f"请求头 JSON 格式错误: {exc.msg}"

        if not isinstance(parsed, dict):
            return None, "请求头必须是 JSON 对象"

        headers = {}
        for key, value in parsed.items():
            key_str = str(key).strip()
            value_str = str(value).strip()
            if key_str and value_str:
                headers[key_str] = value_str
        return headers, None

    def _parse_task_line(self, line: str) -> tuple[Optional[tuple[str, Optional[str], dict[str, str]]], Optional[str]]:
        """解析任务行，支持 链接|文件名|请求头JSON"""
        parts = line.split('|', 2)
        url = parts[0].strip()
        if not url.startswith(('http://', 'https://')):
            return None, "无效链接"

        output_name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
        headers_text = parts[2].strip() if len(parts) > 2 else ""
        headers, error = self._parse_request_headers(headers_text)
        if error:
            return None, error

        return (url, output_name, headers or {}), None

    def _create_task(self, url: str, output_name: Optional[str], output_dir: str, max_workers: int, request_headers: Optional[dict[str, str]] = None) -> DownloadTask:
        """创建下载任务"""
        if not output_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"video_{timestamp}_{self.task_counter}"

        self.task_counter += 1
        return DownloadTask(
            task_id=self.task_counter,
            url=url,
            output_name=output_name,
            output_dir=output_dir,
            max_workers=max_workers,
            request_headers=request_headers
        )

    def _insert_task_to_tree(self, task: DownloadTask):
        """将任务插入到树形列表"""
        self.tasks[task.task_id] = task
        self.task_tree.insert('', 'end', iid=task.task_id, values=(
            task.task_id, f"{task.output_name}.mp4", task.status, "0%", "-"
        ), tags=(f'status_{task.status}',))

    def _save_config(self, output_dir: str, max_workers: int):
        """保存配置"""
        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

    def _add_task(self):
        """添加下载任务"""
        m3u8_url = self.url_entry.get().strip()
        output_name = self.output_entry.get().strip()
        output_dir = self.path_entry.get().strip()
        max_workers = self.thread_var.get()
        request_headers, error = self._parse_request_headers(self.headers_text.get("1.0", 'end'))

        if not m3u8_url:
            self.msgbox.show_error("请输入 M3U8 链接", "错误")
            return
        if not output_dir:
            self.msgbox.show_error("请选择下载路径", "错误")
            return
        if error:
            self.msgbox.show_error(error, "错误")
            return

        task = self._create_task(m3u8_url, output_name or None, output_dir, max_workers, request_headers)
        self._insert_task_to_tree(task)

        self._log(f"添加: {task.output_name}.mp4")
        self._update_stats()

        self.url_entry.delete(0, 'end')
        self.output_entry.delete(0, 'end')
        self.headers_text.delete("1.0", 'end')
        self.url_entry.focus()

        self._save_config(output_dir, max_workers)

    def _batch_add_tasks(self):
        """批量添加下载任务"""
        batch_text = self.batch_text.get("1.0", 'end').strip()
        output_dir = self.path_entry.get().strip()
        max_workers = self.thread_var.get()

        if not batch_text:
            self.msgbox.show_error("请输入要添加的任务", "错误")
            return
        if not output_dir:
            self.msgbox.show_error("请选择下载路径", "错误")
            return

        added_count = 0
        failed_count = 0
        failed_reasons = []

        for line in batch_text.split('\n'):
            line = line.strip()
            if not line:
                continue

            parsed_task, error = self._parse_task_line(line)
            if error or not parsed_task:
                failed_count += 1
                if error:
                    failed_reasons.append(f"{line[:40]} -> {error}")
                continue

            m3u8_url, output_name, request_headers = parsed_task
            task = self._create_task(m3u8_url, output_name, output_dir, max_workers, request_headers)
            self._insert_task_to_tree(task)
            added_count += 1

        self.batch_text.delete("1.0", 'end')
        self._log(f"批量添加: {added_count} 个任务")
        self._update_stats()
        self._save_config(output_dir, max_workers)

        if added_count > 0:
            message = f"成功添加 {added_count} 个任务\n跳过 {failed_count} 个无效任务"
            if failed_reasons:
                message += "\n\n示例错误:\n" + "\n".join(failed_reasons[:3])
            self.msgbox.show_info(message, "完成")

    def _paste_and_add(self):
        """从剪贴板读取并添加任务"""
        try:
            clipboard_content = self.root.clipboard_get().strip()
        except OSError:
            self.msgbox.show_warning("剪贴板为空", "提示")
            return

        if not clipboard_content:
            self.msgbox.show_warning("剪贴板为空", "提示")
            return

        output_dir = self.path_entry.get().strip()
        if not output_dir:
            self.msgbox.show_error("请选择下载路径", "错误")
            return

        valid_tasks = []
        failed_count = 0
        for line in clipboard_content.split('\n'):
            line = line.strip()
            if not line:
                continue

            parsed_task, error = self._parse_task_line(line)
            if parsed_task:
                valid_tasks.append(parsed_task)
            elif error:
                failed_count += 1

        if not valid_tasks:
            self.msgbox.show_warning('剪贴板中没有有效的下载链接\n\n格式: 链接|文件名|请求头JSON', "提示")
            return

        max_workers = self.thread_var.get()
        for url, name, request_headers in valid_tasks:
            task = self._create_task(url, name, output_dir, max_workers, request_headers)
            self._insert_task_to_tree(task)

        self._log(f"粘贴添加: {len(valid_tasks)} 个任务")
        self._update_stats()
        self._save_config(output_dir, max_workers)

        # 构建详细的成功消息
        task_details = []
        for i, (url, name, headers) in enumerate(valid_tasks[:5], 1):  # 最多显示5个
            detail = f"{i}. {name or '未命名'}\n   {url[:60]}{'...' if len(url) > 60 else ''}"
            task_details.append(detail)

        message = f"成功添加 {len(valid_tasks)} 个任务"
        if failed_count > 0:
            message += f"\n跳过 {failed_count} 个无效任务"
        if task_details:
            message += "\n\n" + "\n".join(task_details)
        if len(valid_tasks) > 5:
            message += f"\n... 还有 {len(valid_tasks) - 5} 个任务"

        self.msgbox.show_info(message, "完成")

    def _get_startable_tasks(self, selection_only: bool = False) -> List[DownloadTask]:
        """获取可启动的任务"""
        if selection_only:
            selection = self.task_tree.selection()
            if not selection:
                return []
            return [
                self.tasks[int(task_id)]
                for task_id in selection
                if self.tasks.get(int(task_id)) and self.tasks[int(task_id)].status in self.STARTABLE_STATUSES
            ]
        return [t for t in self.tasks.values() if t.status in self.STARTABLE_STATUSES]

    def _start_tasks(self, tasks: List[DownloadTask]) -> int:
        """启动多个任务，返回实际启动数量"""
        started = 0
        for task in tasks:
            if self.active_downloads >= self.max_concurrent:
                break
            self._start_task(task)
            started += 1
        return started

    def _start_selected(self):
        """开始选中的任务"""
        startable_tasks = self._get_startable_tasks(selection_only=True)
        if not startable_tasks:
            if self.task_tree.selection():
                return
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        if self.active_downloads >= self.max_concurrent:
            self.msgbox.show_warning(f"已达到最大并发数 {self.max_concurrent}", "提示")
            return

        started = self._start_tasks(startable_tasks)
        if started > 0:
            self._log(f"开始下载: {started} 个任务")

    def _start_all(self):
        """开始所有等待中的任务"""
        startable_tasks = self._get_startable_tasks()
        if not startable_tasks:
            self.msgbox.show_info("没有等待中的任务", "提示")
            return

        if self.active_downloads >= self.max_concurrent:
            self.msgbox.show_warning(f"已达到最大并发数 {self.max_concurrent}", "提示")
            return

        started = self._start_tasks(startable_tasks)
        self._log(f"全部开始: {started} 个任务")

    def _start_task(self, task: DownloadTask):
        """启动单个任务"""
        task.status = "下载中"
        task._stop_flag.clear()
        self._update_task_display(task)

        task.thread = threading.Thread(target=self._download_thread, args=(task,), daemon=True)
        task.thread.start()

        with self._lock:
            self.active_downloads += 1
        self._update_status()
        self._update_stats()

    def _download_thread(self, task: DownloadTask):
        """下载线程"""
        try:
            task.downloader = M3U8Downloader(
                task.url,
                task.output_name,
                task.max_workers,
                task.output_dir,
                task.request_headers
            )

            def progress_callback(current: int, total: int, message: str):
                if task._stop_flag.is_set():
                    if task.downloader:
                        task.downloader.stop()
                    return
                task.downloaded = current
                task.total = total
                if total > 0:
                    task.progress = (current / total) * 100
                task.message = message
                self.message_queue.put(('progress', task.task_id))

            task.downloader.progress_callback = progress_callback
            auto_cleanup = self.config_manager.get('auto_cleanup', True)
            task.downloader.download(auto_cleanup=auto_cleanup)

            if task._stop_flag.is_set():
                task.status = "已取消"
                self.message_queue.put(('cancelled', task.task_id))
            else:
                task.status = "已完成"
                self.message_queue.put(('complete', task.task_id))

        except Exception as e:
            if task._stop_flag.is_set():
                task.status = "已取消"
                self.message_queue.put(('cancelled', task.task_id))
            else:
                task.status = "已失败"
                task.message = str(e)
                self.message_queue.put(('error', task.task_id, str(e)))

        finally:
            if task.downloader:
                task.downloader.close()
            with self._lock:
                self.active_downloads -= 1
            self.message_queue.put(('finish', task.task_id))

    def _pause_selected(self):
        """取消选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        cancelled_count = 0
        for task_id in selection:
            task = self.tasks.get(int(task_id))
            if task and task.status == "下载中":
                task._stop_flag.set()
                if task.downloader:
                    task.downloader.stop()
                task.status = "取消中"
                self._update_task_display(task)
                cancelled_count += 1

        if cancelled_count > 0:
            self._log(f"取消: {cancelled_count} 个任务")

    def _remove_selected(self):
        """删除选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        removed = 0
        for task_id in selection:
            tid = int(task_id)
            task = self.tasks.get(tid)
            if task and task.status != "下载中":
                del self.tasks[tid]
                self.task_tree.delete(tid)
                removed += 1

        if removed > 0:
            self._log(f"删除: {removed} 个任务")
            self._update_stats()

    def _clear_completed(self):
        """清除已完成的任务"""
        completed_ids = [tid for tid, t in self.tasks.items() if t.status in self.FINISHED_STATUSES]

        for task_id in completed_ids:
            del self.tasks[task_id]
            self.task_tree.delete(task_id)

        if completed_ids:
            self._log(f"清除: {len(completed_ids)} 个任务")
            self._update_stats()

    def _retry_failed(self):
        """重试失败的任务"""
        failed_tasks = [t for t in self.tasks.values() if t.status in self.RETRYABLE_STATUSES]

        if not failed_tasks:
            self.msgbox.show_info("没有失败的任务需要重试", "提示")
            return

        if self.active_downloads >= self.max_concurrent:
            self.msgbox.show_warning(f"已达到最大并发数 {self.max_concurrent}", "提示")
            return

        started = 0
        for task in failed_tasks:
            if self.active_downloads >= self.max_concurrent:
                break
            task.reset()
            self._update_task_display(task)
            self._start_task(task)
            started += 1

        self._log(f"重试: {started} 个任务")

    def _update_task_display(self, task: DownloadTask):
        """更新任务显示"""
        if task.task_id in self.tasks:
            speed_str = self._summarize_task_message(task.message)
            progress_str = f"{task.progress:.1f}%" if task.total > 0 else f"{task.downloaded}"

            self.task_tree.item(task.task_id, values=(
                task.task_id, f"{task.output_name}.mp4", task.status, progress_str, speed_str
            ), tags=(f'status_{task.status}',))

    def _update_status(self):
        """更新状态栏"""
        self.status_label.config(text=f"活动下载: {self.active_downloads}  ·  最大并发: {self.max_concurrent}")

    def _start_waiting_tasks(self):
        """检查并启动等待中的任务"""
        if self.active_downloads >= self.max_concurrent:
            return

        for task in self.tasks.values():
            if task.status == "等待中" and self.active_downloads < self.max_concurrent:
                self._start_task(task)

    def _process_messages(self):
        """处理消息队列"""
        try:
            while True:
                msg = self.message_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == 'progress':
                    task = self.tasks.get(msg[1])
                    if task:
                        self._update_task_display(task)

                elif msg_type == 'complete':
                    task = self.tasks.get(msg[1])
                    if task:
                        self._update_task_display(task)
                        self._log(f"完成: {task.output_name}.mp4")
                        self._update_stats()

                elif msg_type == 'cancelled':
                    task = self.tasks.get(msg[1])
                    if task:
                        self._update_task_display(task)
                        self._log(f"已取消: {task.output_name}.mp4")
                        self._update_stats()

                elif msg_type == 'error':
                    task = self.tasks.get(msg[1])
                    if task:
                        self._update_task_display(task)
                        self._log(f"失败: {task.output_name}.mp4 - {msg[2]}")
                        self._update_stats()

                elif msg_type == 'finish':
                    self._update_status()
                    self._start_waiting_tasks()

        except Empty:
            pass

        self.root.after(100, self._process_messages)

    def _open_settings(self):
        """打开设置窗口"""
        settings_window = ttk.Toplevel(self.root)
        settings_window.withdraw()
        settings_window.title("设置")
        settings_window.geometry("420x320")
        settings_window.resizable(False, False)

        self._set_window_icon(settings_window)
        settings_window.transient(self.root)
        settings_window.grab_set()

        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 420) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 320) // 2
        settings_window.geometry(f"+{x}+{y}")

        frame = ttk.Frame(settings_window, padding=28)
        frame.pack(fill=BOTH, expand=YES)

        # 设置项
        row1 = ttk.Frame(frame)
        row1.pack(fill=X, pady=12)
        ttk.Label(row1, text="最大并发下载数", font=('Segoe UI', 10)).pack(side=LEFT)
        max_concurrent_var = ttk.IntVar(value=self.max_concurrent)
        ttk.Spinbox(row1, from_=1, to=10, textvariable=max_concurrent_var, width=10, font=('Segoe UI', 10)).pack(side=RIGHT)

        row2 = ttk.Frame(frame)
        row2.pack(fill=X, pady=12)
        ttk.Label(row2, text="默认下载线程", font=('Segoe UI', 10)).pack(side=LEFT)
        default_workers_var = ttk.IntVar(value=self.config_manager.get('max_workers', 16))
        ttk.Spinbox(row2, from_=1, to=64, textvariable=default_workers_var, width=10, font=('Segoe UI', 10)).pack(side=RIGHT)

        auto_cleanup_var = ttk.BooleanVar(value=self.config_manager.get('auto_cleanup', True))
        ttk.Checkbutton(
            frame, text="自动清理临时文件",
            variable=auto_cleanup_var, bootstyle='success'
        ).pack(anchor=W, pady=20)

        def save_settings():
            self.max_concurrent = max_concurrent_var.get()
            self.config_manager.update({
                'max_concurrent_downloads': max_concurrent_var.get(),
                'max_workers': default_workers_var.get(),
                'auto_cleanup': auto_cleanup_var.get()
            })
            self._update_status()
            settings_window.destroy()
            self.msgbox.show_info("设置已保存", "成功")

        ttk.Button(
            frame, text="保存设置",
            command=save_settings,
            bootstyle='primary',
            width=14
        ).pack(pady=24)

        settings_window.deiconify()

    def on_closing(self):
        """窗口关闭事件"""
        self.config_manager.set('window_geometry', self.root.geometry())

        downloading = [t for t in self.tasks.values() if t.status == "下载中"]
        if downloading:
            if self.msgbox.yesno(f"还有 {len(downloading)} 个任务正在下载，确定要退出吗？", "确认退出"):
                self.root.destroy()
        else:
            self.root.destroy()


def main():
    """主函数"""
    root = ttk.Window(themename="cosmo")
    root.withdraw()
    app = M3U8DownloaderGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
