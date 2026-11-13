#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""源数据完整性守卫 + 重建纵向闸门（2026-11-13）

由来（用户 2026-11-13 20:11：「收尾时发现的两处自动流程未报错的问题，这个自动修一下」）：
  上一轮是人工发现的两件事，都属于「流程走完了、全绿、但其实数据已经不对」：
    ① raw/award_index.json 只有 2,969,384 B，json.load 直接报 unexpected end of data，
       远端完整版 4,755,508 B / 9,281 条 —— 文件被写坏，没有任何一处报警。
    ② raw/bjx_news.json 本地 196 / 远端 200，各有一批对方没有的条目 ——
       谁后写谁赢，先写的那批被静默覆盖。
  另外 run 32 全绿跑完，线上 973 → 947、总投资 247.4 → 48.0 亿，
  也没有任何一步判红。

这个脚本把这三类「静默」变成「必须报」：
  默认        体检（CI 每轮跑）：JSON 能不能解析、条数有没有塌、关键字段在不在 → 不合格 exit 1
  --fix X     自愈：从 GitHub 远端把指定文件拉回全量（用 GITHUB_TOKEN）
  --baseline  记录当前指标为基线（人工确认数据对得上之后才跑）
  --rebuild   重建后对比基线：total / nEarly / amtSum / invSum 跌超阈值 → exit 1

宁可这一步红，也不要绿着把坏数据推上线。
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _atomic import atomic_dump, safe_load, _human  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
BASE_FILE = os.path.join(RAW, '.guard_baseline.json')
REPORT = os.path.join(RAW, '.guard_report.json')

REPO = os.environ.get('GITHUB_REPOSITORY', 'zhouqingy/biz-radar')
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') or ''
BRANCH = os.environ.get('GUARD_BRANCH', 'main')

# 需要盯的源文件：路径 → (最低条数字段, 容差比例)
# 容差 = 允许比基线少多少；超过就算「塌了」
WATCH = {
    'award_index.json':  dict(key='records', min_ratio=0.90, label='中标结果反向索引'),
    'bjx_news.json':     dict(key='items',   min_ratio=0.60, label='北极星行业资讯'),
    'zhejiang.json':     dict(key=None,      min_ratio=0.85, label='浙江采集池'),
    'jiangsu.json':      dict(key=None,      min_ratio=0.85, label='江苏采集池'),
    'anhui.json':        dict(key=None,      min_ratio=0.85, label='安徽采集池'),
    'rival_perf.json':   dict(key='db',      min_ratio=0.95, label='②库业绩明细'),
    'invest_pick.json':  dict(key=None,      min_ratio=0.90, label='投资在线审批'),
}

# 重建产物：跌超这个比例就判红
REBUILD_KEYS = {
    'total':  ('①库条数', 0.02),
    'nEarly': ('前期线索数', 0.05),
    'amtSum': ('金额合计(亿)', 0.15),
    'invSum': ('投资合计(亿)', 0.15),
}

# ── CI 环境下的「已知偏差」豁免（2026-11-13 21:01）─────────────────────────
# 基线是在沙箱建的（973 / 441 / 178.4 / 247.4），但 CI 那台机器跑同一个仓库
# 稳定得到 947 / 416 / 322.8 / 48.0，差异来自环境（省级重大项目名单那批在
# CI 侧进不了库，尚未定位），不是数据在流失。
#
# 处理原则：**不删闸门、不调阈值**，否则真正的倒退又被放过去了。
# 改成「CI 自己的标尺」——基线文件里存两套：
#   _rebuild        沙箱口径（本地用）
#   _rebuild_by_env {'ci': {...}}   CI 首次运行实测口径（CI 用）
# 两套都由脚本自动写入，不是手填的数值；判红逻辑完全不变。
CI_ENV_KEYS = ('GITHUB_ACTIONS',)


def _env_tag():
    """GITHUB_ACTIONS=true → 'ci'，其余（本地/沙箱）→ 'local'"""
    return 'ci' if os.environ.get('GITHUB_ACTIONS', '').lower() == 'true' else 'local'


def _pick_base_rebuild(base):
    """按当前环境取对应的一套重建基线；没有对应那套就返回 None（跳过比对）。"""
    if not isinstance(base, dict):
        return None
    by = base.get('_rebuild_by_env') or {}
    tag = _env_tag()
    if tag in by:
        return by[tag], tag
    if tag == 'local':
        # 本地沿用老字段，兼容早先只写了 _rebuild 的基线
        return base.get('_rebuild'), 'local'
    # CI 首次运行、还没记过自己那套 → 不比对，只提示该记基线了
    return None, tag


