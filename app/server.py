# -*- coding: utf-8 -*-
"""商机雷达 V4 · 契约薄服务（分期第一步，Python 标准库，零第三方依赖）

定位：
  - 按 app/API_CONTRACT.md 的 12 条契约暴露 JSON 接口；
  - 数据源是**现有已筛好的静态数据包**（biz-radar/data*.js），本服务只读、不写、不改；
  - 后端采集调度 / 数据库 / 鉴权属分期后续，本轮用 /api/collect/* 的 planned 状态如实占位，
    绝不假装已经能抓取；
  - 「能不能投」不由本服务判：数据已过 biz_rules.semantic_drop()/judge() 入库，这里只做视图筛选。
    /api/rules 通过 import biz_rules 只读展示规则，证明规则源在服务端可直接复用。

启动：python3.11 app/server.py --port 8848
访问：http://127.0.0.1:8848/  （首页由本服务静态托管）
"""
import argparse
import json
import os
import re
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, 'biz-radar')
APP = os.path.join(ROOT, 'app')
HERE = os.path.dirname(os.path.abspath(__file__))

_CACHE = {}
_LOCK = threading.Lock()


def _js_literal(s):
    """零依赖解析 JS 对象字面量（裸键 / 单引号 / 尾逗号 / 注释）。

    data.policy.js 是 `var DATA_POLICY = { gen: '...', ... }` 这类 JS 字面量，
    不是严格 JSON（旧页面靠 <script> 加载）。这里只做词法扫描，不 eval、不执行任何代码。
    """
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


def _load_js(fname):
    """把 window.DATA_XXX={...} / var DATA_XXX={...} 解成 dict，只读。"""
    with _LOCK:
        if fname in _CACHE:
            return _CACHE[fname]
        p = os.path.join(SITE, fname)
        if not os.path.exists(p):
            _CACHE[fname] = {}
            return {}
        s = open(p, encoding='utf-8').read()
        s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)          # 剥块注释
        s = re.sub(r'^\s*//.*$', '', s, flags=re.M)           # 剥行注释
        i, j = s.find('{'), s.rfind('}')
        if i < 0 or j <= i:
            _CACHE[fname] = {}
            return {}
        raw = s[i:j + 1]
        try:
            d = json.loads(raw)
        except Exception:
            # 非严格 JSON 的 JS 字面量（政策档）：走只读词法解析，不 eval
            d = _js_literal(raw)
        if not isinstance(d, dict):
            d = {}
        _CACHE[fname] = d
        return d


def _as_list(v):
    """新闻 / 组织分组既可能是 list，也可能是 {updated,days,items} 包装。"""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        it = v.get('items')
        return it if isinstance(it, list) else [v]
    return []


def _core():
    return _load_js('data.core.js')


def _data():
    """整包 data.js：含 items 1119 条 + org + news。"""
    return _load_js('data.js')


def _items():
    return _data().get('items', [])


def _health():
    p = os.path.join(ROOT, '数据质量体检.json')
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return {}


# ---------- 视图筛选（只筛已入库数据，不做业务判定） ----------
_ITEM_KEYS = ['id', 't', 'rg', 'city', 'st', 'g', 'sg', 'sG', 'sub', 'buyer', 'win',
              'amt', 'amtTxt', 'd', 'dl', 'mode', 'sc', 'bk', 'iv', 'dp', 'w', 'hm',
              'linkbad', 'url', 'hist', 'snip']


def _slim(x):
    return {k: x.get(k) for k in _ITEM_KEYS if k in x}


def _match(it, q, region, segment, stage, focus):
    if focus and str(it.get('w')) not in ('1', '1.0'):
        return False
    if region and it.get('rg') != region:
        return False
    if stage and it.get('st') != stage:
        return False
    if segment and segment not in (str(it.get('sub') or ''), str(it.get('sg') or '')):
        return False
    if q:
        hay = ' '.join(str(it.get(k) or '') for k in ('t', 'buyer', 'win', 'city', 'snip', 'sub'))
        if q.lower() not in hay.lower():
            return False
    return True


def _facets(rows):
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


