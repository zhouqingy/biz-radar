#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh_push_many.py · 一次提交推多个文件（Git Data API，原子）

════════════════════════════════════════════════════════════════════════
为什么不用 gh_put.py 一个个推
════════════════════════════════════════════════════════════════════════
gh_put.py 走 Contents API，一个文件一个提交。本轮要推 9 个文件 = 9 个提交，
而这时候 CI 的每日流程正在跑（跑完它会 pull --rebase 再 push）。
提交越多、窗口越长，撞车概率越高；一旦撞上，CI 那次 push 被拒，
「采集到的数据没提交回仓库」——下一轮又从旧数据开始。

Git Data API 能一次成树、一次提交、一次移 ref，**一个提交推完所有文件**：
  ① POST /git/blobs     每个文件一个 blob（base64）
  ② POST /git/trees     base_tree = 当前 HEAD 树，只覆盖要改的路径
  ③ POST /git/commits   parents = [当前 HEAD]
  ④ PATCH /git/refs/heads/main  force:false（非快进会报错，不硬来）

⚠ force:false 是硬要求：宁可报错让调用方决定，也不覆盖别人的提交。
   遇到 422/409 重试一次（重新取 HEAD 再成树）。

用法：
  python3.11 gh_push_many.py "提交说明" 本地1:仓库内路径1 本地2:仓库内路径2 ...
  python3.11 gh_push_many.py "提交说明" --dry-run ...   # 只看不动
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

OWNER = os.environ.get('GH_OWNER', 'zhouqingy')
REPO = os.environ.get('GH_REPO', 'biz-radar')
BRANCH = os.environ.get('GH_BRANCH', 'main')
API = 'https://api.github.com/repos/%s/%s' % (OWNER, REPO)


def _token():
    for p in ('/root/.config/bizradar/gh_token',
              os.path.expanduser('~/.config/bizradar/gh_token')):
        if os.path.isfile(p):
            return open(p).read().strip()
    return os.environ.get('GH_TOKEN', '').strip()


def api(path, token, method='GET', data=None, timeout=180):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(API + path, data=body, method=method)
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    req.add_header('User-Agent', 'bizradar-push')
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get('message', '')
        except Exception:
            msg = e.read()[:300].decode('utf-8', 'ignore')
        return None, 'HTTP %s %s' % (e.code, msg)
    except Exception as e:
        return None, str(e)


def push(pairs, msg, token, dry=False):
    for _try in range(2):
        head, err = api('/git/ref/heads/' + BRANCH, token)
        if err:
            print('❌ 取 HEAD 失败：%s' % err)
            return False
        base_sha = head['object']['sha']
        base_commit, err = api('/git/commits/' + base_sha, token)
        if err:
            print('❌ 取 base commit 失败：%s' % err)
            return False
        base_tree = base_commit['tree']['sha']
        print('基线 %s (try %d)' % (base_sha[:10], _try + 1))

        entries, total = [], 0
        for local, remote in pairs:
            if not os.path.isfile(local):
                print('  ⚠ 缺文件，跳过：%s' % local)
                continue
            raw = open(local, 'rb').read()
            total += len(raw)
            b, err = api('/git/blobs', token, 'POST',
                         {'content': base64.b64encode(raw).decode(), 'encoding': 'base64'})
            if err:
                print('  ❌ blob 失败 %s：%s' % (remote, err))
                return False
            entries.append({'path': remote, 'mode': '100644', 'type': 'blob', 'sha': b['sha']})
            print('  · blob %-46s %8.1f KB' % (remote, len(raw) / 1024.0))
        if not entries:
            print('没有可推文件')
            return True
        if dry:
            print('[dry-run] 将提交 %d 个文件、%.1f KB，未执行' % (len(entries), total / 1024.0))
            return True

        tree, err = api('/git/trees', token, 'POST', {'base_tree': base_tree, 'tree': entries})
        if err:
            print('❌ 成树失败：%s' % err)
            return False
        commit, err = api('/git/commits', token, 'POST',
                          {'message': msg, 'tree': tree['sha'], 'parents': [base_sha]})
        if err:
            print('❌ 提交失败：%s' % err)
            return False
        upd, err = api('/git/refs/heads/' + BRANCH, token, 'PATCH',
                       {'sha': commit['sha'], 'force': False})
        if err:
            print('⚠ 移 ref 失败（可能被抢先）：%s' % err)
            time.sleep(2)
            continue
        print('✅ 已推送 %s · %d 个文件 · %.1f KB · %s'
              % (commit['sha'][:10], len(entries), total / 1024.0, msg))
        return True
    print('❌ 两次都失败，放弃（没有强推，远端未被覆盖）')
    return False


def main():
    args = sys.argv[1:]
    dry = '--dry-run' in args
    args = [x for x in args if x != '--dry-run']
    if len(args) < 2:
        print(__doc__)
        return 2
    msg, rest = args[0], args[1:]
    pairs = []
    for x in rest:
        if ':' not in x:
            print('⚠ 参数格式应为 本地:仓库内路径 —— %s' % x)
            return 2
        a, b = x.split(':', 1)
        pairs.append((a, b))
    t = _token()
    if not t:
        print('缺少 token')
        return 2
    return 0 if push(pairs, msg, t, dry) else 1


if __name__ == '__main__':
    raise SystemExit(main())
