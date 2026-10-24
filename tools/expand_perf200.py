#!/usr/bin/env python3
"""对手/业主库扩容 80 → TOP200（2026-10-24，用户确认全做）
数据不用重爬：graphs.json 的 rivals/owners 每家已聚合好 items（来自 merged 全库
打标聚合）。本脚本做三件事：
  1) 名字清洗：剥括号注释、拆「A、B」并联名、去「人民政府」后缀重复档
  2) 按 amtW(万元) 排序取 TOP200（现有 80 家保留，补 120 家）
  3) 写入 rival_perf.json db（kind=owner/rival，items 带 t/d/rg/p/url/win/amt）
p 字段用「四省平台聚合」，与爬虫采集的条目区分。
"""
import json, re, os

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
BAD_T = ('转让', '挂牌', '竞价', '拍卖', '竞买', '产权交易', '报废处置',
         '车辆', '废旧物资', '物资处置')


def clean_name(s):
    s = re.sub(r'（[^）]*）|\([^)]*\)', '', s or '').strip()
    return s


def norm_key(s):
    s = clean_name(s)
    s = re.sub(r'(人民政府|有限公司|股份|集团)$', '', s)
    return s


def main():
    g = json.load(open(os.path.join(RAW, 'graphs.json')))
    rp = json.load(open(os.path.join(RAW, 'rival_perf.json')))
    db = rp.get('db') or {}
    known_norms = {norm_key(k) for k in db}

    pool = []   # (score, n, amtW, kind, name, items)
    for kind, arr in (('rival', g.get('rivals') or []), ('owner', g.get('owners') or [])):
        for u in arr:
            nm = clean_name(u.get('name') or '')
            # 并联名拆分（「A公司、B公司」这种聚合脏数据）
            parts = [nm] if '、' not in nm else [p.strip() for p in nm.split('、') if len(p.strip()) >= 6]
            for p in parts:
                if len(p) < 5:
                    continue
                nk = norm_key(p)
                if not nk or nk in known_norms:
                    continue
                # items 清洗：脏标题剔除，字段裁剪
                its = []
                for it in (u.get('items') or []):
                    t = it.get('t') or ''
                    if any(b in t[:30] for b in BAD_T):
                        continue
                    its.append({'t': t, 'd': it.get('d') or '', 'rg': it.get('rg') or '',
                                'p': '四省平台聚合', 'url': it.get('url') or '',
                                'win': it.get('win') or '', 'amt': it.get('amt') or 0})
                if not its:
                    continue
                pool.append((u.get('amtW') or 0, u.get('n') or 0, kind, p, its))

    # 去重（同名不同档）
    seen = set()
    dedup = []
    for amtW, n, kind, p, its in sorted(pool, key=lambda x: -x[0]):
        nk = norm_key(p)
        if nk in seen:
            continue
        seen.add(nk)
        dedup.append((amtW, n, kind, p, its))
    target = 200 - len(db)
    add = dedup[:target]
    print('候选池 %d（去重后），补 %d 家至 %d' % (len(dedup), len(add), len(db) + len(add)))
    for amtW, n, kind, p, its in add:
        db[p] = {'kind': kind, 'kw': p, 'n': len(its), 'items': its}
    rp['db'] = db
    rp['expanded'] = '2026-10-24 TOP200（graphs.json 聚合扩容）'
    json.dump(rp, open(os.path.join(RAW, 'rival_perf.json'), 'w'), ensure_ascii=False)
    print('完成，db %d 家' % len(db))


if __name__ == '__main__':
    main()
