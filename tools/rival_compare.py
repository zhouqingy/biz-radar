#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三家同场竞对对比页生成器。

数据：/tmp/fn3/data.json（由 build_fn_data.py 产出）
产物：/workspace/竞对对比_南通西部供热.html

页面重点不是罗列三份画像，而是回答一个问题：
同一个标里三家对手各是什么底细、我们该怕谁、下次怎么打。
"""
import json
import os

SRC = '/tmp/fn3/data.json'
OUT = '/workspace/竞对对比_南通西部供热.html'
HOST = 'https://zfcg.nantong.gov.cn'

D = json.load(open(SRC, encoding='utf-8'))
UNITS = D['units']


def esc(s):
    return (str(s or '')
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def money(a):
    if a is None:
        return '—'
    return '%.2f亿' % a if a >= 1 else '%d万' % round(a * 10000)


def pct(a, b):
    return '%.0f%%' % (a / b * 100) if b else '—'


# ---------- 对比维度 ----------
def big_cnt(u):
    return sum(1 for x in u['items'] if x['a'] >= 1)


def max_one(u):
    return max((x['a'] for x in u['items']), default=0)


def avg(u):
    return u['amount'] / u['n'] if u['n'] else 0


def span(u):
    ds = sorted(x['d'] for x in u['items'] if x['d'])
    return (ds[0][:4] + '–' + ds[-1][:4]) if len(ds) >= 2 else (ds[0][:4] if ds else '—')


def qual_top(u):
    q = u.get('qual') or []
    if not q:
        return '—'
    return q[0]['n']


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--line:#e5e7eb;--tx:#111827;--mut:#6b7280;--acc:#0f766e;--acc2:#b45309;--red:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.7 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:28px 18px 90px}
h1{font-size:23px;margin:0 0 5px;letter-spacing:-.4px}
.sub{color:var(--mut);font-size:13px;margin-bottom:10px}
.src{font-size:12px;color:#9ca3af;margin-bottom:22px}
.src a{color:var(--acc)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 17px;position:relative;overflow:hidden}
.card.me{border-color:var(--acc);box-shadow:0 0 0 2px rgba(15,118,110,.09)}
.card .rk{position:absolute;top:11px;right:13px;font-size:11px;color:#9ca3af;font-weight:600}
.card h3{font-size:14.5px;margin:0 0 2px;line-height:1.4;padding-right:46px;letter-spacing:-.2px}
.card .par{font-size:11.5px;color:var(--mut);margin-bottom:11px;line-height:1.45}
.card .big{font-size:25px;font-weight:700;letter-spacing:-1px;color:var(--acc2);line-height:1.15}
.card .big sm{font-size:13px;font-weight:600;color:var(--mut);margin-left:3px}
.card .bl{font-size:11.5px;color:var(--mut);margin-bottom:12px}
.card ul{margin:0;padding:0;list-style:none;font-size:12.5px}
.card li{display:flex;justify-content:space-between;gap:10px;padding:4px 0;border-bottom:1px dashed #f1f3f5}
.card li:last-child{border-bottom:none}
.card li span{color:var(--mut)}
.card li b{font-weight:600;font-variant-numeric:tabular-nums}
.card .tagline{margin-top:11px;font-size:11.5px;color:var(--acc);background:#f0fdfa;border-radius:5px;padding:6px 9px;line-height:1.5}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:18px}
.panel h2{font-size:14px;margin:0 0 14px;display:flex;align-items:center;gap:8px;font-weight:600}
.panel h2 i{width:3px;height:14px;background:var(--acc);border-radius:2px}
.panel h2 em{font-style:normal;font-weight:400;font-size:11.5px;color:#9ca3af}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 10px;border-bottom:1.5px solid var(--line);font-size:12px;color:var(--mut);font-weight:600;white-space:nowrap}
th:first-child{width:150px}
td{padding:9px 10px;border-bottom:1px solid #f3f4f6;vertical-align:top}
td.dim{color:var(--mut);font-size:12.5px;white-space:nowrap}
tr:hover td{background:#fafbfc}
.num{font-variant-numeric:tabular-nums;font-weight:600}
.best{color:var(--acc);font-weight:700}
.worst{color:var(--red)}
.rkbar{display:flex;align-items:center;gap:9px;margin-bottom:7px;font-size:12.5px}
.rkbar .bl{width:150px;flex:none;color:#4b5563;text-align:right;font-size:12px}
.rkbar i{height:16px;border-radius:3px;min-width:3px;flex:0 1 auto;max-width:calc(100% - 210px);background:linear-gradient(90deg,#0f766e,#14b8a6)}
.rkbar i.b{background:linear-gradient(90deg,#b45309,#f59e0b)}
.rkbar i.c{background:#94a3b8}
.rkbar em{font-style:normal;color:var(--mut);font-size:11.5px;white-space:nowrap}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;align-items:start}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.item{display:flex;gap:9px;padding:7px 0;border-bottom:1px dashed #f1f3f5;font-size:12.5px}
.item:last-child{border-bottom:none}
.item .ix{width:19px;height:19px;flex:none;border-radius:5px;background:#f1f5f9;color:#64748b;
display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;margin-top:2px}
.item .bd{flex:1;min-width:0;line-height:1.55}
.item .bd b{color:#111827}
.item .bd span{color:var(--mut)}
.toast{position:fixed;left:50%;bottom:40px;transform:translateX(-50%) translateY(20px);background:#111827;color:#fff;
padding:10px 20px;border-radius:8px;font-size:13px;opacity:0;transition:.25s;pointer-events:none;z-index:9999}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
.btn{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;padding:3px 9px;border-radius:4px;
border:1px solid #d1d5db;background:#fff;color:#374151;cursor:pointer;text-decoration:none;white-space:nowrap;line-height:1.6}
.btn:hover{background:#f3f4f6}
.btn.pri{background:var(--acc);border-color:var(--acc);color:#fff}
.btn.pri:hover{background:#115e59}
.tag{display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;background:#f1f5f9;color:#475569;white-space:nowrap}
.tag.t1{background:#ecfdf5;color:#0f766e}.tag.t2{background:#fef3c7;color:#92400e}.tag.t3{background:#eef2ff;color:#3730a3}
.tb2 td.p{line-height:1.5}
.tb2 td.p b{font-weight:600}
.up{color:var(--red);font-weight:700}
.down{color:var(--acc);font-weight:700}
"""

