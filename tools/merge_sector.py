#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
把「三行业中资出海」采集结果并入海外板块（D.overseas）。

行业分组 grp 新增两个：数据中心、化肥（原有：有色/化工化纤/钢铁/水泥建材/其他制造）
每条都会带上「与我司业务的关联点」，让销售一眼看懂为什么值得跟。
"""
import os, re, json, time

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
DATA = os.path.join(os.path.dirname(ROOT), 'biz-radar', 'data.js')
SRC = os.path.join(RAW, 'sector_oversea.json')

# 行业 → 与我司业务的关联点（写进 desc，页面上直接可读）
LINK = {
    '数据中心': '巨量电力需求，配套光伏+储能+柴油发电机、变配电 EPC；冷却系统带来水处理需求；海岛项目（如巴淡岛）需海水淡化。',
    '化肥': '合成氨/磷化工属高耗能，必配自备热电站（煤/气发电）、余热回收、脱硫脱硝，以及废水零排放。',
    '水泥': '水泥窑余热发电是我司成熟市场；出海项目还需自备电厂、脱硝除尘、余热供暖。',
}
# 公告标题 → 阶段标签
NOISE_TITLE = ['终止', '延期', '取消', '诉讼', '仲裁']


def main():
    if not os.path.exists(SRC):
        print('无 sector_oversea.json，跳过'); return
    src = json.load(open(SRC, encoding='utf-8'))
    s = open(DATA, encoding='utf-8').read()
    d = json.loads(s[s.find('{'):s.rfind('}') + 1])
    ov = d.get('overseas', [])

    have = set((x.get('title') or '')[:40] for x in ov)
    added = 0
    for x in src.get('items', []):
        t = x['t']
        if any(w in t for w in NOISE_TITLE):
            continue                      # 终止/延期类不是机会
        k = t[:40]
        if k in have:
            continue
        have.add(k)
        sec = x['sector']
        ov.append({
            'name': x['sec'] or '未披露', 'grp': sec, 'kw': x['sec'],
            'title': t, 'date': x['d'], 'tag': '海外投资',
            'desc': '%s（%s）%s 【与我司关联】%s' % (x['sec'], x['geo'], t, LINK.get(sec, '')),
            'url': x['url'], 'rel': 6, 'src': '巨潮公告',
        })
        added += 1

    # 2026-10-19 修：原来直接写 data.js，结果每次 update_weekly.py 全量重建就被冲掉
    # （竞对 65→59、海外 76→71）。现在改为写入持久源 raw/oversea_extra.json，
    # build_web.py 每轮重建都会读它并入，增量不会丢。
    EXTRA = os.path.join(RAW, 'oversea_extra.json')
    old = []
    if os.path.exists(EXTRA):
        _e = json.load(open(EXTRA, encoding='utf-8'))
        old = _e.get('items', _e) if isinstance(_e, dict) else _e
    keys = set((x.get('title') or x.get('t') or '')[:40] for x in old)
    new = [x for x in ov if (x.get('title') or '')[:40] not in keys]
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': old + new},
              open(EXTRA, 'w', encoding='utf-8'), ensure_ascii=False)

    from collections import Counter
    print('持久源 oversea_extra.json：原有 %d + 本次 %d → 共 %d 条'
          % (len(old), len(new), len(old) + len(new)))
    print('行业分组:', dict(Counter(x.get('grp') for x in old + new)))
    print('→ 需再跑一次 update_weekly.py（或 build_web.py）才会进入页面')


if __name__ == '__main__':
    main()
