# -*- coding: utf-8 -*-
"""供应商分 A/B 类（2026-10-21 用户确认口径）

用户原话：
「现在供应商有两种，第一个业主供应商是和我一样的设计院、中冶长天、中冶华天、
 中冶赛迪、中冶京诚这类，这就需要找他们的业绩，第二类完全是给业主供货的不参与
 EPC 招标，这类供应商我们就能联系他们跟业主对接，也就是看他们跟业主关系如何，
 我们该去找谁」

2026-10-21 用户再次确认后改口径（重要，别按老思路改回去）：
「建材商和施工单位也可以啊，这个主要还是看谁参与这个业主的项目多就行，就知道
 他跟这个业主关系好，B类是不需要单独列出来的，这个是跟业主画像放在一起的，
 点进去有一个A、B类的情况，当然A类也出现在竞争对手或合作伙伴那一块」

所以：
  · **不单独开「供应商」页**。供应商挂在**业主画像**里，点业主进去分 A/B 两类看
  · A 类 = 设计院 / 工程公司 / 建设集团 —— 同行也是对手，会抢 EPC 总包，
          同时还要出现在「同业与伙伴」那块
  · B 类 = 建材商 / 施工单位 / 设备商 —— 不投 EPC，但参与得多说明跟业主关系好，
          是我们渗透这个业主时「该找谁引路」的答案
  · 关系深度判据 = **该供应商在这个业主的项目里出现了几次**，
    不是全局排名。一家设计院全库 10 个标，但在这个业主身上只 1 次；
    一家本地安装公司在这个业主身上 6 次——后者对我们渗透更管用。

分类只能靠名字，必然有误判。所以规则要「宁可漏判到 B，不要错判到 A」——
A 类名单后面要拿出来当对手看的，混进去设备商是硬伤。

输出：raw/supplier_ab.json
"""

import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'raw', 'owner_graph.json')
DST = os.path.join(ROOT, 'raw', 'supplier_ab.json')

# ══════════════════════════════════════════════════════════════════════
# A 类判据：设计院 / 工程公司 / 建设集团
# 按「强特征 → 弱特征」排列，匹配到就直接判 A
# ══════════════════════════════════════════════════════════════════════
A_STRONG = [
    # 设计院（最强特征，几乎不会误判）
    r'设计院', r'设计研究院', r'勘测设计', r'电力设计', r'建筑设计', r'热工研究',
    r'设计研究总院', r'规划勘测设计', r'工程咨询设计', r'设计集团',
    # 冶金系统的工程公司（用户点名：中冶长天、华天、赛迪、京诚、南方、恩菲）
    r'中冶', r'中钢', r'中色', r'恩菲', r'赛迪', r'京诚', r'长天', r'华天',
    r'中国有色工程', r'中国恩菲', r'有色(冶金)?设计',
    # 大型建筑/电力施工央企（2026-10-21 补：这些原本掉进「其他设备」了）
    r'中铁', r'中建', r'中交', r'中电建', r'中国电建', r'中国能建', r'中能建',
    r'宝冶', r'二十冶', r'十九冶', r'十七冶', r'二十冶', r'中国一冶', r'中国五冶',
    r'建工集团', r'省建工', r'市建工', r'建工有限',
    # 电力建设 / 能源建设
    r'电力建设', r'电建', r'能建', r'能源建设', r'电力工程',
    # 工程集团
    r'工程集团', r'建设集团', r'工程总承包', r'工程局', r'建设发展集团',
    r'工程建设', r'工程科技', r'工程技术',
    # 环保/环境类工程公司（它们也投 EPC，是对手）
    r'环保集团', r'环境集团', r'环境科技(有限)?公司', r'环保科技(股份|集团)',
    r'龙源环保', r'康恒环境', r'高能时代', r'金科环境', r'卓锦环保',
    r'环境修复', r'生态环境科技', r'市政工程', r'市政设计',
    # 研究院所（也做 EPC 总包）
    r'研究院', r'研究所', r'勘察院', r'研究开发中心', r'技术研究中心',
    # 2026-10-21 补：剩下的未匹配名单里，这些其实都是工程/施工单位
    r'安装', r'建设发展', r'市政建设', r'市政服务', r'电力技术', r'电力',
    r'新能源(科技|技术|有限)', r'智慧能源', r'综合能源', r'清洁能源',
    r'地质', r'水文', r'勘查', r'建工', r'建筑', r'路桥', r'水利',
    r'环保(有限|股份)', r'环境(有限|股份)', r'生态(科技|环境|有限)',
    r'治理', r'节能(工程|科技|服务)',
]

A_WEAK = [
    # 「有限公司」结尾且带工程 —— 弱特征，需要配合排除词一起用
    r'工程(有限)?公司', r'工程技术(有限)?公司', r'工程科技(有限)?公司',
    r'安装(有限)?公司', r'施工(有限)?公司', r'建设(有限)?公司',
    r'环保工程', r'能源工程', r'热电工程', r'动力工程',
]

