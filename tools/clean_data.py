#!/usr/bin/env python3
"""商机雷达 · 数据清洗（线 B，2026-10-22）

输入 merged.json → 输出 merged.clean.json（同时原地更新 merged.json）。
只做**有把握**的修正，拿不准的一律置空 —— 宁可缺，不可编。

清洗规则（每条都对应实测到的真实脏数据，不是为了好看）：
  R1 金额单位截断      amtTxt='项目总投资3038.75万元' 但 amt=3039 元
                       → amtTxt 里明确写了「万元/亿元」，就按 amtTxt 重算
  R2 金额抓错对象      amtTxt='1万'、'2万' 且项目是亿元级储能/污水厂
                       → 数字明显小于该类型项目的合理下限，置 None 并标记
  R3 金额明显离谱      <1万 或 >50亿（单条公告级别的合同额），除非 amtTxt 里
                       明确是「总投资」且带亿/万单位
  R4 同 URL 重复       同一 url 多条记录（10 组 60 条冗余）
                       → 保留信息最全的一条，其余并入 hist 后删除
  R5 标题过短/空       <6 个字的标题基本是解析残留
  R6 立项公示无金额    这类公告本来就极少写金额（0.5%），保持 None，不猜

输出会打印一份清单，写进 raw/clean_report.json，前端「口径说明」可以读。
"""
import json, os, re, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'merged.json')
REPORT = os.path.join(ROOT, 'raw', 'clean_report.json')


def parse_amt_str(s):
    """从一段中文文本里取金额（元）。'项目总投资3038.75万元' -> 30387500"""
    if not s:
        return None
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*(亿元|亿|万元|万)', str(s))
    if not m:
        return None
    try:
        n = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    return n * 1e8 if '亿' in m.group(2) else n * 1e4


def info_score(r):
    """信息完整度，用于同 URL 重复时择优保留（与 build_data 的口径保持一致）"""
    return (4 if r.get('win') else 0) + (3 if r.get('amt') else 0) + \
           (2 if r.get('url') else 0) + (1 if r.get('buyer') else 0) + \
           len(r.get('snip') or '') / 300.0


