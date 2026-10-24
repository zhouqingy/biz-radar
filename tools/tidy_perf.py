#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 perf_3in1.json 清洗成画像可用的干净数据集。

做三件事：
 1) 同一单位同一项目跨多篇公示重复抓取的，只留金额最大的那条（可研/初设/施工图算同一项目）
 2) 项目名全半角、破折号差异归一后再比对
 3) 给每条打 core 标记（是否属热电主赛道），供前端区分主业/副业

输出：raw/perf_clean.json
用法：/usr/bin/python3 tidy_perf.py
"""
import json
import os
import re
import sys
import time

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
SRC = os.path.join(RAW, 'perf_3in1.json')
OUT = os.path.join(RAW, 'perf_clean.json')

CORE_TRACKS = ('热电联产', '集中供热/热网', '污泥/固废处置',
               '生活垃圾焚烧', '煤气/余热利用', '燃煤/煤电', '脱硫脱硝')


def track_of(p):
    if re.search(r'特高压|换流站|变电站|千伏|kV|KV|输变电|输电线路|电网', p):
        return '电网/输变电'
    if re.search(r'LNG|液化天然气|取排水', p):
        return 'LNG/水工'
    if re.search(r'污泥|固废', p):
        return '污泥/固废处置'
    if re.search(r'垃圾', p):
        return '生活垃圾焚烧'
    if re.search(r'热电联产|背压|热电厂|热电', p):
        return '热电联产'
    if re.search(r'集中供热|供热|热网|蒸汽|动力岛', p):
        return '集中供热/热网'
    if re.search(r'煤气|余热|干熄焦', p):
        return '煤气/余热利用'
    if re.search(r'电厂|发电|燃煤|煤电|煤炭|超超临界', p):
        return '燃煤/煤电'
    if re.search(r'脱硫|脱硝|烟气', p):
        return '脱硫脱硝'
    if re.search(r'光伏|风电|储能|新能源|智慧能源', p):
        return '新能源/其他'
    return '其他（园区/建筑设计）'


# 阶段后缀：可研 / 初设 / 施工图 属同一项目，判重时剥掉
STAGE = re.compile(r'(可行性研究(报告)?(及[^，。;；]*)?|初步设计(服务)?|施工图设计|'
                   r'勘察、?设计(及[^，。;；]*)?(相关服务)?|勘察设计(技术服务)?|'
                   r'勘测设计|设计技术服务|设计服务|工程设计|设计项目|设计|'
                   r'EPC(总承包)?|工程总承包|总承包)$')


def norm_proj(s):
    """项目名归一：全半角、破折号、括号、空白全去掉，再剥尾部阶段词。"""
    s = s or ''
    s = s.replace('（', '(').replace('）', ')')
    s = re.sub(r'[\-—－–~～±\s、,，。;；:：]', '', s)
    s = s.replace('(', '').replace(')', '')
    prev = None
    while prev != s:
        prev = s
        s = STAGE.sub('', s)
    return s


def bad(v):
    """解析器有时把空缺写成字符串 'null' / 'None' / '-'，统一当空值。"""
    if v is None:
        return True
    s = str(v).strip()
    return s == '' or s.lower() in ('null', 'none', 'nan', 'undefined', '-', '--')


def main():
    if not os.path.exists(SRC):
        sys.exit('找不到 %s' % SRC)
    d = json.load(open(SRC, encoding='utf-8'))
    items = d['items']

    # ---- 先修字符串 'null' 之类的脏值 ----
    fixed = 0
    for x in items:
        for k in ('owner', 'date', 'proj', 'amt_txt', 'doc', 'docdate', 'track'):
            if k in x and bad(x[k]):
                if x[k] not in (None, ''):
                    fixed += 1
                x[k] = ''
        if bad(x.get('date')) and not bad(x.get('docdate')):
            x['date'] = x['docdate']   # 用公示发布日期兜底，并在前端标注
            x['date_est'] = True
    if fixed:
        print('修正脏值 %d 处（"null" 字符串等）' % fixed)

    # ---- 去重：同单位 + 同归一项目名，保留金额最大的一条 ----
    best = {}
    dropped = []
    for x in items:
        key = (x['unit'], norm_proj(x.get('proj', '')))
        old = best.get(key)
        if old is None:
            best[key] = x
            continue
        a_new = x.get('amt') or 0
        a_old = old.get('amt') or 0
        if a_new > a_old:
            best[key] = x
            dropped.append(old)
        else:
            dropped.append(x)

    clean = []
    for x in best.values():
        y = dict(x)
        y['tk'] = track_of(y.get('proj', ''))
        y['core'] = y['tk'] in CORE_TRACKS
        clean.append(y)

    clean.sort(key=lambda z: (z['unit'], -(z.get('amt') or 0)))

    units = {}
    for x in clean:
        u = units.setdefault(x['unit'], {'n': 0, 'amt': 0.0, 'core_n': 0, 'core_amt': 0.0})
        a = x.get('amt') or 0
        u['n'] += 1
        u['amt'] += a
        if x['core']:
            u['core_n'] += 1
            u['core_amt'] += a

    out = {'updated': time.strftime('%Y-%m-%d %H:%M'),
           'source': d.get('docs', []),
           'items': clean}
    for u, s in units.items():
        print('\n%s' % u)
        print('  全部 %-3d 条 · %.2f 亿' % (s['n'], s['amt']))
        print('  热电主赛道 %-3d 条 · %.2f 亿' % (s['core_n'], s['core_amt']))
    print('\n去重前 %d 条 → 去重后 %d 条（合并 %d 条重复）' % (len(items), len(clean), len(dropped)))
    for x in dropped:
        print('   合并掉: %-8s %s' % (x['unit'][-8:], x.get('proj', '')[:56]))

    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n→ %s' % OUT)


if __name__ == '__main__':
    main()
