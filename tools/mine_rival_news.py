#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
竞对官网新闻挖掘 —— 「情报精选」板块的自动数据源。

背景：微信公众号文章自动发现已实测全堵（搜狗 antispider 全拦、搜索引擎 site: 无结果、
RSSHub 不可达、Wechat2RSS 无能源类目）。但微信稿的核心价值是「竞对中标喜报 / 海外签约」，
这类信息在竞对自己官网上同样首发、且带日期、带直链、可稳定抓取。
所以本脚本用竞对官网替代微信，作为「情报精选」的自动源。

输出：raw/rival_news.json
"""
import os, re, sys, json, time, gzip, ssl, urllib.request, urllib.error, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
DATA = os.path.join(os.path.dirname(ROOT), 'biz-radar', 'data.js')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

# 事件词：标题里有这些才算「情报」
EVENT = ['中标', '预中标', '签约', '签订', '中标候选人', '开工', '投产', '并网', '总承包',
         'EPC', 'epc', '承建', '承接', '拿下', '获评', '核准', '并网发电', '试运行', '竣工']
# 主业词：命中才说明跟我们业务相关
BIZ = ['热电', '余热', '煤气', '发电', '机组', '光伏', '储能', '脱硫', '脱硝', '除尘',
       '污水', '废水', '海水淡化', '固废', '垃圾', '生物质', '污泥', '供热', '供汽',
       '锅炉', '汽轮机', '超低排放', '环保', '能源', '电厂', '电站', '新能源', '制氢',
       '风电', '输变电', '电网', '热电联产', '零排放', '环境修复', '土壤',
       # 2026-10-19 新增三行业（同事提议）：数据中心 / 化肥 / 水泥 的中资出海
       # 2026-10-19 补：燃气（天然气）发电系列——我司「能源清洁高效利用/热电联产」本就覆盖，
       # 之前词表里完全没有，是缺口。数据中心/园区供电大量采用燃气方案，必须能检索到
       '燃气', '天然气', '燃气轮机', '燃机', '联合循环', 'LNG', '液化天然气',
       '分布式能源', '分布式发电', '三联供', '冷热电', 'CCHP', '内燃机发电', '自备燃气',
       '数据中心', 'IDC', '算力', '智算', '超算',
       '化肥', '合成氨', '尿素', '磷化工', '磷肥', '钾盐',
       '水泥', '熟料', '水泥窑']
# 海外词
OVERSEA = ['印尼', '越南', '老挝', '柬埔寨', '泰国', '马来西亚', '菲律宾', '孟加拉', '巴基斯坦',
           '印度', '非洲', '几内亚', '赞比亚', '刚果', '秘鲁', '智利', '印尼', '沙特', '阿联酋',
           '伊拉克', '塞尔维亚', '波黑', '土耳其', '埃及', '摩洛哥', '津巴布韦', '缅甸', '海外',
           '境外', '国际', '出口', '一带一路']
# 噪音词：官网上最多的一类水文，命中直接丢
NOISE = ['获评', '荣获', '获评', '考核', '出席', '参加', '召开', '举行', '举办', '大会', '会议',
         '座谈会', '研讨', '调研', '走访', '慰问', '党建', '党课', '学习', '宣讲', '培训',
         '比赛', '竞赛', '活动', '评选', '榜单', '排名', '揭牌', '成立', '签署战略', '交流',
         '看望', '督导', '检查', '视察', '参观', '招聘', '团建', '联欢', '表彰', '当选',
         '任职', '任命', '干部', '民主生活', '主题党日', '志愿服务', '篮球', '运动会']
# 规模词：有这些说明项目量级明确，价值更高
SCALE = re.compile(r'(\d+(\.\d+)?)\s*(兆瓦|MW|mw|万千瓦|千瓦|kW|kw|吨/日|吨\/日|万立方米|亿元|万元|MW时|MWh|兆瓦时)')


def fetch(u, t=25, retry=1):
    last = None
    for _ in range(retry + 1):
        try:
            r = urllib.request.Request(u, headers={'User-Agent': UA,
                'Accept-Language': 'zh-CN,zh;q=0.9', 'Accept-Encoding': 'gzip',
                'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
                'Referer': urllib.parse.urlunparse(urllib.parse.urlparse(u)[:2] + ('', '', '', '')) + '/'})
            resp = urllib.request.urlopen(r, timeout=t, context=CTX)
            raw = resp.read(400000)
            break
        except Exception as e:
            last = e
            raw = None
            time.sleep(0.8)
    if raw is None:
        raise last
    if resp.headers.get('Content-Encoding') == 'gzip':
        raw = gzip.decompress(raw)
    for e in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(e)
        except Exception:
            pass
    return raw.decode('utf-8', 'ignore')


def abs_url(base, href):
    if not href or href.startswith('#') or href.startswith('javascript'):
        return ''
    return urllib.parse.urljoin(base, href)


def parse_date(u, txt=''):
    """URL 里常带 /art/2026/10/9/ 这种，优先用；否则从文本找"""
    m = re.search(r'/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})', u)
    if m:
        return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', txt or '')
    if m:
        return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ''


def pick_level(title, body=''):
    s = title + ' ' + body[:300]
    # 噪音优先排除：水文命中且没有规模/项目实体的一律丢
    if any(k in title for k in NOISE) and not SCALE.search(title):
        return ''
    ev = sum(1 for k in EVENT if k in s)
    biz = sum(1 for k in BIZ if k in s)
    scale = bool(SCALE.search(title))
    if ev and biz and (scale or any(k in s for k in OVERSEA)):
        return 'S'
    if ev and biz:
        return 'A'
    return ''   # B 级噪音太多，不收


def pick_tag(title):
    if any(k in title for k in OVERSEA):
        return '海外项目'
    if any(k in title for k in ['资质', '撤销', '撤回', '处罚', '通报', '失信']):
        return '政策资质'
    if any(k in title for k in ['中标', '预中标', '签约', '签订', '候选人', '拿下', '承接', '承建']):
        return '中标签约'
    if any(k in title for k in ['开工', '投产', '并网', '竣工', '试运行', '获评']):
        return '开工投产'
    return '行业动向'


def clean_title(t):
    t = re.sub(r'\s+', ' ', t or '').strip()
    return t


COL_KW = re.compile(r'新闻|资讯|要闻|动态|公告|媒体|项目|业绩|案例|快讯|中心')
NEWS_PAT = re.compile(r'(news|xwzx|xinwen|article|/art/|detail|info|zxdt|dtzx|media|meida)', re.I)
COMMON_PATH = ['/news/', '/news/index.html', '/news.html', '/xwzx/', '/xwzx/index.html',
               '/about/news/', '/cn/news/', '/newscenter/', '/news/list.html', '/xwzx/list.html']


def find_cols(home, h):
    """找新闻栏目页：首页链接关键词 + URL 模式 + 常见硬编码路径"""
    cols = [home]
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{1,26})</a>', h):
        href, txt = m.group(1), m.group(2).strip()
        u = abs_url(home, href)
        if not u or u.rstrip('/') == home.rstrip('/'):
            continue
        if COL_KW.search(txt) or NEWS_PAT.search(href):
            if u not in cols:
                cols.append(u)
    pu = urllib.parse.urlparse(home)
    for cp in COMMON_PATH:
        u = '%s://%s%s' % (pu.scheme, pu.netloc, cp)
        if u not in cols:
            cols.append(u)
    return cols[:8]


def harvest(name, home, deep=True, log=print):
    """抓一家竞对官网，返回条目列表"""
    out, seen = [], set()
    try:
        h = fetch(home)
    except Exception as e:
        log('  [跳过] %s 首页失败 %s' % (name[:18], type(e).__name__))
        return out

    pages = find_cols(home, h) if deep else [home]
    for pu in pages:
        try:
            ph = fetch(pu, t=15) if pu != home else h
        except Exception:
            continue
        # <a> 文本标题 + <li>/<td> 内嵌链接两种形态都收
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]{6,160}?)</a>', ph):
            href, raw = m.group(1), m.group(2)
            title = clean_title(re.sub(r'<[^>]+>', '', raw))
            if not title or len(title) < 8:
                continue
            lv = pick_level(title)
            if not lv:
                continue
            u = abs_url(pu, href)
            if not u or u in seen:
                continue
            seen.add(u)
            out.append({
                't': title, 'url': u, 'd': parse_date(u, title),
                'src': name, 'srcKind': '官网', 'tag': pick_tag(title), 'level': lv,
            })
        if len(out) > 60:
            break
    return out


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    s = open(DATA, encoding='utf-8').read()
    d = json.loads(s[s.find('{'):s.rfind('}') + 1])
    comps = d.get('competitors', [])
    if limit:
        comps = comps[:limit]
    print('开始抓 %d 家竞对官网' % len(comps))
    allitems, okc = [], 0
    for i, c in enumerate(comps):
        name, home = c.get('name', ''), (c.get('url') or '')
        if not home.startswith('http'):
            continue
        pu = urllib.parse.urlparse(home)
        # url 指向具体文章页时，退回域名根（否则只能抓到一篇）
        if pu.path.count('/') >= 2 or re.search(r'/[a-z]?\d{8,}', pu.path):
            home = '%s://%s/' % (pu.scheme, pu.netloc)
        got = harvest(name, home)
        if got:
            okc += 1
            print('  [%2d/%d] %s → %d 条' % (i + 1, len(comps), name[:22], len(got)))
        allitems.extend(got)
        time.sleep(0.3)

    # 去重：同标题 + 同事件指纹（同一项目被多家号/多栏目重复报道时只留最早一条）
    def fp(t):
        t = re.sub(r'^[\u4e00-\u9fa5A-Za-z0-9·、]{2,12}[：:]\s*', '', t)   # 去「舟山日报：」这类来源前缀
        t = re.sub(r'^[\u4e00-\u9fa5A-Za-z0-9（）()·、]{0,18}(院|公司|集团|有限公司|股份)', '', t)
        for k in EVENT:
            t = t.replace(k, '')
        t = re.sub(r'[\s：:，,。（）()""''《》\-|—]', '', t)
        return t[:18]
    seen, fseen, items = set(), set(), []
    for x in sorted(allitems, key=lambda z: (z['d'] or ''), reverse=True):
        k = re.sub(r'[\s（）()]', '', x['t'])
        f = fp(x['t'])
        if k in seen or (len(f) >= 8 and f in fseen):
            continue
        seen.add(k); fseen.add(f)
        items.append(x)
    items.sort(key=lambda z: (z['d'], z['level']), reverse=True)
    os.makedirs(RAW, exist_ok=True)
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'n_src': okc, 'items': items},
              open(os.path.join(RAW, 'rival_news.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    from collections import Counter
    print('\n抓通 %d/%d 家，原始 %d 条 → 去重后 %d 条' % (okc, len(comps), len(allitems), len(items)))
    print('分级:', dict(Counter(x['level'] for x in items)))
    print('分类:', dict(Counter(x['tag'] for x in items)))
    for x in items[:8]:
        print('  [%s/%s] %s | %s' % (x['level'], x['d'] or '无日期', x['t'][:52], x['src'][:14]))


if __name__ == '__main__':
    main()
