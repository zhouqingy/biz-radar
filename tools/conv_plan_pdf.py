# -*- coding: utf-8 -*-
"""把规划 PDF 的提取结果（raw/plan_pdf/*.json）转成 raw/early/ 的入库格式。

为什么要单独一步
────────────────
 crawl_fgw_plan.py 走的是省发改委批复（HTML，覆盖全省但只有企业名+项目方向）。
 规划 PDF 附件信息更全：**投资额、装机规模、投运年份、技术方案**全都有，
 但得先人工/半自动拿到 PDF 并解析。
 两条路的数据最后都要汇到 raw/early/，由 build_data.py 统一收进「立项线索」层。

输入约定（raw/plan_pdf/*.json）
──────────────────────────
  meta.region / meta.plan_period / meta.src_files
  resource_projects[]: name/owner/kind/scale/period/invest_wan/online/tech/resource/benefit
  chp_sources[]:       area/name/now/plan/cap_tph/type
  surplus_resource_owners[]: name/industry/surplus

输出：raw/early/plan-pdf-<同名>.json，early='热电规划'（→ build_data 映射为立项公示）

只收有动作的热源点（新建/技改/改造/改扩建/替代），「维持不变」的不收——没有商机。
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(ROOT, 'raw', 'plan_pdf')
EARLY_DIR = os.path.join(ROOT, 'raw', 'early')

# 有动作才收；「维持不变」「本公司在列」只是现状描述，不产生招标
ACT_TYPES = ('新建', '技改', '改造', '改扩建', '替代', '在建')


def conv(fn):
    d = json.load(open(fn, encoding='utf-8'))
    meta = d.get('meta') or {}
    rg = (meta.get('region') or '').split()[0] or '江苏'
    city = (meta.get('region') or '').split()[-1] if ' ' in (meta.get('region') or '') else ''
    period = meta.get('plan_period') or ''
    src = (meta.get('src_files') or [''])[0]
    out = []

    # ① 资源综合利用发电重点项目（有投资额、装机、投运年份，最值钱）
    for p in (d.get('resource_projects') or []):
        amt = (p.get('invest_wan') or 0) * 1e4 or None      # 万元 → 元
        snip = '省/市规划重点项目（%s 规划）。%s；资源：%s；%s' % (
            period, p.get('tech') or '', p.get('resource') or '', p.get('benefit') or '')
        out.append({
            't': p.get('name') or '',
            'rg': rg, 'city': city, 'buyer': p.get('owner') or '',
            'amt': amt,
            'amtTxt': ('总投资约 %s 万元' % p['invest_wan']) if p.get('invest_wan') else '',
            'd': meta.get('pub_date') or '', 'dl': '',
            'p': '发改委规划附件·PDF', 'url': meta.get('pub_url') or '',
            'snip': snip[:300], 'mode': p.get('scale') or '',
            'early': '热电规划',
            'expect': (p.get('online') or p.get('period') or ''),
        })

    # ② 热电联产热源点里「有动作」的
    for s in (d.get('chp_sources') or []):
        ty = (s.get('type') or '').strip()
        if not any(a in ty for a in ACT_TYPES):
            continue
        out.append({
            't': '%s%s项目（%s）' % (s.get('name') or '', '热电联产', ty),
            'rg': rg, 'city': city, 'buyer': s.get('name') or '',
            'amt': None, 'amtTxt': '',
            'd': meta.get('pub_date') or '', 'dl': '',
            'p': '发改委规划附件·PDF', 'url': meta.get('pub_url') or '',
            'snip': '%s 规划热源点（%s）。现状：%s；规划：%s；供热能力 %s t/h' % (
                period, s.get('area') or '', s.get('now') or '', s.get('plan') or '',
                s.get('cap_tph') or ''),
            'mode': '%s t/h' % s['cap_tph'] if s.get('cap_tph') else '',
            'early': '热电规划', 'expect': period,
        })

    # ③ 富余资源没利用的企业（潜在项目，还没立项）
    #    ⚠ ①②已点名的企业不再重复收（规划里同一家既列了项目又列了富余资源）
    seen_buyer = {r['buyer'] for r in out}
    for o in (d.get('surplus_resource_owners') or []):
        nm = (o.get('name') or '').strip()
        if nm in seen_buyer:
            continue
        # 同一家的不同写法（母公司名 vs 项目公司名），前 4 字一致视为同一主体
        if any(len(b) >= 4 and len(nm) >= 4 and b[:4] == nm[:4] for b in seen_buyer):
            continue
        out.append({
            't': '%s 余能综合利用发电（规划富余资源待开发）' % (o.get('name') or ''),
            'rg': rg, 'city': city, 'buyer': o.get('name') or '',
            'amt': None, 'amtTxt': '',
            'd': meta.get('pub_date') or '', 'dl': '',
            'p': '发改委规划附件·PDF', 'url': meta.get('pub_url') or '',
            'snip': '%s 规划资源量调查（%s行业）：%s' % (
                period, o.get('industry') or '', o.get('surplus') or ''),
            'mode': '', 'early': '热电规划', 'expect': period,
        })
    return out


def main():
    os.makedirs(EARLY_DIR, exist_ok=True)
    n = 0
    for fn in sorted(glob.glob(os.path.join(PDF_DIR, '*.json'))):
        base = os.path.basename(fn)[:-5]
        rows = [r for r in conv(fn) if r['t'] and r['buyer']]
        dest = os.path.join(EARLY_DIR, 'plan-pdf-%s.json' % base)
        json.dump(rows, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('%s → %s（%d 条）' % (base, os.path.basename(dest), len(rows)))
        for r in rows:
            print('   · %-6s %-30s %s' % (r['expect'][:6], r['buyer'][:30], r['t'][:46]))
        n += len(rows)
    print('\n合计 %d 条' % n)


if __name__ == '__main__':
    main()
