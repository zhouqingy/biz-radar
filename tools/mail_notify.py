#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mail_notify.py · 把「今天更新了什么」直接送进用户邮箱（写草稿箱）

════════════════════════════════════════════════════════════════════════
为什么要有这个脚本（2026-11-13 用户发问后补）
════════════════════════════════════════════════════════════════════════
用户原话：「那岂不是以后更新得每次我发个消息你才能更新？为什么不都是一样的吗？」

那一问之后，采集链已经全自动了（每日 07:20 北京时间）。但还剩一个「人工」：
**用户得自己去点网页才知道今天有没有新东西**。跑到哪一步、新增几条、哪几站挂了，
全在 Actions 日志里 —— 用户不该为了看一眼结论去翻日志。

这个脚本只干一件事：把结论搬进邮件。不采数据、不改口径、不写任何 data*.js。

────────────────────────────────────────────────────────────────────────
为什么是 IMAP APPEND 到「草稿箱」，不是 SMTP 发信
────────────────────────────────────────────────────────────────────────
· SMTP 需要单独开「发信」权限并另配授权码；新浪/QQ 这类邮箱现在基本默认关闭
  客户端 SMTP，配一次要用户改好几次网页设置。
· IMAP 只要邮箱的「授权码」（开启 IMAP 时生成的那一个），APPEND 一条消息到
  Drafts 就完事。它在邮箱客户端里直接可见、点一下就发，且不走发送通道，
  不会被反垃圾规则拦（它压根没被「发送」过）。
· 一个 Secret 同时给「0.5 开工」「8 收工」两处用，不重复配。

────────────────────────────────────────────────────────────────────────
配置（GitHub → Settings → Secrets and variables → Actions）
────────────────────────────────────────────────────────────────────────
  MAIL_USER  完整邮箱地址，如 you@qq.com / you@163.com
  MAIL_PASS  该邮箱的「IMAP 授权码」（不是登录密码）
  MAIL_HOST  IMAP 服务器，可留空自动推断（见 HOSTS）
三项任意缺失 → 脚本直接 exit 0 并打印一行提示，绝不判红。

────────────────────────────────────────────────────────────────────────
两种阶段
────────────────────────────────────────────────────────────────────────
  --stage start  开工。主题「【商机雷达】已开工 11-13」，正文一屏看完。
  --stage end    收工。主题「【商机雷达】今日新增 44 条 · 11-13」，
                 正文含：新增条数 / 整站失败站数 / 库内总数 / 数据日期 /
                 已公示金额 / 总投资 / 规划前瞻条数 / 健康结论。

