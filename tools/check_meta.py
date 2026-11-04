# -*- coding: utf-8 -*-
"""本库数据两处口径自查

① meta（顶部 KPI）与列表（items/chunks）必须逐项对得上；
② meta.bizTop 的标签必须在**当前 index.html 前端**都有定义，否则用户看到乱码式中文。

历史坑：
  · withAmt 483（按 merged 全量）vs 列表 460（过完 judge 过滤）→ 差 23 条带金额被剔除；
  · bizTop 用的是 build_web 老分类名（能源清洁高效利用）而列表是 sg 短码
    （cogen/sewage…），同一个页面两套词表。
"""
import json
import os
import re
import sys

SITE = '/workspace/biz-radar'


def load_js(p):
    s = open(p, encoding='utf-8').read()
    return json.loads(s[s.index('=') + 1:].rstrip().rstrip(';'))


def main():
    core = load_js(os.path.join(SITE, 'data.core.js'))
    m = core['meta']
    C = {}
    for fn in ('data.items.js', 'data.chunk-rest.js', 'data.chunk-lead.js'):
        J = load_js(os.path.join(SITE, fn))
        for k, v in J['cols'].items():
            C.setdefault(k, []).extend(v)
    n = len(C['t'])
    bad = []

    def chk(label, a, b):
        flag = 'OK ' if a == b else '❌ '
        if a != b:
            bad.append(label)
        print('%s%-16s meta=%s  列表=%s' % (flag, label, a, b))

    chk('total', m['total'], n)
    chk('withAmt', m['withAmt'], sum(1 for i in range(n) if C['amt'][i]))
    chk('withWin', m['withWin'], sum(1 for i in range(n) if C['win'][i]))
    s_list = round(sum(x for x in C['amt'] if x), 1)
    chk('amtSum(亿)', m['amtSum'], s_list)

    # 地区/状态分布也对一下
    from collections import Counter
    for key, col in (('rgTop', 'rg'), ('stTop', 'st')):
        got = dict((k, v) for k, v in m.get(key, []))
        want = Counter(C[col])
        diff = {k: (got.get(k, 0), want.get(k, 0)) for k in set(got) | set(want)
                if got.get(k, 0) != want.get(k, 0)}
        if diff:
            bad.append(key)
            print('❌ %-15s 不一致 %s' % (key, list(diff.items())[:5]))
        else:
            print('OK %-15s %d 个分组一致' % (key, len(want)))

    # bizTop 标签必须在前端 SEG_NAME 里
    html = open(os.path.join(SITE, 'index.html'), encoding='utf-8').read()
    blk = re.search(r'var SEG_NAME\s*=\s*\{(.*?)\};', html, re.S)
    names = set(re.findall(r"[A-Za-z]+:'([^']+)'", blk.group(1))) if blk else set()
    labels = [k for k, _ in m.get('bizTop', [])]
    miss = [x for x in labels if x not in names]
    if miss:
        bad.append('bizTop 标签')
        print('❌ bizTop 标签前端无定义: %s' % miss)
        print('   前端可选名: %s' % sorted(names))
    else:
        print('OK bizTop 标签 %d 个均在前端词表内' % len(labels))

    print()
    if bad:
        print('结论：仍有 %d 处不一致 → %s' % (len(bad), bad))
        sys.exit(1)
    print('结论：全部一致 ✅')


if __name__ == '__main__':
    main()