# ---------- 卡片 ----------
cards = ''
order = sorted(UNITS, key=lambda u: -u['amount'])
ROLE_RANK = {}
for u in UNITS:
    r = u.get('role') or ''
    ROLE_RANK[u['name']] = 1 if '第一' in r else (2 if '第二' in r else (3 if '第三' in r else 9))

for i, u in enumerate(order, 1):
    me = ROLE_RANK.get(u['name']) == 1
    cards += '<div class="card%s">' % (' me' if me else '')
    cards += '<div class="rk">%s</div>' % ('★ 中标' if me else '第%d名' % ROLE_RANK.get(u['name'], i))
    cards += '<h3>%s</h3>' % esc(u['name'])
    cards += '<div class="par">%s</div>' % esc(u['parent'])
    cards += '<div class="big">%.2f<sm>亿</sm></div>' % u['amount']
    cards += '<div class="bl">可查业绩 %d 条 · %s</div>' % (u['n'], span(u))
    cards += '<ul>'
    cards += '<li><span>热电主赛道</span><b>%d 条 / %s</b></li>' % (u['core_n'], money(u['core_amount']))
    cards += '<li><span>单笔最大</span><b>%s</b></li>' % money(max_one(u))
    cards += '<li><span>覆盖省份</span><b>%d 省</b></li>' % u['nprov']
    cards += '<li><span>服务业主</span><b>%d 家</b></li>' % u['nowner']
    cards += '<li><span>本次报价</span><b>%s</b></li>' % esc(u['quote'])
    cards += '</ul>'
    if u.get('tagline') or u.get('tag'):
        cards += '<div class="tagline">%s</div>' % esc(u.get('tag'))
    cards += '</div>'

# ---------- 对比表 ----------
dims = [
    ('合同额合计', lambda u: money(u['amount']), True),
    ('业绩条数', lambda u: '%d 条' % u['n'], True),
    ('热电主赛道条数', lambda u: '%d 条' % u['core_n'], True),
    ('单笔最大金额', lambda u: money(max_one(u)), True),
    ('平均单笔', lambda u: money(avg(u)), True),
    ('亿元级大单', lambda u: '%d 条' % big_cnt(u), True),
    ('覆盖省份', lambda u: '%d 省' % u['nprov'], True),
    ('服务业主', lambda u: '%d 家' % u['nowner'], True),
    ('业绩年份跨度', span, False),
    ('最高设计资质', qual_top, False),
    ('本次报价', lambda u: u['quote'], False),
    ('本次名次', lambda u: u['role'].split('·')[-1].strip().replace('中标候选人', '').strip() or '—', False),
]


def cmp_val(u, fn):
    return fn(u)


NUMERIC_DIMS = {'合同额合计', '业绩条数', '热电主赛道条数', '单笔最大金额',
                '平均单笔', '亿元级大单', '覆盖省份', '服务业主'}

