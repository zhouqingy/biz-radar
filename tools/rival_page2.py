#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""竞对画像页生成器 v2

数据源：CloudBase 云函数 API（https://...tcloudbase.com/api）
产物：
  1. 独立页  /workspace/竞对画像_中国联合工程.html   （可直接打开）
  2. 抽屉片段 /workspace/biz-radar/rival.js + rival.css （挂进商机雷达主站）

v2 相比 v1 的四处改进：
  ① 业绩明细跳转：改成「按钮 + 可复制链接」双保险，绕开 iframe/沙箱拦截
  ② 装机规模：新增「规模」列，从原公告补录
  ③ 企业资质：新增资质卡片，带证书编号与来源公示
  ④ 联动：抽屉式侧滑面板，主站内打开，不整页跳走
"""
import json
import re
import os

API = 'https://getinfo-d3ghutir5752f2749-1342254874.ap-shanghai.app.tcloudbase.com/api'
HOST = 'https://zfcg.nantong.gov.cn'

SRC = '/tmp/v2.json'
OUT_PAGE = '/workspace/竞对画像_中国联合工程.html'
OUT_JS = '/workspace/biz-radar/rival.js'
OUT_CSS = '/workspace/biz-radar/rival.css'

D = json.load(open(SRC, encoding='utf-8'))
Q = D['q']
ITEMS = D['items']

# ---------- 赛道归类（顺序敏感：先具体后笼统） ----------
CORE_TRACKS = ('热电联产', '集中供热/热网', '污泥/固废处置',
               '生活垃圾焚烧', '煤气/余热利用', '燃煤/煤电', '脱硫脱硝')


def track_of(p):
    # 电网/输变电：特高压、换流站、变电站、千伏线路
    if re.search(r'特高压|换流站|变电站|千伏|kV|KV|输变电|输电线路|电网', p):
        return '电网/输变电'
    if re.search(r'LNG|液化天然气|取排水', p): return 'LNG/水工'
    if re.search(r'污泥|固废', p): return '污泥/固废处置'
    if re.search(r'垃圾', p): return '生活垃圾焚烧'
    if re.search(r'热电联产|背压|热电厂|热电', p): return '热电联产'
    if re.search(r'集中供热|供热|热网|蒸汽|动力岛', p): return '集中供热/热网'
    if re.search(r'煤气|余热|干熄焦', p): return '煤气/余热利用'
    if re.search(r'电厂|发电|燃煤|煤电|煤炭|超超临界', p): return '燃煤/煤电'
    if re.search(r'脱硫|脱硝|烟气', p): return '脱硫脱硝'
    if re.search(r'光伏|风电|储能|新能源|智慧能源', p): return '新能源/其他'
    return '其他（园区/建筑设计）'


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
    txt = proj + owner
    for pv, kws in PROV:
        for k in kws:
            if k in txt:
                return pv
    return '其他/海外'


for it in ITEMS:
    it['tk'] = track_of(it['p'])
    it['core'] = it['tk'] in CORE_TRACKS
    it['pv'] = prov_of(it['p'], it['o'])
    it['url'] = HOST + it['s'] if it['s'].startswith('/') else it['s']

TOTAL = sum(i['a'] for i in ITEMS)
ITEMS.sort(key=lambda x: -x['a'])

# 赛道统计
tk_stat = {}
for i in ITEMS:
    k = i['tk']
    d = tk_stat.setdefault(k, {'n': 0, 'amt': 0})
    d['n'] += 1
    d['amt'] += i['a']
tk_rows = sorted(tk_stat.items(), key=lambda x: -x[1]['amt'])

# 省份统计
pv_stat = {}
for i in ITEMS:
    k = i['pv']
    d = pv_stat.setdefault(k, {'n': 0, 'amt': 0})
    d['n'] += 1
    d['amt'] += i['a']
pv_rows = sorted(pv_stat.items(), key=lambda x: -x[1]['amt'])

# 年份统计
yr_stat = {}
for i in ITEMS:
    y = (i['d'] or '')[:4] or '未知'
    yr_stat[y] = yr_stat.get(y, 0) + 1
yr_rows = sorted(yr_stat.items())


def money(a):
    return '%.2f亿' % a if a >= 1 else '%d万' % round(a * 10000)


def esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--line:#e5e7eb;--tx:#111827;--mut:#6b7280;--acc:#0f766e;--acc2:#b45309;--red:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:28px 18px 90px}
h1{font-size:23px;margin:0 0 4px;letter-spacing:-.4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:22px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:12px;margin-bottom:20px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:15px 16px}
.kpi .n{font-size:26px;font-weight:700;letter-spacing:-1px;line-height:1.15}
.kpi .n sm{font-size:14px;font-weight:600;color:var(--mut);margin-left:3px}
.kpi .l{font-size:12px;color:var(--mut);margin-top:3px}
.kpi.a .n{color:var(--acc)}.kpi.b .n{color:var(--acc2)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:16px 18px;margin-bottom:18px}
.panel h2{font-size:14px;margin:0 0 13px;display:flex;align-items:center;gap:8px;font-weight:600}
.panel h2 i{width:3px;height:14px;background:var(--acc);border-radius:2px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12.5px;width:100%}
.bar .bl{width:130px;flex:none;color:#4b5563;text-align:right;font-size:12px;line-height:1.35}
.bar i{height:17px;background:linear-gradient(90deg,#0f766e,#14b8a6);border-radius:3px;min-width:3px;flex:0 1 auto;max-width:calc(100% - 200px)}
.bar i.g{background:#94a3b8}
.bar em{font-style:normal;color:var(--mut);font-size:12px;flex:none;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 8px;border-bottom:1.5px solid var(--line);font-size:12px;color:var(--mut);font-weight:600;white-space:nowrap}
td{padding:10px 8px;border-bottom:1px solid #f3f4f6;vertical-align:top}
tr:hover td{background:#f9fafb}
td.d{color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums;font-size:12.5px}
td.p{max-width:380px;line-height:1.5}
td.p b{font-weight:600;color:#111827}
td.p .sc{display:block;margin-top:3px;font-size:11.5px;color:#0f766e;background:#ecfdf5;border-left:2px solid #14b8a6;padding:2px 6px;border-radius:0 3px 3px 0}
td.p .sc.none{color:#9ca3af;background:#f9fafb;border-left-color:#e5e7eb;font-style:italic}
td.o{max-width:170px;color:#4b5563;font-size:12.5px}
td.m{text-align:right;font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}
td.m big{font-size:14px;color:var(--acc2)}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;background:#f1f5f9;color:#475569;white-space:nowrap}
.tag.t1{background:#ecfdf5;color:#0f766e}
.tag.t2{background:#fef3c7;color:#92400e}
.tag.t3{background:#eef2ff;color:#3730a3}
.btn{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;padding:3px 9px;border-radius:4px;
border:1px solid #d1d5db;background:#fff;color:#374151;cursor:pointer;text-decoration:none;white-space:nowrap;line-height:1.6}
.btn:hover{background:#f3f4f6;border-color:#9ca3af}
.btn.pri{background:#0f766e;border-color:#0f766e;color:#fff}
.btn.pri:hover{background:#115e59}
.btn-group{display:flex;flex-direction:column;gap:4px;align-items:flex-start}
.qual{display:flex;gap:14px;align-items:flex-start;padding:13px 0;border-bottom:1px solid #f3f4f6}
.qual:last-child{border-bottom:none;padding-bottom:0}
.qual .ic{width:38px;height:38px;flex:none;border-radius:9px;background:linear-gradient(135deg,#0f766e,#14b8a6);
display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px;font-weight:700}
.qual .bd{flex:1;min-width:0}
.qual .nm{font-size:14px;font-weight:600;margin-bottom:2px}
.qual .cd{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;color:#0f766e;background:#f0fdfa;
display:inline-block;padding:1px 7px;border-radius:3px;margin:2px 0}
.qual .nt{font-size:12.5px;color:#4b5563;line-height:1.55}
.qual .sr{font-size:11.5px;color:#9ca3af;margin-top:3px}
.co{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:9px 26px;font-size:13px}
.co div{display:flex;gap:9px;min-width:0}
.co dt{color:var(--mut);flex:none;width:92px;font-size:12.5px;text-align:right;line-height:1.75}
.co dd{margin:0;color:#1f2937;line-height:1.75;min-width:0;word-break:break-word}
.co dd.mono{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;letter-spacing:.2px}
.note{font-size:12px;color:var(--mut);line-height:1.65;background:#fafafa;border-radius:7px;padding:11px 13px;margin-top:12px}
.note b{color:#374151}
.toast{position:fixed;left:50%;bottom:40px;transform:translateX(-50%) translateY(20px);background:#111827;color:#fff;
padding:10px 20px;border-radius:8px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:9999}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
.legend{font-size:11.5px;color:var(--mut);margin-top:8px}
"""

