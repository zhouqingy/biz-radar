#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商机雷达唯一邮件生成/发送入口：日报、重大插发、周报。

默认：沙箱读取正式站同快照，GitHub Actions 读取刚发布的仓库快照。
只读业务数据，不调用采集，不改①库，不另写 investable 判定。
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import smtplib
import sys
import time
import uuid
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from preflight import require_briefing
require_briefing('send_daily.py')

from mail_data import load_snapshot
from mail_rules import daily_routes, date_of, recent, root_key, title_of, unique
from biz_rules import judge

OWNER = '3072871455@qq.com'
TODAY = dt.date.today()
STATE_PATH = os.environ.get('MAIL_STATE') or os.path.join(HERE, 'raw', 'mail_state.json')
DELIVERY_LOG = os.environ.get('MAIL_DELIVERY_LOG') or os.path.join(HERE, 'raw', 'mail_delivery_log.jsonl')


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def link(row, length=72):
    title = esc(title_of(row)[:length])
    url = row.get('url') or row.get('u') or ''
    if re.match(r'^https?://', url):
        return '<a href="%s" style="color:#0f4a9e;text-decoration:none">%s</a>' % (esc(url), title)
    return title


def plain_line(row):
    return '%s %s %s' % (date_of(row) or '日期待核', title_of(row), row.get('url') or '')


