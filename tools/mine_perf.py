#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对业绩挖掘 · mine_perf.py
===========================
从各地公共资源交易中心的中标候选人公示页，抽取「中标候选人企业业绩」表。

为什么要做这个：
  中标公示里常常附一张业绩表，列出中标单位过去干过的项目——
  工程名称 / 建设单位 / 中标时间 / 中标金额。
  把这些攒起来，就是一份**有实证的竞对画像**：大致报价区间、做过哪些细分、服务过哪些业主。

数据源（南通已验证）：
  http://ggzyjy.nantong.gov.cn/jyxx/003001/003001004/tradeInfo.html?pageIndex=N
  · 列表每页 15 条，共 14,957 条中标公示
  · 详情页 curl 直取即可（无需无头浏览器）
  · 约 2/3 的详情页带业绩表，单页 3-15 条业绩

用法：
  python3 mine_perf.py --pages 10                      # 先抓 10 页看看效果
  python3 mine_perf.py --pages 50 --out raw/perf_nt.json
  python3 mine_perf.py --report                        # 只打印已有数据的汇总
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'

# 各地站点配置。目前只做南通，验证有效后再扩。
SITES = {
    'nantong': {
        'name': '南通市公共资源交易中心',
        'rg': '江苏',
        # 分页规则（2026-10-21 实测确认）：
        #   第 1 页   /tradeInfo.html
        #   第 2-8 页 /{N}.html            ← 静态路径，curl 直取即可
        #   第 9 页起 /tradeInfo.html?categoryNum=003001004&pageIndex=N
        # 早期误用 ?pageIndex=N 翻前 8 页，服务端忽略该参数、永远返回第 1 页。
        'list': 'http://ggzyjy.nantong.gov.cn/jyxx/003001/003001004/%s',
        'host': 'http://ggzyjy.nantong.gov.cn',
        'need_browser': False,
    },
}

# ---------------- 赛道相关度过滤 ----------------
# 南通站是「全行业」公示，前几页大量是幕墙、景观、监理、房建，
# 跟都市环保（热电/余热/脱硫脱硝/水处理/固废）完全无关。
# 因此必须做赛道过滤，否则业绩库会被噪音淹没。
TRACK = [
    ('热电联产',   ['热电联产', '热电机组', '背压', '供热机组', '热网', '蒸汽管网', '集中供热']),
    ('余热发电',   ['余热发电', '余热利用', '余热锅炉', '干熄焦', '烧结余热', '烟气余热']),
    ('煤气/燃气发电', ['煤气发电', '燃气发电', '燃机', '联合循环', 'CCPP', '天然气发电', '分布式能源', '三联供']),
    ('燃煤发电',   ['燃煤', '煤电', '超超临界', '亚临界', '机组扩建', '发电工程', '电厂']),
    ('脱硫脱硝',   ['脱硫', '脱硝', '烟气治理', 'SCR', 'SNCR']),
    ('除尘超低排放', ['除尘', '超低排放', '电袋', '布袋']),
    ('废水/水处理', ['废水', '污水', '中水', '水处理', '零排放', '海水淡化']),
    ('固废/垃圾',  ['垃圾焚烧', '垃圾发电', '固废', '污泥']),
    ('光伏/储能',  ['光伏', '风电', '储能', '新能源发电']),
    ('环境修复',   ['土壤修复', '场地修复', '生态修复']),
]
# 明确排除：这些出现即判为无关（避免「XX 项目配套道路」这类误命中）
EXCLUDE = ['幕墙', '景观', '绿化', '园林', '装饰', '装修', '监理', '房建', '住宅', '安置房',
           '学校', '医院', '办公楼', '道路', '桥梁', '市政道路', '管网改造', '电梯', '消防工程',
           '弱电', '智能化', '空调', '供配电', '变配电']


def track_of(proj):
    """返回 (赛道名 or None, 是否被排除)。"""
    t = proj or ''
    for k in EXCLUDE:
        if k in t:
            return None, True
    for name, kws in TRACK:
        if any(k in t for k in kws):
            return name, False
    return None, False


ITEM_RE = re.compile(r'/jyxx/003001/003001004/(\d{8})/([0-9a-f-]{36})\.html')


def list_url(cfg, p):
    """按南通站的分页规则拼列表页地址。"""
    if p <= 1:
        return cfg['list'] % 'tradeInfo.html'
    if p <= 8:
        return cfg['list'] % ('%d.html' % p)
    return cfg['list'] % ('tradeInfo.html?categoryNum=003001004&pageIndex=%d' % p)


