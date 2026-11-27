#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商机雷达 · 统一发布清单、防回退闸门与 Pages 回读。

只读取构建产物，不采集、不改业务数据、不调用或重写 biz_rules.py。

用法（仓库根目录）：
  python tools/release_manifest.py build --root . --scope daily
  python tools/release_manifest.py build --root . --scope digest
  python tools/release_manifest.py build --root . --scope metals
  python tools/release_manifest.py verify-online --root . --scope daily \
      --base-url https://zhouqingy.github.io/biz-radar

scope 只决定本次必须完整检查的模块；清单始终保留上一版的其他模块指标。
BIZ_EXPECT_DATE=YYYY-MM-DD 可要求行情当日与全部历史端点 dated 到该日。
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

SCHEMA = 1
DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})')
CORE_FILES = (
    'index.html', 'boot.js', 'data.core.js', 'data.items.js',
    'data.chunk-lead.js', 'data.chunk-rest.js', 'data.news.js', 'data.js',
    'data.plan.js', 'data.changes.js', 'data.metalhist.js', 'data.org.js',
    'data.graph.js', 'data.ovprofile.js', 'data.policy.js', 'data.entprobe.js',
    'data.rivalperf.js', 'data.siku.js', 'data.candperf.js',
)
VERIFY_FILES = {
    'daily': ('data.core.js', 'data.items.js', 'data.chunk-lead.js',
              'data.chunk-rest.js', 'data.news.js', 'data.changes.js',
              'data.plan.js', 'data.metalhist.js', 'data.js'),
    'digest': ('data.js', 'data.news.js'),
    'metals': ('data.core.js', 'data.metalhist.js'),
}


