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
from typing import Dict, List
from queue import Queue
from m3u8_downloader import M3U8Downloader
from config_manager import ConfigManager


class MsgBox:
    """自定义消息框，支持设置图标"""

    def __init__(self, parent):
        self.parent = parent
        self._icon_path = self._get_icon_path()

    def _get_icon_path(self):
        """获取图标路径"""
        try:
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, 'icon.ico')
            else:
                icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
            if os.path.exists(icon_path):
                return icon_path
        except:
            pass
        return None

    def _show(self, title, message, icon='info'):
        """显示消息框"""
        # 根据消息长度计算窗口高度
        lines = message.count('\n') + 1
        height = max(140, 120 + lines * 20)

        dialog = ttk.Toplevel(self.parent)
        dialog.withdraw()  # 先隐藏窗口
        dialog.title(title)
        dialog.geometry(f"380x{height}")
        dialog.resizable(False, False)
        dialog.transient(self.parent)
        dialog.grab_set()

        # 设置图标
        if self._icon_path:
            try:
                dialog.iconbitmap(self._icon_path)
            except:
                pass

        # 居中
        self.parent.update_idletasks()
        x = self.parent.winfo_x() + (self.parent.winfo_width() - 380) // 2
        y = self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2
        dialog.geometry(f"+{x}+{y}")

        # 内容
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=YES)

        # 图标和消息
        msg_frame = ttk.Frame(frame)
        msg_frame.pack(fill=BOTH, expand=YES)

        icon_map = {
            'info': 'ℹ',
            'warning': '⚠',
            'error': '✗',
            'question': '?'
        }
        icon_char = icon_map.get(icon, 'ℹ')

        bootstyle_map = {
            'info': 'info',
            'warning': 'warning',
            'error': 'danger',
            'question': 'primary'
        }
        bootstyle = bootstyle_map.get(icon, 'info')

        ttk.Label(msg_frame, text=icon_char, font=('Segoe UI', 24), bootstyle=bootstyle).pack(side=LEFT, padx=(0, 15))
        ttk.Label(msg_frame, text=message, font=('Segoe UI', 10), wraplength=280).pack(side=LEFT, fill=X, expand=YES)

        # 按钮
        ttk.Button(frame, text="确定", command=dialog.destroy, bootstyle='primary', width=10).pack(pady=15)

        dialog.deiconify()  # 显示窗口
        dialog.wait_window()

    def _ask(self, title, message):
        """显示询问框"""
        # 根据消息长度计算窗口高度
        lines = message.count('\n') + 1
        height = max(140, 120 + lines * 20)

        result = [False]
        dialog = ttk.Toplevel(self.parent)
        dialog.withdraw()  # 先隐藏窗口
        dialog.title(title)
        dialog.geometry(f"380x{height}")
        dialog.resizable(False, False)
        dialog.transient(self.parent)
        dialog.grab_set()

        # 设置图标
        if self._icon_path:
            try:
                dialog.iconbitmap(self._icon_path)
            except:
                pass

        # 居中
        self.parent.update_idletasks()
        x = self.parent.winfo_x() + (self.parent.winfo_width() - 380) // 2
        y = self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2
        dialog.geometry(f"+{x}+{y}")

        # 内容
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill=BOTH, expand=YES)

        # 图标和消息
        msg_frame = ttk.Frame(frame)
        msg_frame.pack(fill=BOTH, expand=YES)

        ttk.Label(msg_frame, text='?', font=('Segoe UI', 24), bootstyle='primary').pack(side=LEFT, padx=(0, 15))
        ttk.Label(msg_frame, text=message, font=('Segoe UI', 10), wraplength=280).pack(side=LEFT, fill=X, expand=YES)

        # 按钮
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=15)

        def on_yes():
            result[0] = True
            dialog.destroy()

        def on_no():
            dialog.destroy()

        ttk.Button(btn_frame, text="是", command=on_yes, bootstyle='primary', width=8).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="否", command=on_no, width=8).pack(side=LEFT, padx=5)

        dialog.deiconify()  # 显示窗口
        dialog.wait_window()
        return result[0]

    def show_info(self, message, title="提示"):
        self._show(title, message, 'info')

    def show_warning(self, message, title="警告"):
        self._show(title, message, 'warning')

    def show_error(self, message, title="错误"):
        self._show(title, message, 'error')

    def yesno(self, message, title="确认"):
        return self._ask(title, message)


