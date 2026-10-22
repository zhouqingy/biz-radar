#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业主画像 + 供应商关系图谱（2026-10-21，领导意见）

背景：领导问"江浙沪皖业主的情况、业主招标情况、主要供应商有哪些、和业主关系怎么样，
      这样就知道该联系哪个供应商和业主"。这些数据本来就藏在商机库里——
      793 条有业主名、258 条有中标单位、238 条两者都有——但从来没被关联成"关系"。

产出 raw/owner_graph.json：
  owners[]    业主档案：地区、项目数、金额、状态分布、合作供应商（次数/金额/最近时间）、项目清单
  suppliers[] 供应商档案：中标次数、金额、服务过哪些业主、擅长细分方向、活跃地区

只在 build 阶段算一次并落盘，不增加页面加载负担。
"""
import os, re, json, time
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
DATA = os.path.join(os.path.dirname(ROOT), 'biz-radar', 'data.js')
OUT = os.path.join(RAW, 'owner_graph.json')

# ---- 清洗规则 ----
# 1) 去掉"（项目单位：xxx）""(建设单位:xxx)"这类附加说明，只留主体名
PAREN = re.compile(r'[（(]\s*(?:项目单位|建设单位|代建单位|业主单位|招标人)\s*[：:][^）)]*[）)]')
# 2) 明显不是业主名的噪音
BAD_OWNER = ['得票数', '详见', '略', '暂无', '无', '见附件', '待定', '其他', '/']
# 3) 中标单位里的"（第一中标候选人）"这类备注
WIN_NOTE = re.compile(r'[（(]\s*第?[一二三]?中标?候选人[）)]')


def clean_owner(s):
    s = (s or '').strip()
    s = PAREN.sub('', s).strip()
    s = re.sub(r'\s+', '', s)
    return s


def clean_win(s):
    s = (s or '').strip()
    s = WIN_NOTE.sub('', s).strip()
    s = re.sub(r'\s+', '', s)
    return s


def bad(n):
    if not n or len(n) < 3 or len(n) > 60:
        return True
    return any(b == n for b in BAD_OWNER)


def main():
    s = open(DATA, encoding='utf-8').read()
    D = json.loads(s[s.index('{'):s.rindex('}') + 1])
    items = D['items']
    MAP = D.get('buyers', [])          # 已有的业主列表（含 items）
    buy_items = {b['name']: b.get('items', []) for b in MAP}

    # ---- 并入公告原文补全的结果（中标单位 / 联系人 / 电话 / 地址 / 代理机构）----
    # mine_notice.py 用无头 Chrome 抓公告详情页得到，补上商机库里缺失的 47% 中标单位
    extra = {}
    _p = os.path.join(RAW, 'notice_extra.json')
    if os.path.exists(_p):
        try:
            extra = json.load(open(_p, encoding='utf-8')).get('items', {})
        except Exception:
            extra = {}
    n_ex_win = 0
    for x in items:
        e = extra.get(x.get('url') or '')
        if not e:
            continue
        if e.get('win') and not (x.get('win') or '').strip():
            x['win'] = e['win']
            n_ex_win += 1
        for k in ('contact', 'phone', 'addr', 'agent'):
            if e.get(k):
                x[k] = e[k]
    print('公告原文补全：并入中标单位 %d 条（库内原有缺失已补）' % n_ex_win)

    # ---------- 业主聚合 ----------
    recs = defaultdict(list)      # 业主名 -> 记录列表
    for x in items:
        b = clean_owner(x.get('buyer'))
        if bad(b):
            continue
        recs[b].append(x)

    owners = []
    supplier_agg = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'owners': defaultdict(int),
                                        'subs': Counter(), 'rgs': Counter(), 'last': '',
                                        'items': []})
    for name, rs in recs.items():
        amt = sum(r['amt'] for r in rs if r.get('amt'))
        rgs = Counter(r['rg'] for r in rs if r.get('rg'))
        sts = Counter(r['st'] for r in rs)
        subs = Counter(r['sub'] for r in rs if r.get('sub'))
        dates = sorted([r['d'] for r in rs if r.get('d')], reverse=True)

        # 合作供应商：有中标单位记录
        sup = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'last': '', 'items': []})
        wins_known = 0
        for r in rs:
            w = clean_win(r.get('win'))
            if bad(w):
                continue                      # 没公布中标单位 = 未知，不算"无人中标"
            wins_known += 1
            sup[w]['n'] += 1
            if r.get('amt'):
                sup[w]['amt'] += r['amt']
            if (r.get('d') or '') > sup[w]['last']:
                sup[w]['last'] = r.get('d') or ''
            sup[w]['items'].append({'t': r.get('t', ''), 'd': r.get('d', ''),
                                    'amt': r.get('amt'), 'url': r.get('url', '')})
            # 反向写供应商
            g = supplier_agg[w]
            g['n'] += 1
            if r.get('amt'):
                g['amt'] += r['amt']
            g['owners'][name] += 1
            if r.get('sub'):
                g['subs'][r['sub']] += 1
            if r.get('rg'):
                g['rgs'][r['rg']] += 1
            if (r.get('d') or '') > g['last']:
                g['last'] = r.get('d') or ''
            g['items'].append({'t': r.get('t', ''), 'd': r.get('d', ''),
                               'amt': r.get('amt'), 'url': r.get('url', ''),
                               'owner': name})

        sups = [{'name': k, 'n': v['n'], 'amt': round(v['amt'], 4),
                 'last': v['last'], 'items': v['items'][:8]}
                for k, v in sup.items()]
        sups.sort(key=lambda z: (-z['n'], -(z['amt'] or 0)))

        # 项目清单（按日期倒序，最多留 30 条）
        plist = [{'t': r.get('t', ''), 'd': r.get('d', ''), 'st': r.get('st', ''),
                  'amt': r.get('amt'), 'win': clean_win(r.get('win')),
                  'sub': r.get('sub', ''), 'url': r.get('url', ''),
                  'mode': r.get('mode', ''),
                  'contact': r.get('contact', ''), 'phone': r.get('phone', ''),
                  'addr': r.get('addr', ''), 'agent': r.get('agent', '')}
                 for r in sorted(rs, key=lambda z: (z.get('d') or ''), reverse=True)][:30]

        # 联系方式：从公告原文里抽到的联系人和电话，按出现频次去重（同一业主常有固定对接人）
        cts = Counter()
        for r in rs:
            c, ph = (r.get('contact') or '').strip(), (r.get('phone') or '').strip()
            if c or ph:
                cts[(c, ph)] += 1
        contacts = [{'name': c, 'phone': p, 'n': v} for (c, p), v in cts.most_common(5)]
        addr = next((r.get('addr') for r in rs if r.get('addr')), '')
        agent = Counter(r.get('agent') for r in rs if r.get('agent')).most_common(3)

        owners.append({
            'name': name,
            'rg': rgs.most_common(1)[0][0] if rgs else '',
            'rgAll': dict(rgs),
            'n': len(rs),
            'amt': round(amt, 4),
            'latest': dates[0] if dates else '',
            'st': dict(sts),
            'subs': [{'k': k, 'n': v} for k, v in subs.most_common(6)],
            'nWin': wins_known,                     # 已公布中标单位的条数
            'nSup': len(sups),                      # 合作过的不同供应商数
            'sups': sups[:10],
            'contacts': contacts,
            'addr': addr,
            'agent': [{'name': a, 'n': b} for a, b in agent],
            'items': plist,
        })
    owners.sort(key=lambda z: (-z['n'], -(z['amt'] or 0)))

    # ---------- 供应商档案 ----------
    suppliers = []
    for k, v in supplier_agg.items():
        suppliers.append({
            'name': k,
            'n': v['n'],
            'amt': round(v['amt'], 4),
            'last': v['last'],
            'nOwners': len(v['owners']),
            'owners': [{'name': o, 'n': c} for o, c in
                       sorted(v['owners'].items(), key=lambda z: -z[1])][:10],
            'subs': [{'k': s, 'n': c} for s, c in v['subs'].most_common(4)],
            'rgs': [{'k': r, 'n': c} for r, c in v['rgs'].most_common(4)],
            'items': sorted(v['items'], key=lambda z: (z.get('d') or ''), reverse=True)[:10],
        })
    suppliers.sort(key=lambda z: (-z['n'], -(z['amt'] or 0)))

    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'nOwner': len(owners),
        'nSupplier': len(suppliers),
        'nRel': sum(o['nWin'] for o in owners),
        'owners': owners,
        'suppliers': suppliers,
    }
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('业主 %d 家 / 供应商 %d 家 / 可关联记录 %d 条 → %s'
          % (len(owners), len(suppliers), out['nRel'], OUT))
    print('业主 TOP5:')
    for o in owners[:5]:
        print('  %-30s %d 条 · %.2f 亿 · 供应商 %d 家 · 最新 %s'
              % (o['name'][:28], o['n'], o['amt'], o['nSup'], o['latest']))
    print('供应商 TOP5:')
    for x in suppliers[:5]:
        print('  %-30s 中标 %d 次 · %.2f 亿 · 服务 %d 家业主'
              % (x['name'][:28], x['n'], x['amt'], x['nOwners']))


if __name__ == '__main__':
    main()
