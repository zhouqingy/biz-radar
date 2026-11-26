#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安徽发改委·批准结果信息主动公开（核准批复全文）采集 2026-11-26

由来（§5.117，用户点名「这个很有用啊，几乎所有的项目都会在这里备案」）
----------------------------------------------------------------
省发改委每季度的「依申请公开信息目录」（crawl_odi_ah.py 抓的那个大表）里
除了境外投资备案，还有大量境内项目的**核准批复/节能审查意见**目录行 ——
但目录表本身不带原文链接（依申请公开，只列条目）。

溯源路径（2026-11-26 实测打通）：
  同一批批复在省发改委「批准结果信息 → 企业投资项目核准」栏目有**主动公开全文页**：
    列表接口（要带 Referer，否则「系统繁忙」）：
      /site/label/8888?labelName=publicInfoList&siteId=49631471&organId=7011
        &pageSize=50&pageIndex=N&type=4&action=list&isJson=true&isRel=true
        &catId=49945391
    详情正文（amdManage 数据库，按 id）：
      /site/tpl/1034671121?id=NNNN
      或文章页 /public/7011/<contentId>.html（列表直接给 link）
  实测 404 条核准批复里主业粗筛命中 62 条：马钢南区/北区余热发电、
  南区三期煤气发电、铜陵有色金冠铜业三期余热发电、福耀纯低温余热发电、
  旋力特钢余热发电…… 全是主业直接命中。

口径（对齐 pick_odi 的分层思路，但这里是境内核准）：
  S 收：余热/余压/煤气发电/热电联产/背压/锅炉/焚烧发电/生物质发电/
        自备电厂/燃机/汽轮/储能/光伏电站/垃圾发电
  A 收：客户行业（钢铁/焦化/干熄/烧结/高炉/冶炼/化工/水泥/玻璃/造纸）
        的节能审查意见/节能报告 —— 厂里必然配套我们的系统
  X 不收：纯风电核准（非我们交付）、煤矿安全检测、机构资质变更、
        节能调度资金、产教融合基地等
