#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对业绩挖掘 · 页面原型生成 perf_sheet.py
========================================
把 mine_perf.py 产出的 raw/perf_*.json 渲染成一张可直接看的单页 HTML。
目的：先让人判断「这些数据有没有用」，再决定要不要接进主站。

输出：/workspace/biz-radar-tools/perf_sheet.html
"""
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(ROOT, 'perf_sheet.html')


def esc(s):
    return (str(s or '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def load():
    items = []
    meta = {}
    p = os.path.join(RAW, 'perf_nantong.json')
    if os.path.exists(p):
        d = json.load(open(p, encoding='utf-8'))
        meta = {'site': d.get('site_name'), 'rg': d.get('rg'), 'updated': d.get('updated')}
        items = d.get('items', [])
    # 去重：同一(unit, proj, date)
    seen, uniq = set(), []
    for x in items:
        k = (x.get('unit'), x.get('proj'), x.get('date'))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(x)
    return uniq, meta


def money(a):
    if not a:
        return '—'
    if a >= 1:
        return '%.2f亿' % a
    return '%.0f万' % (a * 10000)


def amt_band(a):
    if not a:
        return '金额未披露'
    if a < 0.01:
        return '<100万'
    if a < 0.1:
        return '100-1000万'
    if a < 1:
        return '1000万-1亿'
    if a < 5:
        return '1-5亿'
    return '>5亿'


BAND_ORDER = ['>5亿', '1-5亿', '1000万-1亿', '100-1000万', '<100万', '金额未披露']


def main():
    items, meta = load()
    if not items:
        print('没有数据，先跑 mine_perf.py')
        return

    # ---- 单位画像 ----
    g = defaultdict(list)
    for x in items:
        g[x['unit']].append(x)

    units = []
    for u, v in g.items():
        amts = [x['amt'] for x in v if x.get('amt')]
        units.append({
            'unit': u,
            'n': len(v),
            'sum': sum(amts),
            'avg': (sum(amts) / len(amts)) if amts else 0,
            'owners': sorted({x['owner'] for x in v if x.get('owner')}),
            'years': sorted({(x['date'] or '')[:4] for x in v if x.get('date')}),
            'items': sorted(v, key=lambda a: a.get('date') or '', reverse=True),
        })
    units.sort(key=lambda a: (-a['n'], -a['sum']))

    # ---- 汇总 ----
    bands = Counter(amt_band(x.get('amt')) for x in items)
    tracks = Counter(x.get('track') or '非主业（房建/市政/景观等）' for x in items)
    owners = Counter(x['owner'] for x in items if x.get('owner'))
    all_amts = [x['amt'] for x in items if x.get('amt')]

    # ---- 明细行 ----
    rows = []
    for x in sorted(items, key=lambda a: (a.get('date') or ''), reverse=True):
        tag = x.get('track') or ''
        rows.append(
            '<tr data-track="%s" data-unit="%s">'
            '<td class="d">%s</td>'
            '<td class="u">%s</td>'
            '<td class="p">%s</td>'
            '<td class="o">%s</td>'
            '<td class="a">%s</td>'
            '<td>%s</td>'
            '</tr>' % (
                esc(tag), esc(x['unit']),
                esc((x.get('date') or '')[:7]),
                esc(x['unit']),
                esc(x['proj']),
                esc(x['owner']),
                ('%.2f 亿' % x['amt']) if (x.get('amt') or 0) >= 1 else (money(x.get('amt')) if x.get('amt') else esc(x.get('amt_txt') or '—')),
                ('<span class="tag">%s</span>' % esc(tag)) if tag else '<span class="tag off">非主业</span>',
            ))

    # ---- 单位卡 ----
    cards = []
    for u in units:
        chips = ''.join('<span class="chip">%s</span>' % esc(y) for y in u['years'])
        own = '、'.join(esc(o) for o in u['owners'][:4])
        if len(u['owners']) > 4:
            own += ' 等 %d 家' % len(u['owners'])
        det = []
        for x in u['items'][:6]:
            det.append('<li><div class="dp">%s</div><div class="dm">%s · %s · %s</div></li>' % (
                esc(x['proj']), esc((x.get('date') or '')[:7]),
                money(x.get('amt') if x.get('amt') else 0) if x.get('amt') else esc(x.get('amt_txt') or '—'),
                esc(x['owner'])))
        cards.append("""
