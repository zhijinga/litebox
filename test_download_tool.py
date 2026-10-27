"""Offline downloader integration tests: real HTTP, format selection, merging."""
import copy
import functools
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import download_tool as tool
import server


class SilentFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args): pass


class DownloadTests(unittest.TestCase):
    def test_url_validation(self):
        for url in ('file:///etc/passwd', 'https://localhost/a', 'https://youtube.com.evil.com/a',
                    'https://user:pass@youtube.com/watch?v=x', 'https://youtube.com:8080/watch?v=x',
                    'https://www.youtube.com/redirect?q=http://localhost/',
                    'https://www.youtube.com/playlist?list=x'):
            with self.subTest(url=url), self.assertRaises(ValueError): tool.validate_url(url)
        self.assertEqual(tool.validate_url(' http://youtu.be/example#t=1 '), 'https://youtu.be/example')

    def test_resolution_list_and_restrictions(self):
        info = {'formats': [{'height': 720, 'vcodec': 'h264', 'acodec': 'aac', 'fps': 30},
                            {'height': 720, 'vcodec': 'vp9', 'acodec': 'none', 'fps': 60},
                            {'height': 1080, 'vcodec': 'h264', 'has_drm': True},
                            {'height': 90, 'vcodec': 'none', 'acodec': 'none'}]}
        self.assertEqual(tool.summarize(info)['resolutions'], [{'height': 720, 'label': '720p · 60 fps'}])
        for extra in ({'is_live': True}, {'entries': []}):
            with self.assertRaises(ValueError): tool.summarize(dict(info, **extra))
        legacy = {'url': 'https://example.com/legacy.mp4', 'ext': 'mp4'}
        self.assertEqual(tool.summarize(legacy)['resolutions'][0]['height'], 0)
        self.assertEqual(tool.summarize({'formats': [{'format_id': '16', 'ext': 'mp4', 'height': 360}]})['resolutions'][0]['height'], 360)

    def test_local_http_download_and_merge(self):
        if not tool.available() or not server.ffmpeg_path(): self.skipTest('Run installer first')
        from yt_dlp import YoutubeDL
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for height in (144, 240):
                subprocess.run([server.ffmpeg_path(), '-v', 'error', '-f', 'lavfi', '-i',
                                f'color=size={height * 2}x{height}:rate=2:duration=1', '-an',
                                '-c:v', 'libx264', str(root / f'{height}.mp4')], check=True)
            subprocess.run([server.ffmpeg_path(), '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=1',
                            '-c:a', 'aac', str(root / 'audio.m4a')], check=True)
            http = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(SilentFiles, directory=folder))
            threading.Thread(target=http.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{http.server_port}'
            info = {'id': 'fixture', 'title': '中文测试 / title', 'extractor_key': 'Youtube', 'duration': 1,
                    'formats': [{'format_id': str(h), 'url': f'{base}/{h}.mp4', 'ext': 'mp4',
                                 'height': h, 'width': h * 2, 'vcodec': 'avc1.640028', 'acodec': 'none'} for h in (144, 240)]
                    + [{'format_id': 'audio', 'url': base + '/audio.m4a', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2'}]}

            class FixtureDL(YoutubeDL):
                def extract_info(self, url, download=True, **kwargs):
                    # Only metadata is stubbed; downloading, choosing and merging are real.
                    return self.process_ie_result(copy.deepcopy(info), download=download)

            manager = tool.DownloadManager(server.ffmpeg_path)
            try:
                with patch('yt_dlp.YoutubeDL', FixtureDL):
                    job = manager.analyze('https://www.youtube.com/watch?v=fixture')
                    key = job['id']
                    for _ in range(100):
                        job = manager.snapshot(key)
                        if job['state'] != 'analyzing': break
                        time.sleep(.05)
                    self.assertEqual(job['state'], 'ready', job)
                    with self.assertRaises(ValueError): manager.start(key, 1080)
                    manager.start(key, 144)
                    for _ in range(200):
                        job = manager.snapshot(key)
                        if job['state'] not in ('downloading', 'merging'): break
                        time.sleep(.05)
                    self.assertEqual(job['state'], 'done', job)
                    result, name = manager.file(key)
                    self.assertIn('144p.mp4', name)
                    probe = subprocess.run([server.ffmpeg_path(), '-hide_banner', '-i', str(result), '-f', 'null', '-'], capture_output=True, text=True)
                    self.assertEqual(probe.returncode, 0)
                    self.assertIn('288x144', probe.stderr)
                    self.assertIn('Audio: aac', probe.stderr)
                    self.assertNotIn('_url', job)
                    manager.remove(key)
                    self.assertFalse(result.exists())
                    with self.assertRaises(KeyError): manager.snapshot(key)
            finally:
                manager.close(); http.shutdown(); http.server_close()


if __name__ == '__main__': unittest.main()
