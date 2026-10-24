# -*- coding: utf-8 -*-
"""三图谱：对手 / 业主 / 队友  ── build_graphs.py

用户 2026-10-23 定的网页四件事：
  ① 对手投/参与了哪些标、中标人、价格、标书
  ② 队友参与哪些标、跟哪个业主关系好（投标次数参考）、能否联合
  ③ 业主招了哪些标、常是哪些人中的、可否找中标人取经合作
  ④ 业主动向、海外动作、有色等行业在哪新上项目

这三张图就是把这四件事从「一条条公告」压成「一个个对象」：
  rivals[]   对手图谱：谁在我们主业里中了多少标、报什么价、跟谁组队
  owners[]   业主图谱：谁在招标、常是哪些单位中的（亲密度=中标次数）
  partners[] 队友图谱：可联合对象，以及联合时我方该出 EP 还是 PC

口径：全库参与（同业/客户不按「找商机」严筛），但对每条打 level 标签，
      图上就能看出这个对手是「抢我主业」还是「只是兼营区露过面」。
产出 raw/graphs.json
"""
import os, re, json
from collections import defaultdict, Counter

import biz_rules as BR
import seg_biz as SM

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(RAW, 'graphs.json')
SRC = os.path.join(ROOT, 'merged.json')

# ── 中标单位清洗 ────────────────────────────────────────────────
NOISE_WIN = {'合同价款', '得票数', '详见', '生产过程', '地方', '无', '暂无',
             '见附件', '其他', '待定', '/', '略', '第一中标候选人', '第二中标候选人',
             '第三中标候选人', '中标人', '中标单位', '成交供应商'}
SUFFIX_OK = ('公司', '研究院', '设计院', '集团', '厂', '中心', '局', '部', '队',
             '站', '社', '所', '大学', '学院', '总院', '医院', '处', '管委会',
             '办公室', '有限公司', '股份', '总厂', '分行', '支行')
RE_CAND = re.compile(r'^\s*(?:第[一二三]?)?中标候选人[:：]?\s*')
RE_PRICE = re.compile(r'(?:投标报价|中标价|报价|中标金额)\s*[:：]?\s*[0-9,\.]+\s*(?:元|万元|亿元)?')
RE_LEAD = re.compile(r'^\s*(?:第一|第二|第三|1|2|3)\s*[:：、]?\s*')
RE_PAREN_NOTE = re.compile(r'[（(][^）)]*(?:报价|金额|价格|万元|元)[^）)]*[）)]')


def split_wins(s):
    """把 win 字段拆成干净的单位名列表"""
    s = (s or '').strip()
    if not s:
        return []
    s = RE_PAREN_NOTE.sub('；', s)
    s = RE_PRICE.sub('；', s)
    out = []
    for part in re.split(r'[;；\n]', s):
        p = part.strip()
        p = RE_CAND.sub('', p)
        p = RE_LEAD.sub('', p)
        p = re.sub(r'\s+', '', p)
        p = p.strip('　 ,，。.、')
        if not p or len(p) < 6:
            continue
        if p in NOISE_WIN:
            continue
        if not p.endswith(SUFFIX_OK):
            continue
        if re.search(r'\d{4,}元', p):
            continue
        out.append(p)
    # 去重保序
    seen = set()
    r = []
    for x in out:
        if x not in seen:
            seen.add(x)
            r.append(x)
    return r


# ── 单位类型判定（决定是对手还是队友） ────────────────────────────
RE_CONSTRUCT = re.compile(r'(建设|安装|施工|工程局|建工|建筑工程|机电安装|电力工程|钢构|土木|路桥|市政工程)')
RE_DESIGN = re.compile(r'(设计|研究院|勘察|规划|咨询)')
RE_EQUIP = re.compile(r'(锅炉|汽轮机|汽机|电机|电气|重工|机械|装备|环保设备|成套设备|电力设备|阀门|风机|除尘器)')
RE_FINANCE = re.compile(r'(投资|融资|资本|基金|租赁|财团)')

