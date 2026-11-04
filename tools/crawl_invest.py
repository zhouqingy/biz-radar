# -*- coding: utf-8 -*-
"""投资在线审批监管平台采集（浙江 / 江苏）

════════════════════════════════════════════════════════════════════
为什么要这个源（2026-11-04 用户提出）
════════════════════════════════════════════════════════════════════
现有采集只覆盖 5 个交易中心（江苏/浙江/合肥/苏州/常州），拿的是**招标公告**。
但一个项目真正能被"提前"发现的时点，是它过审批的时候：

    项目备案 → 用地预审 → 规划许可 → 节能审查 → 环评审批 → 施工许可 → （才）招标

等招标公告出来，对手已经在里面了。审批平台给的是**招标之前 3~12 个月**的信号。

而且它带一个现有数据完全没有的字段：审批事项名称（ITEM_NAME）。
「节能审查」意味着项目要上设备、「环评审批」意味着工艺定了、「规划许可」意味着要动土——
这些是判断"该不该跟"的硬信号，不是新闻稿里的形容词。

════════════════════════════════════════════════════════════════════
两个站的差别（实测 2026-11-04）
════════════════════════════════════════════════════════════════════
浙江  tzxm.zjzwfw.gov.cn
      POST /publicannouncement.do?method=itemList
      返回 JSON，字段整齐，**无需登录、无需验证码**
      （页面源码里验证码那段 publicCheckRondom 已被注释掉）
      全库 24.6 万条，支持 item_name 关键词检索

江苏  tzxm.fzggw.jiangsu.gov.cn
      GET /portalopenPublicInformation.do?method=queryExamineAll
      返回 HTML 表格，每页 20 行，字段用正则抠
      全库 17.1 万项目

上海  tzxm.fgw.sh.gov.cn
      **只有"按项目代码查"，没有全量公示列表** → 不接（已与用户确认）

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    python3 crawl_invest.py --dry-run           # 只抓、只打印，不写文件
    python3 crawl_invest.py                     # 抓完写 raw/invest_zj.json / invest_js.json
    python3 crawl_invest.py --days 30           # 只看最近 30 天（默认 45）

⚠ 全量拉不可能（24.6 万条 × 10 条/页 = 2.46 万次请求），必须靠关键词过滤。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# 关键词按业务分层组织，方便日后按层扩缩
KW = {
    '热电联产': ['热电', '热电联产'],
    '集中供热': ['供热', '供汽', '蒸汽'],
    '余热余压': ['余热', '余压', '乏汽', '烟气回收'],
    '锅炉设备': ['锅炉', '汽轮', '发电机组'],
    '自备电厂': ['自备电厂', '自备电站', '动力站'],
    '环保治理': ['脱硫', '脱硝', '除尘', '超低排放'],
    '污水与零排': ['污水', '零排放', '中水', '废水'],
    '固废与焚烧': ['垃圾焚烧', '焚烧发电', '固废'],
    '光伏储能': ['光伏', '储能', '分布式能源'],
}
ALL_KW = sorted({k for v in KW.values() for k in v})

# 明显是噪声的事项：户籍、社保这类与工程无关的审批
NOISE_ITEM = ('身份证', '户籍', '社保', '婚姻', '驾驶证', '营业执照登记',
              '税务登记', '发票', '公积金')


def fetch_json(url, data, referer):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        'User-Agent': UA,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': referer,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def fetch_html(url, referer=''):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': referer})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'ignore')


# ══════════════════════════════════════════════════════════════════
# 浙江
# ══════════════════════════════════════════════════════════════════
ZJ_API = 'https://tzxm.zjzwfw.gov.cn/publicannouncement.do?method=itemList'
ZJ_REF = ('https://tzxm.zjzwfw.gov.cn/tzxmweb/zwtpages/resultsPublicity/'
          'notice_of_publicity_new.html?page=2')


def crawl_zj(kw, pages=3):
    """按关键词拉浙江公示。pageNo 从 0 开始，每页 10 条。"""
    out = []
    for pno in range(pages):
        try:
            j = fetch_json(ZJ_API, {
                'pageFlag': '1', 'pageNo': str(pno), 'area_code': '', 'area_flag': '1',
                'deal_code': '', 'item_name': kw,
            }, ZJ_REF)
        except Exception as e:
            print('    [浙江 %s p%d] 失败 %s' % (kw, pno, type(e).__name__))
            break
        if not j:
            break
        items = (j[0] or {}).get('itemList') or []
        if not items:
            break
        for it in items:
            item_name = (it.get('ITEM_NAME') or '').strip()
            if any(n in item_name for n in NOISE_ITEM):
                continue
            out.append({
                'prov': '浙江',
                'code': (it.get('deal_code') or '').strip(),
                'name': (it.get('apply_project_name') or '').strip(),
                'item': item_name,
                'dept': (it.get('DEPT_NAME') or '').strip(),
                'deal': (it.get('DEAL_NAME') or '').strip(),
                'date': (it.get('DEAL_TIME') or '')[:10],
                'kw': kw,
                'src': '浙江投资在线审批平台',
                'uuid': it.get('projectuuid') or '',
            })
        time.sleep(0.25)
    return out


# ══════════════════════════════════════════════════════════════════
# 江苏
# ══════════════════════════════════════════════════════════════════
JS_API = 'https://tzxm.fzggw.jiangsu.gov.cn/portalopenPublicInformation.do?method=queryExamineAll'


def fetch_js_post(kw, page=1, size=20):
    """江苏站支持 POST 表单搜索（2026-11-04 实测有效，别写成 GET）。

    踩过的坑：一开始以为它不支持关键词过滤，靠翻页拿数据 —— 实测一页 20 行、
    一天就有 300+ 条备案、命中业务关键词只有 0.3%，翻 15 页只捞到 1 条。
    后来发现页面上有两个 form，字段名就是 apply_project_name，
    用 POST 提交即可服务端过滤，每个关键词都能返回精确匹配。
    """
    d = urllib.parse.urlencode({
        'apply_project_name': kw, 'pageNo': str(page), 'pageSize': str(size),
    }).encode()
    req = urllib.request.Request(JS_API, data=d, headers={
        'User-Agent': UA,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': 'https://tzxm.fzggw.jiangsu.gov.cn/',
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'ignore')

# 江苏返回的是 HTML 表格。真实结构（2026-11-04 抓包确认，别凭猜写正则）：
#   <td ... title="[备案]2611-320684-89-01-244996扬州新旭光伏...项目">
#       [备案]2611-320684-89-01-244996<p class="full_name">扬州新旭光伏...项目</p>
#   </td>
#   <td ... title="企业投资项目备案">企业投资项目备案</td>
#   <td align="center">南通市海门区数据局</td>      ← 审批部门
#   <td align="center">南通市海门区</td>            ← 部门区划
#   <td align="center">批复</td>                    ← 审批结果
#   <td ...>苏...号</td>                            ← 批复文号
#   <td ...>2026/10/31</td>                         ← 审批时间
_JS_ROW = re.compile(
    r'\[(备案|审批|核准)\]'                          # 项目类型
    r'(\d{4}-\d{6}-\d{2}-\d{2}-\d{6})'               # 项目代码
    r'\s*<p class="full_name">([^<]{2,200})</p>'      # 项目名
    r'([\s\S]{0,900}?)'
    r'(\d{4}/\d{1,2}/\d{1,2})'                        # 审批时间
)
_JS_TD = re.compile(r'<td[^>]*>([\s\S]{0,200}?)</td>', re.I)


def crawl_js(kw, pages=3):
    """江苏站：POST 服务端搜索 + 本地再筛一遍（服务端是模糊匹配，会带出无关结果）。"""
    out = []
    for pno in range(1, pages + 1):
        try:
            h = fetch_js_post(kw, page=pno)
        except Exception as e:
            print('    [江苏 %s p%d] 失败 %s' % (kw, pno, type(e).__name__))
            break
        n0 = len(out)
        for m in _JS_ROW.finditer(h):
            kind, code, name, mid, day = (
                m.group(1), m.group(2), m.group(3), m.group(4), m.group(5))
            name = re.sub(r'<[^>]+>', '', name)
            name = re.sub(r'\s+', '', name)
            if len(name) < 4:
                continue
            tds = [re.sub(r'<[^>]+>', '', t).strip() for t in _JS_TD.findall(mid)]
            item = tds[0] if tds else ''
            dept = tds[1] if len(tds) > 1 else ''
            deal = ''
            for t in tds:
                if t in ('批复', '办结', '不予受理', '退件', '通过', '办结(通过)'):
                    deal = t
                    break
            if any(n in item for n in NOISE_ITEM):
                continue
            y, mo, d = [int(x) for x in day.split('/')]
            out.append({
                'prov': '江苏',
                'code': code,
                'name': name,
                'item': item,
                'dept': dept,
                'deal': deal or kind,
                'date': '%04d-%02d-%02d' % (y, mo, d),
                'kw': kw,
                'src': '江苏投资在线审批平台',
                'uuid': '',
            })
        if len(out) == n0:
            break
        time.sleep(0.35)
    return out


# ══════════════════════════════════════════════════════════════════
def in_days(d, days):
    if not d or not re.match(r'^\d{4}-\d{2}-\d{2}$', d):
        return False
    today = time.strftime('%Y-%m-%d')
    from datetime import date
    try:
        d0 = date.fromisoformat(d)
        d1 = date.fromisoformat(today)
    except Exception:
        return False
    return 0 <= (d1 - d0).days <= days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--days', type=int, default=45)
    ap.add_argument('--pages', type=int, default=3)
    ap.add_argument('--only', default='', help='只跑某一个省：浙江 / 江苏')
    a = ap.parse_args()

    allrows = []
    for prov, fn in (('浙江', crawl_zj), ('江苏', crawl_js)):
        if a.only and a.only != prov:
            continue
        print('== %s ==' % prov)
        seen = set()
        got = []
        for kw in ALL_KW:
            rows = fn(kw, a.pages)
            fresh = [r for r in rows if (r['code'], r['item']) not in seen]
            for r in fresh:
                seen.add((r['code'], r['item']))
            got += fresh
            if rows:
                print('  %-6s 抓到 %3d 条（去重后新 %3d）' % (kw, len(rows), len(fresh)))
        rec = [r for r in got if in_days(r['date'], a.days)]
        print('  → 合计 %d 条，其中近 %d 天 %d 条' % (len(got), a.days, len(rec)))
        allrows += got

    # 按日期倒序，方便看新鲜度
    allrows.sort(key=lambda x: x['date'] or '', reverse=True)
    print('\n总计 %d 条，最新 %s，最早 %s' % (
        len(allrows), allrows[0]['date'] if allrows else '-',
        allrows[-1]['date'] if allrows else '-'))

    # 事项分布（这是新数据源最有价值的部分）
    from collections import Counter
    print('\n审批事项 TOP12（现有数据里完全没有这个维度）：')
    for k, v in Counter(r['item'] for r in allrows if r['item']).most_common(12):
        print('  %-34s %d' % (k[:34], v))

    print('\n最近 8 条样例：')
    for r in allrows[:8]:
        print('  [%s] %s | %s | %s' % (r['date'], r['prov'], r['name'][:34], r['item'][:24]))

    if a.dry_run:
        print('\n（dry-run，未写文件）')
        return

    os.makedirs(RAW, exist_ok=True)
    for prov, fp in (('浙江', 'invest_zj.json'), ('江苏', 'invest_js.json')):
        rows = [r for r in allrows if r['prov'] == prov]
        p = os.path.join(RAW, fp)
        # 与已有文件合并去重，避免每次重建把历史冲掉
        old = []
        if os.path.exists(p):
            try:
                old = json.load(open(p, encoding='utf-8')).get('items') or []
            except Exception:
                old = []
        merged = {(r['code'], r['item'], r['date']): r for r in old}
        for r in rows:
            merged.setdefault((r['code'], r['item'], r['date']), r)
        out = sorted(merged.values(), key=lambda x: x['date'] or '', reverse=True)
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'),
                   'src': prov + '投资在线审批平台',
                   'items': out}, open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('写入 %s：%d 条（本次新增 %d）' % (fp, len(out), len(out) - len(old)))


if __name__ == '__main__':
    main()