thead = '<tr><th>对比项</th>' + ''.join('<th>%s</th>' % esc(u['abbr']) for u in UNITS) + '</tr>'
tbody = ''
for name, fn, higher_better in dims:
    # 只为数值型维度算最优
    vals = [fn(u) for u in UNITS]
    numeric = []
    for u in UNITS:
        v = u['amount'] if name == '合同额合计' else (
            u['n'] if name == '业绩条数' else (
                u['core_n'] if name == '热电主赛道条数' else (
                    max_one(u) if name == '单笔最大金额' else (
                        avg(u) if name == '平均单笔' else (
                            big_cnt(u) if name == '亿元级大单' else (
                                u['nprov'] if name == '覆盖省份' else (
                                    u['nowner'] if name == '服务业主' else None)))))))
        numeric.append(v)
    ok = [x for x in numeric if x is not None]
    mx = max(ok) if ok else None
    tbody += '<tr><td class="dim">%s</td>' % esc(name)
    for u, v, nv in zip(UNITS, vals, numeric):
        cls = ''
        # 只有纯数值维度才标最优；资质、报价、名次这类不做优劣判断
        if nv is not None and mx and nv == mx and name in NUMERIC_DIMS:
            cls = ' best'
        tbody += '<td class="num%s">%s</td>' % (cls, esc(v))
    tbody += '</tr>'

# ---------- 主赛道拉力条 ----------
mxamt = max(u['amount'] for u in UNITS) or 1
bars = ''
for idx, u in enumerate(UNITS):
    cl = '' if idx == 0 else ('b' if idx == 1 else 'c')
    bars += ('<div class="rkbar"><span class="bl">%s</span>'
             '<i class="%s" style="width:%.1f%%"></i><em>%s · 主赛道 %s</em></div>'
             % (esc(u['abbr']), cl, u['amount'] / mxamt * 88, money(u['amount']),
                pct(u['core_amount'], u['amount'])))

# ---------- 三家资质重卡 ----------
qualh = ''
for u in UNITS:
    qualh += '<div style="margin-bottom:16px"><div style="font-size:12.5px;font-weight:600;margin-bottom:7px">%s</div>' % esc(u['abbr'])
    for q in (u.get('qual') or []):
        qualh += ('<div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #f3f4f6">'
                  '<div style="width:26px;height:26px;flex:none;border-radius:7px;background:linear-gradient(135deg,#0f766e,#14b8a6);'
                  'color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700">资</div>'
                  '<div style="flex:1;min-width:0"><div style="font-size:13px;font-weight:600">%s</div>'
                  '<div style="font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#0f766e">%s</div>'
                  '<div style="font-size:12px;color:#6b7280;line-height:1.5">%s</div>'
                  '<div style="font-size:11px;color:#9ca3af">来源：%s</div></div></div>'
                  % (esc(q['n']), esc(q['code']), esc(q['note']), esc(q['src'])))
    if not (u.get('qual') or []):
        qualh += '<div style="font-size:12px;color:#9ca3af">暂无公开资质记录</div>'
    qualh += '</div>'

# ---------- 明细表：按金额排序的三家全部业绩 ----------
allrows = []
for u in UNITS:
    for x in u['items']:
        allrows.append((u, x))
allrows.sort(key=lambda p: -p[1]['a'])
detail = ''
for u, x in allrows[:40]:
    cls = x['a'] >= 5 and 't1' or (x['a'] >= 1 and 't2' or 't3')
    url = HOST + x['s'] if x['s'].startswith('/') else x['s']
    sc = ('<span style="display:block;margin-top:2px;font-size:11px;color:#0f766e;background:#ecfdf5;'
          'border-left:2px solid #14b8a6;padding:1px 6px;border-radius:0 3px 3px 0">%s</span>' % esc(x['sc'])
          ) if x['sc'] else ''
    dim = '' if x['core'] else ' style="opacity:.55"'
    detail += ('<tr%s><td style="white-space:nowrap;font-size:12px;color:#6b7280">%s</td>'
               '<td style="font-size:12.5px;font-weight:600;white-space:nowrap">%s</td>'
               '<td class="p" style="max-width:340px"><b>%s</b>%s'
               '<div style="margin-top:3px"><span class="tag %s">%s</span> <span class="tag">%s</span></div></td>'
               '<td style="font-size:12px;color:#4b5563;max-width:160px">%s</td>'
               '<td class="num" style="text-align:right;white-space:nowrap">%s</td>'
               '<td><a class="btn pri" href="%s" target="_blank" rel="noopener">原文</a></td></tr>'
               % (dim, esc(x['d'] or '—'), esc(u['abbr']), esc(x['p']), sc, cls,
                  esc(x['tk']), esc(x['pv']), esc(x['o'] or '原表未列'), money(x['a']), esc(url)))

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>三家同场竞对对比 · 南通西部供热一期初步设计</title>
<style>%(css)s</style></head><body>
<div class="wrap">

