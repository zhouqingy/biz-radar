#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中冶南方都市环保 · 业绩抓取（2026-10-21）
==========================================
目的：不是给都市环保做宣传页，而是**反推"我们到底能干哪些活"的真实业务边界**。

用户原话：「你可以读取中冶南方都市环保的业绩情况来判断参考」。
之前的业务分类是我从公司名「都市环保」瞎推的（列了土壤修复、废水零排、市政污水
当主线），用户纠正说那些是分公司业务、不是主战场。所以必须以实际中过的标为准。

数据源（已实测可直连，无需登录）：
  https://www.ccepc.com/ccepccn/aEnergy.html        热电 + 煤气发电，316 行
  https://www.ccepc.com/ccepccn/aEnvironment.html   环境修复，68 行
  https://www.ccepc.com/ccepccn/swastesolid.html    固废处理，85 行

产出：
  raw/ccepc_perf.json
    {
      "统计时间": ...,
      "分类": {"煤气发电": [...], "热电联产": [...], ...},
      "细分词频": {...},        ← 这张表最关键：真实业务边界
      "区域分布": {...},
      "年份趋势": {...}
    }
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(RAW, 'cepcp_perf.json')

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
}

PAGES = [
    ('aEnergy.html', '能源'),
    ('aEnvironment.html', '环境修复'),
    ('swastesolid.html', '固废'),
]


def clean(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'[\s\u3000]+', ' ', s).strip()


def parse_table(html):
    """把页面里所有 table 拆成 [[cell,...],...]，跳过标题行（只有 1 个 cell 的）"""
    rows = []
    for t in re.findall(r'<table[\s\S]*?</table>', html, re.I):
        for tr in re.findall(r'<tr[\s\S]*?</tr>', t, re.I):
            cells = [clean(c) for c in re.findall(r'<t[dh][\s\S]*?</t[dh]>', tr, re.I)]
            cells = [c for c in cells if c]
            if len(cells) >= 3:
                rows.append(cells)
    return rows


# ── 业务细分识别 ──────────────────────────────────────────────────────
# 这张表是「业务边界判定的核心」。每一条都是从项目名称里抽的关键词，
# 用来回答：这家公司到底在干什么活？哪些是主业、哪些只是顺手做？
#
# 注意：这里**不是**我们自己的分类，而是从 469 条真实业绩里跑出来的词频。
# 跑完再回头看哪些该进主业、哪些该降级，比拍脑袋准。
SEGMENTS = [
    # (标签, 正则, 归属大类)
    ('煤气发电',   r'煤气(资源)?(综合)?(利用|发电)|高炉煤气|焦炉煤气|转炉煤气|混合煤气', '能源'),
    ('余热发电',   r'余热(余能|余压)?(利用)?(发电)?|余热锅炉|烟气余热', '能源'),
    ('干熄焦',     r'干熄焦|CDQ', '能源'),
    ('烧结余热',   r'烧结(机)?(余热|烟气|环冷)', '能源'),
    ('超高温亚临界', r'超高温亚临界', '能源'),
    ('超临界',     r'(?<!超高温)超临界', '能源'),
    ('高温超高压', r'高温超高压|超高温超高压', '能源'),
    ('热电联产',   r'热电联产|热电厂|供热(电站|机组|工程)?|背压', '能源'),
    ('自备电厂',   r'自备(电)?厂|能源站|动力站', '能源'),
    ('生物质发电', r'生物质', '能源'),
    ('垃圾焚烧发电', r'垃圾(焚烧)?(发电|电厂)|焚烧发电', '固废'),
    ('脱硫脱硝',   r'脱硫|脱硝|烟气(治理|净化)|超低排放', '废气'),
    ('烧结烟气',   r'烧结(机)?烟气', '废气'),
    ('污水/废水',  r'污水|废水|中水|水处理', '水务'),
    ('土壤/场地修复', r'土壤|场地修复|修复', '环境修复'),
    ('固废/危废',  r'固废|危废|污泥|飞灰', '固废'),
    ('转底炉',     r'转底炉', '固废'),
    ('EPC总承包',  r'EPC|总承包|交钥匙', '承包方式'),
    ('设计',       r'设计', '承包方式'),
    ('设备供货',   r'设备(供货|采购)|供货', '承包方式'),
    ('运营/BOT',   r'运营|BOT|BOO|TOT|特许经营', '承包方式'),
]
SEG_COMPILED = [(t, re.compile(p), c) for t, p, c in SEGMENTS]