class GateError(RuntimeError):
    pass


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def read_js(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    try:
        return json.loads(text[text.index('{'):text.rindex('}') + 1])
    except Exception as exc:
        raise GateError('无法解析 %s：%s' % (path, exc))


def day(value):
    m = DATE_RE.match(str(value or '').strip())
    return m.group(1) if m else ''


# 金属历史端点容忍度（2026-11-27）：新浪不同品种日 K 落库时间不一致，
# 允许「落后 1 个自然日 + 最多 3 个品种」，超出即视为真抓取失败。
MAX_STALE_DAYS = 3
MAX_STALE_SYMBOLS = 3


def date_of(text):
    try:
        return dt.date.fromisoformat(str(text))
    except Exception:
        return dt.date(1970, 1, 1)


def latest(rows):
    dates = [day(x.get('d') or x.get('date')) for x in (rows or []) if isinstance(x, dict)]
    return max((x for x in dates if x), default='')


def digest_metric(obj):
    obj = obj or {}
    return {'count': len(obj.get('items') or []), 'updated': str(obj.get('updated') or '')}


def metrics(root, scope):
    """只计算本次职责范围内的指标；daily 是全量快照。"""
    out = {}
    if scope in ('daily', 'digest'):
        news = read_js(os.path.join(root, 'data.news.js'))
        full = read_js(os.path.join(root, 'data.js'))
        dg = digest_metric(news.get('digest'))
        dg_full = digest_metric(full.get('digest'))
        if dg != dg_full:
            raise GateError('digest 在 data.news.js 与 data.js 不一致：%s != %s' % (dg, dg_full))
        raw_path = os.path.join(root, 'tools', 'raw', 'digest.json')
        if os.path.isfile(raw_path):
            dg_raw = digest_metric(read_json(raw_path))
            if dg != dg_raw:
                raise GateError('digest 页面产物与 raw/digest.json 不一致：%s != %s' % (dg, dg_raw))
        out['digest'] = dg
    if scope == 'daily':
        core = read_js(os.path.join(root, 'data.core.js'))
        meta = core.get('meta') or {}
        blocks = []
        dates = []
        for name in ('data.items.js', 'data.chunk-lead.js', 'data.chunk-rest.js'):
            block = read_js(os.path.join(root, name))
            n = int(block.get('n') or 0)
            blocks.append({'file': name, 'count': n})
            dates += [day(x) for x in (block.get('cols') or {}).get('d', [])]
        chunk_total = sum(x['count'] for x in blocks)
        core_total = int(meta.get('total') or 0)
        if core_total != chunk_total:
            raise GateError('core.meta.total=%d，但三块①库合计=%d' % (core_total, chunk_total))
        declared = {str(x.get('name') or ''): int(x.get('n') or 0) for x in (meta.get('chunks') or [])}
        actual = {x['file'].replace('data.chunk-', '').replace('.js', ''): x['count']
                  for x in blocks if x['file'].startswith('data.chunk-')}
        for name, count in actual.items():
            if declared.get(name) != count:
                raise GateError('分块元数据不一致：%s 声明=%s，实际=%d' % (name, declared.get(name), count))
        max_item_date = max((x for x in dates if x), default='')
        out['items'] = {'total': core_total, 'dataAsOf': str(meta.get('dataAsOf') or ''),
                        'latestItemDate': max_item_date, 'blocks': blocks}
        # 2026-11-27 §5.123：产业投资线索（海外机会 · 项目线索视图）单独计数。
        #   事故背景：raw 里 81 条新闻、22 条线索，被 CI 用旧分类器整份重写后
        #   变成 78 条新闻、6 条线索 —— 条数只掉 3 条，旧的 count 检查完全看不出来，
        #   但页面上「项目线索」整个视图空了。必须按 leadKey 计数单独防回退。
        _flash = news.get('overseaFlash') or []
        _leads = [x for x in _flash if str(x.get('leadKey') or '').strip()]
        out['overseaFlash'] = {'count': len(_flash), 'leads': len(_leads),
                               'leadsLatest': latest(_leads) if _leads else '',
                               'latestDate': latest(_flash)}
        changes = read_js(os.path.join(root, 'data.changes.js'))
        kpi = changes.get('kpi') or {}
        changes_total = int(kpi.get('libTotal') or 0)
        if changes_total != core_total:
            raise GateError('本周变化 libTotal=%d，①库=%d，不是同一快照' % (changes_total, core_total))
        if day(changes.get('asOf')) != max_item_date:
            raise GateError('本周变化 asOf=%s，①库最新日期=%s，不是同一快照'
                            % (changes.get('asOf'), max_item_date))
        out['changes'] = {'libTotal': changes_total, 'asOf': day(changes.get('asOf'))}
        health_path = os.path.join(root, '数据质量体检.json')
        if os.path.isfile(health_path):
            health = read_json(health_path)
            summary = health.get('summary') or {}
            errors = int(summary.get('errors') or 0)
            out['health'] = {'errors': errors, 'warnings': int(summary.get('warns') or 0),
                             'generated': str(health.get('gen') or '')}
            if errors:
                raise GateError('数据质量体检存在 %d 个阻断错误，停止发布' % errors)
        plan = read_js(os.path.join(root, 'data.plan.js'))
        out['plan'] = {'count': int(plan.get('n') or 0), 'gen': str(plan.get('gen') or '')}
    if scope in ('daily', 'metals'):
        core = read_js(os.path.join(root, 'data.core.js'))
        metals = core.get('metals') or {}
        items = metals.get('items') or []
        hist = read_js(os.path.join(root, 'data.metalhist.js'))
        series = hist.get('s') or {}
        ends = sorted({day(v.get('end')) for v in series.values() if day(v.get('end'))})
        # 2026-11-27 修：原来要求「所有品种端点必须完全一致」，任一品种当天未固化
        #   （新浪不同品种日 K 落库时间不一致，如 SN 沪锡常晚于其余品种）就整轮判红，
        #   结果是 20 个品种全都不发布，比缺一个更糟。
        #   现口径：以最新端点为基准，允许少量品种落后 1 个交易日；超出即判红。
        #   —— 仍有下限保护：真正的抓取失败会造成大面积或长期落后，不会被放过。
        stale = {}
        if len(ends) > 1:
            newest = ends[-1]
            older = ends[:-1]
            if len(older) > 1 or (newest and older and
                                   (date_of(newest) - date_of(older[-1])).days > MAX_STALE_DAYS):
                detail = sorted('%s(%s)：%s' % (code, v.get('n') or '未命名', day(v.get('end')))
                                for code, v in series.items())
                raise GateError('金属历史端点不一致：%s；品种明细：%s' % (ends, '、'.join(detail)))
            stale = {code: day(v.get('end')) for code, v in series.items()
                     if day(v.get('end')) != newest}
            if len(stale) > MAX_STALE_SYMBOLS:
                raise GateError('金属历史落后品种过多（%d 个 > 上限 %d）：%s'
                                % (len(stale), MAX_STALE_SYMBOLS, stale))
            print('::warning::金属历史有 %d 个品种落后于最新端点 %s：%s（不阻断发布）'
                  % (len(stale), newest, stale))
        out['metals'] = {'count': len(items), 'updated': day(metals.get('updated')),
                         'historyCount': len(series), 'historyEnds': ends,
                         'historyLatest': ends[-1] if ends else None,
                         'historyStale': stale,
                         'historyGenerated': day(hist.get('updated'))}
    return out


def file_metrics(root):
    files = {}
    for name in CORE_FILES:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path, 'rb') as f:
            raw = f.read()
        files[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return files


def check_regressions(old, new, scope):
    if not old:
        return []
    errors = []
    old_modules = old.get('modules') or {}
    new_modules = new.get('modules') or {}
    keys = {
        'daily': ('items', 'digest', 'overseaFlash', 'changes', 'plan', 'metals'),
        'digest': ('digest',),
        'metals': ('metals',),
    }[scope]
    date_fields = {
        'items': ('dataAsOf', 'latestItemDate'), 'digest': ('updated',),
        'overseaFlash': ('latestDate',), 'changes': ('asOf',),
        'plan': ('gen',), 'metals': ('updated', 'historyGenerated'),
    }
    for key in keys:
        before = old_modules.get(key) or {}
        after = new_modules.get(key) or {}
        for field in date_fields[key]:
            a, b = day(before.get(field)), day(after.get(field))
            if a and b and b < a:
                errors.append('%s.%s 日期回退：%s → %s' % (key, field, a, b))
    if scope == 'daily':
        a = int((old_modules.get('items') or {}).get('total') or 0)
        b = int((new_modules.get('items') or {}).get('total') or 0)
        if a and b < a * 0.75:
            errors.append('①库条数骤降超过 25%%：%d → %d' % (a, b))
        a = int((old_modules.get('plan') or {}).get('count') or 0)
        b = int((new_modules.get('plan') or {}).get('count') or 0)
        if a and b < a * 0.70:
            errors.append('规划前瞻条数骤降超过 30%%：%d → %d' % (a, b))
        # 2026-11-27 §5.123：产业投资线索防回退（本次事故的直接护栏）。
        #   线索条数取决于分类器能识别多少中资主体，一旦 CI 跑在旧版
        #   industry_leads.py 上，新闻还在、线索全没，页面「项目线索」视图直接空。
        #   阈值取 60%：正常的每日波动不会腰斩；分类器回退、raw 被覆盖会。
        a = int((old_modules.get('overseaFlash') or {}).get('leads') or 0)
        b = int((new_modules.get('overseaFlash') or {}).get('leads') or 0)
        if a >= 5 and b < a * 0.60:
            if b == 0:
                errors.append('产业投资线索归零：上次 %d 条，本次 0 条'
                              '（排查 industry_leads.py 版本、raw/oversea_flash.json 是否被整份重写）' % a)
            else:
                errors.append('产业投资线索骤降超过 40%%：%d → %d'
                              '（排查 industry_leads.py 是否为仓库最新版、raw/oversea_flash.json 是否被整份重写）'
                              % (a, b))
        # 即使上一版清单里还没有 leads 指标（首次上线本检查），也不允许「有新闻、零线索」。
        _nf = int((new_modules.get('overseaFlash') or {}).get('count') or 0)
        if _nf >= 20 and b == 0:
            errors.append('产业投资线索为 0：速览 %d 条新闻一条都没识别出线索，分类器疑似失效' % _nf)
    if scope in ('daily', 'digest'):
        a = int((old_modules.get('digest') or {}).get('count') or 0)
        b = int((new_modules.get('digest') or {}).get('count') or 0)
        if a and b < a * 0.50:
            errors.append('情报精选条数骤降超过 50%%：%d → %d' % (a, b))
        if b < 1:
            errors.append('情报精选为空')
    if scope in ('daily', 'metals'):
        m = new_modules.get('metals') or {}
        old_n = int((old_modules.get('metals') or {}).get('count') or 0)
        if int(m.get('count') or 0) < 10 or int(m.get('historyCount') or 0) < 10:
            errors.append('金属行情品种不足 10 个：%s' % m)
        if old_n and int(m.get('count') or 0) < old_n:
            errors.append('金属行情品种减少：%d → %d' % (old_n, m.get('count')))
    return errors


def build(args):
    root = os.path.abspath(args.root)
    out_path = os.path.join(root, 'release-manifest.json')
    old = read_json(out_path) if os.path.isfile(out_path) else None
    current = metrics(root, args.scope)
    result = {
        'schema': SCHEMA,
        'run': {
            'id': os.environ.get('GITHUB_RUN_ID') or 'local',
            'attempt': os.environ.get('GITHUB_RUN_ATTEMPT') or '1',
            'workflow': os.environ.get('GITHUB_WORKFLOW') or args.scope,
            'baseSha': os.environ.get('GITHUB_SHA') or '',
            'builtAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
            'scope': args.scope,
            'sourceHealth': os.environ.get('BIZ_SOURCE_HEALTH') or '',
        },
        'modules': dict((old or {}).get('modules') or {}),
        'files': file_metrics(root),
    }
    result['modules'].update(current)
    errors = check_regressions(old, result, args.scope)
    expected = day(os.environ.get('BIZ_EXPECT_DATE'))
    if expected and args.scope in ('daily', 'metals'):
        m = current.get('metals') or {}
        if m.get('updated') != expected:
            errors.append('当日行情不是 %s：%s（可能回退了缓存）' % (expected, m.get('updated')))
        if m.get('historyEnds') != [expected]:
            errors.append('历史行情端点未统一到 %s：%s' % (expected, m.get('historyEnds')))
    if args.scope == 'daily':
        if int((current.get('items') or {}).get('total') or 0) <= 0:
            errors.append('①库为空')
        if int((current.get('plan') or {}).get('count') or 0) <= 0:
            errors.append('规划前瞻为空')
    if errors and not args.allow_regression:
        for e in errors:
            print('::error::' + e, file=sys.stderr)
        raise GateError('发布闸门未通过；未改写 release-manifest.json')
    for e in errors:
        print('::warning::已显式允许回退：' + e)
    tmp = out_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(tmp, out_path)
    print('发布清单已生成：scope=%s · modules=%d · files=%d · %s'
          % (args.scope, len(result['modules']), len(result['files']), out_path))
    for key in sorted(current):
        print('  %s: %s' % (key, json.dumps(current[key], ensure_ascii=False)))
    return 0


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'bizradar-release-verifier', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def verify_online(args):
    root = os.path.abspath(args.root)
    manifest = read_json(os.path.join(root, 'release-manifest.json'))
    run_id = ((manifest.get('run') or {}).get('id') or 'local')
    errors = []
    for name in VERIFY_FILES[args.scope]:
        expected = (manifest.get('files') or {}).get(name) or {}
        if not expected.get('sha256'):
            errors.append('清单缺少 ' + name)
            continue
        url = '%s/%s?release=%s&sha=%s' % (
            args.base_url.rstrip('/'), name, run_id, expected['sha256'][:16])
        last = ''
        for attempt in range(args.attempts):
            try:
                raw = fetch(url)
                got = hashlib.sha256(raw).hexdigest()
                if got == expected['sha256'] and len(raw) == expected.get('bytes'):
                    print('线上回读通过：%s · %d bytes' % (name, len(raw)))
                    break
                last = 'sha256/bytes 不符：got=%s/%d' % (got[:12], len(raw))
            except Exception as exc:
                last = str(exc)
            if attempt + 1 < args.attempts:
                time.sleep(args.delay)
        else:
            errors.append('%s 未通过线上回读：%s' % (name, last))
    if errors:
        for e in errors:
            print('::error::' + e, file=sys.stderr)
        return 1
    print('Pages 线上回读全部通过：scope=%s · run=%s' % (args.scope, run_id))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    for command in ('build', 'verify-online'):
        p = sub.add_parser(command)
        p.add_argument('--root', default='.')
        p.add_argument('--scope', choices=tuple(VERIFY_FILES), required=True)
        if command == 'build':
            p.add_argument('--allow-regression', action='store_true',
                           help='仅用于人工确认的异常发布；默认禁止')
        else:
            p.add_argument('--base-url', default='https://zhouqingy.github.io/biz-radar')
            p.add_argument('--attempts', type=int, default=12)
            p.add_argument('--delay', type=int, default=10)
    args = ap.parse_args()
    try:
        return build(args) if args.command == 'build' else verify_online(args)
    except (GateError, FileNotFoundError, KeyError, ValueError) as exc:
        print('::error::%s' % exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