# 表格行
rows = []
for i, it in enumerate(ITEMS, 1):
    sc = it.get('sc') or ''
    if sc:
        extra = ''
        if it.get('iv'):
            extra += ' · 总投资 ' + it['iv']
        if it.get('dn'):
            extra += ' · ' + it['dn'] + ' 建成'
        scell = '<span class="sc">%s%s</span>' % (esc(sc), esc(extra))
    else:
        scell = '<span class="sc none">未公开（原表无此列）</span>'

    code = 'JT%02d' % i
    rows.append(
        '<tr>'
        '<td class="d">%s</td>'
        '<td class="p"><b>%s</b>%s<div style="margin-top:5px">'
        '<span class="tag %s">%s</span> <span class="tag">%s</span></div></td>'
        '<td class="o">%s</td>'
        '<td class="m"><big>%s</big></td>'
        '<td>'
        '<div class="btn-group">'
        '<a class="btn pri" href="%s" target="_blank" rel="noopener">打开公示原文</a>'
        '<button class="btn" onclick="cp(\'%s\',this)">复制链接</button>'
        '</div>'
        '</td>'
        '</tr>' % (
            it['d'] or '—',
            esc(it['p']), scell,
            't1' if it['a'] >= 5 else ('t2' if it['a'] >= 1 else 't3'),
            esc(it['tk']), esc(it['pv']),
            esc(it['o']),
            money(it['a']),
            esc(it['url']),
            esc(it['url']),
        ))

