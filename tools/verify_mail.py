#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邮件数据、路由、HTML 与发送状态的本地验收；不真实联网发信。"""
import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import mail_data
import mail_rules
import send_daily

OUT = Path(os.environ.get('MAIL_VERIFY_OUT') or Path(__file__).resolve().parent.parent / 'preview')
OUT.mkdir(parents=True, exist_ok=True)
report = {'checks': [], 'metrics': {}}


def check(name, condition, detail=None):
    report['checks'].append({'name': name, 'ok': bool(condition), 'detail': detail})
    if not condition:
        raise AssertionError('%s: %s' % (name, detail))


def run():
    snapshot = mail_data.load_snapshot()
    check('①库与正式站同为728条', snapshot['counts'] == {
        'items': 728, 'overseaRaw': 74, 'policies': 36, 'projects': 326, 'digest': 20}, snapshot['counts'])
    check('分块29+373+326', [x['count'] for x in snapshot['blocks']] == [29, 373, 326], snapshot['blocks'])
    check('公告截止日期一致', snapshot['meta']['dataAsOf'] == '2026-11-26', snapshot['meta']['dataAsOf'])
    html_body, text, routes, counts = send_daily.daily_content(snapshot)
    report['metrics']['daily'] = counts
    bad = ('镍冶炼厂利用率下降', '哥伦比亚西南部五省', '加蓬金克莱', '科威特夏盖亚', '南非西北省',
           '葛洲坝巴基斯坦达苏水电', 'Técnicas Reunidas', '三菱动力获越南', 'GreenCloud')
    main_text = ''.join(mail_rules.title_of(x) for x in routes['oversea7'])
    market_text = ''.join(mail_rules.title_of(x) for x in routes['market7'])
    check('非主业/外国项目不进出海主区和市场参考', not any(x in main_text + market_text for x in bad), main_text + market_text)
    check('每条出海主区均有中资主体和具体主业项目', all(mail_rules.CN_ACTOR.search(mail_rules.text_of(x)) and mail_rules.concrete_project(x) for x in routes['oversea7']))
    check('同一阿布扎比事件只保留一条', main_text.count('融资关闭') == 1 and main_text.count('2.6GW') == 1, main_text)
    check('军信垃圾发电进入主区而非市场参考', '军信股份' in main_text and '军信股份' not in market_text)
    policy_text = ''.join(mail_rules.title_of(x) for x in routes['policies30'])
    check('政策区剔除企业制度/评论/监管调研', not any(x in policy_text for x in ('赣能股份', '院长', '调研监管', '新增平均', '我国已制定')), policy_text)
    check('政策区保留正式政策', '实施方案' in policy_text and '征求意见' in policy_text, policy_text)
    project_text = ''.join(mail_rules.title_of(x) for x in routes['projects7'])
    check('项目区剔除监理/设备采购/水电抽蓄/规划', not any(x in project_text for x in ('监理', '除尘器采购', '水电站', '抽蓄', '绿色交通')), project_text)
    check('海外u字段生成真实链接', 'https://news.goalfore.cn/latest/detail/109313.html' in html_body)
    check('海外s字段进入来源列', '国复咨询' in html_body)
    check('QQ邮件不使用空折叠区', '<details' not in html_body and '<summary' not in html_body)
    check('纯文本包含全部主区标题', all(mail_rules.title_of(x) in text for x in routes['oversea7']))
    before = Path(send_daily.STATE_PATH).read_bytes() if Path(send_daily.STATE_PATH).exists() else b''
    with contextlib.redirect_stdout(io.StringIO()):
        rc = send_daily.main(['--dry', '--output-dir', str(OUT)])
    after = Path(send_daily.STATE_PATH).read_bytes() if Path(send_daily.STATE_PATH).exists() else b''
    check('dry不写已发状态且返回0', rc == 0 and before == after)
    weekly_html, weekly_text, weekly_counts = send_daily.weekly_content(snapshot)
    check('周报与日报共用同一快照', '①库 728 条' in weekly_html and weekly_counts['weeklyBiz'] >= 1, weekly_counts)
    spot_html, spot_text, events, spot_counts = send_daily.spot_content(snapshot)
    check('重大插发只含中资主业S档事件', spot_counts['fresh'] == 1 and '湖南安装' in spot_text, spot_counts)

    with tempfile.TemporaryDirectory() as td:
        state = os.path.join(td, 'state.json')
        log = os.path.join(td, 'delivery.jsonl')
        with patch.object(send_daily, 'STATE_PATH', state), patch.object(send_daily, 'DELIVERY_LOG', log), \
             patch.object(send_daily, 'send_mail', return_value='<mock@biz-radar>') as sender, contextlib.redirect_stdout(io.StringIO()):
            rc = send_daily.main(['--tag', '测试'])
        records = [json.loads(x) for x in open(log, encoding='utf-8')]
        check('SMTP接受后才登记sent与已发状态', rc == 0 and sender.call_count == 1 and records[-1]['status'] == 'sent'
              and json.load(open(state, encoding='utf-8'))['sent'], records)
        with patch.object(send_daily, 'DELIVERY_LOG', log), patch.object(send_daily, 'credentials', side_effect=RuntimeError('模拟缺凭证')), contextlib.redirect_stdout(io.StringIO()):
            rc = send_daily.main(['--tag', '失败测试'])
        records = [json.loads(x) for x in open(log, encoding='utf-8')]
        check('缺凭证明确failed且非零退出', rc == 1 and records[-1]['status'] == 'failed' and '模拟缺凭证' in records[-1]['error'], records[-1])
    report['status'] = 'passed'


try:
    run()
except Exception as exc:
    report['status'] = 'failed'
    report['exception'] = repr(exc)
report['passed'] = sum(x['ok'] for x in report['checks'])
report['total'] = len(report['checks'])
(OUT / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'status': report['status'], 'passed': report['passed'], 'total': report['total'], 'exception': report.get('exception')}, ensure_ascii=False, indent=2))
if report['status'] != 'passed':
    raise SystemExit(1)
