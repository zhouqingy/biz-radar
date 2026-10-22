#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_detail.py —— 详情页扫描：附件清单 + 原始发布平台

为什么需要它：
  1. 用户要「能看到附件清单就行，让他自己选」。招标文件/清单/图纸都在附件里，
     这是最有价值的信息。列表接口的 attachname 字段几乎全空，必须扫详情页。
  2. 用户要「跳转到最原始的发布平台」。省级平台很多只是转发，真正的原始公告
     在市级/行业平台上（详情页里藏着「原文链接」）。

产出：写回 raw/<省>.json，每条追加
  files    [{n:文件名, u:下载地址}]          附件清单
  origin   {n:平台名, u:原始链接}            原始发布平台（能识别到时才有）
  srcType  official / reprint                信源分级
  shell    1                                 空壳页（正文抓不到）
  scanAt   扫描时间

用法：
  python3 scan_detail.py --prov 浙江 --limit 300      扫描浙江前300条
  python3 scan_detail.py --all --limit 200            四地各200条
  python3 scan_detail.py --all --days 30              只扫近30天的
"""
import os, re, json, time, argparse, subprocess, hashlib
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

PROV_FILE = {'江苏': 'jiangsu.json', '浙江': 'zhejiang.json',
             '安徽': 'anhui.json', '上海': 'shanghai.json'}

# 附件扩展名——只认这些，避免把普通页面链接当附件
DOC_EXT = re.compile(r'\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z|dwg|ofd|wps|et)(?:$|[?#])', re.I)

# 转载站/聚合站特征：这些不是原始发布平台，附件往往也拿不到
REPRINT_HOST = ('zhaobiao.cn', 'bidcenter.com.cn', 'chinabidding.cn', 'qianlima.com',
                'bidchance.com', 'jianyu360.com', 'bibenet.com', 'zhulong.com',
                'toubiao.com', '51bid', 'caizhi', 'zbytb.com', 'chinazbcg.com',
                'hczy', 'bidlink', 'ebnew.com', 'infobidding', 'chinabidding')

# 来源平台名：两站共用同一套模板
#   浙江：<label id="zhuanzaitext">浙江省统一招投标交易平台</label>
#   江苏：来源：南京云平台     ← 这行是「真正的原始发布平台」的关键线索
SRC_NAME = [
    r'id="zhuanzaitext"[^>]*>([^<]{2,40})<',
    r'来源[：:]\s*<label[^>]*>([^<]{2,40})<',
    r'来源[：:]\s*</?b>?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,30})',
    r'来源平台[：:]\s*</?b>?>?\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,30})',
]

# 原始平台识别：优先抽取 URL，退而求其次抽「来源平台名」
ORIGIN_PATTERNS = [
    # <span id="secondtitle">http://...</span>  江苏站的下级原文链接
    (r'id="secondtitle"[^>]*>\s*(https?://[^<\s]+)', '原文链接'),
    (r'class="[^"]*origin[^"]*"[^>]*>\s*(https?://[^<\s]+)', '来源'),
    (r'原文链接[：:]\s*<a[^>]*href="([^"]+)"', '原文链接'),
]

# 这些平台名没有信息量，识别到也不显示
SRC_NOISE = ('', 'None', 'null', '本站', '本站原创', '公共资源交易平台',
             '全国公共资源交易平台', '中国招标投标公共服务平台')


def curl(url, timeout=30):
    p = subprocess.run(['curl', '-s', '-m', str(timeout), '-L',
                        '-H', 'User-Agent: ' + UA,
                        '-H', 'Accept-Language: zh-CN,zh;q=0.9',
                        '-w', '\n__CODE__%{http_code}',
                        url], capture_output=True, text=True, errors='ignore')
    body = p.stdout or ''
    code = ''
    m = re.search(r'\n__CODE__(\d{3})\s*$', body)
    if m:
        code = m.group(1)
        body = body[:m.start()]
    return body, code


def decode(body):
    """很多交易平台是 GBK，curl 拿到的是字节串被当 latin-1 解的乱码，这里救回来"""
    if not body:
        return ''
    if body.count('\ufffd') > 5 or '\u00e5\u0085' in body[:2000]:
        for enc in ('gb18030', 'gbk'):
            try:
                return body.encode('latin-1', 'ignore').decode(enc, 'ignore')
            except Exception:
                pass
    return body


def uniq_keep(seq):
    out, seen = [], set()
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def scan_files(html, base):
    """提取附件清单。返回 [{n,u}]"""
    files = []

    # ① 附件区 #attach / #fujian / class 含 attach 的块
    for m in re.finditer(
            r'<(?:div|p|span)[^>]*(?:id="(?:attach|fujian)"|class="[^"]*attach[^"]*")[^>]*>(.*?)</(?:div|p|span)>',
            html, re.S | re.I):
        block = m.group(1)
        for a in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I):
            href = a.group(1).strip()
            name = re.sub(r'<[^>]+>', '', a.group(2)).strip()
            if not href or href.startswith('#') or 'javascript' in href.lower():
                continue
            files.append((name or '附件', href))
        # 附件区里也可能有裸文本文件名
        for t in re.finditer(r'([^\s<>"\']{3,80}\.(?:pdf|docx?|xlsx?|zip|rar|7z))', block, re.I):
            files.append((t.group(1), ''))

    # ② 全文扫带文档扩展名的链接（正文里内嵌的附件，阿里云 OSS 直链很常见）
    for a in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href = a.group(1).strip()
        if not DOC_EXT.search(href):
            continue
        name = re.sub(r'<[^>]+>', '', a.group(2)).strip()
        files.append((name or href.rsplit('/', 1)[-1], href))

    # ③ 裸文档链接（不带 a 标签）
    for t in re.finditer(r'(https?://[^\s<>"\']{10,200}\.(?:pdf|docx?|xlsx?|zip|rar|7z))(?:["\'<\s]|$)', html, re.I):
        files.append((t.group(1).rsplit('/', 1)[-1], t.group(1)))

    out, seen = [], set()
    seen_path = set()
    for name, href in files:
        name = re.sub(r'\s+', ' ', name).strip()[:120]
        if not name:
            continue
        # 裸文件名（href 空）如果已经有一条同名的真链接，就丢掉
        if not href:
            stem = name.rsplit('/', 1)[-1]
            if stem in seen_path:
                continue
        else:
            seen_path.add(name.rsplit('/', 1)[-1])
        u = urljoin(base, href) if href else ''
        key = (name, u)
        if key in seen:
            continue
        seen.add(key)
        # 没有链接的裸文件名价值低，放最后
        out.append({'n': name, 'u': u})
    # 有链接的排前面
    out.sort(key=lambda f: 0 if f['u'] else 1)
    return out[:20]


def scan_origin(html, base, own_host):
    """找原始发布平台。
    返回 {'n':平台名, 'u':原始链接(可能为空)}
    两站详情页都写了「来源：XX平台」，这是判断是否转载、原文在哪的第一手线索。
    """
    # ① 有明确 URL 的原文链接最可靠
    for pat, kind in ORIGIN_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if not m:
            continue
        u = next((g for g in m.groups() if g and g.startswith('http')), '')
        if not u:
            continue
        u = urljoin(base, u)
        host = re.sub(r'^https?://', '', u).split('/')[0].lower()
        if own_host and own_host in host:
            continue          # 指向自己，不算原始平台
        if any(h in host for h in REPRINT_HOST):
            continue          # 转载站不算原始平台
        return {'n': host, 'u': u}

    # ② 只有平台名：浙江「来源：浙江省统一招投标交易平台」、江苏「来源：南京云平台」
    for pat in SRC_NAME:
        m = re.search(pat, html, re.S | re.I)
        if not m:
            continue
        nm = re.sub(r'\s+', '', m.group(1)).strip('：: ')
        if nm in SRC_NOISE or len(nm) < 2:
            continue
        if '<' in nm or '>' in nm:
            continue
        return {'n': nm, 'u': ''}
    return None


def check_file(url, timeout=15):
    """验证附件直链是否真的能下到东西。
    踩过的坑：
      ① 浙江站的 PDF 大量返回 200 但 0 字节（文件名带中文括号），只看状态码会被骗；
      ② 用 `curl -I` 发 HEAD 时，如果服务器不返回 Content-Length、只给 chunked，
         会误判成不可用——必须再发 Range 请求实测前几个字节。
    """
    if not url:
        return False
    # ① Range 请求拿前 1KB，最可靠
    p = subprocess.run(['curl', '-s', '-o', '/tmp/_chk.bin', '-m', str(timeout),
                        '-r', '0-1023', '-w', '%{http_code}',
                        '-H', 'User-Agent: ' + UA, url],
                       capture_output=True, text=True, errors='ignore')
    code = (p.stdout or '').strip()
    try:
        got = os.path.getsize('/tmp/_chk.bin')
    except OSError:
        got = 0
    if code in ('200', '206') and got > 100:
        return True, _full_size(url, timeout) or got
    # ② Range 不被支持的老服务器：退化成 GET 取全量前 8KB 判断
    p2 = subprocess.run(['curl', '-s', '-o', '/tmp/_chk2.bin', '-m', str(timeout),
                         '--max-filesize', '8388608', '-w', '%{http_code}',
                         '-H', 'User-Agent: ' + UA, url],
                        capture_output=True, text=True, errors='ignore')
    code2 = (p2.stdout or '').strip()
    try:
        got2 = os.path.getsize('/tmp/_chk2.bin')
    except OSError:
        got2 = 0
    return (code2 == '200' and got2 > 1024), got2


def _full_size(url, timeout=12):
    """取文件总大小（字节）。取不到返回 0"""
    p = subprocess.run(['curl', '-s', '-I', '-L', '-m', str(timeout),
                        '-H', 'User-Agent: ' + UA, url],
                       capture_output=True, text=True, errors='ignore')
    m = re.search(r'(?i)content-length:\s*(\d+)', p.stdout or '')
    return int(m.group(1)) if m else 0


def scan_one(url):
    """扫一条，返回 dict"""
    body, code = curl(url)
    html = decode(body)
    r = {'shell': 0, 'files': [], 'origin': None, 'code': code}
    if code != '200' or len(html) < 400:
        r['shell'] = 1          # 空壳页/坏链
        return r
    own = re.sub(r'^https?://', '', url).split('/')[0].lower()
    files = scan_files(html, url)
    # 校验每个附件是否真能下（最多验 5 个，避免太慢），同时记下大小供前端显示
    for f in files[:5]:
        ok, sz = check_file(f.get('u'))
        f['ok'] = 1 if ok else 0
        f['sz'] = sz
    r['files'] = files
    r['origin'] = scan_origin(html, url, own)
    # 正文有实质内容吗（去掉标签后字数）
    txt = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = re.sub(r'\s+', '', txt)
    if len(txt) < 120:
        r['shell'] = 1
    # 2026-10-22：正文不再用完就扔。招标人 / 中标单位 / 金额 / 联系人
    # 全在这一页里，而这几项正是全库最缺的（中标单位覆盖只有 38.8%）。
    try:
        import detail_fields
        r['fields'] = detail_fields.parse(html)
    except Exception as e:
        r['fields'] = {}
        print('   [fields] 抽取失败:', e)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prov', default='')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--limit', type=int, default=200, help='每省最多扫多少条（优先新的、没扫过的）')
    ap.add_argument('--days', type=int, default=0, help='只扫最近 N 天的')
    ap.add_argument('--rescan', action='store_true', help='连已扫过的重扫')
    ap.add_argument('--sleep', type=float, default=0.3)
    # 2026-10-22：并发线程数。境外机房（GitHub Actions）延迟高，串行跑不完，
    # 用 8 路并发把 200 条压到 2-3 分钟内。本地跑也可以设 1 保持原行为。
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()

    provs = ['江苏', '浙江', '安徽', '上海'] if args.all else [args.prov]
    provs = [p for p in provs if p]
    if not provs:
        print('请指定 --prov 或 --all'); return

    today = time.strftime('%Y-%m-%d')
    cutoff = ''
    if args.days:
        cutoff = time.strftime('%Y-%m-%d', time.localtime(time.time() - args.days * 86400))

    grand = {'scanned': 0, 'files': 0, 'origin': 0, 'shell': 0}
    for prov in provs:
        fn = PROV_FILE.get(prov)
        if not fn:
            continue
        path = os.path.join(RAW, fn)
        if not os.path.exists(path):
            continue
        arr = json.load(open(path, encoding='utf-8'))

        # 排序：优先未扫过的 + 日期新的
        def prio(x):
            done = 1 if (x.get('scanAt') and not args.rescan) else 0
            return (done, '' if not x.get('d') else _neg(x.get('d')))
        def _neg(d):
            # 日期越新越靠前：把 '2026-10-20' 映射成可比较的负数串
            return ''.join(chr(0x39 - (ord(c) - 0x30)) if c.isdigit() else c for c in d)
        arr_sorted = sorted(arr, key=prio)

        todo = []
        for x in arr_sorted:
            if not x.get('url'):
                continue
            if cutoff and (x.get('d') or '') < cutoff:
                continue
            todo.append(x)
            if len(todo) >= args.limit:
                break

        print('[%s] 待扫 %d 条（共 %d 条）' % (prov, len(todo), len(arr)))
        t0 = time.time()
        st = {'files': 0, 'origin': 0, 'shell': 0, 'buyer': 0, 'win': 0, 'amt': 0, 'phone': 0}

        # ── 2026-10-22 改成并发 ────────────────────────────────────────
        # 起因：GitHub Actions 上跑这一跑，200 条扫了 9 分钟还没完，直接撞 40 分钟
        # 总超时被砍。原因是 Actions 机房在境外，访问国内政务站单次请求要 2-4 秒，
        # 原来串行 + sleep，200 条光等待就 10 分钟以上。
        # 现在用线程池并发（默认 8 路），总耗时降到 1/5 左右。
        # 注意：--sleep 仍然保留，但变成"每个线程请求之间歇一下"，避免把对方打挂。
        import threading
        from concurrent.futures import ThreadPoolExecutor
        lock = threading.Lock()
        cnt = {'done': 0}

        def work(x):
            try:
                r = scan_one(x['url'])
            except Exception:
                return None
            time.sleep(args.sleep)
            return (x, r)

        def apply(item):
            x, r = item
            x['scanAt'] = today
            x['shell'] = r['shell']
            if r['files']:
                x['files'] = r['files']
                st['files'] += 1
            else:
                x.setdefault('files', [])
            if r['origin']:
                x['origin'] = r['origin']
                st['origin'] += 1
            if r['shell']:
                st['shell'] += 1
            # 2026-10-22 新增：把详情页正文里的业主/中标单位/金额/联系人补回记录。
            # 原则是**只补不改**：字段已经有值就不覆盖（列表接口给的通常更准，
            # 那是结构化字段；详情页是文本抽取，用作补齐）。
            f = r.get('fields') or {}
            for k, cur in (('buyer', 'buyer'), ('win', 'win'), ('agc', 'agc'),
                           ('contact', 'contact'), ('phone', 'phone'),
                           ('openDate', 'openDate'), ('winJoint', 'winJoint')):
                if f.get(k) and not x.get(cur):
                    x[cur] = f[k]
                    if k in st:
                        st[k] += 1
            if f.get('amt') and not x.get('amt'):
                x['amt'] = f['amt']
                x['amtY'] = round(f['amt'] / 1e8, 4)
                if f.get('amtSrc'):
                    x['amtSrc'] = f['amtSrc']
                st['amt'] += 1
            # 信源分级
            host = re.sub(r'^https?://', '', x['url']).split('/')[0].lower()
            x['srcType'] = 'reprint' if any(h in host for h in REPRINT_HOST) else 'official'

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for item in ex.map(work, todo):
                if item is None:
                    continue
                with lock:
                    apply(item)
                    cnt['done'] += 1
                    i = cnt['done']
                    if i % 25 == 0:
                        print('   %d/%d  附件%d 原始平台%d 空壳%d  (%.0fs)'
                              % (i, len(todo), st['files'], st['origin'], st['shell'],
                                 time.time() - t0))

        json.dump(arr, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
        print('[%s] 完成 附件%d 条 / 原始平台%d 条 / 空壳%d 条  %.0fs'
              % (prov, st['files'], st['origin'], st['shell'], time.time() - t0))
        grand['scanned'] += len(todo)
        for k in ('files', 'origin', 'shell'):
            grand[k] += st[k]

    # 心跳
    hb = os.path.join(RAW, '心跳_详情扫描.json')
    json.dump({'at': time.strftime('%Y-%m-%d %H:%M'),
               'scanned': grand['scanned'],
               'withFiles': grand['files'],
               'withOrigin': grand['origin'],
               'shell': grand['shell']},
              open(hb, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[scan_detail] 合计扫描 %d 条 · 有附件 %d · 识别原始平台 %d · 空壳 %d'
          % (grand['scanned'], grand['files'], grand['origin'], grand['shell']))


if __name__ == '__main__':
    main()