去重：与 raw/early/ 全部既有条目按「标题前 22 字」比对，防重复入库。
"""
import json
import os
import re
import time
import urllib.request
import urllib.parse

from preflight import require_briefing          # 开工必读校验
require_briefing('crawl_ah_result.py')

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'raw', 'early', 'ah-fgw-result.json')
SITE = 'https://fzggw.ah.gov.cn'
HDR = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
}

# 栏目 → (catId, early 标记)
CATS = [
    (49945391, '核准批复', '企业投资项目核准'),
    (49945401, '节能审查', '节能审查'),
]

# ── S：工程本体是我们的活 ─────────────────────────────────────────────
S_W = ('余热', '余压', '煤气发电', '热电联产', '背压', '垃圾焚烧发电', '焚烧发电',
       '生物质发电', '自备电厂', '自备电站', '燃机', '汽轮', '发电机组',
       '储能', '光伏电站', '集中供热', '热网', '锅炉')
# ── A：客户行业扩产/节能审查，厂里必配我们的系统 ──────────────────────
A_W = ('钢铁', '特钢', '焦化', '干熄', '烧结', '高炉', '转炉', '电炉', '冶炼',
       '不锈钢', '轧', '水泥', '熟料', '玻璃', '造纸', '化工', '化纤', '炼化',
       '电解铝', '铜业', '镍', '铁合金')
# ── X：明确不收 ──────────────────────────────────────────────────────
X_W = ('风电', '风电场', '煤矿安全', '检测检验机构', '资质变更', '节能发电调度',
       '专项补助', '产教融合', '实训基地', '学院', '学校', '医院', '宿舍')


def _list_page(cat_id, pi, ps=50):
    u = (SITE + '/site/label/8888?_=0.618&labelName=publicInfoList&siteId=49631471'
         '&organId=7011&pageSize=%d&pageIndex=%d&isDate=true&dateFormat=yyyy-MM-dd'
         '&length=50&type=4&action=list&result=&isJson=true&keyWords=&isRel=true'
         '&catIds=&catId=%d' % (ps, pi, cat_id))
    req = urllib.request.Request(u, headers=dict(HDR, **{
        'Referer': SITE + '/public/column/7011?type=4&catId=%d&action=list' % cat_id}))
    for i in range(3):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=30).read()
                           .decode('utf-8', 'ignore'))
            return d if isinstance(d, list) else d.get('data') or []
        except Exception:
            if i == 2:
                return []
            time.sleep(1.5)
    return []


def judge(t):
    """返回 (tier, why)。t=标题"""
    n = t or ''
    if any(w in n for w in X_W) and not any(w in n for w in S_W):
        # 「XX风电+余热」之类少见，先救 S
        return None, ''
    if any(w in n for w in S_W):
        return 'S', '工程含：' + '/'.join([w for w in S_W if w in n][:3])
    if any(w in n for w in A_W):
        return 'A', '客户行业：' + '/'.join([w for w in A_W if w in n][:3])
    return None, ''


_CODE_RE = None  # 占位防误删


def _detail_snip(url, title):
    """抓详情页正文，取文号 + 一句核心内容（不点开也能看懂）。"""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': HDR['User-Agent']})
        html = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')
    except Exception:
        return ''
    txt = re.sub(r'<[^>]+>', ' ', html)
    txt = re.sub(r'\s+', ' ', txt)
    m = re.search(r'(皖[^ ]{0,6}[〔].{1,12}[〕]\s*\d+\s*号)', txt)
    code = m.group(1) if m else ''
    # 找正文句：优先「同意…」
    sent = ''
    for pat in [r'(同意[^。；\n]{10,120}。)', r'(建设规模[^。；\n]{5,110}。)',
                r'(项目[^。；\n]{20,120}。)']:
        mm = re.search(pat, txt)
        if mm:
            sent = mm.group(1).strip()
            break
    bits = []
    if code:
        bits.append('文号' + code)
    if sent:
        bits.append(sent)
    return '；'.join(bits)[:220]


def load_seen():
    """与 raw/early/ 全部既有条目去重（标题前 22 字 + url）。"""
    seen = set()
    d = os.path.join(ROOT, 'raw', 'early')
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if not fn.endswith('.json') or fn == os.path.basename(OUT):
                continue   # 自己上一轮的产物不参与去重（幂等重跑）
            try:
                arr = json.load(open(os.path.join(d, fn), encoding='utf-8'))
            except Exception:
                continue
            for x in arr if isinstance(arr, list) else []:
                t = (x.get('t') or '')[:22]
                if t:
                    seen.add(t)
                if x.get('url'):
                    seen.add(x['url'])
    return seen


def main():
    seen = load_seen()
    out, scanned = [], 0
    for cat_id, early, cname in CATS:
        pi, empty_streak = 1, 0
        while empty_streak < 2 and pi <= 40:
            items = _list_page(cat_id, pi)
            if not items:
                empty_streak += 1
                pi += 1
                continue
            empty_streak = 0
            for it in items:
                scanned += 1
                t = (it.get('title') or '').strip()
                if not t:
                    continue
                tier, why = judge(t)
                if not tier:
                    continue
                key22 = t[:22]
                if key22 in seen:
                    continue
                url = it.get('link') or ''
                if url and url in seen:
                    continue
                seen.add(key22)
                if url:
                    seen.add(url)
                snip = ''
                if url:
                    snip = _detail_snip(url, t)
                out.append({
                    't': t, 'rg': '安徽', 'early': early,
                    'd': (it.get('publishDate') or '')[:10],
                    'url': url,
                    'src': '安徽省发改委·批准结果信息（%s）' % cname,
                    'tier': tier, 'why': why,
                    'snip': snip or ('安徽省发改委%s（主动公开），详见原文。' % ('核准批复' if early == '核准批复' else '节能审查意见')),
                })
            pi += 1
            time.sleep(0.6)
    out.sort(key=lambda x: x.get('d') or '', reverse=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    ns = sum(1 for x in out if x['tier'] == 'S')
    print('扫描 %d 条 → 主业相关 %d 条（S %d / A %d）→ %s'
          % (scanned, len(out), ns, len(out) - ns, OUT))
    for x in out[:12]:
        print('  %s [%s] %s' % (x['d'], x['tier'], x['t'][:62]))


if __name__ == '__main__':
    main()
