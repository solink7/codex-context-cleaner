"""
[INPUT]: 固定 UTF-8 字节的阶段/文本协议、共用提示脚本与原生 JXA 窗口。
[OUTPUT]: 中文状态往返、失败保留与成功自动关闭的回归结果。
[POS]: 提示层测试；使用临时状态文件，不启动代理或访问真实上游。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

UI = Path(__file__).resolve().parents[1] / 'platform/mac/启动代理.app/Contents/MacOS'


class ProtocolTests(unittest.TestCase):
    def parse(self, text):
        node = shutil.which('node')
        if not node:
            self.skipTest('需要 Node 检查纯文本协议')
        code = '''const vm = require('node:vm');
const context = {ObjC: {import() {}}};
vm.createContext(context);
vm.runInContext(require('node:fs').readFileSync(process.argv[1], 'utf8'), context);
console.log(JSON.stringify(context.parseStatus(require('node:fs').readFileSync(0, 'utf8'))));
'''
        result = subprocess.run([node, '-e', code, str(UI / 'progress.js')], input=text.encode('utf-8'),
                                capture_output=True, timeout=5, check=True)
        return json.loads(result.stdout.decode('utf-8'))

    def test_status_keeps_chinese_and_multiple_lines(self):
        message = '启动失败：端口已被占用。\n请先停止旧代理。\n路径含有 空格和中文。'
        self.assertEqual(self.parse('error\n' + message), {'phase': 'error', 'message': message})

    def test_partial_or_unknown_status_is_ignored(self):
        for text in ('success', 'unsupported\nmessage', ''):
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text))

    @unittest.skipUnless(Path('/bin/zsh').exists(), '需要 zsh 检查 Mac 写入协议')
    def test_shell_output_round_trips_without_partial_state(self):
        with tempfile.TemporaryDirectory(prefix='cleaner 提示 ') as directory:
            root = Path(directory)
            state = root / 'status'
            message = '代理已在运行：127.0.0.1:8787\n不会重复启动。'
            code = f'''APP_CONTENTS={shlex.quote(str(UI.parent))}
SERVICE={shlex.quote(str(root))}
source {shlex.quote(str(UI / 'status-ui.sh'))}
STATUS_FILE={shlex.quote(str(state))}
ui_write success {shlex.quote(message)}
'''
            subprocess.run(['/bin/zsh', '-c', code], check=True, capture_output=True, text=True, timeout=5)
            self.assertEqual(self.parse(state.read_text()), {'phase': 'success', 'message': message})
            self.assertFalse(state.with_suffix('.tmp').exists())


@unittest.skipUnless(sys.platform == 'darwin' and os.environ.get('CI') != 'true',
                         '原生窗口需本地桌面会话；CI 验证无窗口启动流程')
class NativeWindowTests(unittest.TestCase):
    def test_same_process_retains_error_then_closes_after_success(self):
        with tempfile.TemporaryDirectory(prefix='cleaner 原生提示 ') as directory:
            state = Path(directory) / 'status'
            state.write_text('progress\n[测试] 正在验证提示窗口，请稍候…', encoding='utf-8')
            process = subprocess.Popen(['/usr/bin/osascript', '-l', 'JavaScript',
                                        str(UI / 'progress.js'), str(state)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(.6)
                self.assertIsNone(process.poll(), '进度阶段窗口未能运行')
                staging = state.with_suffix('.tmp')
                staging.write_text('error\n[测试] 验证错误提示保留，请等待自动结束。', encoding='utf-8')
                staging.replace(state)
                time.sleep(2.5)
                self.assertIsNone(process.poll(), '失败原因被自动关闭')
                staging.write_text('success\n[测试] 验证通过，窗口即将自动关闭。', encoding='utf-8')
                staging.replace(state)
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertEqual(stderr, '')
            finally:
                if process.poll() is None:
                    process.terminate()
                process.communicate(timeout=3)


if __name__ == '__main__':
    unittest.main()