def main():
    if not os.path.exists(SRC):
        print(f'❌ 找不到 {SRC}')
        return 1
    data = json.load(open(SRC, encoding='utf-8'))
    n0 = len(data)
    log = defaultdict(list)

    # ---------- R1 金额单位截断 ----------
    # 判据：amtTxt 里明确带「万元/亿元」，而 amt 的数值和它差 1000 倍以上。
    # 这不是猜，是 amtTxt 自己写着单位，只是当年解析时把单位丢了。
    #
    # ⚠ 这里踩过一次：R1 先把「2,865,000万」补成 286.5 亿，R3 转头又把它置空，
    #   同一条被两条规则各判一次，报告里既"补了 14 条"又"删了 2 条"，自相矛盾。
    #   病根是 R3 的合理性上限只看绝对值，而 286.5 亿这个数本身就该被拦下——
    #   一条「污水处理系统」的中标公告不可能 286 亿。所以 R1 补值前先过一遍
    #   同一套合理性校验：补出来也不合理的，不补，留给 R3 统一置空。
    PLAUSIBLE_MAX = 5e9   # 单条公告 50 亿封顶（江浙沪皖一个项目的发包额）

    def plausible(v, txt=''):
        if v is None:
            return False
        if v < 5e4:
            return False
        if v > PLAUSIBLE_MAX and '总投资' not in (txt or ''):
            return False
        # 「总投资」也兜一层：超过 1000 亿的总投资在江浙沪皖单项目里不存在
        if v > 1e11:
            return False
        return True

    for r in data:
        amt, txt = r.get('amt'), r.get('amtTxt') or ''
        fixed = parse_amt_str(txt)
        if not fixed:
            continue
        if not plausible(fixed, txt):
            # 补出来的数也不合理 —— 不补，但必须留一句说明，
            # 否则用户看到「金额空着」会以为是漏抓。
            if not r.get('amtNote'):
                r['amtNote'] = ('公告里写的金额 ' + txt[:30] +
                                ' 量级不合理（疑为工程造价/评分误读），未采用')
            log['R1b_不采信'].append({'t': r.get('t', '')[:50], 'txt': txt[:40], 'val': fixed})
            continue
        if amt is None:
            r['amt'] = fixed
            r['amtY'] = round(fixed / 1e8, 4)
            log['R1_补金额'].append({'t': r.get('t', '')[:50], 'txt': txt[:40], 'new': fixed})
        elif amt > 0 and (fixed / amt >= 1000 or amt / fixed >= 1000):
            log['R1_改单位'].append({'t': r.get('t', '')[:50], 'txt': txt[:40],
                                     'old': amt, 'new': fixed})
            r['amt'] = fixed
            r['amtY'] = round(fixed / 1e8, 4)

    # ---------- R2/R3 金额不可能值 ----------
    # 江浙沪皖一个能源/环保类**项目**的合同额，低于 5 万基本只能是
    # 「标书费」「工本费」「服务费尾数」这类非项目金额，放在项目库里就是噪音；
    # 高于 50 亿的单条公告也不正常（那是集团级投资，不是本项目发包额）。
    # 唯一的例外：amtTxt 里明确写「总投资」且带亿单位——那确实可能是几十亿的项目。
    #
    # 实测被这条拦下的典型：
    #   「柯桥未来医学中心污水处理系统」amtTxt='2,865,000万' → 286.5 亿（乱抓）
    #   「中央北路污染土壤修复」amtTxt='28,086,668万'      → 2808 亿（乱抓）
    #   这两条都是中标公示里把"工程造价/评标分"抓进金额字段，必须清掉。
    lowered = 0
    for r in data:
        amt = r.get('amt')
        if not amt:
            continue
        txt = r.get('amtTxt') or ''
        if not plausible(amt, txt):
            log['R2_置空'].append({'t': r.get('t', '')[:50], 'amt': amt, 'txt': txt[:40]})
            r['amt'] = None
            r['amtY'] = None
            r['amtNote'] = ('原记录金额 ' + (txt[:30] or str(int(amt))) +
                            '，量级不合理（疑抓到造价/评分），已置空')
            lowered += 1

    # ---------- R4 同 URL 重复 ----------
    # ⚠ 2026-10-28 修：原来只用 url 做分组键，结果一篇省发改委规划批复里点名的
    #   多家企业（南京那篇点了南钢、梅山钢铁、南化、扬子石化 4 家）被压成 1 条——
    #   41 条规划线索只剩 13 条；规划 PDF 同理，一份附件提 3~5 个热源点业主，
    #   按 url 合并后 19 条只剩 4 条。这些都是**不同业主的不同商机**，不能合并。
    #   所以分组键加上 buyer：同一 url 同一业主才算真冗余。
    by_url = defaultdict(list)
    for r in data:
        u = (r.get('url') or '').strip()
        if u and u not in ('None', 'null'):
            by_url[(u, (r.get('buyer') or '').strip())].append(r)
    drop = set()
    for (u, _buyer), rows in by_url.items():
        if len(rows) < 2:
            continue
        rows.sort(key=info_score, reverse=True)
        keep = rows[0]
        for d in rows[1:]:
            # 把被删记录的信息塞进 keep.hist，保证不丢线索
            h = keep.get('hist') or []
            h.append({'st': d.get('st'), 'd': d.get('d'), 'url': u,
                      '_mergedBy': 'clean_R4', 't': d.get('t', '')[:60]})
            keep['hist'] = h
            drop.add(id(d))
            log['R4_去重'].append({'t': d.get('t', '')[:50], 'url': u})
    if drop:
        data = [r for r in data if id(r) not in drop]

    # ---------- R5 标题过短 ----------
    keep2 = []
    for r in data:
        t = (r.get('t') or '').strip()
        if len(t) < 6:
            log['R5_删短标题'].append({'t': t})
            continue
        keep2.append(r)
    data = keep2

    # ---------- 写回 ----------
    json.dump(data, open(SRC, 'w', encoding='utf-8'), ensure_ascii=False)

    rep = {
        'updated': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
        'before': n0,
        'after': len(data),
        'amtCoverage': f"{sum(1 for r in data if r.get('amt'))}/{len(data)}",
        'rules': {k: len(v) for k, v in sorted(log.items())},
        'samples': {k: v[:12] for k, v in sorted(log.items())},
    }
    json.dump(rep, open(REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    print(f'清洗：{n0} → {len(data)} 条（-{n0 - len(data)}）')
    for k, v in sorted(log.items()):
        print(f'  {k:14s} {len(v):4d} 条')
    hit = sum(1 for r in data if r.get('amt'))
    print(f'金额覆盖率：{hit}/{len(data)} = {hit / len(data) * 100:.1f}%')
    print(f'报告已写 {REPORT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
