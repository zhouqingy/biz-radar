#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并“新增单位”补丁文件到主数据：
  raw/_inbox/new_competitors.json  -> raw/industry.json  .competitors
  raw/_inbox/new_partners.json     -> raw/partners.json
  raw/_inbox/new_overseas_units.json -> 同时进 partners（海外赛道·联合体总包方）
                                        与 competitors（海外赛道·同类竞逐者，dual=true）

用法：
  python3 merge_units.py           # 合并并写回
  python3 merge_units.py --check   # 只预览，不写盘
去重键：单位名称前 6 个汉字（去括号后缀）
"""
import glob, json, os, re, sys, shutil, time

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
INBOX = os.path.join(RAW, '_inbox')

CHECK = '--check' in sys.argv

def load(p, default=None):
    if not os.path.exists(p):
        return default
    return json.load(open(p, encoding='utf-8'))

def save(p, obj):
    if CHECK:
        return
    bak = p + '.bak'
    if os.path.exists(p) and not os.path.exists(bak):
        shutil.copy2(p, bak)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)

# 别名归并：同一家单位的不同写法统一到主条目，避免重复入库（键为挖掘侧清洗后的名字）
ALIAS = {
    '华光环保能源设计研究院有限公司': '无锡华光环保能源集团股份有限公司（含华光环保能源（西安）设计研究院有限公司）',
    '华光环保能源西安设计研究院有限公司': '无锡华光环保能源集团股份有限公司（含华光环保能源（西安）设计研究院有限公司）',
    '华光环保能源（西安）设计研究院有限公司': '无锡华光环保能源集团股份有限公司（含华光环保能源（西安）设计研究院有限公司）',
    '上海锅炉厂有限公司': '上海电气集团股份有限公司（含上海锅炉厂有限公司）',
}

GENERIC = ['股份有限公司', '有限责任公司', '有限公司', '集团', '中国',
           '工程', '建设', '技术', '研究院', '设计', '股份', '(', '）']

def _strip_content(s):
    """循环删掉所有括号及其内容（支持嵌套）——解决“全称（简称）”写法"""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r'[（(][^（()）]*[）)]', '', s)
    return s


def _strip_char(s):
    """只删括号字符、保留内容——解决“公司名（地名）公司名”写法，如 华光环保能源（西安）设计研究院"""
    return s.replace('（', '').replace('）', '').replace('(', '').replace(')', '')


def _core(s):
    s = s.replace(' ', '').replace('　', '')
    core = s
    for g in GENERIC:
        core = core.replace(g, '')
    return core if len(core) >= 4 else s


def key(name):
    """名称指纹：去通用词后的核心串；核心串太短时回退，避免“中国能源建设集团XX”被误判为同一家"""
    import re
    return _core(_strip_content(name or ''))


def keys(name):
    """两个候选指纹：括号内容删掉 / 括号内容保留。任一命中即视为同一家"""
    n = name or ''
    out = []
    for s in (_strip_content(n), _strip_char(n)):
        k = _core(s)
        if k and k not in out:
            out.append(k)
    return out or [n]

def cat_of(x, default='综合类'):
    return (x.get('cat') or '').strip() or default

def norm_recent(x):
    """统一 recent 字段：字符串 -> 保留；列表 -> 每项规范化为 {title,amount,date,region,url}"""
    r = x.get('recent')
    if not r:
        return None
    if isinstance(r, str):
        return r
    if isinstance(r, list):
        out = []
        for it in r:
            if isinstance(it, str):
                out.append({'title': it})
            elif isinstance(it, dict):
                out.append({
                    'title': it.get('title') or it.get('t') or '',
                    'amount': it.get('amount') or it.get('amtTxt') or '',
                    'date': it.get('date') or it.get('d') or '',
                    'region': it.get('region') or '',
                    'url': it.get('url') or '',
                })
        return [o for o in out if o['title']]
    return None

def comp_entry(x, dual=False):
    """转成 competitors 条目：recent 压成字符串（前端 compCard 原渲染字符串）"""
    rc = norm_recent(x)
    if isinstance(rc, list):
        rc = '；'.join(
            (i['title'] + ('（%s）' % i['amount'] if i.get('amount') else '')
             + ('，%s' % i['date'] if i.get('date') else ''))
            for i in rc[:3])
    e = {
        'name': x.get('name'),
        'type': x.get('type') or '',
        'cat': cat_of(x),
        'strength': x.get('strength') or '',
        'recent': rc or '',
        'url': x.get('url') or '',
    }
    if x.get('city'):
        e['city'] = x['city']
    if dual:
        e['dual'] = True
    if x.get('_mine'):
        e['_mine'] = x['_mine']
    return e

def part_entry(x):
    """转成 partners 条目：recent 保持列表"""
    e = dict(x)
    e['cat'] = cat_of(x)
    rc = norm_recent(x)
    if rc is not None:
        e['recent'] = rc if isinstance(rc, list) else [{'title': rc}]
    return e

def merge(target, additions, label, overwrite=False):
    """按指纹去重后追加。
    overwrite=False：已存在时只补全空字段；
    overwrite=True（深度调研档案）：已存在时用新档案整体覆盖内容字段，保留 _mine 标记。"""
    exist = {}
    for i, t in enumerate(target):
        for k in keys(t.get('name', '')):
            exist.setdefault(k, i)
    added, updated, skipped = 0, 0, 0
    for a in additions:
        nm = a.get('name', '')
        if nm in ALIAS:                 # 别名归一：不同写法合并到主条目
            a = dict(a)
            a['name'] = ALIAS[nm]
        ks = keys(a.get('name', ''))
        if not ks or not ks[0]:
            skipped += 1
            continue
        hit = next((exist[k] for k in ks if k in exist), None)
        if hit is not None:
            i = hit
            old = target[i]
            if overwrite:
                keep = {f: old.get(f) for f in ('_mine', 'dual') if old.get(f) is not None}
                old.update({kk: vv for kk, vv in a.items() if vv})
                old.update(keep)
                updated += 1
                continue
            changed = False
            for f in ('cat', 'city', 'type', 'strength', 'role', 'url', 'recent'):
                if not old.get(f) and a.get(f):
                    old[f] = a[f]
                    changed = True
            if changed:
                updated += 1
            else:
                skipped += 1
        else:
            target.append(a)
            for k in ks:
                exist.setdefault(k, len(target) - 1)
            added += 1
    print('  %-10s 新增 %d · %s %d · 跳过(已存在) %d'
          % (label, added, '覆盖' if overwrite else '补全', updated, skipped))
    return added

def dedup_key(r):
    return (r.get('url') or r.get('title') or '')[:80]


def refresh_dynamics(comps, par, refresh):
    """把库内 A/B 级项目里的最新中标，追加进已入库单位的 recent（只动数组型，人工调研的字符串型不碰）。
    返回 (刷新家数, 追加条数)"""
    if not refresh:
        return 0, 0
    # 指纹对齐：挖掘侧的键与库内单位名都过同一个 key() 指纹
    rstd = {}
    for k, v in refresh.items():
        for kk in keys(k):
            rstd.setdefault(kk, v)
    n_unit, n_rec = 0, 0
    for lst in (comps, par):
        for u in lst:
            new_recs = next((rstd[k] for k in keys(u.get('name', '')) if k in rstd), None) or []
            if not new_recs:
                continue
            rc = u.get('recent')
            if isinstance(rc, str) or not rc:
                continue          # 字符串型（人工调研段落）与空值不刷新
            old_keys = {dedup_key(r) for r in rc if isinstance(r, dict)}
            added = 0
            for r in new_recs:
                if dedup_key(r) in old_keys:
                    continue
                rc.append(r)
                old_keys.add(dedup_key(r))
                added += 1
            if added:
                # 按日期倒序，最多留 5 条
                u['recent'] = sorted(rc, key=lambda r: (r.get('date') or '') if isinstance(r, dict) else '',
                                     reverse=True)[:5]
                n_unit += 1
                n_rec += added
    return n_unit, n_rec


def main():
    if not os.path.isdir(INBOX):
        print('[ERR] 没有 %s 目录，无需合并' % INBOX)
        return 1

    ind_path = os.path.join(RAW, 'industry.json')
    par_path = os.path.join(RAW, 'partners.json')

    ind = load(ind_path, {'trends': [], 'competitors': [], 'platforms': []})
    par = load(par_path, [])
    comps = ind.setdefault('competitors', [])

    nc = load(os.path.join(INBOX, 'new_competitors.json'), [])
    np_ = load(os.path.join(INBOX, 'new_partners.json'), [])
    no = load(os.path.join(INBOX, 'new_overseas_units.json'), [])
    mc = load(os.path.join(INBOX, 'mined_competitors.json'), [])
    mp = load(os.path.join(INBOX, 'mined_partners.json'), [])

    print('补丁文件：竞企 %d · 伙伴 %d · 海外赛道 %d' % (len(nc), len(np_), len(no)))
    print('库内挖掘：竞企 %d · 伙伴 %d（来自 A/B 级项目中标记录）' % (len(mc), len(mp)))
    print('合并前  ：竞企 %d · 伙伴 %d' % (len(comps), len(par)))

    merge(comps, [comp_entry(x) for x in nc], '竞企')
    merge(par, [part_entry(x) for x in np_], '伙伴')
    merge(par, [part_entry(x) for x in no], '伙伴·海外')
    merge(comps, [comp_entry(x, dual=True) for x in no], '竞企·海外')
    merge(comps, [comp_entry(x) for x in mc], '竞企·挖掘')
    merge(par, [part_entry(x) for x in mp], '伙伴·挖掘')

    # 深度调研档案：覆盖式更新（写完后移入 processed/ 留档，避免下次重复覆盖人工改动）
    dc = load(os.path.join(INBOX, 'deep_competitors.json'), [])
    dp = load(os.path.join(INBOX, 'deep_partners.json'), [])
    # 薄档案补厚：支持 thin_competitors_*.json / thin_partners_*.json 多批次
    for fn in sorted(glob.glob(os.path.join(INBOX, 'thin_*.json'))):
        base = os.path.basename(fn)
        if 'competitor' in base:
            dc += load(fn, [])
        elif 'partner' in base:
            dp += load(fn, [])
    if dc or dp:
        print('深度/补厚档案：竞企 %d · 伙伴 %d（覆盖式写入）' % (len(dc), len(dp)))
        merge(comps, [comp_entry(x) for x in dc], '竞企·深度', overwrite=True)
        merge(par, [part_entry(x) for x in dp], '伙伴·深度', overwrite=True)
        procd = os.path.join(INBOX, 'processed')
        os.makedirs(procd, exist_ok=True)
        for fn in ('deep_competitors.json', 'deep_partners.json') + \
                  tuple(os.path.basename(f) for f in sorted(glob.glob(os.path.join(INBOX, 'thin_*.json')))):
            src = os.path.join(INBOX, fn)
            if os.path.exists(src):
                dst = os.path.join(procd, '%s.%s.json' % (fn[:-5], time.strftime('%Y%m%d')))
                if not CHECK:
                    shutil.move(src, dst)
                print('  已归档 %s → processed/' % fn)

    mr = load(os.path.join(INBOX, 'refresh_dynamics.json'), {})
    nu, nr = refresh_dynamics(comps, par, mr)
    print('动态刷新：已入库单位追加最新业绩 %d 家 / %d 条（按日期倒序，每家最多留 5 条）' % (nu, nr))

    print('合并后  ：竞企 %d · 伙伴 %d' % (len(comps), len(par)))
    # 输出薄档案队列：供每周自动任务挑几家做深度调研（strength < 60 字视为过薄）
    thin = [{'name': u.get('name'), 'where': w, 'len': len(u.get('strength') or '')}
            for w, lst in (('competitors', comps), ('partners', par))
            for u in lst if len(u.get('strength') or '') < 60]
    if thin:
        q = os.path.join(INBOX, 'thin_queue.json')
        if not CHECK:
            json.dump(thin, open(q, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('薄档案队列 %d 家 → %s（每周任务会自动挑几家补厚）' % (len(thin), q))
    else:
        print('薄档案队列：无（所有单位档案均已达标）')

    # 分类统计
    from collections import Counter
    print('竞企分类：', dict(Counter(x.get('cat', '其他') for x in comps)))
    print('伙伴分类：', dict(Counter(x.get('cat', '其他') for x in par)))

    if CHECK:
        print('\n[--check] 未写盘')
        return 0
    save(ind_path, ind)
    save(par_path, par)
    # 同步顶层副本（保持与 raw/ 一致，避免误用旧副本）
    save(os.path.join(ROOT, 'industry.json'), ind)
    save(os.path.join(ROOT, 'partners.json'), par)
    print('\n已写入：raw/industry.json, raw/partners.json 及顶层副本（.bak 备份）')
    return 0

if __name__ == '__main__':
    sys.exit(main())
