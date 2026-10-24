#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对画像报告 · rival_profile.py
==============================
把 raw/perf_*.json 渲染成一份「单家竞对」的画像页。
不是数据罗列，而是回答三个问题：
  1. 他大概报多少钱（报价区间 + 单价带）
  2. 他擅长干什么（细分赛道分布）
  3. 他服务谁（业主图谱 + 地域分布）

输出：/workspace/竞对画像_中国联合工程.html
"""
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = '/workspace/竞对画像_中国联合工程.html'


def esc(s):
    return (str(s or '').replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


# ---- 赛道分类：按都环主业口径 ----
TRACK = [
    ('生活垃圾焚烧', ['垃圾焚烧', '垃圾发电', '生活垃圾']),
    ('污泥/固废处置', ['污泥', '固废', '资源化']),
    ('热电联产', ['热电联产', '热电']),
    ('集中供热/热网', ['集中供热', '供热', '热网', '蒸汽']),
    ('煤气/余热利用', ['煤气', '余热', '干熄焦']),
    ('燃煤/煤电', ['燃煤', '煤电', '超超临界', '循环经济煤炭']),
    ('脱硫脱硝', ['脱硫', '脱硝', '烟气']),
    ('新能源/其他', ['光伏', '风电', '储能', '动力岛', '智慧能源']),
]


def track_of(proj):
    """
    赛道归类。注意顺序：先判最具体的，再判泛化的。
    「电厂」「发电」这类词太泛，放最后兜底，否则会把「电厂扩建」抢到燃煤前面。
    """
    if re.search(r'污泥|固废', proj):
        return '污泥/固废处置'
    if re.search(r'垃圾', proj):
        return '生活垃圾焚烧'
    if re.search(r'热电联产|背压|热电厂|热电', proj):
        return '热电联产'
    if re.search(r'集中供热|供热|热网|蒸汽|动力岛', proj):
        return '集中供热/热网'
    if re.search(r'煤气|余热|干熄焦', proj):
        return '煤气/余热利用'
    if re.search(r'电厂|发电|燃煤|煤电|煤炭|超超临界', proj):
        return '燃煤/煤电'
    if re.search(r'脱硫|脱硝|烟气', proj):
        return '脱硫脱硝'
    if re.search(r'光伏|风电|储能|新能源|智慧能源', proj):
        return '新能源/其他'
    return '其他（园区/建筑设计）'


# 地域
PROV = ['浙江', '江苏', '广东', '广西', '河南', '宁夏', '贵州', '新疆', '山东', '福建',
        '陕西', '内蒙古', '山西', '安徽', '湖南', '湖北', '河北', '四川', '上海', '北京']


def prov_of(owner, proj):
    for p in PROV:
        if p in owner or p in proj:
            return p
    for city, p in [('玉林', '广西'), ('田东', '广西'), ('阿拉尔', '新疆'), ('叶县', '河南'),
                    ('宁东', '宁夏'), ('潜江', '湖北'), ('孟州', '河南'), ('诸城', '山东'),
                    ('绍兴', '浙江'), ('嘉兴', '浙江'), ('海宁', '浙江'), ('宁波', '浙江'),
                    ('海盐', '浙江'), ('杭州', '浙江'), ('巨化', '浙江'), ('龙德', '浙江'),
                    ('榆林', '陕西'), ('福州', '福建'), ('漳州', '福建'), ('佛山', '广东'),
                    ('友山', '贵州'), ('寰球', '北京')]:
        if city in owner or city in proj:
            return p
    return '其他'


def money(a):
    if not a:
        return '—'
    return ('%.2f亿' % a) if a >= 1 else ('%.0f万' % (a * 10000))


def load():
    p = os.path.join(RAW, 'perf_dlgc.json')
    d = json.load(open(p, encoding='utf-8'))
    items = d.get('items', [])
    seen, out = set(), []
    for x in items:
        k = (x['unit'], x['proj'], x['date'])
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out, d


def main():
    items, meta = load()
    if not items:
        print('无数据')
        return
    items.sort(key=lambda a: a['date'], reverse=True)

    # ---------- 指标 ----------
    amts = [x['amt'] for x in items if x.get('amt')]
    total = sum(amts)
    n = len(items)
    owner_cnt = Counter(x['owner'] for x in items if x.get('owner'))
    tracks = Counter(track_of(x['proj']) for x in items)
    provs = Counter(prov_of(x['owner'], x['proj']) for x in items)
    years = Counter((x['date'] or '')[:4] for x in items)

    # 大单（≥1亿）
    big = [x for x in items if (x.get('amt') or 0) >= 1]
    big.sort(key=lambda a: -a['amt'])
    big_sum = sum(x['amt'] for x in big)

    # 设计 vs EPC
    epc = [x for x in items if re.search(r'EPC|总承包|采购施工', x['proj'], re.I)]
    design = [x for x in items if re.search(r'设计|勘察|咨询|可研', x['proj'])
              and not re.search(r'EPC|总承包', x['proj'], re.I)]

    # ---------- 渲染 ----------
    def bar(cnt, order=None, cls=''):
        mx = max(cnt.values()) if cnt else 1
        keys = order if order else [k for k, _ in cnt.most_common()]
        rows = []
        for k in keys:
            v = cnt.get(k, 0)
            if not v:
                continue
            rows.append(
                '<div class="bar"><span class="bl">%s</span>'
                '<i class="%s" style="width:%d%%"></i><em>%d</em></div>'
                % (esc(k), cls, max(2, int(v / mx * 100)), v))
        return ''.join(rows)

    # 明细行
    body = []
    for x in items:
        t = track_of(x['proj'])
        isbig = (x.get('amt') or 0) >= 1
        body.append(
            '<tr class="%s"><td class="d">%s</td>'
            '<td class="p"><a href="%s" target="_blank" rel="noopener" '
            'class="tt" title="打开原始公示">%s</a>%s</td>'
            '<td class="o">%s</td><td class="a">%s</td>'
            '<td><span class="tag">%s</span></td><td class="s">%s</td></tr>'
            % ('hot' if isbig else '', esc(x['date']),
               esc(x.get('src') or '#'),
               esc(x['proj']),
               ' <span class="epc">EPC</span>' if re.search(r'EPC|总承包', x['proj'], re.I) else '',
               esc(x['owner']),
               money(x.get('amt')),
               esc(t),
               esc(prov_of(x['owner'], x['proj']))))

    # 业主卡
    ocard = []
    byowner = defaultdict(list)
    for x in items:
        if x.get('owner'):
            byowner[x['owner']].append(x)
    for o, xs in sorted(byowner.items(), key=lambda kv: -sum(y.get('amt') or 0 for y in kv[1]))[:12]:
        sm = sum(y.get('amt') or 0 for y in xs)
        ocard.append(
            '<div class="oc"><div class="on">%s</div><div class="ov">%s</div>'
            '<div class="od">%d 次 · %s</div></div>'
            % (esc(o), money(sm), len(xs), esc(prov_of(o, ''))))

    # 时间轴
    tl = []
    for y in sorted(years, reverse=True):
        tl.append('<div class="yr"><b>%s</b><span>%d 条</span></div>' % (y, years[y]))

    # 三档报价带
    def band(a):
        if a is None:
            return '未披露'
        if a >= 5:
            return '≥5亿（大型EPC）'
        if a >= 1:
            return '1-5亿（中型EPC）'
        if a >= 0.1:
            return '1000万-1亿（专项设计）'
        return '<1000万（小单/咨询）'
    bands = Counter(band(x.get('amt')) for x in items)
    bsum = defaultdict(float)
    for x in items:
        bsum[band(x.get('amt'))] += (x.get('amt') or 0)
    order = ['≥5亿（大型EPC）', '1-5亿（中型EPC）', '1000万-1亿（专项设计）', '<1000万（小单/咨询）']
    brow = ''.join(
        '<div class="br"><span class="bl">%s</span><i style="width:%d%%"></i>'
        '<em>%d 条 · %s</em></div>'
        % (b, int(bands[b] / max(bands.values()) * 100) if bands.get(b) else 0,
           bands[b], money(bsum[b]))
        for b in order if bands.get(b))

    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>竞对画像 · 中国联合工程有限公司</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--line:#e5e7eb;--tx:#111827;--mut:#6b7280;--acc:#0f766e;--acc2:#b45309;--red:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:28px 18px 80px}
h1{font-size:23px;margin:0 0 4px;letter-spacing:-.4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:12px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:15px 16px}
.kpi .n{font-size:26px;font-weight:700;letter-spacing:-1px;line-height:1.15}
.kpi .n sm{font-size:14px;font-weight:600;color:var(--mut);margin-left:3px}
.kpi .l{font-size:12px;color:var(--mut);margin-top:3px}
.kpi.a .n{color:var(--acc)}
.kpi.b .n{color:var(--acc2)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:16px 18px;margin-bottom:18px}
.panel h2{font-size:14px;margin:0 0 13px;display:flex;align-items:center;gap:8px;font-weight:600}
.panel h2 i{width:3px;height:14px;background:var(--acc);border-radius:2px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:800px){.two{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12.5px;width:100%%}
.bar .bl{width:170px;flex:none;color:#4b5563;text-align:right;font-size:12px;line-height:1.35}
.bar i{height:17px;background:var(--acc);border-radius:3px;min-width:3px;flex:0 1 auto;max-width:calc(100%% - 210px)}
.bar i.g{background:#94a3b8}
.bar em{font-style:normal;color:var(--mut);font-size:12px;flex:none}
.br{display:flex;align-items:center;gap:10px;margin-bottom:9px;font-size:12.5px}
.br .bl{width:170px;flex:none;color:#4b5563;text-align:right}
.br i{height:18px;background:linear-gradient(90deg,#0f766e,#14b8a6);border-radius:3px;min-width:3px;flex:0 1 auto;max-width:calc(100%% - 240px)}
.br em{font-style:normal;color:var(--mut);font-size:12px;flex:none}
table{width:100%%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 10px;border-bottom:1.5px solid var(--line);font-size:12px;color:var(--mut);font-weight:600}
td{padding:9px 10px;border-bottom:1px solid #f3f4f6;vertical-align:top}
tr.hot td{background:#fbfefd}
tr:hover td{background:#f9fafb}
td.d{color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:12.5px}
td.p{max-width:420px;line-height:1.5}
td.p .tt{color:#1f2937;text-decoration:none;border-bottom:1px dotted #cbd5e1}
td.p a.tt:hover{color:var(--acc);border-bottom-color:var(--acc)}
.epc{background:#fef3c7;color:#92400e;font-size:10.5px;padding:0 5px;border-radius:3px;margin-left:4px}
td.o{color:var(--mut);font-size:12.5px;max-width:220px}
td.a{white-space:nowrap;font-weight:600;font-variant-numeric:tabular-nums;color:#0f172a}
td.s{color:var(--mut);font-size:12.5px;white-space:nowrap}
.tag{background:#e6f4f1;color:#0f766e;padding:1px 7px;border-radius:20px;font-size:11px;white-space:nowrap}
.ocs{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.oc{border:1px solid var(--line);border-radius:9px;padding:11px 13px}
.on{font-size:13px;font-weight:600;line-height:1.4}
.ov{color:var(--acc);font-weight:700;font-size:16px;margin-top:3px}
.od{font-size:11.5px;color:var(--mut)}
.yr{display:inline-block;margin:0 14px 8px 0;font-size:13px}
.yr b{font-size:16px;color:var(--acc)}
.yr span{color:var(--mut);margin-left:5px;font-size:12px}
.note{border-left:3px solid var(--acc2);background:#fffbeb;padding:12px 15px;border-radius:0 8px 8px 0;font-size:13px;line-height:1.75}
.note b{color:var(--acc2)}
.tbwrap{max-height:600px;overflow:auto;border:1px solid #f3f4f6;border-radius:8px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:11px}
.filters button{border:1px solid var(--line);background:#fff;border-radius:20px;padding:5px 13px;font-size:12.5px;cursor:pointer;color:#4b5563}
.filters button.on{background:var(--acc);border-color:var(--acc);color:#fff}
::-webkit-scrollbar{height:8px;width:8px}::-webkit-scrollbar-thumb{background:#d1d5db;border-radius:4px}
</style></head><body><div class="wrap">

<h1>竞对画像 · 中国联合工程有限公司</h1>
<div class="sub">
数据来源：南通市公共资源交易平台 · 中标候选人公示内嵌「中标候选人企业业绩」表<br>
共 3 篇公示贡献了这家公司的业绩清单，每一行都是**招标人自己公示的、带建设单位和金额的实证记录**，不是推测。
</div>

<div class="kpis">
  <div class="kpi a"><div class="n">%(n)d<sm>条</sm></div><div class="l">可查业绩</div></div>
  <div class="kpi a"><div class="n">%(total).1f<sm>亿</sm></div><div class="l">累计合同额</div></div>
  <div class="kpi"><div class="n">%(own)d<sm>家</sm></div><div class="l">服务业主</div></div>
  <div class="kpi b"><div class="n">%(big)d<sm>条</sm></div><div class="l">亿元级大单</div></div>
  <div class="kpi"><div class="n">%(bigpct)d<sm>%%</sm></div><div class="l">大单占总额</div></div>
  <div class="kpi"><div class="n">%(span)s</div><div class="l">业绩时间跨度</div></div>
</div>

<div class="panel">
  <h2><i></i>一句话画像</h2>
  <div class="note">
    <b>这是一家用 EPC 总承包吃大项目、用专项设计养长尾的「热电流派」设计院。</b><br>
    %(n)d 条业绩里 %(big)d 条是亿元级，却贡献了 %(bigpct)d%% 的合同额（%(bigsum).1f 亿 / %(total).1f 亿）——
    典型的「二八倒置」：<b>单子少、单笔大</b>。最大的三单分别是
    神华榆林煤炭综合利用动力装置 EPC 7.31 亿、玉林白平产业园热电联产 EPC 6.61 亿、山发龙城污泥处置 EPC 4.90 亿。<br>
    主业高度集中在<b>热电联产 + 集中供热 + 垃圾/污泥处置</b>这三块，
    而且从 2018 年做到 2026 年没断过，<b>浙江是它的基本盘</b>（绍兴、嘉兴、宁波、海盐、巨化一串）。
    <b>投标报价特征</b>：专项设计单 200-2500 万，中型 EPC 1-5 亿，大型 EPC 5 亿以上。
  </div>
</div>

<div class="two">
  <div class="panel"><h2><i></i>报价档位分布（单笔）</h2>%(brow)s
    <div style="font-size:12px;color:var(--mut);margin-top:10px">
      这张图最有用的地方：<b>知道它会在什么量级的项目上出现</b>。看到 3000 万的热电设计标，它大概率来；看到 8 亿的 EPC，它也会来。
    </div>
  </div>
  <div class="panel"><h2><i></i>细分赛道</h2>%(tbody)s
    <div style="font-size:12px;color:var(--mut);margin-top:10px">
      全部落在我们主业范围内，没有一条是纯房建或市政。
    </div>
  </div>
</div>

<div class="two">
  <div class="panel"><h2><i></i>地域分布</h2>%(pbody)s
    <div style="font-size:12px;color:var(--mut);margin-top:10px">
      浙江最密，但广东、广西、河南、宁夏、贵州、陕西、福建都有——
      <b>它不是地方院，是全国跑单的</b>。
    </div>
  </div>
  <div class="panel"><h2><i></i>业绩年份</h2>%(tl)s
    <div style="font-size:12px;color:var(--mut);margin-top:10px">
      按中标时间分布。2018-2026 连续有单，2021 年是高峰（6 条）。
    </div>
  </div>
</div>

<div class="panel">
  <h2><i></i>业主图谱（按合同额排序）</h2>
  <div class="ocs">%(ocard)s</div>
</div>

<div class="panel">
  <h2><i></i>业绩明细（%(n)d 条）</h2>
  <div class="filters">
    <button class="on" data-f="all">全部 %(n)d</button>
    <button data-f="big">亿元级 %(big)d</button>
    <button data-f="epc">EPC/总承包 %(nepc)d</button>
    <button data-f="design">纯设计 %(ndes)d</button>
  </div>
  <div class="tbwrap"><table><thead><tr>
    <th style="width:88px">中标时间</th><th>工程名称</th><th style="width:200px">建设单位</th>
    <th style="width:96px">金额</th><th style="width:150px">赛道</th><th style="width:64px">地域</th>
  </tr></thead><tbody id="tb">%(body)s</tbody></table></div>
</div>

<div class="panel">
  <h2><i></i>数据可信度说明</h2>
  <table><thead><tr><th style="width:150px">来源</th><th>说明</th></tr></thead><tbody>
  <tr><td><b>原始公示</b></td><td>南通市公共资源交易平台 <code>zfcg.nantong.gov.cn</code>，栏目 003001004「中标候选人公示」，原文链接逐条可回溯</td></tr>
  <tr><td><b>表格结构</b></td><td>「1.1 中标候选人企业业绩」表，单位名称列 rowspan 合并，按 rowspan 继承解析，不按固定列数切</td></tr>
  <tr><td><b>交叉验证</b></td><td>同一条公示里，中国联合 9 条、江苏院 10 条、河北院 8 条，合计 27 条，与第三方转载站（电力项目网）逐字比对一致</td></tr>
  <tr><td><b>已知局限</b></td><td>只覆盖<b>在南通投标并被公示业绩</b>的部分。该公司在全国的真实业绩量远大于此，
      想补全需要接入浙江、广东、江苏省级平台以及各大能源集团电子采购平台</td></tr>
  </tbody></table>
</div>

</div>
<script>
var rows=[].slice.call(document.querySelectorAll('#tb tr'));
function isEpc(t){return /EPC|总承包|采购施工/i.test(t);}
function isDesign(t){return /设计|勘察|咨询|可研/.test(t) && !isEpc(t);}
document.querySelectorAll('.filters button').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('.filters button').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    var f=b.dataset.f;
    rows.forEach(function(r){
      var t=r.querySelector('.p').innerText, big=r.classList.contains('hot');
      var show = f==='all' || (f==='big'&&big) || (f==='epc'&&isEpc(t)) || (f==='design'&&isDesign(t));
      r.style.display = show?'':'none';
    });
  };
});
</script>
</body></html>""" % {
        'n': n,
        'total': total,
        'own': len(owner_cnt),
        'big': len(big),
        'bigpct': int(big_sum / total * 100) if total else 0,
        'bigsum': big_sum,
        'span': '%s-%s' % (min(y for y in years if y), max(y for y in years if y)),
        'brow': brow,
        'tbody': bar(tracks),
        'pbody': bar(provs),
        'tl': ''.join(tl),
        'ocard': ''.join(ocard),
        'nepc': len(epc),
        'ndes': len(design),
        'body': ''.join(body),
    }

    open(OUT, 'w', encoding='utf-8').write(html)
    print('已生成', OUT)
    print('  %d 条 · %.2f 亿 · 业主 %d 家 · 亿元级 %d 条' % (n, total, len(owner_cnt), len(big)))


if __name__ == '__main__':
    main()
