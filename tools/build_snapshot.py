#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""商机雷达 V4 · GitHub Pages 静态快照生成器（只读 / 零第三方依赖 / 自包含）

两种用法：
  本机全量（生成页面 + 全部 JSON）：
    python3.11 app/snapshot/build_snapshot.py --full --page-src app/index.html \
        --data-dir biz-radar --out v4 --assets .
  GitHub Actions 每天只读重烤（数据没变 → 产物逐字节一致 → 空转绿灯）：
    python3.11 tools/build_snapshot.py --data-dir . --out v4

只做三件事：
  1. 只读解析**已筛好的** data*.js（JS 字面量词法扫描，不 eval、不执行、不改写）
  2. 把 §6 契约 12 条接口所需的「全量数据」烤成 <out>/api/*.json
  3. 可选：把 app/index.html 的 api() 门面换成静态适配层，生成 <out>/index.html

判定红线（AGENTS.md / 底稿 §5.30 R4）：
  「能不能投」只由服务端 biz_rules.judge() 在**入库时**判；本脚本不 import、不调用、
  不复制任何判定关键词，快照里 w 沿用入库值。前端只做视图筛选
  （q / facets / 排序 / 分页），属视图层，不重判、不过 semantic_drop()。

幂等：产物不含构建时间戳，版本号取数据包 meta.updated / dataAsOf；
      数据不变时每日重烤逐字节一致，workflow git diff --quiet 会直接跳过提交。
"""
import argparse
import json
import os
import re
import sys

# ── 与 app/server.py 同源的只读 JS 字面量解析器（不含任何业务判定）──────────
def _js_literal(s):
    i, n = 0, len(s)

    def ws():
        nonlocal i
        while i < n:
            if s[i].isspace():
                i += 1
            elif s.startswith('//', i):
                j = s.find('\n', i)
                i = n if j < 0 else j + 1
            elif s.startswith('/*', i):
                j = s.find('*/', i + 2)
                i = n if j < 0 else j + 2
            else:
                break

    def string():
        nonlocal i
        q = s[i]
        i += 1
        buf = []
        mp = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v', '0': '\0'}
        while i < n:
            c = s[i]
            if c == '\\':
                i += 1
                if i >= n:
                    break
                e = s[i]
                buf.append(mp.get(e, e))
                i += 1
            elif c == q:
                i += 1
                return ''.join(buf)
            else:
                buf.append(c)
                i += 1
        return ''.join(buf)

    def value():
        nonlocal i
        ws()
        if i >= n:
            return None
        c = s[i]
        if c in ('"', "'"):
            return string()
        if c == '{':
            return obj()
        if c == '[':
            return arr()
        for lit, val in (('true', True), ('false', False), ('null', None)):
            if s.startswith(lit, i):
                i += len(lit)
                return val
        st = i
        while i < n and s[i] not in ',}] \t\r\n':
            i += 1
        raw = s[st:i]
        if re.fullmatch(r'-?\d+', raw):
            return int(raw)
        try:
            return float(raw)
        except ValueError:
            return raw

    def obj():
        nonlocal i
        i += 1
        o = {}
        while True:
            ws()
            if i >= n or s[i] == '}':
                i += 1
                return o
            if s[i] == ',':
                i += 1
                continue
            if s[i] in ('"', "'"):
                k = string()
            else:
                st = i
                while i < n and (s[i].isalnum() or s[i] in '_$'):
                    i += 1
                k = s[st:i] or '?'
            ws()
            if i < n and s[i] == ':':
                i += 1
            o[k] = value()

    def arr():
        nonlocal i
        i += 1
        a = []
        while True:
            ws()
            if i >= n or s[i] == ']':
                i += 1
                return a
            if s[i] == ',':
                i += 1
                continue
            a.append(value())

    v = value()
    return v if isinstance(v, dict) else {}


CACHE = {}


