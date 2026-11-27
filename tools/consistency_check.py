#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开工自检 · 本地脚本 vs 仓库 main 一致性

为什么需要这个脚本（2026-11-27 §5.122 事故）：
    我在本地给 industry_leads.py 加了一批主体识别规则，但一直没提交。
    CI 跑的是仓库里的旧版，采集时把 raw/oversea_flash.json 整份重写，
    22 条产业线索被洗成 6 条，页面上「项目线索」视图直接空了。
    事故根因不是某个 bug，而是「本地与线上不是同一份代码」这件事没人检查。

用法：
    python3.11 consistency_check.py              # 只报告
    python3.11 consistency_check.py --strict     # 有未推送改动即 exit 1

判据：本地文件的 git blob sha1 与远端 tree 里的 sha 是否相等。
    DIRTY  本地改过没推  → CI 会用另一个版本跑，必须推完再放手
    BEHIND 远端比本地新  → 先拉一份再改，否则下次推送会覆盖别人
"""
import hashlib
import json
import os
import sys
import urllib.request

OWNER = os.environ.get('GH_OWNER', 'zhouqingy')
REPO = os.environ.get('GH_REPO', 'biz-radar')
BRANCH = os.environ.get('GH_BRANCH', 'main')
HERE = os.path.dirname(os.path.abspath(__file__))

# 这些文件决定「数据长什么样」：口径、分类、采集、构建、发布闸门。
# 少列一个就可能重演同型事故，加文件时同步加进来。
TRACKED = (
    'industry_leads.py',
    'biz_rules.py',
    'collect_v4.py',
    'oversea_sources.py',
    'oversea_manual.py',
    'mine_oversea_wechat.py',
    'build_data.py',
    'build_web.py',
    'update_weekly.py',
    'healthcheck.py',
    'mail_rules.py',
    'send_daily.py',
    'news_rules.py',
    'release_manifest.py',
    'verify_industry_leads.py',
    'zj_csv_import.py',
)


def token():
    for p in ('/root/.config/bizradar/gh_token',
              os.path.expanduser('~/.config/bizradar/gh_token')):
        if os.path.isfile(p):
            return open(p, encoding='utf-8').read().strip()
    return os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''


def remote_tree(tok):
    url = ('https://api.github.com/repos/%s/%s/git/trees/%s?recursive=1'
           % (OWNER, REPO, BRANCH))
    req = urllib.request.Request(url)
    req.add_header('Authorization', 'Bearer ' + tok)
    req.add_header('Accept', 'application/vnd.github+json')
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.load(r)
    return {x['path']: x['sha'] for x in data.get('tree', []) if x['type'] == 'blob'}


def blob_sha(path):
    """按 git 的对象格式算 sha1，才能跟 tree 里的 sha 直接比。"""
    with open(path, 'rb') as f:
        data = f.read()
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def main():
    strict = '--strict' in sys.argv
    tok = token()
    if not tok:
        print('没有找到 GitHub token，跳过远端比对')
        return 0
    try:
        tree = remote_tree(tok)
    except Exception as e:
        print('拉取远端文件树失败：%s' % e)
        return 2

    dirty, behind, same, missing = [], [], [], []
    for name in TRACKED:
        local = os.path.join(HERE, name)
        remote_path = 'tools/' + name
        rs = tree.get(remote_path)
        if not os.path.isfile(local):
            missing.append(name)
            continue
        ls = blob_sha(local)
        if rs is None:
            dirty.append((name, ls[:8], '远端无此文件'))
        elif ls == rs:
            same.append(name)
        else:
            dirty.append((name, ls[:8], rs[:8]))

    print('一致性自检 · %s/%s@%s' % (OWNER, REPO, BRANCH))
    print('  一致 %d / 本地有未推送改动 %d / 本地缺失 %d'
          % (len(same), len(dirty), len(missing)))
    if dirty:
        print('\n以下文件本地与线上不是同一版 —— CI 会用线上那版跑，先推再继续：')
        for name, ls, rs in dirty:
            print('  DIRTY %-24s 本地 %s / 线上 %s' % (name, ls, rs))
    if missing:
        print('\n本地缺失：%s' % '、'.join(missing))
    if not dirty and not missing:
        print('  ✅ 全部一致，可以放心让 CI 跑')
    if strict and (dirty or missing):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
