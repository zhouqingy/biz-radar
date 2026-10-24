#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把清洗后的业绩 + 企业档案打成云函数用的 data.json（多公司版）。

输出结构：
{
  "updated": "...",
  "units": [ {name, short, abbr, parent, credit, qual:[...], tag, risk, role, quote,
              n, amount, core_n, core_amount, items:[...]}, ... ],
  "index": { "中国联合工程有限公司": 0, ... }
}

云函数侧保持向后兼容：传 ?unit=中国联合工程有限公司 返回旧扁平结构。
用法：/usr/bin/python3 build_fn_data.py [输出路径]
"""
import json
import os
import sys
import time

HOST = 'https://zfcg.nantong.gov.cn'
BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
CLEAN = os.path.join(RAW, 'perf_clean.json')
PROF = os.path.join(RAW, 'units_profile.json')
SCALE = os.path.join(RAW, 'scale_patch.json')
OUT = sys.argv[1] if len(sys.argv) > 1 else '/tmp/fn3/data.json'

PROV = [
    ('广西', '玉林 田东 博白 南宁 柳州'.split()),
    ('新疆', '阿拉尔 乌鲁木齐 南疆 阿克苏'.split()),
    ('河南', '叶县 孟州 平顶山 郑州 舞阳 金海'.split()),
    ('宁夏', '宁东 银川'.split()),
    ('湖北', '潜江 武汉 宜昌 荆门'.split()),
    ('山东', '诸城 龙城 潍坊 济南 青岛 烟台 淄博 临沂 东岳 万华'.split()),
    ('浙江', '绍兴 嘉兴 海宁 宁波 海盐 杭州 巨化 龙德 华川 物产 盛元 众茂 智造谷 舟山 荣盛'.split()),
    ('陕西', '榆林 西安 陕北'.split()),
    ('福建', '福州 漳州 赤湖 联盛'.split()),
    ('广东', '佛山 广州 深圳'.split()),
    ('贵州', '友山 贵阳 大方'.split()),
    ('北京', '寰球 北京'.split()),
    ('江苏', '南通 启东 通州湾 连云港 吕四港 滨海港 淮安 靖江 句容 赣榆 射阳 金陵 梅山 泰州 如东 洋口'.split()),
    ('上海', '上海 石化 金山'.split()),
    ('河北', '定州 保定 邯郸 河北'.split()),
    ('辽宁', '沈阳 沈西 辽宁'.split()),
    ('安徽', '淮南 合肥 宿州 山鹰'.split()),
    ('江西', '永修 南昌 星火'.split()),
    ('内蒙古', '乌海 蒙西 晋中 鄂尔多斯'.split()),
]


def prov_of(proj, owner):
    txt = (proj or '') + (owner or '')
    for pv, kws in PROV:
        for k in kws:
            if k in txt:
                return pv
    return '其他/海外'


def clean_str(v):
    """'null'/'None'/'-' 之类的脏值一律当空串。"""
    if v is None:
        return ''
    s = str(v).strip()
    return '' if s.lower() in ('null', 'none', 'nan', 'undefined', '-', '--') else s


def main():
    clean = json.load(open(CLEAN, encoding='utf-8'))
    prof = json.load(open(PROF, encoding='utf-8'))['units']
    scale = {}
    if os.path.exists(SCALE):
        scale = json.load(open(SCALE, encoding='utf-8'))

    by_unit = {}
    for x in clean['items']:
        by_unit.setdefault(x['unit'], []).append(x)

    order = ['中国联合工程有限公司',
             '中国能源建设集团江苏省电力设计院有限公司',
             '中国电建集团河北省电力勘测设计研究院有限公司']

    units, index = [], {}
    for name in order:
        rows = by_unit.get(name, [])
        p = prof.get(name, {})
        items = []
        for x in sorted(rows, key=lambda z: -(z.get('amt') or 0)):
            sp = scale.get(x.get('proj', ''), {})
            items.append({
                'p': clean_str(x.get('proj')),
                'o': clean_str(x.get('owner')),
                'a': round(x.get('amt') or 0, 6),
                't': clean_str(x.get('amt_txt')),
                'd': clean_str(x.get('date'))[:10],
                's': clean_str(x.get('src')),
                'doc': clean_str(x.get('doc'))[:60],
                'docd': clean_str(x.get('docdate')),
                'sc': sp.get('scale', ''),
                'iv': sp.get('invest', ''),
                'dn': sp.get('done', ''),
                'tk': clean_str(x.get('tk')),
                'core': bool(x.get('core')),
                'est': bool(x.get('date_est')),
                'pv': prov_of(x.get('proj'), x.get('owner')),
            })
        amount = sum(i['a'] for i in items)
        core = [i for i in items if i['core']]
        core_amt = sum(i['a'] for i in core)
        provs = sorted({i['pv'] for i in items} - {'其他/海外'})
        index[name] = len(units)
        units.append({
            'name': name,
            'short': p.get('short', name[:4]),
            'abbr': p.get('abbr', p.get('short', name[:4])),
            'parent': p.get('parent', ''),
            'credit': p.get('credit', ''),
            'base': p.get('base', ''),
            'founded': p.get('founded', ''),
            'qual': p.get('qual', []),
            'tag': p.get('tag', ''),
            'risk': p.get('risk', ''),
            'role': p.get('role', ''),
            'quote': p.get('quote', ''),
            'n': len(items),
            'amount': round(amount, 4),
            'core_n': len(core),
            'core_amount': round(core_amt, 4),
            'nprov': len(provs),
            'nowner': len({i['o'] for i in items if i['o']}),
            'items': items,
        })

    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'src': '南通市公共资源交易平台（含三家投标人同场公示）',
        'units': units,
        'index': index,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

    print('→ %s  (%.1f KB)' % (OUT, os.path.getsize(OUT) / 1024))
    for u in units:
        print('  %-8s 全部 %2d 条 %7.2f 亿 | 主赛道 %2d 条 %7.2f 亿 | %2d 省 · %2d 业主 | 资质 %d 项'
              % (u['abbr'], u['n'], u['amount'], u['core_n'], u['core_amount'],
                 u['nprov'], u['nowner'], len(u['qual'])))


if __name__ == '__main__':
    main()
