#!/usr/bin/env python3
"""Install a verified, platform-specific FFmpeg from a pinned PyPI wheel."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION = '0.6.0'


def download(url, destination, proxy=None):
    try:
        with urllib.request.urlopen(url, timeout=90) as response, destination.open('wb') as output:
            shutil.copyfileobj(response, output)
        return
    except Exception as original:
        # Official macOS Python may lack its own CA bundle; system curl uses
        # the operating system's trust store. Never disable TLS verification.
        curl = shutil.which('curl')
        if not curl:
            raise original
        print('正在使用系统下载器重试…', flush=True)
        command = [curl, '--fail', '--location', '--silent', '--show-error',
                   '--retry', '2', '--connect-timeout', '20', '--max-time', '300',
                   '--output', str(destination)]
        if proxy:
            command += ['--proxy', proxy]
        result = subprocess.run(command + [url], capture_output=True, timeout=330)
        if result.returncode:
            raise RuntimeError('网络下载失败，请检查连接或使用 --proxy 指定代理。') from original


def validate(executable):
    try:
        result = subprocess.run([str(executable), '-version'], capture_output=True, timeout=20)
        if result.returncode or b'ffmpeg version' not in result.stdout:
            return False
        # Verify both codecs used by this tool, without building any project.
        with tempfile.TemporaryDirectory(prefix='media-check-') as folder:
            for codec, suffix in [('libmp3lame', 'mp3'), ('libx264', 'mp4')]:
                audio = suffix == 'mp3'
                cmd = [str(executable), '-v', 'error', '-f', 'lavfi', '-i',
                       'sine=duration=0.1' if audio else 'color=size=16x16:duration=0.1',
                       '-c:a' if audio else '-c:v', codec, str(Path(folder) / ('test.' + suffix))]
                if subprocess.run(cmd, capture_output=True, timeout=30).returncode:
                    return False
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def wheel_tag(system, machine):
    machine = machine.lower()
    if system == 'Darwin':
        return 'macosx_11_0_arm64' if machine in ('arm64', 'aarch64') else 'macosx_10_9_x86_64' if machine in ('x86_64', 'amd64') else None
    if system == 'Windows':
        return 'win_amd64' if machine in ('amd64', 'x86_64') else None
    if system == 'Linux' and machine in ('x86_64', 'amd64'):
        return 'manylinux2014_x86_64'
    return None


def install(proxy=None, check=False):
    target = ROOT / 'bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    for candidate in [target, shutil.which('ffmpeg')]:
        if candidate and validate(candidate):
            print('FFmpeg 已就绪：' + str(candidate))
            return
    if check:
        raise RuntimeError('未找到可运行且支持 MP3 / H.264 的 FFmpeg，请先运行安装脚本。')
    tag = wheel_tag(platform.system(), platform.machine())
    if not tag:
        raise RuntimeError('当前平台没有对应安装包。请自行安装 FFmpeg 并加入 PATH 后重试。')
    if proxy:
        urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy})))
    print('正在查询对应平台的 FFmpeg 安装包：' + tag, flush=True)
    with tempfile.TemporaryDirectory(prefix='ffmpeg-metadata-') as folder:
        metadata_file = Path(folder) / 'metadata.json'
        download(f'https://pypi.org/pypi/imageio-ffmpeg/{VERSION}/json', metadata_file, proxy)
        metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
    package = next((item for item in metadata['urls'] if item['filename'].endswith(tag + '.whl')), None)
    if not package:
        raise RuntimeError('没有找到对应架构的软件包，请自行安装 FFmpeg。')
    if not package['url'].startswith('https://files.pythonhosted.org/'):
        raise RuntimeError('下载地址不属于预期的软件包源，已停止。')
    target.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ffmpeg-install-') as folder:
        archive = Path(folder) / 'package.whl'
        print('正在下载（首次安装需要联网）…', flush=True)
        digest = hashlib.sha256()
        download(package['url'], archive, proxy)
        with archive.open('rb') as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != package['digests']['sha256']:
            raise RuntimeError('下载校验失败，请重新运行安装脚本。')
        staged = Path(folder) / target.name
        with zipfile.ZipFile(archive) as bundle:
            name = next(n for n in bundle.namelist() if '/binaries/ffmpeg-' in n and not n.endswith('/'))
            staged.write_bytes(bundle.read(name))
            staged.chmod(0o755)
            if not validate(staged):
                raise RuntimeError('FFmpeg 运行验证失败，系统版本或架构可能不兼容。')
            # Keep license notices alongside the downloaded executable.
            for name in bundle.namelist():
                if 'LICENSE' in Path(name).name.upper() or 'COPYING' in Path(name).name.upper():
                    (target.parent / Path(name).name).write_bytes(bundle.read(name))
        # Stage beside the target so final replacement is atomic on this filesystem.
        pending = target.with_name(target.name + '.installing')
        try:
            shutil.copy2(staged, pending)
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    print('安装完成，MP3 / H.264 编码验证通过。')


def install_downloader(proxy=None, check=False, upgrade=False):
    vendor = ROOT / '.vendor'
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(vendor), str(ROOT))))
    probe_code = ('import yt_dlp, yt_dlp_ejs, download_tool; import subprocess; '
                  'runtime = download_tool.deno_path(); assert runtime; '
                  'subprocess.run([runtime, "--version"], check=True, capture_output=True)')
    probe = subprocess.run([sys.executable, '-c',
                            probe_code],
                           env=env, capture_output=True, timeout=30)
    if probe.returncode == 0 and not upgrade:
        print('视频下载组件已就绪。')
        return
    if check:
        print('提示：视频下载组件未就绪，运行安装脚本后重启可启用；其他工具仍可使用。')
        return
    print('正在安装视频下载组件（yt-dlp / Deno），首次下载需要联网…', flush=True)
    pip = subprocess.run([sys.executable, '-m', 'pip', '--version'], capture_output=True)
    if pip.returncode:
        subprocess.run([sys.executable, '-m', 'ensurepip', '--upgrade'], check=True)
    command = [sys.executable, '-m', 'pip', 'install', '--upgrade', '--only-binary=:all:',
               '--target', str(vendor), '--disable-pip-version-check', '--no-warn-script-location',
               '-r', str(ROOT / 'requirements-download.txt')]
    if proxy:
        command += ['--proxy', proxy]
    subprocess.run(command, check=True)
    if subprocess.run([sys.executable, '-c', probe_code], env=env).returncode:
        raise RuntimeError('下载组件验证失败，请检查 Python 版本和平台。')
    print('视频下载组件安装完成。')


def main():
    parser = argparse.ArgumentParser(description='安装本地媒体工具所需的 FFmpeg')
    parser.add_argument('--check', action='store_true', help='仅检查环境，不下载')
    parser.add_argument('--proxy', help='下载代理，如 http://127.0.0.1:7890')
    parser.add_argument('--update-downloader', action='store_true', help='更新视频下载组件以适应平台变化')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        print('需要 Python 3.11 或更高版本。', file=sys.stderr)
        return 1
    try:
        install(args.proxy, args.check)
        install_downloader(args.proxy, args.check, args.update_downloader)
    except Exception as error:
        print('安装未完成：' + str(error), file=sys.stderr)
        print('请确认网络可访问 PyPI；使用代理时可运行：python setup.py --proxy http://127.0.0.1:端口', file=sys.stderr)
        return 1
    print('现在可以双击启动脚本打开工具。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
