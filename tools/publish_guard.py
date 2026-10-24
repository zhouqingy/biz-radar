#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
域名守卫 · Domain Guard
=======================
为什么要这个东西：发布工具按「沙箱 runtimeId」生成域名。沙箱一旦被回收重建，
runtimeId 就会变，发布会**静默落到新域名**，同事手里的旧链接停更且不自知。

这里做两件事：
1. 发布前把本地记录里的 runtimeId 对齐到当前环境、保留 publish.conf 里钉死的
   appName —— 强制继续打在旧域名上；
2. 发布后校验返回的链接，若确实漂移了（例如换到完全不同的环境），明确报警并
   给出人工补救办法，而不是假装成功。

publish.conf：一行，写对外域名前缀，如  a60be47466efe1223
"""
import json
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PIN_FILE = os.path.join(ROOT, 'publish.conf')
PUB_STATE = os.path.expanduser('~/.workbuddy-sandbox-publish/state.json')


def read_pin():
    """对外承诺的稳定域名前缀，例如 a60be47466efe1223"""
    try:
        raw = open(PIN_FILE, encoding='utf-8').read().strip()
        return raw.split()[0] if raw else ''
    except Exception:
        return ''


def pin_domain():
    """发布前调用：把域名钉回 publish.conf 指定的那个。"""
    want = read_pin()
    cur = (os.environ.get('AGENTOS_RUNTIME_ID') or '').strip()
    if not want or not cur:
        return
    st = {}
    if os.path.exists(PUB_STATE):
        try:
            st = json.load(open(PUB_STATE, encoding='utf-8')) or {}
        except Exception:
            st = {}
    if st.get('appName') == want and st.get('runtimeId') == cur:
        return                                    # 正常：无需干预
    if st.get('appName') == want:
        note = '沙箱已重建，回绑旧域名'
    elif not st.get('appName'):
        note = '本地无发布记录，沿用既有域名'
    else:
        note = '检测到域名漂移，已纠正为对外域名'
    st.update({'runtimeId': cur, 'appName': want})
    st.setdefault('createdAt', int(time.time() * 1000))
    st['lastReleaseId'] = None
    os.makedirs(os.path.dirname(PUB_STATE), exist_ok=True)
    json.dump(st, open(PUB_STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('[域名守卫] %s → %s.app.workbuddy.host' % (note, want))


def warn_if_drift(link):
    """发布后调用：链接不是目标域名时明确报警。返回 True 表示漂移。"""
    want = read_pin()
    if not link or not want or want in link:
        return False
    print('\n' + '!' * 62)
    print('[域名守卫] ⚠ 本次发布落到了新域名，旧链接没有更新！')
    print('   旧（对外）：%s.app.workbuddy.host' % want)
    print('   新（本次）：%s' % link)
    print('   怎么办：回到最初创建这个页面的那个会话，说一句「跑一次刷新」，')
    print('            那个沙箱会重新发布并把内容推回旧域名。')
    print('!' * 62)
    return True


if __name__ == '__main__':
    print('pin =', read_pin() or '（未设置）')
    print('state =', PUB_STATE)
    if os.path.exists(PUB_STATE):
        st = json.load(open(PUB_STATE, encoding='utf-8'))
        print('  appName   :', st.get('appName'))
        print('  runtimeId :', st.get('runtimeId'))
        print('  当前环境  :', (os.environ.get('AGENTOS_RUNTIME_ID') or '').strip())
        print('  结论      :',
              '匹配，发布会打到既定域名' if st.get('appName') == read_pin()
              and st.get('runtimeId') == (os.environ.get('AGENTOS_RUNTIME_ID') or '').strip()
              else '不匹配 —— pin_domain() 会自动纠正')
