# -*- coding: utf-8 -*-
"""把 data.entprobe.js 里「同一家单位的两份档案」并成一份（2026-11-04）

为什么做这件事
--------------
用户点海外客户卡片看详情，17 家里有 16 家显示「这家还没有企业档案」，
但其中力勤、海亮、润泽其实**有**档案，只是档案建在另一个名字下：

    名单  宁波力勤资源科技股份有限公司   → 归一「宁波力勤资源科技」
    档案  力勤资源 / 力勤资源科技股份有限公司（两份！）

两份档案记的是同一批印尼 OBI 电厂项目，一份日期粗（2024-09）、金额空，
另一份细（2026、带机组号）。所以不是"没抓到"，是"抓了两次、各存各的"。

合并规则（保守，宁可少并不错并）
--------------------------------
1. 归一后名字相等 → 同一家（红狮控股 / 红狮控股集团有限公司 这种）
2. 归一后互相是前缀、且短的一方 ≥ 4 字 → 同一家
   （力勤资源 ⊂ 力勤资源科技 → 同一家；中金 ⊄ 中金数据集团 之外还有别的，
    两字短名一律不并，避免把「中金」并到不相关的公司）
3. 合并不删记录：按项目名前 16 字去重，新的补齐旧记录里空着的字段
4. 摘要 / 城市 / 类型取「非空的那份」，两份都有就留字数多的
5. 保留名字最长的那份的 n 作为主名（列表里写全称的多）

CLI
---
    python3 merge_entprobe_firms.py --dry-run     # 只打印会并哪些，不改文件
    python3 merge_entprobe_firms.py               # 真写回 data.entprobe.js
"""
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(BASE, '..', 'biz-radar', 'data.entprobe.js')

# 业务限定词：多出来的名字里带这些，说明是子公司/分公司/另一个业务主体，不能并
SCOPE_W = ('环境', '环保', '新材', '新材料', '建设', '工程', '电力', '能源', '发展',
           '投资', '装备', '材料', '水泥', '金源', '分公司', '分厂', '设计', '研究院',
           '贸易', '物流', '矿业', '资源', '实业', '控股')
# 地名：多出来的是地名 → 分公司/区域公司（国能龙源环保【南京】有限公司），不能并
CITY_W = ('北京', '上海', '天津', '重庆', '南京', '苏州', '无锡', '常州', '南通', '徐州',
          '盐城', '扬州', '杭州', '宁波', '温州', '绍兴', '嘉兴', '金华', '台州', '湖州',
          '合肥', '芜湖', '马鞍山', '铜陵', '安庆', '蚌埠', '淮南', '淮北', '滁州', '宣城',
          '广州', '深圳', '武汉', '长沙', '成都', '西安', '济南', '青岛', '郑州', '太原',
          '唐山', '邯郸', '石家庄', '沈阳', '大连', '福州', '厦门', '南昌', '昆明', '贵阳')


def norm(s):
    s = re.sub(r'[（(][^）)]*[）)]', '', str(s or '')).replace(' ', '')
    for _ in range(3):
        s2 = re.sub(r'(有限责任公司|股份有限公司|有限公司|集团|总公司|公司)$', '', s)
        if s2 == s:
            break
        s = s2
    return s


def same(a, b):
    """a、b 是否同一家（a 是已归并组的主名，b 是待判断的名字）

    ⚠ 2026-11-04 踩过的坑：只按「前缀包含」并，会把
       上海建工集团股份有限公司  ⊃ 上海建工环境科技有限公司
    并成一家 —— 可这是母公司和它的环境子公司，业绩、口径完全不同，
    并在一起等于替用户编了一条「上海建工做过环境科技」的结论。
    所以先拦「层级词」：一方比另一方多出 环境/环保/新材/建设/工程/电力/
    能源/科技/发展/投资/装备/材料 这类业务限定词时，判为不同主体。
    真正的简称（力勤资源 → 力勤资源科技股份有限公司）多出来的是「科技」
    这种非业务限定词，不受影响。
    """
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) < 4 or not long_.startswith(short):
        return False
    # 多出来的那截里带业务限定词 → 子公司/关联公司，不是简称
    extra = long_[len(short):]
    if any(w in extra for w in SCOPE_W):
        return False
    if any(w in extra for w in CITY_W):
        return False
    return True


def pick(a, b):
    """两个字段都有时，留字数多的（信息更全）"""
    a, b = a or '', b or ''
    return a if len(a) >= len(b) else b


def merge_firm(main, other):
    """把 other 并进 main，返回新增记录数"""
    have = {re.sub(r'\s+', '', str(h.get('p') or ''))[:16]: h for h in main.get('h') or []}
    add = 0
    for r in other.get('h') or []:
        key = re.sub(r'\s+', '', str(r.get('p') or ''))[:16]
        t = have.get(key)
        if t:
            # 老记录里空着的字段，用新的补上；有值的不覆盖
            for k in ('a', 'a0', 'a1', 'a2', 'd', 'st', 'who', 'u', 'sd', 'k', 'ov', 'whr', 'by', 's'):
                if r.get(k) not in (None, '', '—') and t.get(k) in (None, '', '—'):
                    t[k] = r[k]
            # 日期精确度：2024-09 → 2026 这种，留更精确的（长度更长）
            if len(str(r.get('d') or '')) > len(str(t.get('d') or '')):
                t['d'] = r['d']
            continue
        main.setdefault('h', []).append(dict(r))
        have[key] = r
        add += 1
    for k in ('city', 'ty', 'sm', 'why', 'cat'):
        main[k] = pick(main.get(k), other.get(k))
    return add


def main():
    dry = '--dry-run' in sys.argv
    raw = open(JS, encoding='utf-8').read()
    head, i, j = raw[:raw.find('{')], raw.find('{'), raw.rfind('}')
    d = json.loads(raw[i:j + 1])
    firms = d['firms']

    # 长的名字先做组头（全称优先当主名）
    order = sorted(range(len(firms)), key=lambda k: -len(norm(firms[k]['n'])))
    groups, used = [], set()
    for idx in order:
        if idx in used:
            continue
        g = [idx]
        used.add(idx)
        for k in order:
            if k in used:
                continue
            if same(firms[idx]['n'], firms[k]['n']):
                g.append(k)
                used.add(k)
        groups.append(g)

    merged = [g for g in groups if len(g) > 1]
    print('档案 %d 份 → 归并后 %d 份（合并 %d 组）' % (len(firms), len(groups), len(merged)))

    out, n_add = [], 0
    for g in groups:
        # 组内按记录数降序，记录最多的当底
        g2 = sorted(g, key=lambda k: -len(firms[k].get('h') or []))
        main_f = json.loads(json.dumps(firms[g2[0]], ensure_ascii=False))
        for k in g2[1:]:
            n_add += merge_firm(main_f, firms[k])
            print('  并：%-22s → %-22s  +%d 条' % (
                firms[k]['n'][:22], main_f['n'][:22], len(firms[k].get('h') or [])))
        out.append(main_f)

    print('合并后总记录 %d 条（净增 %d 条不重复的）' % (
        sum(len(f.get('h') or []) for f in out), n_add))

    if dry:
        print('（dry-run，未写文件）')
        return

    d['firms'] = out
    body = json.dumps(d, ensure_ascii=False, indent=1)
    open(JS, 'w', encoding='utf-8').write(head + body + ';\n')
    print('已写回 %s（%d B）' % (JS, os.path.getsize(JS)))


if __name__ == '__main__':
    main()
