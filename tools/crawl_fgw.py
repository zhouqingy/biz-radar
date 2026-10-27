# -*- coding: utf-8 -*-
"""省市发改委「项目/能源公示」采集器（2026-10-27 补源方案 A 的一部分）。

为什么写这个
────────────
用户问「业务信息监测为什么只有 3 条」——根因是 trends 池只吃行业媒体（北极星 + 微信），
而电力垂直媒体不报「省发改委刚把哪台机组纳入规划」这类**政府侧一手信号**。
这类信号在省发改委的「网上公示 / 能源」栏目里，静态页可直抓，一天几十条。

实测两个源（2026-10-27）：
  · 江苏省发改委 网上公示 /col/col319/ —— 煤电项目优选排序、应急备用电源、
    海上风电竞争性配置中选主体、能源首台（套）名单 —— 全是「哪台机组要上」的名单
  · 上海市发改委 能源 /fgw_ny/ —— 燃机项目专家优选实施方案、可再生能源专项资金
    项目目录（目录里是具体项目名单）

产出：raw/fgw_news.json（与 bjx_news.json 同构：t/url/src/cat/d），
由 build_web.py 并入行业动态池，再交给前端 sigJudge 判定。

用法：python crawl_fgw.py [--dry]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
OUT = os.path.join(RAW, 'fgw_news.json')

# (站点名, 列表页 URL, 链接前缀补全)
FEEDS = [
    ('江苏省发改委·网上公示', 'https://fzggw.jiangsu.gov.cn/col/col319/index.html',
     'https://fzggw.jiangsu.gov.cn'),
    ('上海市发改委·能源', 'https://fgw.sh.gov.cn/fgw_ny/index.html',
     ''),
]
# 双向过滤：既要命中能源/项目类词，又不能是人事/奖励/价格类噪声。
# ⚠ 第一版只做了 WANT（单向），实测 34 条里一半是「负责人任职前公示」
#   「碳足迹拟奖励名单」这种跟建厂毫无关系的，进了池子只会稀释真信号。
WANT = re.compile(r'机组|煤电|热电|发电|燃机|风电|光伏|储能|电力|能源|供热|余热|'
                  r'生物质|垃圾|电网|节能|技改|装机|新能源|可再生能源|煤炭|'
                  r'项目名单|优选|中选|核准|备选项目')
SKIP = re.compile(r'任职|负责人|博士后|先进集体|先进个人|获奖|奖励|碳足迹|价格|'
                  r'物流|研究会|促进会|中心|价格认定|成品油|监测|培训|大赛|'
                  r'创新创业|招生|招聘|人事')


def fetch(url, timeout=25):
    r = subprocess.run(['curl', '-sk', '-m', str(timeout), url,
                        '-H', 'User-Agent: ' + UA],
                       capture_output=True)
    return r.stdout.decode('utf-8', 'ignore')


def ymd_from_href(href):
    """从链接里抠日期：/art/2026/4/16/… 、/fgw_ny/20261020/…"""
    m = re.search(r'/(?:art/)?(\d{4})[/-](\d{1,2})[/-](\d{1,2})', href)
    if m:
        return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r'/(\d{8})/', href)
    if m:
        s = m.group(1)
        return '%s-%s-%s' % (s[:4], s[4:6], s[6:8])
    return ''


def crawl_feed(name, url, base):
    html = fetch(url)
    if len(html) < 500:
        print('  %s 抓取失败（%d 字节）' % (name, len(html)))
        return []
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]{0,200}?)</a>', html):
        href, raw = m.group(1), m.group(2)
        t = re.sub(r'<[^>]+>', ' ', raw)
        t = re.sub(r'\s+', ' ', t).strip()
        if len(t) < 10 or len(t) > 80:
            continue
        if not WANT.search(t) or SKIP.search(t):
            continue
        if not re.search(r'/art/|/fgw_\w+/\d{8}|/\d{8}/', href):
            continue
        full = href if href.startswith('http') else (base + href if base else href)
        if not full.startswith('http'):
            continue
        key = t[:34]
        if key in seen:
            continue
        seen.add(key)
        out.append({'t': t, 'url': full, 'src': name,
                    'cat': '项目与能源公示', 'd': ymd_from_href(href)})
    print('  %s %d 条' % (name, len(out)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    print('== 省市发改委项目/能源公示 ==')
    items = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for got in ex.map(lambda f: crawl_feed(*f), FEEDS):
            items.extend(got)

    # 去重：标题前 34 字
    seen, uniq = set(), []
    for x in items:
        if x['t'][:34] in seen:
            continue
        seen.add(x['t'][:34])
        uniq.append(x)
    print('合计 %d 条（去重后）' % len(uniq))
    for x in uniq[:8]:
        print('   %s | %s' % (x['d'] or '无日期', x['t'][:52]))

    if a.dry:
        print('--dry 不落盘')
        return 0
    old = []
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            old = []
    have = {x['t'][:34] for x in old}
    add = [x for x in uniq if x['t'][:34] not in have]
    json.dump(old + add, open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('✅ 写入 %s：新增 %d 条，累计 %d 条' % (OUT, len(add), len(old) + len(add)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
