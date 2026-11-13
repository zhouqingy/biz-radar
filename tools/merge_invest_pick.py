#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 pick_invest.py 分出来的 B 档（已到核准/施工许可、库内还搜不到公告）并进分省主库

════════════════════════════════════════════════════════════════════
这一步为什么必须有（2026-11-13 补）
════════════════════════════════════════════════════════════════════
pick_invest.py 产出 raw/invest_pick.json 之后，11-04 那轮到这里就断了 ——
没有任何脚本把它并进 raw/{jiangsu,zhejiang}.json，于是 build_data 根本读不到，
①库里的「投资在线」190 条一直是 legacy_D 的老数据（最新 2026-09-23）。

写库口径（与 collect_v4.merge() 完全一致，不要另造一套）：
  · 只写 B 档。A 档是「商机库里已经有公告」，写进去就是重复卡片；C 档是只有一纸备案；
    「弃」档是光伏/设备生产/装修这类非工程实体。
  · st 统一「立项公示」—— 审批平台是招标之前最早的一档，与 EARLY_SRC 的映射一致。
  · 金额一律不填。备案/核准页面没有可靠金额，硬塞会污染「已公示金额」。
  · url 留空（审批平台没有稳定的对外详情页），前端会走「无原文链接」降级。
  · 去重按「去掉括号后的项目名 + 公告日期」，与已有条目比对；只追加，不删不改。
  · 不合口径的不用这里管：build_data 仍会过一次 judge() / semantic_drop()，
    污水厂、纯设备类会在构建时被剔掉（这正是唯一规则源该做的事）。
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, 'raw')

PROV_FILE = {'江苏': 'jiangsu.json', '浙江': 'zhejiang.json',
             '安徽': 'anhui.json', '上海': 'shanghai.json'}
PLAT = {'江苏': '江苏投资在线审批平台', '浙江': '浙江投资在线审批平台',
        '安徽': '安徽投资在线审批平台', '上海': '上海投资在线审批平台'}
# 阶段对应的「到哪一步」说明，直接写进 snip，用户一眼能看懂
PHASE_TXT = {'施工许可': '已拿施工许可', '建设工程规划': '已拿建设工程规划许可',
             '规划许可': '已拿规划许可', '初步设计': '已过初步设计审批',
             '用地预审': '已过用地预审', '核准': '已核准', '竣工验收': '已竣工验收'}
OWNER_RE = re.compile(r'^(.{2,40}?(?:股份有限公司|有限责任公司|有限公司|集团公司|集团|公司|厂))')


def norm(s):
    s = re.sub(r'[（(][^）)]*[）)]', '', str(s or ''))
    return re.sub(r'[\s·、,，。:：;；]', '', s)


def owner_of(name):
    m = OWNER_RE.match(str(name or ''))
    return m.group(1) if m else ''


def main():
    src = os.path.join(RAW, 'invest_pick.json')
    if not os.path.exists(src):
        print('⚠ 缺 raw/invest_pick.json，先跑 build_invest_matched.py + pick_invest.py')
        return 2
    d = json.load(open(src, encoding='utf-8'))
    b = d.get('B') or []
    print('读入 B 档 %d 条（源 %s，生成于 %s）' % (len(b), os.path.basename(src), d.get('updated')))

    byp = {}
    for x in b:
        byp.setdefault(x.get('prov') or '', []).append(x)

    grand = 0
    for prov, rows in sorted(byp.items()):
        fn = PROV_FILE.get(prov)
        if not fn:
            print('  ⚠ %s 无对应分省库文件，跳过 %d 条' % (prov, len(rows)))
            continue
        p = os.path.join(RAW, fn)
        old = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []
        if isinstance(old, dict):
            old = old.get('items', [])
        have = {(norm(x.get('t')), (x.get('d') or '')[:10]) for x in old}
        # 同一项目可能已用别的日期进过库，再补一层纯名字比对，避免「同一项目两条」
        have_name = {norm(x.get('t')) for x in old}
        # 2026-11-13 修：init 由「整次运行一次」改成「每省一次」。
        # 原来 init=0 在循环外，江苏把 added 加到 1 之后，浙江也从这个 1 开始累，
        # 于是第二个省的日志打出「1082 → 1083（新增 1）」这种假数字，
        # 合计也会多算。只影响日志、不影响写库，但日志是排查的第一手证据，
        # 不能是错的。
        init = len(old)
        added = 0
        for x in rows:
            name = (x.get('name') or '').strip()
            if not name:
                continue
            dt = (x.get('date_last') or '')[:10]
            if (norm(name), dt) in have or norm(name) in have_name:
                continue
            ph = x.get('phase') or ''
            its = x.get('items') or []
            last = its[-1] if its else {}
            snip = '%s · 最近办结 %s%s' % (
                PHASE_TXT.get(ph, ph or '审批中'), dt,
                (' · ' + (last.get('dept') or '')) if last.get('dept') else '')
            old.append({
                't': name, 'city': '', 'rg': prov, 'st': '立项公示',
                'buyer': owner_of(name), 'win': '', 'amt': None, 'amtTxt': '',
                'd': dt, 'dl': None, 'p': PLAT.get(prov, prov + '投资在线审批平台'),
                'url': '', 'mode': '', 'snip': snip[:400], 'attach': '',
                'platLevel': '省级', 'srcType': 'official',
            })
            have.add((norm(name), dt))
            have_name.add(norm(name))
            added += 1
        if added:
            json.dump(old, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        grand += added
        print('  [merge] %-6s %s: %d → %d（新增 %d）' % (prov, fn, init, len(old), added))
    print('合计新增 %d 条' % grand)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
