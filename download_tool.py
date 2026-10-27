"""Local, bounded yt-dlp jobs for public YouTube and Bilibili videos."""
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / '.vendor'
if VENDOR.is_dir():
    sys.path.insert(0, str(VENDOR))


def available():
    return importlib.util.find_spec('yt_dlp') is not None


def deno_path():
    binary = 'deno.exe' if os.name == 'nt' else 'deno'
    candidates = [VENDOR / 'bin' / binary, VENDOR / 'Scripts' / binary]
    candidates += list((VENDOR / 'deno').rglob(binary)) if (VENDOR / 'deno').is_dir() else []
    return next((str(p) for p in candidates if p.is_file()), shutil.which('deno'))


def validate_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('请粘贴完整的视频网址。')
    parsed = urlparse(value.strip())
    hosts = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
             'youtu.be', 'bilibili.com', 'www.bilibili.com', 'm.bilibili.com', 'b23.tv'}
    if (parsed.scheme not in ('http', 'https') or parsed.hostname not in hosts
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError('目前只支持 Bilibili 和 YouTube 视频网址。')
    if parsed.path.startswith(('/playlist', '/@', '/channel/', '/space', '/bangumi/')):
        raise ValueError('请粘贴单个视频的网址，暂不支持合集、频道和番剧。')
    if parsed.hostname == 'youtu.be' or parsed.hostname == 'b23.tv':
        valid_path = bool(re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path))
    elif 'youtube.com' in parsed.hostname:
        valid_path = ((parsed.path == '/watch' and bool(re.fullmatch(r'[A-Za-z0-9_-]+', parse_qs(parsed.query).get('v', [''])[0])))
                      or bool(re.fullmatch(r'/(shorts|embed|live|v)/[A-Za-z0-9_-]+/?', parsed.path)))
    else:
        valid_path = bool(re.fullmatch(r'/video/(BV[A-Za-z0-9]+|av[0-9]+)/?', parsed.path))
    if not valid_path:
        raise ValueError('请粘贴单个视频页面或短链接，暂不支持此页面类型。')
    return parsed._replace(scheme='https', fragment='').geturl()


def validate_proxy(value):
    if not value:
        return ''
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('代理地址无效。')
    parsed = urlparse(value.strip())
    if parsed.scheme not in ('http', 'https', 'socks5', 'socks5h') or not parsed.hostname or not parsed.port:
        raise ValueError('代理格式示例：http://127.0.0.1:7890')
    return value.strip()


def summarize(info):
    if info.get('_type') in ('playlist', 'multi_video') or 'entries' in info:
        raise ValueError('暂不支持合集或多段视频，请使用单个视频链接。')
    if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
        raise ValueError('暂不支持正在直播或尚未开始的视频。')
    formats = info.get('formats') or ([info] if info.get('url') else [])
    audio = any(f.get('acodec') not in (None, 'none') for f in formats)
    legacy = any(f.get('url') and not f.get('height') and f.get('ext') in ('mp4', 'flv', 'webm', 'mkv')
                 and f.get('vcodec') != 'none' and not f.get('has_drm') for f in formats)
    choices = {}
    for f in formats:
        height = f.get('height')
        unknown_combined = (f.get('vcodec') is None and f.get('acodec') is None
                            and f.get('ext') in ('mp4', 'flv', 'webm', 'mkv'))
        if (not isinstance(height, (int, float)) or height <= 0 or f.get('vcodec') == 'none'
                or (f.get('vcodec') is None and not unknown_combined)
                or f.get('has_drm') or not (audio or unknown_combined)):
            continue
        height = int(height)
        choices[height] = max(choices.get(height, 0), f.get('fps') or 0)
    if not choices and not legacy:
        raise ValueError('没有找到可下载的音视频清晰度，可能需要登录或当前网络受限。')
    resolutions = [{'height': h, 'label': f'{h}p' + (f' · {int(fps)} fps' if fps else '')}
                   for h, fps in sorted(choices.items(), reverse=True)]
    if not resolutions and legacy:
        resolutions = [{'height': 0, 'label': '原始清晰度（平台未标注尺寸）'}]
    return {'title': str(info.get('title') or '视频')[:240],
            'platform': 'YouTube' if 'youtube' in str(info.get('extractor_key', '')).lower() else 'Bilibili',
            'duration': info.get('duration'),
            'resolutions': resolutions}


