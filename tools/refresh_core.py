# -*- coding: utf-8 -*-
"""按线上真实数据重算 data.core.js 的 meta —— 顶部 KPI 和筛选计数的唯一来源

为什么必须单独写一个：
  data.core.js 是 build_web.py 生成的，而 build_web.py 读的是本地 merged.json
  （10-28 的 2670 条旧版）。线上数据包是 2225 条，两者对不上，页面上就出现
  「入库项目 2670 / 数据更新 2026-10-28」，底下列表却是 2225 条 ——
  用户一眼就看出来数字不对劲。

  这次口径调整只动了 iv/dp，但 meta 里的 total / new / withAmt / 各种 Top
  全都没跟着重算。这个脚本只改 meta，其余（metals / platforms / watch /
  domStat / chunks）原样保留。

用法：
    python3 refresh_core.py --dry
    python3 refresh_core.py            # 调 build_web 时默认 --merge
    python3 refresh_core.py --replace  # 强制整包重建 meta

⚠ 2026-11-04 起默认 --merge：只更新能从 cols 真实算出来的字段（total / withAmt /
  withWin / amtSum / 各项 Top / dataAsOf），其余（updated / at / new / rawTotal /
  dropped）沿用旧值。原因见下面 _derivable 的注释。
"""
import json, os, shutil, sys
from collections import Counter

SITE = '/workspace/biz-radar'
CORE = os.path.join(SITE, 'data.core.js')
FILES = ['data.items.js', 'data.chunk-rest.js', 'data.chunk-lead.js']
DRY = '--dry' in sys.argv

# 业务分层短码 -> 中文名（跟前端 SEG_NAME 保持一致）
SEG_CN = {
    'youse': '有色冶炼供能', 'steelgas': '钢铁煤气发电', 'wasteheat': '余热余压利用',
    'cogen': '热电联产·集中供热', 'chemheat': '化工余热回收',
    'selfplant': '自备电厂·能源站', 'datactr': '数据中心供能', 'wte': '垃圾焚烧发电',
    'soil': '土壤与场地修复', 'zero': '废水零排放', 'sewage': '市政污水',
    'oversea': '中资出海能源岛', 'other': '其他',
}
# 分级中文（跟顶部 KPI 的「A 战略必争」对齐）
GRADE_CN = {'A': 'A 战略必争', 'B': 'B 重点跟进', 'C': 'C 一般', 'D': 'D 备选'}


def load_cols():
    C = {}
    for fn in FILES:
        s = open(os.path.join(SITE, fn), encoding='utf-8').read()
        J = json.loads(s[s.index('=') + 1:].rstrip(';'))
        for k, v in J['cols'].items():
            C.setdefault(k, []).extend(v)
    return C


def top(counter, k=8, cn=None):
    return [[(cn.get(a, a) if cn else a), b] for a, b in counter.most_common(k)]