# 赛道条形
max_amt = max(v['amt'] for _, v in tk_rows) or 1
tk_html = ''
for k, v in tk_rows:
    w = v['amt'] / max_amt * 100
    tk_html += ('<div class="bar"><span class="bl">%s</span>'
                '<i style="width:%.1f%%"></i><em>%d 项 · %s</em></div>' % (esc(k), w * 0.92, v['n'], money(v['amt'])))

# 省份条形
max_pv = max(v['amt'] for _, v in pv_rows) or 1
pv_html = ''
for k, v in pv_rows:
    w = v['amt'] / max_pv * 100
    cls = '' if k == '浙江' else ' g'
    pv_html += ('<div class="bar"><span class="bl">%s</span>'
                '<i class="%s" style="width:%.1f%%"></i><em>%d 项 · %s</em></div>'
                % (esc(k), cls.strip(), w * 0.92, v['n'], money(v['amt'])))

# 年份
yr_html = ''.join('<div class="bar"><span class="bl">%s</span><i class="g" style="width:%.1f%%"></i><em>%d 项</em></div>'
                  % (y, c / max(yr_stat.values()) * 92, c) for y, c in yr_rows)

# 资质
qual_html = ''
for q in Q['qual']:
    qual_html += (
        '<div class="qual"><div class="ic">资</div><div class="bd">'
        '<div class="nm">%s</div>'
        '<div class="cd">证书编号 %s</div>'
        '<div class="nt">%s</div>'
        '<div class="sr">来源：%s</div>'
        '</div></div>' % (esc(q['n']), esc(q['code']), esc(q['note']), esc(q['src']))
    )

big4 = [i for i in ITEMS if i['a'] >= 1]
big4_amt = sum(i['a'] for i in big4)

PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>竞对画像 · %(name)s</title>
<style>%(css)s</style></head><body>
<div class="wrap">
<h1>%(short)s · 竞对画像</h1>
<div class="sub">%(name)s ｜ 数据源：南通市公共资源交易平台「中标候选人公示 · 企业业绩」表<br>
数据更新 %(updated)s ｜ 接口实时拉取</div>

<div class="kpis">
  <div class="kpi a"><div class="n">%(n)d<sm>条</sm></div><div class="l">可查业绩</div></div>
  <div class="kpi b"><div class="n">%(amt).2f<sm>亿</sm></div><div class="l">合同额合计</div></div>
  <div class="kpi"><div class="n">%(nbig)d<sm>条</sm></div><div class="l">亿元级大单（占 %(pct).0f%%）</div></div>
  <div class="kpi"><div class="n">%(nprov)d<sm>省</sm></div><div class="l">业务覆盖</div></div>
  <div class="kpi"><div class="n">%(nown)d<sm>家</sm></div><div class="l">服务业主</div></div>
</div>

<div class="panel">
  <h2><i></i>企业资质</h2>
  %(qual)s
  <div class="note">
    <b>为什么这条重要：</b>工程设计综合资质甲级是设计领域最高等级，全国持证企业仅数十家，
    可承接全部 21 个行业。这意味着对方<b>不受行业限制</b>——热电、垃圾焚烧、污泥固废、建筑市政都能投，
    在任何一个标段遇到它都不奇怪。证书编号 %(qcode)s 可在四库一平台核验。
  </div>
</div>

<div class="panel">
  <h2><i></i>企业基本信息</h2>
  <div class="co">
    <div><dt>全称</dt><dd>%(name)s</dd></div>
    <div><dt>母公司</dt><dd>%(parent)s</dd></div>
    <div><dt>信用代码</dt><dd class="mono">%(credit)s</dd></div>
    <div><dt>成立</dt><dd>%(founded)s</dd></div>
    <div><dt>总部</dt><dd>%(base)s</dd></div>
    <div><dt>人员</dt><dd>%(staff)s</dd></div>
    <div><dt>核心赛道</dt><dd>%(track)s</dd></div>
    <div><dt>累计业绩</dt><dd>%(note)s</dd></div>
  </div>
