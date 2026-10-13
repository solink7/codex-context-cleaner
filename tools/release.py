#!/usr/bin/env python3
"""
[INPUT]: README.md、默认配置、固定运行环境清单与平台入口。
[OUTPUT]: dist/ 内独立的 macOS 与 Windows 发布压缩包。
[POS]: 纯构建入口；只写 dist/，不修改源码或读取本地私有配置。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import argparse
import csv
import json
from pathlib import Path
import re
import shutil
import stat
import tempfile
import sys
import zipfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))
from tools.docs import render_readme
from sanitizer import load_config
IGNORED = {'__pycache__', '.DS_Store', '.runtime', 'CLAUDE.md', 'AGENTS.md'}
WINDOWS_SCRIPTS = ('start.ps1', 'stop.ps1', 'control.ps1', 'runtime.ps1')
PACKAGE_NAME = 'codex-context-cleaner'


def validate_manifest(path):
    with path.open(encoding='ascii', newline='') as source:
        entries = list(csv.DictReader(source, delimiter='\t'))
    platforms = {'macos-arm64', 'macos-x64', 'windows-x64', 'windows-x86', 'windows-arm64'}
    if len(entries) != len(platforms) or {entry.get('platform') for entry in entries} != platforms:
        raise ValueError('运行环境清单缺项或重复')
    for entry in entries:
        url = urlsplit(entry.get('url', ''))
        domain = 'github.com' if entry['platform'].startswith('macos-') else 'www.python.org'
        if (url.scheme != 'https' or url.hostname != domain or url.username is not None
                or not re.fullmatch(r'[0-9a-f]{64}', entry.get('sha256', ''))
                or not re.fullmatch(r'\d+\.\d+\.\d+', entry.get('version', ''))):
            raise ValueError(f"运行环境清单无效：{entry['platform']}")
    return entries


def validate_guide(path):
    return render_readme(path.read_text(encoding='utf-8-sig'))


def build_mac(folder, guide, config):
    folder.mkdir(parents=True)
    (folder / 'README.html').write_text(guide, encoding='utf-8')
    source = ROOT / 'platform' / 'mac'
    for name in ('启动代理.app', '停止代理.app'):
        shutil.copytree(source / name, folder / name,
                        ignore=shutil.ignore_patterns(*IGNORED))
    app = folder / '启动代理.app' / 'Contents'
    stop = folder / '停止代理.app' / 'Contents' / 'MacOS'
    (app / 'Resources').mkdir(parents=True, exist_ok=True)
    (app / 'MacOS' / 'runtime.sh').write_bytes((source / 'runtime.sh').read_bytes())
    for name in ('runtime-manifest.tsv', 'sanitizer.py'):
        (app / 'Resources' / name).write_bytes((ROOT / name).read_bytes())
    (app / 'Resources' / 'config.json').write_bytes(config)
    for name in ('status-ui.sh', 'progress.js'):
        (stop / name).write_bytes((app / 'MacOS' / name).read_bytes())
    return {'config.json': '启动代理.app/Contents/Resources/config.json'}


def build_windows(folder, guide, config):
    scripts = folder / 'platform' / 'windows'
    scripts.mkdir(parents=True)
    (folder / 'README.html').write_text(guide, encoding='utf-8')
    (folder / 'config.json').write_bytes(config)
    for name in ('sanitizer.py', 'runtime-manifest.tsv'):
        shutil.copy2(ROOT / name, folder / name)
    source = ROOT / 'platform' / 'windows'
    for name in WINDOWS_SCRIPTS:
        shutil.copy2(source / name, scripts / name)
    for name in ('start.cmd', 'stop.cmd'):
        shutil.copy2(source / name, folder / name)
    return {}


def write_archive(folder, archive, links):
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, f'{PACKAGE_NAME}/{path.relative_to(folder).as_posix()}')
                info.create_system = 3
                mode = 0o755 if path.name == 'launcher' else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                package.writestr(info, path.read_bytes())
        for name, target in links.items():
            info = zipfile.ZipInfo(f'{PACKAGE_NAME}/{name}')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(info, target.encode('utf-8'))
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError('压缩包完整性检查失败')
        for item in package.infolist():
            if not item.filename.isascii() and not item.flag_bits & 0x800:
                raise ValueError('Unicode 文件名缺少 ZIP UTF-8 标记')


def publish(output=None, target='all', config_path=None):
    output = (output or ROOT / 'dist').resolve()
    protected = [ROOT, *(ROOT / name for name in ('platform', 'tests', 'tools'))]
    if output == ROOT or any(path == output or path in output.parents for path in protected[1:]):
        raise ValueError('发布目录不能覆盖源码目录')
    validate_manifest(ROOT / 'runtime-manifest.tsv')
    guide = validate_guide(ROOT / 'README.md')
    config = (json.dumps(load_config(config_path or ROOT / 'config.example.json'), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    if target not in ('all', 'macOS', 'Windows'):
        raise ValueError('target 必须是 all、macOS 或 Windows')
    platform = ROOT / 'platform' / 'windows'
    for name in (*WINDOWS_SCRIPTS, 'start.cmd', 'stop.cmd'):
        path = platform / name
        if not path.is_file():
            raise ValueError(f'Windows 平台目录缺少 {name}')
        if path.suffix == '.ps1' and not path.read_bytes().startswith(b'\xef\xbb\xbf'):
            raise ValueError(f'{name} 必须使用 UTF-8 BOM，兼容 PowerShell 5.1')
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    # 完成两包构建与校验后才替换成品；暂存目录随后自动删除。
    with tempfile.TemporaryDirectory(prefix='.build-', dir=output) as temporary:
        staging = Path(temporary)
        for system, build in (('macOS', build_mac), ('Windows', build_windows)):
            if target != 'all' and target != system:
                continue
            folder = staging / system / PACKAGE_NAME
            links = build(folder, guide, config)
            archive = staging / f'{PACKAGE_NAME}-{system}.zip'
            write_archive(folder, archive, links)
            archives.append(archive)
        result = []
        for archive in archives:
            target = output / archive.name
            archive.replace(target)
            result.append(target)
    return tuple(result)


def main():
    parser = argparse.ArgumentParser(description='从单一源码生成 macOS 与 Windows 发布包')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    parser.add_argument('--target', choices=('all', 'macOS', 'Windows'), default='all')
    parser.add_argument('--config', type=Path, help='显式使用自定义配置；默认仅使用 config.example.json')
    args = parser.parse_args()
    for archive in publish(args.output_dir, args.target, args.config):
        print(f'已发布：{archive}')


if __name__ == '__main__':
    main()
