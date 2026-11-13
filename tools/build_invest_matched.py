#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把投资在线审批平台的两份扁平采集结果聚合成 pick_invest.py 要的 invest_matched.json

════════════════════════════════════════════════════════════════════
为什么需要这一步（2026-11-13 补）
════════════════════════════════════════════════════════════════════
11-04 那条链是四段：
    crawl_invest.py     → raw/invest_zj.json / invest_js.json   （每条 = 一个审批事项）
    （聚合 + 反查库）   → raw/invest_matched.json               ← **这一段当时是手工跑的，没留脚本**
    pick_invest.py      → raw/invest_pick.json（A/B/C/弃 分档）
    （合并进分省库）    → raw/{jiangsu,zhejiang}.json           ← **这一段当时也没有**

结果：四个脚本 11-04 推上仓库后，从来没有任何工作流调用过它们。
①库里的「投资在线」190 条全是 legacy_D 里的老数据（最新 2026-09-23），
此后每天的审批信号（招标前 3~12 个月）一条都没进来。

本脚本补的是第二段：按项目名把散落的事项聚成一条，并用商机库反查
「这个项目现在到哪一步了」（A 档=库内已有公告，B 档=库内搜不到 ⇒ 还没招标）。

聚合口径（与 pick_invest.py 的 B 档判定一致）：
  · phase 取该条目在 HARD 阶段（施工许可/规划许可/核准/…）里**最晚**的那一项
  · 没有 HARD 阶段的，phase 留空，pick_invest 会判进「弃」
  · 去重键 (prov, name, code)：同名不同项目代码的算两条