# 单位百科里点过名的，以百科为准（名字里不一定带「设计」二字）
_OVERRIDE = {}


def load_override():
    try:
        d = json.load(open(os.path.join(RAW, 'units_encyclopedia.json'), encoding='utf-8'))
    except Exception:
        return
    for g in d.get('groups', []):
        for u in g.get('units', []):
            nm = u.get('name', '')
            if not nm:
                continue
            biz = ' '.join(u.get('biz', []) + u.get('focus3', []))
            if re.search(r'设计|研究院|勘察|咨询', nm + biz):
                k = 'design'
            elif re.search(r'建设|安装|施工|工程', nm + biz):
                k = 'construct'
            else:
                k = 'other'
            _OVERRIDE[nm] = {'kind': k, 'relation': u.get('relation', ''),
                             'group': g.get('name', '')}
            for s in (u.get('short') or '').split('/'):
                s = s.strip()
                if len(s) >= 4:
                    _OVERRIDE[s] = _OVERRIDE[nm]


def unit_kind(name):
    if name in _OVERRIDE:
        return _OVERRIDE[name]['kind']
    # 判序：设计院优先（「XX设计研究院工程有限公司」也算设计端），再看施工，再资方
    if RE_DESIGN.search(name):
        return 'design'
    if RE_EQUIP.search(name):
        return 'equip'
    if RE_CONSTRUCT.search(name) or name.endswith('工程有限公司') or name.endswith('工程集团有限公司'):
        return 'construct'
    if RE_FINANCE.search(name):
        return 'finance'
    return 'other'


# 业务层级 → 重要度
LEVEL_MAIN = ('youse', 'steel', 'waste_heat', 'cogen')          # 一级
LEVEL_MAIN2 = ('chem_heat', 'selfplant', 'idc')                  # 二级
LEVEL_KEEP = ('wte',)                                            # 留（垃圾焚烧）
LEVEL_SIDE = ('soil', 'zero', 'sewage')                          # 兼营


def level_of(seg):
    if seg in LEVEL_MAIN:
        return 1
    if seg in LEVEL_MAIN2:
        return 2
    if seg in LEVEL_KEEP:
        return 3
    if seg in LEVEL_SIDE:
        return 4
    return 9


def level_name(lv):
    return {1: '一级主业', 2: '二级主业', 3: '垃圾焚烧（留）',
            4: '兼营区', 9: '其他/未分类'}[lv]


