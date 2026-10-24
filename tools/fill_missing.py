#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fill_missing.py —— 补「中标单位 / 业主 / 金额 / 联系人」

为什么单独写一个，而不是复用 scan_detail.py：
  scan_detail 是"批量扫描 + 附件清单 + 原始平台"的通用工具，
  它的 todo 逻辑是「按省份扫前 N 条新的」，扫的是**所有**记录。
  而这里的目标很窄：**只扫缺字段的那些**，而且一旦补齐就跳过。
  两者混在一起，会让每天的正常扫描莫名其妙变慢。

目标（2026-10-22 实测缺口）：
  中标单位   250/644 中标类 = 38.8%   ← 最缺，直接影响对手画像
  业主       764/1894 = 40.3%
  金额       339/1894 = 17.9%

产出：写回 raw/<省>.json 的对应记录（不新建文件，避免两套数据打架）

用法：
  python3.11 -u fill_missing.py --limit 100            # 补 100 条
  python3.11 -u fill_missing.py --limit 500 --prov 浙江
  python3.11 -u fill_missing.py --dry                  # 只统计不抓
"""
import os, re, json, time, argparse, subprocess, random

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
PROV_FILE = {'江苏': 'jiangsu.json', '浙江': 'zhejiang.json',
             '安徽': 'anhui.json', '上海': 'shanghai.json'}

# 转载站正文往往是残缺的，抓了也白抓，直接跳过
REPRINT_HOST = ('zhaobiao.cn', 'bidcenter.com.cn', 'chinabidding.cn', 'qianlima.com',
                'bidchance.com', 'jianyu360.com', 'bibenet.com', 'zhulong.com',
                'toubiao.com', '51bid', 'caizhi', 'zbytb.com', 'chinazbcg.com',
                'bidlink', 'ebnew.com', 'infobidding', 'zhiliaobiaoxun')

WIN_ST = ('中标结果公示', '中标候选人公示', '成交公告')


def curl(url, timeout=25):
    try:
        p = subprocess.run(['curl', '-s', '-L', '-m', str(timeout),
                            '-H', 'User-Agent: ' + UA,
                            '-H', 'Accept-Language: zh-CN,zh;q=0.9',
                            url], capture_output=True, timeout=timeout + 5)
        raw = p.stdout or b''
        for enc in ('utf-8', 'gbk', 'gb18030'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', 'ignore')
    except Exception:
        return ''


def need_of(r):
    """这条记录还缺什么（返回缺失字段名列表）"""
    miss = []
    if r.get('st') in WIN_ST and not r.get('win'):
        miss.append('win')
    if not r.get('buyer'):
        miss.append('buyer')
    if not r.get('amt'):
        miss.append('amt')
    if not r.get('phone'):
        miss.append('phone')
    return miss


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prov', default='')
    ap.add_argument('--limit', type=int, default=100)
    ap.add_argument('--sleep', type=float, default=0.35)
    ap.add_argument('--dry', action='store_true')
    # 2026-10-22：并发线程数，原因同 scan_detail（境外线路延迟高，串行撞总超时）
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()

    import detail_fields
    provs = [args.prov] if args.prov else list(PROV_FILE)
    grand = {'n': 0, 'win': 0, 'buyer': 0, 'amt': 0, 'phone': 0, 'fail': 0}

    # 2026-10-24：把 raw/weekly/ 也纳入补全范围。
    # 那天新加的 pull_full_daily.py 全量翻页通道，产出都落在 weekly/ 下
    # （一次 1200+ 条，是现在增量的主力），但当时 fill_missing 只认四个老文件，
    # 于是这批新数据一条都没被补过字段——下游 judge 看不到金额，
    # 「关注档」判定自然常年卡在 15 条上不去。
    # 现在按「省文件 + weekly 全部文件」两份一起扫，写回各自原文件。
    files = []
    for prov in provs:
        fp = os.path.join(RAW, PROV_FILE[prov])
        if os.path.exists(fp):
            files.append((prov, fp))
    _wd = os.path.join(RAW, 'weekly')
    if os.path.isdir(_wd):
        for fn in sorted(os.listdir(_wd)):
            if fn.endswith('.json'):
                files.append(('weekly:' + fn, os.path.join(_wd, fn)))

    for prov, fp in files:
        arr = json.load(open(fp, encoding='utf-8'))
        # 候选：缺关键字段 + 有 url + 是官方站 + 不是空壳
        cand = []
        for r in arr:
            u = (r.get('url') or '').strip()
            if not u or not u.startswith('http'):
                continue
            host = re.sub(r'^https?://', '', u).split('/')[0].lower()
            if any(h in host for h in REPRINT_HOST):
                continue
            if r.get('shell'):
                continue
            m = need_of(r)
            # 只补真正有价值的：缺中标单位，或缺业主，或缺金额
            if not ({'win', 'buyer', 'amt'} & set(m)):
                continue
            cand.append(r)

        # 优先补「缺中标单位」的（最有价值），其次按缺失数排序
        cand.sort(key=lambda r: (0 if (r.get('st') in WIN_ST and not r.get('win')) else 1,
                                 -len(need_of(r))))
        todo = cand[:args.limit]
        print(f'[{prov}] 候选 {len(cand)} 条，本次扫 {len(todo)} 条')
        if args.dry:
            continue

        t0 = time.time()
        # ── 2026-10-22 改成并发 ──────────────────────────────────────
        # 和 scan_detail 同一个原因：GitHub Actions 出境线路延迟高，
        # 串行 + sleep 跑不完，会撞 40 分钟总超时。
        # 这里把「抓页面 + 解析」放进线程池，写回仍然在主线程串行做
        # （dict 原地改，多线程同时改同一条会打架）。
        import threading
        from concurrent.futures import ThreadPoolExecutor
        lock = threading.Lock()

        def fetch(x):
            try:
                html = curl(x['url'])
            except Exception:
                return None
            time.sleep(args.sleep + random.random() * 0.2)
            if not html or len(html) < 400:
                return (x, None)
            try:
                return (x, detail_fields.parse(html, x.get('st') or ''))
            except Exception:
                return (x, None)

        done = {'n': 0}
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for item in ex.map(fetch, todo):
                if item is None:
                    grand['fail'] += 1
                    continue
                x, f = item
                if f is None:
                    grand['fail'] += 1
                    continue
                got = []
                # 只补不改：已有值一律不动。
                # ⚠ 空字符串也算「没值」——原始数据里 win='' 有一批（列表接口返回空串），
                #   如果只判 `not x.get('win')` 其实是对的，但写回时要保证不写入空值，
                #   否则会造出一批「看起来有字段、点开是空」的记录。
                def _set(k, v):
                    if v is None or (isinstance(v, str) and not v.strip()):
                        return False
                    if isinstance(v, list) and not v:
                        return False
                    if x.get(k):
                        return False
                    x[k] = v
                    return True

                if _set('win', f.get('win')):
                    got.append('win'); grand['win'] += 1
                if _set('winJoint', f.get('winJoint')):
                    pass
                if _set('buyer', f.get('buyer')):
                    got.append('buyer'); grand['buyer'] += 1
                if f.get('amt') and not x.get('amt'):
                    x['amt'] = f['amt']
                    x['amtY'] = round(f['amt'] / 1e8, 4)
                    if f.get('amtSrc'):
                        x['amtSrc'] = f['amtSrc']
                    got.append('amt'); grand['amt'] += 1
                if _set('phone', f.get('phone')):
                    got.append('phone'); grand['phone'] += 1
                for k in ('agc', 'contact', 'openDate'):
                    _set(k, f.get(k))
                grand['n'] += 1
                if got:
                    x['fillAt'] = time.strftime('%Y-%m-%d')
                done['n'] += 1
                if done['n'] % 20 == 0:
                    # 每 20 条落盘一次，进程被杀也不白干
                    json.dump(arr, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
                    print(f'   {done["n"]}/{len(todo)}  已补 win={grand["win"]} buyer={grand["buyer"]} '
                          f'amt={grand["amt"]} phone={grand["phone"]}  {time.time()-t0:.0f}s')

        json.dump(arr, open(fp, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'[{prov}] 完成 {len(todo)} 条  {time.time()-t0:.0f}s')

    print(f'\n合计扫描 {grand["n"]} 条 · 补到 中标单位 {grand["win"]} / 业主 {grand["buyer"]} '
          f'/ 金额 {grand["amt"]} / 电话 {grand["phone"]} · 抓取失败 {grand["fail"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