RG_RE = re.compile(r'^(江苏|浙江|上海|安徽|山东|河北|河南|山西|陕西|辽宁|吉林|黑龙江|'
                   r'内蒙古|新疆|甘肃|宁夏|青海|西藏|四川|云南|贵州|广西|广东|福建|'
                   r'江西|湖南|湖北|海南|天津|北京|重庆|海外)')


def main():
    all_rows = []
    for fn, cat in PAGES:
        url = 'https://www.ccepc.com/ccepccn/' + fn
        try:
            r = requests.get(url, headers=H, timeout=30)
            r.encoding = r.apparent_encoding or 'utf-8'
            if r.status_code != 200:
                print('  ✗ %s HTTP %d' % (fn, r.status_code))
                continue
            rows = parse_table(r.text)
            for row in rows:
                all_rows.append({'页': cat, '源': fn, '格': row})
            print('  ✓ %-22s %4d 行' % (fn, len(rows)))
        except Exception as e:
            print('  ✗ %s %s' % (fn, e))

    # 过滤表头行：第一格是「序号」或「项目名称」
    data = []
    for it in all_rows:
        c = it['格']
        if c[0] in ('序号', '') or c[1] == '项目名称':
            continue
        if not re.match(r'^\d+$', c[0]):
            continue
        data.append(it)

    print('\n有效业绩 %d 条' % len(data))

    seg_cnt = Counter()
    seg_years = defaultdict(Counter)
    rg_cnt = Counter()
    year_cnt = Counter()
    seg_examples = defaultdict(list)

    for it in data:
        c = it['格']
        text = ' '.join(c)
        # 项目名一般在第 2 格
        proj = c[1] if len(c) > 1 else ''
        year = ''
        rg = ''
        for cell in c:
            if re.match(r'^(19|20)\d{2}$', cell):
                year = cell
            m = RG_RE.match(cell)
            if m and not rg:
                rg = m.group(1)
        if rg:
            rg_cnt[rg] += 1
        if year:
            year_cnt[year] += 1

        hit = []
        for tag, pat, cat in SEG_COMPILED:
            if pat.search(text):
                seg_cnt[tag] += 1
                hit.append(tag)
                if year:
                    seg_years[tag][year] += 1
                if len(seg_examples[tag]) < 3:
                    seg_examples[tag].append({'项目': proj[:70], '年': year, '地': rg})

    print('\n── 业务细分词频（这决定我们的主业边界）──')
    for tag, n in seg_cnt.most_common():
        print('  %-14s %4d 条  (%.1f%%)' % (tag, n, n * 100.0 / max(1, len(data))))

    print('\n── 区域分布 ──')
    for k, n in rg_cnt.most_common(12):
        print('  %-6s %3d' % (k, n))

    print('\n── 年份分布 ──')
    for k in sorted(year_cnt):
        print('  %s  %3d' % (k, year_cnt[k]))

    os.makedirs(RAW, exist_ok=True)
    out = {
        '统计时间': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
        '来源': 'https://www.ccepc.com/ccepccn/',
        '总条数': len(data),
        '细分词频': dict(seg_cnt.most_common()),
        '区域分布': dict(rg_cnt.most_common()),
        '年份分布': dict(sorted(year_cnt.items())),
        '细分年份': {k: dict(v) for k, v in seg_years.items()},
        '例': dict(seg_examples),
        '明细': [{'页': it['页'], '格': it['格']} for it in data],
    }
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n✅ %s  %.0f KB' % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == '__main__':
    main()
