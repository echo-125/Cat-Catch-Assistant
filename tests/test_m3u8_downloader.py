import unittest
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

from m3u8_downloader import M3U8Downloader


class ParseM3U8Tests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(__file__).resolve().parent / "tmp" / uuid.uuid4().hex
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_downloader(self, url: str) -> M3U8Downloader:
        return M3U8Downloader(
            url,
            output_name="test",
            output_dir=str(self.temp_dir)
        )

    def test_parse_media_playlist_resolves_relative_segments(self):
        content = """#EXTM3U
#EXTINF:5,
segment_000.ts
#EXTINF:5,
segment_001.ts
"""
        downloader = self.create_downloader("https://example.com/path/index.m3u8")

        segments = downloader.parse_m3u8(content)

        self.assertEqual(
            segments,
            [
                "https://example.com/path/segment_000.ts",
                "https://example.com/path/segment_001.ts",
            ],
        )

    def test_parse_master_playlist_selects_highest_bandwidth_variant(self):
        master = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=640000
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1280000
high/index.m3u8
"""
        high_variant = """#EXTM3U
#EXTINF:4,
chunk-1.ts
#EXTINF:4,
chunk-2.ts
"""
        downloader = self.create_downloader("https://example.com/master.m3u8")

        with patch.object(downloader, "download_m3u8_content", return_value=high_variant) as mocked_download:
            segments = downloader.parse_m3u8(master)

        mocked_download.assert_called_once_with("https://example.com/high/index.m3u8", announce=False)
        self.assertEqual(
            segments,
            [
                "https://example.com/high/chunk-1.ts",
                "https://example.com/high/chunk-2.ts",
            ],
        )

    def test_parse_m3u8_rejects_playlist_loops(self):
        nested = """#EXTM3U
loop.m3u8
"""
        downloader = self.create_downloader("https://example.com/loop.m3u8")

        with patch.object(downloader, "download_m3u8_content", return_value=nested):
            with self.assertRaisesRegex(ValueError, "循环引用"):
                downloader.parse_m3u8(nested)


if __name__ == "__main__":
    unittest.main()