<div class="card">
  <div class="ch"><b>%s</b><span class="cn">%d 条</span></div>
  <div class="cstat"><span class="big">%.2f 亿</span><span class="sub">累计 &nbsp;|&nbsp; 均 %.0f 万/条</span></div>
  <div class="cy">%s</div>
  <div class="co">业主：%s</div>
  <ul class="cl">%s</ul>
</div>""" % (esc(u['unit']), u['n'], u['sum'], u['avg'] * 10000, chips, own, ''.join(det)))

    bmax = max(bands.values()) if bands else 1
    bhtml = ''.join(
        '<div class="bar"><span class="bl">%s</span><i style="width:%d%%"></i><em>%d</em></div>'
        % (b, int(bands[b] / bmax * 100), bands[b])
        for b in BAND_ORDER if bands.get(b))

    tmax = max(tracks.values())
    thtml = ''.join(
        '<div class="bar"><span class="bl">%s</span><i class="g" style="width:%d%%"></i><em>%d</em></div>'
        % (t, int(n / tmax * 100), n) for t, n in tracks.most_common())

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    energy = sum(n for t, n in tracks.items() if t not in ('非主业（房建/市政/景观等）',))

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>竞对业绩挖掘 · 南通样板</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e6e8ec;--tx:#1b1f27;--mut:#6b7280;--acc:#0f766e;--warn:#b45309;--red:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:26px 18px 70px}
h1{font-size:21px;margin:0 0 6px}
.lead{color:var(--mut);font-size:13px;margin-bottom:20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .n{font-size:25px;font-weight:700;letter-spacing:-.5px}
.kpi .l{font-size:12px;color:var(--mut);margin-top:2px}
.kpi.hot .n{color:var(--acc)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:20px}
.panel h2{font-size:14px;margin:0 0 12px;display:flex;align-items:center;gap:8px}
.panel h2 i{width:3px;height:14px;background:var(--acc);border-radius:2px;display:inline-block}
.two{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:760px){.two{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:10px;margin-bottom:7px;font-size:12.5px}
.bar .bl{width:132px;flex:none;color:var(--mut);text-align:right}
.bar i{height:16px;background:#0f766e;border-radius:3px;min-width:2px}
.bar i.g{background:#94a3b8}
.bar em{font-style:normal;color:var(--mut);font-size:12px}
table{width:100%%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 10px;border-bottom:1.5px solid var(--line);font-size:12px;color:var(--mut);font-weight:600;position:sticky;top:0;background:var(--card)}
td{padding:10px;border-bottom:1px solid #f1f3f5;vertical-align:top}
tr:hover td{background:#fafbfc}
td.d{color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums}
td.u{font-weight:600;max-width:200px}
td.p{max-width:340px;color:#334155}
td.o{max-width:190px;color:var(--mut);font-size:12.5px}
td.a{white-space:nowrap;font-variant-numeric:tabular-nums;font-weight:600;color:#0f172a}
.tag{background:#e6f4f1;color:#0f766e;padding:1px 7px;border-radius:20px;font-size:11px;white-space:nowrap}
.tag.off{background:#f1f3f5;color:#9aa3af}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}
.card{border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:#fff}
.ch{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.ch b{font-size:14px;line-height:1.4}
.cn{font-size:11px;color:#fff;background:#0f766e;border-radius:20px;padding:1px 8px;white-space:nowrap}
.cstat{margin:8px 0 6px}
.cstat .big{font-size:19px;font-weight:700;color:var(--acc)}
.cstat .sub{font-size:11.5px;color:var(--mut);margin-left:6px}
.cy{margin-bottom:4px}
.chip{display:inline-block;background:#f1f3f5;color:#495057;border-radius:4px;padding:0 6px;font-size:11px;margin-right:4px}
.co{font-size:12px;color:var(--mut);margin-bottom:8px}
.cl{margin:0;padding-left:16px;font-size:12px}
.cl li{margin-bottom:5px}
.dp{color:#334155;line-height:1.45}
.dm{color:#9aa3af;font-size:11.5px}
.note{border-left:3px solid var(--warn);background:#fffbeb;padding:12px 15px;border-radius:0 8px 8px 0;font-size:13px;line-height:1.7}
.note b{color:var(--warn)}
.note ul{margin:8px 0 0;padding-left:18px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.filters button{border:1px solid var(--line);background:#fff;border-radius:20px;padding:5px 13px;font-size:12.5px;cursor:pointer;color:#495057}
.filters button.on{background:#0f766e;border-color:#0f766e;color:#fff}
::-webkit-scrollbar{height:8px;width:8px}::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:4px}
.tbwrap{max-height:560px;overflow:auto;border:1px solid #f1f3f5;border-radius:8px}
</style></head><body><div class="wrap">

<h1>竞对业绩挖掘 · 南通样板</h1>
<div class="lead">数据源：%(site)s（%(rg)s）· 中标候选人公示页内嵌「企业业绩」表 · 采集时间 %(now)s<br>
每条业绩 = 一家单位过去干过的一个项目，带建设单位、中标时间、中标金额。这是**有实证**的竞对画像原料。</div>

<div class="kpis">
  <div class="kpi"><div class="n">%(n)d</div><div class="l">业绩条数（去重后）</div></div>
  <div class="kpi"><div class="n">%(nu)d</div><div class="l">涉及单位</div></div>
  <div class="kpi"><div class="n">%(no)d</div><div class="l">涉及业主</div></div>
  <div class="kpi"><div class="n">%(sm).1f<small style="font-size:13px">亿</small></div><div class="l">累计中标金额</div></div>
  <div class="kpi %(hotcls)s"><div class="n">%(en)d</div><div class="l">命中我们赛道</div></div>
</div>

<div class="panel">
  <h2><i></i>先说结论：链路跑通了，但这个源对我们用处有限</h2>
  <div class="note">
    <b>好消息</b>：翻页、详情抓取、rowspan 表格解析、金额换算、赛道过滤、按单位聚合——<b>全链路打通</b>，
    换任何一个有同类业绩表的站点，改一个配置就能跑。
    <ul>
      <li>翻页规则已破解：南通第 1 页 <code>tradeInfo.html</code>，第 2-8 页 <code>/{N}.html</code>，第 9 页起才用 <code>?pageIndex=N</code>。早期用 pageIndex 翻前 8 页，服务端直接忽略参数、永远返回第 1 页。</li>
      <li>表格里「单位名称」列用 rowspan 合并，只有每块首行有值，后面几行少一个 td —— 按 rowspan 继承而不是固定列数，才能对上。</li>
    </ul>
    <b>坏消息</b>：南通是<b>市级全行业</b>交易中心，%(n)d 条里只有 %(en)d 条落在我们的赛道上，
    而且那 %(en)d 条全是<b>农村生活污水</b>和<b>小型分布式光伏</b>，<b>热电联产 / 余热发电 / 煤气发电 / 脱硫脱硝 一条都没有</b>。
    第 9-15 页更是入账 0 条——近期这批公示结构完全偏房建、市政、学校、安置房。
  </div>
</div>

<div class="two">
  <div class="panel"><h2><i></i>金额量级分布</h2>%(bhtml)s
  <div style="font-size:12px;color:var(--mut);margin-top:10px">中位数区间落在 100-1000 万，以市政设计、监理、小型施工为主，和 EPC 总包不是一回事。</div></div>
  <div class="panel"><h2><i></i>赛道命中分布</h2>%(thtml)s
  <div style="font-size:12px;color:var(--mut);margin-top:10px">「非主业」占 %(offpct)d%%，这些就是采回来但对我们没用的部分。</div></div>
</div>

<div class="panel">
  <h2><i></i>按单位聚合 —— 这就是「竞对画像」的雏形</h2>
  <div class="cards">%(cards)s</div>
</div>

<div class="panel">
  <h2><i></i>业绩明细（%(n)d 条，按中标时间倒序）</h2>
  <div class="filters">
    <button class="on" data-f="all">全部 %(n)d</button>
    <button data-f="hit">只看命中赛道 %(en)d</button>
    <button data-f="off">只看非主业 %(off2)d</button>
  </div>
  <div class="tbwrap"><table><thead><tr>
    <th style="width:74px">中标时间</th><th style="width:190px">单位</th><th>工程名称</th>
    <th style="width:180px">建设单位</th><th style="width:92px">金额</th><th style="width:86px">赛道</th>
  </tr></thead><tbody id="tb">%(rows)s</tbody></table></div>
</div>

<div class="panel">
  <h2><i></i>下一步怎么走（三条路，代价不同）</h2>
  <table><thead><tr><th style="width:150px">路线</th><th>做法</th><th style="width:210px">代价 / 风险</th></tr></thead><tbody>
  <tr><td><b>A. 继续铺市级</b></td><td>把江浙沪皖 40 多个地级市交易中心都接上，靠量砸出命中</td><td>开发 2-3 天，每市适配一次；命中率仍只有 10-20%%；需要节流防封</td></tr>
  <tr><td><b>B. 直接转能源平台</b></td><td>华能、大唐、国家电投、华电、浙能、宝武的电子采购平台。你截图里那种「玉林白平产业园热电联产 EPC · 6.6 亿」就出自这类平台</td><td>逐家适配，门槛高（华能 412、需 UA）；但<b>每条都跟我们相关</b></td></tr>
  <tr><td><b>C. 双轨</b></td><td>市级只留「能源/环保」类目（南通有 categoryNum 可细分），省掉 80%% 噪声；主攻能源平台</td><td>推荐。工作量介于两者之间，命中率最高</td></tr>
  </tbody></table>
</div>

</div>
<script>
var btns=document.querySelectorAll('.filters button'),rows=document.querySelectorAll('#tb tr');
btns.forEach(function(b){b.onclick=function(){
  btns.forEach(function(x){x.classList.remove('on')});b.classList.add('on');
  var f=b.dataset.f;
  rows.forEach(function(r){
    var t=r.dataset.track||'';
    r.style.display=(f==='all'||(f==='hit'&&t)||(f==='off'&&!t))?'':'none';
  });
};});
</script>
</body></html>""" % {
        'site': esc(meta.get('site') or '南通市公共资源交易中心'),
        'rg': esc(meta.get('rg') or '江苏'),
        'now': now,
        'n': len(items),
        'nu': len(units),
        'no': len(owners),
        'sm': sum(all_amts),
        'en': energy,
        'hotcls': '' if energy > len(items) * 0.3 else 'hot',
        'bhtml': bhtml,
        'thtml': thtml,
        'offpct': int(tracks.get('非主业（房建/市政/景观等）', 0) / len(items) * 100),
        'off2': tracks.get('非主业（房建/市政/景观等）', 0),
        'cards': ''.join(cards),
        'rows': ''.join(rows),
    }

    open(OUT, 'w', encoding='utf-8').write(html)
    print('已生成', OUT)
    print('  业绩 %d 条 · 单位 %d 家 · 业主 %d 家 · 累计 %.2f 亿 · 命中赛道 %d 条'
          % (len(items), len(units), len(owners), sum(all_amts), energy))


if __name__ == '__main__':
    main()
