#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8 视频下载器 - GUI 版本
支持多任务并行下载
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import threading
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from queue import Queue
from m3u8_downloader import M3U8Downloader
from config_manager import ConfigManager
from chinese_converter import traditional_to_simplified, is_traditional


class DownloadTask:
    """下载任务"""

    def __init__(self, task_id: int, url: str, output_name: str, output_dir: str, max_workers: int):
        self.task_id = task_id
        self.url = url
        self.output_name = output_name
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.status = "等待中"  # 等待中, 下载中, 已完成, 已失败, 已取消
        self.progress = 0
        self.downloaded = 0
        self.total = 0
        self.message = ""
        self.downloader = None
        self.thread = None


class M3U8DownloaderGUI:
    """M3U8 下载器图形界面"""

    def __init__(self, root):
        self.root = root
        self.root.title("M3U8 视频下载器 v3.0 - 多任务版")

        # 加载配置
        self.config_manager = ConfigManager()
        config = self.config_manager.config

        # 设置窗口大小
        geometry = config.get('window_geometry', '900x700')
        self.root.geometry(geometry)
        self.root.resizable(True, True)

        # 任务管理
        self.tasks: Dict[int, DownloadTask] = {}
        self.task_counter = 0
        self.max_concurrent = config.get('max_concurrent_downloads', 3)
        self.active_downloads = 0

        # 消息队列（用于线程间通信）
        self.message_queue = Queue()

        # 创建界面
        self.create_widgets()

        # 启动消息处理
        self.process_messages()

    def create_widgets(self):
        """创建所有界面组件"""

        # 主容器
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        # === 输入区域 ===
        input_frame = ttk.LabelFrame(main_frame, text="添加下载任务", padding="10")
        input_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        input_frame.columnconfigure(1, weight=1)

        # M3U8 URL
        ttk.Label(input_frame, text="M3U8 链接:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.url_entry = ttk.Entry(input_frame, width=80)
        self.url_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 0))

        # 下载路径
        ttk.Label(input_frame, text="下载路径:").grid(row=1, column=0, sticky=tk.W, pady=5)
        path_frame = ttk.Frame(input_frame)
        path_frame.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 0))
        path_frame.columnconfigure(0, weight=1)

        self.path_entry = ttk.Entry(path_frame)
        self.path_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        # 从配置加载路径
        self.path_entry.insert(0, self.config_manager.get('download_path', os.getcwd()))

        self.path_btn = ttk.Button(path_frame, text="浏览...", command=self.browse_path, width=10)
        self.path_btn.grid(row=0, column=1)

        # 输出文件名和并发线程
        ttk.Label(input_frame, text="输出文件名:").grid(row=2, column=0, sticky=tk.W, pady=5)
        output_frame = ttk.Frame(input_frame)
        output_frame.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 0))
        output_frame.columnconfigure(0, weight=1)

        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))

        ttk.Label(output_frame, text="(留空自动生成)", foreground="gray").grid(row=0, column=1, padx=(5, 10))

        ttk.Label(output_frame, text="并发线程:").grid(row=0, column=2, padx=(0, 5))
        self.thread_var = tk.IntVar(value=self.config_manager.get('max_workers', 16))
        thread_spinbox = ttk.Spinbox(output_frame, from_=1, to=64, textvariable=self.thread_var, width=8)
        thread_spinbox.grid(row=0, column=3)

        # 添加任务按钮
        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=10)

        self.add_btn = ttk.Button(button_frame, text="添加到下载列表", command=self.add_task, width=20)
        self.add_btn.grid(row=0, column=0, padx=5)

        self.settings_btn = ttk.Button(button_frame, text="设置", command=self.open_settings, width=10)
        self.settings_btn.grid(row=0, column=1, padx=5)

        # === 任务列表区域 ===
        task_frame = ttk.LabelFrame(main_frame, text="下载任务列表", padding="10")
        task_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        task_frame.columnconfigure(0, weight=1)
        task_frame.rowconfigure(0, weight=1)

        # 任务列表 Treeview
        columns = ('ID', '文件名', '状态', '进度', '已下载', '总数', '速度')
        self.task_tree = ttk.Treeview(task_frame, columns=columns, show='headings', height=10)

        # 设置列标题和宽度
        self.task_tree.heading('ID', text='ID')
        self.task_tree.heading('文件名', text='文件名')
        self.task_tree.heading('状态', text='状态')
        self.task_tree.heading('进度', text='进度')
        self.task_tree.heading('已下载', text='已下载')
        self.task_tree.heading('总数', text='总数')
        self.task_tree.heading('速度', text='速度')

        self.task_tree.column('ID', width=50, anchor='center')
        self.task_tree.column('文件名', width=200)
        self.task_tree.column('状态', width=100, anchor='center')
        self.task_tree.column('进度', width=100, anchor='center')
        self.task_tree.column('已下载', width=80, anchor='center')
        self.task_tree.column('总数', width=80, anchor='center')
        self.task_tree.column('速度', width=120, anchor='center')

        # 添加滚动条
        scrollbar = ttk.Scrollbar(task_frame, orient=tk.VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=scrollbar.set)

        self.task_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))

        # 任务控制按钮
        task_button_frame = ttk.Frame(task_frame)
        task_button_frame.grid(row=1, column=0, columnspan=2, pady=10)

        self.start_selected_btn = ttk.Button(task_button_frame, text="开始选中", command=self.start_selected, width=12)
        self.start_selected_btn.grid(row=0, column=0, padx=5)

        self.start_all_btn = ttk.Button(task_button_frame, text="全部开始", command=self.start_all, width=12)
        self.start_all_btn.grid(row=0, column=1, padx=5)

        self.pause_btn = ttk.Button(task_button_frame, text="暂停选中", command=self.pause_selected, width=12)
        self.pause_btn.grid(row=0, column=2, padx=5)

        self.remove_btn = ttk.Button(task_button_frame, text="删除选中", command=self.remove_selected, width=12)
        self.remove_btn.grid(row=0, column=3, padx=5)

        self.clear_completed_btn = ttk.Button(task_button_frame, text="清除已完成", command=self.clear_completed, width=12)
        self.clear_completed_btn.grid(row=0, column=4, padx=5)

        # === 日志区域 ===
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="10")
        log_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        # 日志文本框
        self.log_text = scrolledtext.ScrolledText(log_frame, width=100, height=8, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # 状态栏
        self.status_label = ttk.Label(main_frame, text="就绪 | 活动下载: 0 | 最大并发: 3")
        self.status_label.grid(row=3, column=0, sticky=tk.W, pady=(5, 0))

    def browse_path(self):
        """浏览下载路径"""
        path = filedialog.askdirectory(title="选择下载目录")
        if path:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, path)
            # 保存配置
            self.config_manager.set('download_path', path)

    def log(self, message):
        """添加日志消息"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)  # 自动滚动到底部
        self.log_text.config(state=tk.DISABLED)

    def add_task(self):
        """添加下载任务"""
        # 获取输入
        m3u8_url = self.url_entry.get().strip()
        output_name = self.output_entry.get().strip()
        output_dir = self.path_entry.get().strip()
        max_workers = self.thread_var.get()

        # 验证输入
        if not m3u8_url:
            messagebox.showerror("错误", "请输入 M3U8 链接")
            return

        if not output_dir:
            messagebox.showerror("错误", "请选择下载路径")
            return

        # 如果没有填写文件名，自动生成
        if not output_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_name = f"video_{timestamp}"

        # 繁体转简体
        if is_traditional(output_name):
            original_name = output_name
            output_name = traditional_to_simplified(output_name)
            self.log(f"文件名转换: {original_name} → {output_name}")

        # 清理文件名（支持繁体中文）
        try:
            # 确保文件名可以正确编码
            output_name.encode('utf-8')
        except UnicodeEncodeError:
            # 如果编码失败，尝试修复
            output_name = output_name.encode('utf-8', errors='ignore').decode('utf-8')

        # 创建任务
        self.task_counter += 1
        task = DownloadTask(
            task_id=self.task_counter,
            url=m3u8_url,
            output_name=output_name,
            output_dir=output_dir,
            max_workers=max_workers
        )

        self.tasks[task.task_id] = task

        # 添加到列表（确保显示正确）
        try:
            display_name = f"{output_name}.mp4"
        except:
            display_name = f"video_{task.task_id}.mp4"

        self.task_tree.insert('', 'end', iid=task.task_id, values=(
            task.task_id,
            display_name,
            task.status,
            "0%",
            "0",
            "0",
            "-"
        ))

        self.log(f"添加任务 #{task.task_id}: {display_name}")

        # 清空输入
        self.url_entry.delete(0, tk.END)
        self.output_entry.delete(0, tk.END)

        # 保存配置
        self.config_manager.update({
            'download_path': output_dir,
            'max_workers': max_workers
        })

    def start_selected(self):
        """开始选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择任务")
            return

        for task_id in selection:
            task_id = int(task_id)
            task = self.tasks.get(task_id)
            if task and task.status in ["等待中", "已暂停"]:
                self.start_task(task)

    def start_all(self):
        """开始所有等待中的任务"""
        for task in self.tasks.values():
            if task.status in ["等待中", "已暂停"]:
                self.start_task(task)

    def start_task(self, task: DownloadTask):
        """启动单个任务"""
        if self.active_downloads >= self.max_concurrent:
            messagebox.showwarning("提示", f"已达到最大并发数 {self.max_concurrent}，请等待其他任务完成")
            return

        task.status = "下载中"
        self.update_task_display(task)

        # 创建下载线程
        task.thread = threading.Thread(
            target=self.download_thread,
            args=(task,),
            daemon=True
        )
        task.thread.start()

        self.active_downloads += 1
        self.update_status()

    def download_thread(self, task: DownloadTask):
        """下载线程"""
        try:
            # 创建下载器
            task.downloader = M3U8Downloader(
                task.url,
                task.output_name,
                task.max_workers,
                task.output_dir
            )

            # 设置进度回调
            def progress_callback(current, total, message):
                task.downloaded = current
                task.total = total
                if total > 0:
                    task.progress = (current / total) * 100
                task.message = message
                self.message_queue.put(('progress', task.task_id))

            task.downloader.progress_callback = progress_callback

            # 重定向输出
            import builtins
            original_print = print

            def task_print(*args, **kwargs):
                msg = ' '.join(str(arg) for arg in args)
                self.message_queue.put(('log', f"#{task.task_id} {msg}"))

            builtins.print = task_print

            try:
                # 执行下载
                task.downloader.download(auto_cleanup=True)
                task.status = "已完成"
                self.message_queue.put(('complete', task.task_id))

            finally:
                builtins.print = original_print

        except Exception as e:
            task.status = "已失败"
            task.message = str(e)
            self.message_queue.put(('error', task.task_id, str(e)))

        finally:
            self.active_downloads -= 1
            self.message_queue.put(('finish', task.task_id))

    def pause_selected(self):
        """暂停选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择任务")
            return

        for task_id in selection:
            task_id = int(task_id)
            task = self.tasks.get(task_id)
            if task and task.status == "下载中":
                # 注意：当前实现无法真正暂停，只能标记状态
                task.status = "已暂停"
                self.update_task_display(task)
                self.log(f"任务 #{task_id} 已暂停")

    def remove_selected(self):
        """删除选中的任务"""
        selection = self.task_tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请先选择任务")
            return

        for task_id in selection:
            task_id = int(task_id)
            task = self.tasks.get(task_id)
            if task and task.status not in ["下载中"]:
                # 删除任务
                del self.tasks[task_id]
                self.task_tree.delete(task_id)
                self.log(f"删除任务 #{task_id}")

    def clear_completed(self):
        """清除已完成的任务"""
        completed_ids = [
            task_id for task_id, task in self.tasks.items()
            if task.status in ["已完成", "已失败"]
        ]

        for task_id in completed_ids:
            del self.tasks[task_id]
            self.task_tree.delete(task_id)

        if completed_ids:
            self.log(f"清除了 {len(completed_ids)} 个已完成任务")

    def update_task_display(self, task: DownloadTask):
        """更新任务显示"""
        if task.task_id in self.tasks:
            speed_str = task.message if task.message else "-"
            self.task_tree.item(task.task_id, values=(
                task.task_id,
                f"{task.output_name}.mp4",
                task.status,
                f"{task.progress:.1f}%",
                str(task.downloaded),
                str(task.total),
                speed_str
            ))

    def update_status(self):
        """更新状态栏"""
        self.status_label.config(
            text=f"就绪 | 活动下载: {self.active_downloads} | 最大并发: {self.max_concurrent}"
        )

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
                        self.log(f"任务 #{task_id} 下载完成")

                elif msg_type == 'error':
                    task_id, error = msg[1], msg[2]
                    self.log(f"任务 #{task_id} 失败: {error}")

                elif msg_type == 'finish':
                    self.update_status()

                elif msg_type == 'log':
                    self.log(msg[1])

        except:
            pass

        # 继续处理
        self.root.after(100, self.process_messages)

    def open_settings(self):
        """打开设置窗口"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("400x300")
        settings_window.resizable(False, False)

        frame = ttk.Frame(settings_window, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        # 最大并发下载
        ttk.Label(frame, text="最大并发下载数:").grid(row=0, column=0, sticky=tk.W, pady=10)
        max_concurrent_var = tk.IntVar(value=self.max_concurrent)
        ttk.Spinbox(frame, from_=1, to=10, textvariable=max_concurrent_var, width=10).grid(row=0, column=1, pady=10)

        # 默认并发线程
        ttk.Label(frame, text="默认并发线程:").grid(row=1, column=0, sticky=tk.W, pady=10)
        default_workers_var = tk.IntVar(value=self.config_manager.get('max_workers', 16))
        ttk.Spinbox(frame, from_=1, to=64, textvariable=default_workers_var, width=10).grid(row=1, column=1, pady=10)

        # 自动清理
        auto_cleanup_var = tk.BooleanVar(value=self.config_manager.get('auto_cleanup', True))
        ttk.Checkbutton(frame, text="自动清理临时文件", variable=auto_cleanup_var).grid(row=2, column=0, columnspan=2, pady=10)

        # 保存按钮
        def save_settings():
            self.max_concurrent = max_concurrent_var.get()
            self.config_manager.update({
                'max_concurrent_downloads': max_concurrent_var.get(),
                'max_workers': default_workers_var.get(),
                'auto_cleanup': auto_cleanup_var.get()
            })
            self.update_status()
            settings_window.destroy()
            messagebox.showinfo("成功", "设置已保存")

        ttk.Button(frame, text="保存", command=save_settings, width=15).grid(row=3, column=0, columnspan=2, pady=20)

    def on_closing(self):
        """窗口关闭事件"""
        # 保存窗口大小
        geometry = self.root.geometry()
        self.config_manager.set('window_geometry', geometry)

        # 检查是否有正在下载的任务
        downloading = [task for task in self.tasks.values() if task.status == "下载中"]
        if downloading:
            if messagebox.askyesno("确认退出", f"还有 {len(downloading)} 个任务正在下载，确定要退出吗？"):
                self.root.destroy()
        else:
            self.root.destroy()


def main():
    """主函数"""
    root = tk.Tk()
    app = M3U8DownloaderGUI(root)

    # 绑定关闭事件
    root.protocol("WM_DELETE_WINDOW", app.on_closing)

    root.mainloop()


if __name__ == "__main__":
    main()
