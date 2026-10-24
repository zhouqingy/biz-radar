#!/usr/bin/env python3
"""江苏省站详情补抓器
═══════════════════════════════════════════════
策略：不抓全量（13 市一年 20 万+条），只抓「命中对手/业主/伙伴名单」的
notice/cand/result 条目详情，抽出评标情报（招标人/中标价/控制价/候选人表），
写入 js_lifecycle.json 的 item['detail']（schema 与 nt_lifecycle 一致，
build_web 并网循环自动消费出「全网业绩」+「评标出场记录」）。
命中判定：rival_perf.json 的单位名（归一化）出现在标题或列表摘要里。
"""
import json, os, re, sys, time, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_city_lifecycle import parse_detail  # 复用解析器


def fetch_detail(url):
    # 省站证书链异常，curl 必须 -k（列表接口同款问题）
    import subprocess
    p = subprocess.run(['curl', '-sk', '-m', '25', url,
                        '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)'], capture_output=True)
    return p.stdout.decode('utf-8', 'ignore')

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
LF = os.path.join(RAW, 'js_lifecycle.json')
RP = os.path.join(RAW, 'rival_perf.json')


def rname_norm(s):
    return re.sub(r'[（）()；;\s，,]', '', s or '')


def load_names():
    db = (json.load(open(RP, encoding='utf-8')).get('db') or {})
    return {k: rname_norm(k) for k in db}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--sleep', type=float, default=0.35)
    args = ap.parse_args()

    names = load_names()
    norms = {v for v in names.values() if len(v) >= 5}
    data = json.load(open(LF, encoding='utf-8'))
    items = data.get('items') or []
    todo = []
    for x in items:
        if x.get('detail'):
            continue
        if x.get('cat') not in ('cand', 'result', 'notice', 'sl-cand', 'sl-result',
                                'sl-notice', 'jt-cand', 'jt-result', 'jt-notice',
                                'cg-notice', 'cg-result'):
            continue
        hay = rname_norm((x.get('t') or '') + (x.get('snip') or ''))
        if any(kn in hay or hay in kn for kn in norms):
            todo.append(x)
    print('待补抓 %d / %d 条' % (len(todo), len(items)), flush=True)
    got = 0
    for x in todo[:args.limit]:
        try:
            d = parse_detail(fetch_detail(x['url']))
        except Exception as e:
            print('ERR', x['t'][:30], str(e)[:60], flush=True)
            continue
        if d and (d.get('cands') or d.get('win') or d.get('buyer')
                  or d.get('win_amt')):
            x['detail'] = d
            got += 1
            print('OK', x['cat'], x['d'], x['t'][:36],
                  '| 中标', d.get('win', '')[:20], d.get('win_amt'),
                  '| 候选', len(d.get('cands') or []), flush=True)
        time.sleep(args.sleep)
    json.dump(data, open(LF, 'w'), ensure_ascii=False)
    print('详情入库 %d 条 -> %s' % (got, LF))


if __name__ == '__main__':
    main()
