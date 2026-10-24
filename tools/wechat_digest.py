#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
微信公众号精选稿入库 —— 「情报精选」的人工/半自动源。

用法：
  python3 wechat_digest.py "https://mp.weixin.qq.com/s/xxx" "https://mp.weixin.qq.com/s/yyy" ...
  python3 wechat_digest.py --file links.txt     # 每行一个链接

会自动：抓正文 → 提取公众号名 → 清洗 → 生成摘要 → 按规则分级 → 追加进 raw/wechat_digest.json
分级规则（沿用已验证的口径）：
  S 主业技术词 + 签约/中标/投产/开工/EPC/总承包，或竞对负面
  A 项目/矿产消息但与主业关联弱一档
  B 仅作背景参考
  C 丢弃：正文 >6000 字的研究报告/行业综述（信息密度低，读了也没法行动）
"""
import os, re, sys, json, time, gzip, ssl, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(RAW, 'wechat_digest.json')
PROBE = os.path.join(RAW, '_probe_links.json')

UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 '
      '(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1')
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

BIZ = ['热电', '余热', '煤气', '发电', '机组', '光伏', '储能', '脱硫', '脱硝', '除尘', '污水',
       '废水', '海水淡化', '固废', '垃圾', '生物质', '污泥', '供热', '锅炉', '汽轮机', '电厂',
       '电站', '新能源', '制氢', '零排放', '环境修复', '氧化铝', '电解铝', '自备电厂', '输变电',
       '电力', '设计院', '工程', '环保', '能源', '冶炼', '钢铁', '冶金', '水泥', '矿业', '矿区',
       # 2026-10-19 新增三行业
       '数据中心', 'IDC', '算力', '智算', '化肥', '合成氨', '尿素', '磷化工', '钾盐', '熟料',
       '燃气', '天然气', '燃气轮机', '联合循环', 'LNG', '分布式能源', '三联供', '冷热电', 'CCHP']
EVENT = ['中标', '签约', '签订', '投产', '开工', 'EPC', '总承包', '承建', '承接', '投资', '建设']
NEG = ['撤销', '撤回', '造假', '处罚', '通报', '失信', '被撤', '责令']
OVERSEA = ['印尼', '越南', '几内亚', '海外', '境外', '泰国', '马来西亚', '非洲', '老挝', '柬埔寨']
MAX_KEEP = 6000   # 正文超过这个字数判定为研究报告/综述 → 丢弃


def fetch(u, t=30):
    r = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9',
                                           'Accept-Encoding': 'gzip'})
    resp = urllib.request.urlopen(r, timeout=t, context=CTX)
    raw = resp.read(1200000)
    if resp.headers.get('Content-Encoding') == 'gzip':
        raw = gzip.decompress(raw)
    for e in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(e)
        except Exception:
            pass
    return raw.decode('utf-8', 'ignore')


def clean_text(h):
    h = re.sub(r'<script[\s\S]*?</script>', ' ', h)
    h = re.sub(r'<style[\s\S]*?</style>', ' ', h)
    t = re.sub(r'<[^>]+>', '\n', h)
    t = re.sub(r'&nbsp;|&amp;|&lt;|&gt;|&quot;', ' ', t)
    t = re.sub(r'[ \t\xa0]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


def parse(h, url):
    out = {}
    m = (re.search(r'var\s+nickname\s*=\s*(?:htmlDecode\()?\s*["\']([^"\']+)', h) or
         re.search(r'id="js_name"[^>]*>\s*([^<\s]{2,30})\s*<', h) or
         re.search(r'property="og:site_name"\s+content="([^"]+)', h))
    nm = (m.group(1).strip() if m else '')
    # "微信公众平台" 是 og:site_name 的通用兜底值，不是真实公众号名
    out['src'] = '' if nm in ('微信公众平台', '微信', '') else nm
    m = re.search(r'var\s+msg_title\s*=\s*["\']([^"\']+)', h) or \
        re.search(r'property="og:title"\s+content="([^"]+)', h) or \
        re.search(r'<h1[^>]*class="rich_media_title"[^>]*>([\s\S]{0,200}?)</h1>', h)
    out['t'] = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ''
    m = re.search(r'var\s+ct\s*=\s*["\']?(\d{10})', h) or re.search(r'var\s+create_time\s*=\s*["\'](\d{10})', h)
    out['d'] = time.strftime('%Y-%m-%d', time.localtime(int(m.group(1)))) if m else ''
    out['text'] = clean_text(h)
    out['url'] = url
    return out


def summarize(text, n=2):
    t = re.sub(r'\s+', ' ', text)
    # 取正文里信息密度最高的两句（含数字/单位/项目名）
    sents = [s.strip() for s in re.split(r'[。！？\n]', t) if len(s.strip()) > 18]
    scored = sorted(sents, key=lambda s: -(
        len(re.findall(r'\d', s)) * 2 +
        sum(1 for k in BIZ + EVENT if k in s) +
        (3 if re.search(r'\d+\s*(亿|万|MW|兆瓦|吨)', s) else 0)))
    picked = (scored[:n] if scored else [t[:120]])
    return '。'.join(p[:90] for p in picked)[:220]


def level_of(title, text):
    s = title + ' ' + text[:1500]
    if len(text) > MAX_KEEP:
        return 'C'
    neg = any(k in s for k in NEG)
    biz = sum(1 for k in BIZ if k in s)
    ev = sum(1 for k in EVENT if k in s)
    if neg and biz:
        return 'S'
    if biz >= 2 and ev and (any(k in s for k in OVERSEA) or re.search(r'\d+\s*(亿|万|MW|兆瓦)', s)):
        return 'S'
    if biz and ev:
        return 'A'
    if biz or ev:
        return 'B'
    return 'C'


def tag_of(title, text):
    s = title + ' ' + text[:800]
    if any(k in s for k in NEG + ['资质', '撤销']):
        return '政策资质'
    if any(k in s for k in OVERSEA):
        return '海外项目'
    if any(k in s for k in ['中标', '签约', '签订', '承接', '承建', '投资']):
        return '中标签约'
    if any(k in s for k in ['投产', '开工', '并网', '竣工']):
        return '开工投产'
    return '行业动向'


def main():
    args = sys.argv[1:]
    links = []
    if '--file' in args:
        fp = args[args.index('--file') + 1]
        links = [l.strip() for l in open(fp, encoding='utf-8') if l.strip().startswith('http')]
    else:
        links = [a for a in args if a.startswith('http')]

    # 没有新链接时，把已探测的 8 篇补上公众号名和摘要
    if not links and os.path.exists(PROBE):
        links = [x['url'] for x in json.load(open(PROBE, encoding='utf-8'))]
        print('未给新链接，处理已探测的 %d 篇' % len(links))

    old = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {'items': []}
    items = {x['url']: x for x in old.get('items', [])}
    for u in links:
        try:
            h = fetch(u)
            a = parse(h, u)
            if not a['t']:
                print('  [跳过] 取不到标题', u[:60]); continue
            lv = level_of(a['t'], a['text'])
            if lv == 'C':
                print('  [丢弃 C] %s（正文 %d 字，研究报告类）' % (a['t'][:44], len(a['text']))); continue
            items[u] = {'t': a['t'], 'url': u, 'd': a['d'], 'src': a['src'] or '微信公众号',
                        'srcKind': '微信', 'tag': tag_of(a['t'], a['text']), 'level': lv,
                        'sum': summarize(a['text'])}
            print('  [%s] %s | %s | %s' % (lv, a['d'] or '无日期', a['t'][:46], a['src'][:16]))
        except Exception as e:
            print('  [失败]', u[:60], type(e).__name__, str(e)[:50])
        time.sleep(0.6)

    arr = sorted(items.values(), key=lambda z: (z.get('d') or ''), reverse=True)
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': arr},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    from collections import Counter
    print('\n微信精选库共 %d 条，分级 %s' % (len(arr), dict(Counter(x['level'] for x in arr))))


if __name__ == '__main__':
    main()