def opportunities(params):
    rows = _items()
    q = params.get('q', '').strip()
    region = params.get('region', '').strip()
    stage = params.get('stage', '').strip()
    segment = params.get('segment', '').strip()
    focus = params.get('focus', '') in ('1', 'true')
    sort = params.get('sort', 'sc')
    try:
        page = max(1, int(params.get('page', 1)))
        size = min(200, max(1, int(params.get('size', 20))))
    except ValueError:
        page, size = 1, 20
    hit = [x for x in rows if _match(x, q, region, segment, stage, focus)]
    if sort == 'amt':
        hit.sort(key=lambda x: float(x.get('amt') or 0), reverse=True)
    elif sort == 'd':
        hit.sort(key=lambda x: str(x.get('d') or ''), reverse=True)
    else:
        hit.sort(key=lambda x: float(x.get('sc') or 0), reverse=True)
    total = len(hit)
    chunk = hit[(page - 1) * size: page * size]
    meta = _core().get('meta', {}) or _data().get('meta', {})
    return {
        'total': total, 'page': page, 'size': size,
        'items': [_slim(x) for x in chunk],
        'facets': _facets(rows),
        'meta': {'source': 'biz-radar/data.js（已筛好的①库，只读）',
                 'updated': meta.get('updated', ''), 'total': meta.get('total', len(rows)),
                 'note': '视图筛选；能不能投由 biz_rules.judge() 在入库时判定，本接口不重判'},
    }


def opportunity_one(iid):
    for x in _items():
        if x.get('id') == iid:
            return {'item': x, 'meta': {'source': 'biz-radar/data.js'}}
    return {'error': 'not found', 'id': iid}


def orgs(params):
    d = _data()
    typ = params.get('type', '')
    q = params.get('q', '').strip().lower()
    # 只读视图分页：模块内检索先在全量里过滤再切片，避免「翻不到后面的单位」。
    # 缺省 size=20 与旧行为一致，不破坏契约；不写任何数据、不做业务判定。
    try:
        page = max(1, int(params.get('page', 1)))
        size = min(100, max(1, int(params.get('size', 20))))
    except ValueError:
        page, size = 1, 20
    groups = {'rivals': 'rivals', 'buyers': 'buyers', 'latent': 'latent',
              'domestic': 'domestic', 'clients': 'clients', 'partners': 'partners',
              'competitors': 'competitors'}
    out = {}
    for k, src in groups.items():
        if typ and typ != k and not (typ == 'owner' and k in ('buyers', 'clients', 'domestic')):
            continue
        arr = d.get(src, []) or []
        if q:
            arr = [x for x in arr if q in json.dumps(x, ensure_ascii=False).lower()]
        out[k] = {'count': len(arr), 'page': page, 'size': size,
                  'items': arr[(page - 1) * size: page * size]}
    return {'groups': out, 'meta': {'source': 'biz-radar/data.js + data.org.js（②库，按单位聚合）',
                                    'note': '②反推①须再过①过滤；此处只读展示，不反推',
                                    'view': 'q 文本视图筛选 + page/size 只读分页'}}


def policies(params):
    d = _load_js('data.policy.js')
    q = params.get('q', '').strip().lower()
    plist = d.get('policies', []) or []
    rlist = d.get('related', []) or []
    # 政策档的 clauses 内嵌在每个政策项里（顶层只有 gen/meta/policies/related/...），
    # 这里汇总成契约要求的顶层 clauses，并挂上来源文号，不改动源数据。
    clauses = []
    for p in list(plist) + list(rlist):
        if not isinstance(p, dict):
            continue
        src = p.get('no') or p.get('short') or p.get('title') or ''
        for c in (p.get('clauses') or []):
            cc = dict(c) if isinstance(c, dict) else {'text': str(c)}
            cc.setdefault('policy', src)
            clauses.append(cc)
    if q:
        clauses = [c for c in clauses if q in json.dumps(c, ensure_ascii=False).lower()]
    return {'policies': plist, 'related': rlist,
            'clauses': clauses[:60], 'timeline': d.get('timeline', []),
            'total': len(clauses),
            'meta': {'source': 'biz-radar/data.policy.js（JS 字面量，只读解析）',
                     'meta': d.get('meta', {}), 'gen': d.get('gen', ''),
                     'note': 'clauses 均为官方原文逐条，不是二手解读'}}