def load_state():
    try:
        with open(STATE_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return {'sent': data.get('sent') or {}, 'spot': data.get('spot') or {}}
    except FileNotFoundError:
        return {'sent': {}, 'spot': {}}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    cutoff = (TODAY - dt.timedelta(days=14)).isoformat()
    state['sent'] = {k: v for k, v in state['sent'].items() if v >= cutoff}
    state['spot'] = {k: v for k, v in state['spot'].items() if v >= cutoff}
    state['updated'] = dt.datetime.now().isoformat(timespec='seconds')
    temp = STATE_PATH + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
    os.replace(temp, STATE_PATH)


def delivery_record(mode, status, subject='', recipients=None, error='', snapshot=None, counts=None, message_ids=None):
    return {
        'at': dt.datetime.now().isoformat(timespec='seconds'), 'mode': mode, 'status': status,
        'subject': subject, 'recipients': recipients or [], 'error': error,
        'messageIds': message_ids or [], 'dataAsOf': str((snapshot or {}).get('meta', {}).get('dataAsOf') or ''),
        'items': (snapshot or {}).get('counts', {}).get('items', 0),
        'snapshotSha256': (snapshot or {}).get('sha256', ''), 'counts': counts or {},
    }


def write_delivery(record):
    os.makedirs(os.path.dirname(DELIVERY_LOG), exist_ok=True)
    with open(DELIVERY_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
    print('MAIL_RESULT ' + json.dumps(record, ensure_ascii=False, sort_keys=True))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write('\n### 邮件%s\n\n- 状态：**%s**\n- 主题：%s\n- 收件人：%s\n- 数据：①库 %s 条，截止 %s\n- 错误：%s\n' % (
                record['mode'], record['status'], esc(record['subject']), esc(','.join(record['recipients'])),
                record['items'], record['dataAsOf'] or '—', esc(record['error'] or '无')))


def credentials():
    user = os.environ.get('MAIL_USER', '').strip()
    password = os.environ.get('MAIL_PASS', '').strip()
    if user and password:
        return user, password
    path = os.path.expanduser('~/.digest_smtp.json')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as f:
            config = json.load(f)
        return config['user'].strip(), config['pass'].strip()
    raise RuntimeError('缺少 MAIL_USER/MAIL_PASS 或 ~/.digest_smtp.json，未发送')


def send_mail(subject, text, html_body, to):
    user, password = credentials()
    message = MIMEMultipart('alternative')
    message.attach(MIMEText(text, 'plain', 'utf-8'))
    message.attach(MIMEText(html_body, 'html', 'utf-8'))
    message['Subject'] = Header(subject, 'utf-8')
    message['From'] = user
    message['To'] = to
    message['Date'] = formatdate(localtime=True)
    message_id = '<%s@biz-radar.local>' % uuid.uuid4().hex
    message['Message-ID'] = message_id
    server = smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=45)
    try:
        server.login(user, password)
        refused = server.sendmail(user, [to], message.as_string())
        if refused:
            raise RuntimeError('SMTP 部分拒收：%s' % refused)
    finally:
        try:
            server.quit()
        except Exception:
            server.close()
    print('SMTP_ACCEPTED %s %s' % (to, message_id))
    return message_id


def table(rows, kind='news', empty='本时间窗无符合条件的新增，不拿旧闻凑数。'):
    if not rows:
        return '<p style="color:#7a8494;font-size:12.5px;margin:4px 0">%s</p>' % esc(empty)
    if kind == 'biz':
        heads = ('日期', '项目/标题', '地区', '金额', '档位')
    else:
        heads = ('日期', '项目/标题', '来源/分类')
    out = ['<table role="presentation" style="border-collapse:collapse;width:100%;table-layout:fixed">',
           '<tr>' + ''.join('<th style="border-bottom:1px solid #dce3ed;padding:6px 5px;text-align:left;font-size:12px;background:#f4f7fb">%s</th>' % x for x in heads) + '</tr>']
    for row in rows:
        if kind == 'biz':
            amount = row.get('amtTxt') or (('%g 亿' % row['amt']) if row.get('amt') else '—')
            cells = (date_of(row), link(row), row.get('rg') or row.get('city') or '—', amount, (row.get('g') or '—').upper())
        else:
            label = row.get('src') or row.get('s') or row.get('source') or row.get('tag') or row.get('chan') or '—'
            if row.get('is_old'):
                label = str(label) + ' · 前报'
            if not date_of(row):
                label = str(label) + ' · 日期待核'
            cells = (date_of(row) or '待核', link(row), label)
        out.append('<tr>' + ''.join('<td style="border-bottom:1px solid #edf0f4;padding:7px 5px;font-size:12px;line-height:1.5;vertical-align:top;word-break:break-all">%s</td>' % (
            cell if index == 1 else esc(cell)) for index, cell in enumerate(cells)) + '</tr>')
    out.append('</table>')
    return ''.join(out)


def section(title, rows, kind='news', empty=None):
    body = table(rows, kind, empty or '本时间窗无符合条件的新增，不拿旧闻凑数。')
    return '<section style="margin:0 0 18px"><h3 style="font-size:14px;color:#123f73;margin:0 0 7px;border-left:3px solid #2978c8;padding-left:8px">%s <span style="color:#7a8494;font-weight:400">%d 条</span></h3>%s</section>' % (
        esc(title), len(rows), body)


def alerts(snapshot):
    out = []
    asof = str(snapshot['meta'].get('dataAsOf') or '')[:10]
    if asof:
        gap = (TODAY - dt.date.fromisoformat(asof)).days
        if gap > 3:
            out.append('①库最新公告日期为 %s，已 %d 天未出现更新' % (asof, gap))
    metal_date = str((snapshot['core'].get('metals') or {}).get('updated') or '')[:10]
    if metal_date:
        gap = (TODAY - dt.date.fromisoformat(metal_date)).days
        if gap > 3:
            out.append('金属行情更新至 %s，已 %d 天未更新' % (metal_date, gap))
    ov_dates = [date_of(x) for x in snapshot['oversea'] if date_of(x)]
    if ov_dates:
        gap = (TODAY - dt.date.fromisoformat(max(ov_dates))).days
        if gap > 3:
            out.append('出海速览最新事件日期为 %s，已 %d 天未更新' % (max(ov_dates), gap))
    return out


def frame(snapshot, subtitle, sections, warning=''):
    source = '正式站同快照' if snapshot['source'].startswith('online:') else '本次发布仓库快照'
    head = ('<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Microsoft YaHei,sans-serif;max-width:760px;color:#17233b">'
            '<h2 style="font-size:19px;margin:0 0 5px">商机雷达 · %s</h2>'
            '<p style="font-size:12px;color:#65738b;margin:0 0 12px">%s · %s · ①库 %d 条 · 公告截止 %s · 快照 %s</p>'
            '<p style="font-size:12px;margin:0 0 14px"><a href="https://zhouqingy.github.io/biz-radar/" style="color:#0f4a9e">打开完整平台</a>（政策、项目、竞争情报与①库均按同一快照）</p>')
    head %= (esc(subtitle), TODAY.isoformat(), source, len(snapshot['items']), esc(snapshot['meta'].get('dataAsOf') or '—'), snapshot['sha256'][:12])
    tail = ('<p style="font-size:11px;color:#8792a5;border-top:1px solid #e6ebf2;padding-top:10px;margin-top:18px">'
            '出海主区只收“可确认中资主体 + 主业能源设施 + 具体项目动作”；纯市场新闻仅在“市场参考”展示，非主业及无明确中资主体项目不进入主区。'
            '①库能投判定仍由 biz_rules.judge() 统一执行。</p></div>')
    return head + warning + ''.join(sections) + tail


def daily_content(snapshot):
    routes = daily_routes(snapshot, TODAY)
    watch = [x for x in snapshot['items'] if x.get('w') in (1, '1')
             and judge(x.get('t'), x.get('snip') or '').get('investable')]
    routes['watch7'] = unique(recent(watch, 7, TODAY))[:6]
    state = load_state()
    for row in routes['oversea7']:
        row['is_old'] = bool(state['sent'].get(root_key(title_of(row))))
    al = alerts(snapshot)
    warning = ''
    if al:
        warning = '<div style="background:#fff7e6;border:1px solid #ebc56d;padding:9px 12px;margin:0 0 14px;font-size:12px"><b>数据提醒</b><br>%s</div>' % '<br>'.join(esc(x) for x in al)
    sections = [
        section('近 3 天新增 A/B 商机', routes['biz3'], 'biz'),
        section('重点关注项目近 7 天动态', routes['watch7'], 'news', '近 7 天无重点关注主业项目新动态。'),
        section('中资出海项目近 7 天', routes['oversea7']),
        section('项目情况近 7 天', routes['projects7']),
        section('政策动态近 30 天', routes['policies30'], 'news', '近 30 天无新政策入库；旧政策不在邮件里冒充新增，请查平台政策档。'),
        section('竞争情报近 30 天', routes['digest30']),
        section('市场参考（非项目级）', routes['market7'], 'news', '近 7 天无需要保留的主业市场参考。'),
        section('4～10 天前商机回顾', routes['reviewBiz'], 'biz'),
        section('4～10 天前出海回顾', routes['reviewOversea']),
    ]
    names = ('近3天A/B商机', '重点关注7天', '中资出海7天', '项目情况7天', '政策30天', '竞争情报30天', '市场参考7天', '商机回顾', '出海回顾')
    keys = ('biz3', 'watch7', 'oversea7', 'projects7', 'policies30', 'digest30', 'market7', 'reviewBiz', 'reviewOversea')
    lines = ['商机雷达每日简报 %s' % TODAY, '①库 %d 条，公告截止 %s' % (len(snapshot['items']), snapshot['meta'].get('dataAsOf'))]
    lines += ['', '数据提醒：' + '；'.join(al)] if al else []
    for name, key in zip(names, keys):
        lines += ['', '【%s】%d 条' % (name, len(routes[key]))]
        lines += [plain_line(x) for x in routes[key]] or ['无']
    counts = dict((key, len(routes[key])) for key in keys)
    return frame(snapshot, '每日简报', sections, warning), '\n'.join(lines), routes, counts


def spot_content(snapshot):
    routes = daily_routes(snapshot, TODAY)
    state = load_state()
    events = []
    for row in routes['biz3']:
        if date_of(row) == TODAY.isoformat() and (row.get('g') or '').upper() == 'A' and (row.get('amt') or 0) >= 1:
            events.append(row)
    for row in routes['oversea7']:
        if date_of(row) == TODAY.isoformat() and row.get('tier') == 'S':
            events.append(row)
    events = unique(events)
    fresh = [x for x in events if not state['spot'].get(root_key(title_of(x)))]
    if not fresh:
        return None, '', [], {'events': len(events), 'fresh': 0}
    sections = [section('今日公告级重大事件', fresh)]
    text = '重大事件速递 %s\n' % TODAY + '\n'.join(plain_line(x) for x in fresh)
    return frame(snapshot, '重大事件速递', sections), text, fresh, {'events': len(events), 'fresh': len(fresh)}


def weekly_content(snapshot):
    routes = daily_routes(snapshot, TODAY)
    biz7 = recent([x for x in snapshot['items'] if (x.get('g') or '').upper() in ('A', 'B')], 7, TODAY)
    biz7.sort(key=lambda x: x.get('amt') or 0, reverse=True)
    sections = [
        section('本周 A/B 商机（按金额）', unique(biz7)[:15], 'biz'),
        section('本周中资出海项目', routes['oversea7']),
        section('本周项目情况', routes['projects7']),
        section('近 30 天政策动态', routes['policies30']),
        section('近 30 天竞争情报', routes['digest30']),
    ]
    counts = {'weeklyBiz': len(unique(biz7)[:15]), 'oversea7': len(routes['oversea7']),
              'projects7': len(routes['projects7']), 'policies30': len(routes['policies30']), 'digest30': len(routes['digest30'])}
    text = '商机雷达周报 %s\n' % TODAY + '\n'.join(plain_line(x) for x in unique(biz7)[:15] + routes['oversea7'])
    return frame(snapshot, '每周汇总', sections), text, counts


def output_preview(directory, mode, subject, text, html_body, snapshot, counts, routes=None):
    os.makedirs(directory, exist_ok=True)
    base = os.path.join(directory, mode)
    with open(base + '.html', 'w', encoding='utf-8') as f:
        f.write(html_body)
    with open(base + '.txt', 'w', encoding='utf-8') as f:
        f.write(text)
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump({'subject': subject, 'snapshot': {k: snapshot[k] for k in ('source', 'meta', 'counts', 'blocks', 'sha256')},
                   'counts': counts, 'routes': routes}, f, ensure_ascii=False, indent=2, default=str)
    print('PREVIEW %s' % base)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--to', default=OWNER)
    parser.add_argument('--tag', default='审')
    parser.add_argument('--dry', action='store_true', help='只生成预览，绝不发送或写已发状态')
    parser.add_argument('--weekly', action='store_true')
    parser.add_argument('--spot', action='store_true')
    parser.add_argument('--output-dir', default='')
    parser.add_argument('--mail', nargs='?', const=OWNER, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.mail:
        args.to = args.mail
    mode = 'weekly' if args.weekly else ('spot' if args.spot else 'daily')
    recipients = [x.strip() for x in args.to.split(',') if x.strip()]
    snapshot = load_snapshot()
    routes = None
    if mode == 'weekly':
        html_body, text, counts = weekly_content(snapshot)
        subject = '【商机雷达·周报】%s 周' % TODAY.isoformat()
    elif mode == 'spot':
        html_body, text, events, counts = spot_content(snapshot)
        subject = '【商机雷达·重大】%d 条 · %s' % (len(events), TODAY.isoformat())
        routes = {'events': [dict(x) for x in events]}
        if not events:
            if not args.dry:
                write_delivery(delivery_record(mode, 'skipped', '今日无未发重大事件', recipients, snapshot=snapshot, counts=counts))
            else:
                print('SPOT_SKIPPED 今日无未发重大事件')
            return 0
    else:
        html_body, text, routes, counts = daily_content(snapshot)
        subject = '【商机雷达·%s】每日简报 %s' % (args.tag, TODAY.isoformat())
    if args.output_dir:
        output_preview(args.output_dir, mode, subject, text, html_body, snapshot, counts, routes)
    if args.dry:
        print('DRY_OK %s %s' % (mode, json.dumps(counts, ensure_ascii=False)))
        return 0
    message_ids = []
    try:
        for recipient in recipients:
            message_ids.append(send_mail(subject, text, html_body, recipient))
    except Exception as exc:
        write_delivery(delivery_record(mode, 'failed', subject, recipients, str(exc), snapshot, counts, message_ids))
        return 1
    state = load_state()
    if mode == 'daily':
        for row in routes['oversea7']:
            state['sent'][root_key(title_of(row))] = TODAY.isoformat()
    elif mode == 'spot':
        for row in routes['events']:
            state['spot'][root_key(title_of(row))] = TODAY.isoformat()
    save_state(state)
    write_delivery(delivery_record(mode, 'sent', subject, recipients, snapshot=snapshot, counts=counts, message_ids=message_ids))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
