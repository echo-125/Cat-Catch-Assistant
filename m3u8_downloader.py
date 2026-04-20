#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8 视频下载器
功能：下载 HLS 流媒体视频并转换为 MP4 格式
作者：Claude Code
日期：2026-04-15
"""

import os
import re
import sys
import time
import requests
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional

# Windows下隐藏子进程窗口
if sys.platform == 'win32':
    import msvcrt
    STARTUPINFO = subprocess.STARTUPINFO
    STARTF_USESHOWWINDOW = subprocess.STARTF_USESHOWWINDOW
    SW_HIDE = subprocess.SW_HIDE
else:
    STARTUPINFO = None


class M3U8Downloader:
    """M3U8 视频下载器类"""

    def __init__(self, m3u8_url: str, output_name: str = "output", max_workers: int = 16, output_dir: str = "."):
        """
        初始化下载器

        参数:
            m3u8_url: M3U8 播放列表的 URL（可能是 .jpg 或其他扩展名）
            output_name: 输出文件名（不含扩展名）
            max_workers: 最大并发下载线程数
            output_dir: 输出目录路径
        """
        self.m3u8_url = m3u8_url

        # 处理文件名编码问题（支持繁体中文等特殊字符）
        self.output_name = self._sanitize_filename(output_name)

        self.max_workers = max_workers
        self.output_dir = Path(output_dir)

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 临时文件目录
        self.temp_dir = self.output_dir / f"{self.output_name}_temp"
        self.temp_dir.mkdir(exist_ok=True)

        # 请求头，模拟浏览器访问
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Charset': 'utf-8, big5, gb2312, gbk'  # 支持多种中文编码
        }

        # 统计信息
        self.total_segments = 0
        self.downloaded_segments = 0
        self.failed_segments = 0
        self.start_time = None
        self.current_speed = 0.0  # 当前下载速度（片/秒）

        # 进度回调函数
        self.progress_callback = None

        # 重试配置
        self.max_retries = 3  # 每个分片最多重试3次
        self.retry_delay = 2  # 重试延迟2秒

        # 停止标志（用于取消下载）
        self._stop_flag = False

    def _sanitize_filename(self, filename: str) -> str:
        """
        清理文件名，移除或替换不合法字符，支持繁体中文

        参数:
            filename: 原始文件名

        返回:
            清理后的文件名
        """
        # Windows文件名非法字符
        illegal_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']

        # 替换非法字符为下划线
        for char in illegal_chars:
            filename = filename.replace(char, '_')

        # 移除首尾空格和点
        filename = filename.strip('. ')

        # 如果文件名为空，使用默认名称
        if not filename:
            from datetime import datetime
            filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 确保文件名编码正确（支持繁体中文）
        try:
            # 尝试UTF-8编码
            filename.encode('utf-8')
        except UnicodeEncodeError:
            # 如果UTF-8失败，尝试其他编码
            try:
                filename = filename.encode('big5', errors='ignore').decode('big5')
            except:
                filename = filename.encode('utf-8', errors='ignore').decode('utf-8')

        return filename

    def download_m3u8_content(self) -> str:
        """
        下载 M3U8 播放列表内容

        返回:
            M3U8 文件的文本内容
        """
        print(f"[1/5] 正在下载播放列表: {self.m3u8_url}")

        try:
            response = requests.get(self.m3u8_url, headers=self.headers, timeout=30)
            response.raise_for_status()

            # 尝试多种编码，优先UTF-8，然后尝试Big5（繁体中文）
            content = None
            for encoding in ['utf-8', 'big5', 'gbk', 'gb2312', response.apparent_encoding]:
                try:
                    response.encoding = encoding
                    content = response.text
                    # 验证内容是否有效
                    if content and '#EXTM3U' in content.upper():
                        return content
                except:
                    continue

            # 如果都失败，使用默认编码
            response.encoding = 'utf-8'
            return response.text

        except requests.RequestException as e:
            raise Exception(f"下载 M3U8 文件失败: {e}")

    def parse_m3u8(self, m3u8_content: str) -> List[str]:
        """
        解析 M3U8 内容，提取所有 TS 分片的 URL

        参数:
            m3u8_content: M3U8 文件的文本内容

        返回:
            TS 分片的完整 URL 列表
        """
        print("[2/5] 正在解析播放列表...")

        segments = []
        lines = m3u8_content.split('\n')

        # 检查是否是 M3U8 文件
        if not lines[0].startswith('#EXTM3U'):
            raise Exception("不是有效的 M3U8 文件")

        # 遍历每一行
        for line in lines:
            line = line.strip()

            # 跳过空行和注释行（以 # 开头，但不是 #EXTINF 等标签）
            if not line or (line.startswith('#') and not line.startswith('#EXT-X-KEY')):
                continue

            # 如果是 TS 分片（不以 # 开头的行）
            if not line.startswith('#'):
                # 处理相对路径：将相对 URL 转换为完整 URL
                if line.startswith('http'):
                    segment_url = line
                else:
                    # 使用 urljoin 自动处理相对路径
                    segment_url = urljoin(self.m3u8_url, line)

                segments.append(segment_url)

        self.total_segments = len(segments)
        print(f"      找到 {self.total_segments} 个视频分片")

        if self.total_segments == 0:
            raise Exception("未找到任何视频分片，可能是嵌套的 M3U8 列表")

        return segments

    def download_segment(self, segment_url: str, index: int) -> Tuple[int, Optional[str]]:
        """
        下载单个 TS 分片（带重试机制）

        参数:
            segment_url: TS 分片的 URL
            index: 分片序号

        返回:
            (序号, 本地文件路径) 或 (序号, None 表示失败)
        """
        # 检查停止标志
        if self._stop_flag:
            return (index, None)

        # 生成本地文件名，使用 4 位数字编号（0000.ts, 0001.ts...）
        filename = f"segment_{index:04d}.ts"
        filepath = self.temp_dir / filename

        # 如果文件已存在且不为空，跳过下载（支持断点续传）
        if filepath.exists() and filepath.stat().st_size > 0:
            self.downloaded_segments += 1
            if self.progress_callback:
                self.progress_callback(self.downloaded_segments, self.total_segments, "下载进度")
            return (index, str(filepath))

        # 重试下载
        for retry in range(self.max_retries):
            # 每次重试前检查停止标志
            if self._stop_flag:
                return (index, None)

            try:
                # 下载分片
                response = requests.get(segment_url, headers=self.headers, timeout=30)
                response.raise_for_status()

                # 保存到文件
                with open(filepath, 'wb') as f:
                    f.write(response.content)

                # 更新进度
                self.downloaded_segments += 1
                progress = (self.downloaded_segments / self.total_segments) * 100

                # 计算下载速度
                speed_str = ""
                if self.start_time and self.downloaded_segments > 0:
                    elapsed_time = time.time() - self.start_time
                    if elapsed_time > 0:
                        self.current_speed = self.downloaded_segments / elapsed_time
                        remaining = (self.total_segments - self.downloaded_segments) / self.current_speed if self.current_speed > 0 else 0
                        speed_str = f"{self.current_speed:.1f}片/秒"
                        print(f"\r      下载进度: {self.downloaded_segments}/{self.total_segments} ({progress:.1f}%) | 速度: {speed_str} | 剩余: {remaining:.0f}秒", end='')
                    else:
                        print(f"\r      下载进度: {self.downloaded_segments}/{self.total_segments} ({progress:.1f}%)", end='')
                else:
                    print(f"\r      下载进度: {self.downloaded_segments}/{self.total_segments} ({progress:.1f}%)", end='')

                # 调用进度回调（传递速度信息）
                if self.progress_callback:
                    self.progress_callback(self.downloaded_segments, self.total_segments, speed_str)

                return (index, str(filepath))

            except Exception as e:
                if self._stop_flag:
                    return (index, None)
                if retry < self.max_retries - 1:
                    # 还有重试机会，等待后重试
                    if retry == 0:
                        print(f"\n      分片 {index} 下载失败，准备重试...")
                    time.sleep(self.retry_delay)
                else:
                    # 重试次数用完，标记为失败
                    print(f"\n      分片 {index} 下载失败（已重试{self.max_retries}次）: {e}")
                    self.failed_segments += 1
                    return (index, None)

        return (index, None)

    def download_all_segments(self, segment_urls: List[str]) -> List[str]:
        """
        并发下载所有 TS 分片

        参数:
            segment_urls: TS 分片 URL 列表

        返回:
            按顺序排列的本地文件路径列表
        """
        print(f"[3/5] 正在下载视频分片（{self.max_workers} 线程并发）...")

        # 记录开始时间
        self.start_time = time.time()

        # 使用字典存储下载结果，key 为序号，value 为文件路径
        results = {}

        # 使用线程池并发下载
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有下载任务
            future_to_index = {
                executor.submit(self.download_segment, url, idx): idx
                for idx, url in enumerate(segment_urls)
            }

            # 等待所有任务完成
            for future in as_completed(future_to_index):
                # 检查停止标志
                if self._stop_flag:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise Exception("下载已取消")
                index, filepath = future.result()
                results[index] = filepath

        print()  # 换行

        # 如果已停止，直接返回
        if self._stop_flag:
            raise Exception("下载已取消")

        # 检查失败的分片并进行统一重试
        failed_indices = [i for i in range(len(segment_urls)) if results.get(i) is None]

        if failed_indices:
            print(f"      发现 {len(failed_indices)} 个失败分片，开始统一重试...")
            retry_success = self._retry_failed_segments(segment_urls, results, failed_indices)

        # 计算总耗时
        if self.start_time:
            elapsed_time = time.time() - self.start_time
            print(f"      下载耗时: {elapsed_time:.1f} 秒")
            if elapsed_time > 0:
                avg_speed = self.downloaded_segments / elapsed_time
                print(f"      平均速度: {avg_speed:.2f} 片/秒")

        # 检查是否有失败的分片
        if self.failed_segments > 0:
            print(f"      警告: {self.failed_segments} 个分片下载失败")

        # 按序号排序，返回文件路径列表
        sorted_paths = [results[i] for i in range(len(segment_urls))]

        # 过滤掉失败的（None 值）
        valid_paths = [path for path in sorted_paths if path is not None]

        return valid_paths

    def _retry_failed_segments(self, segment_urls: List[str], results: dict, failed_indices: List[int]) -> int:
        """
        重试失败的分片（统一重试机制）

        参数:
            segment_urls: 所有分片 URL 列表
            results: 下载结果字典
            failed_indices: 失败的分片索引列表

        返回:
            重试成功的数量
        """
        retry_success = 0
        max_batch_retry = 3  # 批量重试次数

        for batch_retry in range(max_batch_retry):
            if not failed_indices:
                break

            print(f"      第 {batch_retry + 1} 次批量重试 {len(failed_indices)} 个分片...")

            # 重置失败计数
            batch_failed = []

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_index = {
                    executor.submit(self._retry_download_segment, segment_urls[idx], idx): idx
                    for idx in failed_indices
                }

                for future in as_completed(future_to_index):
                    index, filepath = future.result()
                    if filepath:
                        results[index] = filepath
                        retry_success += 1
                        self.failed_segments -= 1  # 减少失败计数
                    else:
                        batch_failed.append(index)

            failed_indices = batch_failed

            if failed_indices:
                # 等待一段时间再重试
                time.sleep(2)

        if failed_indices:
            print(f"      最终仍有 {len(failed_indices)} 个分片下载失败")

        return retry_success

    def _retry_download_segment(self, segment_url: str, index: int) -> Tuple[int, Optional[str]]:
        """
        重试下载单个分片（简化版，不更新进度）

        参数:
            segment_url: TS 分片的 URL
            index: 分片序号

        返回:
            (序号, 本地文件路径) 或 (序号, None 表示失败)
        """
        filename = f"segment_{index:04d}.ts"
        filepath = self.temp_dir / filename

        try:
            response = requests.get(segment_url, headers=self.headers, timeout=30)
            response.raise_for_status()

            with open(filepath, 'wb') as f:
                f.write(response.content)

            self.downloaded_segments += 1
            return (index, str(filepath))

        except Exception:
            return (index, None)

    def merge_segments(self, segment_paths: List[str]) -> str:
        """
        合并所有 TS 分片为一个文件

        参数:
            segment_paths: TS 分片文件路径列表

        返回:
            合并后的文件路径
        """
        print("[4/5] 正在合并视频分片...")

        merged_file = str(self.temp_dir / "merged.ts")

        # 使用二进制方式合并文件
        with open(merged_file, 'wb') as outfile:
            for i, segment_path in enumerate(segment_paths):
                if segment_path and os.path.exists(segment_path):
                    with open(segment_path, 'rb') as infile:
                        outfile.write(infile.read())

                    # 显示进度
                    progress = ((i + 1) / len(segment_paths)) * 100
                    print(f"\r      合并进度: {i+1}/{len(segment_paths)} ({progress:.1f}%)", end='')

        print()  # 换行
        print(f"      合并完成: {merged_file}")

        return merged_file

    def _get_hidden_startupinfo(self):
        """获取隐藏窗口的启动信息（Windows）"""
        if sys.platform == 'win32':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            return startupinfo
        return None

    def convert_to_mp4(self, input_file: str) -> str:
        """
        将 TS 文件转换为 MP4 格式（使用 ffmpeg）

        参数:
            input_file: 输入的 TS 文件路径

        返回:
            输出的 MP4 文件路径
        """
        print("[5/5] 正在转换为 MP4 格式...")

        output_file = str(self.output_dir / f"{self.output_name}.mp4")

        # 获取隐藏窗口的启动信息
        startupinfo = self._get_hidden_startupinfo()

        # 检查 ffmpeg 是否可用
        try:
            subprocess.run(['ffmpeg', '-version'],
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         check=True,
                         startupinfo=startupinfo)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("      警告: 未找到 ffmpeg，跳过转换")
            print(f"      你可以手动使用 ffmpeg 转换: ffmpeg -i {input_file} -c copy {output_file}")
            return input_file

        # 使用 ffmpeg 转换（-c copy 表示直接复制流，不重新编码，速度快）
        cmd = [
            'ffmpeg',
            '-i', input_file,      # 输入文件
            '-c', 'copy',          # 复制编码流（不重新编码）
            '-y',                  # 覆盖已存在的文件
            output_file            # 输出文件
        ]

        try:
            # 执行转换命令（隐藏窗口）
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                startupinfo=startupinfo
            )

            print(f"      转换完成: {output_file}")

            # 获取文件大小
            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"      文件大小: {size_mb:.2f} MB")

            return output_file

        except subprocess.CalledProcessError as e:
            print(f"      转换失败: {e}")
            print(f"      你可以手动使用 ffmpeg 转换: ffmpeg -i {input_file} -c copy {output_file}")
            return input_file

    def cleanup(self):
        """清理临时文件"""
        print("\n正在清理临时文件...")

        try:
            # 删除所有 TS 分片和合并的 TS 文件
            for file in self.temp_dir.glob("*.ts"):
                file.unlink()

            # 删除临时目录
            if self.temp_dir.exists() and not any(self.temp_dir.iterdir()):
                self.temp_dir.rmdir()
                print("临时文件已清理")
        except Exception as e:
            print(f"清理失败: {e}")

    def download(self, auto_cleanup: bool = True):
        """
        执行完整的下载流程

        参数:
            auto_cleanup: 是否自动清理临时文件（GUI模式建议True）
        """
        try:
            # 1. 下载 M3U8 播放列表
            m3u8_content = self.download_m3u8_content()

            # 2. 解析播放列表，获取所有分片 URL
            segment_urls = self.parse_m3u8(m3u8_content)

            # 3. 并发下载所有分片
            segment_paths = self.download_all_segments(segment_urls)

            if not segment_paths:
                raise Exception("没有成功下载任何分片")

            # 4. 合并分片
            merged_file = self.merge_segments(segment_paths)

            # 5. 转换为 MP4
            final_file = self.convert_to_mp4(merged_file)

            # 获取文件大小
            if os.path.exists(final_file):
                file_size = os.path.getsize(final_file) / (1024 * 1024)
            else:
                file_size = 0

            print("\n" + "="*50)
            print("✓ 下载完成！")
            print(f"输出文件: {final_file}")
            if file_size > 0:
                print(f"文件大小: {file_size:.2f} MB")
            print(f"成功下载: {self.downloaded_segments}/{self.total_segments} 个分片")
            if self.failed_segments > 0:
                print(f"失败分片: {self.failed_segments} 个")
            print("="*50)

            # 自动清理临时文件
            if auto_cleanup:
                self.cleanup()
            else:
                # 命令行模式，询问是否清理
                choice = input("\n是否删除临时文件？(y/n): ").strip().lower()
                if choice == 'y':
                    self.cleanup()

        except Exception as e:
            print(f"\n错误: {e}")
            sys.exit(1)


def main():
    """主函数"""
    print("="*50)
    print("M3U8 视频下载器 v1.0")
    print("="*50)

    # 获取用户输入
    if len(sys.argv) > 1:
        # 从命令行参数获取 URL
        m3u8_url = sys.argv[1]
        output_name = sys.argv[2] if len(sys.argv) > 2 else "output"
        output_dir = sys.argv[3] if len(sys.argv) > 3 else "."
    else:
        # 交互式输入
        m3u8_url = input("\n请输入 M3U8 链接: ").strip()
        output_name = input("请输入输出文件名（不含扩展名，默认 output）: ").strip() or "output"
        output_dir = input("请输入保存路径（默认当前目录）: ").strip() or "."

    # 验证输入
    if not m3u8_url:
        print("错误: URL 不能为空")
        sys.exit(1)

    # 创建下载器并开始下载
    downloader = M3U8Downloader(m3u8_url, output_name, max_workers=16, output_dir=output_dir)
    downloader.download()


if __name__ == "__main__":
    main()
