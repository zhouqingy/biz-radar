#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fill_amount.py —— 专补「金额」一条字段

和 fill_missing.py 的分工：
  fill_missing 是「中标单位 / 业主 / 金额 / 联系人」四件一起补，按「最缺的优先」排队，
  所以缺金额的记录永远排在缺中标单位的后面，金额覆盖率常年上不去。
  这个脚本只干一件事：把没有 amt 的记录，回访原文把金额抠出来。

⚠ 口径必须分开存，不能混进同一个 amt 字段：
  - 中标/成交/合同价  → kind='win'    这是「这条标值多少钱」
  - 项目总投资/投资估算 → kind='inv'    这是「业主打算投多少钱」，两者能差 3~10 倍
  2026-11-04 用户确认：金额需要。此前 611.7 亿里混了 28 条总投资（42.6 亿），
  会让「已公示金额」这个数字既不是中标额也不是投资额。这里写入时带上 amtKind，
  下游 build_data / build_web 再决定哪些进「中标额」、哪些单独列。

写回规则（不新建文件，改原文件，先备份）：
  r['amt']      元
  r['amtY']     亿元
  r['amtKind']  'win' / 'inv'
  r['amtSrc']   抽到它的标签（中标价 / 投资估算 / 定标成交结果 …）
  r['amtFillAt'] 补采时间，便于回滚和统计

用法：
  python3 fill_amount.py --limit 60 --dry       # 只看能补多少，不落盘
  python3 fill_amount.py --limit 60             # 真补 60 条
  python3 fill_amount.py --all --workers 8      # 全量补
"""
import argparse
import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')

PROV_FILE = {'江苏': 'jiangsu.json', '浙江': 'zhejiang.json',
             '安徽': 'anhui.json', '上海': 'shanghai.json'}

# 转载站正文残缺，抓了也白抓
REPRINT_HOST = ('zhaobiao.cn', 'bidcenter.com.cn', 'chinabidding.cn', 'qianlima.com',
                'bidchance.com', 'jianyu360.com', 'bibenet.com', 'zhulong.com',
                'toubiao.com', '51bid', 'caizhi', 'zbytb.com', 'chinazbcg.com',
                'bidlink', 'ebnew.com', 'infobidding', 'zhiliaobiaoxun')

# 抓不到正文的平台：细节页是 JS 渲染或要登录，直接跳过省时间
SKIP_HOST = ('baohua', 'sggzy', 'zfcg.czt')

# 中标口径的标签（src 字段来自 detail_fields 的 amtSrc）
WIN_SRC = ('投标报价', '中标价', '中标金额', '成交金额', '中选金额', '合同金额',
           '定标成交结果', '括注金额')
INV_SRC = ('投资估算', '投资额', '预算金额', '最高投标限价', '招标控制价',
           '合同估算价', '项目总投资')


def kind_of(src):
    """金额来源 → 口径。默认按中标价算（detail_fields 优先抽中标类）"""
    if any(k in (src or '') for k in INV_SRC):
        return 'inv'
    return 'win'


def collect(files):
    """收集候选：缺金额 + 有 url + 非转载 + 非空壳"""
    cand = []
    for tag, fp in files:
        arr = json.load(open(fp, encoding='utf-8'))
        for r in arr:
            if r.get('amt'):
                continue
            u = (r.get('url') or '').strip()
            if not u.startswith('http'):
                continue
            host = re.sub(r'^https?://', '', u).split('/')[0].lower()
            if any(h in host for h in REPRINT_HOST):
                continue
            if any(h in host for h in SKIP_HOST):
                continue
            if r.get('shell'):
                continue
            cand.append((tag, fp, r))
    # 优先补「中标类阶段」的：它们的金额就是中标价，价值最高
    WIN_ST = ('中标结果公示', '中标候选人公示', '成交公告', '中标公告', '中标结果公告')
    cand.sort(key=lambda x: 0 if (x[2].get('st') in WIN_ST) else 1)
    return cand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=60)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--prov', default='')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    import fill_missing as FM
    import detail_fields as DF

    provs = [args.prov] if args.prov else list(PROV_FILE)
    files = []
    for p in provs:
        fp = os.path.join(RAW, PROV_FILE[p])
        if os.path.exists(fp):
            files.append((p, fp))
    wd = os.path.join(RAW, 'weekly')
    if os.path.isdir(wd) and not args.prov:
        for fn in sorted(os.listdir(wd)):
            if fn.endswith('.json'):
                files.append(('weekly:' + fn, os.path.join(wd, fn)))

    cand = collect(files)
    todo = cand if args.all else cand[:args.limit]
    print('缺金额候选 %d 条，本次处理 %d 条' % (len(cand), len(todo)))

    def work(item):
        tag, fp, r = item
        try:
            html = FM.curl(r['url'])
            f = DF.parse(html)
        except Exception:
            return (item, None)
        return (item, f.get('amt') if f else None, (f or {}).get('amtSrc'))

    t0 = time.time()
    done = 0
    stat = {'win': 0, 'inv': 0, 'fail': 0}
    samples = []
    # 按文件分组写回，避免同文件并发读改写打架
    hit = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(work, todo):
            done += 1
            item, amt, src = res if len(res) == 3 else (res[0], None, None)
            tag, fp, r = item
            if not amt:
                stat['fail'] += 1
            else:
                k = kind_of(src)
                stat[k] += 1
                hit.setdefault(fp, []).append((r, amt, src, k))
                if len(samples) < 12:
                    samples.append((r['t'][:40], amt / 1e8, src, k))
            if done % 20 == 0:
                print('   %d/%d  中标价 %d · 投资额 %d · 无果 %d  %.0fs'
                      % (done, len(todo), stat['win'], stat['inv'], stat['fail'],
                         time.time() - t0))
    print('\n抓取完成 %.0fs：中标价 %d 条 · 投资额 %d 条 · 抓不到 %d 条'
          % (time.time() - t0, stat['win'], stat['inv'], stat['fail']))
    for s in samples:
        print('   %-42s %7.3f亿  [%s→%s]' % s)

    if args.dry:
        print('\n【--dry，未写盘】')
        return

    stamp = time.strftime('%Y-%m-%d %H:%M')
    for fp, rows in hit.items():
        shutil.copy(fp, fp + '.bak_amt')
        arr = json.load(open(fp, encoding='utf-8'))
        # ⚠ 不能用 id(r) 做索引：hit 里存的对象与重新 load 出来的 arr 不是同一批实例，
        #    id() 全对不上 —— 2026-11-04 第一次跑就是这里「抓到 426 条、写回 0 条」。
        #   改用「标题 + URL」定位，一对多也能覆盖。
        idx = {}
        for i, x in enumerate(arr):
            idx.setdefault(((x.get('t') or '').strip(), (x.get('url') or '').strip()), []).append(i)
        n = 0
        for r, amt, src, k in rows:
            key = ((r.get('t') or '').strip(), (r.get('url') or '').strip())
            for i in idx.get(key, []):
                x = arr[i]
                if x.get('amt'):
                    continue
                x['amt'] = amt
                x['amtY'] = round(amt / 1e8, 4)
                x['amtKind'] = k
                x['amtSrc'] = src or ''
                x['amtFillAt'] = stamp
                n += 1
        json.dump(arr, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('写回 %-40s %d 条' % (os.path.basename(fp), n))


if __name__ == '__main__':
    main()
