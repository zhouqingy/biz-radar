#!/usr/bin/env python3
"""对 rival_perf.json 里 0 命中的单位，用更短关键词逐级重试。
级别：core_name 原词 → 截 6 字 → 截 4 字。首个非 0 命中即采用。
更新 db[kind] 和 done[kw]，并回写文件。"""
import json, os, sys, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_rival_perf import core_name, crawl_one

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw', 'rival_perf.json')
d = json.load(open(RAW, encoding='utf-8'))
db = d['db']

zero = [k for k, v in db.items() if not v.get('n')]
print('0 命中单位：%d 家' % len(zero))
fixed = 0
for name in zero:
    kw0 = core_name(name)
    recs, stat = [], []
    for kw in [kw0, kw0[:6], kw0[:4]]:
        if len(kw) < 4:
            break
        recs, stat = crawl_one(kw, per_site_max=120)
        if recs:
            db[name]['kw'] = kw
            db[name]['n'] = len(recs)
            db[name]['items'] = recs[:200]
            d['done'][name] = kw
            fixed += 1
            print('[fix] %s 用「%s」→ %d 条' % (name, kw, len(recs)))
            break
        time.sleep(0.3)
    else:
        print('[--] %s 仍 0 (%s)' % (name, stat))
    time.sleep(0.3)

tot = sum(v['n'] for v in db.values())
d['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
json.dump(d, open(RAW, 'w', encoding='utf-8'), ensure_ascii=False)
print('✅ 修复 %d 家，现共 %d 家 %d 条' % (fixed, len(db), tot))
