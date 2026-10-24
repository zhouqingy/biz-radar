#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把站点打包成一个可以双击打开的 HTML（2026-10-21）

为什么要这个：
  `python3 -m http.server` 跑在沙箱里，用户在自己电脑上开 127.0.0.1 当然连不上——
  那是他自己机器的回环地址。要么给公网地址（但用户要求先本地验证），
  要么就给一个不依赖服务器的单文件。

  这个脚本把 index.html 里所有 <script src=...> 直接内联，产出单文件。
  双击就能跑，没有跨域、没有 fetch、没有服务器。

注意：
  体积会偏大（数据全塞进去）。本地文件不经过网络，双击打开也是秒开，可以接受。
"""
import os, re

OUT = '/workspace/biz-radar'
SRC = os.path.join(OUT, 'index.html')
DST = '/workspace/商机雷达-本地预览.html'

# 内联顺序：数据 → 启动器（主脚本已在 html 里，不能动）
INLINE = ['data.core.js', 'data.items.js', 'data.chunk-lead.js', 'data.chunk-rest.js',
          'data.org.js', 'data.graph.js', 'data.news.js', 'boot.js']

html = open(SRC, encoding='utf-8').read()


def read(fn):
    p = os.path.join(OUT, fn)
    if not os.path.exists(p):
        print('  跳过（不存在）', fn)
        return ''
    s = open(p, encoding='utf-8').read()
    # 内联脚本里如果出现 </script> 会提前闭合标签，必须转义
    return s.replace('</script', '<\\/script')


# 1) 把所有外链脚本换成内联
for fn in INLINE:
    body = read(fn)
    if not body:
        continue
    pat = re.compile(r'<script[^>]*src="' + re.escape(fn) + r'[^"]*"[^>]*>\s*</script>')
    if not pat.search(html):
        print('  ⚠ 没找到引用：', fn)
        continue
    html = pat.sub(lambda m: '<script>\n/* ==== ' + fn + ' ==== */\n' + body + '\n</script>',
                   html, count=1)
    print('  内联 %-22s %6.0f KB' % (fn, len(body.encode()) / 1024))

# 2) rival.js（竞对画像抽屉）有就内联
body = read('rival.js')
if body:
    pat = re.compile(r'<script[^>]*src="rival\.js[^"]*"[^>]*>\s*</script>')
    if pat.search(html):
        html = pat.sub(lambda m: '<script>\n/* ==== rival.js ==== */\n' + body + '\n</script>',
                       html, count=1)

# 2.5) 按需加载的模块（org / news / graph）和分块（chunk-lead / chunk-rest）
#      在 HTML 里没有 <script> 标签——它们是运行时 document.createElement 拉进来的。
#      本地单文件没有服务器，拉不到，所以直接注入成全局变量，让 need()/loadChunk()
#      第一行就命中缓存（need 检查 window['DATA_'+mod.toUpperCase()]）。
MODS = [('data.org.js', 'DATA_ORG'),
        ('data.news.js', 'DATA_NEWS'),
        ('data.graph.js', 'DATA_GRAPH'),
        # 四库信用代码：进深度档案才用，和 graph 一批预注入
        ('data.siku.js', 'DATA_SIKU'),
        # 分块：两个都改名成 DATA_CHUNK，由 loadChunk 依次消费
        ('data.chunk-lead.js', 'DATA_CHUNK'),
        ('data.chunk-rest.js', 'DATA_CHUNK')]
inject = []
for fn, gvar in MODS:
    p2 = os.path.join(OUT, fn)
    if not os.path.exists(p2):
        continue
    raw = open(p2, encoding='utf-8').read().replace('</script', '<\\/script')
    # 原文件是 window.DATA_XXX = {...};  分块两个文件同名，要变成队列
    if gvar == 'DATA_CHUNK':
        inject.append('<script>window.__CHUNKS__=window.__CHUNKS__||[];'
                      'window.DATA_CHUNK=null;' + raw + ';'
                      'if(window.DATA_CHUNK)window.__CHUNKS__.push(window.DATA_CHUNK);'
                      'window.DATA_CHUNK=null;</script>')
    else:
        inject.append('<script>' + raw + '</script>')
    print('  预注入 %-22s %6.0f KB' % (fn, len(raw.encode()) / 1024))

html = html.replace('</head>', '\n'.join(inject) + '\n</head>', 1)

# 3) 删掉残留的本地外链脚本（防遗漏导致本地 404 白屏）
left = set(re.findall(r'<script[^>]*src="(?!http)([^"?]+)[^"]*"', html))
if left:
    print('  ⚠ 仍有外链脚本未内联：', left)
    for fn in left:
        html = re.sub(r'<script[^>]*src="' + re.escape(fn) + r'[^"]*"[^>]*>\s*</script>', '', html)

# 4) 顶部加一条「本地预览」提示条，避免和线上版混淆
banner = ('<div style="background:#fff8ee;border-bottom:1px solid #f7e2c4;padding:7px 16px;'
          "font:600 12.5px/1.6 -apple-system,'Microsoft YaHei',sans-serif;color:#a8620a\">"
          '本地预览版 · 与线上功能一致，数据已全部内联，双击即可打开</div>')
html = re.sub(r'(<body[^>]*>)', lambda m: m.group(1) + banner, html, count=1)

open(DST, 'w', encoding='utf-8').write(html)
print('\n✅ %s  %.1f MB' % (DST, os.path.getsize(DST) / 1024 / 1024))