def metals(params):
    c = _core().get('metals', {}) or _data().get('metals', {})
    arr = c.get('items', []) or []
    code = params.get('code', '').strip().upper()
    q = params.get('q', '').strip().lower()
    if code:
        arr = [x for x in arr if str(x.get('code', '')).upper() == code]
    if q:
        # 品种 / 代码 / 解读的文本视图筛选，与其他模块 q 语义一致
        arr = [x for x in arr if q in json.dumps(x, ensure_ascii=False).lower()]
    # data.metalhist.js 的历史在顶层 s（不是 series）：{CU:{n,u,sym,start,end,cnt,df,d[],p[]}}
    # 早期误读 series → hist 恒为空，页面因此画不出曲线。这里只读真实字段，
    # 并裁末 120 点作为视图采样（原始全量仍在 data.metalhist.js，不改动、不补造）。
    hist_raw = _load_js('data.metalhist.js')
    raw = (hist_raw.get('s') or hist_raw.get('series') or {}) if isinstance(hist_raw, dict) else {}
    hist = {}
    for code, one in raw.items():
        if not isinstance(one, dict):
            continue
        hist[code] = dict(one, d=(one.get('d') or [])[-120:], p=(one.get('p') or [])[-120:])
    return {'items': arr, 'updated': c.get('updated', ''),
            'hist': hist,
            'meta': {'source': 'data.core.js + data.metalhist.js',
                     'note': 'hist 取顶层 s 字段末 120 点作视图采样；原始全量在 data.metalhist.js，未改动'}}


def news(params):
    d = _data()
    kind = params.get('kind', '')
    q = params.get('q', '').strip().lower()
    try:
        page = max(1, int(params.get('page', 1)))
        size = min(100, max(1, int(params.get('size', 20))))
    except ValueError:
        page, size = 1, 20
    keys = ['trends', 'wechat', 'digest', 'overseas', 'overseaFlash', 'overseaOdi']
    # kind 支持逗号分隔多组（如海外机会要同时看 overseas / overseaFlash / overseaOdi）
    kinds = [x.strip() for x in kind.split(',') if x.strip()]
    out = {}
    for k in keys:
        if kinds and 'all' not in kinds and k not in kinds:
            continue
        arr = _as_list(d.get(k))
        if q:
            arr = [x for x in arr if q in json.dumps(x, ensure_ascii=False).lower()]
        out[k] = {'count': len(arr), 'page': page, 'size': size,
                  'items': arr[(page - 1) * size: page * size]}
    return {'groups': out, 'meta': {'source': 'biz-radar/data.js / data.news.js',
                                    'note': 'wechat / digest 为 {updated,items} 包装，服务端已展平',
                                    'view': 'q 文本视图筛选 + page/size 只读分页'}}


def changes(params):
    d = _load_js('data.changes.js')
    return {'changes': d, 'meta': {'source': 'biz-radar/data.changes.js'}}


def search(params):
    """全库统一检索：跨①库 / ②库 / 政策档 / 新闻分组返回。"""
    q = params.get('q', '').strip()
    if not q:
        return {'q': q, 'groups': {}, 'total': 0}
    lim = 6
    g = {}
    o = opportunities({'q': q, 'size': lim})
    g['opportunities'] = {'count': o['total'], 'items': o['items']}
    g['orgs'] = {'count': 0, 'items': []}
    d = _data()
    for k in ('rivals', 'buyers', 'clients', 'partners'):
        for x in d.get(k, []) or []:
            if q.lower() in json.dumps(x, ensure_ascii=False).lower():
                g['orgs']['items'].append({'group': k, 'name': x.get('n') or x.get('name') or ''})
                g['orgs']['count'] += 1
                if len(g['orgs']['items']) >= lim:
                    break
        if len(g['orgs']['items']) >= lim:
            break
    p = policies({'q': q})
    g['policies'] = {'count': p['total'], 'items': p['clauses'][:lim]}
    n = news({'q': q, 'kind': 'all'})
    ni, nc = [], 0
    for k, v in n['groups'].items():
        nc += v['count']
        ni.extend([{'group': k, 'title': (x.get('t') or x.get('title') or '')[:80]}
                   for x in v['items'][:2]])
    g['news'] = {'count': nc, 'items': ni[:lim]}
    return {'q': q, 'groups': g, 'total': sum(v['count'] for v in g.values()),
            'meta': {'note': '跨库统一检索；命中不做业务判定，只是文本匹配'}}


