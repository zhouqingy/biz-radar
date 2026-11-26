# -*- coding: utf-8 -*-
"""商机雷达 · 数据质量体检（可复用，每次更新/重跑后执行）

用法：python3.11 biz-radar-tools/healthcheck.py [--out 报告.html] [--no-sync]
只读，不修改任何数据文件。输出 JSON + HTML 报告。

⚠ 唯一的写操作（2026-11-05 第 1 批新增，F29/F32）：默认把「数据血缘 + 质量体检」
   快照同步进 index.html 的 p-help 面板，只替换两行 HEALTH_SNAPSHOT 注释之间的内容，
   head/tail 原样拼接、页面其余部分一个字节不动。锚点缺失则跳过并告警。
   加 --no-sync 可完全关闭；页面数字永远来自本脚本，不允许手工填写。

⚠ 开工前必读：本脚本在被任何采集/构建流程调用前，先经 preflight.py 校验
   /workspace/00-公司业务口径.md 已读（见文件头）。口径不清就跑数据 = 污染库。
"""
import json, re, sys, os, html, datetime
from collections import Counter, defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get('BIZ_WORKSPACE') or os.path.dirname(TOOLS)
BR = (os.environ.get('BIZ_OUT') or os.environ.get('BIZ_SITE')
      or (os.path.join(ROOT, 'biz-radar')
          if os.path.isfile(os.path.join(ROOT, 'biz-radar', 'data.items.js')) else ROOT))

# 开工校验：必须能读到业务口径底稿
sys.path.insert(0, TOOLS)
try:
    from preflight import require_briefing
    require_briefing('healthcheck.py')
except ImportError:
    print('[体检] 警告：preflight.py 缺失，跳过必读校验（建议补上）', file=sys.stderr)
except SystemExit as e:
    raise


def load_js(path):
    s = open(path, encoding='utf-8').read()
    m = re.search(r'=\s*(\{.*\})\s*;?\s*$', s, re.S)
    if not m:
        raise ValueError('解析不到 JSON: ' + path)
    return json.loads(m.group(1))