# 这些词出现就说明是设备/产品商，不能判 A
B_MARK = [
    r'锅炉', r'汽轮', r'发电机', r'电机', r'风机', r'泵业', r'阀门', r'仪表',
    r'重工', r'装备', r'机械', r'设备', r'制造', r'材料', r'耐火', r'窑炉',
    r'节能科技', r'环保科技', r'环保设备', r'净化设备', r'除尘设备',
    r'电缆', r'电器', r'仪表', r'自控', r'变频', r'换热器', r'压力容器',
    r'钢材', r'管材', r'密封', r'轴承', r'滤料', r'药剂',
]

# ══════════════════════════════════════════════════════════════════════
# B 类细分：便于页面上分组展示「该找谁引路」
# ══════════════════════════════════════════════════════════════════════
B_TYPES = [
    ('锅炉',     [r'锅炉']),
    ('汽机',     [r'汽轮', r'汽机', r'透平']),
    ('发电机',   [r'发电机', r'电机']),
    ('窑炉',     [r'窑炉', r'炉窑', r'加热炉', r'热工设备']),
    ('环保设备', [r'除尘', r'脱硫', r'脱硝', r'环保设备', r'净化', r'过滤', r'滤']),
    ('换热/压力容器', [r'换热', r'压力容器', r'容器', r'冷却塔']),
    ('通用机电', [r'风机', r'泵', r'阀门', r'电机', r'起重', r'输送']),
    ('材料',     [r'材料', r'钢材', r'管材', r'耐火', r'保温']),
    ('自控仪表', [r'仪表', r'自控', r'自动化', r'变频']),
]


def split_union(name):
    """从联合体全串里取出牵头单位。

    实测公告里的写法极其混乱，光分隔符就有：、 , ， / ； ; + ＋ | 以及
    「联合体：」「（牵头单位）」「（成员方）」这类标注。
    不拆的话，A 类名单里会出现
    「中国联合工程有限公司;浙江顺泰工程建设有限公司」这种双名条，
    既算不准战绩，也没法当对手看。
    """
    s = (name or '').strip()
    if not s:
        return s
    # ⚠ 这里踩过大坑，别再改成「按括号直接切」：
    #   「华光环保能源(西安)设计研究院有限公司」里的括号是**公司名的一部分**
    #   （表示分支机构所在地），不是联合体标注。按括号切会把公司名切碎成
    #   「华光环保能源」，直接毁掉 100 多条记录。
    #   只有括号里出现「联合体/牵头/成员/中标候选人」这类字样时，括号才是标注。
    s = re.sub(r'[（(][^）)]*(联合体|牵头|成员|第[一二三]|中标候选人)[^）)]*[）)]', '|', s)
    parts = [p.strip().rstrip('等').strip() for p in re.split(r'[、,，/;；+＋|]', s)]
    for p in parts:
        p = re.sub(r'^(第[一二三]中标候选人|中标人|成交供应商|牵头方|牵头单位)\s*[:：]?\s*', '', p).strip()
        if len(p) >= 4:
            return p
    return s


def _any(pat_list, s):
    for p in pat_list:
        if re.search(p, s):
            return True
    return False


def b_type(name):
    for t, pats in B_TYPES:
        if _any(pats, name):
            return t
    return '其他设备'


def classify(name):
    """返回 (类别, 依据)

    类别：'A' 设计院/工程公司  'B' 设备供应商
    判定顺序很关键：先看 B 标记，命中就判 B，避免「XX锅炉工程有限公司」
    这种名字被 A_WEAK 的「工程有限公司」抢走。
    """
    nm = (name or '').strip()
    if not nm:
        return 'B', '空名'

    # 1) 强 A 特征优先（设计院/中冶/电建这类，即使名字带「设备」也是 A）
    for p in A_STRONG:
        if re.search(p, nm):
            # 唯独「设计院」后面跟「设备」这种不存在，不用特殊处理
            return 'A', '强特征:%s' % p

    # 2) 有设备标记 → B
    for p in B_MARK:
        if re.search(p, nm):
            return 'B', '设备标记:%s' % p

    # 3) 弱 A 特征
    for p in A_WEAK:
        if re.search(p, nm):
            return 'A', '弱特征:%s' % p

    return 'B', '未匹配(默认B)'


