#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环评/核准公示采集 · 江苏+安徽（2026-11-25 §5.107 用户拍板新增）

为什么做
────────────────────────────────────────────────────────────────────────
岚泽大丰港配套动力站案例：①库只抓到了发改委规划公示（2026-07-09），
而「环评受理公示」（2026-10-27，盐城生态环境局）这类**核准前最后一关**
完全不在采集范围——环评受理=项目实质推进的强信号，比规划公示确定性强。
用户 2026-11-25 拍板：补江苏+安徽两省，写进要求，自动更新。

三个源（全部实测可用 2026-11-25）
────────────────────────────────────────────────────────────────────────
  A 安徽生态环境厅环评审批列表（大汉 CMS /site/label/8888 接口，需 session
    先访问页面拿 cookie + labelName=publicInfoList&siteId=6788031&organId=21691）
  B 江苏环保公众网 jshbgz.cn/hpgs/（全省环评公示聚合，含地市项目，静态表）
  C 江苏省生态环境厅行政审批 col83551（省厅审批的报告书大项目）

判定口径
────────────────────────────────────────────────────────────────────────
  · 标题必须含能源关键词（锅炉/热电/生物质/余热/燃气发电/自备/焚烧发电/
    垃圾发电/供热/焦炉/高炉/冶炼/电解铝/氧化铝）——环评公示全行业都有，
    不筛会灌进大量化工/公路/医疗噪音
  · 落 merged.json，st='环评受理公示'，走 build_data 统一过 judge()
  · 不新增业务词表，进库仍由 biz_rules.judge() 判定

用法
    python3.11 collect_eia.py            # 采集并合并 merged.json
    python3.11 collect_eia.py --dry     # 只看命中
