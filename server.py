#!/usr/bin/env python3
"""A loopback-only audio converter. Requires Python 3 and FFmpeg."""
import json
import os
import shutil
import subprocess
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 2 * 1024**3


def ffmpeg_path():
    bundled = ROOT / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    return str(bundled) if bundled.is_file() else shutil.which('ffmpeg')


class Handler(BaseHTTPRequestHandler):
    def error(self, status, message):
        data = json.dumps({'error': message}, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/status':
            data = json.dumps({'ffmpeg': bool(ffmpeg_path())}).encode()
            mime = 'application/json'
        elif path == '/image-tool.js':
            data = (ROOT / 'image-tool.js').read_bytes()
            mime = 'text/javascript; charset=utf-8'
        elif path == '/':
            data = (ROOT / 'index.html').read_bytes()
            mime = 'text/html; charset=utf-8'
        else:
            return self.error(404, '页面不存在')
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        enhance = urlparse(self.path).path == '/api/enhance'
        if urlparse(self.path).path not in ('/api/convert', '/api/enhance'):
            return self.error(404, '接口不存在')
        # Reject cross-origin requests to this local service.
        if self.headers.get('Origin') not in (None, f'http://{self.headers.get("Host")}'):
            return self.error(403, '不允许跨站请求')
        if not ffmpeg_path():
            return self.error(503, '请先安装 FFmpeg，再重新尝试转换。')
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.error(400, '文件大小无效')
        if not 0 < size <= MAX_BYTES:
            return self.error(413, '请选择小于 2 GB 的视频')
        bitrate = parse_qs(urlparse(self.path).query).get('bitrate', ['192'])[0]
        if bitrate not in ('128', '192', '320'):
            return self.error(400, '音质参数无效')
        query = parse_qs(urlparse(self.path).query)
        preset = query.get('preset', ['gentle'])[0]
        resolution = query.get('resolution', ['original'])[0]
        preview = query.get('preview', ['0'])[0] == '1'
        filters = {
            'gentle': 'hqdn3d=1.2:1.2:3:3,unsharp=5:5:0.45:5:5:0',
            'lowlight': 'hqdn3d=3:3:6:6,eq=brightness=0.035:contrast=1.05:gamma=1.12,unsharp=5:5:0.3:5:5:0',
            'animation': 'hqdn3d=1:1:2:2,unsharp=5:5:0.6:5:5:0',
        }
        if enhance and (preset not in filters or resolution not in ('original', '1080', '2160')):
            return self.error(400, '增强参数无效')
        with tempfile.TemporaryDirectory(prefix='tomp3-') as folder:
            source, target = Path(folder) / 'input.mp4', Path(folder) / ('output.mp4' if enhance else 'output.mp3')
            with source.open('wb') as output:
                remaining = size
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        return self.error(400, '文件上传中断')
                    output.write(chunk)
                    remaining -= len(chunk)
            command = [ffmpeg_path(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(source)]
            if enhance:
                vf = filters[preset]
                if resolution != 'original':
                    # Fit inside a landscape/portrait box; never downscale larger sources.
                    height = int(resolution)
                    width = height * 16 // 9
                    vf += f",scale=w='if(gte(iw,ih),max(iw,{width}),max(iw,{height}))':h='if(gte(iw,ih),max(ih,{height}),max(ih,{width}))':force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"
                vf += ',scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1'
                if preview:
                    command += ['-t', '5']
                command += ['-map', '0:v:0', '-map', '0:a:0?', '-vf', vf,
                            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
                            '-movflags', '+faststart']
            else:
                command += ['-map', '0:a:0', '-vn', '-codec:a', 'libmp3lame', '-b:a', bitrate + 'k']
            command.append(str(target))
            try:
                result = subprocess.run(command, capture_output=True, timeout=3600)
            except subprocess.TimeoutExpired:
                return self.error(408, '处理超过一小时，请使用更短的视频或较低的输出分辨率')
            if result.returncode or not target.exists():
                return self.error(422, '无法处理，请确认视频文件完整且包含所需的视频或音轨。')
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4' if enhance else 'audio/mpeg')
            self.send_header('Content-Length', str(target.stat().st_size))
            self.send_header('Content-Disposition', 'attachment; filename="' + target.name + '"')
            self.end_headers()
            with target.open('rb') as audio:
                shutil.copyfileobj(audio, self.wfile)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('127.0.0.1', 8765), Handler)
    print('本地 MP4 → MP3：http://127.0.0.1:8765（按 Ctrl+C 停止）')
    webbrowser.open('http://127.0.0.1:8765')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
