#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gh_put.py · 用 Contents API 往仓库里写文件（含子目录）

为什么单独写一个：
  publish_gh.py 只会把文件推到仓库**根目录**，而 GitHub Actions 的工作流
  必须在 .github/workflows/ 下面。沙箱里 github.com:443 不通、没法 git push，
  只能用 Contents API 逐个文件 PUT。这个脚本就是干这个的。

用法：
  python3.11 gh_put.py <本地路径> <仓库内路径>
  python3.11 gh_put.py /tmp/wf/test.yml .github/workflows/net-test.yml
"""
import base64, json, os, sys, time, urllib.request, urllib.error

OWNER = os.environ.get('GH_OWNER', 'zhouqingy')
REPO = os.environ.get('GH_REPO', 'biz-radar')
API = 'https://api.github.com/repos/%s/%s/contents/' % (OWNER, REPO)


def _token():
    for p in ('/root/.config/bizradar/gh_token',
              os.path.expanduser('~/.config/bizradar/gh_token')):
        if os.path.isfile(p):
            return open(p).read().strip()
    return os.environ.get('GH_TOKEN', '').strip()


def api(url, token, method='GET', data=None, timeout=180):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('X-GitHub-Api-Version', '2022-11-28')
    if body:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, 'HTTP %d %s' % (e.code, e.read()[:300].decode('utf-8', 'ignore'))
    except Exception as e:
        return None, str(e)


def put(local, remote, msg, token):
    raw = open(local, 'rb').read()
    sha = None
    for _ in range(3):
        d, err = api(API + remote, token)
        if d and isinstance(d, dict) and d.get('sha'):
            sha = d['sha']
        break
    payload = {'message': msg,
               'content': base64.b64encode(raw).decode()}
    if sha:
        payload['sha'] = sha
    d, err = api(API + remote, token, 'PUT', payload)
    if err and 'sha' in err.lower():
        d2, _ = api(API + remote, token)
        if d2 and d2.get('sha'):
            payload['sha'] = d2['sha']
        d, err = api(API + remote, token, 'PUT', payload)
    if err:
        print('  ❌ %s -> %s' % (remote, err[:200]))
        return False
    print('  ✅ %s  %.1f KB' % (remote, len(raw) / 1024.0))
    return True


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    local, remote = sys.argv[1], sys.argv[2]
    msg = sys.argv[3] if len(sys.argv) > 3 else '更新 %s' % remote
    t = _token()
    if not t:
        print('缺少 token')
        sys.exit(2)
    sys.exit(0 if put(local, remote, msg, t) else 1)
