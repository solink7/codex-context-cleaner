"""
[INPUT]: 根目录 README.md 中的标题、段落、列表、链接与代码块。
[OUTPUT]: 带 UTF-8 声明的离线 HTML 使用说明。
[POS]: 发布器的文档渲染器，只维护 Markdown 源，不生成第二份仓库说明。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import html
import re
from urllib.parse import urlsplit


def inline(text):
    # 先识别代码与链接，再转义普通文本，防止说明内容注入 HTML。
    pattern = r'`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*'
    parts = []
    cursor = 0
    for match in re.finditer(pattern, text):
        parts.append(html.escape(text[cursor:match.start()]))
        code, label, target, strong = match.groups()
        if code is not None:
            parts.append('<code>' + html.escape(code) + '</code>')
        elif target is not None:
            if urlsplit(target).scheme not in ('https', 'http', ''):
                raise ValueError('README 链接使用了不支持的协议')
            parts.append('<a href="' + html.escape(target, quote=True) + '">' + html.escape(label) + '</a>')
        else:
            parts.append('<strong>' + html.escape(strong) + '</strong>')
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    return ''.join(parts)


def render_readme(text):
    lines = text.splitlines()
    titles = [line[2:] for line in lines if line.startswith('# ')]
    if len(titles) != 1:
        raise ValueError('README.md 必须包含一个主标题')
    parts, paragraph = [], []
    listing = None
    code = None

    def flush_paragraph():
        if paragraph:
            parts.append('<p>' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()

    for line in lines:
        if code is not None:
            if line.startswith('```'):
                parts.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
                code = None
            else:
                code.append(line)
            continue
        numbered = re.match(r'^\d+\. (.*)$', line)
        current = 'ul' if line.startswith('- ') else 'ol' if numbered else None
        if listing != current:
            flush_paragraph()
            if listing:
                parts.append(f'</{listing}>')
            if current:
                parts.append(f'<{current}>')
            listing = current
        if line.startswith('```'):
            flush_paragraph()
            code = []
        elif current:
            parts.append('<li>' + inline(numbered[1] if numbered else line[2:]) + '</li>')
        elif line.startswith('#'):
            flush_paragraph()
            heading = re.match(r'^(#{1,6}) (.*)$', line)
            if not heading:
                raise ValueError('README 标题格式无效')
            level = len(heading[1])
            parts.append(f'<h{level}>' + inline(heading[2]) + f'</h{level}>')
        elif not line.strip():
            flush_paragraph()
        else:
            paragraph.append(line.strip())
    flush_paragraph()
    if listing:
        parts.append(f'</{listing}>')
    if code is not None:
        raise ValueError('README 代码块未闭合')
    title = html.escape(titles[0])
    return f'''<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} 使用说明</title>
<style>
body {{ margin:0; color:#222; background:#fafaf8; font:16px/1.8 system-ui,"Microsoft YaHei","PingFang SC",sans-serif; }}
main {{ max-width:760px; margin:auto; padding:32px 24px 64px; }}
h1 {{ font-size:28px; line-height:1.3; }}
h2 {{ font-size:20px; margin-top:32px; border-top:1px solid #ddd; padding-top:20px; }}
li {{ margin:6px 0; }} p,li,code,a {{ overflow-wrap:anywhere; }}
code {{ font-family:ui-monospace,Consolas,monospace; font-size:.95em; }}
pre {{ padding:16px; overflow:auto; background:#eee; border-radius:6px; }}
@media print {{ body {{ background:white; }} main {{ padding:0; }} }}
</style></head><body><main>{''.join(parts)}</main></body></html>
'''
