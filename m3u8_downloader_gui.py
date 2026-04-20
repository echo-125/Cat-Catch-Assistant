#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8 视频下载器 - GUI 版本
支持多任务并行下载
"""

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledText
from ttkbootstrap.tooltip import ToolTip
import threading
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from queue import Queue

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

    def __init__(self, parent):
        self.parent = parent
        self._icon_path = self._get_icon_path()

    def _get_icon_path(self) -> Optional[str]:
        """获取图标路径"""
        try:
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, 'icon.ico')
            else:
                icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
            return icon_path if os.path.exists(icon_path) else None
        except OSError:
            return None

    def _create_dialog(self, title: str, message: str, height: int) -> ttk.Toplevel:
        """创建对话框基础框架"""
        dialog = ttk.Toplevel(self.parent)
        dialog.withdraw()
        dialog.title(title)
        dialog.geometry(f"380x{height}")
        dialog.resizable(False, False)
        dialog.transient(self.parent)
        dialog.grab_set()

        if self._icon_path:
            try:
                dialog.iconbitmap(self._icon_path)
            except OSError:
                pass

        self.parent.update_idletasks()
        x = self.parent.winfo_x() + (self.parent.winfo_width() - 380) // 2
        y = self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2
        dialog.geometry(f"+{x}+{y}")

        return dialog

    def show_info(self, message: str, title: str = "提示"):
        self._show(title, message, 'info')

    def show_warning(self, message: str, title: str = "警告"):
        self._show(title, message, 'warning')

    def show_error(self, message: str, title: str = "错误"):
        self._show(title, message, 'error')

    def _show(self, title: str, message: str, icon_type: str):
        """显示消息框"""
        lines = message.count('\n') + 1
        height = max(160, 130 + lines * 22)
        dialog = self._create_dialog(title, message, height)

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=YES)

        msg_frame = ttk.Frame(frame)
        msg_frame.pack(fill=BOTH, expand=YES)

        icon_char, bootstyle = self.ICON_MAP.get(icon_type, ('ℹ', 'info'))
        ttk.Label(msg_frame, text=icon_char, font=('Segoe UI', 24), bootstyle=bootstyle).pack(side=LEFT, padx=(0, 15))
        ttk.Label(msg_frame, text=message, font=('Segoe UI', 10), wraplength=280).pack(side=LEFT, fill=X, expand=YES)

        ttk.Button(frame, text="确定", command=dialog.destroy, bootstyle='primary', width=10).pack(pady=15)

        dialog.deiconify()
        dialog.wait_window()

    def yesno(self, message: str, title: str = "确认") -> bool:
        """显示询问框"""
        lines = message.count('\n') + 1
        height = max(160, 130 + lines * 22)
        dialog = self._create_dialog(title, message, height)

        result = [False]

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=YES)

        msg_frame = ttk.Frame(frame)
        msg_frame.pack(fill=BOTH, expand=YES)

        ttk.Label(msg_frame, text='?', font=('Segoe UI', 24), bootstyle='primary').pack(side=LEFT, padx=(0, 15))
        ttk.Label(msg_frame, text=message, font=('Segoe UI', 10), wraplength=280).pack(side=LEFT, fill=X, expand=YES)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=15)

        ttk.Button(btn_frame, text="是", command=lambda: [result.__setitem__(0, True), dialog.destroy()], bootstyle='primary', width=8).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="否", command=dialog.destroy, width=8).pack(side=LEFT, padx=5)

        dialog.deiconify()
        dialog.wait_window()
        return result[0]


class DownloadTask:
    """下载任务"""

    def __init__(self, task_id: int, url: str, output_name: str, output_dir: str, max_workers: int):
        self.task_id = task_id
        self.url = url
        self.output_name = output_name
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.status = "等待中"
        self.progress = 0.0
        self.downloaded = 0
        self.total = 0
        self.message = ""
        self.downloader: Optional[M3U8Downloader] = None
        self.thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()


class M3U8DownloaderGUI:
    """M3U8 下载器图形界面"""

    MAX_LOG_LINES = 500

    def __init__(self, root: ttk.Window):
        self.root = root
        self.root.title("M3U8 视频下载器")

        self._set_window_icon(self.root)

        self.config_manager = ConfigManager()
        config = self.config_manager.config

        geometry = config.get('window_geometry', '1000x680')
        self.root.geometry(geometry)
        self.root.minsize(800, 550)

        self.tasks: Dict[int, DownloadTask] = {}
        self.task_counter = 0
        self.max_concurrent = config.get('max_concurrent_downloads', 3)
        self.active_downloads = 0
        self._lock = threading.Lock()

        self.message_queue: Queue = Queue()
        self.msgbox = MsgBox(root)

        self._create_widgets()
        self._bind_shortcuts()
        self._process_messages()

    def _create_widgets(self):
        """创建所有界面组件"""
        main_frame = ttk.Frame(self.root, padding=16)
        main_frame.pack(fill=BOTH, expand=YES)

        self._create_header(main_frame)
        self._create_input_section(main_frame)
        self._create_task_section(main_frame)
        self._create_status_bar(main_frame)

    def _create_header(self, parent: ttk.Frame):
        """创建标题栏"""
        header = ttk.Frame(parent)
        header.pack(fill=X, pady=(0, 12))

        title_frame = ttk.Frame(header)
        title_frame.pack(side=LEFT)

        ttk.Label(
            title_frame,
            text="M3U8 视频下载器",
            font=('Segoe UI', 16, 'bold'),
            bootstyle='primary'
        ).pack(side=LEFT)

        ttk.Label(
            title_frame,
            text="v3.1",
            font=('Segoe UI', 9),
            bootstyle='secondary'
        ).pack(side=LEFT, padx=(6, 0), pady=(7, 0))

        ttk.Button(
            header,
            text="设置",
            command=self._open_settings,
            width=8
        ).pack(side=RIGHT)

    def _create_input_section(self, parent: ttk.Frame):
        """创建输入区域"""
        input_card = ttk.Labelframe(parent, text="添加任务", padding=12)
        input_card.pack(fill=X, pady=(0, 12))

        notebook = ttk.Notebook(input_card)
        notebook.pack(fill=X, expand=YES)

        self._create_single_task_tab(notebook)
        self._create_batch_task_tab(notebook)

    def _create_single_task_tab(self, notebook: ttk.Notebook):
        """创建单个任务标签页"""
        single_frame = ttk.Frame(notebook, padding=12)
        notebook.add(single_frame, text="单个任务")

        row1 = ttk.Frame(single_frame)
        row1.pack(fill=X, pady=(0, 8))

        ttk.Label(row1, text="链接", width=6).pack(side=LEFT)
        self.url_entry = ttk.Entry(row1)
        self.url_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 8))
        self.url_entry.bind('<Control-v>', lambda e: self._paste_from_clipboard())

        paste_btn = ttk.Button(row1, text="粘贴", command=self._paste_from_clipboard, width=6)
        paste_btn.pack(side=LEFT)
        ToolTip(paste_btn, text="从剪贴板粘贴 (Ctrl+V)")

        row2 = ttk.Frame(single_frame)
        row2.pack(fill=X, pady=(0, 10))

        ttk.Label(row2, text="路径", width=6).pack(side=LEFT)
        self.path_entry = ttk.Entry(row2)
        self.path_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 8))
        self.path_entry.insert(0, self.config_manager.get('download_path', os.getcwd()))

        browse_btn = ttk.Button(row2, text="...", command=self._browse_path, width=3)
        browse_btn.pack(side=LEFT, padx=(0, 12))
        ToolTip(browse_btn, text="选择保存路径")

        ttk.Label(row2, text="文件名", width=6).pack(side=LEFT)
        self.output_entry = ttk.Entry(row2, width=20)
        self.output_entry.pack(side=LEFT, padx=(4, 8))

        ttk.Label(row2, text="线程").pack(side=LEFT)
        self.thread_var = ttk.IntVar(value=self.config_manager.get('max_workers', 16))
        thread_spin = ttk.Spinbox(row2, from_=1, to=64, textvariable=self.thread_var, width=5)
        thread_spin.pack(side=LEFT, padx=(4, 0))
        ToolTip(thread_spin, text="下载线程数")

        row3 = ttk.Frame(single_frame)
        row3.pack(fill=X)

        ttk.Button(row3, text="粘贴添加", command=self._paste_and_add, width=10).pack(side=LEFT, padx=(0, 6))
        ttk.Label(row3, text="").pack(side=LEFT, fill=X, expand=YES)
        ttk.Button(row3, text="添加任务", command=self._add_task, bootstyle='primary', width=10).pack(side=RIGHT)

    def _create_batch_task_tab(self, notebook: ttk.Notebook):
        """创建批量任务标签页"""
        batch_frame = ttk.Frame(notebook, padding=12)
        notebook.add(batch_frame, text="批量添加")

        ttk.Label(
            batch_frame, text="每行一个任务，格式: 链接|文件名 (文件名可选)", bootstyle='secondary'
        ).pack(anchor=W, pady=(0, 6))

        self.batch_text = ScrolledText(batch_frame, height=4, autohide=True)
        self.batch_text.pack(fill=X, expand=YES, pady=(0, 8))

        batch_btn_row = ttk.Frame(batch_frame)
        batch_btn_row.pack(fill=X)

        self.batch_path_label = ttk.Label(
            batch_btn_row, text=f"保存至: {self.path_entry.get()}", bootstyle='secondary'
        )
        self.batch_path_label.pack(side=LEFT)

        ttk.Button(
            batch_btn_row, text="批量添加", command=self._batch_add_tasks, bootstyle='primary', width=12
        ).pack(side=RIGHT)

    def _create_task_section(self, parent: ttk.Frame):
        """创建任务列表区域"""
        task_card = ttk.Labelframe(parent, text="下载任务", padding=12)
        task_card.pack(fill=BOTH, expand=YES, pady=(0, 12))

        toolbar = ttk.Frame(task_card)
        toolbar.pack(fill=X, pady=(0, 8))

        left_btns = ttk.Frame(toolbar)
        left_btns.pack(side=LEFT)

        start_btn = ttk.Button(left_btns, text="开始", command=self._start_selected, width=6)
        start_btn.pack(side=LEFT, padx=(0, 4))
        ToolTip(start_btn, text="开始选中的任务")

        start_all_btn = ttk.Button(left_btns, text="全部开始", command=self._start_all, width=8)
        start_all_btn.pack(side=LEFT, padx=4)
        ToolTip(start_all_btn, text="开始所有等待中的任务")

        ttk.Separator(left_btns, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        cancel_btn = ttk.Button(left_btns, text="取消", command=self._pause_selected, width=6)
        cancel_btn.pack(side=LEFT, padx=4)
        ToolTip(cancel_btn, text="取消选中的下载任务")

        retry_btn = ttk.Button(left_btns, text="重试", command=self._retry_failed, width=6)
        retry_btn.pack(side=LEFT, padx=4)
        ToolTip(retry_btn, text="重试失败的任务")

        ttk.Separator(left_btns, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        remove_btn = ttk.Button(left_btns, text="删除", command=self._remove_selected, width=6)
        remove_btn.pack(side=LEFT, padx=4)
        ToolTip(remove_btn, text="删除选中的任务")

        clear_btn = ttk.Button(left_btns, text="清除", command=self._clear_completed, width=6)
        clear_btn.pack(side=LEFT, padx=4)
        ToolTip(clear_btn, text="清除已完成/失败的任务")

        self.stats_label = ttk.Label(toolbar, text="", bootstyle='secondary')
        self.stats_label.pack(side=RIGHT)
        self._update_stats()

        columns = ('id', 'filename', 'status', 'progress', 'speed')
        self.task_tree = ttk.Treeview(
            task_card,
            columns=columns,
            show='headings',
            height=8,
            bootstyle='info',
            selectmode='extended'
        )

        self.task_tree.heading('id', text='#', anchor=CENTER)
        self.task_tree.heading('filename', text='文件名', anchor=W)
        self.task_tree.heading('status', text='状态', anchor=CENTER)
        self.task_tree.heading('progress', text='进度', anchor=CENTER)
        self.task_tree.heading('speed', text='速度', anchor=CENTER)

        self.task_tree.column('id', width=40, anchor=CENTER)
        self.task_tree.column('filename', width=350, anchor=W)
        self.task_tree.column('status', width=80, anchor=CENTER)
        self.task_tree.column('progress', width=100, anchor=CENTER)
        self.task_tree.column('speed', width=100, anchor=CENTER)

        scrollbar = ttk.Scrollbar(task_card, orient=VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=scrollbar.set)

        self.task_tree.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

        self.task_tree.bind('<Double-1>', self._on_task_double_click)
        self.task_tree.bind('<Delete>', lambda e: self._remove_selected())
        self.task_tree.bind('<Return>', lambda e: self._start_selected())

        self._create_context_menu()

    def _create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = ttk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="开始", command=self._start_selected)
        self.context_menu.add_command(label="取消", command=self._pause_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="重试", command=self._retry_failed)
        self.context_menu.add_command(label="删除", command=self._remove_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制链接", command=self._copy_task_url)
        self.context_menu.add_command(label="打开目录", command=self._open_task_folder)

        self.task_tree.bind('<Button-3>', self._show_context_menu)

    def _show_context_menu(self, event):
        """显示右键菜单"""
        item = self.task_tree.identify_row(event.y)
        if item:
            self.task_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def _on_task_double_click(self, event):
        """双击任务"""
        selection = self.task_tree.selection()
        if selection:
            task_id = int(selection[0])
            task = self.tasks.get(task_id)
            if task:
                if task.status in ["等待中", "已暂停", "已失败", "已取消"]:
                    self._start_selected()
                elif task.status == "下载中":
                    self._pause_selected()

    def _copy_task_url(self):
        """复制任务链接"""
        selection = self.task_tree.selection()
        if selection:
            task_id = int(selection[0])
            task = self.tasks.get(task_id)
            if task:
                self.root.clipboard_clear()
                self.root.clipboard_append(task.url)
                self._log(f"已复制链接: {task.url[:50]}...")

    def _open_task_folder(self):
        """打开任务目录"""
        selection = self.task_tree.selection()
        if selection:
            task_id = int(selection[0])
            task = self.tasks.get(task_id)
            if task and os.path.exists(task.output_dir):
                os.startfile(task.output_dir)

    def _create_status_bar(self, parent: ttk.Frame):
        """创建底部区域"""
        bottom_frame = ttk.Frame(parent)
        bottom_frame.pack(fill=BOTH, expand=YES)

        log_frame = ttk.Labelframe(bottom_frame, text="日志", padding=8)
        log_frame.pack(fill=BOTH, expand=YES, pady=(0, 8))

        self.log_text = ScrolledText(log_frame, height=4, autohide=True)
        self.log_text.pack(fill=BOTH, expand=YES)

        self.status_label = ttk.Label(
            bottom_frame,
            text="就绪",
            bootstyle='secondary',
            font=('Segoe UI', 9)
        )
        self.status_label.pack(anchor=W)

    def _bind_shortcuts(self):
        """绑定快捷键"""
        self.root.bind('<Control-v>', lambda e: self._paste_from_clipboard())
        self.root.bind('<Control-Return>', lambda e: self._add_task())
        self.root.bind('<F5>', lambda e: self._start_all())
        self.root.bind('<Escape>', lambda e: self._pause_selected())

    def _update_stats(self):
        """更新统计信息"""
        total = len(self.tasks)
        waiting = sum(1 for t in self.tasks.values() if t.status == "等待中")
        downloading = sum(1 for t in self.tasks.values() if t.status == "下载中")
        completed = sum(1 for t in self.tasks.values() if t.status == "已完成")
        failed = sum(1 for t in self.tasks.values() if t.status == "已失败")

        self.stats_label.config(
            text=f"共 {total} 个任务 | 下载中: {downloading} | 等待: {waiting} | 完成: {completed} | 失败: {failed}"
        )

    def _set_window_icon(self, window):
        """设置窗口图标"""
        try:
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, 'icon.ico')
            else:
                icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')

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

    def _create_task(self, url: str, output_name: Optional[str], output_dir: str, max_workers: int) -> DownloadTask:
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
            max_workers=max_workers
        )

    def _insert_task_to_tree(self, task: DownloadTask):
        """将任务插入到树形列表"""
        self.tasks[task.task_id] = task
        self.task_tree.insert('', 'end', iid=task.task_id, values=(
            task.task_id,
            f"{task.output_name}.mp4",
            task.status,
            "0%",
            "-"
        ))

    def _add_task(self):
        """添加下载任务"""
        m3u8_url = self.url_entry.get().strip()
        output_name = self.output_entry.get().strip()
        output_dir = self.path_entry.get().strip()
        max_workers = self.thread_var.get()

        if not m3u8_url:
            self.msgbox.show_error("请输入 M3U8 链接", "错误")
            return

        if not output_dir:
            self.msgbox.show_error("请选择下载路径", "错误")
            return

        task = self._create_task(m3u8_url, output_name or None, output_dir, max_workers)
        self._insert_task_to_tree(task)

        self._log(f"添加: {task.output_name}.mp4")
        self._update_stats()

        self.url_entry.delete(0, 'end')
        self.output_entry.delete(0, 'end')
        self.url_entry.focus()

        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

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

        for line in batch_text.split('\n'):
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            m3u8_url = parts[0].strip()

            if not m3u8_url.startswith(('http://', 'https://')):
                failed_count += 1
                continue

            output_name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
            task = self._create_task(m3u8_url, output_name, output_dir, max_workers)
            self._insert_task_to_tree(task)
            added_count += 1

        self.batch_text.delete("1.0", 'end')
        self._log(f"批量添加: {added_count} 个任务")
        self._update_stats()

        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

        if added_count > 0:
            self.msgbox.show_info(f"成功添加 {added_count} 个任务\n跳过 {failed_count} 个无效链接", "完成")

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
        for line in clipboard_content.split('\n'):
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            url = parts[0].strip()

            if url.startswith(('http://', 'https://')):
                name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                valid_tasks.append((url, name))

        if not valid_tasks:
            self.msgbox.show_warning("剪贴板中没有有效的下载链接\n\n格式: 链接|文件名", "提示")
            return

        max_workers = self.thread_var.get()
        for url, name in valid_tasks:
            task = self._create_task(url, name, output_dir, max_workers)
            self._insert_task_to_tree(task)

        self._log(f"粘贴添加: {len(valid_tasks)} 个任务")
        self._update_stats()

        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

        self.msgbox.show_info(f"成功添加 {len(valid_tasks)} 个任务", "完成")

    def _start_selected(self):
        """开始选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        startable_tasks = [
            self.tasks[int(task_id)]
            for task_id in selection
            if self.tasks.get(int(task_id)) and self.tasks[int(task_id)].status in ["等待中", "已暂停", "已失败", "已取消"]
        ]

        if not startable_tasks:
            return

        available_slots = self.max_concurrent - self.active_downloads
        if available_slots <= 0:
            self.msgbox.show_warning(f"已达到最大并发数 {self.max_concurrent}", "提示")
            return

        started = 0
        for task in startable_tasks:
            if self.active_downloads >= self.max_concurrent:
                break
            self._start_task(task)
            started += 1

        if started > 0:
            self._log(f"开始下载: {started} 个任务")

    def _start_all(self):
        """开始所有等待中的任务"""
        startable_tasks = [
            task for task in self.tasks.values()
            if task.status in ["等待中", "已暂停", "已失败", "已取消"]
        ]

        if not startable_tasks:
            self.msgbox.show_info("没有等待中的任务", "提示")
            return

        available_slots = self.max_concurrent - self.active_downloads
        if available_slots <= 0:
            self.msgbox.show_warning(f"已达到最大并发数 {self.max_concurrent}", "提示")
            return

        started = 0
        for task in startable_tasks:
            if self.active_downloads >= self.max_concurrent:
                break
            self._start_task(task)
            started += 1

        self._log(f"全部开始: {started} 个任务")

    def _start_task(self, task: DownloadTask):
        """启动单个任务"""
        task.status = "下载中"
        task._stop_flag.clear()
        self._update_task_display(task)

        task.thread = threading.Thread(
            target=self._download_thread,
            args=(task,),
            daemon=True
        )
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
                task.output_dir
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

            task.downloader.download(auto_cleanup=True)

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
            task = self.tasks.get(int(task_id))
            if task and task.status != "下载中":
                del self.tasks[int(task_id)]
                self.task_tree.delete(int(task_id))
                removed += 1

        if removed > 0:
            self._log(f"删除: {removed} 个任务")
            self._update_stats()

    def _clear_completed(self):
        """清除已完成的任务"""
        completed_ids = [
            task_id for task_id, task in self.tasks.items()
            if task.status in ["已完成", "已失败", "已取消"]
        ]

        for task_id in completed_ids:
            del self.tasks[task_id]
            self.task_tree.delete(task_id)

        if completed_ids:
            self._log(f"清除: {len(completed_ids)} 个任务")
            self._update_stats()

    def _retry_failed(self):
        """重试失败的任务"""
        failed_tasks = [
            task for task in self.tasks.values()
            if task.status in ["已失败", "已取消"]
        ]

        if not failed_tasks:
            self.msgbox.show_info("没有失败的任务需要重试", "提示")
            return

        available_slots = self.max_concurrent - self.active_downloads
        if available_slots <= 0:
            self.msgbox.show_warning(f"已达到最大并发数 {self.max_concurrent}", "提示")
            return

        started = 0
        for task in failed_tasks:
            if self.active_downloads >= self.max_concurrent:
                break

            task.status = "等待中"
            task.progress = 0
            task.downloaded = 0
            task.total = 0
            task.message = ""
            task._stop_flag.clear()

            self._update_task_display(task)
            self._start_task(task)
            started += 1

        self._log(f"重试: {started} 个任务")

    def _update_task_display(self, task: DownloadTask):
        """更新任务显示"""
        if task.task_id in self.tasks:
            speed_str = task.message if task.message else "-"
            progress_str = f"{task.progress:.1f}%" if task.total > 0 else f"{task.downloaded}"

            self.task_tree.item(task.task_id, values=(
                task.task_id,
                f"{task.output_name}.mp4",
                task.status,
                progress_str,
                speed_str
            ))

    def _update_status(self):
        """更新状态栏"""
        self.status_label.config(
            text=f"活动下载: {self.active_downloads} | 最大并发: {self.max_concurrent}"
        )

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
                        self._log(f"失败: {task.output_name}.mp4 - {msg[2][:30]}")
                        self._update_stats()

                elif msg_type == 'finish':
                    self._update_status()
                    self._start_waiting_tasks()

        except Exception:
            pass

        self.root.after(100, self._process_messages)

    def _open_settings(self):
        """打开设置窗口"""
        settings_window = ttk.Toplevel(self.root)
        settings_window.withdraw()
        settings_window.title("设置")
        settings_window.geometry("380x300")
        settings_window.resizable(False, False)

        self._set_window_icon(settings_window)

        settings_window.transient(self.root)
        settings_window.grab_set()

        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 380) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 300) // 2
        settings_window.geometry(f"+{x}+{y}")

        frame = ttk.Frame(settings_window, padding=24)
        frame.pack(fill=BOTH, expand=YES)

        row1 = ttk.Frame(frame)
        row1.pack(fill=X, pady=10)
        ttk.Label(row1, text="最大并发下载数", width=16).pack(side=LEFT)
        max_concurrent_var = ttk.IntVar(value=self.max_concurrent)
        ttk.Spinbox(row1, from_=1, to=10, textvariable=max_concurrent_var, width=8).pack(side=RIGHT)

        row2 = ttk.Frame(frame)
        row2.pack(fill=X, pady=10)
        ttk.Label(row2, text="默认下载线程", width=16).pack(side=LEFT)
        default_workers_var = ttk.IntVar(value=self.config_manager.get('max_workers', 16))
        ttk.Spinbox(row2, from_=1, to=64, textvariable=default_workers_var, width=8).pack(side=RIGHT)

        auto_cleanup_var = ttk.BooleanVar(value=self.config_manager.get('auto_cleanup', True))
        ttk.Checkbutton(frame, text="自动清理临时文件", variable=auto_cleanup_var).pack(anchor=W, pady=16)

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

        ttk.Button(frame, text="保存", command=save_settings, bootstyle='primary', width=12).pack(pady=20)

        settings_window.deiconify()

    def on_closing(self):
        """窗口关闭事件"""
        geometry = self.root.geometry()
        self.config_manager.set('window_geometry', geometry)

        downloading = [task for task in self.tasks.values() if task.status == "下载中"]
        if downloading:
            if self.msgbox.yesno(f"还有 {len(downloading)} 个任务正在下载，确定要退出吗？", "确认退出"):
                self.root.destroy()
        else:
            self.root.destroy()


def main():
    """主函数"""
    root = ttk.Window(themename="cosmo")
    app = M3U8DownloaderGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()