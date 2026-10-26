# -*- coding: utf-8 -*-
"""
把「中标结果公告全文扫描」的反向索引（award_index.json）并进业绩库
（rival_perf.json）—— 2026-10-26 新增。

为什么需要这一步：
  crawl_rival_perf.py 是「先有人名、再去搜」；scan_awards.py 是「先看公告、读出人名」。
  两条路互补，但结果必须合到同一个库里，前端才只需读一份数据。

合并规则（宁缺勿滥，不猜）：
  · 只合进**库里已经有的单位**（含同集团词根匹配），以及索引里出现 ≥3 次的高频单位
    —— 否则 940 家单位全塞进去，库里 200 家的画像会被一堆陌生名字撑爆，反而更难用。
  · 同一份公告去重：按 (日期 + 标题前 60 字) 判重，两条通道都抓到的只留一条，
    并把来源标成 scan（正文读出的，字段更全，带业主和中标价）。
  · 金额统一按「元→亿」换算：扫描器已换算好，这里只做二次校验。
  · owner 字段是这次新增的：正文里读到「建设单位名称」，比标题猜的准。

用法：
  python3 merge_awards.py               # 合并
  python3 merge_awards.py --min-hit 2   # 低频单位门槛（默认 3）
  python3 merge_awards.py --dry         # 只看会新增多少条
"""
import argparse
import gzip
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
PERF = os.path.join(RAW, 'rival_perf.json')
AIDX = os.path.join(RAW, 'award_index.json')


# ─── 单位名词根（与前端 index.html 里的 rpRoot / rpSameGroup 保持同一套规则）───
_TAIL = re.compile(r'(股份有限公司|有限责任公司|有限公司|股份公司|集团公司|集团|公司|'
                   r'研究院|设计院|工程局|工程公司|总局|总公司|分公司|厂|院)$')
_PLACE = re.compile(r'^(?:中国|江苏|浙江|上海|安徽|无锡|南京|苏州|常州|南通|扬州|泰州|镇江|盐城|'
                    r'淮安|连云港|宿迁|徐州|杭州|宁波|温州|绍兴|嘉兴|湖州|金华|台州|合肥|芜湖|'
                    r'马鞍山|蚌埠|安庆|铜陵|池州|宣城|滁州|宿州|六安|亳州|淮南|淮北|黄山|阜阳)'
                    r'(?:市|省|自治区)?')


def root(n):
    s = re.sub(r'[（(][^）)]*[）)]', '', str(n or '')).replace(' ', '').replace('　', '')
    for _ in range(6):
        t = _TAIL.sub('', s)
        if t == s:
            break
        s = t
    return s


def stem(s):
    t = _PLACE.sub('', s)
    return t if len(t) >= 4 else s


def same_group(a, b):
    sa, sb = stem(a), stem(b)
    if sa == sb and len(sa) >= 4:
        return True
    if len(sa) >= 4 and len(sb) >= 4 and (sa.startswith(sb) or sb.startswith(sa)):
        return True
    # 公共前缀
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    c = a[:i]
    return len(c) >= 4 and len(c) >= min(len(a), len(b)) * 0.6


# 本行赛道词：热电、环保、能源、电力、节能、锅炉、燃机、设计院/研究院（设计院是 EPC 主力）
SECTOR_WORDS = ('热电', '热力', '环保', '能源', '电力', '节能', '锅炉', '燃机', '燃气',
                '新能源', '环境', '生态', '水务', 'water', '设计院', '设计研究院',
                '电力设计', '勘测设计', '工程院', '电力工程', '能源建设',
                '电建', '能建', '中冶', '中电', '华电', '国电', '大唐', '华能',
                '国家电投', '三峡', '中广核', '中核', '光大', '绿色动力')


def load_any(p):
    if os.path.exists(p + '.gz'):
        return json.load(gzip.open(p + '.gz', 'rt', encoding='utf-8'))
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return {}


