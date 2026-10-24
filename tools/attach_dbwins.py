#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本库中标记录挂到单位百科（2026-10-23）

用户要求百科「做深、按真实的来」。
最真实的深度就在我们自己抓的公告里：build_graphs.py 聚合的 246 家对手，
每家带逐条中标明细（标题/日期/金额/业主/原文链接/联合体成员）。
把这份明细按名字对到 38 家百科单位上，挂成 db_wins 字段——
不联网、不编造，全是我们自己抓到的一手记录。
画像弹层里新增「本库中标记录」一段，营销能直接看到这家单位最近在哪些业主那里中了什么标。
"""
import json, re, io

RAW = '/workspace/biz-radar-tools/raw'
g = json.load(open(RAW+'/graphs.json', encoding='utf-8'))
enc = json.load(open(RAW+'/units_encyclopedia.json', encoding='utf-8'))

def norm(n):
    n = n or ''
    n = re.sub(r'[（(].*$', '', n)
    n = n.replace('有限责任公司','').replace('股份有限公司','').replace('集团有限公司','')
    n = n.replace('有限公司','').replace('集团','').strip()
    return n

kw2grp = {}
for _g in json.load(open(RAW+'/alias_groups.json', encoding='utf-8'))['groups']:
    for _kw in _g.get('match', []):
        kw2grp.setdefault(_kw, _g['name'])

RIV = g['rivals']

def cands(name):
    """候选搜索词：全称 → 规范名 → 别名表中最长的匹配词 → 去掉行业后缀的核心名"""
    out = [name, norm(name)]
    best = ''
    for kw in kw2grp:
        if kw in name and len(kw) > len(best):
            best = kw
    if best: out.append(best)
    core = re.sub(r'(工程技术|建设集团|工程|设计研究院|研究院|科技|国际工程|集团).*$', '', norm(name))
    if len(core) >= 3: out.append(core)
    return [c for c in out if c and len(c) >= 3]

def find_rival(name):
    for c in cands(name):
        for r in RIV:
            if r['name'] == c: return [r]
    for c in cands(name):
        got = [r for r in RIV if c in r['name'] or (len(r['name']) >= 4 and r['name'] in c)]
        if got: return got
    return []

hit, miss = [], []
for grp in enc['groups']:
    for u in grp.get('units', []):
        rs = find_rival(u['name'])
        if rs:
            its = []
            for r in rs:
                its += (r.get('items') or [])
            its.sort(key=lambda x: (x.get('d') or ''), reverse=True)
            if its:
                u['db_wins'] = [{'t': it['t'], 'd': it.get('d') or '', 'amt': it.get('amt'),
                                 'buyer': it.get('buyer') or '', 'url': it.get('url') or '',
                                 'sub': it.get('sub') or '', 'mates': it.get('mates') or []}
                                for it in its[:10]]
                u['db_n'] = sum(r.get('n', 0) for r in rs)
                # amt 单位是「元」，这里换算成「亿元」（原写成 /1e4，8.5 亿被算成 85540 亿）
                u['db_amt'] = round(sum(r.get('amt') or 0 for r in rs) / 1e8, 2)
                u['db_last'] = (its[0].get('d') or '') if its else ''
                hit.append((grp['id'], u['name'], len(u['db_wins']), u.get('db_amt'), len(rs)))
                continue
        miss.append((grp['id'], u['name']))

json.dump(enc, open(RAW+'/units_encyclopedia.json','w',encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('命中 %d 家（挂了本库中标明细）：' % len(hit))
for h in sorted(hit, key=lambda x:-x[3]):
    print('  %-8s %-34s %2d条明细  本库合计 %7.2f亿  合并了%d个投标主体' % h)
print('\n未命中 %d 家：' % len(miss))
for m in miss: print('  %-8s %s' % m)
