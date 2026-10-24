#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Pages 发布器 · publish_gh.py
===================================
把 /workspace/biz-radar 下的 index.html + data.js 推到 GitHub 仓库，
由 GitHub Pages 自动渲染。域名恒定，不绑沙箱。

为什么用它替代 publish.js：
  workbuddy 沙箱发布的域名 = 'a' + md5(AGENTOS_RUNTIME_ID) 前16位，
  后端鉴权绑沙箱身份 —— 定时任务每次落在新沙箱，注入别人的 runtimeId
  会被 403 runtimeId mismatch 拒绝（2026-10-15 实测确认）。
  GitHub Pages 的域名只跟账号/仓库名绑定，任何沙箱都能推。

为什么用 REST API 而不是 git push：
  沙箱内 github.com:443 不通（实测连接超时 136s），但 api.github.com 通。
  Contents API 走 443 的 api 域名，稳定可用。

用法：
  GH_TOKEN=github_pat_xxx python3.11 publish_gh.py
  python3.11 publish_gh.py --token github_pat_xxx
  python3.11 publish_gh.py --dry-run          # 只体检不推送

环境变量：
  GH_TOKEN       GitHub fine-grained token（只需目标仓库 Contents: Read and write）
  GH_OWNER       默认 zhouqingy
  GH_REPO        默认 biz-radar
  BIZ_SITE       默认 /workspace/biz-radar
