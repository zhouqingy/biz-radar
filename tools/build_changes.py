# -*- coding: utf-8 -*-
"""商机雷达 · 本周变化（F31，只读，接入 update_weekly.py 全量重建链路）

用户 2026-11-05 原话：「你那个数据是每次都需要更新的，就比如说你重新抓一次，
你要对你的库里面数据进行一个重跑，比如说它因为它是一个实时性的嘛有可能今天招不到，
明天就已经就已经那个出结果了，这种状态是会一直变化的，然后也会有一些那个漏项」。

⚠ 三个边界，写在前头：
  1) **只读**：只扫①库三个 chunk 的列式数据，不写任何 data*.js 主数据、不删条目、
     不改 `biz_rules.py`、不重跑筛选。四类只是对现有字段（nw / d / hist / st / win）
     的统计呈现，不是新的过滤/删留规则 —— 口径唯一源仍是 biz_rules.py。
  2) **不做跨版本 diff**：本轮没有可依赖的「上一次快照」（data.js.bak 不存在），
     且 hist 字段本身就记录了同一项目的状态链，天然能识别「阶段推进 / 新出结果」。
     所以每次全量重建都从**当前库自身**重新算一遍，实时状态变化自然体现，
     不依赖历史文件。这也符合用户「每次更新全量重跑」的要求。
  3) **本周 = 数据自身的截止窗口**，不是运行当天：取①库主日期 d 的最大值当 asOf，
     往前 7 天为本周窗口。避免沙箱系统时钟与数据不同步时算出「本周 0 条」。

四类（都是「提示去复核」，不是判删）：
  ① 新增 new       ：nw=1（本轮新增标记）或主日期落在本周窗口
  ② 阶段推进 advanced：hist 出现 ≥2 个不同阶段且阶段序数往前进（计划→公告→候选→结果）
  ③ 新出结果 result  ：最新阶段为中标候选人/中标结果公示，且该条日期落在本周窗口
  ④ 疑似漏项 gap    ：a) 已到结果阶段但 win（中标单位）为空；
                       b) 主状态仍是招标公告/招标计划、距 asOf >45 天且 hist 无后续阶段

产物：
  biz-radar/data.changes.js   window.DATA_CHANGES（页面 need('changes') 懒加载）
  本周变化.json / .html        逐条明细 + 四类口径，供回执与人工复核

用法：python3.11 biz-radar-tools/build_changes.py
"""
import json, os, re, sys, html, datetime
from collections import Counter, OrderedDict

TOOLS = os.path.dirname(os.path.abspath(__file__))
# 本地：脚本在 /workspace/biz-radar-tools，站点在平级 biz-radar；
# CI：脚本在 <repo>/tools，站点直接是仓库根。可用环境变量显式覆盖。
ROOT = os.environ.get('BIZ_WORKSPACE') or os.path.dirname(TOOLS)
BR = (os.environ.get('BIZ_OUT') or os.environ.get('BIZ_SITE')
      or (os.path.join(ROOT, 'biz-radar')
          if os.path.isfile(os.path.join(ROOT, 'biz-radar', 'data.items.js')) else ROOT))
sys.path.insert(0, TOOLS)
from preflight import require_briefing
require_briefing('build_changes.py')

PARTS = ['data.items.js', 'data.chunk-lead.js', 'data.chunk-rest.js']
WIN_DAYS = 7          # 本周窗口天数（含 asOf 当天）
STALE_DAYS = 45       # 招标公告停留超过这个天数且无后续 → 疑似漏跟
MAX_SHOW = 40         # 每类最多带多少条明细（总数单独给，避免 data.changes.js 过大）

# 与 index.html 的 SITE_PREFIX / fullUrl() 一一对应；改一边必须改另一边。
SITE_PREFIX = {
    'js': 'http://jsggzy.jszwfw.gov.cn', 'zj': 'https://ggzy.zj.gov.cn',
    'hf': 'https://ggzy.hefei.gov.cn', 'sz': 'https://ggzy.suzhou.gov.cn',
    'cz': 'https://ggzy.changzhou.gov.cn', 'sh': 'https://www.shggzy.com',
    'zb': 'https://www.zbytb.com', 'gx': 'https://www.gxxszb.com',
}

# 阶段序数：只用于判断「是否往前推进」，不做任何删留判断。
STAGE_RANK = {
    '招标计划': 1, '立项公示': 1, '招标公告': 2, '变更公告': 2,
    '中标候选人公示': 3, '中标结果公示': 4, '其他': 0,
}
RESULT_ST = ('中标候选人公示', '中标结果公示')
OPEN_ST = ('招标公告', '招标计划')


