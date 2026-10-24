#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉域名发布 · Pinned Publish
===========================
根治「沙箱漂移导致网址变化」的执行器。

原理（读完 lib.js 后确认）：
  域名 =  'a' + md5(AGENTOS_RUNTIME_ID)[0:16]
  getOrCreateAppName() 只在 state.runtimeId !== 当前env 时**重新生成** appName。
  所以只要发布前把 ~/.workbuddy-sandbox-publish/state.json 写成
      {runtimeId: <本沙箱真实ID>, appName: <publish.conf 钉死的值>}
  两者对齐 → 不重新生成 → 无论沙箱怎么漂，appName 恒定 → 网址恒定。
  后端 createArtifactRelease 只拿 appName 当域名、拿 runtimeId 标发布来源，
  两者不必同源，因此跨沙箱钉域名成立。

另附一层保险：PIN_RUNTIME_ID（可选）。若 publish.conf 第二行写了当年生成该
域名的原始 runtimeId，则直接把 AGENTOS_RUNTIME_ID 注入为它，连 md5 结果都一致。
"""
import json, os, subprocess, sys, time, re

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get('BIZ_SITE') or '/workspace/biz-radar'
PIN_FILE = os.path.join(ROOT, 'publish.conf')
PUB_STATE = os.path.expanduser('~/.workbuddy-sandbox-publish/state.json')
DEFAULT_PIN = 'a60be47466efe1223'


def read_conf():
    """publish.conf 第一行=对外域名前缀；第二行可选=原始 runtimeId"""
    pin, rid = DEFAULT_PIN, ''
    try:
        lines = [l.strip() for l in open(PIN_FILE, encoding='utf-8') if l.strip()]
        if lines:
            pin = lines[0].split()[0]
        if len(lines) > 1 and re.match(r'^[1-9]\d*$', lines[1]):
            rid = lines[1]
    except Exception:
        pass
    return pin, rid


def find_publish():
    cands = ['/root/.codebuddy/skills/sites/scripts/publish.js',
             '/root/.codebuddy/skills/发布为应用/scripts/publish.js',
             os.path.expanduser('~/.codebuddy/skills/sites/scripts/publish.js')]
    for p in cands:
        if os.path.isfile(p):
            return p
    for base in ('/root/.codebuddy', os.path.expanduser('~')):
        for dp, dns, fns in os.walk(base):
            dns[:] = [d for d in dns if d not in ('node_modules', '.git')]
            if 'publish.js' in fns and 'scripts' in dp:
                return os.path.join(dp, 'publish.js')
    return None


def main():
    pin, orig_rid = read_conf()
    cur = (os.environ.get('AGENTOS_RUNTIME_ID') or '').strip()
    inject = os.environ.get('PIN_RUNTIME_ID') or orig_rid or cur
    if not inject:
        print('[钉域名] 缺少 AGENTOS_RUNTIME_ID，放弃'); return 2

    # ① 预写 state.json：runtimeId 对齐本环境变量，appName 钉死
    st = {'runtimeId': inject, 'appName': pin, 'lastReleaseId': None,
          'createdAt': int(time.time() * 1000)}
    os.makedirs(os.path.dirname(PUB_STATE), exist_ok=True)
    json.dump(st, open(PUB_STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('[钉域名] state=%s  → 目标 %s.app.workbuddy.host' % (inject, pin))

    pub = find_publish()
    if not pub:
        print('[钉域名] 未找到 publish.js'); return 3

    env = dict(os.environ, AGENTOS_RUNTIME_ID=inject)
    port = os.environ.get('BIZ_PORT', '8046')
    ts = time.strftime('%H:%M:%S')
    print('[钉域名] %s 开始发布 ...' % ts)
    r = subprocess.run(['node', pub, '--dir', SITE, '--port', port],
                       capture_output=True, text=True, env=env, timeout=1800)
    out = (r.stdout or '') + (r.stderr or '')
    tail = out[-2500:]
    print(tail)

    # ② 事后校验：真实命中域名是否为钉死值
    host_re = re.compile(r'([a-z0-9\-]{6,40})\.app\.workbuddy\.host')
    hosts = sorted(set(host_re.findall(out)))
    ok = pin in hosts
    print('\n[钉域名] ' + ('✅ 命中目标域名 %s.app.workbuddy.host' % pin if ok
                        else '❌ 漂移到了别的域名：%s（目标 %s）' % (hosts or '未知', pin)))
    if not ok and pin not in out:
        print('[钉域名] 排查：publish.conf 是否可读 / 后端是否拒绝复用该 appName')
    return 0 if ok else 4


if __name__ == '__main__':
    sys.exit(main())
