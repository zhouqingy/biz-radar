#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zj_csv_import.py · 浙江省投资项目在线审批监管平台「CSV 全量补漏」导入器

════════════════════════════════════════════════════════════════════════
为什么要有这个脚本（2026-11-27 用户拍板：半个月给一批 CSV）
════════════════════════════════════════════════════════════════════════
tzxm_approve.py 只能「按关键词逐词搜 + 每词最多 3 页」，实测同窗口
（11-17~11-26）只抓到 6 条，而用户在平台上一次全量导出能覆盖 23 条。
两个通道覆盖的是不同面：
  · 脚本日常增量 —— 每天自动跑，覆盖最近一两天的新公示
  · 用户半月 CSV  —— 全量导出，补上脚本翻页翻不到的漏项
所以 CSV 不是替代脚本，是补漏。这个脚本把「CSV → 四层过滤 → raw/early」
固化成一条命令，免得每次靠临时脚本、口径漂移。

════════════════════════════════════════════════════════════════════════
四层过滤（与 build_data.py 同一套判据，不另写关键词）
════════════════════════════════════════════════════════════════════════
L1 事项范围   只留「项目存在/推进」的审批事项：备案、核准、环评、节能审查、
              水土保持；人防/施工许可/消防/用地规划这类程序性事项丢。
L2 关键词     collect_v4.KW_ALL（45 词）命中才留 —— 与采集端同一张表。
L3 语义硬过滤 biz_rules.semantic_drop() + collect_v4.KW_NOISE —— 入库前硬拦。
L4 业务终审   biz_rules.judge() / rescue_energy() / equip_level_drop() /
              family_drop()，与 build_data.py 第 6 段完全同序，产出
              「预计进①库 / 会被拦下」两栏 —— 这是真实入库数，不是条数糊弄。

⚠ 纯光伏（不含储能/柴发）按用户既有裁决「纯光伏不做」拦下，属正常拦截，
  不是漏抓。报告里单列，便于对照。

用法：
  python3.11 zj_csv_import.py --csv position_data1128.csv              # 只体检不写盘
  python3.11 zj_csv_import.py --csv position_data1128.csv --write      # 写 raw/early
  python3.11 zj_csv_import.py --csv x.csv --out /tmp/rep --write       # 报告另存