def sh(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ''


def fetch(url, timeout=30):
    """用 curl 抓页面。加 -k 是因为部分政府站点证书链不完整。"""
    return sh(['curl', '-sS', '--max-time', str(timeout), '-A', UA, '-k', url], timeout + 15)


def fetch_browser(url, budget=18000, timeout=120):
    """翻页/JS 渲染页面用无头 Chrome。"""
    return sh(['google-chrome', '--headless=new', '--disable-gpu', '--no-sandbox',
               '--virtual-time-budget=%d' % budget, '--dump-dom', url], timeout)


def parse_list(html):
    """从列表页提取详情链接。"""
    out = []
    for d, uid in ITEM_RE.findall(html):
        out.append('/jyxx/003001/003001004/%s/%s.html' % (d, uid))
    # 去重保序
    return list(dict.fromkeys(out))


CELL = re.compile(r'<td([^>]*)>(.*?)</td>', re.S)


def clean(t):
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', t).strip()


def parse_perf(html):
    """
    解析「中标候选人企业业绩」表。

    表结构（南通）：
      单位名称 | 工程名称 | 建设单位 | 中标时间 | 中标金额
    单位名称列用了 rowspan 合并，只有第一行有值，后续行少一个 td。
    所以不能按固定列数解析，要靠 rowspan 继承。
    """
    # 只取业绩表：id='Table1.2'
    i = html.find("id='Table1.2'")
    if i < 0:
        i = html.find('id="Table1.2"')
    if i < 0:
        return []
    seg = html[i:html.find('</table>', i)]
    if not seg:
        return []

    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', seg, re.S)
    if len(rows) < 2:
        return []

    out = []
    cur = None
    left = 0          # 当前 rowspan 还剩几行
    for r in rows:
        tds = CELL.findall(r)
        vals = []
        for attrs, content in tds:
            vals.append(clean(content))
        if not vals:
            continue
        # 跳过表头
        if vals[0] in ('单位名称', '中标候选人名称') or (
                len(vals) >= 2 and vals[1] in ('工程名称', '项目名称')):
            continue

        has_unit = 'rowspan' in tds[0][0]
        if has_unit:
            m = re.search(r"rowspan=['\"]?(\d+)", tds[0][0])
            left = int(m.group(1)) if m else 1
            cur = vals[0]
            rest = vals[1:]
        else:
            rest = vals
            left = max(0, left - 1)

        if not cur or len(rest) < 4:
            continue
        proj, owner, when, amt = rest[0], rest[1], rest[2], rest[3]
        if not proj or proj in ('/', '—', '-', '无'):
            continue
        out.append({
            'unit': cur,
            'proj': proj,
            'owner': owner,
            'date': when[:10],
            'amt_txt': amt,
        })
    return out


AMT_RE = re.compile(r'([\d,]+(?:\.\d+)?)\s*(万元|亿元|元)')


def parse_amt(txt):
    """'66083.374万元' -> 6.6083374（亿元）；统一按亿元存，便于汇总。"""
    m = AMT_RE.search(txt or '')
    if not m:
        return None
    try:
        v = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    unit = m.group(2)
    if unit == '亿元':
        return round(v, 4)
    if unit == '万元':
        return round(v / 10000, 6)
    return round(v / 1e8, 8)


def parse_title(html):
    m = re.search(r'<title>(.*?)</title>', html, re.S)
    if m:
        t = clean(m.group(1))
        if t and '404' not in t:
            return t[:120]
    # 部分页面 title 为空，退回正文首个加粗/居中标题
    m = re.search(r'<b[^>]*>(.*?)</b>', html, re.S)
    return clean(m.group(1))[:120] if m else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', default='nantong')
    ap.add_argument('--pages', type=int, default=10)
    ap.add_argument('--out', default='')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--sleep', type=float, default=1.2, help='每页间隔秒数，防封')
    args = ap.parse_args()

    out_path = args.out or os.path.join(RAW, 'perf_%s.json' % args.site)

    if args.report:
        return report(out_path)

    cfg = SITES[args.site]
    store = {'site': args.site, 'site_name': cfg['name'], 'rg': cfg['rg'],
             'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': []}
    if os.path.exists(out_path):
        try:
            old = json.load(open(out_path, encoding='utf-8'))
            store['items'] = old.get('items', [])
        except Exception:
            pass
    have = {(x['unit'], x['proj']) for x in store['items']}

    n_page = n_doc = n_new = n_skip = 0
    for p in range(1, args.pages + 1):
        url = list_url(cfg, p)
        html = fetch_browser(url) if cfg['need_browser'] else fetch(url)
        links = parse_list(html)
        if not links:
            print('[第%d页] 列表为空，停止' % p)
            break
        n_page += 1
        got = 0
        for ln in links:
            full = cfg['host'] + ln
            h = fetch(full)
            if not h:
                continue
            n_doc += 1
            perfs = parse_perf(h)
            if not perfs:
                continue
            title = parse_title(h)
            for x in perfs:
                key = (x['unit'], x['proj'])
                if key in have:
                    continue
                tk, excluded = track_of(x['proj'])
                if excluded:
                    n_skip += 1
                    continue
                have.add(key)
                x['amt'] = parse_amt(x['amt_txt'])
                x['src'] = full
                x['doc'] = title
                x['rg'] = cfg['rg']
                x['city'] = '南通'
                x['track'] = tk or ''      # 空 = 未归类，前端可单独看
                store['items'].append(x)
                n_new += 1
                got += 1
            time.sleep(0.35)   # 详情页间隔，别太快
        print('[第%d页] 列表 %d 条 · 入账 %d 条 · 累计 %d 条（跳过无关 %d）'
              % (p, len(links), got, len(store['items']), n_skip))
        time.sleep(args.sleep)

    os.makedirs(RAW, exist_ok=True)
    json.dump(store, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n列表页 %d · 详情页 %d · 本次新增 %d · 过滤无关 %d · 累计 %d 条 → %s'
          % (n_page, n_doc, n_new, n_skip, len(store['items']), out_path))
    report(out_path)


def report(path):
    if not os.path.exists(path):
        print('还没有数据：%s' % path)
        return
    d = json.load(open(path, encoding='utf-8'))
    items = d.get('items', [])
    print('\n' + '=' * 62)
    print('竞对业绩库 · %s · 更新 %s' % (d.get('site_name', ''), d.get('updated', '')))
    print('=' * 62)
    print('总业绩 %d 条 · 涉及单位 %d 家 · 涉及业主 %d 家'
          % (len(items), len({x['unit'] for x in items}), len({x['owner'] for x in items})))

    by = defaultdict(list)
    for x in items:
        by[x['unit']].append(x)

    print('\n【按单位】业绩数 TOP15')
    print('%-38s %4s %10s %10s %10s' % ('单位', '条数', '金额合计', '均值', '最大单'))
    for unit, xs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:15]:
        amts = [x['amt'] for x in xs if x.get('amt')]
        tot = sum(amts)
        avg = tot / len(amts) if amts else 0
        mx = max(amts) if amts else 0
        print('%-38s %4d %9.2f亿 %8.0f万 %8.0f万'
              % (unit[:38], len(xs), tot, avg * 10000, mx * 10000))

    # 细分方向：用我司赛道词归类
    KW = [('热电联产', ['热电联产', '热电机组', '背压', '供热机组']),
          ('余热发电', ['余热发电', '余热利用', '余热锅炉']),
          ('煤气/燃气发电', ['煤气发电', '燃气', '燃机', '联合循环', 'CCPP']),
          ('脱硫脱硝', ['脱硫', '脱硝', '烟气']),
          ('除尘超低排放', ['除尘', '超低排放', '电袋']),
          ('废水/水处理', ['废水', '污水', '中水', '水处理', '零排放']),
          ('光伏/新能源', ['光伏', '风电', '储能', '新能源']),
          ('垃圾焚烧', ['垃圾', '焚烧'])]
    print('\n【按细分方向】')
    cnt = Counter()
    for x in items:
        t = x['proj']
        for name, kws in KW:
            if any(k in t for k in kws):
                cnt[name] += 1
                break
        else:
            cnt['其他'] += 1
    for k, v in cnt.most_common():
        print('  %-14s %4d 条' % (k, v))

    print('\n【样例 8 条】')
    for x in items[:8]:
        amt = ('%.2f亿' % x['amt']) if x.get('amt') else '—'
        print('  %s | %s | %s | %s' % (x['unit'][:22], x['proj'][:44], x['date'], amt))


if __name__ == '__main__':
    main()
