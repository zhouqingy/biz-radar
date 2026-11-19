#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资项目在线审批监管平台（tzxm）办结公示采集器 → raw/early/zj-tzxm-<date>.json / js-tzxm-<date>.json

为什么做这个（2026-11-19 用户拍板「1、2、3做」）：
  在线审批监管平台的「办结公示」比招标公告早 3~12 个月——项目备案/核准/节能审查
  一办结，说明业主拿地立项已定，马上要进入 EPC 招标阶段。浙江（tzxm.zjzwfw.gov.cn）
  是全国数据量最大的省级平台，江苏（tzxm.fzggw.jiangsu.gov.cn）备案公示同步更新。
  2026-11-19 实测两省公开接口均免登录。

信源与接口（2026-11-19 实测）：
  浙江  POST https://tzxm.zjzwfw.gov.cn/publicannouncement.do?method=itemList
        参数 pageFlag=&pageNo=&area_code=&area_flag=&deal_code=&item_name=<关键词>&Txtidcode=
        返回 [{"counts": 总条数, "itemList": [{deal_code, apply_project_name, ITEM_NAME,
                DEAL_NAME, DEPT_NAME, DEAL_TIME, projectuuid, SENDID}]}]，按办理时间倒序
  江苏  GET  https://tzxm.fzggw.jiangsu.gov.cn/portalopenPublicInformation.do?method=querybeianExamineAll
        参数 pageSize=50&pageNo=1&apply_project_name=<关键词>&region=
        返回 HTML 表格（项目代码/名称、备案机关、备案证号、备案时间）

关键词：一律从 collect_v4.KW_ALL 取（开工必读硬约束：不另写关键词）。
入库过滤：is_noise + biz_rules.semantic_drop（与采集端同一份规则）。
用法：
  python3 tzxm_approve.py          # 两省都抓，落盘
  python3 tzxm_approve.py --dry    # 只打印不落盘
  python3 tzxm_approve.py --days 30        # 回看窗口（默认 30 天）
  python3 tzxm_approve.py --only zj        # 只抓浙江
  python3 tzxm_approve.py --maxpage 6      # 每个关键词最多翻几页