def main():
    g = json.load(open(SRC, encoding='utf-8'))
    sp = g.get('suppliers') or []

    out = []
    stat = {'A': 0, 'B': 0}
    reason_cnt = {}
    for x in sp:
        raw_nm = x.get('name') or ''
        nm = split_union(raw_nm)
        cls, why = classify(nm)
        stat[cls] += 1
        reason_cnt[why] = reason_cnt.get(why, 0) + 1
        y = dict(x)
        # 保留原始串（联合体全串），页面上要展示「它还跟谁组队投过」
        if nm != raw_nm:
            y['raw'] = raw_nm
        y['name'] = nm
        y['cls'] = cls
        y['why'] = why
        if cls == 'B':
            y['bt'] = b_type(nm)
        out.append(y)

    out.sort(key=lambda z: (z['cls'] != 'A', -(z.get('n') or 0), -(z.get('amt') or 0)))

    # ── 给业主画像的 sups 打 A/B 标记（用户要求：供应商跟业主画像放一起）──
    # owner_graph.json 里每个业主已经带 sups 列表（该业主下谁中过标、几次、多少钱），
    # 这里只需要按名字把类别填进去。命中不了的（名字带联合体全串、括号注释等）
    # 用 split_union 归一化后再查一次。
    CLS_MAP = {z['name']: z['cls'] for z in out}
    for z in out:
        if z.get('raw'):
            CLS_MAP.setdefault(z['raw'], z['cls'])

    def lookup(nm):
        if nm in CLS_MAP:
            return CLS_MAP[nm]
        u = split_union(nm)
        if u in CLS_MAP:
            return CLS_MAP[u]
        c, _ = classify(u)
        return c

    g2 = json.load(open(SRC, encoding='utf-8'))
    n_a = n_b = n_x = 0
    for o in g2.get('owners') or []:
        sups = o.get('sups') or []
        if not sups:
            continue
        for sp1 in sups:
            _raw1 = sp1.get('name') or ''
            c = lookup(_raw1)
            sp1['cls'] = c
            # 联合体全串拆成牵头单位，页面才看得清是谁。原串留着备查。
            _u1 = split_union(_raw1)
            if _u1 and _u1 != _raw1:
                sp1['raw'] = _raw1
                sp1['name'] = _u1
            if c == 'A':
                n_a += 1
            else:
                n_b += 1
            # 关系深度：参与次数（这是用户定的判据），金额作为辅助
            sp1['rel'] = (sp1.get('n') or 0)
        # ── 同一家业主下的供应商去重（2026-10-21）──
        # 上游 build_owner_graph.py 是按「中标单位原始字符串」建的图，
        # 而公告里同一家公司有全角/半角括号两种写法：
        #   「华光环保能源（西安）设计研究院有限公司」
        #   「华光环保能源(西安)设计研究院有限公司」
        # 结果在南通美亚热电这一个业主下面被算成两家，各 1 次合作。
        # 这里按「归一化名称」（括号统一成半角、去掉空格）合并，次数相加、金额相加。
        _merged = {}
        _order = []
        for sp1 in sups:
            _k = re.sub(r'\s+', '', (sp1.get('name') or '').replace('（', '(').replace('）', ')'))
            if _k in _merged:
                _m = _merged[_k]
                _m['n'] = (_m.get('n') or 0) + (sp1.get('n') or 0)
                _m['amt'] = round((_m.get('amt') or 0) + (sp1.get('amt') or 0), 4)
                # 保留最近一次时间
                if (sp1.get('last') or '') > (_m.get('last') or ''):
                    _m['last'] = sp1['last']
                # 两边的项目清单拼起来
                _m['items'] = (_m.get('items') or []) + (sp1.get('items') or [])
            else:
                _merged[_k] = dict(sp1)
                _order.append(_k)
        sups = [_merged[k] for k in _order]
        o['sups'] = sups
        o['nSup'] = len(sups)
        # 该业主下 A/B 各几家
        o['nSupA'] = sum(1 for x in sups if x.get('cls') == 'A')
        o['nSupB'] = sum(1 for x in sups if x.get('cls') == 'B')
        n_x += 1
    json.dump(g2, open(SRC, 'w', encoding='utf-8'), ensure_ascii=False)
    print('业主画像 sups 打标：%d 个业主 · A类条目 %d · B类条目 %d'
          % (n_x, n_a, n_b))

    json.dump({'total': len(out), 'stat': stat, 'items': out},
              open(DST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print('供应商 %d 家 → A 类(设计院/工程公司，同行也是对手) %d · B 类(建材/施工/设备) %d'
          % (len(out), stat['A'], stat['B']))
    print('\n判据分布：')
    for k, v in sorted(reason_cnt.items(), key=lambda z: -z[1])[:12]:
        print('  %-22s %d' % (k, v))

    print('\n== A 类（前 30，同行也是对手）==')
    for z in [z for z in out if z['cls'] == 'A'][:30]:
        print('  %2d次 %7.2f亿 %-40s %s' % (z.get('n', 0), z.get('amt', 0),
                                            (z['name'] or '')[:40], z['why']))
    print('\n== B 类按类型 ==')
    from collections import Counter
    bc = Counter(z.get('bt') for z in out if z['cls'] == 'B')
    for k, v in bc.most_common():
        print('  %-14s %d' % (k, v))


if __name__ == '__main__':
    main()
