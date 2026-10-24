#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
把微信线索并入档案：
  1) 竞对动态 → 写入对应单位档案的 recent（近期动态）
  2) 行业动态 → 写入 industry.json 的 trends（标签「微信快讯」）

安全红线：检索是「相关度」匹配，命中的文章未必真是那家单位的新闻
（实测出现过「万德斯中标」被挂在「煤炭工业合肥」检索词下）。
所以写入竞对档案前**必须校验：单位简称要真实出现在标题或摘要里**，
否则宁可丢弃——往对手档案里写错业绩比不写更糟。
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
LEADS = os.path.join(RAW, 'wechat_leads.json')
IND_PATH = os.path.join(RAW, 'industry.json')
PAR_PATH = os.path.join(RAW, 'partners.json')

BIZ_KW = ['热电', '余热', '垃圾焚烧', '生物质', '煤气', '脱硫', '脱硝', '污水', '海水淡化',
          '修复', '光伏', '储能', '发电', 'EPC', '锅炉', '除尘', '超低排放', '固废', '污泥',
          '供热', '汽轮机', '机组', '中标', '签约', '开工', '投产', '核准']

# 业绩类事件词：单位名只要在摘要里出现过就写入，会混进「组织架构」「考察交流」
# 「某某市大项目汇总」这类噪音。所以要求——单位名必须出现在**标题**里，
# 且标题或摘要必须含业绩事件词，两条同时满足才写进档案。
EVENT_KW = ['中标', '预中标', '签约', '签订', '开工', '投产', 'EPC', '总承包', '合同',
            '候选人', '拿下', '承接', '承建', '完成']


def load(p, default):
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception as e:
        print('[WARN] %s 解析失败：%s' % (os.path.basename(p), e))
        return default


def norm(s):
    return re.sub(r'[（）()\s]', '', s or '')


def recent_of(x):
    r = x.get('recent')
    if not r:
        return []
    if isinstance(r, str):
        return [{'title': r, 'date': '', 'url': x.get('url', '')}]
    return list(r)


def dump_recent(x, arr):
    """按日期倒序、去重（同标题只留一条），每家最多 5 条"""
    seen, out = set(), []
    for r in sorted(arr, key=lambda z: (z.get('date') or ''), reverse=True):
        t = (r.get('title') or r.get('t') or '').strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(r)
    x['recent'] = out[:5]


def main():
    if not os.path.exists(LEADS):
        print('（无 wechat_leads.json，跳过）')
        return
    leads = load(LEADS, {}).get('items', [])
    if not leads:
        print('（微信线索为空，跳过）')
        return

    ind = load(IND_PATH, {})
    par = load(PAR_PATH, [])
    if isinstance(par, dict):
        par = par.get('partners', [])
    comps = ind.get('competitors', []) if isinstance(ind, dict) else []

    # ---------- 1. 竞对喜报 → 档案 recent ----------
    n_unit, skip = 0, 0
    for x in leads:
        if x.get('cat') != '竞对动态':
            continue
        unit = norm(x.get('unit') or '')
        if len(unit) < 3:
            continue
        title_n = norm(x.get('t') or '')
        body = (x.get('t') or '') + (x.get('snip') or '')
        if unit not in title_n:
            skip += 1                      # 单位名没出现在标题 → 多为汇总快讯/误命中，丢弃
            continue
        title = x.get('t') or ''
        if not any(k in title for k in EVENT_KW):
            skip += 1                      # 标题无业绩事件词 → 多为介绍/招聘/会议类，丢弃
            continue
        entry = {'title': (x.get('t') or '').strip(),
                 'amount': '',
                 'date': x.get('d') or '',
                 'region': '微信·%s' % (x.get('src') or ''),
                 'url': x.get('url') or ''}
        hit = False
        for pool in (comps, par):
            for u in pool:
                if unit in norm(u.get('name') or ''):
                    arr = recent_of(u) + [entry]
                    dump_recent(u, arr)
                    hit = True
                    n_unit += 1
                    break
            if hit:
                break
    print('[竞对喜报] 写入 %d 条到单位档案（因标题不含单位名而丢弃 %d 条误命中）' % (n_unit, skip))

    # ---------- 2. 行业动态 → trends ----------
    trends = ind.get('trends', []) if isinstance(ind, dict) else []
    have = {norm(t.get('title') or '') for t in trends}
    n_tr = 0
    for x in leads:
        if x.get('cat') != '行业动态':
            continue
        t = (x.get('t') or '').strip()
        snip = (x.get('snip') or '').strip()
        if not t or len(snip) < 20:
            continue
        if not any(k in (t + snip) for k in BIZ_KW):
            continue                       # 与业务无关（如招聘、会议通知）不收
        if norm(t) in have:
            continue
        trends.append({'title': t,
                       'desc': snip[:120],
                       'date': x.get('d') or '',
                       'source': '微信·%s' % (x.get('src') or ''),
                       'tag': '微信快讯',
                       'url': x.get('url') or ''})
        have.add(norm(t))
        n_tr += 1
    trends.sort(key=lambda z: (z.get('date') or ''), reverse=True)
    if isinstance(ind, dict):
        ind['trends'] = trends[:80]
    print('[行业动态] 新增 %d 条（trends 合计 %d 条）' % (n_tr, len(ind.get('trends', []))))

    json.dump(ind, open(IND_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(par, open(PAR_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已写回 industry.json / partners.json')


if __name__ == '__main__':
    main()
