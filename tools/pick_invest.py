#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从审批备案里挑出「真值得进商机库」的项目（2026-11-04）

用户的原话：
    1255 条根本就没有必要全部都进主库嘛，还是进一些对于我们来说有用的一些项目就行了。
    ……这个并不是项目越多越好嘛，你越多哎看的人头晕眼花的其实也不是很好，
    主要还是按照那个实用性嘛。

所以这里不是「能进就进」，而是**按可用性分档，只放 A/B 两档**：

  A 已进交易  —— 商机库里能查到招标/中标公告的。这类其实商机库已经有了，
                 审批库的价值只是补一条「这个项目还通过了什么审批」，不新增卡片。
  B 已开工/核准 —— ★ 这才是真正有价值的：拿到了核准/施工许可，但商机库里搜不到。
                 意味着**还没招标、马上要招标**，是最早的介入点。
  C 停在备案  —— 只有一纸备案，可能两年不动工。648 条，全部不进。
  弃           —— 光伏、设备生产、管线接入、装修这类非工程实体。509 条。

B 档为什么可靠
--------------
「核准」和「施工许可」是审批链条上最靠后的两道 —— 拿到它们说明钱和地都落实了。
对比「备案」：备案只是立项告知，浙江一年几十万条，绝大多数躺在那里不动。
实测 B 档 73 条里全是热电联产、垃圾焚烧、超低排放改造、余热回收，
名字本身就是我们的业务，不需要再猜。
"""
import json
import os
import re
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

TRADE = ('招标公告', '招标计划', '中标候选人公示', '中标结果公示', '变更公告')
# 已经实质开工/批下来的审批事项
HARD = ('施工许可', '规划许可', '初步设计', '核准', '建设工程（含临时建', '建设工程规划',
        '用地预审', '竣工验收', '竣工规划')

# 工程实体词：证明这是个「要建的东西」，不是管线接入/设备生产/装修
ENG = ('热电联产', '集中供热', '供热工程', '热网', '蒸汽管道', '余热', '余压', '脱硫',
       '脱硝', '超低排放', '污水处理', '污水厂', '水处理', '中水回用', '零排放',
       '垃圾焚烧', '焚烧发电', '固废', '飞灰', '污泥', '背压', '锅炉', '汽轮',
       '自备电厂', '能源站', '生物质', '资源综合利用', '热力', '发电', '电力',
       '烟气', '烟尘', '节能改造', '提标改造', '扩建', '技改')
# 反例：这些名字里带业务词，但不是工程
# 实测栽过：「船用层压木和船舶脱硫系统生产项目」——名字里有「脱硫」，但这是
# 生产脱硫设备的工厂，不是脱硫工程。所以「生产」「制造」「加工」一律先排除。
NOISE = ('年产', '生产线', '设备生产', '生产项目', '生产', '制造', '加工', '研发',
         '销售', '门店', '办公', '装修', '宿舍', '厂房新建', '充电', '加气',
         '加油站', '光伏', '储能', '数据中心', '物流', '养殖', '种植', '医药',
         '医院', '实验室', '学校', '幼儿园')


def is_eng(name):
    n = name or ''
    if any(w in n for w in NOISE):
        return False
    return any(w in n for w in ENG)


def pick(matched_path=None):
    p = matched_path or os.path.join(ROOT, 'raw', 'invest_matched.json')
    d = json.load(open(p, encoding='utf-8'))['items']
    A, B = [], []
    for x in d:
        st = (x.get('db') or {}).get('st') or ''
        ph = x.get('phase') or ''
        x['_eng'] = is_eng(x['name'])
        if st in TRADE:
            x['tier'] = 'A'
            x['why'] = '商机库已有 ' + st
            A.append(x)
        elif x['_eng'] and any(w in ph for w in HARD):
            x['tier'] = 'B'
            x['why'] = '已到「%s」且库内无公告 ⇒ 未招标' % ph
            B.append(x)
        else:
            x['tier'] = ''
    # B 档按「审批走得多深」+「事项条数」排序：施工许可 > 规划许可 > 初步设计 > 核准
    DEPTH = {'施工许可': 0, '建设工程（含临时建': 1, '建设工程规划': 1, '竣工': 2,
             '规划许可': 3, '初步设计': 4, '用地预审': 5, '核准': 6}
    B.sort(key=lambda x: (DEPTH.get(x['phase'], 9), -len(x['items']), x['date_last']))
    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'total_raw': len(d),
        'nA': len(A), 'nB': len(B),
        'A': A, 'B': B,
    }
    return out


def main():
    o = pick()
    p = os.path.join(ROOT, 'raw', 'invest_pick.json')
    json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('源 %d 条 → A %d / B %d，写入 %s' % (o['total_raw'], o['nA'], o['nB'], p))
    from collections import Counter
    print('B 档审批阶段分布', dict(Counter(x['phase'] for x in o['B']).most_common()))
    print('B 档省份', dict(Counter(x['prov'] for x in o['B'])))
    print('\nB 档前 12 条:')
    for x in o['B'][:12]:
        print('  %s %-8s %-10s %s' % (x['prov'], x['date_last'], x['phase'][:10], x['name'][:52]))


if __name__ == '__main__':
    main()