"""
import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight import require_briefing
require_briefing('zj_csv_import.py')

import biz_rules as BR
from collect_v4 import KW_ALL, KW_NOISE
from biz_rules import (judge, semantic_drop, equip_level_drop,
                       family_drop, rescue_energy, HARD_DROP, MODE_EPC)

ROOT = os.path.dirname(os.path.abspath(__file__))
EARLY_DIR = os.path.join(ROOT, 'raw', 'early')
PLAT = '浙江省投资项目在线审批监管平台 办结公示'
URL = ('https://tzxm.zjzwfw.gov.cn/tzxmweb/zwtpages/resultsPublicity/'
       'notice_of_publicity_new.html')

# ---- L1 事项范围：能证明「项目存在并推进」的审批事项 ----
ITEM_KEEP = ('项目备案', '项目核准', '环境影响报告', '环境影响评价', '节能审查',
             '水土保持')
ITEM_DROP = ('人防', '施工许可', '消防', '规划许可', '用地', '不动产',
             '招标事项核准', '竣工验收', '竣工备案', '档案', '地震', '气象',
             '占道', '挖掘', '排水许可', '排污许可', '夜间施工', '渣土')

# ---- L4 与 build_data.py 完全一致的删除前缀（judge 不可投时的出口）----
DROP_PREFIX = ('纯货物/后勤', '分包施工单项', '后期服务', '管网类',
               '设备返厂/维修类', '兼营（分公司业务）', '纯施工总承包', '非能源工程')


def norm_title(s):
    s = re.sub(r'[（(].*?[)）]', '', s or '')
    return re.sub(r'[\s·、，,。\-—【】\[\]]', '', s)


def read_csv(path):
    for enc in ('utf-8-sig', 'gb18030', 'utf-8'):
        try:
            with open(path, encoding=enc, newline='') as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise SystemExit('CSV 编码识别失败：%s' % path)


def stage_of(item):
    if '技术改造' in item:
        return '在线审批技改'
    return '在线审批'


def judge_final(t, snip, item):
    """复刻 build_data.py 第 6 段的判定顺序。

    返回 (状态, 理由)，状态三态：
      enter  —— 会进①库，可直接写 raw/early
      review —— 连业务层级都没命中（seg=other），但标题确实像能源设施
                （如「综合能源服务站」「多能互补供能工程」这类新业态还没进
                业务层级词表）。**不自动写盘**，列清单人工过一眼。
      block  —— 明确不该进，写明依据
    """
    st = '招标计划' if '技术改造' in item else '立项公示'
    v = rescue_energy(t)
    if v == 'drop':
        return 'block', '小锅炉/产业用房/供水（rescue_energy）'
    if equip_level_drop(t, None):
        return 'block', '存量主设备改造（N13）'
    j = judge(t, snip, amt=None, st=st, buyer='', win='', bk='')
    if j.get('investable'):
        return 'enter', 'judge 判可投'
    if v == 'keep':
        return 'enter', '余热余气/批复类强制视为主业'
    dp = j.get('drop') or ''
    if any(dp.startswith(p) for p in DROP_PREFIX):
        return 'block', dp
    # ⚠ 2026-11-27 实测：judge 第 ⑩ 步会把更具体的 drop 原因（如
    #   「纯货物/后勤：充电桩」）**覆盖**成「纯噪声：无业务归属」，于是
    #   build_data 的 8 类前缀匹配失效 → 充电桩/设备采购照样进①库。
    #   这里补一道：标题命中 HARD_DROP（纯货物/后勤词表，biz_rules 原有）且
    #   不含 EPC 模式词 → 判拦下。用的是既有词表，不新造判据。
    if dp.startswith('纯噪声'):
        h = next((k for k in HARD_DROP if k in t), '')
        if h and not any(k in t for k in MODE_EPC):
            return 'block', '纯货物/后勤：' + h + '（drop 被「纯噪声」覆盖，见 biz_rules ⑩）'
    df = family_drop(t, None)
    if df:
        return 'block', df
    if dp.startswith('纯噪声'):
        return 'review', '业务层级未命中（seg=other），需人工看一眼'
    return 'enter', '非 EPC 类但不在删除名单（立项阶段正常）'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--out', default='')
    ap.add_argument('--write', action='store_true', help='写入 raw/early/*.json')
    ap.add_argument('--include-review', action='store_true',
                    help='把「待人工复核」那批也一并写入（默认不写）')
    ap.add_argument('--batch', default='', help='批次日期，默认取 CSV 内最大办结日期')
    a = ap.parse_args()

    rows = read_csv(a.csv)
    print('CSV 原始行数 %d' % len(rows))

    # 既有 early 标题集合：用于去重（同名不再进）
    exist = set()
    if os.path.isdir(EARLY_DIR):
        for fn in os.listdir(EARLY_DIR):
            if not fn.endswith('.json'):
                continue
            try:
                arr = json.load(open(os.path.join(EARLY_DIR, fn), encoding='utf-8'))
            except Exception:
                continue
            if isinstance(arr, list):
                for x in arr:
                    if isinstance(x, dict) and x.get('t'):
                        exist.add(norm_title(x['t']))

    L1 = L2 = L3 = 0
    kept, review, blocked, drop_reason = [], [], [], {}
    seen = set()
    for r in rows:
        item = (r.get('ITEM_NAME') or '').strip()
        title = (r.get('apply_project_name') or '').strip()
        dept = (r.get('DEPT_NAME') or '').strip()
        code = (r.get('deal_code') or '').strip()
        dt = (r.get('DEAL_TIME') or '')[:10]
        if not title or not dt:
            continue
        # L1
        if any(k in item for k in ITEM_DROP):
            drop_reason['L1-程序性事项'] = drop_reason.get('L1-程序性事项', 0) + 1
            continue
        if not any(k in item for k in ITEM_KEEP):
            drop_reason['L1-事项不在范围'] = drop_reason.get('L1-事项不在范围', 0) + 1
            continue
        L1 += 1
        # L2
        if not any(k in title for k in KW_ALL):
            drop_reason['L2-无业务关键词'] = drop_reason.get('L2-无业务关键词', 0) + 1
            continue
        L2 += 1
        # L3
        _drop, _code, _why = semantic_drop(title)
        if _drop or any(k in title for k in KW_NOISE):
            drop_reason['L3-语义过滤(%s)' % _code] = drop_reason.get('L3-语义过滤(%s)' % _code, 0) + 1
            continue
        L3 += 1
        key = (norm_title(title), item)
        if key in seen:
            continue
        seen.add(key)
        snip = '项目代码 %s；审批事项：%s；办理结果：已办结；办结部门：%s；办结时间：%s。' % (
            code, item, dept, dt)
        stt, why = judge_final(title, snip, item)
        rec = {'t': title, 'rg': '浙江', 'city': '', 'buyer': '', 'amt': None,
               'amtTxt': '', 'd': dt, 'dl': '',
               'p': '%s（%s · %s）' % (PLAT, item, dept), 'url': URL,
               'snip': snip, 'mode': '', 'early': stage_of(item), 'expect': '',
               '_code': code, '_why': why}
        {'enter': kept, 'review': review, 'block': blocked}[stt].append(rec)

    # 与既有 raw/early 去重
    dup = [x for x in kept if norm_title(x['t']) in exist]
    fresh = [x for x in kept if norm_title(x['t']) not in exist]
    rev_fresh = [x for x in review if norm_title(x['t']) not in exist]

    import datetime
    batch = a.batch or datetime.date.today().isoformat()
    print('\n=== 四层过滤 ===')
    print('L1 事项范围后  %d' % L1)
    print('L2 关键词后    %d' % L2)
    print('L3 语义过滤后  %d' % L3)
    for k, v in sorted(drop_reason.items()):
        print('   丢 %-16s %d' % (k, v))
    print('\nL4 业务终审：预计进①库 %d 条 / 待人工复核 %d 条 / 被拦下 %d 条'
          % (len(kept), len(review), len(blocked)))
    print('其中与既有 raw/early 同标题重复 %d 条 → 实际新增 %d 条（另有待复核新增 %d 条）'
          % (len(dup), len(fresh), len(rev_fresh)))

    if blocked:
        why = {}
        for x in blocked:
            why[x['_why']] = why.get(x['_why'], 0) + 1
        print('\n被拦下的原因分布：')
        for k, v in sorted(why.items(), key=lambda kv: -kv[1]):
            print('   %-30s %d' % (k, v))

    print('\n=== 实际新增（可写 raw/early）%d 条 ===' % len(fresh))
    for x in sorted(fresh, key=lambda y: y['d'], reverse=True):
        print('  %s  %-6s %s' % (x['d'], x['early'], x['t'][:56]))

    if rev_fresh:
        print('\n=== 待人工复核（默认不写盘，确认后加 --include-review）%d 条 ===' % len(rev_fresh))
        for x in sorted(rev_fresh, key=lambda y: y['d'], reverse=True):
            print('  %s  %-6s %s' % (x['d'], x['early'], x['t'][:56]))

    out_dir = a.out or os.path.join('/workspace', '浙江审批-补漏-%s' % batch.replace('-', ''))
    os.makedirs(out_dir, exist_ok=True)
    rep = {
        'batch': batch, 'csv': a.csv, 'rows': len(rows),
        'L1': L1, 'L2': L2, 'L3': L3,
        'enter': len(kept), 'review': len(review), 'blocked': len(blocked),
        'dup_with_early': len(dup), 'fresh': len(fresh), 'review_fresh': len(rev_fresh),
        'drop_reason': drop_reason,
        'blocked_items': [{k: v for k, v in x.items() if k != 'snip'} for x in blocked],
        'dup_items': [{'d': x['d'], 't': x['t']} for x in dup],
        'fresh_items': [{k: v for k, v in x.items() if k != 'snip'} for x in fresh],
        'review_items': [{k: v for k, v in x.items() if k != 'snip'} for x in rev_fresh],
    }
    os.makedirs(out_dir, exist_ok=True)
    json.dump(rep, open(os.path.join(out_dir, '补漏报告.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    towrite = list(fresh) + (list(rev_fresh) if a.include_review else [])
    if a.write and towrite:
        for x in towrite:
            x.pop('_code', None)
            x.pop('_why', None)
        p = os.path.join(EARLY_DIR, 'zj-tzxm-%s-补漏.json' % batch)
        json.dump(towrite, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n✅ 已写入 %s（%d 条）' % (p, len(towrite)))
        print('   下一步：commit 该文件 → 跑 update_weekly.py 重建 → 页面才看得到')
    elif a.write:
        print('\n（无新增，未写盘）')
    else:
        print('\n（体检模式，未写盘；加 --write 才落 raw/early）')
    print('报告：%s' % os.path.join(out_dir, '补漏报告.json'))


if __name__ == '__main__':
    main()
