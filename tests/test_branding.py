"""
[INPUT]: 当前源码、Mac 升级兼容脚本与本机服务标识。
[OUTPUT]: 运行目录一致性、前代服务阻止重复启动与旧名称边界回归。
[POS]: 命名回归；升级检查使用临时 launchctl 夹具，不触碰实际服务。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from control import ServiceController

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_runtime_paths_and_public_guide_use_product_name(self):
        controller = ServiceController(ROOT)
        self.assertEqual(controller.label, 'local.codex-context-cleaner')
        self.assertEqual(controller.service_dir.name, 'codex-context-cleaner')
        guide = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('~/Library/Application Support/codex-context-cleaner/', guide)
        for name in ('platform/mac/settings.sh', 'platform/mac/启动代理.app/Contents/MacOS/launcher',
                     'platform/mac/停止代理.app/Contents/MacOS/launcher'):
            self.assertIn('Library/Application Support/codex-context-cleaner', (ROOT / name).read_text(encoding='utf-8'))
        for name in ('platform/windows/start.ps1', 'platform/windows/settings.ps1'):
            self.assertIn("'codex-context-cleaner'", (ROOT / name).read_text(encoding='utf-8-sig'))

    def test_previous_brand_is_only_used_by_upgrade_detection(self):
        allowed = {'platform/mac/legacy.sh', 'tools/smoke.py', 'tests/test_branding.py'}
        paths = [ROOT / name for name in ('README.md', 'CLAUDE.md', 'control.py', 'settings.py', 'sanitizer.py')]
        for folder in ('ui', 'platform', 'tests', 'tools'):
            paths.extend((ROOT / folder).rglob('*'))
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            if not path.is_file() or '__pycache__' in path.parts or relative in allowed:
                continue
            # 源模板中的历史构建副本由发布器重建，不作为源码审计对象。
            if relative.startswith('platform/mac/') and (path.name in {'config.json', 'runtime-manifest.tsv', 'sanitizer.py'}
                    or (path.name in {'runtime.sh', 'legacy.sh'} and 'Contents' in path.parts)
                    or ('停止代理.app' in path.parts and path.name in {'progress.js', 'status-ui.sh'})):
                continue
            try:
                content = path.read_text(encoding='utf-8-sig').lower()
            except UnicodeDecodeError:
                continue
            with self.subTest(path=relative):
                self.assertNotIn('relay', content)

    @unittest.skipUnless(Path('/bin/zsh').exists(), '需要 zsh 执行 Mac 升级检查')
    def test_previous_service_blocks_new_start_without_stopping_it(self):
        source = (ROOT / 'platform/mac/legacy.sh').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='cleaner-upgrade-') as temporary:
            root = Path(temporary)
            launchctl = root / 'launchctl'
            record = root / 'calls'
            for running in (True, False):
                launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > ' + shlex.quote(str(record))
                                     + '\nexit ' + ('0' if running else '113') + '\n', encoding='utf-8')
                launchctl.chmod(0o755)
                script = source.replace('/bin/launchctl', shlex.quote(str(launchctl)))
                script += '\nnotice() { print -r -- "$1"; }\nrequire_previous_service_stopped\n'
                result = subprocess.run(['/bin/zsh', '-c', script], capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 1 if running else 0)
                self.assertEqual(record.read_text().strip(), 'list local.relay-sanitizer')
                if running:
                    self.assertIn('旧版代理仍在运行', result.stdout)

    @unittest.skipUnless(Path('/bin/zsh').exists(), '需要 zsh 执行 Mac 升级检查')
    def test_stop_targets_only_the_previous_registered_service(self):
        source = (ROOT / 'platform/mac/legacy.sh').read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='cleaner-upgrade-stop-') as temporary:
            root = Path(temporary)
            record = root / 'calls'
            launchctl = root / 'launchctl'
            launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> ' + shlex.quote(str(record))
                                 + '\nexit 0\n', encoding='utf-8')
            launchctl.chmod(0o755)
            script = source.replace('/bin/launchctl', shlex.quote(str(launchctl)))
            script += '\nnotice() { print -r -- "$1"; }\nstop_previous_service\n'
            result = subprocess.run(['/bin/zsh', '-c', script], capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(record.read_text().splitlines(), ['list local.relay-sanitizer', 'remove local.relay-sanitizer'])


if __name__ == '__main__':
    unittest.main()