"""
import argparse, base64, hashlib, json, os, sys, time, urllib.request

OWNER = os.environ.get('GH_OWNER', 'zhouqingy')
REPO = os.environ.get('GH_REPO', 'biz-radar')
SITE = os.environ.get('BIZ_SITE') or '/workspace/biz-radar'
API = 'https://api.github.com/repos/%s/%s' % (OWNER, REPO)
PAGES_URL = 'https://%s.github.io/%s/' % (OWNER.lower(), REPO)
# 2026-10-21：页面已拆成分模块（core/items/items.all/org/news）+ 启动器 boot.js。
# 原来这里只推 data.js 单文件，新页面在线上会因为取不到 data.core.js 直接白屏。
FILES = ('index.html',
         'boot.js',
         'data.core.js',
         'data.items.js',        # 首屏 400 条关注档
         'data.chunk-lead.js',   # 立项线索 637 条（点「💡 立项线索」才拉）
         'data.chunk-rest.js',   # 其余 917 条（点「全部」/ 搜索才拉）
         'data.org.js',          # 同业 / 业主 / 客户
         'data.graph.js',        # 业主图谱（进图谱子页才拉）
         # 2026-10-22 补：data.siku.js 是进「业主画像图谱」子页时**同时**去拉的
         # （四库信用代码，给档案里的「身份信息」用）。它从来没在这个清单里，
         # 线上一直 404，控制台每次都报一条红字。功能上会降级成「去四库一平台查」
         # 的跳转链接，所以一直没人发现——但它确实一直在报错。
         'data.siku.js',
         'data.news.js',
         'data.rivalperf.js',  # 2026-10-24 对手/业主全网业绩库（画像弹层用）
         'data.js',            # 整包兜底：任一模块加载失败时前端会回退到它
         'rival.js',
         'rival-cuc.html',
         'rival-compare.html')


def api(path, token, method='GET', data=None, timeout=300):
    body = json.dumps(data).encode('utf-8') if data is not None else None
    req = urllib.request.Request(API + path, data=body, method=method)
    req.add_header('Authorization', 'Bearer ' + token)
    req.add_header('Accept', 'application/vnd.github+json')
    req.add_header('User-Agent', 'bizradar-publisher')
    if body is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout)), None
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get('message', '')
        except Exception:
            msg = e.read()[:200].decode('utf-8', 'ignore')
        return None, 'HTTP %s %s' % (e.code, msg)
    except Exception as e:
        return None, str(e)


def get_sha(name, token, retry=3):
    """取远端文件 sha。

    注意 None 有两种含义：文件确实不存在（返回 404）／ 请求本身失败了。
    以前不区分，网络抖一下就拿 None 当「新建文件」去 PUT，GitHub 直接回
    422 Invalid request. "sha" wasn't supplied. —— 大文件偶发失败就是这么来的。
    现在只有确认 404 才返回 None，其它错误重试后抛出来，绝不带着空 sha 去写。
    """
    for i in range(retry):
        d, err = api('/contents/' + name, token)
        if not err:
            return d.get('sha') if isinstance(d, dict) else None
        if '404' in str(err) or 'Not Found' in str(err):
            return None                      # 真的不存在，可以新建
        time.sleep(1.5 * (i + 1))
    raise RuntimeError('获取 %s 的 sha 失败（已重试 %d 次）：%s' % (name, retry, err))


def verify_remote(name, raw, token, retry=4):
    """推完回读校验（2026-10-23 事故后新增）。

    ══════════ 为什么必须有这一道 ══════════
    2026-10-23 16:04，publish_gh.py 打印了一整屏「✅ index.html 0.25 MB 2 秒」，
    最后还来一句「✅ 已推送，Pages 约 1-2 分钟生效」。结果远端仓库里
    index.html 仍是 108,768 字节的旧版，sha 一点没变。

    原因：Contents API 偶尔在网关层就返回了 200/201，但对象没有真正落盘
    （那次的伴随症状是另一个文件报 HTTP 403 "The rule did not run because
    of a timeout"）。HTTP 200 只代表「请求被受理」，不代表「字节已写入」。

    这道校验做的事：GET 回来，比对比 git blob sha（== 本地算出来的一致）和
    size。不一致就等一等再查，超过 retry 次才算真失败。
    宁可多花几秒，也不要再让用户对着一句「已推送」白等六分钟。
    """
    want_sha = hashlib.sha1(b'blob %d\x00' % len(raw) + raw).hexdigest()
    last = ''
    for i in range(retry):
        d, err = api('/contents/' + name, token)
        if err:
            last = str(err)
        else:
            got_sha = (d.get('sha') or '') if isinstance(d, dict) else ''
            got_sz = d.get('size') if isinstance(d, dict) else None
            if got_sha == want_sha and got_sz == len(raw):
                return True, ''
            last = 'sha %s→%s / size %s→%s' % (
                want_sha[:8], got_sha[:8] or '空', len(raw), got_sz)
        time.sleep(2 + i * 2)
    return False, last


def put_file(name, token, dry=False):
    path = os.path.join(SITE, name)
    if not os.path.isfile(path):
        print('  ❌ %s 不存在，跳过' % name)
        return False
    raw = open(path, 'rb').read()
    try:
        sha = get_sha(name, token)
    except Exception as e:
        # 网络读取不稳定（IncompleteRead 等）时不硬失败：
        # 记下来让外层下一轮补推，整个发布流程不至于中断。
        print('  ⏳ %s  取 sha 失败，稍后补推（%s）' % (name, str(e)[:60]))
        return False
    if dry:
        print('  [dry-run] %s  %.2f MB  sha=%s' % (name, len(raw) / 1048576.0,
                                                   (sha or '新建')[:8]))
        return True
    payload = {
        'message': '商机雷达数据更新 %s' % time.strftime('%Y-%m-%d %H:%M'),
        'content': base64.b64encode(raw).decode(),
    }
    if sha:
        payload['sha'] = sha
    t0 = time.time()
    d, err = api('/contents/' + name, token, 'PUT', payload)
    if err and 'sha' in str(err).lower():
        # 远端这次没给 sha（或我们传的过期了）：重新取一次再试。
        # 2026-10-23 事故：这里第二次 get_sha 自己也可能 IncompleteRead，
        # 异常一路冒泡到 main() 把整个发布进程干掉——后面 6 个文件全没推。
        # 取 sha 是「可以重来的事」，不该终止整轮发布：包成 try，失败就交补推。
        try:
            sha2 = get_sha(name, token, retry=5)
        except Exception as e2:
            print('  ⏳ %s  复取 sha 失败，稍后补推（%s）' % (name, str(e2)[:60]))
            return False
        if sha2:
            payload['sha'] = sha2
        d, err = api('/contents/' + name, token, 'PUT', payload)
    if err:
        print('  ❌ %s -> %s' % (name, str(err)[:120]))
        return False

    # 回读校验：HTTP 200 不等于字节落盘，必须 GET 回来比对 sha + size。
    ok, why = verify_remote(name, raw, token)
    if not ok:
        print('  ❌ %s  写入未生效（远端不符：%s）' % (name, why[:100]))
        return False

    print('  ✅ %s  %.2f MB  %d 秒  已回读校验'
          % (name, len(raw) / 1048576.0, time.time() - t0))
    return True


def read_total(path):
    """从 data.js 里取 meta.total，用于防倒退比对"""
    try:
        # meta 在 2MB 文件里位置不定（metals 排在最前），只读前几千字符会漏掉，
        # 这里全文匹配第一个 "total"
        s = open(path, encoding='utf-8').read()
        import re as _re
        m = _re.search(r'"total"\s*:\s*(\d+)', s)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def guard_rollback(force=False):
    """
    防倒退闸门：新数据条目数比上一版掉太多，就拦下不推。
    跨沙箱重建时个别渠道会抓失败（实测波动 1467→1437），
    没有这道闸门会把残缺数据直接推上线。
    """
    cur = os.path.join(SITE, 'data.js')
    bak = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.js.bak')
    n_cur, n_bak = read_total(cur), read_total(bak)
    if not n_cur or not n_bak:
        print('[闸门] 上一版或本版 total 读不到，跳过比对')
        return True
    drop = (n_bak - n_cur) / float(n_bak)
    if drop > 0.03:
        print('[闸门] ❌ 条目数倒退 %.1f%%（上一版 %d → 本版 %d），已阻止推送'
              % (drop * 100, n_bak, n_cur))
        print('       常见原因：新沙箱里某个抓取渠道失败。确认无误可加 --force 强制推送')
        return force
    if drop < -0.5:
        print('[闸门] ⚠ 条目数暴涨 %.1f%%（%d → %d），请确认不是脏数据'
              % (-drop * 100, n_bak, n_cur))
    else:
        print('[闸门] ✅ 条目数 %d → %d（%+.1f%%），正常' % (n_bak, n_cur, -drop * 100))
    return True


def guard_index_html(force=False):
    """index.html 体积闸门（2026-10-23 事故后新增）。

    ══════════ 为什么必须有这一道 ══════════
    2026-10-22 16:08，我推了一次 index.html，体积从 264,790 → 108,768 字节，
    把用户在线上迭代了好几天的版本（新增「中标情报 / 业主图谱 / 合作生态」三个面板）
    整个冲掉，退回到 10-21 的旧备份。用户第二天看到页面"样式又改回去了"。

    根因：本地 /workspace/biz-radar/index.html 只是旧备份的拷贝，不是源码；
    真实源码在用户手上、在仓库里。我在陈旧文件上改完直接推 = 悄悄回滚。

    这道闸门只防「体积大幅缩水」这一种最容易发生的误覆盖：
    HTML 是加法演进的，正常更新体积只会缓慢上涨；
    一次掉 20% 以上，几乎只能是拿旧文件盖了新文件。
    """
    cur = os.path.join(SITE, 'index.html')
    bak = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html.bak')
    if not (os.path.isfile(cur) and os.path.isfile(bak)):
        print('[闸门] index.html 无可比基线，跳过（首次推送正常）')
        return True
    a, b = os.path.getsize(bak), os.path.getsize(cur)
    if not b:
        print('[闸门] ❌ 本版 index.html 是空文件，已阻止推送')
        return force
    chg = (b - a) / float(a)
    if chg < -0.20:
        print('[闸门] ❌ index.html 体积骤降 %.0f%%（%d → %d 字节），疑似用旧文件覆盖了新页面'
              % (chg * 100, a, b))
        print('       确认是有意精简可加 --force；否则先在线上取回最新版再改')
        return force
    print('[闸门] ✅ index.html %d → %d 字节（%+.0f%%）' % (a, b, chg * 100))
    return True


def _read_saved_token():
    """读本地保存的 token，免去每次手动传 --token"""
    for p in ('/root/.config/bizradar/gh_token',
              os.path.expanduser('~/.config/bizradar/gh_token')):
        try:
            if os.path.isfile(p):
                return open(p).read().strip()
        except Exception:
            pass
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token', default=os.environ.get('GH_TOKEN', ''))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='跳过防倒退闸门')
    a = ap.parse_args()

    token = a.token.strip() or _read_saved_token()
    if not token:
        print('[publish_gh] 缺少 token：用 --token 或环境变量 GH_TOKEN')
        return 2
    if not token.startswith(('github_pat_', 'ghp_')):
        print('[publish_gh] ⚠ token 格式看起来不对（应为 github_pat_ 或 ghp_ 开头）')

    # 体检：本地数据
    dj = os.path.join(SITE, 'data.js')
    stamp = '?'
    if os.path.isfile(dj):
        head = open(dj, encoding='utf-8').read(3000)
        import re as _re
        m = _re.search(r'"updated":"([^"]+)"', head)
        if m:
            stamp = m.group(1)
    print('[publish_gh] 目标 %s · 本地数据日期 %s' % (PAGES_URL, stamp))

    d, err = api('', token, timeout=60)
    if err:
        print('[publish_gh] ❌ 仓库不可访问：%s' % err)
        print('           检查 GH_OWNER/GH_REPO、token 是否授权了该仓库的 Contents 写权限')
        return 3
    print('[publish_gh] 仓库 %s（%s）' % (d.get('full_name'), '私有' if d.get('private') else '公开'))

    if not guard_rollback(a.force):
        return 5
    if not guard_index_html(a.force):
        return 6

    # 网络不稳（到 GitHub API 偶发 IncompleteRead / 空 sha）时，失败的文件
    # 自动再补推两轮，中间歇 3 秒。实测一轮 12 个文件里常有一两个需要重来。
    failed = []
    for f in FILES:
        if not put_file(f, token, a.dry_run):
            failed.append(f)
    # 2026-10-23：网络 IncompleteRead 频发，2 轮补推不够（实测一轮 16 个文件里
    # 有 4~5 个要重来）。加到 4 轮，每轮之间多歇一会儿让链路缓过来。
    for attempt in range(4):
        if not failed:
            break
        print('[publish_gh] 补推第 %d 轮：%s' % (attempt + 1, ', '.join(failed)))
        time.sleep(5 + attempt * 5)
        still = []
        for f in failed:
            if not put_file(f, token, a.dry_run):
                still.append(f)
        failed = still
    if failed:
        print('\n[publish_gh] ❌ 仍有 %d 个文件未推成功：%s' % (len(failed), ', '.join(failed)))
        return 4

    if a.dry_run:
        print('\n[publish_gh] dry-run 结束，未推送')
        return 0

    print('\n[publish_gh] ✅ 已推送，Pages 约 1-2 分钟生效')
    print('[publish_gh] ' + PAGES_URL)

    # 落心跳，供人工判定
    try:
        import re as _re
        root = os.path.dirname(os.path.abspath(__file__))
        hb = {'task': 'publish_gh.py', 'time': time.strftime('%Y-%m-%d %H:%M'),
              'shareLink': PAGES_URL.rstrip('/'), 'expectedHost': '%s.github.io' % OWNER.lower(),
              'ok': True, 'drift': False, 'note': 'GitHub Pages 推送成功，域名恒定'}
        p = os.path.join(root, 'raw')
        os.makedirs(p, exist_ok=True)
        json.dump(hb, open(os.path.join(p, '心跳_GitHub.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print('[心跳] 已写入 raw/心跳_GitHub.json')
    except Exception as e:
        print('[心跳] 写入失败：%s' % e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