def load_js(data_dir, fname):
    if fname in CACHE:
        return CACHE[fname]
    p = os.path.join(data_dir, fname)
    if not os.path.exists(p):
        CACHE[fname] = {}
        return {}
    s = open(p, encoding='utf-8').read()
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    s = re.sub(r'^\s*//.*$', '', s, flags=re.M)
    i, j = s.find('{'), s.rfind('}')
    if i < 0 or j <= i:
        CACHE[fname] = {}
        return {}
    raw = s[i:j + 1]
    try:
        d = json.loads(raw)
    except Exception:
        d = _js_literal(raw)
    if not isinstance(d, dict):
        d = {}
    CACHE[fname] = d
    return d


def as_list(v):
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        it = v.get('items')
        return it if isinstance(it, list) else [v]
    return []


ITEM_KEYS = ['id', 't', 'rg', 'city', 'st', 'g', 'sg', 'sG', 'sub', 'buyer', 'win',
             'amt', 'amtTxt', 'd', 'dl', 'mode', 'sc', 'bk', 'iv', 'dp', 'w', 'hm',
             'linkbad', 'url', 'hist', 'snip']
ORG_KEYS = ['rivals', 'buyers', 'latent', 'domestic', 'clients', 'partners', 'competitors']
NEWS_KEYS = ['trends', 'wechat', 'digest', 'overseas', 'overseaFlash', 'overseaOdi']


def facets(rows):
    out = {}
    for key, field in [('region', 'rg'), ('stage', 'st'), ('segment', 'sub')]:
        c = {}
        for x in rows:
            v = str(x.get(field) or '').strip()
            if v:
                c[v] = c.get(v, 0) + 1
        out[key] = [{'value': k, 'count': v} for k, v in
                    sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:30]]
    return out


def write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


