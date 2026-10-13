"""
[INPUT]: 单一源码发布器、默认配置与干净检出的临时夹具。
[OUTPUT]: 默认配置隔离、双端打包、文档生成与纯构建的回归结果。
[POS]: 发布回归，只写临时目录，不修改用户运行记录。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='relay 发布测试 ')
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / 'source').resolve()
        self.root.mkdir()
        for name in ('sanitizer.py', 'runtime-manifest.tsv', 'README.md', 'config.example.json'):
            shutil.copy2(release.ROOT / name, self.root / name)
        shutil.copytree(release.ROOT / 'platform', self.root / 'platform',
                        ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
        self.config = b'{"port":9999,"private_setting":"must-not-publish"}'
        self.default_config = (self.root / 'config.example.json').read_bytes()
        (self.root / 'config.json').write_bytes(self.config)

    def publish(self, output=None, target='all'):
        with patch('tools.release.ROOT', self.root):
            return release.publish(output, target)

    def test_one_source_produces_two_platform_archives(self):
        mac, windows = self.publish()
        self.assertEqual(mac.name, 'codex-context-cleaner-macOS.zip')
        self.assertEqual(windows.name, 'codex-context-cleaner-Windows.zip')
        self.assertEqual(mac.parent, self.root / 'dist')
        self.assertFalse((self.root.parent / 'Relay-Sanitizer-Windows').exists())
        self.assertFalse(list(mac.parent.glob('.build-*')))
        with zipfile.ZipFile(windows) as package:
            names = set(package.namelist())
            self.assertEqual(len(names), 10)
            self.assertIn('codex-context-cleaner/start.cmd', names)
            self.assertIn('codex-context-cleaner/platform/windows/start.ps1', names)
            self.assertNotIn('codex-context-cleaner/platform/mac/启动代理.app/Contents/Info.plist', names)
            self.assertEqual(package.read('codex-context-cleaner/config.json'), self.default_config)
            self.assertIsNone(package.testzip())
        with zipfile.ZipFile(mac) as package:
            names = package.namelist()
            self.assertIn('codex-context-cleaner/启动代理.app/Contents/MacOS/launcher', names)
            self.assertFalse(any('windows/' in name or name.endswith('.cmd') for name in names))
            self.assertIsNone(package.testzip())
        self.assertEqual((self.root / 'config.json').read_bytes(), self.config)

    def test_mac_config_link_and_executable_modes(self):
        mac, _ = self.publish()
        with zipfile.ZipFile(mac) as package:
            info = package.getinfo('codex-context-cleaner/config.json')
            self.assertTrue(stat.S_ISLNK(info.external_attr >> 16))
            self.assertEqual(package.read(info).decode('utf-8'), '启动代理.app/Contents/Resources/config.json')
            self.assertEqual(package.read('codex-context-cleaner/启动代理.app/Contents/Resources/config.json'), self.default_config)
            launcher = package.getinfo('codex-context-cleaner/启动代理.app/Contents/MacOS/launcher')
            self.assertTrue((launcher.external_attr >> 16) & stat.S_IXUSR)
            for item in package.infolist():
                if not item.filename.isascii():
                    self.assertTrue(item.flag_bits & 0x800)

    def test_packages_exclude_development_files_and_runtime_data(self):
        app = self.root / 'platform/mac/启动代理.app'
        (app / '__pycache__').mkdir()
        (app / '__pycache__/cache.pyc').write_bytes(b'cache')
        (app / '.runtime').mkdir()
        (app / '.runtime/process.json').write_text('runtime')
        (app / '.DS_Store').write_bytes(b'metadata')
        for archive in self.publish():
            with zipfile.ZipFile(archive) as package:
                names = package.namelist()
                self.assertEqual(sum(name.endswith('README.html') for name in names), 1)
                forbidden = ('CLAUDE.md', 'AGENTS.md', '__pycache__', '.runtime/', '.DS_Store', 'tests/', 'tools/', 'README.txt', 'README.md')
                self.assertFalse(any(part in name for name in names for part in forbidden))

    def test_target_build_works_without_local_config_or_generated_files(self):
        (self.root / 'config.json').unlink()
        generated = (
            'platform/mac/启动代理.app/Contents/MacOS/runtime.sh',
            'platform/mac/启动代理.app/Contents/Resources/config.json',
            'platform/mac/启动代理.app/Contents/Resources/sanitizer.py',
            'platform/mac/启动代理.app/Contents/Resources/runtime-manifest.tsv',
            'platform/mac/停止代理.app/Contents/MacOS/progress.js',
            'platform/mac/停止代理.app/Contents/MacOS/status-ui.sh',
        )
        for name in generated:
            (self.root / name).unlink(missing_ok=True)
        for target in ('macOS', 'Windows'):
            archives = self.publish(target=target)
            self.assertEqual(len(archives), 1)
            self.assertTrue(archives[0].name.endswith(target + '.zip'))
        self.assertFalse((self.root / 'config.json').exists())
        self.assertTrue(all(not (self.root / name).exists() for name in generated))

    def test_invalid_input_preserves_previous_releases(self):
        archives = self.publish()
        before = {p.name: p.read_bytes() for p in archives}
        script = self.root / 'platform/windows/start.ps1'
        script.write_bytes(script.read_bytes().removeprefix(b'\xef\xbb\xbf'))
        with self.assertRaisesRegex(ValueError, 'UTF-8 BOM'):
            self.publish()
        self.assertEqual(before, {p.name: p.read_bytes() for p in archives})

    def test_output_must_not_overwrite_source(self):
        for output in (self.root, self.root / 'platform/mac/build'):
            with self.assertRaisesRegex(ValueError, '源码目录'):
                self.publish(output)

    def test_readme_requires_single_heading(self):
        path = self.root / 'README.md'
        guide = release.validate_guide(path)
        self.assertIn('<meta charset="utf-8">', guide)
        path.write_text('missing title')
        with self.assertRaises(ValueError):
            release.validate_guide(path)

    def test_manifest_rejects_missing_platform_and_bad_hash(self):
        path = self.root / 'runtime-manifest.tsv'
        text = path.read_text(encoding='ascii')
        path.write_text('\n'.join(text.splitlines()[:-1]))
        with self.assertRaises(ValueError):
            release.validate_manifest(path)
        path.write_text(text.replace('11785155', 'zzzzzzzz'))
        with self.assertRaises(ValueError):
            release.validate_manifest(path)


if __name__ == '__main__':
    unittest.main()