def friendly_error(error):
    text = str(error).lower()
    if any(word in text for word in ('sign in', 'login', 'cookies', 'premium', 'members-only', 'private video')):
        return '平台要求登录或视频有访问限制。当前版本只处理无需登录即可下载的视频。'
    if any(word in text for word in ('403', '429', 'blocked', 'bot', 'geo', 'region')):
        return '平台限制了当前请求或地区访问，请稍后重试或检查网络。'
    if any(word in text for word in ('timeout', 'timed out', 'resolve', 'connection', 'certificate', 'proxy')):
        return '网络连接失败，请检查网络；需要代理时填写本机代理地址后重新解析。'
    if 'format' in text:
        return '所选清晰度暂不可用，请重新解析链接或选择其他分辨率。'
    if isinstance(error, ValueError):
        return str(error)
    return '处理失败，链接可能失效或平台规则已更新。可重新运行安装脚本更新下载组件后重试。'


class QuietLogger:
    def debug(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


class DownloadManager:
    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg
        self.jobs = {}
        self.lock = threading.RLock()

    def cleanup(self):
        # Never delete an active download. Finished files expire after two hours.
        with self.lock:
            for key, job in list(self.jobs.items()):
                if job['state'] not in ('analyzing', 'downloading', 'merging') and time.time() - job['_updated'] > 7200:
                    shutil.rmtree(job['_folder'], ignore_errors=True)
                    del self.jobs[key]

    def update(self, key, **values):
        with self.lock:
            self.jobs[key].update(values, _updated=time.time())

    def snapshot(self, key):
        self.cleanup()
        with self.lock:
            job = self.jobs.get(key)
            if not job:
                raise KeyError('任务不存在或已过期，请重新解析。')
            return {k: v for k, v in job.items() if not k.startswith('_')}

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                shutil.rmtree(job['_folder'], ignore_errors=True)

    def options(self, job):
        options = {'quiet': True, 'no_warnings': True, 'logger': QuietLogger(),
                   'noplaylist': True, 'socket_timeout': 20, 'retries': 2,
                   'fragment_retries': 2, 'extractor_retries': 1,
                   'cachedir': False, 'restrictfilenames': False,
                   'ffmpeg_location': self.ffmpeg(),
                   'max_filesize': 2 * 1024 ** 3}
        if job['_proxy']:
            options['proxy'] = job['_proxy']
        deno = deno_path()
        if deno:
            options['js_runtimes'] = {'deno': {'path': deno}}
        return options

    def analyze(self, url, proxy=''):
        url, proxy = validate_url(url), validate_proxy(proxy)
        if not available():
            raise ValueError('下载组件尚未安装，请先运行安装脚本，然后重启工具。')
        if not self.ffmpeg():
            raise ValueError('缺少 FFmpeg，请先运行安装脚本。')
        self.cleanup()
        with self.lock:
            if sum(j['state'] in ('analyzing', 'downloading', 'merging') for j in self.jobs.values()) >= 2:
                raise ValueError('已有两个任务正在处理，请等待完成。')
            if len(self.jobs) >= 20:
                raise ValueError('当前会话任务较多，请清理任务后重试。')
            key = uuid.uuid4().hex
            self.jobs[key] = {'id': key, 'state': 'analyzing', 'message': '正在读取视频信息…',
                              'progress': 0, '_url': url, '_proxy': proxy, '_updated': time.time(),
                              '_folder': tempfile.mkdtemp(prefix='litebox-download-')}
        threading.Thread(target=self._analyze, args=(key,), daemon=True).start()
        return self.snapshot(key)

    def _analyze(self, key):
        from yt_dlp import YoutubeDL
        try:
            with YoutubeDL(self.options(self.jobs[key])) as ydl:
                info = ydl.extract_info(self.jobs[key]['_url'], download=False)
            summary = summarize(info)
            self.update(key, state='ready', message='选择分辨率后开始下载。', **summary)
        except Exception as error:
            self.update(key, state='error', message=friendly_error(error))

    def start(self, key, height):
        with self.lock:
            job = self.jobs.get(key)
            if not job:
                raise KeyError('任务已过期，请重新解析。')
            if job['state'] != 'ready':
                raise ValueError('请先解析视频，或等待当前任务完成。')
            if isinstance(height, bool) or height not in [r['height'] for r in job['resolutions']]:
                raise ValueError('请选择列表中的分辨率。')
            if sum(j['state'] in ('analyzing', 'downloading', 'merging') for j in self.jobs.values()) >= 2:
                raise ValueError('已有两个任务正在处理，请等待完成。')
            self.update(key, state='downloading', message='正在连接视频源…', progress=0)
        threading.Thread(target=self._download, args=(key, height), daemon=True).start()
        return self.snapshot(key)

    def _download(self, key, height):
        from yt_dlp import YoutubeDL
        job = self.jobs[key]
        started = time.monotonic()

        def progress(data):
            if time.monotonic() - started > 3600:
                raise ValueError('下载已超过一小时，请稍后重试。')
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            downloaded = data.get('downloaded_bytes') or 0
            if downloaded > 2 * 1024 ** 3:
                raise ValueError('视频超过 2 GB，请选择更低的分辨率。')
            if data['status'] == 'downloading':
                percent = min(99, round(downloaded / total * 100)) if total else 0
                self.update(key, state='downloading', progress=percent,
                            message=f'正在下载当前音视频流：{percent}%' if total else '正在下载，大小暂未知…')
            elif data['status'] == 'finished':
                self.update(key, state='merging', message='正在准备下一条流或合并音视频…')

        options = self.options(job)
        options.update({'format': f'bv[height={height}][ext=mp4]+ba[ext=m4a]/b[height={height}][ext=mp4]/bv[height={height}]+ba/b[height={height}]' if height else 'best',
                        'merge_output_format': 'mp4/mkv', 'outtmpl': str(Path(job['_folder']) / 'video.%(ext)s'),
                        'progress_hooks': [progress], 'overwrites': True})
        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(job['_url'], download=True)
            paths = [p for p in Path(job['_folder']).iterdir() if p.suffix in ('.mp4', '.mkv', '.webm', '.flv', '.mov') and not re.search(r'\.f[\w-]+\.', p.name)]
            if len(paths) != 1 or paths[0].stat().st_size == 0:
                raise ValueError('未生成完整视频，源文件可能超过大小限制，请选择较低清晰度。')
            path = paths[0]
            if path.stat().st_size > 2 * 1024 ** 3:
                raise ValueError('合并后的视频超过 2 GB，请选择更低的分辨率。')
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(info.get('title') or 'video'))[:120].strip('. ')
            self.update(key, state='done', progress=100, message='下载完成，请保存到电脑。',
                        filename=f'{name or "video"}_{str(height) + "p" if height else "original"}{path.suffix}', size=path.stat().st_size,
                        file_url=f'/api/video/file/{key}', _file=path)
        except Exception as error:
            shutil.rmtree(job['_folder'], ignore_errors=True)
            self.update(key, state='error', message=friendly_error(error))

    def file(self, key):
        with self.lock:
            job = self.jobs.get(key)
            if not job or job['state'] != 'done':
                raise KeyError('下载文件不存在或尚未完成。')
            self.update(key)  # Extend the lifetime while a user retrieves a result.
            return job['_file'], job['filename']

    def remove(self, key):
        with self.lock:
            job = self.jobs.get(key)
            if not job:
                return
            if job['state'] in ('analyzing', 'downloading', 'merging'):
                raise ValueError('请等待任务结束后再清理。')
            shutil.rmtree(job['_folder'], ignore_errors=True)
            del self.jobs[key]