数字来源：全部读环境变量（workflow 里前序步骤写进 GITHUB_ENV 的），
本脚本只搬运、不重算 —— 页面数字来自脚本，通知也一样。
"""
import argparse
import imaplib
import json
import os
import re
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.environ.get('BIZ_OUT') or os.path.join(os.path.dirname(ROOT), 'biz-radar')

# 常见邮箱的 IMAP 服务器。用 SSL 993，STARTTLS 143 的很少见了，不折腾。
HOSTS = {
    'qq.com': 'imap.qq.com',
    'foxmail.com': 'imap.qq.com',
    '163.com': 'imap.163.com',
    '126.com': 'imap.126.com',
    'yeah.net': 'imap.yeah.net',
    'sina.com': 'imap.sina.com',
    'sina.cn': 'imap.sina.com',
    'sohu.com': 'imap.sohu.com',
    'aliyun.com': 'imap.aliyun.com',
    '139.com': 'imap.139.com',
    '189.cn': 'imap.189.cn',
    'gmail.com': 'imap.gmail.com',
    'outlook.com': 'outlook.office365.com',
    'hotmail.com': 'outlook.office365.com',
    'live.com': 'outlook.office365.com',
}


def host_of(user, override=''):
    if override:
        return override.strip()
    dom = (user.split('@')[-1] or '').lower()
    return HOSTS.get(dom, 'imap.' + dom if dom else '')


def env(key, default=''):
    v = (os.environ.get(key) or '').strip()
    return v if v else default


def read_core_meta():
    """直接从构建产物读 meta —— 环境变量拿不到时兜底，保证邮件不能说错话。"""
    try:
        s = open(os.path.join(SITE, 'data.core.js'), encoding='utf-8').read()
        return json.loads(s[s.index('=') + 1:].strip().rstrip(';')).get('meta') or {}
    except Exception:
        return {}


def read_plan_n():
    try:
        s = open(os.path.join(SITE, 'data.plan.js'), encoding='utf-8').read()
        return int(json.loads(s[s.index('=') + 1:].strip().rstrip(';')).get('n') or 0)
    except Exception:
        return 0


def num(key, default=0, cast=int):
    v = env(key)
    if not v:
        return default
    try:
        return cast(v)
    except Exception:
        return default


def fmt_money(yi):
    try:
        return '%.1f 亿' % float(yi)
    except Exception:
        return '%s 亿' % yi


def build_body(stage, meta, plan_n):
    today = time.strftime('%Y-%m-%d')
    now = time.strftime('%H:%M')
    run_url = ''
    srv = env('GITHUB_SERVER_URL')
    repo = env('GITHUB_REPOSITORY')
    rid = env('GITHUB_RUN_ID')
    if srv and repo and rid:
        run_url = '%s/%s/actions/runs/%s' % (srv, repo, rid)

    if stage == 'start':
        subj = '【商机雷达】已开工 %s' % today[5:]
        body = (
            '商机雷达每日更新已开工。\n\n'
            '开始时间：%s %s\n'
            '本次站点：江苏 / 浙江 / 合肥 / 苏州 / 常州\n'
            '预计用时：30~50 分钟\n\n'
            '跑完会再来一封，主题里直接写「今日新增 N 条」，点开就能看到结论，'
            '不用去翻 Actions 日志。\n' % (today, now)
        )
        if run_url:
            body += '\n进度（实时）：%s\n' % run_url
        return subj, body

    added = num('CRAWL_ADDED')
    failed = num('CRAWL_FAILED')
    total = num('META_TOTAL') or int(meta.get('total') or 0)
    new_n = num('META_NEW')
    asof = env('META_ASOF') or str(meta.get('dataAsOf') or '')
    amt = env('META_AMT') or str(meta.get('amtSum') or 0)
    inv = env('META_INV') or str(meta.get('invSum') or 0)
    note = env('HEALTH_NOTE') or '（健康判定未产出一行摘要）'

    if added:
        subj = '【商机雷达】今日新增 %d 条 · %s' % (added, today[5:])
    else:
        subj = '【商机雷达】%s · 今日无新增 · %s' % ('⚠' if failed >= 3 else 'ℹ', today[5:])

    lines = [
        '结论：%s' % note,
        '',
        '── 本轮采集 ──────────────',
        '新增入库：%d 条' % added,
        '整站失败：%d 站（>=3 站且 0 新增才算实质失效）' % failed,
        '',
        '── 库内现状 ──────────────',
        '商机库总数：%s 条' % total,
        '数据日期：%s' % (asof or '—'),
        '本轮新建条目：%s 条' % new_n,
        '已公示金额合计：%s' % fmt_money(amt),
        '总投资合计：%s' % fmt_money(inv),
        '规划前瞻：%d 条' % plan_n,
        '',
        '结束时间：%s %s' % (today, now),
    ]
    if run_url:
        lines += ['', '明细日志：%s' % run_url]
    lines += ['', '—— 本邮件由每日流水线自动写入草稿箱，点发送即可留存。']
    return subj, '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=('start', 'end'), default='end')
    ap.add_argument('--dry-run', action='store_true', help='只打印，不连邮箱')
    a = ap.parse_args()

    user = env('MAIL_USER')
    pwd = env('MAIL_PASS')
    host = host_of(user, env('MAIL_HOST'))
    # dry-run 时不要求授权码，只要求邮箱地址 —— 便于在沙箱里核对正文措辞。
    if not user or (not pwd and not a.dry_run):
        print('未配置 MAIL_USER / MAIL_PASS，跳过（这是可选通知，不影响采集）')
        return 0
    if not host:
        print('⚠ 推断不出 IMAP 服务器，请在 MAIL_HOST 里明确指定')
        return 0

    meta = read_core_meta()
    plan_n = read_plan_n()
    subj, body = build_body(a.stage, meta, plan_n)

    if a.dry_run:
        print('HOST', host)
        print('SUBJ', subj)
        print('-' * 50)
        print(body)
        return 0

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subj, 'utf-8')
    msg['From'] = formataddr((str(Header('商机雷达', 'utf-8')), user))
    msg['To'] = user
    msg['Date'] = formatdate(localtime=True)
    raw = msg.as_bytes()

    try:
        M = imaplib.IMAP4_SSL(host, 993)
    except Exception as e:
        print('⚠ 连不上 %s:993 —— %s' % (host, e))
        return 0
    try:
        M.login(user, pwd)
        # 选草稿箱。不同邮箱叫法不一样，按常见顺序试。
        ok_folder = ''
        for box in ('Drafts', '&g0l6P3ux-', '"Drafts"', '"草稿箱"', 'INBOX.Drafts',
                    '[Gmail]/Drafts', 'Draft'):
            try:
                typ, _ = M.select(box)
                if typ == 'OK':
                    ok_folder = box
                    break
            except Exception:
                continue
        if not ok_folder:
            print('⚠ 找不到草稿箱（Drafts），改为写进 INBOX')
            M.select('INBOX')
        # ★ 关键：APPEND 一条 \Draft 标记的消息，多数邮箱客户端会当成草稿显示
        typ, data = M.append(ok_folder or 'INBOX', '\\Draft', imaplib.Time2Internaldate(time.time()), raw)
        if typ == 'OK':
            print('✅ 已写入 %s（%s）· 主题：%s' % (ok_folder or 'INBOX', host, subj))
        else:
            print('⚠ APPEND 返回 %s：%s' % (typ, data))
    except Exception as e:
        print('⚠ 写入失败：%s' % e)
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
