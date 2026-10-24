#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公告原文补全（2026-10-21）

解决两个问题：
  1) 领导问「中标单位是谁」——商机库 542 条中标类公告里只有 254 条带中标单位，
     剩下 288 条的正文里其实写着，但采集时只存了截断摘要（平均 116 字）。
  2) 领导问「该联系谁」——公告原文里带招标人/联系人/电话/地址，这些比中标单位更有用。

实测：宝华平台公告详情页可直接用无头 Chrome 渲染拿到全文（含中标人+联系人+电话）。
浙江/江苏/合肥平台有反爬，成功率低，逐条试、失败的跳过不纠缠。

输出 raw/notice_extra.json：{ 记录url: {win, contact, phone, addr, agent} }
"""
import os, re, json, time, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
DATA = os.path.join(os.path.dirname(ROOT), 'biz-radar', 'data.js')
OUT = os.path.join(RAW, 'notice_extra.json')

# 优先做这些域（实测可通的比例高）
PRIORITY = ['baohuabidding', 'ggzy.zj.gov.cn', 'ggzy.hefei.gov.cn',
            'shggzy.com', 'jsggzy', 'ahtba', 'chnenergybidding']

# 中标人
# 关键：不能只匹配到「公司|集团」就停——"中国电建集团江西省电力设计院有限公司"会被截成"中国电建集团"。
# 改为吃满到标点为止的整段，再清洗。
CORP = r'[\u4e00-\u9fa5A-Za-z0-9（）()·、\-]{4,60}'
RE_WIN = [
    re.compile(r'中标人\s*[:：]\s*(' + CORP + r')'),
    re.compile(r'中标单位\s*[:：]\s*(' + CORP + r')'),
    re.compile(r'第一中标候选人\s*[:：]?\s*(?:名称\s*[:：]\s*)?(' + CORP + r')'),
    re.compile(r'中标候选人名称\s*[:：]\s*(' + CORP + r')'),
]
# 抽出后清洗：截到第一个明显分隔符，去掉尾部的括号备注
WIN_STOP = re.compile(r'[（(]?(?:联合体|地址|地\s*址|联系人|电话|投标报价|中标价|工期|项目负责人|身份证|资格|得分)')


def tidy_corp(s):
    s = WIN_STOP.split(s)[0]
    s = re.sub(r'[，,、；;。：:\s]+$', '', s).strip()
    # 必须像公司名
    if not re.search(r'(公司|集团|院|厂|中心|研究所|大学|事务所|局)$', s):
        return ''
    if len(s) < 4 or len(s) > 50:
        return ''
    return s
RE_PHONE = re.compile(r'(?:^|[\s：:，,、；;])((?:0\d{2,3}[-\s]?\d{7,8})|(?:1[3-9]\d{9}))(?=$|[\s，,、；;。])')
RE_CONTACT = re.compile(r'联系人\s*[:：]\s*([\u4e00-\u9fa5]{2,4})')
RE_ADDR = re.compile(r'地\s*址\s*[:：]\s*([^\s。；;]{6,60})')
RE_AGENT = re.compile(r'招标代理机构\s*[:：]\s*([\u4e00-\u9fa5A-Za-z0-9（）()·、\-]{4,50}?(?:公司|中心|院))')


def html_to_text(h):
    h = re.sub(r'<script.*?</script>', ' ', h, flags=re.S)
    h = re.sub(r'<style.*?</style>', ' ', h, flags=re.S)
    h = re.sub(r'<[^>]+>', ' ', h)
    h = h.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', h)


def fetch_dom(url, timeout=45):
    """用无头 Chrome 渲染（静态 urllib 拿不到 JS 渲染的内容）"""
    try:
        r = subprocess.run(
            ['google-chrome', '--headless=new', '--disable-gpu', '--no-sandbox',
             '--virtual-time-budget=12000', '--dump-dom', url],
            capture_output=True, timeout=timeout)
        return r.stdout.decode('utf-8', 'ignore')
    except Exception:
        return ''


def parse(text):
    out = {}
    for p in RE_WIN:
        m = p.search(text)
        if m:
            nm = tidy_corp(m.group(1).strip())
            if nm:
                out['win'] = nm
                break
    m = RE_CONTACT.search(text)
    if m:
        out['contact'] = m.group(1)
    m = RE_PHONE.search(text)
    if m:
        out['phone'] = re.sub(r'^[\s：:，,、；;]+', '', m.group(0)).strip()
    m = RE_ADDR.search(text)
    if m:
        out['addr'] = m.group(1).strip()
    m = RE_AGENT.search(text)
    if m:
        out['agent'] = m.group(1).strip()
    return out


def work(x):
    url = x['url']
    h = fetch_dom(url)
    if not h or len(h) < 800:
        return url, None
    got = parse(html_to_text(h))
    return url, (got or None)


def main(limit=0):
    s = open(DATA, encoding='utf-8').read()
    D = json.loads(s[s.index('{'):s.rindex('}') + 1])
    its = D['items']

    # 目标：中标类公告且缺 win 的；加上业主/供应商关系需要的
    tgt = [x for x in its
           if x.get('url') and x['st'] in ('中标结果公示', '中标候选人公示')
           and not (x.get('win') or '').strip()]
    tgt.sort(key=lambda z: (0 if any(p in z['url'] for p in PRIORITY) else 1,
                            -(len(z.get('d') or ''))))
    if limit:
        tgt = tgt[:limit]
    print('待补全 %d 条' % len(tgt))

    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding='utf-8')).get('items', {})
    res = dict(old)

    ok = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (url, got) in enumerate(ex.map(work, tgt), 1):
            if got:
                res[url] = got
                ok += 1
            if i % 20 == 0:
                print('  进度 %d/%d，成功 %d' % (i, len(tgt), ok))

    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'items': res},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    nw = sum(1 for v in res.values() if v.get('win'))
    nc = sum(1 for v in res.values() if v.get('contact') or v.get('phone'))
    print('合计 %d 条有结果：中标单位 %d 条、联系人/电话 %d 条 → %s'
          % (len(res), nw, nc, OUT))


if __name__ == '__main__':
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    main(lim)