def full_url(u):
    u = str(u or '')
    if not u or not u.startswith('#'):
        return u
    i = u.find('/')
    if i < 0:
        return u
    code, rest = u[1:i], u[i:]
    return SITE_PREFIX.get(code, '') + rest if code in SITE_PREFIX else u


def load_js(path):
    s = open(path, encoding='utf-8').read()
    m = re.search(r'=\s*(\{.*\})\s*;?\s*$', s, re.S)
    if not m:
        raise ValueError('解析不到列式数据: ' + path)
    return json.loads(m.group(1))


def ymd(s):
    s = str(s or '').strip()
    return s if re.match(r'^\d{4}-\d{2}-\d{2}$', s) else ''


def esc(x):
    return html.escape(str(x))


def main():
    gen = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    rows = []
    blocks = OrderedDict()
    for f in PARTS:
        d = load_js(os.path.join(BR, f))
        c, n, ext = d['cols'], d['n'], (d.get('ext') or {})
        hist = ext.get('hist') or {}
        order = d.get('order')
        blocks[f] = n
        for i in range(n):
            r = {}
            for k, col in c.items():
                v = col[i] if i < len(col) else None
                if v not in (None, '', 0, False):
                    r[k] = v
            h = hist.get(str(i)) or hist.get(i)
            if h:
                r['hist'] = h
            r['_i'] = order[i] if order and i < len(order) else i
            r['_block'] = f
            rows.append(r)

    # ---- 数据截止日与本周窗口（以库自身为准） ----
    all_d = [ymd(r.get('d')) for r in rows]
    all_d = [x for x in all_d if x]
    as_of = max(all_d) if all_d else ''
    a_dt = datetime.date(*map(int, as_of.split('-'))) if as_of else None
    w_from = (a_dt - datetime.timedelta(days=WIN_DAYS - 1)).isoformat() if a_dt else ''
    w_to = as_of

    def in_win(ds):
        ds = ymd(ds)
        return bool(ds and w_from and w_from <= ds <= w_to)

    def days_ago(ds):
        ds = ymd(ds)
        if not ds or not a_dt:
            return 0
        return (a_dt - datetime.date(*map(int, ds.split('-')))).days

    def brief(r, why):
        return {
            'id': r.get('id', ''), 't': r.get('t', ''), 'st': r.get('st', ''),
            'd': ymd(r.get('d')), 'win': r.get('win') or '', 'amt': r.get('amt') or 0,
            'url': full_url(r.get('url')), 'g': r.get('g', ''), 'bk': r.get('bk', ''),
            'rg': r.get('rg', ''), 'why': why,
        }

    groups = OrderedDict((k, []) for k in ('new', 'advanced', 'result', 'gap'))
    for r in rows:
        h = [e for e in (r.get('hist') or []) if isinstance(e, dict)]
        sts = [str(e.get('st') or '') for e in h]
        ranks = [STAGE_RANK.get(s, 0) for s in sts if STAGE_RANK.get(s, 0) > 0]
        main_st = str(r.get('st') or '')

        # ① 新增
        why_new = []
        if r.get('nw'):
            why_new.append('nw=1 本轮新增标记')
        if in_win(r.get('d')):
            why_new.append('主日期 %s 落在本周窗口' % ymd(r.get('d')))
        if why_new:
            groups['new'].append(brief(r, '；'.join(why_new)))

        # ② 阶段推进：hist 有 ≥2 个不同阶段且序数往前进
        if len(ranks) >= 2 and max(ranks) > min(ranks):
            lo = min(ranks); hi = max(ranks)
            lo_st = next((s for s in sts if STAGE_RANK.get(s, 0) == lo), '?')
            hi_st = next((s for s in sts if STAGE_RANK.get(s, 0) == hi), '?')
            groups['advanced'].append(brief(r, '%s → %s（hist %d 阶段）' % (lo_st, hi_st, len(h))))

        # ③ 新出结果：最新阶段为结果类且该条日期在本周窗口
        if h:
            last = h[-1]
            last_st = str(last.get('st') or '')
            if last_st in RESULT_ST and in_win(last.get('d')):
                groups['result'].append(brief(r, '%s %s（结果公告本周新出）' %
                                              (ymd(last.get('d')), last_st)))
        elif main_st in RESULT_ST and in_win(r.get('d')):
            groups['result'].append(brief(r, '%s %s（主状态即结果公告，本周新出）' %
                                          (ymd(r.get('d')), main_st)))

        # ④ 疑似漏项
        reached = main_st in RESULT_ST or any(s in RESULT_ST for s in sts)
        if reached and not (r.get('win') or '').strip():
            groups['gap'].append(brief(r, '已到结果阶段但 win（中标单位）为空 → 结果公告可能没抓全'))
        elif main_st in OPEN_ST and days_ago(r.get('d')) > STALE_DAYS and not ranks:
            groups['gap'].append(brief(r, '%s 停留 %d 天、hist 无后续阶段 → 疑似漏跟后续结果' %
                                       (main_st, days_ago(r.get('d')))))

    defs = [
        ('new', '新增线索', 'nw=1（本轮新增标记）或主发布日期落在本周窗口（%s ~ %s）' % (w_from, w_to)),
        ('advanced', '阶段推进', 'hist 状态历史里出现 ≥2 个不同阶段，且阶段序数往前走（招标计划→招标公告→中标候选人→中标结果）'),
        ('result', '新出结果', '最新一条状态是中标候选人公示 / 中标结果公示，且该条公告日期落在本周窗口 —— 即「今天招标、明天出结果」的实时变化'),
        ('gap', '疑似漏项', 'a) 已到结果阶段但 win 为空（中标单位没抓到）；b) 主状态仍是招标公告/招标计划、距数据截止日 >%d 天且 hist 无后续阶段（漏跟）' % STALE_DAYS),
    ]

    # 明细按日期倒序，限量；总数单独给
    out_groups = OrderedDict()
    for code, _name, _rule in defs:
        lst = sorted(groups[code], key=lambda x: x['d'] or '', reverse=True)
        out_groups[code] = {'n': len(lst), 'items': lst[:MAX_SHOW]}

    kpi = {code: len(groups[code]) for code, _n, _r in defs}
    kpi['libTotal'] = len(rows)

    out = {
        'gen': gen,
        'asOf': as_of,
        'window': {'from': w_from, 'to': w_to, 'days': WIN_DAYS},
        'note': 'F31 本周变化。四周口径均来自①库当前字段（nw/d/hist/st/win）的统计呈现，'
                '不是新的过滤或删留规则；唯一规则源仍是 biz_rules.py。本脚本只读，不写任何主数据。',
        'disclaimer': '四类都是「提示去原文复核」，不代表要改库、更不代表要删条目。'
                      '本周窗口以①库自身最新公告日期为基准，不是运行当天；每次 update_weekly.py '
                      '全量重建会重新生成本档，实时状态变化与漏项随之更新。',
        'defs': [{'code': c, 'name': n, 'rule': r} for c, n, r in defs],
        'kpi': kpi,
        'groups': out_groups,
        'source': {'parts': PARTS, 'blocks': blocks,
                   'rule': 'biz_rules.py（未调用，未改动）', 'script': 'build_changes.py'},
    }

    # ---- data.changes.js（页面 need('changes') 懒加载） ----
    jp_changes = os.path.join(BR, 'data.changes.js')
    with open(jp_changes, 'w', encoding='utf-8') as f:
        f.write('/* F31 本周变化 · 由 biz-radar-tools/build_changes.py 生成，请勿手工编辑。\n'
                '   每次 update_weekly.py 全量重建会刷新本文件。只读统计，不删不改主数据。 */\n')
        f.write('window.DATA_CHANGES = ')
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')

    # ---- 本周变化.json ----
    jp = os.path.join(ROOT, '本周变化.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # ---- 本周变化.html ----
    drows = ''.join('<tr><td class="mono">%s</td><td><b>%s</b></td><td>%s</td></tr>' %
                    (esc(d['code']), esc(d['name']), esc(d['rule'])) for d in out['defs'])
    secs = []
    for code, name, rule in defs:
        g = out_groups[code]
        items = ''.join(
            '<li><a href="%s" target="_blank" rel="noopener">%s ↗</a>'
            '<span class="mono"> [%s] %s · %s</span><div class="why">%s</div></li>' %
            (esc(x['url']) if str(x['url']).startswith('http') else '#',
             esc(x['t']), esc(x['st']), esc(x['d'] or '—'),
             ('中标 ' + esc(x['win'])) if x['win'] else ('金额 ' + str(x['amt']) + ' 亿' if x['amt'] else ''),
             esc(x['why'])) for x in g['items']) or '<li class="empty">（本期无）</li>'
        secs.append('<div class="sec"><h2>%s · <b>%d</b> 条%s</h2>'
                    '<div class="note">%s</div><ul class="lst">%s</ul></div>' %
                    (esc(name), g['n'],
                     ('（列出最新 %d 条）' % len(g['items'])) if g['n'] > len(g['items']) else '',
                     esc(rule), items))
    H = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>本周变化 · %s</title><style>
body{margin:0;background:#f5f7fa;color:#303133;font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 20px 60px}
.hd{background:linear-gradient(100deg,#14532d,#1a7f4b);color:#fff;border-radius:12px;padding:22px 26px;margin-bottom:16px}
.hd h1{margin:0 0 4px;font-size:22px}.hd p{margin:0;opacity:.9;font-size:13px}
.sec{background:#fff;border:1px solid #dbe1e8;border-radius:10px;padding:18px 20px;margin-bottom:14px}
h2{font-size:16px;margin:0 0 10px;padding-left:10px;border-left:4px solid #14713a}
.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.kpi div{flex:1;min-width:120px;background:#f7faf8;border:1px solid #d5e8dc;border-radius:8px;padding:9px 12px}
.kpi b{display:block;font-size:22px;color:#14713a}.kpi span{font-size:11.5px;color:#909399}
.note{background:#f0f7f2;border-left:3px solid #1a7f4b;padding:9px 13px;margin:8px 0;font-size:12.5px;color:#2b5744}
.alert{background:#fff7ed;border-left:4px solid #d97706;padding:11px 14px;border-radius:0 6px 6px 0;margin:12px 0;font-size:13px;color:#7c4a12}
.lst{list-style:none;padding:0;margin:8px 0 0}.lst li{padding:8px 0;border-bottom:1px dashed #e8ecf0;font-size:13px}
.lst li a{color:#14532d;text-decoration:none;font-weight:600}.lst li a:hover{text-decoration:underline}
.lst .why{color:#8a6d3b;font-size:12px;margin-top:2px}.lst .empty{color:#909399}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;color:#606266}
table{width:100%%;border-collapse:collapse;font-size:12.5px}
th{background:#f3f7f4;color:#2b5744;text-align:left;padding:7px 9px;border:1px solid #dbe1e8}
td{padding:7px 9px;border:1px solid #dbe1e8;vertical-align:top}
</style></head><body><div class="wrap">
<div class="hd"><h1>本周变化 · %s</h1><p>F31 · 数据截止 %s · 本周窗口 %s ~ %s（%d 天）· 只读统计，不删不改主数据</p></div>
<div class="sec"><h2>四类合计（①库 %d 条）</h2><div class="kpi">
%s</div><div class="alert"><b>⚠ 四类都是「提示去原文复核」，不是删除清单。</b>%s</div></div>
<div class="sec"><h2>四类口径（来自①库现有字段，不是新规则）</h2><table>
<tr><th style="width:12%%">码</th><th style="width:16%%">类别</th><th>判据</th></tr>%s</table></div>
%s
<div class="sec"><h2>复跑方式</h2><p class="mono">python3.11 /workspace/biz-radar-tools/build_changes.py</p>
<p>每次 <span class="mono">update_weekly.py</span> 全量重建（build_web.py 之后）会重新生成本档与
<span class="mono">biz-radar/data.changes.js</span>，页面「本周变化」视图与周报「〇、本周变化」章节随之更新。</p></div>
</div></body></html>''' % (
        gen, gen, as_of, w_from, w_to, WIN_DAYS, len(rows),
        ''.join('<div><b>%d</b><span>%s</span></div>' % (kpi[c], esc(n)) for c, n, _r in defs),
        esc(out['disclaimer']), drows, ''.join(secs))

    hp = os.path.join(ROOT, '本周变化.html')
    with open(hp, 'w', encoding='utf-8') as f:
        f.write(H)

    print('本周变化 F31 | 数据截止 %s | 窗口 %s ~ %s（%d 天）| ①库 %d 条' %
          (as_of, w_from, w_to, WIN_DAYS, len(rows)))
    for c, n, _r in defs:
        print('  %-10s %-8s %4d 条' % (c, n, kpi[c]))
    print('  输出：', jp_changes, '|', hp, '|', jp)
    return out


if __name__ == '__main__':
    main()