def dump_any(p, obj):
    """仓库里只存 .gz（85MB→11.5MB），本地两种都兼容"""
    if os.path.exists(p + '.gz'):
        with gzip.open(p + '.gz', 'wt', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
        return p + '.gz'
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-hit', type=int, default=3,
                    help='索引里出现多少次以上的陌生单位才建库（默认 3）')
    ap.add_argument('--sector-only', action='store_true', default=True,
                    help='只收名字命中本行赛道的单位（默认开）')
    ap.add_argument('--all-sectors', dest='sector_only', action='store_false')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    perf = load_any(PERF)
    db = perf.get('db') or {}
    aidx = load_any(AIDX).get('records') or {}
    if not aidx:
        print('❌ 没有 award_index.json，先跑 scan_awards.py')
        return 1
    print('业绩库 %d 家 · 中标索引 %d 条' % (len(db), len(aidx)))

    # 索引按「中标单位」聚类
    by_win = {}
    for r in aidx.values():
        w = (r.get('win') or '').strip()
        if not w:
            continue
        by_win.setdefault(w, []).append(r)
    print('索引涉及 %d 家单位' % len(by_win))

    # 决定哪些索引单位要建/合进库
    db_roots = {k: root(k) for k in db}
    target = {}          # db 名 → [idx 记录]
    new_units = {}       # 新建的库条目
    for w, recs in by_win.items():
        # ⚠ 门槛不能一刀切：华光环保能源（西安）在索引里只有 2 条（洪泽 EPC 6.22 亿
        #   就是其中之一），按 min_hit=3 会被直接丢掉 —— 这正是用户要的那条。
        #   所以：命中本行赛道词的单位，1 条也收；其余按 min_hit 卡。
        sec = any(x in w for x in SECTOR_WORDS)
        floor = 2 if sec else a.min_hit      # 本行 2 条起收，其余 3 条起
        if len(recs) < floor:
            continue
        hit = None
        for k, rk in db_roots.items():
            if k == w or same_group(rk, root(w)):
                hit = k
                break
        if hit:
            target.setdefault(hit, []).extend(recs)
        else:
            new_units[w] = recs

    if a.sector_only:
        # 只给「跟我们同行」的单位建档案。
        # 实测痛点：2024-11 一个月的索引里频次最高的是「中亿丰建设集团」「江苏华盛工程咨询」
        # 这类市政/监理单位（34 次、33 次），全收进来会把库里 200 家热电对手淹没 ——
        # 用户要的是「谁在跟我抢热电项目」，不是一份市政施工企业名录。
        drop = [k for k in new_units if not any(w in k for w in SECTOR_WORDS)]
        for k in drop:
            new_units.pop(k, None)
        print('赛道过滤：丢掉 %d 家非本行单位，保留 %d 家' % (len(drop), len(new_units)))

    print('可合并进已有单位 %d 家，新建单位 %d 家' % (len(target), len(new_units)))

    def rec_key(x):
        return (x.get('d') or '') + '|' + re.sub(r'\s+', '', x.get('t') or '')[:60]

    added = 0
    for name, recs in list(target.items()) + list(new_units.items()):
        ent = db.get(name)
        if not ent:
            ent = db[name] = {'kind': 'rival', 'kw': root(name)[:10], 'n': 0, 'items': []}
        items = ent.get('items') or []
        have = {rec_key(x) for x in items}
        for r in recs:
            t = r.get('t') or ''
            d = r.get('d') or ''
            k = d + '|' + re.sub(r'\s+', '', t)[:60]
            if k in have:
                # 已有这条：只用扫描到的更全字段补齐（业主 / 中标价），不覆盖标题
                for x in items:
                    if rec_key(x) == k:
                        if r.get('owner') and not x.get('owner'):
                            x['owner'] = r['owner']
                        if (r.get('amt') or 0) > 0 and not (x.get('amt') or 0):
                            x['amt'] = round(float(r['amt']) * 1e8, 2)   # 库里 amt 单位是元
                        x['src'] = x.get('src') or 'scan'
                        break
                continue
            items.append({
                't': t, 'd': d, 'rg': r.get('city') or '', 'p': '中标结果公告扫描',
                'url': r.get('url') or '',
                'amt': round(float(r.get('amt') or 0) * 1e8, 2),   # 元
                'owner': r.get('owner') or '',
                'win': name,
                'src': 'scan',
            })
            have.add(k)
            added += 1
        items.sort(key=lambda x: x.get('d') or '', reverse=True)
        ent['items'] = items[:300]
        ent['n'] = len(ent['items'])

    print('新增 %d 条业绩，库内共 %d 家单位' % (added, len(db)))
    if a.dry:
        print('（--dry，不落盘）')
        return 0
    perf['db'] = db
    perf['updated'] = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
    p = dump_any(PERF, perf)
    print('✅ 已写回 %s' % p)

    # 抽查：华光
    for k in db:
        if '华光' in k:
            print('  · %s：%d 条' % (k, len(db[k].get('items') or [])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