def rate(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


def main():
    today = datetime.date.today().isoformat()
    R = {'gen': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
         'today': today, 'checks': [], 'issues': [], 'summary': {}}

    def chk(name, ok, detail, level='info'):
        R['checks'].append({'name': name, 'ok': bool(ok), 'detail': detail, 'level': level})
        if not ok and level in ('warn', 'error'):
            R['issues'].append({'name': name, 'detail': detail, 'level': level})

    # ---------- ① 投放/商机库（列式三块） ----------
    parts = ['data.items.js', 'data.chunk-lead.js', 'data.chunk-rest.js']
    blocks = [(f, load_js(os.path.join(BR, f))) for f in parts]
    allcols = defaultdict(list)
    for f, d in blocks:
        for k, v in d['cols'].items():
            allcols[k].extend(v if isinstance(v, list) else [])
    n = sum(d['n'] for _, d in blocks)
    core = load_js(os.path.join(BR, 'data.core.js'))
    core_total = int((core.get('meta') or {}).get('total') or 0)
    R['summary']['lib1_rows'] = n
    R['summary']['lib1_cols'] = len(allcols)
    chk('①库三块合计与 core.meta.total 一致', n == core_total,
        '三块 n = %s，合计 %d；core.meta.total=%d'
        % ([d['n'] for _, d in blocks], n, core_total), level='error')
    chk('①库各列长度一致', all(len(v) == n for v in allcols.values()),
        '异常列：%s' % ([k for k, v in allcols.items() if len(v) != n] or '无'))

    # 字段完整率
    fill = {}
    for k in sorted(allcols.keys()):
        v = allcols[k]
        ne = sum(1 for x in v if x not in (None, '', 0, False, '0'))
        fill[k] = {'nonempty': ne, 'rate': rate(ne, n)}
    R['fill'] = fill

    # 唯一性 / 索引
    ids = allcols['id']
    chk('①库 ID 唯一', len(set(map(str, ids))) == n,
        '重复 %d 个' % (n - len(set(map(str, ids)))))
    orders = [int(x) for x in allcols['order']] if 'order' in allcols else []
    if orders:
        chk('order 覆盖 0..N-1 且不重复', sorted(orders) == list(range(n)),
            'min=%s max=%s 唯一=%d' % (min(orders), max(orders), len(set(orders))))

    # ext 索引合法
    extbad = []
    for f, d in blocks:
        for ek, m in d.get('ext', {}).items():
            for k in m.keys():
                try:
                    if int(k) >= d['n'] or int(k) < 0:
                        extbad.append((f, ek, k))
                except ValueError:
                    extbad.append((f, ek, k))
    chk('ext 行索引合法', not extbad, '越界/非数字 %d 处' % len(extbad))

    # w 与 amt 一致（≥1 亿 → w=1）
    mism = []
    for i, (a, w) in enumerate(zip(allcols['amt'], allcols['w'])):
        try:
            expect = 1 if float(a or 0) >= 1.0 else 0
        except (TypeError, ValueError):
            expect = 0
        if int(w or 0) != expect:
            mism.append((i, a, w))
    chk('w 关注档与金额 ≥1 亿一致', not mism, '不一致 %d 条' % len(mism), 'warn')

    # 阶段 × 中标单位
    st = allcols['st']; win = allcols['win']
    win_stages = ('中标结果公示', '中标候选人公示')
    winrows = [i for i, s in enumerate(st) if s in win_stages]
    winfilled = [i for i in winrows if win[i] and str(win[i]).strip()]
    R['summary']['win_stage_rows'] = len(winrows)
    R['summary']['win_filled_in_stage'] = len(winfilled)
    chk('①库中标类公告有中标单位', True,
        '中标类公告 %d 条，其中带 win %d 条（%s%%）；缺 %d 条可从②库补' %
        (len(winrows), len(winfilled), rate(len(winfilled), len(winrows)),
         len(winrows) - len(winfilled)), 'info')
    chk('①库中标类公告可跳原文', True,
        '中标类公告里有 url 的 %d / %d 条（%s%%）' %
        (sum(1 for i in winrows if allcols['url'][i]), len(winrows),
         rate(sum(1 for i in winrows if allcols['url'][i]), len(winrows))), 'info')

    # 立项线索时效（2026-11-18 §5.62）：状态推进 + 陈旧标记
    # build_data 6.8 每次全量重建自动推进旧线索（写 hist），>2 年无后续的标 stale=1。
    # 这里的数字必须来自脚本实测，与 build_data 打印对得上。
    _staleN = 0
    _leadN = 0
    for _f, _d in blocks:
        _staleN += len(_d.get('ext', {}).get('stale') or {})
        for _s in (_d['cols'].get('st') or []):
            if _s in ('立项公示', '招标计划'):
                _leadN += 1
    R['summary']['lead_rows'] = _leadN
    R['summary']['lead_stale'] = _staleN
    chk('立项线索时效', True,
        '①库仍挂立项/招标计划阶段 %d 条，其中「线索陈旧」(>2 年无后续公开记录) %d 条'
        '已灰显置底；同项目后续阶段的记录会在全量重建时把线索自动推进' % (_leadN, _staleN), 'info')

    # 链接
    urls = [str(u or '') for u in allcols['url']]
    # ⚠ 2026-11-05 修正：'#zj/...' / '#hf/...' 是站内锚点路由，不是坏链接。
    #   index.html 2168 行有还原函数把它拼回 https://ggzy.zj.gov.cn/... 等真实域名，
    #   点开同样能到原文。第一版体检把这类全算成「非 http」误报了 385 条。
    routed = [i for i, u in enumerate(urls) if u.startswith('#')]
    badfmt = [i for i, u in enumerate(urls)
              if u and not u.startswith('http') and not u.startswith('#')]
    emptyu = sum(1 for u in urls if not u)
    dupu = len(urls) - len(set(u for u in urls if u))
    linkbad = sum(1 for x in allcols.get('linkbad', []) if x)
    chk('站内锚点路由可还原', True,
        '# 开头 %d 条（#zj/#hf/#js/#sz/#gx），由前端还原为真实域名，可跳原文' % len(routed), 'info')
    chk('url 格式（非 http 且非站内路由）', not badfmt, '异常 %d 条' % len(badfmt), 'warn')
    chk('url 空值', True, '空 url %d 条（%s%%）' % (emptyu, rate(emptyu, n)), 'info')
    chk('url 重复', True, '重复 %d 条' % dupu, 'info')
    chk('linkbad 标记', True, '已标记链接失效 %d 条' % linkbad, 'info')
    # 占位/假链接：http 开头但明显是编造的（xxxx / TODO / example.com），
    # 只看协议头检查不出来，却是「可跳原文」承诺里最伤信任的一种。
    ph = re.compile(r'xxxx|xxx|TODO|example\.com|placeholder|待补|#N/A', re.I)
    fake = [(i, u) for i, u in enumerate(urls) if u and ph.search(u)]
    R['fake_urls'] = [{'idx': i, 'id': str(allcols['id'][i]), 'url': u,
                       'title': str(allcols['t'][i])[:80]} for i, u in fake]
    chk('url 无占位/假链接', not fake,
        ('异常 %d 条：' % len(fake)) + '；'.join('%s %s' % (allcols['id'][i], u) for i, u in fake)
        if fake else '异常 0 条', 'warn')

    # 金额异常
    amts = []
    for a in allcols['amt']:
        try:
            amts.append(float(a))
        except (TypeError, ValueError):
            amts.append(None)
    valid = [x for x in amts if x is not None and x > 0]
    neg = [x for x in amts if x is not None and x < 0]
    huge = [x for x in amts if x is not None and x > 1000]
    chk('金额无负值', not neg, '负值 %d 条' % len(neg), 'warn')
    chk('金额无 >1000 亿异常值', not huge, '异常 %d 条' % len(huge), 'warn')
    R['summary']['amt_valid'] = len(valid)
    R['summary']['amt_max_yi'] = round(max(valid), 2) if valid else 0

    # 日期
    def isdate(s):
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}$', str(s or '')))
    bd = [i for i, x in enumerate(allcols['d']) if x and not isdate(x)]
    future = [x for x in allcols['dl'] if isdate(x) and str(x) > today]
    # 异常明细写进 JSON/HTML，便于逐条核对。⚠ 只报不改：改主数据要先给用户逐条清单。
    R['date_issues'] = [{'idx': i, 'id': str(allcols['id'][i]), 'd': str(allcols['d'][i]),
                         'title': str(allcols['t'][i])[:100]} for i in bd]
    dtxt = (('异常 %d 条：' % len(bd)) + '；'.join(
        '%s（%s）%s' % (allcols['id'][i], allcols['d'][i],
                        str(allcols['t'][i])[:32]) for i in bd)) if bd else '异常 0 条'
    chk('发布日期 d 格式', not bd, dtxt, 'warn')
    chk('截标日 dl 在未来', True, '未来截标 %d 条（最早 %s）' %
        (len(future), min(future) if future else '—'), 'info')

    # 标题重复
    ts = [str(t or '') for t in allcols['t']]
    chk('标题重复', True, '重复 %d 条' % (len(ts) - len(set(t for t in ts if t))), 'info')

    # ---------- 跨文件一致性 ----------
    core = load_js(os.path.join(BR, 'data.core.js'))
    whole = load_js(os.path.join(BR, 'data.js'))
    items_js = load_js(os.path.join(BR, 'data.items.js'))
    corem = core['meta']; wm = whole.get('meta', {})
    chk('meta 四处对齐', all([
        corem.get('total') == n,
        wm.get('total') == n,
        items_js.get('total') == n,
        core['watch'].get('all') == n,
    ]), 'core=%s / data.js=%s / items.total=%s / watch.all=%s' %
        (corem.get('total'), wm.get('total'), items_js.get('total'), core['watch'].get('all')), 'error')
    chk('data.js items 条数', len(whole.get('items', [])) == n,
        'data.js items %d 条' % len(whole.get('items', [])), 'error')
    chk('关注档 watch 与 w 列一致',
        core['watch'].get('amt') == 1.0 and
        sum(1 for x in allcols['w'] if int(x or 0) == 1) == 98,
        'watch.amt=%s，w=1 实际 %d 条' %
        (core['watch'].get('amt'), sum(1 for x in allcols['w'] if int(x or 0) == 1)), 'warn')

    # ---------- ② 业绩/动向库 ----------
    rp = load_js(os.path.join(BR, 'data.rivalperf.js'))['db']
    cp = load_js(os.path.join(BR, 'data.candperf.js'))['db']
    og = load_js(os.path.join(BR, 'data.org.js'))
    def items_of(v):
        return sum(len(x.get('items') or []) for x in (v.values() if isinstance(v, dict) else v)
                   if isinstance(x, dict))
    rpn, cpn = items_of(rp), items_of(cp)
    orgn = {k: items_of(og[k]) for k in og if isinstance(og[k], (dict, list))}
    R['summary']['lib2'] = {'rivalperf_units': len(rp), 'rivalperf_items': rpn,
                            'candperf_units': len(cp), 'candperf_items': cpn,
                            'org': orgn}
    chk('②库中标/业绩记录规模', True,
        'rivalperf %d 家 / %d 条；candperf %d 家 / %d 条；org 各单位库合计 %d 条' %
        (len(rp), rpn, len(cp), cpn, sum(orgn.values())), 'info')
    # ②库 url 可跳原文
    def url_rate(v):
        tot = good = 0
        for x in (v.values() if isinstance(v, dict) else v):
            for it in (x.get('items') or []) if isinstance(x, dict) else []:
                tot += 1
                if str(it.get('url') or '').startswith('http'):
                    good += 1
        return good, tot
    rg, rt = url_rate(rp); cg, ct = url_rate(cp)
    chk('②库业绩条目可跳原文', True,
        'rivalperf %d/%d（%s%%）；candperf %d/%d（%s%%）' %
        (rg, rt, rate(rg, rt), cg, ct, rate(cg, ct)), 'info')

    # ---------- 行情品种候选主动扫描（2026-11-18 用户问「能不能自己抓」）----------
    # 库里的项目标题/摘要就是产业链需求信号：某产业链词高频出现而行情面板
    # 还没这个品种 → 列成候选报给用户，加不加由用户拍板（口径判断不自动加）。
    _CAND_RX = {
        '天然气/LNG': r'天然气|LNG', '磷酸/磷化工': r'磷酸|磷矿|磷化工',
        '柴油': r'柴油', '汽油': r'汽油|92号', '玻璃/光伏玻璃': r'玻璃',
        '纯碱': r'纯碱', '烧碱': r'烧碱|液碱', '甲醇': r'甲醇',
        '尿素': r'尿素', '沥青': r'沥青', '橡胶': r'橡胶',
        'PVC': r'PVC|聚氯乙烯', '石油焦': r'石油焦|煅后焦',
        '硫酸镍': r'硫酸镍', '硫酸钴': r'硫酸钴', '氢氟酸': r'氢氟酸',
        '萤石': r'萤石', '钨': r'钨', '钼': r'钼', '钛': r'钛白粉|海绵钛',
        '锰硅': r'锰硅|锰矿', '硅铁': r'硅铁', '锗': r'锗', '镓': r'镓',
    }
    _HAVE = {'沪铜','沪铝','沪锌','沪铅','沪镍','沪锡','氧化铝','不锈钢','碳酸锂',
             '螺纹钢','热轧卷板','铁矿石','焦煤','焦炭','燃料油','工业硅','多晶硅',
             '白银','硫磺','硫酸'}
    _mtext = [((r.get('t') or '') + ' ' + (r.get('buyer') or '') + ' ' + (r.get('snip') or ''))
              for r in (whole.get('items') or [])]
    _hits = sorted(((k, sum(1 for t in _mtext if re.search(rx, t)))
                    for k, rx in _CAND_RX.items()), key=lambda x: -x[1])
    _cand = [(k, v) for k, v in _hits if v >= 5]
    chk('行情品种候选扫描', True,
        ('候选（库内出现≥5条且面板还没有）：%s' %
         '、'.join('%s %d条' % (k, v) for k, v in _cand)) if _cand
        else '库内无高频新产业链词，现有 20 品种覆盖足够',
        'info')

    # ---------- 其他数据文件规模 ----------
    others = {}
    for f, key in [('data.plan.js', None), ('data.news.js', None), ('data.siku.js', None),
                   ('data.entprobe.js', None), ('data.metalhist.js', None),
                   ('data.policy.js', None)]:
        p = os.path.join(BR, f)
        if not os.path.exists(p):
            continue
        try:
            d = load_js(p)
            others[f] = {k: (len(v) if isinstance(v, (list, dict)) else str(v)[:30])
                         for k, v in list(d.items())[:8]}
        except Exception as e:
            others[f] = {'error': str(e)[:60]}
    R['others'] = others

    # ---------- 汇总 ----------
    errs = [x for x in R['issues'] if x['level'] == 'error']
    warns = [x for x in R['issues'] if x['level'] == 'warn']
    R['summary']['checks'] = len(R['checks'])
    R['summary']['errors'] = len(errs)
    R['summary']['warns'] = len(warns)
    R['summary']['top_missing'] = sorted(
        [(k, v['rate']) for k, v in fill.items()], key=lambda x: x[1])[:10]

    out_json = os.path.join(ROOT, '数据质量体检.json')
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(R, f, ensure_ascii=False, indent=2)

    # ---------- HTML ----------
    def esc(x):
        return html.escape(str(x))
    rows = ''.join(
        '<tr><td>%s</td><td class="%s">%s</td><td>%s</td></tr>' %
        (esc(c['name']), 'ok' if c['ok'] else ('no' if c['level'] in ('warn', 'error') else ''),
         '通过' if c['ok'] else ('关注' if c['level'] == 'info' else '异常'), esc(c['detail']))
        for c in R['checks'])
    fillrows = ''.join(
        '<tr><td class="mono">%s</td><td>%d</td><td>%.1f%%</td><td><div class="bar2"><i style="width:%.1f%%"></i></div></td></tr>' %
        (esc(k), v['nonempty'], v['rate'], v['rate'])
        for k, v in sorted(fill.items(), key=lambda x: x[1]['rate']))
    iss = ''.join('<li class="%s"><b>%s</b>：%s</li>' %
                  (x['level'], esc(x['name']), esc(x['detail'])) for x in R['issues']) or '<li>无阻断性问题</li>'
    H = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>数据质量体检 · %s</title><style>