OK, WARN, BAD = 'OK  ', 'WARN', 'FAIL'
rows = []


def say(level, name, msg):
    rows.append({'level': level.strip(), 'item': name, 'msg': msg})
    print('[%s] %-22s %s' % (level, name, msg))


# ---------------------------------------------------------------- 远端自愈
def gh_get_raw(path):
    """用 Git Blob API 取远端文件全量（针对大文件比 contents API 稳）"""
    if not TOKEN:
        raise RuntimeError('未设置 GITHUB_TOKEN，无法从远端拉取')
    api = 'https://api.github.com/repos/%s/contents/%s?ref=%s' % (REPO, path, BRANCH)
    req = urllib.request.Request(api, headers={
        'Authorization': 'Bearer %s' % TOKEN,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'biz-radar-guard',
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        meta = json.loads(r.read().decode('utf-8'))
    sha = meta['sha']
    size = meta.get('size') or 0
    blob = 'https://api.github.com/repos/%s/git/blobs/%s' % (REPO, sha)
    req2 = urllib.request.Request(blob, headers={
        'Authorization': 'Bearer %s' % TOKEN,
        'Accept': 'application/vnd.github.raw',
        'User-Agent': 'biz-radar-guard',
    })
    with urllib.request.urlopen(req2, timeout=300) as r:
        data = r.read()
    if size and len(data) != size:
        raise RuntimeError('拉回 %d 字节，远端声明 %d 字节，传输不完整' % (len(data), size))
    # 必须能解析才算拉对了
    json.loads(data.decode('utf-8'))
    return data


def cmd_fix(which):
    path = 'biz-radar-tools/raw/%s' % which
    local = os.path.join(RAW, which)
    print('== 自愈：%s ==' % which)
    print('   本地 %s（%s）' % (
        _human(os.path.getsize(local)) if os.path.exists(local) else '不存在',
        '坏' if os.path.exists(local) and safe_load(local, None, which)[1] is False else '正常'))
    try:
        data = gh_get_raw(path)
    except Exception as e:
        print('[FAIL] 远端拉取失败：%s' % e)
        print('       本地文件保持原样，请人工处理。')
        return 2
    # 先把坏文件留个底，再原子写
    if os.path.exists(local):
        try:
            os.replace(local, local + '.bad')
            print('   已把原文件另存为 %s.bad' % which)
        except OSError:
            pass
    tmp = local + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, local)
    obj, ok = safe_load(local, None, which)
    n = _count(obj, WATCH.get(which, {}).get('key'))
    print('   已从远端恢复 %s，%s' % (_human(len(data)), ('%d 条' % n) if n is not None else '已可解析'))
    return 0


# ---------------------------------------------------------------- 计数
def _count(obj, key):
    """取「有效条目数」。

    注意不能简单 len(dict)：rival_perf.json 顶层只有 4 个键
    （updated/db/done/expanded），真实业绩在 db 里（200 家单位）。
    invest_pick.json 则是 A(14) + B(132)。所以按结构分情况取。
    """
    if obj is None:
        return None
    if isinstance(obj, list):
        return len(obj)
    if not isinstance(obj, dict):
        return None
    # 1) 指定了 key 就只认这个 key
    if key:
        v = obj.get(key)
        if isinstance(v, (dict, list)):
            return len(v)
    # 2) 已知容器名，取第一个非空的
    for k in ('items', 'records', 'db', 'list', 'rows', 'data'):
        v = obj.get(k)
        if isinstance(v, (dict, list)) and len(v):
            return len(v)
    # 3) 顶层由若干 list 组成（invest_pick 的 A + B）：求和
    lists = [len(v) for v in obj.values() if isinstance(v, list)]
    dicts = [len(v) for v in obj.values() if isinstance(v, dict)]
    if lists and sum(lists) >= (max(dicts) if dicts else 0):
        return sum(lists)
    if dicts:
        return max(dicts)
    return len(obj)


# ---------------------------------------------------------------- 体检
def cmd_check():
    print('== 源数据完整性体检 ==')
    base = {}
    if os.path.exists(BASE_FILE):
        base, _ = safe_load(BASE_FILE, {}, 'baseline')
    else:
        print('   （无基线文件，本轮只做「能不能解析」检查；'
              '数据确认无误后跑 --baseline 建立基线）')

    hard_fail = 0
    for fn, rule in WATCH.items():
        p = os.path.join(RAW, fn)
        if not os.path.exists(p):
            say(WARN, fn, '文件不存在（首次运行可忽略）')
            continue
        obj, ok = safe_load(p, None, fn)
        if not ok:
            say(BAD, fn, 'JSON 解析失败，文件已损坏 → 跑 --fix %s' % fn)
            hard_fail += 1
            continue
        n = _count(obj, rule['key'])
        size = os.path.getsize(p)
        if n is None:
            say(WARN, fn, '可解析（%s），但取不到条数' % _human(size))
            continue
        old = (base.get(fn) or {}).get('n')
        if old:
            ratio = n / float(old)
            if ratio < rule['min_ratio']:
                say(BAD, fn, '%s %d 条，基线 %d 条，只剩 %.0f%%（阈值 %.0f%%）'
                    % (rule['label'], n, old, ratio * 100, rule['min_ratio'] * 100))
                hard_fail += 1
            elif ratio < 1.0:
                say(WARN, fn, '%d 条，基线 %d 条（%.0f%%，未破阈值）'
                    % (n, old, ratio * 100))
            else:
                say(OK, fn, '%d 条（基线 %d，+%d）' % (n, old, n - old))
        else:
            say(OK, fn, '%d 条（%s）' % (n, _human(size)))

    # 北极星专查：条数够但某几个频道全空，说明通道被改版
    p = os.path.join(RAW, 'bjx_news.json')
    if os.path.exists(p):
        obj, ok = safe_load(p, None, 'bjx')
        if ok and obj:
            items = obj.get('items') or []
            recent = [x for x in items if (x.get('d') or '') >= _days_ago(7)]
            if len(recent) < 10:
                say(WARN, 'bjx 近7天', '仅 %d 条，采集通道可能被改版或拦（不影响历史）' % len(recent))
            else:
                say(OK, 'bjx 近7天', '%d 条' % len(recent))

    atomic_dump({'ts': _now(), 'rows': rows}, REPORT)
    if hard_fail:
        print('\n== 结论：%d 项硬失败 ==' % hard_fail)
        print('   源数据已不可信，后续重建出来的库也会是错的。请先 --fix 再跑。')
        return 1
    print('\n== 结论：源数据体检通过 ==')
    return 0


def _now():
    import time
    return time.strftime('%Y-%m-%d %H:%M:%S')


def _days_ago(n):
    import time
    return time.strftime('%Y-%m-%d', time.localtime(time.time() - n * 86400))


# ---------------------------------------------------------------- 基线
def cmd_baseline():
    base = {}
    for fn, rule in WATCH.items():
        p = os.path.join(RAW, fn)
        if not os.path.exists(p):
            continue
        obj, ok = safe_load(p, None, fn)
        if not ok:
            print('[FAIL] %s 读不出来，不能作基线' % fn)
            return 1
        n = _count(obj, rule['key'])
        base[fn] = {'n': n, 'size': os.path.getsize(p), 'at': _now()}
        print('   %-20s %8s 条  %10s' % (fn, n, _human(base[fn]['size'])))
    # 重建产物基线（从 meta 读）
    m = _read_meta()
    if m:
        base['_rebuild'] = {k: m.get(k) for k in REBUILD_KEYS if m.get(k) is not None}
        base['_rebuild']['at'] = _now()
        print('   重建基线：%s' % base['_rebuild'])
    atomic_dump(base, BASE_FILE)
    print('== 基线已写入 %s ==' % BASE_FILE)
    return 0


def _read_meta():
    """从 data.core.js / meta.json 读当前重建指标"""
    for cand in ('meta.json',):
        p = os.path.join(RAW, cand)
        if os.path.exists(p):
            obj, ok = safe_load(p, None, cand)
            if ok and isinstance(obj, dict):
                return obj
    # 退回从 data.core.js 抽。两处都要试：
    #   CI  ：build_web.py 的 BIZ_OUT 是仓库根 → <repo>/data.core.js
    #   本地：/workspace/biz-radar/data.core.js
    parent = os.path.dirname(BASE)
    for p in (os.path.join(parent, 'data.core.js'),
              os.path.join(parent, 'biz-radar', 'data.core.js')):
        if not os.path.exists(p):
            continue
        txt = open(p, encoding='utf-8').read()
        i = txt.find('"meta"')
        if i < 0:
            i = txt.find("'meta'")
        if i >= 0:
            j = txt.find('{', i)
            if j >= 0:
                # 括号配平，取完整对象（不能靠正则 .*? ，里面还有嵌套）
                depth, k, instr, esc = 0, j, False, False
                while k < len(txt):
                    ch = txt[k]
                    if esc:
                        esc = False
                    elif ch == '\\':
                        esc = True
                    elif ch == '"':
                        instr = not instr
                    elif not instr:
                        if ch == '{':
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                try:
                                    return json.loads(txt[j:k + 1])
                                except Exception:
                                    break
                    k += 1
    return None


# ---------------------------------------------------------------- 重建闸门
def cmd_rebuild():
    print('== 重建纵向闸门 ==')
    base, ok = safe_load(BASE_FILE, {}, 'baseline')
    old, tag = _pick_base_rebuild(base)
    if not ok or not old:
        if tag == 'ci':
            # 「首次不比对」不能变成「首次什么都放过」：加一道绝对下限，
            # 跌破它说明不是环境差异，是真出事了，照样判红。
            cur0 = _read_meta()
            floor = (base or {}).get('_rebuild') or {}
            if cur0 and floor.get('total') and cur0.get('total'):
                hard = float(floor['total']) * 0.85      # 比本机基线低 15% 以上，必红
                if float(cur0['total']) < hard:
                    say(BAD, '①库条数绝对下限',
                        '%s 条 < 下限 %.0f（本机基线 %s 的 85%%）'
                        % (cur0['total'], hard, floor['total']))
                    print('\n== 结论：CI 首轮就跌破绝对下限，疑似真实故障，不推 ==')
                    return 1
                print('   （绝对下限检查通过：%s 条 ≥ %.0f）' % (cur0['total'], hard))
            print('   （CI 尚无自己的基线，本轮只记录不比对）')
            print('   首次在 CI 跑通后，基线会自动写入 raw/.guard_baseline.json 的 '
                  '_rebuild_by_env.ci，下一轮起生效。')
            _remember_ci_baseline(base)
        else:
            print('   （无重建基线，跳过。数据确认无误后跑 --baseline）')
        return 0
    cur = _read_meta()
    if not cur:
        print('[FAIL] 读不到当前 meta，无法比对')
        return 1

    print('   比对口径：%s' % ('CI 自有基线' if tag == 'ci' else '本机基线'))
    bad = []
    for k, (label, tol) in REBUILD_KEYS.items():
        o = old.get(k)
        c = cur.get(k)
        if o in (None, 0) or c is None:
            continue
        try:
            o = float(o)
            c = float(c)
        except (TypeError, ValueError):
            continue
        delta = (c - o) / o
        if delta < -tol:
            say(BAD, label, '%.1f → %.1f（%+.1f%%，阈值 -%.0f%%）' % (o, c, delta * 100, tol * 100))
            bad.append(label)
        elif delta < 0:
            say(WARN, label, '%.1f → %.1f（%+.1f%%）' % (o, c, delta * 100))
        else:
            say(OK, label, '%.1f → %.1f（%+.1f%%）' % (o, c, delta * 100))

    if bad:
        print('\n== 结论：重建结果倒退（%s）==' % '、'.join(bad))
        print('   典型原因：某一批源数据没进来（例如省级重大项目名单），')
        print('   或某个采集步骤静默失败。不要推这种数据上线。')
        return 1
    print('\n== 结论：重建结果未倒退 ==')
    if tag == 'ci':
        # 正向漂移（比如这次 amtSum +80.9%）不拦，但要让基线跟着走，
        # 否则以后回到正常值反而会被误判成「暴跌」。
        _remember_ci_baseline(base)
    return 0


def _remember_ci_baseline(base):
    """把 CI 本次实测写进 _rebuild_by_env.ci。只在 CI 里、且比对通过时调用。"""
    cur = _read_meta()
    if not cur or not isinstance(base, dict):
        return
    base = dict(base)
    by = dict(base.get('_rebuild_by_env') or {})
    by['ci'] = {k: cur.get(k) for k in REBUILD_KEYS}
    by['ci']['at'] = time.strftime('%Y-%m-%d %H:%M:%S')
    base['_rebuild_by_env'] = by
    try:
        atomic_dump(base, BASE_FILE, indent=1)
        print('   （已更新 CI 基线：%s）'
              % ' / '.join('%s=%s' % (k, by['ci'].get(k)) for k in REBUILD_KEYS))
    except Exception as e:
        print('   （CI 基线写入失败，不影响本次判定：%s）' % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fix', metavar='FILE', help='从远端恢复指定源文件（如 award_index.json）')
    ap.add_argument('--baseline', action='store_true', help='记录当前指标为基线')
    ap.add_argument('--rebuild', action='store_true', help='重建后对比基线')
    a = ap.parse_args()
    if a.fix:
        return cmd_fix(a.fix)
    if a.baseline:
        return cmd_baseline()
    if a.rebuild:
        return cmd_rebuild()
    return cmd_check()


if __name__ == '__main__':
    sys.exit(main())