class DownloadTask:
    """下载任务"""

    def __init__(self, task_id: int, url: str, output_name: str, output_dir: str, max_workers: int):
        self.task_id = task_id
        self.url = url
        self.output_name = output_name
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.status = "等待中"
        self.progress = 0
        self.downloaded = 0
        self.total = 0
        self.message = ""
        self.downloader = None
        self.thread = None
        self._stop_flag = threading.Event()


class M3U8DownloaderGUI:
    """M3U8 下载器图形界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("M3U8 视频下载器")

        # 设置窗口图标
        self.set_icon()

        # 加载配置
        self.config_manager = ConfigManager()
        config = self.config_manager.config

        # 设置窗口大小
        geometry = config.get('window_geometry', '1000x680')
        self.root.geometry(geometry)
        self.root.minsize(800, 550)

        # 任务管理
        self.tasks: Dict[int, DownloadTask] = {}
        self.task_counter = 0
        self.max_concurrent = config.get('max_concurrent_downloads', 3)
        self.active_downloads = 0
        self._lock = threading.Lock()

        # 消息队列
        self.message_queue = Queue()

        # 日志最大行数
        self.max_log_lines = 500

        # 自定义消息框
        self.msgbox = MsgBox(root)

        # 创建界面
        self.create_widgets()

        # 绑定快捷键
        self.bind_shortcuts()

        # 启动消息处理
        self.process_messages()

    def create_widgets(self):
        """创建所有界面组件"""

        # 主容器
        main_frame = ttk.Frame(self.root, padding=16)
        main_frame.pack(fill=BOTH, expand=YES)

        # === 顶部标题栏 ===
        self._create_header(main_frame)

        # === 输入区域 ===
        self._create_input_section(main_frame)

        # === 任务列表 ===
        self._create_task_section(main_frame)

        # === 底部状态栏 ===
        self._create_status_bar(main_frame)

    def _create_header(self, parent):
        """创建标题栏"""
        header = ttk.Frame(parent)
        header.pack(fill=X, pady=(0, 12))

        # 左侧标题
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
            text="v3.0",
            font=('Segoe UI', 9),
            bootstyle='secondary'
        ).pack(side=LEFT, padx=(6, 0), pady=(7, 0))

        # 右侧设置按钮
        ttk.Button(
            header,
            text="设置",
            command=self.open_settings,
            width=8
        ).pack(side=RIGHT)

    def _create_input_section(self, parent):
        """创建输入区域"""
        input_card = ttk.Labelframe(parent, text="添加任务", padding=12)
        input_card.pack(fill=X, pady=(0, 12))

        notebook = ttk.Notebook(input_card)
        notebook.pack(fill=X, expand=YES)

        # 单个任务页
        single_frame = ttk.Frame(notebook, padding=12)
        notebook.add(single_frame, text="单个任务")

        # 第一行：URL
        row1 = ttk.Frame(single_frame)
        row1.pack(fill=X, pady=(0, 8))

        ttk.Label(row1, text="链接", width=6).pack(side=LEFT)
        self.url_entry = ttk.Entry(row1)
        self.url_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 8))
        self.url_entry.bind('<Control-v>', lambda e: self.paste_from_clipboard())

        paste_btn = ttk.Button(row1, text="粘贴", command=self.paste_from_clipboard, width=6)
        paste_btn.pack(side=LEFT)
        ToolTip(paste_btn, text="从剪贴板粘贴 (Ctrl+V)")

        # 第二行：路径 + 文件名 + 线程
        row2 = ttk.Frame(single_frame)
        row2.pack(fill=X, pady=(0, 10))

        ttk.Label(row2, text="路径", width=6).pack(side=LEFT)
        self.path_entry = ttk.Entry(row2)
        self.path_entry.pack(side=LEFT, fill=X, expand=YES, padx=(4, 8))
        self.path_entry.insert(0, self.config_manager.get('download_path', os.getcwd()))

        browse_btn = ttk.Button(row2, text="...", command=self.browse_path, width=3)
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

        # 第三行：按钮
        row3 = ttk.Frame(single_frame)
        row3.pack(fill=X)

        ttk.Button(
            row3, text="粘贴添加", command=self.paste_and_add, width=10
        ).pack(side=LEFT, padx=(0, 6))

        ttk.Label(row3, text="").pack(side=LEFT, fill=X, expand=YES)  # 弹性空间

        ttk.Button(
            row3, text="添加任务", command=self.add_task, bootstyle='primary', width=10
        ).pack(side=RIGHT)

        # 批量添加页
        batch_frame = ttk.Frame(notebook, padding=12)
        notebook.add(batch_frame, text="批量添加")

        ttk.Label(
            batch_frame, text="每行一个任务，格式: 链接|文件名 (文件名可选)", bootstyle='secondary'
        ).pack(anchor=W, pady=(0, 6))

        self.batch_text = ScrolledText(batch_frame, height=4, autohide=True)
        self.batch_text.pack(fill=X, expand=YES, pady=(0, 8))

        batch_btn_row = ttk.Frame(batch_frame)
        batch_btn_row.pack(fill=X)

        ttk.Label(
            batch_btn_row, text=f"保存至: {self.path_entry.get()}", bootstyle='secondary'
        ).pack(side=LEFT)

        ttk.Button(
            batch_btn_row, text="批量添加", command=self.batch_add_tasks, bootstyle='primary', width=12
        ).pack(side=RIGHT)

    def _create_task_section(self, parent):
        """创建任务列表区域"""
        task_card = ttk.Labelframe(parent, text="下载任务", padding=12)
        task_card.pack(fill=BOTH, expand=YES, pady=(0, 12))

        # 工具栏
        toolbar = ttk.Frame(task_card)
        toolbar.pack(fill=X, pady=(0, 8))

        # 左侧按钮组
        left_btns = ttk.Frame(toolbar)
        left_btns.pack(side=LEFT)

        start_btn = ttk.Button(left_btns, text="开始", command=self.start_selected, width=6)
        start_btn.pack(side=LEFT, padx=(0, 4))
        ToolTip(start_btn, text="开始选中的任务")

        start_all_btn = ttk.Button(left_btns, text="全部开始", command=self.start_all, width=8)
        start_all_btn.pack(side=LEFT, padx=4)
        ToolTip(start_all_btn, text="开始所有等待中的任务")

        ttk.Separator(left_btns, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        cancel_btn = ttk.Button(left_btns, text="取消", command=self.pause_selected, width=6)
        cancel_btn.pack(side=LEFT, padx=4)
        ToolTip(cancel_btn, text="取消选中的下载任务")

        retry_btn = ttk.Button(left_btns, text="重试", command=self.retry_failed, width=6)
        retry_btn.pack(side=LEFT, padx=4)
        ToolTip(retry_btn, text="重试失败的任务")

        ttk.Separator(left_btns, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=8)

        remove_btn = ttk.Button(left_btns, text="删除", command=self.remove_selected, width=6)
        remove_btn.pack(side=LEFT, padx=4)
        ToolTip(remove_btn, text="删除选中的任务")

        clear_btn = ttk.Button(left_btns, text="清除", command=self.clear_completed, width=6)
        clear_btn.pack(side=LEFT, padx=4)
        ToolTip(clear_btn, text="清除已完成/失败的任务")

        # 右侧统计
        self.stats_label = ttk.Label(toolbar, text="", bootstyle='secondary')
        self.stats_label.pack(side=RIGHT)
        self.update_stats()

        # 任务列表
        columns = ('id', 'filename', 'status', 'progress', 'speed')
        self.task_tree = ttk.Treeview(
            task_card,
            columns=columns,
            show='headings',
            height=8,
            bootstyle='info',
            selectmode='extended'
        )

        # 设置列
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

        # 滚动条
        scrollbar = ttk.Scrollbar(task_card, orient=VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=scrollbar.set)

        self.task_tree.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

        # 绑定双击事件
        self.task_tree.bind('<Double-1>', self._on_task_double_click)
        self.task_tree.bind('<Delete>', lambda e: self.remove_selected())
        self.task_tree.bind('<Return>', lambda e: self.start_selected())

        # 右键菜单
        self._create_context_menu()

    def _create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = ttk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="开始", command=self.start_selected)
        self.context_menu.add_command(label="取消", command=self.pause_selected)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="重试", command=self.retry_failed)
        self.context_menu.add_command(label="删除", command=self.remove_selected)
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
                    self.start_selected()
                elif task.status == "下载中":
                    self.pause_selected()

    def _copy_task_url(self):
        """复制任务链接"""
        selection = self.task_tree.selection()
        if selection:
            task_id = int(selection[0])
            task = self.tasks.get(task_id)
            if task:
                self.root.clipboard_clear()
                self.root.clipboard_append(task.url)
                self.log(f"已复制链接: {task.url[:50]}...")

    def _open_task_folder(self):
        """打开任务目录"""
        selection = self.task_tree.selection()
        if selection:
            task_id = int(selection[0])
            task = self.tasks.get(task_id)
            if task and os.path.exists(task.output_dir):
                os.startfile(task.output_dir)

    def _create_status_bar(self, parent):
        """创建底部区域"""
        bottom_frame = ttk.Frame(parent)
        bottom_frame.pack(fill=BOTH, expand=YES)

        # 日志区域 - 可拉伸
        log_frame = ttk.Labelframe(bottom_frame, text="日志", padding=8)
        log_frame.pack(fill=BOTH, expand=YES, pady=(0, 8))

        self.log_text = ScrolledText(log_frame, height=4, autohide=True)
        self.log_text.pack(fill=BOTH, expand=YES)

        # 状态栏
        self.status_label = ttk.Label(
            bottom_frame,
            text="就绪",
            bootstyle='secondary',
            font=('Segoe UI', 9)
        )
        self.status_label.pack(anchor=W)

    def bind_shortcuts(self):
        """绑定快捷键"""
        self.root.bind('<Control-v>', lambda e: self.paste_from_clipboard())
        self.root.bind('<Control-Return>', lambda e: self.add_task())
        self.root.bind('<F5>', lambda e: self.start_all())
        self.root.bind('<Escape>', lambda e: self.pause_selected())

    def update_stats(self):
        """更新统计信息"""
        total = len(self.tasks)
        waiting = sum(1 for t in self.tasks.values() if t.status == "等待中")
        downloading = sum(1 for t in self.tasks.values() if t.status == "下载中")
        completed = sum(1 for t in self.tasks.values() if t.status == "已完成")
        failed = sum(1 for t in self.tasks.values() if t.status == "已失败")

        self.stats_label.config(
            text=f"共 {total} 个任务 | 下载中: {downloading} | 等待: {waiting} | 完成: {completed} | 失败: {failed}"
        )

    def set_icon(self):
        """设置窗口图标"""
        self._set_window_icon(self.root)

    def browse_path(self):
        """浏览下载路径"""
        from tkinter import filedialog
        path = filedialog.askdirectory(title="选择下载目录")
        if path:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, path)
            self.config_manager.set('download_path', path)

    def paste_from_clipboard(self):
        """从剪贴板粘贴URL"""
        try:
            clipboard_content = self.root.clipboard_get()
            if clipboard_content:
                self.url_entry.delete(0, 'end')
                self.url_entry.insert(0, clipboard_content.strip())
                self.output_entry.focus()  # 自动跳到文件名输入框
        except:
            pass

    def log(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert('end', f"[{timestamp}] {message}\n")
        self.log_text.see('end')

        # 限制日志行数
        line_count = int(self.log_text.index('end-1c').split('.')[0])
        if line_count > self.max_log_lines:
            self.log_text.delete('1.0', f'{line_count - self.max_log_lines}.0')

    def add_task(self):
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

        if not output_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"video_{timestamp}"

        try:
            output_name.encode('utf-8')
        except UnicodeEncodeError:
            output_name = output_name.encode('utf-8', errors='ignore').decode('utf-8')

        self.task_counter += 1
        task = DownloadTask(
            task_id=self.task_counter,
            url=m3u8_url,
            output_name=output_name,
            output_dir=output_dir,
            max_workers=max_workers
        )

        self.tasks[task.task_id] = task

        self.task_tree.insert('', 'end', iid=task.task_id, values=(
            task.task_id,
            f"{output_name}.mp4",
            task.status,
            "0%",
            "-"
        ))

        self.log(f"添加: {output_name}.mp4")
        self.update_stats()

        # 清空输入，准备下一个
        self.url_entry.delete(0, 'end')
        self.output_entry.delete(0, 'end')
        self.url_entry.focus()

        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

    def batch_add_tasks(self):
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

        lines = batch_text.split('\n')
        added_count = 0
        failed_count = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            m3u8_url = parts[0].strip()

            if not m3u8_url or not (m3u8_url.startswith('http://') or m3u8_url.startswith('https://')):
                failed_count += 1
                continue

            if len(parts) > 1 and parts[1].strip():
                output_name = parts[1].strip()
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_name = f"video_{timestamp}_{added_count}"

            try:
                output_name.encode('utf-8')
            except UnicodeEncodeError:
                output_name = output_name.encode('utf-8', errors='ignore').decode('utf-8')

            self.task_counter += 1
            task = DownloadTask(
                task_id=self.task_counter,
                url=m3u8_url,
                output_name=output_name,
                output_dir=output_dir,
                max_workers=max_workers
            )

            self.tasks[task.task_id] = task

            self.task_tree.insert('', 'end', iid=task.task_id, values=(
                task.task_id,
                f"{output_name}.mp4",
                task.status,
                "0%",
                "-"
            ))

            added_count += 1

        self.batch_text.delete("1.0", 'end')
        self.log(f"批量添加: {added_count} 个任务")
        self.update_stats()

        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

        if added_count > 0:
            self.msgbox.show_info(f"成功添加 {added_count} 个任务\n跳过 {failed_count} 个无效链接", "完成")

    def paste_and_add(self):
        """从剪贴板读取并添加任务"""
        try:
            clipboard_content = self.root.clipboard_get().strip()
        except:
            self.msgbox.show_warning("剪贴板为空", "提示")
            return

        if not clipboard_content:
            self.msgbox.show_warning("剪贴板为空", "提示")
            return

        output_dir = self.path_entry.get().strip()
        if not output_dir:
            self.msgbox.show_error("请选择下载路径", "错误")
            return

        lines = clipboard_content.split('\n')
        valid_tasks = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split('|')
            url = parts[0].strip()

            if url.startswith('http://') or url.startswith('https://'):
                name = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
                valid_tasks.append((url, name))

        if not valid_tasks:
            self.msgbox.show_warning("剪贴板中没有有效的下载链接\n\n格式: 链接|文件名", "提示")
            return

        added_count = 0
        max_workers = self.thread_var.get()

        for url, name in valid_tasks:
            if not name:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                name = f"video_{timestamp}_{added_count}"

            try:
                name.encode('utf-8')
            except UnicodeEncodeError:
                name = name.encode('utf-8', errors='ignore').decode('utf-8')

            self.task_counter += 1
            task = DownloadTask(
                task_id=self.task_counter,
                url=url,
                output_name=name,
                output_dir=output_dir,
                max_workers=max_workers
            )

            self.tasks[task.task_id] = task

            self.task_tree.insert('', 'end', iid=task.task_id, values=(
                task.task_id,
                f"{name}.mp4",
                task.status,
                "0%",
                "-"
            ))

            added_count += 1

        self.log(f"粘贴添加: {added_count} 个任务")
        self.update_stats()

        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

        self.msgbox.show_info(f"成功添加 {added_count} 个任务", "完成")

    def start_selected(self):
        """开始选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        startable_tasks = []
        for task_id in selection:
            task_id = int(task_id)
            task = self.tasks.get(task_id)
            if task and task.status in ["等待中", "已暂停", "已失败", "已取消"]:
                startable_tasks.append(task)

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
            self._start_task_internal(task)
            started += 1

        if started > 0:
            self.log(f"开始下载: {started} 个任务")

    def start_all(self):
        """开始所有等待中的任务"""
        startable_tasks = [task for task in self.tasks.values()
                          if task.status in ["等待中", "已暂停", "已失败", "已取消"]]

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
            self._start_task_internal(task)
            started += 1

        self.log(f"全部开始: {started} 个任务")

    def _start_task_internal(self, task: DownloadTask):
        """内部方法：启动单个任务"""
        task.status = "下载中"
        task._stop_flag.clear()
        self.update_task_display(task)

        task.thread = threading.Thread(
            target=self.download_thread,
            args=(task,),
            daemon=True
        )
        task.thread.start()

        with self._lock:
            self.active_downloads += 1
        self.update_status()
        self.update_stats()

    def download_thread(self, task: DownloadTask):
        """下载线程"""
        try:
            task.downloader = M3U8Downloader(
                task.url,
                task.output_name,
                task.max_workers,
                task.output_dir
            )

            def progress_callback(current, total, message):
                if task._stop_flag.is_set():
                    if task.downloader:
                        task.downloader._stop_flag = True
                    return

                task.downloaded = current
                task.total = total
                if total > 0:
                    task.progress = (current / total) * 100
                task.message = message
                self.message_queue.put(('progress', task.task_id))

            task.downloader.progress_callback = progress_callback

            import builtins
            original_print = print

            def task_print(*args, **kwargs):
                msg = ' '.join(str(arg) for arg in args)
                self.message_queue.put(('log', f"#{task.task_id} {msg}"))

            builtins.print = task_print

            try:
                task.downloader.download(auto_cleanup=True)
                if task._stop_flag.is_set():
                    task.status = "已取消"
                    self.message_queue.put(('cancelled', task.task_id))
                else:
                    task.status = "已完成"
                    self.message_queue.put(('complete', task.task_id))
            finally:
                builtins.print = original_print

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

    def pause_selected(self):
        """取消选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        cancelled_count = 0
        for task_id in selection:
            task_id = int(task_id)
            task = self.tasks.get(task_id)
            if task and task.status == "下载中":
                task._stop_flag.set()
                if task.downloader:
                    task.downloader._stop_flag = True
                task.status = "取消中"
                self.update_task_display(task)
                cancelled_count += 1

        if cancelled_count > 0:
            self.log(f"取消: {cancelled_count} 个任务")

    def remove_selected(self):
        """删除选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            self.msgbox.show_warning("请先选择任务", "提示")
            return

        removed = 0
        for task_id in selection:
            task_id = int(task_id)
            task = self.tasks.get(task_id)
            if task and task.status not in ["下载中"]:
                del self.tasks[task_id]
                self.task_tree.delete(task_id)
                removed += 1

        if removed > 0:
            self.log(f"删除: {removed} 个任务")
            self.update_stats()

    def clear_completed(self):
        """清除已完成的任务"""
        completed_ids = [
            task_id for task_id, task in self.tasks.items()
            if task.status in ["已完成", "已失败", "已取消"]
        ]

        for task_id in completed_ids:
            del self.tasks[task_id]
            self.task_tree.delete(task_id)

        if completed_ids:
            self.log(f"清除: {len(completed_ids)} 个任务")
            self.update_stats()

    def retry_failed(self):
        """重试失败的任务"""
        failed_tasks = [task for task in self.tasks.values()
                       if task.status in ["已失败", "已取消"]]

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

            self.update_task_display(task)
            self._start_task_internal(task)
            started += 1

        self.log(f"重试: {started} 个任务")

    def update_task_display(self, task: DownloadTask):
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

    def update_status(self):
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
                self._start_task_internal(task)

    def process_messages(self):
        """处理消息队列"""
        try:
            while True:
                msg = self.message_queue.get_nowait()
                msg_type = msg[0]

                if msg_type == 'progress':
                    task_id = msg[1]
                    task = self.tasks.get(task_id)
                    if task:
                        self.update_task_display(task)

                elif msg_type == 'complete':
                    task_id = msg[1]
                    task = self.tasks.get(task_id)
                    if task:
                        self.update_task_display(task)
                        self.log(f"完成: {task.output_name}.mp4")
                        self.update_stats()

                elif msg_type == 'cancelled':
                    task_id = msg[1]
                    task = self.tasks.get(task_id)
                    if task:
                        self.update_task_display(task)
                        self.log(f"已取消: {task.output_name}.mp4")
                        self.update_stats()

                elif msg_type == 'error':
                    task_id, error = msg[1], msg[2]
                    task = self.tasks.get(task_id)
                    if task:
                        self.update_task_display(task)
                        self.log(f"失败: {task.output_name}.mp4 - {error[:30]}")
                        self.update_stats()

                elif msg_type == 'finish':
                    self.update_status()
                    self._start_waiting_tasks()

                elif msg_type == 'log':
                    self.log(msg[1])

        except:
            pass

        self.root.after(100, self.process_messages)

    def open_settings(self):
        """打开设置窗口"""
        settings_window = ttk.Toplevel(self.root)
        settings_window.withdraw()  # 先隐藏窗口
        settings_window.title("设置")
        settings_window.geometry("380x300")
        settings_window.resizable(False, False)

        # 设置图标
        self._set_window_icon(settings_window)

        # 居中显示
        settings_window.transient(self.root)
        settings_window.grab_set()

        # 计算居中位置
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 380) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 300) // 2
        settings_window.geometry(f"+{x}+{y}")

        frame = ttk.Frame(settings_window, padding=24)
        frame.pack(fill=BOTH, expand=YES)

        # 最大并发下载
        row1 = ttk.Frame(frame)
        row1.pack(fill=X, pady=10)
        ttk.Label(row1, text="最大并发下载数", width=16).pack(side=LEFT)
        max_concurrent_var = ttk.IntVar(value=self.max_concurrent)
        ttk.Spinbox(row1, from_=1, to=10, textvariable=max_concurrent_var, width=8).pack(side=RIGHT)

        # 默认并发线程
        row2 = ttk.Frame(frame)
        row2.pack(fill=X, pady=10)
        ttk.Label(row2, text="默认下载线程", width=16).pack(side=LEFT)
        default_workers_var = ttk.IntVar(value=self.config_manager.get('max_workers', 16))
        ttk.Spinbox(row2, from_=1, to=64, textvariable=default_workers_var, width=8).pack(side=RIGHT)

        # 自动清理
        auto_cleanup_var = ttk.BooleanVar(value=self.config_manager.get('auto_cleanup', True))
        ttk.Checkbutton(frame, text="自动清理临时文件", variable=auto_cleanup_var).pack(anchor=W, pady=16)

        def save_settings():
            self.max_concurrent = max_concurrent_var.get()
            self.config_manager.update({
                'max_concurrent_downloads': max_concurrent_var.get(),
                'max_workers': default_workers_var.get(),
                'auto_cleanup': auto_cleanup_var.get()
            })
            self.update_status()
            settings_window.destroy()
            self.msgbox.show_info("设置已保存", "成功")

        ttk.Button(frame, text="保存", command=save_settings, bootstyle='primary', width=12).pack(pady=20)

        settings_window.deiconify()  # 显示窗口

    def _set_window_icon(self, window):
        """设置窗口图标"""
        try:
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, 'icon.ico')
            else:
                icon_path = os.path.join(os.path.dirname(__file__), 'icon.ico')

            if os.path.exists(icon_path):
                window.iconbitmap(icon_path)
        except Exception:
            pass

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
