#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只刷新 data.core.js 里的 metals 段 —— 给 metals.yml 用，不重建整个数据包。

为什么单独写这一个（2026-11-08）：
  metals.yml 原来第 2 步跑 build_web.py，那是「重建整个站点数据包」：
  先 cp merged.snapshot.json merged.json（仓库里的 11-03 快照），
  再按这份快照重算 items / chunk / core 全部。可第 4 步只提交
  data.metalhist.js 和 data.core.js，同一批 chunk 被 git stash 丢掉 ——
  于是 core 被换成快照版、列表还是线上那版，顶部「入库项目」和列表长期对不上
  （实测 core=912、列表=1119）。

  行情工作流的职责只有一件事：把 13 个品种的当日价格写进 core。
  所以改成「打开现有 core → 只替换 metals 键 → 原样写回」，
  其余 meta / platforms / watch / domStat / chunks 一个字节都不碰。

用法：
  cd tools && python3.11 refresh_metals_core.py
  BIZ_OUT=/path/to/site python3.11 refresh_metals_core.py   # 指定站点目录

退出码：
  0  已更新或无需更新
  1  抓不到行情 / 文件结构不对（此时不写盘，原文件保持不动）
"""
import json
import os
import re
import sys
import time
import random
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# ⚠ 不能 import build_web —— 那个模块是顶层脚本，import 的瞬间就会把整包重建一遍
#   （连带 build_data 的自检、写文件全跑）。这里用 exec 只抠出 fetch_metals 一个函数，
#   它前面的 METALS_CACHE 常量和 urllib/re/time/random/os/json 这些 import 一起带过来即可。
_MW = os.path.join(HERE, 'build_web.py')
_src = open(_MW, encoding='utf-8').read()
_start = _src.index('# ---- 有色金属期货价格')
_end = _src.index('METALS = fetch_metals()')
_ns = {'os': os, 'sys': sys, 're': re, 'json': json, 'time': time,
       'random': random, 'urllib': urllib, '__file__': _MW}
exec(compile(_src[_start:_end], _MW, 'exec'), _ns)
fetch_metals = _ns['fetch_metals']

TIMEOUT_MIN_ITEMS = 10      # 少于这么多品种视为抓取失败，不写盘
HEAD = '/* 商机雷达 · 核心数据（meta / metals / platforms / watch） */\n'


def site_dir():
    """站点目录：BIZ_OUT → BIZ_SITE → 脚本上一级 → 上一级/biz-radar / workspace/biz-radar。"""
    up = os.path.dirname(HERE)
    cands = []
    for k in ('BIZ_OUT', 'BIZ_SITE'):
        if os.environ.get(k):
            cands.append(os.environ[k])
    cands += [up, os.path.join(up, 'biz-radar'), '/workspace/biz-radar']
    for c in cands:
        if os.path.isfile(os.path.join(c, 'data.core.js')):
            return c
    raise SystemExit('找不到 data.core.js；已试: %s' % cands)


def split(text):
    """拆成 (前缀到 '=' 为止, JSON 对象, 结尾 ';' 与换行) —— 保留原文格式，只换中间。"""
    i = text.index('=')
    j = text.rindex(';')
    body = text[i + 1:j]
    obj = json.loads(body.strip())
    return text[:i + 1], obj, text[j:]


def main():
    site = site_dir()
    path = os.path.join(site, 'data.core.js')
    orig = open(path, encoding='utf-8').read()
    prefix, obj, tail = split(orig)
    before = json.dumps(obj, ensure_ascii=False, sort_keys=True)

    items = fetch_metals()
    if len(items) < TIMEOUT_MIN_ITEMS:
        print('❌ 只抓到 %d 个品种（要求 >= %d），本次不写盘' % (len(items), TIMEOUT_MIN_ITEMS))
        return 1

    obj['metals'] = {'updated': items[0].get('date') or '',
                     'at': time.strftime('%H:%M'),
                     'items': items}

    # 除了 metals，其余键必须逐字节等价 —— 写盘前断言，防止误伤
    after_obj = json.loads(json.dumps(obj, ensure_ascii=False))
    after_obj['metals'] = json.loads(before)['metals']
    assert json.dumps(after_obj, ensure_ascii=False, sort_keys=True) == before, \
        '除 metals 外的键发生了变化，拒绝写盘'

    body = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    open(path, 'w', encoding='utf-8').write(prefix + body + tail)
    print('✅ metals 已更新：%d 个品种 · 行情日 %s · %s'
          % (len(items), obj['metals']['updated'], obj['metals']['at']))
    print('   文件: %s (%d B)' % (path, os.path.getsize(path)))
    print('   其余键（meta/platforms/watch/domStat/chunks）未改动')
    return 0


if __name__ == '__main__':
    sys.exit(main())
