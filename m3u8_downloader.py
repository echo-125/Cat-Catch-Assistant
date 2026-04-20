#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M3U8 视频下载器
功能：下载 HLS 流媒体视频并转换为 MP4 格式
"""

import os
import re
import sys
import time
import requests
import subprocess
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Tuple, Optional, Callable

if sys.platform == 'win32':
    STARTUPINFO = subprocess.STARTUPINFO
    STARTF_USESHOWWINDOW = subprocess.STARTF_USESHOWWINDOW
    SW_HIDE = subprocess.SW_HIDE
else:
    STARTUPINFO = None


class M3U8Downloader:
    """M3U8 视频下载器"""

    ILLEGAL_CHARS = r'[<>:"/\\|?*]'

    def __init__(
        self,
        m3u8_url: str,
        output_name: str = "output",
        max_workers: int = 16,
        output_dir: str = "."
    ):
        self.m3u8_url = m3u8_url
        self.output_name = self._sanitize_filename(output_name)
        self.max_workers = max_workers
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.temp_dir = self.output_dir / f"{self.output_name}_temp"
        self.temp_dir.mkdir(exist_ok=True)

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Charset': 'utf-8, big5, gb2312, gbk'
        }

        self.session = requests.Session()
        self.session.headers.update(self.headers)

        self.total_segments = 0
        self.downloaded_segments = 0
        self.failed_segments = 0
        self.start_time: Optional[float] = None
        self.current_speed = 0.0

        self.progress_callback: Optional[Callable[[int, int, str], None]] = None

        self.max_retries = 3
        self.retry_delay = 2

        self._stop_flag = False

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        filename = re.sub(self.ILLEGAL_CHARS, '_', filename)
        filename = filename.strip('. ')

        if not filename:
            filename = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        return filename

    def download_m3u8_content(self) -> str:
        """下载 M3U8 播放列表内容"""
        print(f"[1/5] 正在下载播放列表: {self.m3u8_url}")

        response = self.session.get(self.m3u8_url, timeout=30)
        response.raise_for_status()

        for encoding in ['utf-8', 'big5', 'gbk', 'gb2312', response.apparent_encoding]:
            try:
                response.encoding = encoding
                if '#EXTM3U' in response.text.upper():
                    return response.text
            except (UnicodeDecodeError, UnicodeError):
                continue

        response.encoding = 'utf-8'
        return response.text

    def parse_m3u8(self, m3u8_content: str) -> List[str]:
        """解析 M3U8 内容，提取 TS 分片 URL"""
        print("[2/5] 正在解析播放列表...")

        lines = m3u8_content.split('\n')
        if not lines or not lines[0].strip().upper().startswith('#EXTM3U'):
            raise ValueError("不是有效的 M3U8 文件")

        segments = []
        for line in lines:
            line = line.strip()
            if not line or (line.startswith('#') and not line.startswith('#EXT-X-KEY')):
                continue

            if not line.startswith('#'):
                segment_url = line if line.startswith('http') else urljoin(self.m3u8_url, line)
                segments.append(segment_url)

        self.total_segments = len(segments)
        print(f"      找到 {self.total_segments} 个视频分片")

        if self.total_segments == 0:
            raise ValueError("未找到任何视频分片，可能是嵌套的 M3U8 列表")

        return segments

    def _download_single_segment(self, segment_url: str, index: int, update_progress: bool = True) -> Tuple[int, Optional[str]]:
        """下载单个分片"""
        if self._stop_flag:
            return (index, None)

        filename = f"segment_{index:04d}.ts"
        filepath = self.temp_dir / filename

        if filepath.exists() and filepath.stat().st_size > 0:
            if update_progress:
                self._update_progress()
            return (index, str(filepath))

        for retry in range(self.max_retries):
            if self._stop_flag:
                return (index, None)

            try:
                response = self.session.get(segment_url, timeout=30)
                response.raise_for_status()

                with open(filepath, 'wb') as f:
                    f.write(response.content)

                if update_progress:
                    self._update_progress()
                return (index, str(filepath))

            except requests.RequestException as e:
                if self._stop_flag:
                    return (index, None)
                if retry < self.max_retries - 1:
                    if retry == 0:
                        print(f"\n      分片 {index} 下载失败，准备重试...")
                    time.sleep(self.retry_delay)
                else:
                    print(f"\n      分片 {index} 下载失败（已重试{self.max_retries}次）: {e}")
                    self.failed_segments += 1
                    return (index, None)

        return (index, None)

    def _update_progress(self):
        """更新下载进度"""
        self.downloaded_segments += 1

        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed > 0:
                self.current_speed = self.downloaded_segments / elapsed
                remaining = (self.total_segments - self.downloaded_segments) / self.current_speed if self.current_speed > 0 else 0
                speed_str = f"{self.current_speed:.1f}片/秒"
                print(f"\r      下载进度: {self.downloaded_segments}/{self.total_segments} ({self.downloaded_segments/self.total_segments*100:.1f}%) | 速度: {speed_str} | 剩余: {remaining:.0f}秒", end='')
            else:
                print(f"\r      下载进度: {self.downloaded_segments}/{self.total_segments}", end='')
        else:
            print(f"\r      下载进度: {self.downloaded_segments}/{self.total_segments}", end='')

        if self.progress_callback:
            speed_str = f"{self.current_speed:.1f}片/秒" if self.current_speed > 0 else ""
            self.progress_callback(self.downloaded_segments, self.total_segments, speed_str)

    def download_all_segments(self, segment_urls: List[str]) -> List[str]:
        """并发下载所有 TS 分片"""
        print(f"[3/5] 正在下载视频分片（{self.max_workers} 线程并发）...")

        self.start_time = time.time()
        results: dict[int, Optional[str]] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index = {
                executor.submit(self._download_single_segment, url, idx): idx
                for idx, url in enumerate(segment_urls)
            }

            for future in as_completed(future_to_index):
                if self._stop_flag:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise RuntimeError("下载已取消")
                index, filepath = future.result()
                results[index] = filepath

        print()

        if self._stop_flag:
            raise RuntimeError("下载已取消")

        failed_indices = [i for i in range(len(segment_urls)) if results.get(i) is None]
        if failed_indices:
            self._retry_failed_segments(segment_urls, results, failed_indices)

        if self.start_time:
            elapsed = time.time() - self.start_time
            print(f"      下载耗时: {elapsed:.1f} 秒")
            if elapsed > 0:
                print(f"      平均速度: {self.downloaded_segments / elapsed:.2f} 片/秒")

        if self.failed_segments > 0:
            print(f"      警告: {self.failed_segments} 个分片下载失败")

        return [results[i] for i in range(len(segment_urls)) if results.get(i) is not None]

    def _retry_failed_segments(self, segment_urls: List[str], results: dict, failed_indices: List[int]) -> int:
        """重试失败的分片"""
        max_batch_retry = 3
        retry_success = 0

        for batch_retry in range(max_batch_retry):
            if not failed_indices:
                break

            print(f"      第 {batch_retry + 1} 次批量重试 {len(failed_indices)} 个分片...")

            batch_failed = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_index = {
                    executor.submit(self._download_single_segment, segment_urls[idx], idx, False): idx
                    for idx in failed_indices
                }

                for future in as_completed(future_to_index):
                    index, filepath = future.result()
                    if filepath:
                        results[index] = filepath
                        retry_success += 1
                        self.failed_segments -= 1
                        self.downloaded_segments += 1
                    else:
                        batch_failed.append(index)

            failed_indices = batch_failed
            if failed_indices:
                time.sleep(2)

        if failed_indices:
            print(f"      最终仍有 {len(failed_indices)} 个分片下载失败")

        return retry_success

    def merge_segments(self, segment_paths: List[str]) -> str:
        """合并所有 TS 分片"""
        print("[4/5] 正在合并视频分片...")

        merged_file = str(self.temp_dir / "merged.ts")

        with open(merged_file, 'wb') as outfile:
            for i, segment_path in enumerate(segment_paths):
                if segment_path and os.path.exists(segment_path):
                    with open(segment_path, 'rb') as infile:
                        outfile.write(infile.read())
                    print(f"\r      合并进度: {i+1}/{len(segment_paths)} ({(i+1)/len(segment_paths)*100:.1f}%)", end='')

        print(f"\n      合并完成: {merged_file}")
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
        """将 TS 文件转换为 MP4 格式"""
        print("[5/5] 正在转换为 MP4 格式...")

        output_file = str(self.output_dir / f"{self.output_name}.mp4")
        startupinfo = self._get_hidden_startupinfo()

        try:
            subprocess.run(
                ['ffmpeg', '-version'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                startupinfo=startupinfo
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("      警告: 未找到 ffmpeg，跳过转换")
            print(f"      你可以手动使用 ffmpeg 转换: ffmpeg -i \"{input_file}\" -c copy \"{output_file}\"")
            return input_file

        try:
            subprocess.run(
                ['ffmpeg', '-i', input_file, '-c', 'copy', '-y', output_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                startupinfo=startupinfo
            )

            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"      转换完成: {output_file}")
            print(f"      文件大小: {size_mb:.2f} MB")
            return output_file

        except subprocess.CalledProcessError as e:
            print(f"      转换失败: {e}")
            print(f"      你可以手动使用 ffmpeg 转换: ffmpeg -i \"{input_file}\" -c copy \"{output_file}\"")
            return input_file

    def cleanup(self):
        """清理临时文件"""
        print("\n正在清理临时文件...")

        try:
            for file in self.temp_dir.glob("*.ts"):
                file.unlink()

            if self.temp_dir.exists() and not any(self.temp_dir.iterdir()):
                self.temp_dir.rmdir()
                print("临时文件已清理")
        except OSError as e:
            print(f"清理失败: {e}")

    def stop(self):
        """停止下载"""
        self._stop_flag = True

    def download(self, auto_cleanup: bool = True):
        """执行完整的下载流程"""
        try:
            m3u8_content = self.download_m3u8_content()
            segment_urls = self.parse_m3u8(m3u8_content)
            segment_paths = self.download_all_segments(segment_urls)

            if not segment_paths:
                raise RuntimeError("没有成功下载任何分片")

            merged_file = self.merge_segments(segment_paths)
            final_file = self.convert_to_mp4(merged_file)

            file_size = os.path.getsize(final_file) / (1024 * 1024) if os.path.exists(final_file) else 0

            print("\n" + "=" * 50)
            print("✓ 下载完成！")
            print(f"输出文件: {final_file}")
            if file_size > 0:
                print(f"文件大小: {file_size:.2f} MB")
            print(f"成功下载: {self.downloaded_segments}/{self.total_segments} 个分片")
            if self.failed_segments > 0:
                print(f"失败分片: {self.failed_segments} 个")
            print("=" * 50)

            if auto_cleanup:
                self.cleanup()
            else:
                choice = input("\n是否删除临时文件？(y/n): ").strip().lower()
                if choice == 'y':
                    self.cleanup()

        except Exception as e:
            print(f"\n错误: {e}")
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.session.close()
        return False


def main():
    """主函数"""
    print("=" * 50)
    print("M3U8 视频下载器 v2.0")
    print("=" * 50)

    if len(sys.argv) > 1:
        m3u8_url = sys.argv[1]
        output_name = sys.argv[2] if len(sys.argv) > 2 else "output"
        output_dir = sys.argv[3] if len(sys.argv) > 3 else "."
    else:
        m3u8_url = input("\n请输入 M3U8 链接: ").strip()
        output_name = input("请输入输出文件名（不含扩展名，默认 output）: ").strip() or "output"
        output_dir = input("请输入保存路径（默认当前目录）: ").strip() or "."

    if not m3u8_url:
        print("错误: URL 不能为空")
        sys.exit(1)

    with M3U8Downloader(m3u8_url, output_name, max_workers=16, output_dir=output_dir) as downloader:
        downloader.download()


if __name__ == "__main__":
    main()