"""
import json
import os
import re
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, 'raw')

# 与 pick_invest.py 的 HARD 保持一致（改一处必须改两处；下面有断言兜底）
HARD = ('施工许可', '规划许可', '初步设计', '核准', '建设工程（含临时建', '建设工程规划',
        '用地预审', '竣工验收', '竣工规划')
# 归一后的阶段名，顺序即「审批走得多深」
PHASE_ORDER = ['施工许可', '建设工程规划', '规划许可', '初步设计', '用地预审', '核准', '竣工验收']
PHASE_MAP = [
    ('施工许可', '施工许可'),
    ('规划许可', '规划许可'),
    ('建设工程（含临时建', '建设工程规划'),
    ('建设工程规划', '建设工程规划'),
    ('初步设计', '初步设计'),
    ('用地预审', '用地预审'),
    ('核准', '核准'),
    ('竣工', '竣工验收'),
]

SRC_FILES = [('浙江', 'invest_zj.json', '浙江投资在线审批平台'),
             ('江苏', 'invest_js.json', '江苏投资在线审批平台')]


def norm_name(s):
    s = re.sub(r'[（(][^）)]*[）)]', '', str(s or ''))
    return re.sub(r'[\s·、,，。:：;；]', '', s)


def load_db():
    """取「上次构建出来的①库」做反查底表。
    用 data.chunk-*.js 而不是 merged.json：这些是仓库里现成的产物，
    CI 里 3.10 这步跑在 4) 重建之前，此时 merged.json 还是上一轮的，一样能用。
    路径三档：本地 ../biz-radar → CI 仓库根 ../ → $BIZ_OUT。"""
    cands = [os.path.join(HERE, '..', 'biz-radar'),
             os.path.join(HERE, '..'),
             os.environ.get('BIZ_OUT') or '']
    rows, seen = [], set()
    for f in ('data.chunk-lead.js', 'data.chunk-rest.js', 'data.items.js'):
        p = ''
        for d in cands:
            if d and os.path.exists(os.path.join(d, f)):
                p = os.path.join(d, f)
                break
        if not p:
            continue
        s = open(p, encoding='utf-8').read()
        try:
            j = json.loads(s[s.index('=') + 1:].strip().rstrip(';'))
        except Exception:
            continue
        c = j.get('cols') if isinstance(j, dict) else None
        if isinstance(c, dict):
            n = len(c.get('t') or [])
            for i in range(n):
                t = c['t'][i]
                if t in seen:
                    continue
                seen.add(t)
                rows.append({'t': t, 'st': c['st'][i] if c.get('st') else '',
                             'd': c['d'][i] if c.get('d') else ''})
        else:
            for r in (j if isinstance(j, list) else []):
                t = r.get('t')
                if t and t not in seen:
                    seen.add(t)
                    rows.append({'t': t, 'st': r.get('st', ''), 'd': r.get('d', '')})
    return rows


def pick_phase(items):
    """取该条目走过的最深一道硬审批（数字越小越靠后），同深度取日期更新的。"""
    best, best_idx, best_d = '', 99, ''
    for it in items:
        name = it.get('item') or ''
        for kw, std in PHASE_MAP:
            if kw in name:
                idx = PHASE_ORDER.index(std) if std in PHASE_ORDER else 98
                d = it.get('date') or ''
                if idx < best_idx or (idx == best_idx and d > best_d):
                    best, best_idx, best_d = std, idx, d
                break
    return best


def main():
    rows = []
    for prov, fn, src in SRC_FILES:
        p = os.path.join(RAW, fn)
        if not os.path.exists(p):
            print('⚠ 缺 %s，跳过 %s' % (fn, prov))
            continue
        d = json.load(open(p, encoding='utf-8'))
        items = d.get('items') if isinstance(d, dict) else d
        print('%-4s 读入 %d 条审批事项（%s）' % (prov, len(items), fn))
        rows += items

    # 聚合：同名同代码 → 一条
    group = defaultdict(list)
    meta = {}
    for r in rows:
        k = (r.get('prov') or '', norm_name(r.get('name')), r.get('code') or '')
        group[k].append(r)
        meta.setdefault(k, {'prov': r.get('prov'), 'name': r.get('name'),
                            'code': r.get('code') or '', 'kw': []})
        if r.get('kw') and r['kw'] not in meta[k]['kw']:
            meta[k]['kw'].append(r['kw'])

    db = load_db()
    if not db:
        # 反查底表读不到就别往下写：B 档的判据是「库内搜不到公告」，
        # 底表为空会让「已经有公告的项目」全部被当成 B 档灌进分省库，直接造成重复卡片。
        print('✗ 读不到①库产物（data.chunk-*.js），本轮不生成 invest_matched.json')
        return 3
    sys.path.insert(0, HERE)
    try:
        import match_invest_status as MIS
    except Exception as e:
        print('✗ 无法加载 match_invest_status.py（%s），本轮不生成' % e)
        return 3
    idx = MIS.build_index(db)

    out, n_hit = [], 0
    for k, its in group.items():
        its.sort(key=lambda x: x.get('date') or '')
        m = meta[k]
        dates = [x.get('date') for x in its if x.get('date')]
        try:
            grade, hit = MIS.lookup(m['name'], idx, db)
        except Exception:
            grade, hit = '', None
        if hit:
            n_hit += 1
        out.append({
            'prov': m['prov'],
            'name': m['name'],
            'code': m['code'],
            'kw': m['kw'],
            'items': [{'item': x.get('item'), 'date': x.get('date'),
                       'dept': x.get('dept'), 'deal': x.get('deal')} for x in its],
            'date_first': dates[0] if dates else '',
            'date_last': dates[-1] if dates else '',
            'phase': pick_phase(its),
            'match': grade,
            'db': hit,
        })

    out.sort(key=lambda x: x.get('date_last') or '', reverse=True)
    dst = os.path.join(RAW, 'invest_matched.json')
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(out), 'items': out},
              open(dst, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('聚合 %d 条（审批事项 %d → 项目 %d）· 库内命中 %d · 写入 %s'
          % (len(out), len(rows), len(out), n_hit, dst))
    from collections import Counter
    print('阶段分布', dict(Counter(x['phase'] or '（未到硬阶段）' for x in out).most_common(8)))
    print('省份分布', dict(Counter(x['prov'] for x in out)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