def main():
    load_override()
    rows = json.load(open(SRC, encoding='utf-8'))
    print('读入', len(rows), '条')

    rivals = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'amtN': 0,
                                  'rgs': Counter(), 'subs': Counter(),
                                  'modes': Counter(), 'owners': Counter(),
                                  'mates': Counter(), 'lvs': Counter(),
                                  'buckets': Counter(), 'last': '', 'items': []})
    owners = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'rgAll': Counter(),
                                  'st': Counter(), 'subs': Counter(),
                                  'wins': Counter(), 'buckets': Counter(),
                                  'lvs': Counter(), 'mainN': 0,
                                  'last': '', 'items': []})

    nkeep = 0
    for r in rows:
        t = r.get('t') or ''
        if not t:
            continue
        j = BR.judge(t, r.get('snip') or '', r.get('amt'),
                     r.get('st') or '', r.get('buyer') or '', r.get('win') or '')
        if not j['keep']:
            continue
        nkeep += 1
        seg = j['seg']
        lv = level_of(seg)
        rg = r.get('rg') or ''
        d = r.get('d') or ''
        amt = r.get('amt') or 0
        buyer = (r.get('buyer') or '').strip()
        url = r.get('url') or ''

        wins = split_wins(r.get('win'))
        if buyer and len(buyer) >= 6:
            o = owners[buyer]
            o['n'] += 1
            o['amt'] += amt
            o['rgAll'][rg or '未知'] += 1
            o['st'][r.get('st') or '其他'] += 1
            o['subs'][j['segname']] += 1
            o['buckets'][j['bucket']] += 1
            o['lvs'][lv] += 1
            if lv <= 3:
                o['mainN'] += 1
            if d > o['last']:
                o['last'] = d
            for w in wins:
                o['wins'][w] += 1
            o['items'].append({'t': t, 'd': d, 'st': r.get('st') or '',
                               'amt': amt, 'sub': j['segname'], 'lv': lv,
                               'win': wins[0] if wins else '', 'url': url,
                               'rg': rg, 'city': r.get('city') or ''})

        for w in wins:
            v = rivals[w]
            v['n'] += 1
            if amt:
                v['amt'] += amt
                v['amtN'] += 1
            v['rgs'][rg or '未知'] += 1
            v['subs'][j['segname']] += 1
            v['modes'][j['mode'] or '未标'] += 1
            v['lvs'][lv] += 1
            v['buckets'][j['bucket']] += 1
            if buyer:
                v['owners'][buyer] += 1
            for w2 in wins:
                if w2 != w:
                    v['mates'][w2] += 1
            if d > v['last']:
                v['last'] = d
            v['items'].append({'t': t, 'd': d, 'rg': rg, 'city': r.get('city') or '',
                               'amt': amt, 'sub': j['segname'], 'lv': lv,
                               'buyer': buyer, 'mode': j['mode'], 'url': url,
                               'mates': [x for x in wins if x != w]})

    # ── 组装对手 ────────────────────────────────────────────────
    rl = []
    for name, v in rivals.items():
        lvs = v['lvs']
        n1 = lvs.get(1, 0)
        n2 = lvs.get(2, 0)
        n3 = lvs.get(3, 0)
        n4 = lvs.get(4, 0)
        kind = unit_kind(name)
        if n1 or n2:
            tag = 'direct'          # 抢我主业 → 头号盯防
        elif n3:
            tag = 'wte'             # 垃圾焚烧圈
        elif n4:
            tag = 'side'            # 只在兼营区露面
        else:
            tag = 'latent'          # 其他圈，暂时不构成正面威胁
        ov = _OVERRIDE.get(name, {})
        rl.append({
            'name': name, 'kind': kind, 'tag': tag,
            'encyGroup': ov.get('group', ''), 'encyRel': ov.get('relation', ''),
            'n': v['n'], 'amt': round(v['amt'], 2),
            'amtW': round(v['amt'] / 1e4, 1),
            'amtAvg': round(v['amt'] / v['amtN'] / 1e4, 1) if v['amtN'] else 0,
            'last': v['last'],
            'n1': n1, 'n2': n2, 'n3': n3, 'n4': n4,
            'lvs': [{'k': level_name(k), 'n': c} for k, c in sorted(lvs.items())],
            'rgs': [{'k': k, 'n': c} for k, c in v['rgs'].most_common(6)],
            'subs': [{'k': k, 'n': c} for k, c in v['subs'].most_common(6)],
            'modes': [{'k': k, 'n': c} for k, c in v['modes'].most_common(5)],
            'owners': [{'k': k, 'n': c} for k, c in v['owners'].most_common(8)],
            'mates': [{'k': k, 'n': c} for k, c in v['mates'].most_common(5)],
            'buckets': dict(v['buckets']),
            'items': sorted(v['items'], key=lambda x: x['d'], reverse=True)[:12],
        })
    rl.sort(key=lambda x: (-(x['n1'] + x['n2']), -x['n'], -x['amt']))

    # ── 组装业主 ────────────────────────────────────────────────
    ol = []
    for name, v in owners.items():
        rg = v['rgAll'].most_common(1)[0][0] if v['rgAll'] else ''
        ol.append({
            'name': name, 'rg': rg, 'n': v['n'], 'mainN': v['mainN'],
            'amt': round(v['amt'], 2), 'amtW': round(v['amt'] / 1e4, 1),
            'last': v['last'],
            'lvs': [{'k': level_name(k), 'n': c} for k, c in sorted(v['lvs'].items())],
            'st': [{'k': k, 'n': c} for k, c in v['st'].most_common(5)],
            'subs': [{'k': k, 'n': c} for k, c in v['subs'].most_common(6)],
            'buckets': dict(v['buckets']),
            'wins': [{'k': k, 'n': c} for k, c in v['wins'].most_common(8)],
            'nSup': len(v['wins']),
            'items': sorted(v['items'], key=lambda x: x['d'], reverse=True)[:12],
        })
    ol.sort(key=lambda x: (-x['n'], -x['amt']))

    # ── 组装队友（可联合对象） ───────────────────────────────────
    pl = []
    for x in rl:
        if x['kind'] == 'construct':
            myrole = '我方出 EP（设计+采购），对方出施工'
            why = '施工端，符合「与施工单位联合→我方做 EP」'
        elif x['kind'] == 'design':
            myrole = '我方出 PC（采购+施工），对方出设计'
            why = '设计端，符合「与设计院联合→我方做 PC」'
        elif x['kind'] == 'finance':
            myrole = 'F+EPC：对方出资金，我方 EPC'
            why = '资方，可组 F+EPC / F+EPC+O'
        elif x['kind'] == 'equip':
            myrole = '我方 EPC，对方供主设备（锅炉/汽轮机/环保设备）'
            why = '主设备商，是我们 EPC 里的关键分包/联合体成员'
        else:
            continue
        # 只保留有联合价值的：在我方相关层级（1/2/3/4）露过面，或地区在江浙沪皖
        rel = x['n1'] + x['n2'] + x['n3'] + x['n4']
        if rel == 0:
            continue
        ov = _OVERRIDE.get(x['name'], {})
        pl.append(dict(x, myrole=myrole, why=why, relN=rel,
                       encyGroup=ov.get('group', ''),
                       encyRel=ov.get('relation', ''),
                       topOwners=x['owners'][:5]))
    pl.sort(key=lambda x: (-x['relN'], -x['n']))

    data = {
        'updated': '2026-10-23',
        'src': 'merged.json 全库，经 biz_rules.judge 打标后聚合',
        'nRows': len(rows), 'nKeep': nkeep,
        'nRival': len(rl), 'nOwner': len(ol), 'nPartner': len(pl),
        'level_legend': {'1': '一级主业（有色供能/钢铁煤气发电/余热余压/热电联产）',
                         '2': '二级主业（化工余热/自备电厂能源站/数据中心供能）',
                         '3': '垃圾焚烧（总承包能力用得上）',
                         '4': '兼营（土壤/废水零排/市政污水）',
                         '9': '其他/未分类'},
        'tag_legend': {'direct': '抢我主业，头号盯防', 'wte': '垃圾焚烧圈对手',
                       'side': '兼营区对手', 'latent': '其他圈，暂不正面冲突'},
        'kind_legend': {'construct': '施工类', 'design': '设计院类',
                        'equip': '主设备商', 'finance': '资方', 'other': '其他'},
        'amtUnit': 'amt 单位=元；amtW/amtAvg 单位=万元',
        'rivals': rl, 'owners': ol, 'partners': pl,
    }
    json.dump(data, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"入库 {nkeep}/{len(rows)}  对手 {len(rl)}  业主 {len(ol)}  队友 {len(pl)}")
    print('--- 对手 Top15（按主业命中数）---')
    for x in rl[:15]:
        print(f"{x['n1']+x['n2']:>2}主/{x['n']:>2}总 {x['amtW']:>9.0f}万 [{x['kind']:<9}] {x['name']}")
    print('--- 业主 Top10 ---')
    for x in ol[:10]:
        print(f"{x['n']:>3}标 主{x['mainN']:>2} {x['amtW']:>9.0f}万 {x['rg']:<4} 合作单位{x['nSup']:>2} {x['name']}")
    print('--- 队友 Top12 ---')
    for x in pl[:12]:
        print(f"rel{x['relN']:>2} {x['n']:>2}次 [{x['kind']:<9}] {x['name']}")
    return data


if __name__ == '__main__':
    main()
