#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞对业绩挖掘 V2 · mine_perf2.py
==============================
V1（mine_perf.py）走的是「遍历列表页 → 逐条抓详情页」的路子，问题是：
  · 市级交易中心是全行业，命中率低（67 条里主业 0 条）
  · 翻页深，噪音大

V2 换思路：**按公司名反查**。
  已知要盯哪几家竞对（中国联合工程、江苏院、河北院……），
  直接用它们的名字去搜公示，只抓命中的那几条。
  → 命中率从 15% 拉到接近 100%，抓取量降低两个数量级。

两种页面都能吃：
  ① 标准版：业绩表是真正的 <table id="Table1.2">，td 齐全（南通原站）
  ② 压平版：第三方转载把整表拍进一个 td，只剩纯文本（电力项目网等）
     靠「日期 00:00:00 + 金额」做锚点反切，建设单位靠后缀匹配回推

用法：
  python3 mine_perf2.py --target 中国联合工程有限公司
  python3 mine_perf2.py --target 中国联合工程有限公司 --pages 30
  python3 mine_perf2.py --report
"""
import argparse
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

# 南通站（2026-10-21 更正：真正可用的域名是 zfcg.nantong.gov.cn）
#
# 栏目号对照（实测）：
#   003001004  老的「中标候选人公示」—— 仍可翻页，但是旧结构，业绩表 id=Table1.2
#   003001005  定标结果公示
#   003001006  中标结果公告
#   003001007  未入围 / 定标结果
#   003001008  合同公告
#   003001009  招标计划
NT = {
    'host': 'https://zfcg.nantong.gov.cn',
    'cand': '003001004',          # 中标候选人公示（含业绩表）
}


def sh(cmd, timeout=90):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception:
        return ''


def fetch(url, timeout=30):
    return sh(['curl', '-sS', '--max-time', str(timeout), '-A', UA, '-k', '-L', url], timeout + 15)


def clean(t):
    t = re.sub(r'<[^>]+>', '', t)
    t = t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', t).strip()


CELL = re.compile(r'<td([^>]*)>(.*?)</td>', re.S)
AMT_RE = re.compile(r'([\d,]+(?:\.\d+)?)\s*(万元|亿元|元)')


def parse_amt(txt):
    """'66083.374万元' -> 6.608337（亿）；统一按亿元存。"""
    m = AMT_RE.search(txt or '')
    if not m:
        return None
    try:
        v = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    u = m.group(2)
    if u == '亿元':
        return round(v, 4)
    if u == '万元':
        return round(v / 10000, 6)
    return round(v / 1e8, 8)


# ---------------------------------------------------------------- 标准版表格
def parse_table(html):
    """业绩表是真 <table> 且 td 齐全的情况（南通原站）。"""
    i = html.find("id='Table1.2'")
    if i < 0:
        i = html.find('id="Table1.2"')
    if i < 0:
        return []
    seg = html[i:html.find('</table>', i)]
    out, cur, left = [], None, 0
    for r in re.findall(r'<tr[^>]*>(.*?)</tr>', seg, re.S):
        tds = CELL.findall(r)
        vals = [clean(c) for a, c in tds]
        if not vals:
            continue
        if vals[0] in ('单位名称', '中标候选人名称') or (
                len(vals) >= 2 and vals[1] in ('工程名称', '项目名称')):
            continue
        if 'rowspan' in tds[0][0]:
            m = re.search(r"rowspan=['\"]?(\d+)", tds[0][0])
            left = int(m.group(1)) if m else 1
            cur, rest = vals[0], vals[1:]
        else:
            rest = vals
            left = max(0, left - 1)
        if not cur or len(rest) < 4:
            continue
        proj, owner, when, amt = rest[0], rest[1], rest[2], rest[3]
        if not proj or proj in ('/', '—', '-', '无'):
            continue
        out.append({'unit': cur, 'proj': proj, 'owner': owner, 'date': when[:10], 'amt_txt': amt})
    return out


# ---------------------------------------------------------------- 压平版正文
# 第三方转载（电力项目网 / 各类聚合站）会把整张表拍进一个 <td>，标签全丢，只剩连着的文字：
#   单位名称工程名称建设单位中标时间中标金额中国联合工程有限公司玉林白平产业园热电联产一期项目EPC工程 \
#   玉林时代聚能热力能源有限公司2021-12-27 00:00:0066083.374万元广西田东锦盛化工有限公司电厂扩建工程...
# 没法靠 td 分列，只能：
#   1) 用「日期 00:00:00 + 金额」做锚点，锚点前的尾串就是建设单位
#   2) 建设单位靠后缀词回推（有限公司/有限责任公司/股份有限公司/集团/厂/公司…）
#   3) 锚点前剩余的部分，上一行金额之后那段 = 工程名称
#
# 关键坑：建设单位名后面紧跟工程名，中间没有分隔符，必须靠后缀回推。
# 但直接匹配「厂」会把「3×350t/h+2×40MW热电联产项目一期（1炉1机）项目河南平煤神马聚碳材料有限责任公司」
# 从 "40MW" 后面的某个字符错切。所以：
#   · 后缀只认「股份有限公司/有限责任公司/有限公司/集团公司/集团/公司/电厂/厂」
#   · 且整段必须至少 4 个汉字，不含 × / t/h / MW / 数字单位 这类工程痕迹
OWNER_SUF = re.compile(
    r'([\u4e00-\u9fa5（）()A-Za-z0-9·]{2,44}?'
    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|集团|公司|热电厂|电厂|厂))$')
# 从右端锚定：结尾必须是公司/厂类后缀，左侧最多再回溯 14 个公司名字符
#   ← 不能用 [....]{4,44}$ 这种写法：它会从行首一路贪吃到行尾，把整个工程名当成公司名
NAME_RE = re.compile(
    r'[\u4e00-\u9fa5（）()A-Za-z0-9·]{2,14}?'
    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|集团|公司|热电厂|电厂|厂)$')
# 含这些字符说明不是公司名，是工程描述
BAD_OWNER = re.compile(r'[×xX]|\d+\s*(?:t/h|MW|万千瓦|千瓦|台|套|炉|机|期|标段)|工程|项目|勘察|设计|施工|总承包|采购')
ANCH = re.compile(r'(\d{4}-\d{2}-\d{2})\s*\d{2}:\d{2}:\d{2}\s*([\d.,]+)(万元|亿元|元)')


def flat_text(html, start_kw='中标候选人企业业绩', stop_kws=('项目经理业绩',)):
    i = html.find(start_kw)
    if i < 0:
        return ''
    j = len(html)
    for k in stop_kws:
        p = html.find(k, i + len(start_kw))
        if p > 0:
            j = min(j, p)
    seg = html[i:j]
    seg = re.sub(r'<br\s*/?>', '\n', seg)
    seg = re.sub(r'<[^>]+>', '', seg)
    seg = seg.replace('&nbsp;', ' ').replace('&amp;', '&')
    seg = re.sub(r'\s+', '', seg)
    seg = seg.replace('单位名称工程名称建设单位中标时间中标金额', '')
    seg = seg.replace('单位名称工程名称建设单位中标时间中标金额（万元）', '')
    return seg


# ---- 一条业绩的切分 ----
#
# 原文（整张表被拍平成一个字符串）：
#   中国联合工程有限公司玉林白平产业园热电联产一期项目EPC工程玉林时代聚能热力能源有限公司2021-12-27 00:00:00 66083.374万元
#                      └──────────── 工程名 ────────────┘└──── 建设单位 ────┘
#
# 难点：工程名里也常含「公司」（如「广西田东锦盛化工有限公司电厂扩建工程」），
#       所以正则里让「工程名尽量短」，反而会把建设单位前半截抢走。
#
# 正解：**从日期往前倒着扫**，用"最长合法公司名"确定建设单位起点。
#       建设单位最右，所以从日期左边界开始，向前扩到最长仍合法的位置。
DATE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})(\d{2}:\d{2}:\d{2})([\d.,]+)(万元|亿元|元)')
SUF = re.compile(r'(?:股份有限公司|有限责任公司|有限公司|集团公司|集团|公司|热电厂|电厂|厂|院)$')
NAME_CH = re.compile(r'[\u4e00-\u9fa5（）()A-Za-z0-9·]+')


# ---- 建设单位词表 ----
# 工程名和建设单位在压平文本里是**直接粘在一起**的，中间没有任何分隔符：
#   「玉林白平产业园热电联产一期项目EPC工程」+「玉林时代聚能热力能源有限公司」
# 纯靠字面规则切，永远会在「程玉林时代…」和「玉林时代…」之间摇摆——
# 因为「程玉林时代聚能热力能源有限公司」本身也是个语法合法的公司名。
#
# 唯一的解：**用已知建设单位词表做最长匹配**。
# 词表来源：
#   1) 标准版表格（真 <table>）直接解析出的 owner，100% 准确，反哺词表
#   2) 南通站中标结果公告里的「招标人名称」
#   3) 已挖掘到的历史业主
# 词表覆盖不到的，才退回字面规则并打 low 标记，供人工复核。
KNOWN_OWNERS = set()
OWNER_TXT = os.path.join(RAW, 'owner_dict.txt')


def load_owners():
    global KNOWN_OWNERS
    KNOWN_OWNERS = set()
    if os.path.exists(OWNER_TXT):
        for ln in open(OWNER_TXT, encoding='utf-8'):
            ln = ln.strip()
            if ln and not ln.startswith('#'):
                KNOWN_OWNERS.add(ln)


def save_owners(new_ones):
    old = set()
    if os.path.exists(OWNER_TXT):
        old = {ln.strip() for ln in open(OWNER_TXT, encoding='utf-8') if ln.strip()}
    allset = sorted(old | set(new_ones))
    with open(OWNER_TXT, 'w', encoding='utf-8') as f:
        f.write('# 建设单位词表（mine_perf2.py 自动积累，可手工增补）\n')
        for x in allset:
            f.write(x + '\n')


def cut_record(head):
    """
    head = 上一条金额之后 → 本条日期之前。
    返回 (工程名, 建设单位, 置信度)。
    """
    head = head.strip()
    if not head:
        return '', '', 'low'

    # ① 词表最长匹配（从右端找，命中即止）
    hit = None
    for nm in KNOWN_OWNERS:
        if head.endswith(nm) and len(head) > len(nm):
            if hit is None or len(nm) > len(hit):
                hit = nm
    if hit:
        return head[:len(head) - len(hit)], hit, 'dict'

    # ② 字面规则兜底
    if not SUF.search(head):
        return head, '', 'low'
    n = len(head)
    best = None
    for L in range(3, min(30, n) + 1):
        seg = head[n - L:]
        if not NAME_CH.fullmatch(seg):
            continue
        if not SUF.search(seg):
            continue
        if len(re.findall(r'[\u4e00-\u9fa5]', seg)) < 4:
            continue
        if BAD_OWNER.search(seg):
            continue
        if n - L < 4:
            continue
        best = seg
    if not best:
        return head, '', 'low'
    return head[:n - len(best)], best, 'rule'


def parse_flat(txt, units):
    """
    从压平文本里切业绩。单位名只在每块第一条前出现一次，按出现位置分块归属。
    """
    if not txt:
        return []
    marks = sorted((txt.find(u), u) for u in units if txt.find(u) >= 0)
    if not marks:
        return []

    def unit_at(pos):
        cur = marks[0][1]
        for p, u in marks:
            if p <= pos:
                cur = u
            else:
                break
        return cur

    out = []
    prev = marks[0][0]
    for m in DATE_RE.finditer(txt):
        head = txt[prev:m.start()]
        proj, owner, conf = cut_record(head)
        # 剥掉块首粘连的单位名
        for p, u in marks:
            if proj.startswith(u) and len(proj) > len(u) + 4:
                proj = proj[len(u):]
                break
        proj = re.sub(r'^(?:中标候选人企业业绩|单位名称|工程名称|建设单位|中标时间|中标金额)+', '', proj)
        proj = proj.strip()
        if len(proj) >= 4:
            out.append({
                'unit': unit_at(m.start()),
                'proj': proj,
                'owner': owner,
                'date': m.group(1),
                'amt_txt': m.group(3) + m.group(4),
                'conf': conf,
            })
        prev = m.end()
    return out


# ---------------------------------------------------------------- 站内全文检索
# 这是**最正确的入口**。翻列表页是错的路子：
#   · 南通市区的「中标候选人公示」一天就好几条，翻到 4 月要翻 100+ 页
#   · 位置还不固定，热电联产那条在第 12 页以后
# 站内全文检索一次就能拿到全部命中，还带 linkurl / webdate / 摘要。
#
# 接口是 epoint 智能检索（ES），POST JSON：
#   注意 wd 字段在 JS 里被 encodeURIComponent 过一次，所以传进来的中文要预先 URL 编码。
SEARCH_API = 'https://zfcg.nantong.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew'
SEARCH_REF = 'https://zfcg.nantong.gov.cn/search/fullsearch.html'


def nt_search(wd, page=0, size=50):
    import urllib.parse
    body = {
        "token": "", "pn": page * size, "rn": size, "sdt": "", "edt": "",
        "wd": urllib.parse.quote(wd), "inc_wd": "", "exc_wd": "",
        "fields": "title;content", "cnum": "001", "sort": '{"webdate":"0"}',
        "ssort": "title", "cl": 100, "terminal": "", "condition": [], "time": "",
        "highlights": "", "statistics": "", "unionCondition": "", "accuracy": "",
        "noParticiple": "0", "searchRange": "",
    }
    cmd = ['curl', '-sS', '-k', '-A', UA, '--max-time', '40', '-X', 'POST',
           '-H', 'Content-Type: application/json;charset=UTF-8', '-e', SEARCH_REF,
           '--data-binary', json.dumps(body, ensure_ascii=False), SEARCH_API]
    r = sh(cmd, 60)
    try:
        d = json.loads(r)
        return d.get('result') or {'totalcount': 0, 'records': []}
    except Exception:
        return {'totalcount': 0, 'records': []}


def nt_search_all(wd, cap=300):
    """翻完所有命中（默认上限 300 条，避免被限流）。"""
    out, page, total = [], 0, None
    while True:
        r = nt_search(wd, page)
        recs = r.get('records') or []
        if total is None:
            total = int(r.get('totalcount') or 0)
        if not recs:
            break
        out.extend(recs)
        page += 1
        if len(out) >= min(total, cap) or page > 30:
            break
        time.sleep(0.4)
    return out, total


# ---------------------------------------------------------------- 列表翻页
def nt_list(cat, p):
    """南通站分页：第 1 页 tradeInfo.html，2-8 页 /{N}.html，9 页起 pageIndex。"""
    if p <= 1:
        return '%s/jyxx/003001/%s/tradeInfo.html' % (NT['host'], cat)
    if p <= 8:
        return '%s/jyxx/003001/%s/%d.html' % (NT['host'], cat, p)
    return '%s/jyxx/003001/%s/tradeInfo.html?categoryNum=%s&pageIndex=%d' % (
        NT['host'], cat, cat, p)


ITEM = {}


def nt_items(html, cat):
    pat = re.compile(r'href="(/jyxx/003001/%s/\d{8}/[0-9a-f-]{36}\.html)"[^>]*>([\s\S]{0,120}?)</a>' % cat)
    out = []
    for u, t in pat.findall(html):
        out.append({'url': NT['host'] + u, 'title': clean(t)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='中国联合工程有限公司',
                    help='要盯的投标单位名，多个用英文逗号分隔')
    ap.add_argument('--kw', default='',
                    help='额外检索关键词（逗号分隔），不填就只用目标单位名')
    ap.add_argument('--cap', type=int, default=300, help='每个关键词最多翻多少条检索结果')
    ap.add_argument('--out', default='')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--sleep', type=float, default=0.5)
    args = ap.parse_args()

    targets = [x.strip() for x in args.target.split(',') if x.strip()]
    kws = [x.strip() for x in args.kw.split(',') if x.strip()] or targets
    load_owners()
    out_path = args.out or os.path.join(RAW, 'perf_dlgc.json')

    if args.report:
        return report(out_path)

    store = {'target': targets, 'updated': time.strftime('%Y-%m-%d %H:%M'),
             'items': [], 'docs': [], 'search': []}
    if os.path.exists(out_path):
        try:
            old = json.load(open(out_path, encoding='utf-8'))
            store['items'] = old.get('items', [])
            store['docs'] = old.get('docs', [])
            store['search'] = old.get('search', [])
        except Exception:
            pass
    have = {(x['unit'], x['proj'], x['date']) for x in store['items']}
    seen_doc = {d['url'] for d in store['docs']}

    # ---- 1) 站内检索，汇总所有候选公示 ----
    cand = {}
    for kw in kws:
        recs, total = nt_search_all(kw, args.cap)
        print('[检索] %-14s 命中 %s 条，取回 %d 条' % (kw, total, len(recs)))
        store['search'].append({'kw': kw, 'total': total, 'taken': len(recs)})
        for r in recs:
            u = r.get('linkurl') or ''
            if not u:
                continue
            t0 = r.get('title') or ''
            # 检索是全文模糊匹配，会带出大量无关公告
            # 真正可能有业绩表的只有这几类标题，先粗筛一刀
            if not any(k in t0 for k in ('中标候选人', '中标结果', '定标结果')):
                continue
            cand[u] = {
                'url': NT['host'] + u if u.startswith('/') else u,
                'title': re.sub(r'^\[新\]', '', r.get('title') or '').strip(),
                'date': (r.get('webdate') or '')[:10],
                'cat': r.get('categorynum') or '',
            }
        time.sleep(0.6)

    print('[汇总] 候选公示 %d 篇（去重后）' % len(cand))

    # ---- 2) 逐篇抓详情，解析业绩表 ----
    n_doc = n_hit = n_new = 0
    for u, it in cand.items():
        if u in seen_doc:
            continue
        dh = fetch(it['url'], 30)      # 注意：u 是相对路径，要用 it['url'] 拼全
        if not dh:
            continue
        n_doc += 1
        seen_doc.add(u)
        if not any(t in dh for t in targets):
            time.sleep(0.2)
            continue
        n_hit += 1
        # 标准版优先
        rows = parse_table(dh)
        src = 'table'
        if not rows:
            present = [t for t in targets if t in dh]
            others = re.findall(
                r'([\u4e00-\u9fa5（）()]{4,30}?(?:设计研究院有限公司|设计院有限公司|工程有限公司|有限公司))', dh)
            uniq = list(dict.fromkeys(present + others))
            rows = parse_flat(flat_text(dh), uniq)
            src = 'flat'
        got = 0
        for x in rows:
            if x['unit'] not in targets:
                continue
            key = (x['unit'], x['proj'], x['date'])
            if key in have:
                continue
            have.add(key)
            x['amt'] = parse_amt(x['amt_txt'])
            x['src'] = u
            x['doc'] = it['title'][:120]
            x['docdate'] = it['date']
            x['parse'] = src
            x.setdefault('conf', 'table' if src == 'table' else 'rule')
            store['items'].append(x)
            n_new += 1
            got += 1
        store['docs'].append({'url': u, 'title': it['title'][:120], 'date': it['date'],
                              'hit': got, 'parse': src})
        if got:
            print('  +%-2d %s %s' % (got, it['date'], it['title'][:52]))
        time.sleep(0.3)

    # 把新发现的建设单位并入词表
    new_owners = {x['owner'] for x in store['items']
                  if x.get('owner') and x.get('conf') in ('table', 'dict')}
    if new_owners:
        save_owners({o.strip() for o in new_owners
                     if o.endswith('公司') or o.endswith('厂') or o.endswith('院')})

    os.makedirs(RAW, exist_ok=True)
    store['updated'] = time.strftime('%Y-%m-%d %H:%M')
    json.dump(store, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n详情页 %d · 命中公示 %d · 新增业绩 %d · 累计 %d → %s'
          % (n_doc, n_hit, n_new, len(store['items']), out_path))
    report(out_path)


def report(path):
    if not os.path.exists(path):
        print('无数据')
        return
    d = json.load(open(path, encoding='utf-8'))
    it = d['items']
    print('\n' + '=' * 66)
    print('竞对业绩画像 · %s · 更新 %s' % ('、'.join(d.get('target', [])), d.get('updated')))
    print('=' * 66)
    print('业绩 %d 条 · 覆盖公示 %d 篇 · 业主 %d 家'
          % (len(it), len(d.get('docs', [])), len({x['owner'] for x in it if x['owner']})))
    by = defaultdict(list)
    for x in it:
        by[x['unit']].append(x)
    for u, xs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        amts = [x['amt'] for x in xs if x.get('amt')]
        print('\n【%s】%d 条 · 合计 %.2f 亿 · 均 %.0f 万'
              % (u, len(xs), sum(amts), (sum(amts) / len(amts) * 10000) if amts else 0))
        for x in sorted(xs, key=lambda a: a['date'], reverse=True):
            print('  %s | %-52s | %-26s | %s'
                  % (x['date'], x['proj'][:52], x['owner'][:26], x['amt_txt']))


if __name__ == '__main__':
    main()
