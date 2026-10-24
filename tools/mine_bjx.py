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
import os, re, json, time, gzip, urllib.request, urllib.parse

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

    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': items},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('北极星采集：')
    for k, v in stat.items():
        print('   %-8s %s' % (k, v))
    print('合计 %d 条 → %s' % (len(items), OUT))


if __name__ == '__main__':
    main()