def rules(_params):
    """只读展示规则源；证明 biz_rules.py 可被服务端直接 import。"""
    out = {'imported': False, 'source': 'biz-radar-tools/biz_rules.py'}
    try:
        sys.path.insert(0, os.path.join(ROOT, 'biz-radar-tools'))
        import biz_rules as br
        out['imported'] = True
        out['amt_focus_min_yi'] = getattr(br, 'AMT_FOCUS_MIN_YI', None)
        # SEM_ACTIVE_CODES 是 set，json 不能直接序列化，转成有序 list
        out['sem_active_codes'] = sorted(str(x) for x in
                                        (getattr(br, 'SEM_ACTIVE_CODES', []) or []))
        out['sem_pending'] = list(getattr(br, 'SEM_PENDING', []) or [])
        out['rule_count'] = len(getattr(br, 'SEM_RULES', []) or [])
        out['wordlist_codes'] = [r[0] for r in (getattr(br, 'SEM_RULES', []) or [])]
        out['active_code_count'] = len(getattr(br, 'SEM_ACTIVE_CODES', []) or [])
        # 底稿口径：12 条删除规则 = 11 类词表 + N13 存量主设备改造（护栏形态，不在词表里）
        out['guard_only_codes'] = sorted(
            set(str(x) for x in (getattr(br, 'SEM_ACTIVE_CODES', []) or [])) -
            set(out['wordlist_codes']))
        try:
            out['stat_title'] = br.stat_title()
        except Exception as e:
            out['stat_title_err'] = str(e)
        out['functions'] = [n for n in ('judge', 'semantic_drop', 'focus_of', 'stat_title')
                            if hasattr(br, n)]
    except Exception as e:
        out['error'] = str(e)
    out['note'] = ('判定只在服务端入库时执行：semantic_drop() 硬过滤 → judge() 判能否投 → '
                   'focus_of() 定关注档；前端只做视图筛选')
    return out


def collect_run(_params):
    """如实占位：采集调度属后端分期，本轮未实现，不假装有抓取。"""
    return {'status': 'planned', 'implemented': False,
            'message': '定时采集 / 调度 / 重试属后端分期（见 V4 方案 §5），本轮未接入，不产生任何数据变更。',
            'next': ['collect_v4.py 包装成任务', '入库前 semantic_drop() 硬过滤',
                     'judge() 判能否投', '增量入库 + hist 状态历史']}


def collect_status(_params):
    return {'status': 'planned', 'implemented': False, 'jobs': [],
            'message': '抓取调度尚未接入；当前数据为已筛好的静态快照（只读）。'}


ROUTES = {
    '/api/opportunities': opportunities,
    '/api/orgs': orgs,
    '/api/policies': policies,
    '/api/metals': metals,
    '/api/news': news,
    '/api/changes': changes,
    '/api/search': search,
    '/api/rules': rules,
    '/api/health': lambda p: _health(),
    '/api/collect/status': collect_status,
}
POST_ROUTES = {'/api/collect/run': collect_run}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        def _default(o):
            if isinstance(o, (set, frozenset)):
                return sorted(o, key=str)
            if isinstance(o, (bytes, bytearray)):
                return o.decode('utf-8', 'replace')
            return str(o)
        body = json.dumps(obj, ensure_ascii=False, default=_default).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _params(self):
        u = urllib.parse.urlparse(self.path)
        return {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}, u.path

    def do_GET(self):
        params, path = self._params()
        if path.startswith('/api/opportunities/'):
            return self._send(opportunity_one(path.rsplit('/', 1)[-1]))
        if path in ROUTES:
            try:
                return self._send(ROUTES[path](params))
            except Exception as e:
                return self._send({'error': str(e)}, 500)
        if path in ('/', '/index.html'):
            p = os.path.join(APP, 'index.html')
            if os.path.exists(p):
                b = open(p, 'rb').read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
        self._send({'error': 'not found', 'path': path}, 404)

    def do_POST(self):
        params, path = self._params()
        if path in POST_ROUTES:
            return self._send(POST_ROUTES[path](params))
        self._send({'error': 'not found'}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8848)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    # 启动即预热，顺便打印真实数字（数字来自文件，不手填）
    print('[V4] 数据源：%s' % SITE)
    print('[V4] ①库条目：%d ｜ meta.total：%s' % (
        len(_items()), (_core().get('meta', {}) or {}).get('total')))
    print('[V4] 规则源 import：%s' % rules({}).get('imported'))
    print('[V4] http://%s:%d/' % (a.host, a.port))
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