"""
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight import require_briefing
require_briefing('collect_eia.py')

ROOT = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(ROOT, 'merged.json')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
      'Accept-Language': 'zh-CN,zh;q=0.9'}

# 能源关键词（标题预筛；业务判定仍走 biz_rules.judge）
EKW = ('锅炉', '热电', '生物质', '余热', '燃气发电', '自备', '焚烧发电',
       '垃圾发电', '供热', '焦炉', '高炉', '冶炼', '电解铝', '氧化铝',
       '煤气', '发电机组', '热力')


def fetch(url, **kw):
    r = requests.get(url, headers=UA, timeout=25, **kw)
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return r.content.decode(enc)
        except UnicodeDecodeError:
            continue
    return r.content.decode('utf-8', 'ignore')


def clean(t):
    t = re.sub(r'[\s\x3000]+', '', t or '')
    # 《…》受理公示 → 去书名号壳，标题太长截断
    return t[:90]


# ── 源 A：安徽生态环境厅（ajax 接口，session 先拿 cookie）────────────────
def src_ah(max_page=3):
    s = requests.Session()
    s.headers.update(UA)
    ref = ('https://sthjt.ah.gov.cn/public/column/21691'
           '?type=4&catId=32709971&action=list')
    s.get('https://sthjt.ah.gov.cn/', timeout=25)
    s.get(ref, timeout=25)
    out = []
    for pg in range(1, max_page + 1):
        r = s.get('https://sthjt.ah.gov.cn/site/label/8888',
                  params={'labelName': 'publicInfoList', 'siteId': '6788031',
                          'organId': '21691', 'catId': '32709971', 'type': '4',
                          'pageNo': str(pg), 'pageSize': '20', 'isAttach': 'false'},
                  headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': ref},
                  timeout=25)
        frag = r.text
        if '公示' not in frag and '环评' not in frag:
            break
        # 片段结构：<a href=… onmouseover=…>…《标题》受理公示</a> … <li class="rq">11-24</li>
        # （锚点标签与《之间有换行/空格，且标题不在 href 属性上——用「向前找最近 href」策略）
        for m in re.finditer(r'《([^》]{8,120}》[^<]{0,60})</a>(.{0,500}?)<li class="rq">(\d\d-\d\d)</li>',
                             frag, re.S):
            title = m.group(1)
            back = frag[max(0, m.start() - 600):m.start()]
            hm = None
            for hm in re.finditer(r'href="([^"]+)"', back):
                pass
            url = hm.group(1) if hm else ''
            if url.startswith('/'):
                url = 'https://sthjt.ah.gov.cn' + url
            out.append({'t': clean('《' + title), 'url': url,
                        'd': '2026-' + m.group(3), 'p': '安徽省生态环境厅·环评公示'})
        time.sleep(0.4)
    return out


# ── 源 B：江苏环保公众网（全省环评公示聚合）────────────────────────────
def src_js_gz(pages=2):
    out = []
    base = 'http://jshbgz.cn/hpgs/'
    urls = [base] + [base + 'index_%d.html' % i for i in range(2, pages + 1)]
    for u in urls:
        try:
            h = fetch(u)
        except Exception:
            break
        for m in re.finditer(r'<a[^>]+href="(\./20\d\d[^"]+)"[^>]*>(.{0,250}?)</a>',
                             h, re.S):
            url, seg = m.group(1), m.group(2)
            txt = re.sub(r'<[^>]+>', ' ', seg)
            title = txt.split('20')[0].strip()
            dm = re.search(r'(20\d\d-\d\d-\d\d)', txt)
            out.append({'t': clean(title),
                        'url': 'http://jshbgz.cn/hpgs/' + url.lstrip('./'),
                        'd': dm.group(1) if dm else '',
                        'p': '江苏环保公众网·环评公示'})
        time.sleep(0.4)
    return out


# ── 源 C：江苏省生态环境厅行政审批（省厅审批的报告书大项目）──────────────
def src_js_provhall():
    out = []
    h = fetch('https://sthjt.jiangsu.gov.cn/col/col83551/index.html')
    for m in re.finditer(r'<a[^>]+href="([^"]*art/20\d\d[^"]*)"[^>]*(?:title="([^"]{8,120})")?[^>]*>([^<]{8,120})<', h):
        url, t1, t2 = m.group(1), m.group(2) or '', m.group(3)
        title = t1 or t2
        if url.startswith('/'):
            url = 'https://sthjt.jiangsu.gov.cn' + url
        seg = h[m.start():m.start() + 300]
        dm = re.search(r'(20\d\d-\d\d-\d\d)', seg)
        out.append({'t': clean(title), 'url': url,
                    'd': dm.group(1) if dm else '',
                    'p': '江苏省生态环境厅·环评公示'})
    return out


SOURCES = [('安徽省厅环评', src_ah), ('江苏公众网环评', src_js_gz),
           ('江苏省厅环评', src_js_provhall)]


def rg_of(x):
    return '安徽' if 'ah.gov.cn' in x.get('url', '') else '江苏'


def main():
    dry = '--dry' in sys.argv
    cand, stat = [], []
    for name, fn in SOURCES:
        try:
            got = fn()
        except Exception as e:
            print('  ✗ %s：%s' % (name, e))
            got = []
        hit = [x for x in got if any(k in x['t'] for k in EKW)]
        print('%-10s 列表 %3d → 能源相关 %d' % (name, len(got), len(hit)))
        for x in hit[:4]:
            print('   ·', x['d'] or '????-??-??', x['t'][:55])
        stat.append((name, len(got), len(hit)))
        cand.extend(hit)

    # 去重（URL + 标题前 22 字）
    seen, dedup = set(), []
    for x in cand:
        k1, k2 = x['url'], re.sub(r'[\s\W]', '', x['t'])[:22]
        if k1 in seen or k2 in seen:
            continue
        seen.add(k1)
        seen.add(k2)
        dedup.append(x)

    print('\n候选 %d → 入池 %d' % (len(cand), len(dedup)))
    if dry:
        return

    # ⚠ 2026-11-25 修正：merged.json 是 build_data 的**输出**（末尾 json.dump 覆盖），
    # 直接写会被下次构建抹掉。正确入口是 raw/early/*.json（build_data §early 加载，
    # 用 early='环评公示' 渠道标记，业务判定仍走 judge()）。
    early_path = os.path.join(ROOT, 'raw', 'early', 'eia-latest.json')
    old_arr = []
    if os.path.exists(early_path):
        try:
            old_arr = json.load(open(early_path, encoding='utf-8'))
        except Exception:
            old_arr = []
    have = {x.get('url') for x in old_arr}
    tk = {re.sub(r'[\s\W]', '', x.get('t') or '')[:22] for x in old_arr}
    added = 0
    for x in dedup:
        if x['url'] in have or re.sub(r'[\s\W]', '', x['t'])[:22] in tk:
            continue
        old_arr.append({
            't': x['t'], 'rg': rg_of(x), 'early': '环评公示',
            'd': x['d'], 'url': x['url'], 'src': x['p'],
            'snip': '环评受理公示（%s）。环评受理=核准前实质推进信号，距招标/开工近。' % x['p']})
        have.add(x['url'])
        tk.add(re.sub(r'[\s\W]', '', x['t'])[:22])
        added += 1
    json.dump(old_arr, open(early_path, 'w', encoding='utf-8'), ensure_ascii=False)
    print('raw/early/eia-latest.json 新增 %d → 合计 %d 条' % (added, len(old_arr)))


if __name__ == '__main__':
    main()
