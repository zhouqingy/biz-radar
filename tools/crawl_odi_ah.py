#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""境外投资备案采集 · 安徽源（省发改委依申请公开季度目录）2026-11-26

背景（§5.115，用户拍板「可以啊，按照你建议的走呗」）
------------------------------------------------
此前备案线只有浙江 tzxm.zjzwfw.gov.cn 一个源（684 条）。实测其他省市里：
  · 江苏/上海：只有散件 PDF 附件，无列表页 → 不可脚本化
  · 商务部 ecomp：需登录 → 不可抓
  · 安徽：省发改委把每季度「依申请公开信息目录」发成一个 HTML 大表，
    其中「境外投资项目备案通知书（注：XXX）」行含 企业+国家+项目+文号+日期，
    每季度约 94 条，纯静态可抓 → 接！

数据源结构（2026-11-26 实测）
----------------------------
1) 目录列表接口（自动发现新一期季度目录）：
   GET https://fzggw.ah.gov.cn/public/applyCatalogQuery
       ?siteId=49631471&organId=7011&pageSize=15&pageIndex=0&catId=2657091
   返回 JSON，data.data[] 每项含 title（「2026年三季度省发展改革委依申请公开
   信息目录」）+ link（/public/7011/150727491.html）+ publishDate。
   共 60 期 / 4 页，全量拉完很便宜。

2) 季度目录页：一个 HTML 大表（Word 导出的表格），每行 <tr> 五列：
   [序号, 标题（境外投资项目备案通知书（注：…项目））, 文号, 日期, 承办处室…]
   只取标题含「境外投资项目备案」的行。

字段映射（对齐 crawl_odi.py 的 item schema，pick_odi.py 可直接吃）：
   name  = 注：里的项目描述（企业+国家+动作+项目）
   owner = 注文里第一个「在/通过/与/向」之前的主体企业名
   geo   = 复用 crawl_odi._find_geo（撞名防护已调好）
   act   = 复用 crawl_odi.ACT 动词表
   code  = 文号（皖发改外资备〔YYYY〕N号）
   date  = 表格日期列
   url   = 季度目录页 URL（可回溯原文）
滞后一季是渠道天然节奏（季度汇编），但比没有强。
"""
import json
import os
import re
import time
import urllib.request

from preflight import require_briefing          # 开工必读校验
require_briefing('crawl_odi_ah.py')

import crawl_odi as ZJ                          # 复用国家表 / _find_geo / ACT / 金额

ROOT = os.path.dirname(os.path.abspath(__file__))
HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
}
BASE = 'https://fzggw.ah.gov.cn'
CATALOG_API = (BASE + '/public/applyCatalogQuery'
               '?siteId=49631471&organId=7011&pageSize=15&pageIndex={page}'
               '&catId=2657091')
OUT = os.path.join(ROOT, 'raw', 'invest_odi_ah.json')


def _get(url, retry=2):
    for i in range(retry + 1):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=HDR),
                                       timeout=30)
            return r.read().decode('utf-8', 'ignore')
        except Exception:
            if i == retry:
                return ''
            time.sleep(1.2 * (i + 1))
    return ''


def list_quarters(max_pages=6):
    """拉全量季度目录（title 含「依申请公开信息目录」的条目）。"""
    out = []
    for page in range(max_pages):
        txt = _get(CATALOG_API.format(page=page))
        if not txt:
            break
        try:
            j = json.loads(txt)
        except Exception:
            break
        rows = (j.get('data') or {}).get('data') or []
        if not rows:
            break
        for it in rows:
            t = (it.get('title') or '').strip()
            link = (it.get('link') or '').strip()
            if '依申请公开信息目录' in t and link:
                out.append({'title': t, 'url': BASE + link,
                            'pub': (it.get('publishDate') or '')[:10]})
        if not (j.get('data') or {}).get('hasMore'):
            break
        time.sleep(0.4)
    return out


_TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
_TAG = re.compile(r'<[^>]+>')
_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})')
_CODE = re.compile(r'〔(\d{4})〕(\d+)号')


def parse_quarter(url):
    """从一个季度目录页解析「境外投资项目备案」行。"""
    html = _get(url)
    if not html:
        return []
    items = []
    for tr in re.findall(r'<tr[^>]*>.*?</tr>', html, re.S):
        tds = [_TAG.sub('', t).replace('&nbsp;', ' ').strip()
               for t in _TD.findall(tr)]
        if not tds:
            continue
        hit = next((t for t in tds if '境外投资项目备案' in t), None)
        if not hit:
            continue
        # 项目名 = 「注：…」里的话；没有「注：」就整段当名字
        m = re.search(r'注[：:]\s*(.+?)\s*[）)]?\s*$', hit)
        name = (m.group(1) if m else hit).strip()
        if not name:
            continue
        code = next((t for t in tds if _CODE.search(t)), '')
        date = ''
        for t in tds:
            dm = _DATE.search(t)
            if dm:
                date = dm.group(1)
                break
        items.append({'name': name, 'code': code.strip(), 'date': date,
                      'src_url': url})
    return items


# 主体企业名 = 项目描述里第一个动作词（在/通过/与/向/收购/并购/增资）之前的部分
_OWNER_CUT = re.compile(r'^(.+?)(?=(在|通过|与|向|收购|并购|增资|认购|合资))')


def _parse_one(name, date, code, url):
    g = ZJ._find_geo(name) or ('', '')
    geo, region = g
    m = ZJ._RE_MONEY.search(name)
    usd, money_txt = None, ''
    if m:
        usd = float(m.group(1)) * ZJ._MONEY_K.get(m.group(2), 0)
        money_txt = m.group(0)
    om = _OWNER_CUT.match(name)
    owner = om.group(1).strip() if om else ''
    act = ''
    for w, a in ZJ.ACT:
        if w in name:
            act = a
            break
    return {'name': name, 'owner': owner, 'geo': geo, 'region': region,
            'act': act, 'usd': usd if usd else None, 'moneyTxt': money_txt,
            'item': '境外投资项目备案', 'dept': '安徽省发展和改革委员会',
            'deal': '已备案', 'date': date, 'code': code, 'src': '安徽省发展改革委（依申请公开目录·境外投资备案）',
            'url': url}


def main():
    quarters = list_quarters()
    print('季度目录 %d 期' % len(quarters))
    raw, seen = [], set()
    for q in quarters:
        for r in parse_quarter(q['url']):
            key = (r['name'], r['date'])
            if key in seen:
                continue
            seen.add(key)
            raw.append(r)
        time.sleep(0.5)
    items = [_parse_one(r['name'], r['date'], r['code'], r['src_url'])
             for r in raw]
    items.sort(key=lambda x: x['date'], reverse=True)
    out = {'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(items),
           'quarters': [q['title'] for q in quarters], 'items': items}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('安徽境外投资备案 %d 条 → %s' % (len(items), OUT))
    # 打几条感受一下
    for x in items[:8]:
        print('  %s %-6s %s' % (x['date'], x['geo'] or '?', x['name'][:60]))


if __name__ == '__main__':
    main()