def main():
    C = load_cols()
    n = len(C['t'])
    ds = [x for x in C['d'] if x]
    amt = [x for x in C['amt'] if x]
    win = [x for x in C['win'] if x]
    # 金额单位：amt 列存的就是「亿元」（build_web.py 第 355 行 'amt': r['amtY']，
    # r['amtY'] 在 build_data.py 里由 元/1e8 得到）。不用再靠量级猜。
    #
    # 原来这里写 `if amt_sum > 1e6: /1e8`，单位判断是照「amt 存元」的旧假设写的。
    # 库里根本没哪个项目是 100 万亿，这个分支永远不进，等于没换算，
    # 于是 611.7 被原样当成「亿元」写进 meta —— 页面顶部就变成
    # 「已公示金额 612 亿」而真实是 611.7 亿……两种口径下数字看着差不多，
    # 是因为恰好 460 个项目的单位值合计 611 本就等于亿元合计。
    # 现在显式按亿元求和，并在写盘前跟 items 列交叉校验。
    amt_sum = sum(float(x) for x in amt) if amt else 0

    # ── 哪些字段能从包里真实算出来，哪些不能 ────────────────────────────
    # 能算的：total / withAmt / withWin / amtSum / 各项 Top / dataAsOf（列表里就有）。
    # 算不出的：updated（采集日）/ at（采集时刻）/ new（本批新增）/ rawTotal（过滤前
    #   原始公告数）/ dropped（被过滤掉的）。
    # 原来这几个一律瞎填：updated 填 today（于是「今天跑一次行情」就等于「数据更新到
    #   今天」）、at 写死 '13:20'、rawTotal 填成入库数（3647 → 2712 那个差就没了）。
    # 现在默认merge：算得出才写，算不出就保留旧值。
    MERGE = '--replace' not in sys.argv
    new = {
        # updated = 这份数据包是哪天出的（页面顶部「数据更新」显示它）
        # dataAsOf = 里面最新一条公告是哪天的（数据截止）
        # 这两个原来都取公告最大日期，会让人以为「今天更新的数据停在 10-26」，
        # 实际是采集日和数据日两个概念，分开写清楚。
        'updated': __import__('datetime').date.today().isoformat(),
        'at': __import__('datetime').datetime.now().strftime('%H:%M'),
        'dataAsOf': max(ds)[:10] if ds else '',
        'total': n,
        'rawTotal': n,          # 原始采集量在本包里查不到，按入库数填，别再编旧数
        'dropped': 0,
        'new': sum(1 for x in C.get('nw', []) if x),
        'withAmt': len(amt),
        'withWin': len(win),
        # 'amtSum' 见下方 _KEEP_AMT 说明：由 build_web 产出，这里不写。
        'bizTop': top(Counter(C['sg']), 6, SEG_CN),
        'gradeTop': top(Counter(C['g']), 4),
        'rgTop': top(Counter(C['rg']), 4),
        'stTop': top(Counter(C['st']), 8),
        'subTop': top(Counter(C.get('ind', ['其他'] * n)), 8),
    }

    s = open(CORE, encoding='utf-8').read()
    i = s.index('=')
    head = s[:i + 1]
    J = json.loads(s[i + 1:].rstrip(';'))
    old = J.get('meta', {})

    print('旧 meta: total=%s updated=%s withAmt=%s amtSum=%s'
          % (old.get('total'), old.get('updated'), old.get('withAmt'), old.get('amtSum')))
    print('新 meta: total=%s updated=%s withAmt=%s amtSum=%s'
          % (new['total'], new['updated'], new['withAmt'], new['amtSum']))
    print('  地区:', new['rgTop'])
    print('  状态:', new['stTop'])
    print('  业务:', new['bizTop'])
    print('  金额: %d 条带金额，合计 %.1f 亿' % (new['withAmt'], new['amtSum']))

    # ⚠ 分口径金额（amtSum / withAmtWin / withInv / invSum）不在这里维护。
    #   它们只有 build_web 算得出来（要读 amtK 口径列），而 refresh_core 的
    #   cols 里没有这一列 —— 一旦在这里「继承旧值」，就会把 build_web 刚算好的
    #   450.7 亿覆盖回上一次的 725.7 亿（2026-11-04 实际踩过这个坑）。
    #   做法改成：本脚本完全不产出这几个键，J['meta'] 更新时把旧值原样带回。
    _KEEP_AMT = ('withAmtWin', 'withInv', 'invSum')
    # 分口径金额一律从旧值带回（不产、不覆盖）
    for k in _KEEP_AMT + ('amtSum',):
        if k in old:
            new[k] = old[k]
    if MERGE:
        keep = ('updated', 'at', 'new', 'rawTotal', 'dropped')
        for k in keep:
            if k in old:
                new[k] = old[k]
        print('  [merge] 沿用旧值：' + ' / '.join('%s=%s' % (k, new[k]) for k in keep))
    J['meta'] = new

    # ── watch：商机库三档的口径数字，页签「找商机 2670」就读它 ──────────────
    # 这几个数原来也是 build_web 按旧数据算的，不重算页签就一直挂着 2670。
    iv = C['iv']
    bk = C['bk']
    hm = C['hm']
    w = C['w']
    def cnt(f):
        return sum(1 for i in range(n) if f(i))
    J['watch'] = {
        'amt': 0.3,
        # 关注档（w=1）—— 页面上仍可用于排序，但不再是筛选门槛
        'tender': cnt(lambda i: bk[i] == 'tender' and iv[i] and w[i]),
        'win': cnt(lambda i: bk[i] == 'win' and iv[i] and w[i]),
        'lead': cnt(lambda i: bk[i] == 'lead' and iv[i] and w[i]),
        # 全档（不卡关注位）—— 页签和档位按钮显示的是这个
        'tenderAll': cnt(lambda i: bk[i] == 'tender' and iv[i]),
        'winAll': cnt(lambda i: bk[i] == 'win' and iv[i]),
        'tenderHm': cnt(lambda i: bk[i] == 'tender' and iv[i] and hm[i]),
        'winHm': cnt(lambda i: bk[i] == 'win' and iv[i] and hm[i]),
        'all': n,
    }
    print('  watch:', J['watch'])
    # 顺带把 chunks 里的条数修正（原来写 715 / 1883，是旧数据）
    if 'chunks' in J:
        for c in J['chunks']:
            fn = os.path.join(SITE, c['file'])
            if os.path.exists(fn):
                t = open(fn, encoding='utf-8').read()
                c['n'] = len(json.loads(t[t.index('=') + 1:].rstrip(';'))['cols']['t'])
                c['kb'] = os.path.getsize(fn) // 1024
        print('  chunks:', J['chunks'])

    if DRY:
        print('\n【试运行，未落盘】')
        return
    shutil.copy2(CORE, CORE + '.bak')
    open(CORE, 'w', encoding='utf-8').write(
        head + json.dumps(J, ensure_ascii=False, separators=(',', ':')) + ';')
    print('\n✅ 已写入 data.core.js（原文件备份为 .bak）')


if __name__ == '__main__':
    main()