# ── 前端静态适配层：只换 api() 门面，页面其余代码一字不改 ──────────────────
SNAP_JS = r'''/* ============ 静态快照适配层（GitHub Pages 版，2026-11-06）============
   页面其余代码一字未改，只替换 api() 门面。§6 契约不变：路径 / 参数 /
   响应结构与 app/server.py 一致，数据源从云端 /api/* 换成同目录 ./api/*.json。
   ⚠ 判定红线：这里只做视图筛选（q / region / stage / segment / focus /
     sort / kind / page / size），w 沿用入库值；不 import、不调用、不复制
     入库判定函数（judge、semantic_drop、focus_of），不重判「能不能投」。 */
var SNAP_CACHE={};
function snapLoad(n){
 if(!SNAP_CACHE[n])SNAP_CACHE[n]=fetch('./api/'+n+'.json',{headers:{'Accept':'application/json'}})
  .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
 return SNAP_CACHE[n];
}
function snapLower(x){return JSON.stringify(x).toLowerCase();}
function snapSlice(a,p,s){
 p=Math.max(1,parseInt(p,10)||1);s=Math.min(200,Math.max(1,parseInt(s,10)||20));
 return {items:a.slice((p-1)*s,p*s),page:p,size:s,count:a.length};
}
function snapGroup(d,p){
 var q=String(p.q||'').trim().toLowerCase(),out={};
 var kinds=String(p.kind||'').split(',').map(function(x){return x.trim();}).filter(Boolean);
 var type=String(p.type||'').trim();
 Object.keys(d.groups||{}).forEach(function(k){
  if(kinds.length&&kinds.indexOf('all')<0&&kinds.indexOf(k)<0)return;
  if(type&&type!==k&&!(type==='owner'&&(k==='buyers'||k==='clients'||k==='domestic')))return;
  var arr=(d.groups[k]||[]).filter(function(x){return !q||snapLower(x).indexOf(q)>=0;});
  var sl=snapSlice(arr,p.page,p.size||20);
  out[k]={count:arr.length,page:sl.page,size:sl.size,items:sl.items};
 });
 return {groups:out,meta:d.meta||{}};
}
function snapItems(d,p){
 var q=String(p.q||'').trim().toLowerCase(),focus=(p.focus==='1'||p.focus==='true');
 var hit=(d.items||[]).filter(function(x){
  if(focus&&String(x.w)!=='1'&&String(x.w)!=='1.0')return false;
  if(p.region&&String(x.rg||'')!==p.region)return false;
  if(p.stage&&String(x.st||'')!==p.stage)return false;
  if(p.segment&&String(x.sub||'')!==p.segment&&String(x.sg||'')!==p.segment)return false;
  if(q){var hay=[x.t,x.buyer,x.win,x.city,x.snip,x.sub]
    .map(function(v){return String(v==null?'':v);}).join(' ').toLowerCase();
   if(hay.indexOf(q)<0)return false;}
  return true;
 });
 var sort=p.sort||'sc';
 hit=hit.slice().sort(function(a,b){
  if(sort==='amt')return (parseFloat(b.amt)||0)-(parseFloat(a.amt)||0);
  if(sort==='d')return String(b.d||'').localeCompare(String(a.d||''));
  return (parseFloat(b.sc)||0)-(parseFloat(a.sc)||0);
 });
 var sl=snapSlice(hit,p.page,p.size||20);
 return {total:hit.length,page:sl.page,size:sl.size,items:sl.items,
         facets:d.facets||{},meta:d.meta||{}};
}
function snapSearch(q,all){
 var lim=6,g={},total=0;
 var it=snapItems(all.items,{q:q,size:lim});
 g.opportunities={count:it.total,items:it.items};
 var orgs=[];
 ['rivals','buyers','clients','partners'].forEach(function(k){
  (all.orgs.groups[k]||[]).forEach(function(x){
   if(orgs.length<lim&&snapLower(x).indexOf(q)>=0)
    orgs.push({group:k,name:x.n||x.name||''});
  });
 });
 g.orgs={count:orgs.length,items:orgs};
 var cl=(all.policies.clauses||[]).filter(function(c){return snapLower(c).indexOf(q)>=0;});
 g.policies={count:cl.length,items:cl.slice(0,lim)};
 var ni=[],nc=0;
 Object.keys(all.news.groups||{}).forEach(function(k){
  var a=(all.news.groups[k]||[]).filter(function(x){return snapLower(x).indexOf(q)>=0;});
  nc+=a.length;
  a.slice(0,2).forEach(function(x){ni.push({group:k,title:String(x.t||x.title||'').slice(0,80)});});
 });
 g.news={count:nc,items:ni.slice(0,lim)};
 Object.keys(g).forEach(function(k){total+=g[k].count||0;});
 return {q:q,groups:g,total:total,
         meta:{note:'跨库统一检索（静态快照）；命中不做业务判定，只是文本匹配'}};
}
function api(path,params,method){
 var p=params||{},m,P,q;
 var ok=function(d){state.offline=false;return d;};
 var bad=function(){state.offline=true;return null;};
 if(path==='/api/collect/status'||(method==='POST'&&path==='/api/collect/run'))P=snapLoad('collect');
 else if((m=path.match(/^\/api\/opportunities\/(.+)$/)))
  P=snapLoad('items').then(function(d){
   var x=(d.items||[]).filter(function(a){return String(a.id)===m[1];})[0];
   return x?{item:x,meta:{source:'静态快照 · 已筛好的①库'}}:{error:'not found',id:m[1]};});
 else if(path==='/api/opportunities')P=snapLoad('items').then(function(d){return snapItems(d,p);});
 else if(path==='/api/orgs')P=snapLoad('orgs').then(function(d){return snapGroup(d,p);});
 else if(path==='/api/news')P=snapLoad('news').then(function(d){return snapGroup(d,p);});
 else if(path==='/api/metals')P=snapLoad('metals').then(function(d){
  var a=(d.items||[]).filter(function(x){
   if(p.code&&String(x.code||'').toUpperCase()!==String(p.code).toUpperCase())return false;
   if(p.q&&snapLower(x).indexOf(String(p.q).toLowerCase())<0)return false;
   return true;});
  return {items:a,updated:d.updated,hist:d.hist||{},meta:d.meta||{}};});
 else if(path==='/api/policies')P=snapLoad('policies').then(function(d){
  q=String(p.q||'').trim().toLowerCase();
  var cl=(d.clauses||[]).filter(function(c){return !q||snapLower(c).indexOf(q)>=0;});
  return {policies:d.policies||[],related:d.related||[],clauses:cl.slice(0,60),
          timeline:d.timeline||[],total:cl.length,meta:d.meta||{}};});
 else if(path==='/api/search'){
  q=String(p.q||'').trim().toLowerCase();
  if(!q)P=Promise.resolve({q:p.q||'',groups:{},total:0,meta:{note:'空 q 如实返回 0'}});
  else P=Promise.all([snapLoad('items'),snapLoad('orgs'),
                      snapLoad('policies'),snapLoad('news')])
   .then(function(a){return snapSearch(q,{items:a[0],orgs:a[1],policies:a[2],news:a[3]});});
 }
 else if(path==='/api/changes')P=snapLoad('changes');
 else if(path==='/api/health')P=snapLoad('health');
 else if(path==='/api/rules')P=snapLoad('rules');
 else P=Promise.reject(new Error('未知契约路径 '+path));
 return P.then(ok).catch(bad);
}'''

