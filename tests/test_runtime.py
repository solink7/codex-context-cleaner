"""
[INPUT]: platform/mac/runtime.sh、固定清单与临时归档/可执行文件夹具。
[OUTPUT]: Mac 环境复用、校验、安装失败与替换回滚的分支回归结果。
[POS]: 启动引导测试；下载用本地夹具替代，真实安装另行验证。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(Path('/bin/zsh').exists(), '需要 zsh 执行 Mac 分支测试')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cleaner 环境 '测试'-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / '运行环境'
        self.destination.mkdir()
        self.manifest = self.root / 'manifest.tsv'
        self.archive = self.root / 'python.tar.gz'
        self.make_archive('#!/bin/sh\nprintf "%s\\n" "$0"\n')

    def make_archive(self, script):
        executable = self.root / 'fixture-python'
        executable.write_text(script)
        executable.chmod(0o755)
        with tarfile.open(self.archive, 'w:gz') as package:
            package.add(executable, arcname='python/bin/python3')
        self.write_manifest(hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def write_manifest(self, digest):
        self.manifest.write_text('platform\tversion\turl\tsha256\nmacos-arm64\t3.13.16\t'
                                 f'https://github.com/astral-sh/python-build-standalone/releases/download/test/python.tar.gz\t{digest}\n')

    def shell(self, body, download=None):
        script = f'''source {shlex.quote(str(ROOT / 'platform/mac/runtime.sh'))}
show_progress() {{ print -r -- "PROGRESS:$1"; }}
download_runtime() {{ {download or ('cp ' + shlex.quote(str(self.archive)) + ' "$2"')}; }}
MANIFEST={shlex.quote(str(self.manifest))}
RUNTIME_ROOT={shlex.quote(str(self.destination))}
{body}
'''
        return subprocess.run(['/bin/zsh', '-c', script], text=True, capture_output=True, timeout=15)

    def ensure(self, download=None):
        return self.shell('''if ensure_python "$MANIFEST" "$RUNTIME_ROOT" macos-arm64 ''; then
 print -r -- "READY:$PYTHON_BIN"
else
 print -r -- "ERROR:$RUNTIME_ERROR"
 exit 1
fi''', download)

    def test_existing_python_skips_download(self):
        result = self.shell(f'''ensure_python "$MANIFEST" "$RUNTIME_ROOT" macos-arm64 {shlex.quote(sys.executable)} || exit 1
print -r -- "READY:$PYTHON_BIN"''', 'return 77')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('正在下载', result.stdout)
        self.assertFalse((self.destination / 'python').exists())

    def test_missing_environment_installs_then_reuses_offline(self):
        first = self.ensure()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn(f'READY:{self.destination}/python/bin/python3', first.stdout)
        self.assertIn('正在下载', first.stdout)
        self.assertIn('正在校验', first.stdout)
        self.assertIn('正在安装', first.stdout)
        second = self.ensure('return 77')
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertNotIn('正在下载', second.stdout)
        self.assertEqual(list(self.destination.glob('.install.*')), [])

    def test_download_failure_cleans_staging(self):
        result = self.ensure('return 1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('下载失败', result.stdout)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_checksum_failure_never_extracts(self):
        self.write_manifest('0' * 64)
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('校验失败', result.stdout)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_corrupt_archive_is_rejected(self):
        self.archive.write_bytes(b'not a tar archive')
        self.write_manifest(hashlib.sha256(self.archive.read_bytes()).hexdigest())
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('解压失败', result.stdout)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_bad_runtime_does_not_replace_existing_files(self):
        old = self.destination / 'python' / 'bin' / 'python3'
        old.parent.mkdir(parents=True)
        old.write_text('#!/bin/sh\nexit 1\n')
        old.chmod(0o755)
        self.make_archive('#!/bin/sh\nexit 1\n')
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('未通过检查', result.stdout)
        self.assertEqual(old.read_text(), '#!/bin/sh\nexit 1\n')
        self.assertEqual(list(self.destination.glob('.install.*')), [])

    def test_relocation_failure_restores_previous_runtime(self):
        old = self.destination / 'python' / 'bin' / 'python3'
        old.parent.mkdir(parents=True)
        old.write_text('#!/bin/sh\nexit 1\n# previous runtime\n')
        old.chmod(0o755)
        self.make_archive('#!/bin/sh\ncase "$0" in */.install.*/*) printf "%s\\n" "$0";; *) exit 1;; esac\n')
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('撤回本次安装', result.stdout)
        self.assertIn('previous runtime', old.read_text())
        self.assertEqual(list(self.destination.glob('.install.*')), [])

    def test_invalid_manifest_rejects_installation(self):
        self.write_manifest('bad-digest')
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('正在下载', result.stdout)
        self.assertEqual(list(self.destination.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
