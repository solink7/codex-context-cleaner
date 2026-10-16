"""
[INPUT]: platform/mac/runtime.sh、固定清单与临时归档/可执行文件夹具。
[OUTPUT]: 已有/首次环境探测上限、下载取消、安装互斥与回滚回归。
[POS]: 启动引导测试；下载用本地夹具替代，真实安装另行验证。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import hashlib
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
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

    def shell(self, body, download=None, discover=False, transfer=False):
        download_override = '' if transfer else ('download_runtime() { show_progress "正在下载 Python"; ' +
                            (download or ('cp ' + shlex.quote(str(self.archive)) + ' "$2"')) + '; }')
        script = f'''source {shlex.quote(str(ROOT / 'platform/mac/runtime.sh'))}
show_progress() {{ print -r -- "PROGRESS:$1"; }}
{download_override}
MANIFEST={shlex.quote(str(self.manifest))}
RUNTIME_ROOT={shlex.quote(str(self.destination))}
{'' if discover else 'python_candidates() { return 0; }'}
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

    def test_system_python_39_skips_download(self):
        executable = Path('/usr/bin/python3')
        if not executable.exists():
            self.skipTest('需要 Mac 系统 Python')
        result = self.shell('''ensure_python "$MANIFEST" "$RUNTIME_ROOT" macos-arm64 /usr/bin/python3 || exit 1
print -r -- "READY:$PYTHON_BIN"''', 'return 77')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('正在下载', result.stdout)

    def test_python_38_is_rejected(self):
        executable = self.root / 'python38'
        executable.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) +
                              " -I -c 'import sys; sys.version_info=(3,8); exec(sys.argv[1])' \"$3\"\n")
        executable.chmod(0o755)
        result = self.shell('probe_python ' + shlex.quote(str(executable)))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, '')

    def test_discovery_prefers_system_then_continues_after_old_python(self):
        old = self.root / 'old' / 'python3'
        current = self.root / 'current' / 'python3'
        old.parent.mkdir()
        current.parent.mkdir()
        old.write_text('#!/bin/sh\nexit 1\n')
        old.chmod(0o755)
        current.symlink_to(sys.executable)
        result = self.shell(f'''python_candidates() {{
 if [[ "$1" == common ]]; then print -r -- {shlex.quote(str(old))};
 else print -r -- {shlex.quote(str(current))}; fi
}}
ensure_python "$MANIFEST" "$RUNTIME_ROOT" macos-arm64 || exit 1
print -r -- "READY:$PYTHON_BIN"''', 'return 77', discover=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('正在下载', result.stdout)
        self.assertIn('READY:', result.stdout)

    def test_common_python_skips_fallback_enumeration(self):
        result = self.shell(f'''python_candidates() {{
 if [[ "$1" == common ]]; then print -r -- {shlex.quote(sys.executable)};
 else print -r -- 'FALLBACK-MUST-NOT-RUN' >&2; return 1; fi
}}
ensure_python "$MANIFEST" "$RUNTIME_ROOT" macos-arm64''', 'return 77')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')

    def test_hanging_python_times_out(self):
        executable = self.root / 'hanging-python'
        executable.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) +
                              " -c 'import time; time.sleep(60)'\n")
        executable.chmod(0o755)
        began = time.monotonic()
        result = self.shell('probe_python ' + shlex.quote(str(executable)))
        self.assertNotEqual(result.returncode, 0)
        self.assertLess(time.monotonic() - began, 6.5)

    def test_new_runtime_first_probe_has_separate_timeout(self):
        self.make_archive('#!/bin/sh\ncase "$0" in */.install.*/*) sleep 6;; esac\nprintf "%s\\n" "$0"\n')
        result = self.ensure()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('首次系统检查最多等待 30 秒', result.stdout)

    def test_aliases_probe_same_executable_once(self):
        executable = self.root / 'bad-python'
        executable.write_text('#!/bin/sh\nexit 1\n')
        executable.chmod(0o755)
        alias = self.root / 'alias-python'
        alias.symlink_to(executable)
        result = self.shell(f'''probe_python() {{ print -r -- PROBED >&2; return 1; }}
install_python() {{ return 1; }}
ensure_python "$MANIFEST" "$RUNTIME_ROOT" macos-arm64 {shlex.quote(str(executable))} {shlex.quote(str(alias))}''', 'return 77')
        self.assertEqual(result.stderr.count('PROBED'), 1)

    def test_existing_install_lock_rejects_parallel_install(self):
        lock = self.destination / 'install.lock'
        lock.write_text(str(os.getpid()) + '\n')
        result = self.ensure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('正在安装', result.stdout)
        self.assertNotIn('正在下载', result.stdout)
        self.assertEqual(lock.read_text(), str(os.getpid()) + '\n')

    def test_download_preflight_failure_never_starts_transfer(self):
        result = self.shell('''runtime_http_request() { print -r -- 'TRANSPORT'; return 7; }
download_runtime https://github.com/test "$RUNTIME_ROOT/python.tar.gz"
print -r -- "ERROR:$RUNTIME_ERROR"''', transfer=True)
        self.assertEqual(result.stdout.count('TRANSPORT'), 1)
        self.assertIn('未开始下载', result.stdout)
        self.assertFalse((self.destination / 'python.tar.gz').exists())

    def test_download_preflight_follows_final_response_size(self):
        headers = self.root / 'headers'
        result = self.shell(f'''runtime_http_request() {{
 print -r -- $'HTTP/1.1 302 Found\\r\\nContent-Length: 0\\r\\n\\r\\nHTTP/2 200\\r\\nContent-Length: 25165824\\r\\n' > {shlex.quote(str(headers))}
}}
check_runtime_download https://github.com/test {shlex.quote(str(headers))} || exit 1
print -r -- "SIZE:$RUNTIME_DOWNLOAD_SIZE"''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SIZE:25165824', result.stdout)

    def test_download_progress_shows_size_speed_and_remaining_time(self):
        result = self.shell('download_progress 1048576 3145728 2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1.0 / 3.0 MB', result.stdout)
        self.assertIn('512 KB/s', result.stdout)
        self.assertIn('预计还需 4 秒', result.stdout)
        result = self.shell('download_progress 0 0 0')
        self.assertIn('剩余时间待测速', result.stdout)

    def test_download_transport_has_no_retries_and_cleans_progress_files(self):
        result = self.shell('''check_runtime_download() { RUNTIME_DOWNLOAD_SIZE=1048576; }
runtime_http_request() { print -r -- "OPTIONS:$*"; return 28; }
download_runtime https://github.com/test "$RUNTIME_ROOT/python.tar.gz"
result=$?
print -r -- "ERROR:$RUNTIME_ERROR"
exit "$result"''', transfer=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--speed-time 20 --speed-limit 1', result.stdout)
        self.assertNotIn('--retry', result.stdout)
        self.assertIn('连续 20 秒', result.stdout)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_download_transfer_finishes_and_cleans_progress_files(self):
        result = self.shell('''check_runtime_download() { RUNTIME_DOWNLOAD_SIZE=4; }
runtime_http_request() {
 local previous argument
 for argument in "$@"; do
  if [[ "$previous" == --output ]]; then print -rn -- data > "$argument"; fi
  previous="$argument"
 done
 sleep .1
}
download_runtime https://github.com/test "$RUNTIME_ROOT/python.tar.gz"''', transfer=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.destination / 'python.tar.gz').read_bytes(), b'data')
        self.assertEqual([p.name for p in self.destination.iterdir()], ['python.tar.gz'])

    def test_cancel_download_reaps_worker(self):
        pidfile = self.root / 'worker.pid'
        # 与实际 curl 包装相同：子 shell 直接 exec，不留下孙进程。
        worker = self.root / 'worker.py'
        worker.write_text('import os,time\nfrom pathlib import Path\n' +
                          f'Path({str(pidfile)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
        script = f'''source {shlex.quote(str(ROOT / 'platform/mac/runtime.sh'))}
show_progress() {{ :; }}
check_runtime_download() {{ RUNTIME_DOWNLOAD_SIZE=99; }}
runtime_http_request() {{ exec {shlex.quote(sys.executable)} {shlex.quote(str(worker))}; }}
trap 'exit 1' TERM
download_runtime https://github.com/test {shlex.quote(str(self.root / 'download'))}
'''
        process = subprocess.Popen(['/bin/zsh', '-c', script], start_new_session=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 3
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            worker_pid = int(pidfile.read_text())
            process.terminate()
            process.communicate(timeout=3)
            with self.assertRaises(ProcessLookupError):
                os.kill(worker_pid, 0)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=3)

    def test_finder_discovers_conda_and_uv_without_shell_profile(self):
        conda = self.root / 'miniforge3/bin/python3'
        uv = self.root / '.local/share/uv/python/cpython-3.13-test-macos-arm64/bin/python3'
        for executable in (conda, uv):
            executable.parent.mkdir(parents=True)
            executable.symlink_to(sys.executable)
        result = self.shell('path=()\npython_candidates fallback ' + shlex.quote(str(self.root)), discover=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(conda), result.stdout.splitlines())
        self.assertIn(str(uv), result.stdout.splitlines())

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
        self.assertIn('首次验证失败', result.stdout)
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
