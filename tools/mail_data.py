#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邮件唯一数据入口：CI 读仓库，沙箱读正式站；绝不改业务数据。"""
import collections
import hashlib
import json
import os
import re
import urllib.request

SITE_URL = 'https://zhouqingy.github.io/biz-radar/'
ITEM_FILES = ('data.items.js', 'data.chunk-lead.js', 'data.chunk-rest.js')


def parse_js(text, name):
    match = re.search(r'=\s*(\{.*\})\s*;?\s*$', text, re.S)
    if not match:
        raise ValueError('%s 不是可解析的列式/对象数据包' % name)
    return json.loads(match.group(1))


def read_local(root, name):
    with open(os.path.join(root, name), encoding='utf-8') as f:
        return f.read()


def read_online(name):
    url = SITE_URL + name + '?mail_snapshot=1'
    req = urllib.request.Request(url, headers={
        'User-Agent': 'bizradar-mail/2.0', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
    if len(raw) < 100:
        raise ValueError('%s 线上内容异常：仅 %d 字节' % (name, len(raw)))
    return raw.decode('utf-8')


def source_root():
    """显式 BIZ_OUT/BIZ_SITE 优先；只有 CI 默认读仓库，其余默认读正式站。"""
    for path in (os.environ.get('BIZ_OUT'), os.environ.get('BIZ_SITE')):
        if path and os.path.isfile(os.path.join(path, 'data.items.js')):
            return os.path.abspath(path)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.environ.get('GITHUB_ACTIONS') == 'true' and os.path.isfile(os.path.join(repo, 'data.items.js')):
        return repo
    return ''


def load_snapshot():
    root = source_root()
    reader = (lambda name: read_local(root, name)) if root else read_online
    texts = {}
    for name in ITEM_FILES + ('data.core.js', 'data.js'):
        texts[name] = reader(name)
    blocks = [parse_js(texts[name], name) for name in ITEM_FILES]
    columns = collections.defaultdict(list)
    counts = []
    for name, block in zip(ITEM_FILES, blocks):
        n = int(block.get('n') or 0)
        counts.append({'file': name, 'count': n})
        for key, values in (block.get('cols') or {}).items():
            if not isinstance(values, list) or len(values) != n:
                raise ValueError('%s 列 %s 长度与 n=%d 不一致' % (name, key, n))
            columns[key].extend(values)
    total = sum(x['count'] for x in counts)
    core = parse_js(texts['data.core.js'], 'data.core.js')
    meta = core.get('meta') or {}
    if int(meta.get('total') or 0) != total:
        raise ValueError('①库总数不一致：meta=%s，分块=%d' % (meta.get('total'), total))
    news = parse_js(texts['data.js'], 'data.js')
    if len(news.get('items') or []) != total:
        raise ValueError('data.js 与①库分块总数不一致')
    digest = (news.get('digest') or {}).get('items') or []
    items = [dict((key, values[i]) for key, values in columns.items()) for i in range(total)]
    dates = [(x.get('d') or '')[:10] for x in items if re.match(r'^20\d\d-\d\d-\d\d$', (x.get('d') or '')[:10])]
    latest = max(dates, default='')
    if latest and str(meta.get('dataAsOf') or '')[:10] != latest:
        raise ValueError('dataAsOf=%s 与①库最新公告日期=%s 不一致' % (meta.get('dataAsOf'), latest))
    return {
        'source': ('repo:' + root) if root else 'online:' + SITE_URL,
        'meta': meta, 'core': core, 'items': items, 'news': news, 'digest': digest,
        'oversea': news.get('overseaFlash') or [],
        # 产业投资既可能在快讯池，也可能已经挂在客户项目卡；两处合并后按项目键取最新状态。
        'industryPool': (news.get('overseaFlash') or []) + (news.get('overseas') or []),
        'industryOwners': tuple(x.get('name') for x in (news.get('overseas') or []) if x.get('name')),
        'policies': news.get('trends') or [], 'projects': news.get('projectNews') or [],
        'counts': {'items': total, 'overseaRaw': len(news.get('overseaFlash') or []),
                   'industryRaw': len((news.get('overseaFlash') or []) + (news.get('overseas') or [])),
                   'policies': len(news.get('trends') or []),
                   'projects': len(news.get('projectNews') or []), 'digest': len(digest)},
        'blocks': counts,
        'sha256': hashlib.sha256(''.join(texts[x] for x in sorted(texts)).encode('utf-8')).hexdigest(),
    }
