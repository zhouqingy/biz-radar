#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地方热电联产 / 集中供热规划批复采集器  →  raw/early/plan-<date>.json

为什么做这个：
  省、市发改委对县市《热电联产规划 / 集中供热规划》的批复正文里，会**直接点名**
  未来要新建的热源点项目（例："原则同意…新建丰县经济开发区热电联产项目(暂命名)
  作为区域主力热源点"）。这比项目核准还早 1~3 年，是市政园区热电联产赛道最早的
  战略级信号 —— 规划一定，区域热源点布局就定了，可以提前跑关系、跟进度。

信源（2026-10 实测）：
  江苏  省发改委"其他文件"栏 dataproxy 接口   —— 仍在持续发布，主战场
  浙江  省发改委"审批文件"栏 jpaas GET 接口   —— 2018~2020 一轮已过，下轮修编待观察
  安徽  省发改委通知公告 + 宣城立项信息        —— 省级无，市级是主战场
  上海  近三年无此类规划批复（热源点已定型），已放弃

用法：
  python3 mine_plan.py            # 正常采集
  python3 mine_plan.py --dry      # 只打印不落盘
  python3 mine_plan.py --pages 6  # 每个源翻多少页（默认 8）
"""
import os, re, sys, json, time, urllib.parse
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
EARLY_DIR = os.path.join(RAW, 'early')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# ── 标题过滤：只认规划类批复 ────────────────────────────────────────────────
PLAN_KW = ['热电联产规划', '集中供热规划', '供热专项规划', '热电联产专项规划',
           '热源点规划', '热电联产布点', '集中供热专项规划', '热电联产（集中供热）规划',
           # 2026-10-19 补：燃气（天然气）分布式能源类规划，园区/数据中心供电常走这条路线
           '燃气分布式能源', '天然气分布式', '分布式能源规划', '冷热电三联供',
           '能源站规划', '区域能源规划']
# 明确排除：只有规划解读/征求意见稿而没有批复的，价值低
WEAK_KW = ['解读', '征求意见', '公示', '废止']

# ── 正文里抽取"未来要建的项目" ───────────────────────────────────────────────
# 匹配：新建/规划新建/规划建设 + 项目名 + 项目
PROJ_RE = re.compile(
    r'(?:规划新建|规划建设|规划期内[^。；]{0,40}?新建|新建|扩建|规划期[^。；]{0,20}?建设)'
    r'([\u4e00-\u9fa5A-Za-z0-9（）()·\-\u3000]{2,32}?'
    r'(?:热电联产|集中供热|供热|热电厂|热源点|生物质)[^。；、，,]{0,8}?项目)')
TAIL_CLEAN = re.compile(r'[（(]暂命名[)）]|[（(]暂定名[)）]|[（(]最终名称[)）]')
# 抽取结果里明显的碎片前缀（"新建和改造…"会截出"和改造…"）
BAD_HEAD = ('和', '与', '及', '、', '或', '的', '了', '在', '对', '将', '以',
            '共', '另', '再', '并', '如', '为', '由')


def date_from_url(u):
    """政务站 URL 自带发布日期：/art/2026/1/18/art_51012_xxx.html"""
    m = re.search(r'/art/(\d{4})/(\d{1,2})/(\d{1,2})/', u or '')
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    return ''


def clean_plan_name(title):
    """抽不到项目名时的兜底：把批复标题洗成一个可读的规划名。"""
    t = re.sub(r'^关于同意|^关于|^省发展改革委关于|省发展改革委', '', title)
    t = re.sub(r'的批复$|^同意|的通知$', '', t)
    t = t.replace('《', '').replace('》', '')
    t = re.sub(r'\s+', '', t)
    return t.strip('（）() —-')[:40]

RG_HINT = ['徐州', '连云港', '宿迁', '淮安', '盐城', '扬州', '泰州', '南通', '镇江',
           '常州', '无锡', '苏州', '南京',
           '杭州', '宁波', '温州', '绍兴', '湖州', '嘉兴', '金华', '衢州', '台州',
           '丽水', '舟山',
           '合肥', '芜湖', '马鞍山', '安庆', '滁州', '阜阳', '宿州', '六安', '蚌埠',
           '淮南', '铜陵', '宣城', '池州', '黄山', '淮北', '亳州']


def get(url, ref=None, timeout=25):
    """统一 GET，返回文本；失败返回空串。"""
    headers = {'User-Agent': UA, 'Accept': '*/*'}
    if ref:
        headers['Referer'] = ref
    try:
        if requests:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or 'utf-8'
                return r.text
            return ''
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as f:
            raw = f.read()
        for enc in ('utf-8', 'gbk', 'gb18030'):
            try:
                return raw.decode(enc)
            except Exception:
                continue
        return raw.decode('utf-8', 'ignore')
    except Exception:
        return ''


def txt_of(html):
    """HTML → 纯文本（够用的粗清洗）。"""
    t = re.sub(r'(?is)<script.*?</script>|<style.*?</style>|<!--.*?-->', ' ', html)
    t = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = (t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&ldquo;', '“')
          .replace('&rdquo;', '”').replace('&mdash;', '—').replace('\u3000', ' '))
    t = re.sub(r'\n\s*\n+', '\n', t)
    return re.sub(r'[ \t]{2,}', ' ', t)


def one_line(s, limit=180):
    """把可能含大量空行的文本压成一行可读摘要。"""
    s = re.sub(r'\s+', ' ', s or '').strip()
    try:
        import html as _h
        s = _h.unescape(s)
    except Exception:
        pass
    return s[:limit]


# 政务网页的框架栏特征词——这些行不是正文
FRAME_KW = ('首页', '索引号', '分 类', '分类:', '发布机构', '发文日期', '成文日期',
            '浏览次数', '字号', '打印', '关闭窗口', '上一篇', '下一篇', '责任编辑',
            '扫一扫', '分享到', '版权所有', '网站标识码', '联系我们', '网站地图',
            '主办单位', '公网安备', '您是第', '无障碍', '返回顶部', '来源：',
            '江苏省发展和改革委员会 其他文件')


def is_frame(s):
    return any(k in s for k in FRAME_KW) or len(s) < 40


# ══════════════════════════════════════════════════════════════════════════
# 信源 1：江苏省发改委（dataproxy）
# ══════════════════════════════════════════════════════════════════════════
JS_BASE = 'https://fzggw.jiangsu.gov.cn'
JS_COL = '51012'          # “其他文件”栏（省发改委批复类文件都落这里）
JS_UNIT = '394686'


def js_list(page):
    """江苏列表，startrecord 步长 45。返回 [(title, href, date)]"""
    wn = urllib.parse.quote('江苏省发展和改革委员会')
    sr = (page - 1) * 45 + 1
    er = sr + 44
    u = (f'{JS_BASE}/module/web/jpage/dataproxy.jsp?startrecord={sr}&endrecord={er}'
         f'&perpage=45&col=1&appid=1&webid=3&path=%2F&columnid={JS_COL}'
         f'&sourceContentType=1&unitid={JS_UNIT}&webname={wn}&permissiontype=0')
    h = get(u, ref=f'{JS_BASE}/col/col{JS_COL}/index.html')
    out = []
    for t, href, span in re.findall(
            r'title="([^"]{6,120})"\s+href="(/art/[^"]+\.html)"(?:.{0,300}?<span>([\d\-]{8,10})</span>)?', h, re.S):
        out.append((t.strip(), JS_BASE + href, (span or '').strip()))
    if not out:   # 兜底：不带日期的写法
        for t, href in re.findall(r'title="([^"]{6,120})"\s+href="(/art/[^"]+\.html)"', h):
            out.append((t.strip(), JS_BASE + href, ''))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 信源 2：浙江省发改委（jpaas GET）
# ══════════════════════════════════════════════════════════════════════════
ZJ_BASE = 'https://fzggw.zj.gov.cn'
ZJ_API = ZJ_BASE + '/api-gateway/jpaas-publish-server/front/page/build/unit'
ZJ_PAGEID = '1599553'     # “审批文件”栏


def zj_list(page):
    q = {'parseType': 'bulidstatic', 'webId': '3185',
         'tplSetId': 'o0YcVHHq5vWtr3uiCp4SY', 'pageType': 'column',
         'tagId': '信息列表', 'editType': 'null', 'pageId': ZJ_PAGEID,
         'paramJson': json.dumps({'pageNo': page, 'pageSize': 15}, ensure_ascii=False)}
    u = ZJ_API + '?' + urllib.parse.urlencode(q)
    h = get(u, ref=f'{ZJ_BASE}/col/col{ZJ_PAGEID}/index.html')
    try:
        j = json.loads(h)
        frag = (j.get('data') or {}).get('html') or ''
    except Exception:
        frag = h
    out = []
    for t, href in re.findall(r'title="([^"]{6,120})"\s+href="(/art/[^"]+\.html)"', frag):
        out.append((t.strip(), ZJ_BASE + href, ''))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 信源 3：安徽（省级通知公告 + 宣城立项信息）
# ══════════════════════════════════════════════════════════════════════════
AH_SOURCES = [
    ('安徽省发改委', 'https://fzggw.ah.gov.cn/ywdt/tzgg/index.html', None),
    ('宣城市发改委', 'https://fgw.xuancheng.gov.cn/News/showList/1553/page_{p}.html', None),
]


def ah_list(entry, page):
    name, pat, _ = entry
    u = pat.format(p=page) if '{p}' in pat else pat
    h = get(u, ref=u)
    out = []
    base = re.match(r'https?://[^/]+', u)
    base = base.group(0) if base else ''
    for t, href in re.findall(r'title="([^"]{6,120})"\s+href="([^"]+\.html)"', h):
        if href.startswith('http'):
            full = href
        elif href.startswith('/'):
            full = base + href
        else:
            full = u.rsplit('/', 1)[0] + '/' + href
        out.append((t.strip(), full, ''))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 正文 → 项目条目
# ══════════════════════════════════════════════════════════════════════════
PLACE_RE = re.compile(r'([\u4e00-\u9fa5]{2,4}(?:市|县))')


def guess_rg(title, body):
    """地名优先从标题取（XX市/XX县），其次命中已知地级市，最后正文。"""
    m = PLACE_RE.search(title)
    if m:
        return m.group(1)
    for src in (title, body[:1500]):
        for g in RG_HINT:
            if g in src:
                return g if g.endswith(('州', '市')) else g + '市'
    m = PLACE_RE.search(body[:800])
    return m.group(1) if m else ''


def pick_projects(title, body):
    """从批复正文里抽出被点名的未来项目名。抽不到就返回 [规划名]。"""
    found, seen = [], set()
    for m in PROJ_RE.finditer(body):
        nm = TAIL_CLEAN.sub('', m.group(1)).strip('（）() ·-')
        if len(nm) < 5 or nm in seen:
            continue
        # 碎片：数字/量词开头、连接词开头、含整句标点或动词残留
        if nm[0].isdigit() or nm[0] in BAD_HEAD or nm[:2] in ('个', '一台', '座'):
            continue
        if any(bad in nm for bad in ['。', '；', '整合', '关停', '的基础上', '批复', '通知']):
            continue
        seen.add(nm)
        found.append(nm)
    if not found:
        found = [clean_plan_name(title)]
    return found[:4]


def mk_item(title, url, date, body, src):
    """一条规划批复 → 若干条项目线索。"""
    projs = pick_projects(title, body)
    rg = guess_rg(title, body)
    out = []
    for p in projs:
        nm = p if '热电' in p or '供热' in p or '热源' in p else p
        # 摘要：优先取正文里第一次出现该项目名的那一段，否则取正文首个有效段
        idx = body.find(nm[:8]) if len(nm) >= 8 else -1
        note = ''
        if idx >= 0:
            cand = one_line(body[max(0, idx - 120):idx + 160], 200)
            note = '' if is_frame(cand) else cand
        if not note:
            # 逐行找第一段有实质内容、且不是网页框架栏的
            for ln in body.split('\n'):
                s = one_line(ln, 200)
                if not is_frame(s) and '发展改革委 其他文件' not in s:
                    note = s
                    break
        # 去掉"如下："这类过渡碎词
        note = re.sub(r'^(?:下|如下|批复如下|现就有关事项批复如下|有关事项批复如下)[：:]?\s*', '', note)
        if len(note) < 20:
            note = f'省发改委对该市/县热电联产规划的批复，规划期内布局新建热源点'
        # 字段名必须对齐 raw/early/ 既有约定（build_data.py 按 t/rg/city/d/p/snip 读取）
        out.append({
            't': nm,
            'rg': src,                       # 省级，用于四地边界过滤（江苏/浙江/安徽）
            'city': rg,                      # 市/县
            'st': '',                        # 由 EARLY_SRC['热电规划'] 覆盖为「立项公示」
            'buyer': '',
            'win': '',
            'amt': None,
            'amtTxt': '',
            'd': date,
            'dl': '',
            'p': f'{src}省发展和改革委员会（{clean_plan_name(title)}）',
            'url': url,
            'snip': f'[{src}·{rg or src} 规划点名] {note[:200]}',
            'mode': '',
            'early': '热电规划',
            'expect': '',
        })
    return out


def run_source(name, lister, pages, arg=None, since=''):
    """翻页 → 标题过滤 → 抓正文 → 出条目。since: 只保留 >= 该日期的批复。"""
    hits = []
    seen_url = set()
    for p in range(1, pages + 1):
        try:
            rows = lister(arg or p, p) if name == '安徽' else lister(p)
        except Exception:
            rows = []
        if not rows:
            break
        for t, href, d in rows:
            if href in seen_url:
                continue
            if not any(k in t for k in PLAN_KW):
                continue
            if any(w in t for w in WEAK_KW) and '批复' not in t:
                continue
            # 政务站 URL 自带发布日期，比列表页的 span 可靠
            d = date_from_url(href) or d
            if since and d and d < since:
                continue          # 规划太老，其中的项目多半已招标/建成
            seen_url.add(href)
            print(f'    · [{name}] {d} {t[:56]}')
            body = txt_of(get(href, ref=href))
            if len(body) < 200:
                continue
            hits.extend(mk_item(t, href, d, body, name))
            time.sleep(0.4)
    return hits


def main():
    dry = '--dry' in sys.argv
    pages = 8
    days = 730          # 只看近两年批复：再早的规划期多半已走完流程
    for i, a in enumerate(sys.argv):
        if a == '--pages' and i + 1 < len(sys.argv):
            try:
                pages = int(sys.argv[i + 1])
            except Exception:
                pass
        if a == '--days' and i + 1 < len(sys.argv):
            try:
                days = int(sys.argv[i + 1])
            except Exception:
                pass
    since = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    print(f'[mine_plan] 扫描地方热电联产 / 集中供热规划批复（不早于 {since}）...')

    allhits = []
    for name, lister, arg in [
        ('江苏', js_list, None),
        ('浙江', zj_list, None),
    ]:
        print(f'  → {name}省发改委')
        try:
            allhits.extend(run_source(name, lister, pages, arg, since))
        except Exception as e:
            print(f'    ! {name} 失败：{e}')
    for entry in AH_SOURCES:
        print(f'  → {entry[0]}')
        try:
            got = run_source('安徽', lambda p, e=entry: ah_list(e, p), 4, since)
            allhits.extend(got)
        except Exception as e:
            print(f'    ! {entry[0]} 失败：{e}')

    # 标题去重
    seen, items = set(), []
    for it in allhits:
        k = re.sub(r'[\s\u3000]', '', it['t'])[:40]
        if k in seen:
            continue
        seen.add(k)
        items.append(it)

    print(f'[mine_plan] 规划类线索 {len(items)} 条')
    for it in items[:20]:
        print(f"    - [{it['rg']}] {it['t'][:56]} | {it['city']} | {it['d']}")

    if dry or not items:
        return
    os.makedirs(EARLY_DIR, exist_ok=True)
    fp = os.path.join(EARLY_DIR, f'plan-{datetime.now().strftime("%Y-%m-%d")}.json')
    json.dump(items, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'[mine_plan] 已写入 {fp}')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print('[mine_plan] 异常（不阻断主流程）:', e)
    sys.exit(0)