API_OLD = """function api(path,params,method){
 var u=path+(params&&qs(params)?'?'+qs(params):'');
 return fetch(u,{method:method||'GET',headers:{'Accept':'application/json'}})
  .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();})
  .then(function(d){state.offline=false;return d;})
  .catch(function(){state.offline=true;return null;});
}"""


def build(args):
    os.makedirs(os.path.join(args.out, 'api'), exist_ok=True)
    d = load_js(args.data_dir, 'data.js')
    core = load_js(args.data_dir, 'data.core.js')
    meta = core.get('meta', {}) or d.get('meta', {}) or {}

    rows = d.get('items', []) or []
    slim = [{k: x[k] for k in ITEM_KEYS if k in x} for x in rows]
    written = []

    def put(name, obj):
        write_json(os.path.join(args.out, 'api', name + '.json'), obj)
        written.append(name + '.json')

    put('items', {
        'items': slim,
        'facets': facets(rows),
        'meta': {
            'source': 'biz-radar/data.js（已筛好的①库，只读静态快照）',
            'updated': meta.get('updated', ''),
            'total': meta.get('total', len(rows)),
            'note': '视图筛选；能不能投由 biz_rules.judge() 在入库时判定，快照不重判',
        },
    })
    put('orgs', {
        'groups': {k: as_list(d.get(k)) for k in ORG_KEYS},
        'meta': {'source': 'biz-radar/data.js + data.org.js（②库，按单位聚合）',
                 'note': '②反推①须再过①过滤；此处只读展示，不反推'},
    })
    put('news', {
        'groups': {k: as_list(d.get(k)) for k in NEWS_KEYS},
        'meta': {'source': 'biz-radar/data.js / data.news.js',
                 'note': 'wechat / digest 为 {updated,items} 包装，已展平'},
    })
    mt = core.get('metals', {}) or d.get('metals', {}) or {}
    hist = load_js(args.data_dir, 'data.metalhist.js').get('series', {}) or {}
    put('metals', {
        'items': mt.get('items', []) or [],
        'updated': mt.get('updated', ''),
        'hist': hist,
        'meta': {'source': 'data.core.js + data.metalhist.js'},
    })
    pol = load_js(args.data_dir, 'data.policy.js')
    plist, rlist = pol.get('policies', []) or [], pol.get('related', []) or []
    clauses = []
    for p in list(plist) + list(rlist):
        if not isinstance(p, dict):
            continue
        src = p.get('no') or p.get('short') or p.get('title') or ''
        for c in (p.get('clauses') or []):
            cc = dict(c) if isinstance(c, dict) else {'text': str(c)}
            cc.setdefault('policy', src)
            clauses.append(cc)
    put('policies', {
        'policies': plist, 'related': rlist, 'clauses': clauses,
        'timeline': pol.get('timeline', []), 'total': len(clauses),
        'meta': {'source': 'biz-radar/data.policy.js（JS 字面量，只读解析）',
                 'meta': pol.get('meta', {}), 'gen': pol.get('gen', ''),
                 'note': 'clauses 均为官方原文逐条，不是二手解读'},
    })
    put('changes', {'changes': load_js(args.data_dir, 'data.changes.js'),
                    'meta': {'source': 'biz-radar/data.changes.js'}})
    put('meta', {
        'snapshot': True,
        'updated': meta.get('updated', ''),
        'dataAsOf': meta.get('dataAsOf', ''),
        'total': meta.get('total', len(rows)),
        'source': '已筛好的 data*.js（页面完成前数据不变）',
        'note': '静态快照不含构建时间戳；数据未变时重烤逐字节一致',
    })

    if args.full:
        hp = os.path.join(args.assets, '数据质量体检.json')
        health = json.load(open(hp, encoding='utf-8')) if os.path.exists(hp) else {}
        put('health', health)
        rp = os.path.join(args.assets, 'biz-radar-tools')
        rules = {'imported': False, 'source': 'biz-radar-tools/biz_rules.py'}
        try:
            sys.path.insert(0, rp)
            import biz_rules as br
            codes = sorted(str(x) for x in (getattr(br, 'SEM_ACTIVE_CODES', []) or []))
            wl = [r[0] for r in (getattr(br, 'SEM_RULES', []) or [])]
            rules.update({
                'imported': True,
                'amt_focus_min_yi': getattr(br, 'AMT_FOCUS_MIN_YI', None),
                'sem_active_codes': codes,
                'sem_pending': list(getattr(br, 'SEM_PENDING', []) or []),
                'rule_count': len(getattr(br, 'SEM_RULES', []) or []),
                'wordlist_codes': wl,
                'active_code_count': len(codes),
                'guard_only_codes': sorted(set(codes) - set(str(x) for x in wl)),
                'functions': [n for n in ('judge', 'semantic_drop', 'focus_of', 'stat_title')
                              if hasattr(br, n)],
            })
            try:
                rules['stat_title'] = br.stat_title()
            except Exception as e:
                rules['stat_title_err'] = str(e)
        except Exception as e:
            rules['error'] = str(e)
        rules['note'] = ('判定只在服务端入库时执行：semantic_drop() 硬过滤 → judge() '
                         '判能否投 → focus_of() 定关注档；静态快照只搬运已判定结果')
        put('rules', rules)
        put('collect', {
            'status': 'planned', 'implemented': False,
            'message': '静态快照为只读交付；自动采集属后端分期，本页不产生任何数据变更。',
            'next': ['collect_v4.py 包装成任务', '入库前 semantic_drop() 硬过滤',
                     'judge() 判能否投', '增量入库 + hist 状态历史'],
        })

        if args.page_src:
            src = open(args.page_src, encoding='utf-8').read()
            if API_OLD not in src:
                raise SystemExit('❌ 页面里找不到 api() 门面，拒绝生成（避免静默产出坏页面）')
            out_html = src.replace(API_OLD, SNAP_JS, 1)
            out_html = out_html.replace("'API 已接通 · 只读'", "'静态快照 · 只读（Pages）'", 1)
            out_html = out_html.replace('<title>商机雷达 · V4</title>',
                                        '<title>商机雷达 · V4 静态快照</title>', 1)
            with open(os.path.join(args.out, 'index.html'), 'w', encoding='utf-8') as f:
                f.write(out_html)
            written.append('index.html')

    print('快照生成完成 | 数据目录 %s | 输出 %s | 文件 %d 个' %
          (args.data_dir, args.out, len(written)))
    for n in written:
        p = os.path.join(args.out, 'index.html') if n == 'index.html' else os.path.join(args.out, 'api', n)
        print('  %-18s %9d B' % (n, os.path.getsize(p)))
    print('①库条目 %d 条 | updated=%s dataAsOf=%s' %
          (len(slim), meta.get('updated', ''), meta.get('dataAsOf', '')))
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default='/workspace/biz-radar', help='data*.js 所在目录')
    ap.add_argument('--out', default='/workspace/v4', help='快照输出目录')
    ap.add_argument('--assets', default='/workspace', help='本机资产根（体检报告 / biz_rules.py）')
    ap.add_argument('--full', action='store_true', help='生成 health/rules/collect 与页面（本机用）')
    ap.add_argument('--page-src', default='', help='V4 页面源 app/index.html')
    args = ap.parse_args()
    build(args)


if __name__ == '__main__':
    main()
