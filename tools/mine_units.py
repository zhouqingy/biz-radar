#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从商机库 A/B 级（战略必争 / 重点跟进）项目里自动挖掘单位：
  · 撞单型（EPC 总包、电力/能源/环保工程公司、设计院牵头） -> 竞争对手
  · 资源型（施工、安装、建工、送变电、城建、市政）        -> 合作生态

产出 raw/_inbox/mined_competitors.json / mined_partners.json，
由 merge_units.py 去重后并入主库（已存在的只补全，不会重复收录）。

入选门槛（宁缺毋滥）：
  · 名称合规（6~40 字，以公司/院/集团/厂/中心/局等结尾，含地域或行业词）
  · 出现 ≥2 次，或单次中标金额 ≥ 1 亿元
  · 排除噪声：含“等”“/”未拆分干净的、纯人名、金额串
"""
import json, os, re, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
MERGED = os.path.join(ROOT, 'merged.json')
INBOX = os.path.join(ROOT, 'raw', '_inbox')

MIN_AMT = 1e8          # 单条金额门槛：1 亿元
MIN_TIMES = 2          # 或出现次数门槛

# —— 噪声与清洗 ——
NOISE_END = ('等', '等公司', '公司等', '/')
SUFFIX_RE = re.compile(
    r'[（(](?:第[一二三]?中标候选人|中标候选人|第一中标候选人|中标人|拟中标人|'
    r'牵头人|成员|成员单位|联合体牵头人|联合体成员|承建|施工|设计|勘察|供货|'
    r'中标|成交|第一名|含[^）)]{0,20})[）)]')
ROLE_RE = re.compile(r'[（(](?:牵头人|成员|成员单位|联合体牵头人|联合体成员)[）)]')
END_OK = ('公司', '设计院', '研究院', '集团', '总厂', '工厂', '厂', '中心',
          '工程局', '建设局', '分局', '设计集团', '事务所', '控股', '股份')
SPLIT_RE = re.compile(r'[;；+、／/]|(?:\s+y\s+)')

# —— 分流关键词 ——
PARTNER_KW = ['安装', '建工', '建设工程', '建设集团', '建设发展', '建筑工程',
              '工程局', '局集团', '局有限公司', '送变电', '城建', '市政', '路桥',
              '土木', '基建', '机械化', '装饰', '钢结构', '航道局', '水务集团']
COMPET_KW = ['环保', '环境', '电力', '电气', '能源', '锅炉', '热电', '能建',
             # 2026-10-19 补：燃气发电/分布式能源类对手（如 xx 燃气发电、xx 分布式能源）
             '燃气', '天然气', '分布式', '燃机',
             '工程技术', '工程科技', '设计研究', '工程设计', '清洁', '水务',
             '水处理', '资源', '科技股份', '中元', '恩菲', '瑞林', '赛迪']
DESIGN_KW = ['设计院', '研究院', '设计集团', '勘察', '设计研究', '工程设计']


def clean_name(raw):
    s = (raw or '').strip()
    if not s:
        return ''
    s = re.sub(r'联合体[：:]?', '', s)          # 残留的“联合体：”标记
    s = SUFFIX_RE.sub('', s)
    s = ROLE_RE.sub('', s)
    s = re.sub(r'^[^一-龥]+', '', s)              # 开头的冒号/符号残留
    prev = None                                   # 循环剥括号（含嵌套），与库内写法对齐
    while prev != s:
        prev = s
        s = re.sub(r'[（(][^（()）]*[）)]', '', s)
    s = re.sub(r'\s+', '', s)
    s = s.strip('、,，。;； ')
    # 结尾补“公司”：如“中国能源建设集团江苏省电力设计院”
    if len(s) >= 6 and not s.endswith(END_OK):
        return ''
    if not (6 <= len(s) <= 40):
        return ''
    if any(s.endswith(n) for n in NOISE_END):
        return ''
    if re.search(r'\d{5,}', s):            # 混了大串数字（金额误入）
        return ''
    if re.match(r'^[一二三四五六七八九十\d]、', s):
        return ''
    return s


def split_units(win):
    """拆分联合体 / 多个中标人。先拆分隔符再清洗，避免“（牵头人）+（成员）”粘连"""
    s = (win or '').strip()
    if not s:
        return []
    s = re.sub(r'联合体[：:]?', '', s)
    # 先按分隔符切（保护括号内的 + 不会被误切：此处直接切即可，角色词随后清洗）
    parts = [p.strip() for p in SPLIT_RE.split(s) if p.strip()]
    out = []
    for p in parts:
        # 顺序很关键：先删角色词块 → 再剥括号及内容 → 再删残留括号字符
        # （否则“（牵头人）”“（测试）”删掉括号字符后会把词粘在末尾，导致整条被判无效丢弃）
        p = ROLE_RE.sub('', SUFFIX_RE.sub('', p))
        prev = None
        while prev != p:
            prev = p
            p = re.sub(r'[（(][^（()）]*[）)]', '', p)
        p = re.sub(r'[（(）)]', '', p)
        # 粘连兜底：按冒号切（"A：B"），再按公司结尾切（"A有限公司B有限公司"）
        subs = []
        for q0 in re.split(r'[：:]', p):
            subs += re.split(r'(?<=有限公司)(?=[\u4e00-\u9fa5])', q0) if q0.count('有限公司') >= 2 else [q0]
        for q in subs:
            n = clean_name(q)
            if n:
                out.append(n)
    # 去重保序
    seen, res = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res


def amt_of(it):
    a = it.get('amt')
    try:
        return float(a) if a else 0.0
    except (TypeError, ValueError):
        return 0.0


def main():
    if not os.path.exists(MERGED):
        print('[ERR] 找不到 %s，请先跑 build_data.py' % MERGED)
        return 1
    items = json.load(open(MERGED, encoding='utf-8'))
    ab = [i for i in items if i.get('g') in ('A', 'B')]
    print('A/B 级项目 %d 条' % len(ab))

    agg = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'recs': [], 'biz': defaultdict(int), 'rg': defaultdict(int)})
    skip_ops = 0
    for it in ab:
        ttl = (it.get('t') or '') + (it.get('snip') or '')
        # 纯运营/运维/服务类项目：承接方不是工程承包主体，不纳入对手/伙伴挖掘
        if re.search(r'(运营|运维|运行维护|委托运营|购买服务|管理服务|日常维护|巡检)', ttl) and \
           not re.search(r'(EPC|总承包|施工|设计|改造|扩建|新建)', ttl):
            skip_ops += 1
            continue
        us = split_units(it.get('win'))
        if not us:
            continue
        # 联合体成员按家数分摊项目金额，避免每家都挂全额导致虚高
        share = amt_of(it) / len(us) if len(us) > 1 else amt_of(it)
        share_txt = ('%.2f亿元（联合体 %d 家分摊）' % (share / 1e8, len(us))) if (len(us) > 1 and share) \
            else (it.get('amtTxt') or (('%.2f亿元' % (share / 1e8)) if share else ''))
        for name in us:
            a = agg[name]
            a['n'] += 1
            a['amt'] += share
            a['big'] = max(a.get('big', 0.0), amt_of(it))   # 所在项目的原始体量（门槛用）
            a['biz'][it.get('biz') or ''] += 1
            a['rg'][it.get('rg') or ''] += 1
            a['recs'].append({
                'title': it.get('t') or '',
                'amount': share_txt,
                'date': it.get('d') or '',
                'region': (it.get('rg') or '') + (it.get('city') or ''),
                'url': it.get('url') or '',
            })
    print('清洗出候选单位 %d 家（跳过纯运营类项目 %d 条）' % (len(agg), skip_ops))

    def sorted_recs(recs, k=5):
        return sorted(recs, key=lambda r: r.get('date') or '', reverse=True)[:k]

    # 动态刷新映射：所有在 A/B 级项目中出现过的单位 -> 其最新库内业绩（含已在库的老单位）
    refresh = {name: sorted_recs(a['recs']) for name, a in agg.items() if a['recs']}
    p_refresh = os.path.join(INBOX, 'refresh_dynamics.json')
    os.makedirs(INBOX, exist_ok=True)
    json.dump(refresh, open(p_refresh, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('动态刷新映射 %d 家 → %s' % (len(refresh), p_refresh))

    # 门槛
    keep = {}
    for name, a in agg.items():
        top = max([x for x in [amt_of(r) for r in []]] or [0]) if False else 0
        if a['n'] >= MIN_TIMES or a.get('big', 0) >= MIN_AMT:
            keep[name] = a
    print('过门槛（≥%d 次 或 ≥%.0f 亿）%d 家' % (MIN_TIMES, MIN_AMT / 1e8, len(keep)))

    comps, parts = [], []
    for name, a in sorted(keep.items(), key=lambda kv: (-kv[1]['amt'], -kv[1]['n'])):
        biz = [b for b, _ in sorted(a['biz'].items(), key=lambda kv: -kv[1])[:2] if b]
        rg = [r for r, _ in sorted(a['rg'].items(), key=lambda kv: -kv[1])[:2] if r]
        head = ('库内 A/B 级项目中标 %d 次' % a['n'])
        if a['amt']:
            head += '、合计 %.2f 亿元' % (a['amt'] / 1e8)
        tail = ''
        if biz:
            tail += '，业务集中在「%s」' % '、'.join(biz)
        if rg:
            tail += '，区域在%s' % '、'.join(rg)
        strength = head + tail + '。由商机库自动挖掘收录，业绩均可在库内点开原文复核。'
        e = {
            'name': name,
            'type': guess_type(name),
            'strength': strength,
            'recent': sorted_recs(a['recs']),
            'url': (a['recs'][0]['url'] if a['recs'] else ''),
            '_mine': {'times': a['n'], 'amt': round(a['amt'] / 1e8, 2)},
        }
        if any(k in name for k in DESIGN_KW):
            e['cat'] = '能源类' if any(k in name for k in ('电力', '能源', '热电', '锅炉')) else '综合类'
        # 分流：资源型优先判为合作生态
        if any(k in name for k in PARTNER_KW):
            e['cat'] = e.get('cat') or '综合类'
            e['role'] = '库内 A/B 级项目中出现的施工/安装资源方，可作为联合体施工分包或当地资源方配合'
            parts.append(e)
        elif any(k in name for k in COMPET_KW) or any(k in name for k in DESIGN_KW):
            e['cat'] = e.get('cat') or ('环保类' if any(k in name for k in ('环保', '环境', '水务', '水处理')) else '能源类')
            comps.append(e)
        else:
            e['cat'] = e.get('cat') or '综合类'
            comps.append(e)

    print('分流结果：竞争对手 %d 家 · 合作生态 %d 家' % (len(comps), len(parts)))
    for e in comps + parts:
        print('   [%-6s] %-34s %d次 %.2f亿' % (
            '对手' if e in comps else '伙伴', e['name'][:34], e['_mine']['times'], e['_mine']['amt']))

    os.makedirs(INBOX, exist_ok=True)
    for fn, arr in [('mined_competitors.json', comps), ('mined_partners.json', parts)]:
        p = os.path.join(INBOX, fn)
        json.dump(arr, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('写入 %s（%d 家）' % (p, len(arr)))
    return 0


def guess_type(name):
    if any(k in name for k in DESIGN_KW):
        return '设计院'
    if any(k in name for k in ('安装', '建工', '建设工程', '建设集团', '建设发展', '建筑工程',
                               '工程局', '局集团', '城建', '市政', '路桥', '航道局')):
        return '施工单位'
    if any(k in name for k in ('环保', '环境', '水处理', '水务')):
        return '环保公司'
    if any(k in name for k in ('电力', '电气', '能源', '锅炉', '热电', '能建')):
        return '能源工程公司'
    return '工程公司'


if __name__ == '__main__':
    sys.exit(main())