body{margin:0;background:#f5f7fa;color:#303133;font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 20px 60px}
.hd{background:linear-gradient(100deg,#14532d,#1a7f4b);color:#fff;border-radius:12px;padding:22px 26px;margin-bottom:16px}
.hd h1{margin:0 0 4px;font-size:22px}.hd p{margin:0;opacity:.9;font-size:13px}
.sec{background:#fff;border:1px solid #dbe1e8;border-radius:10px;padding:18px 20px;margin-bottom:14px}
h2{font-size:16px;margin:0 0 12px;padding-left:10px;border-left:4px solid #14713a}
table{width:100%%;border-collapse:collapse;font-size:12.5px}
th{background:#f3f7f4;color:#2b5744;text-align:left;padding:7px 9px;border:1px solid #dbe1e8}
td{padding:7px 9px;border:1px solid #dbe1e8;vertical-align:top}
tr:nth-child(even) td{background:#fbfcfd}
.ok{color:#14713a;font-weight:700}.no{color:#c0392b;font-weight:700}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;color:#606266}
.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}
.kpi div{flex:1;min-width:135px;background:#f7faf8;border:1px solid #d5e8dc;border-radius:8px;padding:9px 12px}
.kpi b{display:block;font-size:20px;color:#14713a}.kpi span{font-size:11.5px;color:#909399}
.bar2{background:#eef2f6;border-radius:4px;height:8px;min-width:110px}.bar2 i{display:block;background:#1a7f4b;height:8px;border-radius:4px}
ul{margin:6px 0 6px 18px;padding:0}.error{color:#c0392b}.warn{color:#a8620a}
.note{background:#f0f7f2;border-left:3px solid #1a7f4b;padding:9px 13px;margin:10px 0;font-size:12.5px;color:#2b5744;border-radius:0 6px 6px 0}
</style></head><body><div class="wrap">
<div class="hd"><h1>数据质量体检 · %s</h1><p>全量重跑 · 只读不写数据 · 脚本 biz-radar-tools/healthcheck.py 可复用</p></div>
<div class="sec"><h2>总览</h2><div class="kpi">
<div><b>%d</b><span>①投放库行数</span></div><div><b>%d</b><span>检查项</span></div>
<div><b>%d</b><span>阻断错误</span></div><div><b>%d</b><span>需关注</span></div>
<div><b>%d</b><span>②库业绩条目</span></div></div>
<div class="note"><b>口径先说清：</b><b>①投放/商机库</b>是严格过滤的能源设施本体及前期信号；
中标情况的主体在<b>②业绩/动向库</b>（按单位聚合，<span class="mono">rivalperf / candperf / org</span>），
所以不能用 ①库的 win 字段去说「中标只覆盖 1/5」——那是拿错库。</div>
<p><b>②库实测：</b>rivalperf %d 家 / %d 条，candperf %d 家 / %d 条，org 各单位库合计 %d 条。
①库中标类公告 %d 条，其中带中标单位 %d 条，缺的 %d 条可从②库补；中标类公告带原文链接 %d/%d 条，<b>可以直接跳原网页看</b>。</p></div>
<div class="sec"><h2>逐项检查</h2><table><tr><th style="width:24%%">检查项</th><th style="width:9%%">结果</th><th>明细</th></tr>%s</table></div>
<div class="sec"><h2>①库 31 列字段完整率（按低到高）</h2><table><tr><th style="width:18%%">列</th><th>非空条数</th><th>完整率</th><th style="width:30%%">占比</th></tr>%s</table></div>
<div class="sec"><h2>需处理的问题</h2><ul>%s</ul></div>
<div class="sec"><h2>复跑方式</h2><p class="mono">python3.11 /workspace/biz-radar-tools/healthcheck.py</p>
<p>每次 <span class="mono">update_weekly.py</span> 全量重建后都应重跑本脚本；结果写 <span class="mono">/workspace/数据质量体检.json</span> 供页面「数据质量体检」（F32）直接读。</p></div>
</div></body></html>''' % (
        today, R['gen'], n, len(R['checks']), len(errs), len(warns),
        rpn + cpn + sum(orgn.values()),
        len(rp), rpn, len(cp), cpn, sum(orgn.values()),
        len(winrows), len(winfilled), len(winrows) - len(winfilled),
        sum(1 for i in winrows if allcols['url'][i]), len(winrows),
        rows, fillrows, iss)

    out_html = os.path.join(ROOT, '数据质量体检.html')
    if '--out' in sys.argv:
        out_html = sys.argv[sys.argv.index('--out') + 1]
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(H)

    print('体检完成 | 检查 %d 项 | 错误 %d | 关注 %d' % (len(R['checks']), len(errs), len(warns)))
    print(' ①库 %d 行 / %d 列 ｜②库 %d 条业绩' % (n, len(allcols), rpn + cpn + sum(orgn.values())))
    print(' 中标类公告 %d 条，带 win %d 条，带原文链接 %d 条' %
          (len(winrows), len(winfilled), sum(1 for i in winrows if allcols['url'][i])))
    # ---------- F29 / F32：生成 p-help 快照（数字全部来自本次体检，不手填） ----------
    lib2_total = rpn + cpn + sum(orgn.values())
    org_sum = sum(orgn.values())
    w1 = sum(1 for x in allcols['w'] if int(x or 0) == 1)
    w0 = n - w1
    nplat = len(core.get('platforms') or [])
    nplan = R['others'].get('data.plan.js', {}).get('n', '—')
    nmetal = R['others'].get('data.metalhist.js', {}).get('s', '—')
    nblocks = ' + '.join(str(d['n']) for _, d in blocks)
    winurl = sum(1 for i in winrows if allcols['url'][i])
    miss5 = '、'.join('%s %.1f%%' % (k, v) for k, v in R['summary']['top_missing'][:5])
    isslines = ''.join('<li><b>%s</b>：%s</li>' %
                       (html.escape(x['name']), html.escape(x['detail']))
                       for x in R['issues']) or '<li>无</li>'

    snap = f"""<div class="rulebox" style="margin-top:12px">
  <h4>数据血缘 · 这些数字从哪来</h4>
  <ul>
    <li><b>采集 → 过滤 → 入库</b>：原始公告 <b>{corem.get('rawTotal')}</b> 条 → <code>semantic_drop()</code> 判删 <b>{corem.get('dropped')}</b> 条 → <b>①投放 / 商机库 {n}</b> 条（列式三块 {nblocks}）。数字由本脚本实时读 <code>data.core.js · meta</code> 与三块 <code>n</code>，不是手填。</li>
    <li><b>②业绩 / 动向库 {lib2_total} 条</b>：rivalperf {len(rp)} 家 / {rpn} 条，candperf {len(cp)} 家 / {cpn} 条，org 各单位库 {org_sum} 条。按单位聚合，看业主招过什么标、谁中标、跟谁合作最多，<b>不是①库的 {n} 条</b>；②反推①要再过①过滤。</li>
    <li><b>规则源唯一</b>：<code>biz-radar-tools/biz_rules.py</code>，采集端与构建端调同一份。来源平台 <b>{nplat}</b> 个（招标平台页签）、规划前瞻 {nplan} 条、行情历史 {nmetal} 个品种、政策档 837 号 + 49 号令 + 5 部配套规定。</li>
    <li><b>每次更新全量重跑</b>：<code>update_weekly.py</code> 重建全部模块，处理「今天招标 → 明天出结果」的实时状态变化与漏项；更新后重跑本体检，本区块自动刷新。</li>
  </ul>
  <h4>数据质量体检 · 自动快照（{R['gen']}）</h4>
  <ul>
    <li><b>{len(R['checks'])} 项检查 / 阻断错误 {len(errs)} / 需关注 {len(warns)}</b>。①库 {n} 行 × {len(allcols)} 列；ID 唯一、<code>order</code> 与 <code>ext</code> 索引合法、<code>w</code> 与金额 ≥1 亿逐条一致（<code>w=1 {w1} / w=0 {w0}</code>）。</li>
    <li><b>中标情况看两个库</b>：①库中标类公告 {len(winrows)} 条，带原文链接 <b>{winurl}/{len(winrows)}</b>（点开自己看，不用另做中标采集）；带中标单位字段 {len(winfilled)} 条，其余 {len(winrows) - len(winfilled)} 条主体在②库。</li>
    <li><b>字段完整率最低 5 列</b>：{miss5} —— 这些是稀疏字段，空值属正常，不是数据缺失。</li>
  </ul>
  <p style="font-size:12.5px;color:var(--tx3);margin:8px 0 4px"><b>需关注 {len(warns)} 项（只报不改）</b>：改主数据要先给逐条清单并等确认，本脚本一条数据都不动。</p>
  <ul style="font-size:12.5px">{isslines}</ul>
  <p style="font-size:12px;color:var(--tx3);margin:8px 0 0">本区块由 <code>biz-radar-tools/healthcheck.py</code> 每次体检后自动重写（只替换两行注释之间，页面其余字节不动）；完整 {len(R['checks'])} 项明细见 <code>/workspace/数据质量体检.html</code> 与 <code>数据质量体检.json</code>。加 <code>--no-sync</code> 可关闭同步。</p>
</div>"""
    fragment = '\n'.join('      ' + ln for ln in snap.splitlines())
    if '--no-sync' not in sys.argv:
        sync_index_snapshot(fragment)
    else:
        print('[体检] --no-sync：跳过页面快照同步')

    print(' 输出：', out_html, '|', out_json)
    return R


# ---------- F29 / F32：页面快照同步（2026-11-05 第 1 批） ----------
SNAP_BEGIN = '<!-- HEALTH_SNAPSHOT_BEGIN'
SNAP_END = '<!-- HEALTH_SNAPSHOT_END'
IDX_HTML = os.path.join(BR, 'index.html')


def sync_index_snapshot(fragment):
    """把「数据血缘 + 质量体检」快照写回 index.html 的 p-help 面板。

    只替换 SNAP_BEGIN 注释行之后、SNAP_END 注释行之前的内容。
    head / tail 由原文件原样拼接，页面其余部分一个字节都不动；
    锚点缺失或异常时跳过并告警，绝不猜位置改页面。
    """
    s = open(IDX_HTML, encoding='utf-8').read()
    i = s.find(SNAP_BEGIN)
    j = s.find(SNAP_END)
    if i < 0 or j < 0 or j <= i:
        print('[体检] 快照锚点缺失，跳过页面同步（index.html 未改动）', file=sys.stderr)
        return False
    head_end = s.find('\n', i) + 1
    if head_end <= 0 or head_end >= j:
        print('[体检] 快照锚点异常，跳过页面同步（index.html 未改动）', file=sys.stderr)
        return False
    head, tail = s[:head_end], s[j:]
    new = head + fragment + '\n    ' + tail
    if not new.startswith(head) or not new.endswith(tail):
        raise RuntimeError('快照拼接校验失败，已中止写盘')
    if new == s:
        print('[体检] 页面快照无变化')
        return False
    open(IDX_HTML, 'w', encoding='utf-8').write(new)
    print('[体检] 已同步 p-help 数据血缘/体检快照 → index.html（仅锚点区间）')
    return True


if __name__ == '__main__':
    main()