<h1>三家同场竞对对比</h1>
<div class="sub">南通市区西部供热片区热电联产项目一期工程初步设计 · 2026-04-23 中标候选人公示</div>
<div class="src">数据源：南通市公共资源交易平台公示原文中的「中标候选人企业业绩」表，共 %(ndoc)d 条去重后业绩 ·
更新 %(upd)s</div>

<div class="cards">%(cards)s</div>

<div class="panel"><h2><i></i>合同额体量对比 <em>括号内为热电主赛道占比</em></h2>%(bars)s
<div style="font-size:11.5px;color:#9ca3af;margin-top:9px">
注意：江苏院总额最高，但其中 19.9 亿是上海石化一条 EPC。比总量更该看的是「单笔规模」和「热电主赛道厚度」。</div>
</div>

<div class="panel"><h2><i></i>逐项硬碰硬 <em>绿色为该项最优</em></h2>
<table><thead>%(thead)s</thead><tbody>%(tbody)s</tbody></table></div>

<div class="cols">
<div class="panel"><h2><i></i>三家资质摆一起</h2>%(qual)s</div>
<div class="panel"><h2><i></i>怎么看这张表</h2>
<div style="font-size:12.5px;line-height:1.75;color:#4b5563">
<div class="item"><div class="ix">1</div><div class="bd"><b>资质是硬门槛，不是加分项。</b>
江苏院持<span class="up">工程设计综合甲级</span>（A132015910），可跨 21 个行业投标；
中国联合也有综合甲级（A133000033）；<b>河北院只有电力行业甲级</b>（A113005001），
跨行业受限，但它勘察是综合甲级。这三家在任何跨行业热电标里资格都不会掉。</div></div>
<div class="item"><div class="ix">2</div><div class="bd"><b>中国联合的威胁在 EPC，不在设计。</b>
它 24.74 亿里 92%% 集中在 4 条亿元级 EPC 总包（玉林白平 6.6 亿、神华榆林 7.3 亿、
山发龙城污泥 4.9 亿、巨化 4.05 亿）。一旦标的是「设计+采购+施工」打包，它的优势最大。</div></div>
<div class="item"><div class="ix">3</div><div class="bd"><b>江苏院是本省地头蛇，低价也敢报。</b>
这次它报 380 万（最低），是中国联合 498 万打了 76 折，但技术标 44.31 分落后 5.66 分。
说明它<b>靠价格抢分、靠关系补技术</b>。在江苏本地项目上，它是首要提防对象。</div></div>
<div class="item"><div class="ix">4</div><div class="bd"><b>河北院体量小，但不是软柿子。</b>
8 条业绩全在热电主赛道，单笔 2193 万，比中国联合的均值还稳。
从河北、辽宁、山东一路南下，属于「客场作战、报价克制」的类型。</div></div>
</div></div>
</div>

<div class="panel"><h2><i></i>三家业绩合并看（按合同额降序，前 40 条）<em>灰字为非热电主赛道</em></h2>
<table class="tb2"><thead><tr><th>日期</th><th>单位</th><th>项目 / 规模</th><th>建设单位</th>
<th style="text-align:right">合同额</th><th>原文</th></tr></thead><tbody>%(detail)s</tbody></table>
<div style="font-size:11.5px;color:#9ca3af;margin-top:10px">
「原文」跳转到该条业绩所在的中标候选人公示页。规模为原表未列时，不做推测。</div></div>

</div>
<div class="toast" id="toast"></div>
<script>
function cp(t,btn){
  function done(){var x=document.getElementById('toast');x.textContent='链接已复制';
    x.classList.add('on');setTimeout(function(){x.classList.remove('on')},1600);}
  function fb(){var ta=document.createElement('textarea');ta.value=t;
    ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);
    ta.select();try{document.execCommand('copy');done();}catch(e){prompt('复制链接：',t);}document.body.removeChild(ta);}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done).catch(fb);}else{fb();}
}
</script></body></html>""" % {
    'css': CSS, 'cards': cards, 'bars': bars, 'thead': thead, 'tbody': tbody,
    'qual': qualh, 'detail': detail, 'ndoc': sum(u['n'] for u in UNITS),
    'upd': D.get('updated', ''),
}

open(OUT, 'w', encoding='utf-8').write(PAGE)
print('→', OUT, len(PAGE), '字节')
print('三家：', ' / '.join('%s %d条 %.2f亿' % (u['abbr'], u['n'], u['amount']) for u in UNITS))