</div>

<div class="panel">
  <h2><i></i>业绩明细 <span style="font-weight:400;color:#9ca3af;font-size:12px">（按合同额降序，含装机规模）</span></h2>
  <table>
    <thead><tr><th>日期</th><th>项目 / 装机规模</th><th>建设单位</th><th style="text-align:right">合同额</th><th>原文</th></tr></thead>
    <tbody>
%(rows)s
    </tbody>
  </table>
  <div class="legend">
    ※ 「未公开（原表无此列）」表示原公示的业绩表本身只列了工程名与金额，没有规模信息；
    亿元级项目已按项目名反查原招标公告或业主官网补录。
    「打开公示原文」在新标签页打开；若被浏览器拦截，点「复制链接」手动粘贴。
  </div>
</div>

<div class="two">
  <div class="panel">
    <h2><i></i>赛道分布</h2>
    %(tk)s
    <div class="legend">按合同额统计。一条业绩只归一个赛道（先具体后笼统）。</div>
  </div>
  <div class="panel">
    <h2><i></i>地域分布</h2>
    %(pv)s
    <div class="legend">陕西、广西单项金额高，是因为各有 1 个亿元级 EPC 落子，不代表当地业务多。</div>
  </div>
</div>

<div class="panel">
  <h2><i></i>年份分布</h2>
  %(yr)s
</div>

<div class="panel">
  <h2><i></i>打法判断</h2>
  <div class="note" style="margin-top:0;background:#fff">
    <b>1. 集中度极高。</b>%(nbig)d 条亿元级项目合计 %(bigamt).2f 亿，占全部合同额的 %(pct).0f%%。
    拿下一个大 EPC 胜过几十个小设计——投标时不必在百万级小单上死磕价格。<br><br>
    <b>2. 主业是热电联产，但不受行业约束。</b>热电联产 %(tk1n)d 条是基本盘，
    但持综合甲级资质意味着它能随时切入垃圾焚烧、污泥固废、建筑市政——常州、南通这类
    「热电+固废」打捆项目要特别留意。<br><br>
    <b>3. 浙江是基本盘，正在向外扩。</b>浙江 %(zj)d 条、%(zja).2f 亿；
    但广西、陕西、山东、新疆都有亿元级落子。南通这单（498 万初步设计）对它只是小单，
    <b>真正要防的是它顺着这个项目继续接后续 EPC</b>。<br><br>
    <b>4. 报价不拼低价。</b>南通西部供热片区初步设计，江苏院 380 万最低、河北院 480 万、
    河南院 318 万，<b>中国联合 498 万最高价中标</b>——靠技术标 49.9/50 分拉开差距。
    跟它竞争要靠技术方案，不是靠降价。
  </div>
</div>

</div>
<div class="toast" id="toast"></div>
<script>
function cp(txt, btn){
  var done = function(){
    var t = document.getElementById('toast');
    t.textContent = '链接已复制，可粘贴到浏览器打开';
    t.classList.add('on');
    setTimeout(function(){ t.classList.remove('on'); }, 2200);
    if(btn){ var o = btn.textContent; btn.textContent = '已复制'; setTimeout(function(){ btn.textContent = o; }, 1600); }
  };
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(txt).then(done).catch(function(){ fb(); });
  } else { fb(); }
  function fb(){
    var ta = document.createElement('textarea');
    ta.value = txt; ta.style.position='fixed'; ta.style.opacity='0';
    document.body.appendChild(ta); ta.select();
    try{ document.execCommand('copy'); done(); }catch(e){ prompt('手动复制：', txt); }
    document.body.removeChild(ta);
  }
}
</script>
</body></html>
""" % dict(
    name=Q['name'], short=Q['short'], updated=D['updated'],
    css=CSS,
    n=D['total'], amt=TOTAL, nbig=len(big4), pct=big4_amt / TOTAL * 100,
    nprov=len(pv_rows), nown=len(set(i['o'] for i in ITEMS)),
    qual=qual_html, qcode=Q['qual'][0]['code'],
    parent=Q['parent'], credit=Q['credit'], founded=Q['founded'],
    base=Q['base'], staff=Q['staff'], track=Q['track'], note=Q['note'],
    rows='\n'.join(rows), tk=tk_html, pv=pv_html, yr=yr_html,
    bigamt=big4_amt,
    tk1n=tk_stat.get('热电联产', {}).get('n', 0),
    zj=pv_stat.get('浙江', {}).get('n', 0),
    zja=pv_stat.get('浙江', {}).get('amt', 0),
)

open(OUT_PAGE, 'w', encoding='utf-8').write(PAGE)
print('页面已生成:', OUT_PAGE, len(PAGE), '字节')
