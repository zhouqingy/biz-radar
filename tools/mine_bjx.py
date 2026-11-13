#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北极星电力网行业动态采集（2026-10-20 新增渠道）

为什么加这个源：行业动态板块原来靠微信快讯，微信渠道堵死后 80 条只剩 25 条、
最新停在 09-16。北极星是电力/环保垂直媒体，纯静态 HTML 可直抓（实测首页 193 链接 / 49 条业务命中），
且频道划分正好对上我司主业：
  fd    发电（火电/热电/余热）
  daqi  大气（脱硫脱硝/除尘/超低排放）
  energy 能源（综合能源/节能）
  chuneng 储能
  shui  水处理

输出：raw/bjx_news.json  {updated, items:[{t,url,src,cat,d}]}
"""
import os, re, json, time, gzip, sys, urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _atomic import atomic_dump, safe_load
except ImportError:  # _atomic.py 尚未同步到远端时退化，保证脚本本身仍能跑
    import json as _j

    def atomic_dump(obj, path, indent=None, ensure_ascii=False):
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            _j.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return path

    def safe_load(path, default=None, label=''):
        if not os.path.exists(path):
            return default, True
        try:
            with open(path, encoding='utf-8') as f:
                return _j.load(f), True
        except Exception as e:
            print('[FATAL] %s 读取失败：%s（%d 字节）'
                  % (label or os.path.basename(path), e, os.path.getsize(path)))
            return default, False


ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(RAW, 'bjx_news.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

CHANS = [
    ('https://www.bjx.com.cn/', '电力综合'),
    ('https://fd.bjx.com.cn/', '发电'),
    ('https://daqi.bjx.com.cn/', '大气治理'),
    ('https://energy.bjx.com.cn/', '综合能源'),
    ('https://chuneng.bjx.com.cn/', '储能'),
    ('https://shui.bjx.com.cn/', '水处理'),
]

# 业务词：命中才收（跟 biz_crawl.py 的 HIT 口径一致，另加燃气系列）
BIZ = ['余热', '发电', '热电', '煤气', '燃气', '天然气', '联合循环', '分布式能源',
       '三联供', '锅炉', '汽机', '机组', 'CCPP', 'TRT', '光伏', '储能',
       '烧结', '焦化', '高炉', '转炉', '电炉', '超低排放', '脱硫', '脱硝', '除尘',
       '烟气', 'VOCs', '废气', '污水', '废水', '中水', '零排放', '海水淡化', '污泥',
       '固废', '危废', '土壤', '修复', '水处理', '供水', '排水', '供热', '节能',
       '综合利用', '能源', 'EPC', '总承包', '中标', '签约', '投产', '开工', '核准', '环评']

# 明显不是机会的噪音（招聘/展会/人事/股价/研报）
NOISE = ['招聘', '求职', '简历', '展会', '论坛报名', '培训班', '人事', '任命',
         '辞职', '股价', '涨停', '研报', '评级', '财报', '季报', '年报', '分红']


def fetch(u, timeout=25):
    r = urllib.request.Request(u, headers={
        'User-Agent': UA, 'Accept': 'text/html,*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9', 'Referer': 'https://www.bjx.com.cn/'})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        b = resp.read()
        if resp.headers.get('Content-Encoding') == 'gzip':
            try:
                b = gzip.decompress(b)
            except Exception:
                pass
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('gbk', 'ignore')


def extract(html, cat):
    """从列表页/首页抽取 (标题, 链接, 日期)"""
    out = []
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>\s*([^<]{8,80}?)\s*</a>', html):
        url, t = m.group(1), m.group(2).strip()
        t = re.sub(r'\s+', ' ', t)
        if len(t) < 8:
            continue
        if not any(k in t for k in BIZ):
            continue
        if any(w in t for w in NOISE):
            continue
        # 只要北极星自己的文章页
        if 'bjx.com.cn' not in url:
            continue
        if re.search(r'/(job|b2b|club|edu|ex)\.', url):
            continue
        # 日期：链接里常带 /20261020/ 这类
        dm = re.search(r'/(20\d{6})/', url) or re.search(r'/(20\d{2})[-/]?(\d{2})[-/]?(\d{2})', url)
        d = ''
        if dm:
            s = dm.group(1) if dm.lastindex == 1 else ''.join(dm.groups())
            s = re.sub(r'\D', '', s)[:8]
            if len(s) == 8:
                d = '%s-%s-%s' % (s[:4], s[4:6], s[6:8])
        out.append({'t': t, 'url': url, 'src': '北极星·' + cat, 'cat': cat, 'd': d})
    return out


def main():
    items, seen, stat = [], set(), {}
    for url, cat in CHANS:
        try:
            h = fetch(url)
            got = extract(h, cat)
        except Exception as e:
            stat[cat] = '❌ %s' % type(e).__name__
            continue
        n = 0
        for x in got:
            k = x['t'][:34]
            if k in seen:
                continue
            seen.add(k)
            items.append(x)
            n += 1
        stat[cat] = '%d 条' % n
        time.sleep(0.6)

    # ── 并集合并（2026-11-13 修静默丢项）──────────────────────────────
    # 原来这里直接覆盖写：某天某个频道抓少了、或者首页改版只返回一半，
    # 旧新闻就被永久抹掉，而且不报错。实测出现过「本地 196 / 远端 200，
    # 各自都有对方没有的条目」——谁后写谁赢，先写的全丢。
    # 现在改成：旧 ∪ 新，按 url 去重（无 url 退回标题前 34 字），只裁掉 120 天前的。
    old, ok = safe_load(OUT, {}, 'bjx_news.json')
    old_items = (old.get('items') or []) if isinstance(old, dict) else []
    if not ok:
        print('[WARN] 旧 bjx_news.json 读不出来，本轮以新抓结果为准（旧文件已保留为 .bad）')
        try:
            os.replace(OUT, OUT + '.bad')
        except OSError:
            pass
        old_items = []

    def _key(x):
        u = (x.get('url') or '').strip()
        return u if u else (x.get('t') or '')[:34]

    merged, seen2 = [], set()
    # 先放旧的（历史优先），再放新的（补充）；同一 key 以新抓的为准（标题/日期可能更新）
    for x in items:
        k = _key(x)
        if k in seen2:
            continue
        seen2.add(k)
        merged.append(x)
    add_old = 0
    for x in old_items:
        k = _key(x)
        if k in seen2:
            continue
        seen2.add(k)
        merged.append(x)
        add_old += 1

    # 只保留近 120 天，避免文件无限膨胀
    cut = (time.strftime('%Y-%m-%d', time.localtime(time.time() - 120 * 86400)))
    before = len(merged)
    merged = [x for x in merged if not x.get('d') or x['d'] >= cut]
    dropped = before - len(merged)

    atomic_dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': merged}, OUT)

    print('北极星采集：')
    for k, v in stat.items():
        print('   %-8s %s' % (k, v))
    print('新抓 %d 条 · 从旧文件补回 %d 条 · 裁掉 120 天前 %d 条 → 合计 %d 条'
          % (len(items), add_old, dropped, len(merged)))

    # 抓取骤降告警：新抓条数不到旧文件六成，多半是改版或被拦，必须喊出来
    if old_items and len(items) < len(old_items) * 0.6:
        print('[WARN] 本轮新抓 %d 条，仅为旧文件 %d 条的 %.0f%%。'
              % (len(items), len(old_items), 100.0 * len(items) / len(old_items)))
        print('       已用并集保底，但采集通道很可能出问题了，请查 CHANS 是否被改版。')
    print('→ %s' % OUT)


if __name__ == '__main__':
    main()