"""
import os, re, sys, json, time, html as _html
import urllib.request, urllib.parse
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
RAW = os.path.join(ROOT, 'raw')
EARLY_DIR = os.path.join(RAW, 'early')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

from collect_v4 import KW_ALL, is_noise          # 唯一关键词源 + 噪声词表
import biz_rules as BR                            # 唯一规则源：semantic_drop

# ── 浙江：只认「立项前的审批事项」，其他（跨越许可/竣工验收/消防备案）不要 ──
ITEM_ALLOW_RE = re.compile(
    r'项目备案|项目核准|节能审查|环境影响报告|水土保持方案审批')
# 技改备案距招标更近 → 走「技改备案」渠道（招标计划档），其余走「在线审批」（立项公示档）
TECH_RE = re.compile(r'技术改造|技改')

def http(url, data=None, timeout=25, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data if data is None else urllib.parse.urlencode(data).encode(),
                                         headers={'User-Agent': UA, 'Referer': url.split('?')[0]})
            return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')
        except Exception as e:
            last = e; time.sleep(1.0 + i)
    raise last

# ──────────────────────────── 浙江 ────────────────────────────
ZJ_URL = 'https://tzxm.zjzwfw.gov.cn/publicannouncement.do?method=itemList'
ZJ_LIST_URL = ('https://tzxm.zjzwfw.gov.cn/tzxmweb/zwtpages/resultsPublicity/'
               'notice_of_publicity_new.html')

def fetch_zj(kw, cutoff, maxpage):
    """返回该关键词近 cutoff 天内的办结公示条目（按页翻到过界即停）。"""
    out = []
    for page in range(1, maxpage + 1):
        raw = http(ZJ_URL, data={'pageFlag': '', 'pageNo': page, 'area_code': '',
                                 'area_flag': '', 'deal_code': '', 'item_name': kw,
                                 'Txtidcode': ''})
        try:
            arr = json.loads(raw)
            rows = (arr[0] or {}).get('itemList') or []
        except Exception:
            rows = []
        if not rows: break
        stop = False
        for r in rows:
            d = (r.get('DEAL_TIME') or '')[:10]
            if d < cutoff: stop = True; continue
            name = (r.get('apply_project_name') or '').strip()
            item = (r.get('ITEM_NAME') or '').strip()
            if not name or not ITEM_ALLOW_RE.search(item): continue
            out.append({'t': name, 'rg': '浙江', 'city': '', 'buyer': '', 'amt': None,
                        'amtTxt': '', 'd': d, 'dl': '',
                        'p': '浙江省投资项目在线审批监管平台 办结公示（%s · %s）'
                             % (item, (r.get('DEPT_NAME') or '').strip()),
                        'url': ZJ_LIST_URL,
                        'snip': '项目代码 %s；审批事项：%s；办理结果：%s；办结部门：%s；办结时间：%s。'
                                % (r.get('deal_code') or '-', item,
                                   r.get('DEAL_NAME') or '-', r.get('DEPT_NAME') or '-', d),
                        'mode': '',
                        'early': '在线审批技改' if TECH_RE.search(item) else '在线审批',
                        'expect': ''})
        if stop: break
        time.sleep(0.25)
    return out

# ──────────────────────────── 江苏 ────────────────────────────
JS_URL = 'https://tzxm.fzggw.jiangsu.gov.cn/portalopenPublicInformation.do'
JS_ROW = re.compile(r'<td width="240"[^>]*title="([^"]*)".*?<p class="full_name">(.*?)</p>.*?'
                    r'<td width="160"[^>]*title="([^"]*)".*?'
                    r'<td width="150"[^>]*>(.*?)</td>.*?'
                    r'<td width="100"[^>]*>(.*?)</td>', re.S)

def fetch_js(kw, cutoff, maxpage):
    out = []
    for page in range(1, maxpage + 1):
        q = urllib.parse.urlencode({'method': 'querybeianExamineAll', 'pageSize': '50',
                                    'pageNo': str(page), 'apply_project_name': kw,
                                    'region': ''})
        s = http(JS_URL + '?' + q, timeout=40)
        rows = JS_ROW.findall(s)
        if not rows: break
        stop = False
        for code, name_html, org, cert, d in rows:
            name = _html.unescape(re.sub(r'<[^>]+>', '', name_html)).strip()
            d = d.strip().replace('/', '-')
            code = _html.unescape(code).strip().replace(name, '').strip()
            if d < cutoff: stop = True; continue
            cert = _html.unescape(re.sub(r'<[^>]+>', '', cert)).strip()
            org = _html.unescape(org).strip()
            if not name: continue
            out.append({'t': name, 'rg': '江苏', 'city': '', 'buyer': '', 'amt': None,
                        'amtTxt': '', 'd': d, 'dl': '',
                        'p': '江苏省投资项目在线审批监管平台 备案/审查公示（%s %s）' % (org, cert),
                        'url': JS_URL + '?' + q,
                        'snip': '项目代码 %s；备案机关 %s；证号 %s；备案时间 %s。备案已完成、'
                                '尚未进入招标阶段。' % (code, org, cert, d),
                        'mode': '',
                        'early': '技改备案' if ('技' in cert or '技' in kw) else '在线审批',
                        'expect': ''})
        if stop: break
        time.sleep(0.25)
    return out

# ──────────────────────────── 主流程 ────────────────────────────
def clean(rows):
    """与采集端同一份过滤：噪声词 + semantic_drop（硬过滤）。"""
    out, dropped = [], 0
    for x in rows:
        t = x['t']
        if is_noise(t): dropped += 1; continue
        try:
            if not BR.semantic_drop(t, x.get('snip') or ''):
                dropped += 1; continue
        except Exception:
            pass
        out.append(x)
    return out, dropped

def dedup(rows):
    seen, out = set(), []
    for x in rows:
        k = (x['t'], x['d'])
        if k in seen: continue
        seen.add(k); out.append(x)
    return out

def main():
    dry = '--dry' in sys.argv
    days = 30
    if '--days' in sys.argv: days = int(sys.argv[sys.argv.index('--days') + 1])
    maxpage = 5
    if '--maxpage' in sys.argv: maxpage = int(sys.argv[sys.argv.index('--maxpage') + 1])
    only = ''
    if '--only' in sys.argv: only = sys.argv[sys.argv.index('--only') + 1]
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    today = datetime.now().strftime('%Y-%m-%d')
    print('在线审批公示采集：窗口 %d 天（%s 起），关键词 %d 个' % (days, cutoff, len(KW_ALL)))

    all_rows = []
    if only in ('', 'zj'):
        zj = []
        for kw in KW_ALL:
            try: r = fetch_zj(kw, cutoff, maxpage)
            except Exception as e:
                print('[WARN] 浙江 kw=%s 失败 %r' % (kw, e)); r = []
            zj.extend(r)
            if r: print('  浙江 %-8s %d 条' % (kw, len(r)))
        zj, drop = clean(dedup(zj))
        print('浙江合计 %d 条（过滤掉 %d）' % (len(zj), drop))
        all_rows.extend(zj)
    if only in ('', 'js'):
        js = []
        for kw in KW_ALL:
            try: r = fetch_js(kw, cutoff, maxpage)
            except Exception as e:
                print('[WARN] 江苏 kw=%s 失败 %r' % (kw, e)); r = []
            js.extend(r)
            if r: print('  江苏 %-8s %d 条' % (kw, len(r)))
        js, drop = clean(dedup(js))
        print('江苏合计 %d 条（过滤掉 %d）' % (len(js), drop))
        all_rows.extend(js)

    if dry:
        for x in all_rows[:40]:
            print('  [%s %s] %s' % (x['rg'], x['d'], x['t'][:50]))
        print('dry 合计 %d 条' % len(all_rows)); return
    if not all_rows:
        print('本轮零新增'); return
    for x in all_rows:
        fn = 'zj-tzxm-%s.json' % today if x['rg'] == '浙江' else 'js-tzxm-%s.json' % today
        p = os.path.join(EARLY_DIR, fn)
        arr = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []
        if not any(r['t'] == x['t'] and r['d'] == x['d'] for r in arr):
            arr.append(x)
        json.dump(arr, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    n_zj = sum(1 for x in all_rows if x['rg'] == '浙江')
    print('落盘完成：浙江 %d / 江苏 %d → raw/early/{zj,js}-tzxm-%s.json'
          % (n_zj, len(all_rows) - n_zj, today))

if __name__ == '__main__':
    main()
