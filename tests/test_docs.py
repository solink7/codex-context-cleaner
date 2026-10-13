"""
[INPUT]: tools.docs 的 Markdown 渲染能力。
[OUTPUT]: 中文、代码、链接保留与 HTML 转义的回归结果。
[POS]: 确保 GitHub README 与包内 HTML 使用同一份内容。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import unittest
from tools.docs import render_readme


class DocsTests(unittest.TestCase):
    def test_chinese_code_and_links_are_preserved(self):
        html = render_readme('# 工具\n\n- 保留 `call_id`\n- [下载](https://example.com)\n\n```powershell\n<中文 & test>\n```\n')
        self.assertIn('<meta charset="utf-8">', html)
        self.assertIn('<code>call_id</code>', html)
        self.assertIn('<a href="https://example.com">下载</a>', html)
        self.assertIn('&lt;中文 &amp; test&gt;', html)
        self.assertNotIn('<中文 & test>', html)

    def test_unclosed_code_and_unsafe_links_are_rejected(self):
        for text in ('# 工具\n```\ncode', '# 工具\n[link](javascript:alert)', '# 工具\n# 第二标题'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                render_readme(text)


if __name__ == '__main__':
    unittest.main()
