#!/usr/bin/env python3
"""安徽省站详情补抓器
═══════════════════════════════════════════════
2026-10-24 破解：安徽详情页正文异步加载，POST /jsgc/newDetailSub
  data: type=pbjg&bulletinNature=2&guid=xxx&statusGuid=
type: pbjg=评标结果(候选人公示正文) / tender=招标公告 / xmkb=开标记录 / xmdj=项目登记
候选人表是横向结构：一行「排序」列头是 第一/第二/第三中标候选人，
下一行「单位名称」按列给各家；报价行（若有）同样按列。
只抓名单命中条目，写入 item['detail']（schema 与 nt 一致）。
"""
import json, os, re, sys, argparse, subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_city_lifecycle import parse_amt, strip_html

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
LF = os.path.join(RAW, 'ah_lifecycle.json')


def rname_norm(s):
    return re.sub(r'[（）()；;\s，,]', '', s or '')


def post_sub(guid, typ, nature=2):
    p = subprocess.run(['curl', '-s', '-m', '25',
                        'https://ggzy.ah.gov.cn/jsgc/newDetailSub', '-X', 'POST',
                        '--data', 'type=%s&bulletinNature=%d&guid=%s&statusGuid=' % (typ, nature, guid),
                        '-H', 'User-Agent: Mozilla/5.0',
                        '-H', 'Referer: https://ggzy.ah.gov.cn/'], capture_output=True)
    return p.stdout.decode('utf-8', 'ignore')


def _rows(o):
    out = []
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', o):
        tds = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>|&nbsp;', '', c)).strip()
               for c in re.findall(r'<t[dh][^>]*>([\s\S]*?)</t[dh]>', tr)]
        if tds:
            out.append(tds)
    return out


def parse_ah_detail(o):
    d, names, quotes, ctrl = {}, [], [], []
    for tds in _rows(o):
        k = tds[0]
        if k == '招标人' and len(tds) >= 3:
            d['buyer'] = tds[2]
        elif k == '招标代理机构' and len(tds) >= 3:
            d['agent'] = tds[2]
        elif '联系人' in k and len(tds) >= 2:
            d.setdefault('contacts', []).append((tds[0], tds[1].replace(' ', ''))[:2])
        elif k == '排序':
            pass
        elif k == '单位名称':
            names = [x.replace('\n', '').strip() for x in tds[1:]]
        elif '报价' in k or '价格' in k:
            quotes = tds[1:]
        elif '控制价' in k or '最高限价' in k:
            ctrl = tds[1:]
    if names:
        cands = []
        for i, nm in enumerate(names):
            nm = nm.strip()
            if not nm or len(nm) < 4:
                continue
            q = 0
            if i < len(quotes):
                q = parse_amt(quotes[i])
                if q < 0.01:
                    q = 0   # 防得票数/分值被当报价
            cands.append({'n': nm[:80], 'quote': q})
        d['cands'] = cands[:12]
    if ctrl and ctrl[0]:
        d['control'] = parse_amt(ctrl[0])
    # 拟中标/中标价：中标结果公示(nature=3)正文里常见
    txt = re.sub(r'\s+', ' ', strip_html(o))
    m = re.search(r'(中标|成交)(价|金额|价格)[^0-9]{0,10}([\d,.]+\s*万?亿?\s*元)', txt)
    if m:
        d['win_amt'] = parse_amt(m.group(3))
    m = re.search(r'中标[人单位][名是为：:]{1,3}([^\s，,。;；]{4,60})', txt)
    if m:
        d['win'] = m.group(1).strip()
    # ── 行文式正文（合肥/合肥热电等合肥平台格式）：
    # 第N中标（成交）候选人名称：X … 投标报价：…（29773200.00元）
    if not d.get('cands'):
        cs = []
        for pm in re.finditer(
                r'第[一二三四五六七八九十\d]+中标（成交）候选人名称[:：]\s*([^：]{4,140}?)\s{0,2}(?=地址|投标报价|质量|工期|备注|$)',
                txt):
            nm = pm.group(1).strip()
            if not nm or nm == '无':
                continue
            seg = txt[pm.end():pm.end() + 300]
            qm = re.search(r'([\d,]+(?:\.\d+)?)\s*元', seg)
            q = parse_amt(qm.group(1) + '元') if qm else 0
            if q < 0.01:
                q = 0
            cs.append({'n': nm[:80], 'quote': q})
        if cs:
            d['cands'] = cs[:12]
    if not d.get('buyer'):
        m = re.search(r'招标（采购）人名称[:：]\s*([^\s，,。;；]{4,40})', txt)
        if m:
            d['buyer'] = m.group(1).strip()
    if not d.get('agent'):
        m = re.search(r'招标代理机构名称[:：]\s*([^\s，,。;；]{4,40})', txt)
        if m:
            d['agent'] = m.group(1).strip()
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sleep', type=float, default=0.4)
    ap.add_argument('--limit', type=int, default=100)
    args = ap.parse_args()
    rp = json.load(open(os.path.join(RAW, 'rival_perf.json'), encoding='utf-8'))
    db = rp.get('db') or {}
    norms = {rname_norm(k) for k in db if len(rname_norm(k)) >= 5}
    data = json.load(open(LF, encoding='utf-8'))
    items = data.get('items') or []
    todo = []
    for x in items:
        if x.get('detail') or x.get('cat') not in ('cand', 'result'):
            continue
        hay = rname_norm(x.get('t') or '')
        if any(kn in hay or hay in kn for kn in norms):
            todo.append(x)
    print('待补抓 %d 条' % len(todo), flush=True)
    got = 0
    for x in todo[:args.limit]:
        m = re.search(r'guid=([a-f0-9-]{20,})', x.get('url') or '')
        if not m:
            continue
        nature = 2 if x['cat'] == 'cand' else 3
        o = post_sub(m.group(1), 'pbjg', nature)
        d = parse_ah_detail(o) if len(o) > 500 else {}
        if d and (d.get('cands') or d.get('win') or d.get('buyer') or d.get('win_amt')):
            x['detail'] = d
            got += 1
            print('OK', x['d'], x['t'][:36], '| 招标人', d.get('buyer', '')[:16],
                  '| 候选', len(d.get('cands') or []), flush=True)
        else:
            print('-- 无有效内容', x['t'][:36], flush=True)
        import time
        time.sleep(args.sleep)
    json.dump(data, open(LF, 'w'), ensure_ascii=False)
    print('详情入库 %d 条' % got)


if __name__ == '__main__':
    main()
