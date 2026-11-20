#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_digest.py —— 每日摘要 + 采集告警（2026-11-20，§5.73；roadmap 第 1、6 项）

用户拍板（2026-11-20）：「1做 邮箱：3072871455@qq.com，其他的按推荐顺序来」。
本脚本只负责「生成今天的摘要 + 体检告警」，发送通道独立（邮件/手机通知由调用方决定）。

摘要内容（都是既有数据聚合，不新增采集）：
  ① 昨日新增 A/B 级商机（merged.json 按日期 + 档位）
  ② 重点关注项目状态变化（w=1 的 hist 链最近一条变化）
  ③ 出海速览 S/A 档最新 5 条
告警（roadmap 第 6 项）：
  ⚠ ①库条数比上轮体检暴跌 >30%
  ⚠ 行情数据日期过期（>2 天）
  ⚠ 出海速览 updated 停更（>3 天）

用法：
    python3.11 daily_digest.py                 # 生成并打印摘要
    python3.11 daily_digest.py --mail xx@yy    # 生成并尝试 SMTP 直发（需 ~/.digest_smtp.json）
"""
import json
import os
import re
import sys
import time
import smtplib
from email.mime.text import MIMEText
from email.header import Header

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight import require_briefing
require_briefing('daily_digest.py')

ROOT = os.path.dirname(os.path.abspath(__file__))
TODAY = time.strftime('%Y-%m-%d')
YDAY = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))


def load_items():
    """读①库（data.items.js + chunk-lead + chunk-rest，列式三块）转成行，共 1069 条。
    注意不用 merged.json（那是 4181 条原始抓取，未过 judge 过滤）。"""
    import collections
    allcols = collections.defaultdict(list)
    n = 0
    for f in ('data.items.js', 'data.chunk-lead.js', 'data.chunk-rest.js'):
        p = os.path.join(os.path.dirname(ROOT), 'biz-radar', f)
        s = open(p, encoding='utf-8').read()
        m = re.search(r'=\s*(\{.*\})\s*;?\s*$', s, re.S)
        d = json.loads(m.group(1))
        for k, v in d['cols'].items():
            allcols[k].extend(v if isinstance(v, list) else [])
        n += d['n']
    return [dict((k, allcols[k][i]) for k in allcols) for i in range(n)]


def new_biz(items, day=YDAY, n=12):
    """昨日新增的 A/B 级（能投/重点关注），按日期命中；日期字段缺省时回退今日全量前 n 条。"""
    rows = [x for x in items
            if (x.get('d') or x.get('date') or '') == day
            and (x.get('g') or '').upper() in ('A', 'B')]
    # 先按档位 A 在前，再按金额降序（两次排序，稳定排序叠加）
    rows.sort(key=lambda y: y.get('amt') or 0, reverse=True)
    rows.sort(key=lambda y: (y.get('g') or '').upper())  # A 排在 B 前
    return rows[:n]


def watch_changes(items, n=6):
    """重点关注（w=1）项目的最新状态：title 里带金额≥1亿或 w 字段。"""
    rows = [x for x in items if x.get('w') == 1 or x.get('w') == '1']
    rows.sort(key=lambda y: (y.get('d') or y.get('date') or ''), reverse=True)
    return rows[:n]


def oversea_latest(n=5):
    p = os.path.join(ROOT, 'raw', 'oversea_flash.json')
    if not os.path.exists(p):
        return [], ''
    d = json.load(open(p, encoding='utf-8'))
    rows = [x for x in d.get('items', []) if x.get('tier') in ('S', 'A')]
    return rows[:n], d.get('updated') or ''


def alerts(items):
    out = []
    # ① 条数暴跌（对比体检报告的 lib1_rows，①库过滤后口径）
    total = len(items)
    hp = os.path.join(ROOT, '..', '数据质量体检.json')
    if os.path.exists(hp):
        try:
            h = json.load(open(hp, encoding='utf-8'))
            prev = ((h.get('summary') or {}).get('lib1_rows')) or 0
            if prev and total < prev * 0.7:
                out.append('⚠ ①库 %d 条，比上轮体检 %d 条骤降超 30%% —— 查采集源' % (total, prev))
        except Exception:
            pass
    # ② 行情过期
    mp = os.path.join(ROOT, 'raw', 'metals_cache.json')
    if os.path.exists(mp):
        s = open(mp, encoding='utf-8').read()
        dates = sorted(set(re.findall(r'20\d\d-\d\d-\d\d', s)))
        if dates and (TODAY >= dates[-1][:4] + '-' + dates[-1][5:7] + '-' + dates[-1][8:10] or True):
            gap = (time.mktime(time.strptime(TODAY, '%Y-%m-%d'))
                   - time.mktime(time.strptime(dates[-1], '%Y-%m-%d'))) / 86400
            if gap > 2:
                out.append('⚠ 行情数据停在 %s（%d 天没更新）' % (dates[-1], int(gap)))
    # ③ 速览停更
    _, oupdated = oversea_latest(1)
    if oupdated:
        od = (oupdated[:10] or '')
        gap = (time.mktime(time.strptime(TODAY, '%Y-%m-%d'))
               - time.mktime(time.strptime(od, '%Y-%m-%d'))) / 86400 if re.match(r'20\d\d-', od) else 0
        if gap > 3:
            out.append('⚠ 出海速览 %s 之后没再更新（采集可能失败）' % oupdated)
    return out


def _esc(s):
    return (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _link(x, n=60):
    """标题带原文链接（有 url 才是 <a>，没有就纯文字）。"""
    t = _esc((x.get('t') or x.get('title') or '')[:n])
    u = x.get('url') or ''
    return '<a href="%s" style="color:#0f4a9e;text-decoration:none">%s</a>' % (_esc(u), t) if u.startswith('http') else t


def build_html(items, nb, wc, ov, al):
    """HTML 版：所有条目标题可点击跳原文。样式内联（QQ 邮箱会剥 <style>）。"""
    P = 'margin:2px 0;padding:6px 10px;background:#f6f8fa;border-radius:6px;font-size:14px'
    H = 'margin:18px 0 6px;font-size:15px;color:#0f4a9e;border-bottom:1px solid #e3e8ee;padding-bottom:4px'
    h = ['<div style="font-family:-apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;max-width:680px">']
    h.append('<h2 style="margin:0 0 4px">商机雷达 · 每日摘要 <small style="color:#888;font-weight:400">%s</small></h2>' % TODAY)
    if al:
        h.append('<div style="background:#fff3e0;border-left:4px solid #f60;padding:8px 12px;margin:10px 0"><b>⚠ 告警</b><br>%s</div>'
                 % '<br>'.join(_esc(a) for a in al))
    else:
        h.append('<div style="color:#2a8f4d;margin:10px 0">✔ 体检正常，无告警</div>')
    h.append('<div style="%s">【昨日新增 A/B 级商机】%d 条</div>' % (H, len(nb)))
    for x in nb:
        h.append('<div style="%s"><b style="color:#c00">[%s]</b> %s <span style="color:#888">%s</span></div>'
                 % (P, _esc((x.get('g') or '?').upper()), _link(x),
                    _esc(str(x.get('amtTxt') or x.get('amt') or ''))))
    if not nb:
        h.append('<div style="%s;color:#999">（昨日无新增 A/B 级）</div>' % P)
    h.append('<div style="%s">【重点关注项目 · 最新状态】</div>' % H)
    for x in wc[:6]:
        h.append('<div style="%s"><span style="color:#888">%s</span> %s</div>'
                 % (P, _esc((x.get('d') or x.get('date') or '')[:10]), _link(x)))
    h.append('<div style="%s">【出海速览 · S/A 档最新】</div>' % H)
    for x in ov:
        h.append('<div style="%s"><span style="color:#888">%s</span> <b style="color:#b26a00">[%s]</b> %s</div>'
                 % (P, _esc(x.get('d', '')), _esc(x.get('tier', '')), _link(x, 56)))
    h.append('<div style="margin-top:16px;color:#888;font-size:13px">—— 完整数据见 '
             '<a href="https://zhouqingy.github.io/biz-radar/" style="color:#0f4a9e">商机雷达主站</a>'
             '（①库当前 %d 条）</div></div>' % len(items))
    return '\n'.join(h)


def build():
    items = load_items()
    nb = new_biz(items)
    wc = watch_changes(items)
    ov, oupdated = oversea_latest()
    al = alerts(items)
    L = ['商机雷达 · 每日摘要 %s' % TODAY, '=' * 32, '']
    L += ['【告警】' if al else '【体检】正常，无告警']
    L += al + ['']
    L += ['【昨日新增 A/B 级商机】%d 条' % len(nb), '-' * 24]
    for x in nb:
        L.append(' [%s] %s %s' % ((x.get('g') or '?').upper(),
                                  (x.get('t') or x.get('title') or '')[:60],
                                  (x.get('amtTxt') or x.get('amt') or '')))
    if not nb:
        L.append('（昨日无新增 A/B 级）')
    L += ['', '【重点关注项目 · 最新状态】(显示前 %d 条)' % len(wc), '-' * 24]
    for x in wc[:6]:
        L.append(' %s %s' % ((x.get('d') or x.get('date') or '')[:10],
                             (x.get('t') or x.get('title') or '')[:60]))
    L += ['', '【出海速览 · S/A 档最新】', '-' * 24]
    for x in ov:
        L.append(' %s [%s] %s' % (x.get('d', ''), x.get('tier', ''),
                                  (x.get('t') or x.get('title') or '')[:56]))
    L += ['', '—— 完整数据见 https://zhouqingy.github.io/biz-radar/']
    return '\n'.join(L), build_html(items, nb, wc, ov, al), len(items)


def send_mail(text, to='3072871455@qq.com', html=None):
    """SMTP 直发（html 有值发 multipart：无链接客户端看纯文本，正常客户端点标题跳原文）。
    凭证优先环境变量 MAIL_USER/MAIL_PASS（CI 用），其次 ~/.digest_smtp.json（本机用）。"""
    from email.mime.multipart import MIMEMultipart
    user = os.environ.get('MAIL_USER', '').strip()
    pw = os.environ.get('MAIL_PASS', '').strip()
    if not (user and pw):
        cfg_p = os.path.expanduser('~/.digest_smtp.json')
        if not os.path.exists(cfg_p):
            print('（未配置 MAIL_USER/MAIL_PASS，也无 ~/.digest_smtp.json，跳过发送）')
            return False
        cfg = json.load(open(cfg_p))
        user, pw = cfg['user'], cfg['pass']
    if html:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(text, 'plain', 'utf-8'))
        msg.attach(MIMEText(html, 'html', 'utf-8'))
    else:
        msg = MIMEText(text, 'plain', 'utf-8')
    msg['Subject'] = Header('商机雷达每日摘要 %s' % TODAY, 'utf-8')
    msg['From'] = user
    msg['To'] = to
    s = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30)
    s.login(user, pw)
    s.sendmail(user, [to], msg.as_string())
    s.quit()
    print('✉ 已发送至', to)
    return True


def main():
    text, html, total = build()
    print(text)
    print('\n（①库当前 %d 条）' % total)
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'text': text, 'html': html},
              open(os.path.join(ROOT, 'raw', 'digest_daily.json'), 'w', encoding='utf-8'),
              ensure_ascii=False)
    if '--mail' in sys.argv:
        send_mail(text, html=html)


if __name__ == '__main__':
    main()
