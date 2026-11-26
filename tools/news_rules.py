#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""新闻栏目路由（不是①库 judge）：政策 / 项目 / 竞争情报 / 归档。

依据 2026-11-26 用户确认：政策档只放政策；具体项目进项目情况；
情报精选只保留主业范围内的竞对、伙伴、重点客户重要动作。
原始采集文件不删，本模块只决定展示归位。
"""
from urllib.parse import urlparse
import html
import re

POLICY_DOC = (
    '管理办法', '实施方案', '工作方案', '指导意见', '行动计划', '实施细则',
    '征求意见', '征求意见稿', '政策解读', '价格机制', '电价机制', '市场规则',
    '交易规则', '运行机制', '补偿机制', '配额', '碳市场', '碳交易', '补贴',
    '贴息', '条例', '规定', '办法', '细则', '标准', '规范', '规划', '政策',
)
POLICY_VERB = ('印发', '发布', '出台', '征求意见', '解读', '施行', '实施', '修订')
PROJECT_ACTION = (
    '招标', '中标', '开标', '候选人', '签约', '核准', '备案', '环评', '受理',
    '开工', '动工', '吊装', '水压试验', '施工', '并网', '投产', '竣工', '验收',
    '投运', '试运行', '扩建', '新建', '技改', '拟建', '建设',
)
PROJECT_ENTITY = ('项目', '工程', '机组', '电厂', '电站', '生产线', '装置', '锅炉', '工厂', '园区')

# 非主业形态优先于能源词，防止“储能电站送出工程”被储能二字误留。
OUT_SCOPE = (
    '输变电', '送出工程', '变电站', '核电', '风机', '风电整机',
    '污水处理', '污水厂', '废水处理', '中水回用', '水环境治理', '水系综合整治',
    '设备维修', '车辆管理系统', '管道包覆', '药剂总包', '中标无效', '周年',
)
EXTERNAL_HOSTS = {
    'www.chinaxdsb.com', 'www.baohuabidding.cn', 'www.cpnn.com.cn', 'www.cfi.net.cn',
}
CORE = (
    '燃煤', '煤电', '火电', '热电', '电厂', '电站', '发电', '机组', '锅炉', '汽轮机',
    '煤气', '余热', '余压', '储能', '生物质', '垃圾发电', '焚烧发电', '海水淡化',
    '燃气', '天然气', 'LNG', '分布式能源', '源网荷储', '微电网', '零碳园区',
    '热电联产', '集中供热', '供热', '供汽', '动力岛', '能源岛', '能源站',
    '氧化铝', '电解铝', '有色冶炼', '熟料', '水泥窑', '钢铁', '焦化',
)
WIND = ('风电', '海上风', '陆上风')
PV = ('光伏', '渔光互补')
SCALE = re.compile(r'\d+(?:\.\d+)?\s*(?:兆瓦|MW|mw|万千瓦|千瓦|kW|kw|MWh|兆瓦时|亿元|万吨|吨/日)')
OVERSEA = ('海外', '境外', '印尼', '越南', '马来西亚', '阿曼', '沙特', '阿联酋', '迪拜', '非洲', '西非', '欧洲', '纳米比亚')


def text_of(x):
    return html.unescape((x.get('title') or x.get('t') or '') + ' ' + (x.get('desc') or x.get('sum') or ''))


def core_relevance(x):
    text = text_of(x)
    if any(k in text for k in OUT_SCOPE):
        return False
    # 纯风电不做；纯光伏不做，光伏+储能/热电等复合能源仍留。
    if any(k in text for k in WIND) and not any(k in text for k in ('储能', '热电', '火电', '余热')):
        return False
    if any(k in text for k in PV) and not any(k in text for k in ('储能', '热电', '火电', '余热', '源网荷储')):
        return False
    return any(k in text for k in CORE)


def is_project(x):
    text = text_of(x)
    return any(k in text for k in PROJECT_ENTITY) and any(k in text for k in PROJECT_ACTION)


def is_policy(x):
    title = html.unescape(x.get('title') or x.get('t') or '')
    if (x.get('tag') or '').startswith('政策'):
        return True
    if any(k in title for k in POLICY_DOC) and any(k in title for k in POLICY_VERB):
        return True
    if is_project(x):
        return False
    return any(k in title for k in POLICY_DOC) and (
        any(k in title for k in POLICY_VERB) or (x.get('tag') or '').startswith('政策')
        or any(k in title for k in ('电价', '市场', '机制', '规划', '办法', '方案', '规则'))
    )


def route_trends(items):
    policies, projects, archive = [], [], []
    for original in items:
        x = dict(original)
        x['title'] = html.unescape(x.get('title') or '')
        x['desc'] = html.unescape(x.get('desc') or '')
        if is_policy(x):
            x['tag'] = x.get('tag') if (x.get('tag') or '').startswith('政策') else '政策·行业规则'
            policies.append(x)
        elif is_project(x) and core_relevance(x):
            projects.append(x)
        else:
            archive.append(x)
    return policies, projects, archive


def parse_date(url, title=''):
    patterns = (
        r'/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:/|$)',
        r'/t(20\d{2})(\d{2})(\d{2})_',
        r'/(20\d{2})(\d{2})(\d{2})/',
    )
    for pattern in patterns:
        m = re.search(pattern, url or '')
        if m:
            return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', title or '')
    return '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ''


def _host(url):
    return (urlparse(url or '').hostname or '').lower().split(':')[0]


def official_source(x, competitors):
    if x.get('srcKind') == '微信':
        return True  # 人工挑选的深度稿，不冒充官网自动源。
    src = x.get('src') or ''
    target = _host(x.get('url'))
    if target in EXTERNAL_HOSTS:
        return False
    homes = [_host(c.get('url')) for c in competitors if c.get('name') == src]
    if not homes or not target:
        return False
    return any(target == home or target.endswith('.' + home) or home.endswith('.' + target) for home in homes if home)


def _event_fingerprint(title):
    text = re.sub(r'^[^：:]{1,18}[：:]', '', title or '')
    for word in ('新华社', '人民网', '人民日报', '中企', '承建', '勘察设计', '总承包',
                 '项目', '工程', '投产', '开工', '竣工', '并网', '首次', '一次成功',
                 '首台机组', '1号机组', '发电', '顺利'):
        text = text.replace(word, '')
    return re.sub(r'[\s：:，,。、！？!?（）()《》「」“”‘’·|｜—\-]', '', text)


def clean_digest(items, competitors):
    kept, archive = [], []
    for original in items:
        x = dict(original)
        x['t'] = html.unescape(x.get('t') or '').strip()
        x['sum'] = html.unescape(x.get('sum') or '').strip()
        x['d'] = x.get('d') or parse_date(x.get('url'), x['t'])
        if not official_source(x, competitors) or not core_relevance(x):
            archive.append(x)
            continue
        # 精选等级重新按主业事件内容计算，不沿用泛能源采集时的宽口径。
        text = text_of(x)
        x['level'] = 'S' if SCALE.search(text) or any(k in text for k in OVERSEA) else 'A'
        kept.append(x)
    kept.sort(key=lambda z: ({'S': 0, 'A': 1}.get(z.get('level'), 2), z.get('d') or ''), reverse=False)
    # 等级升序后，各等级内部按日期倒序；无日期不虚构，排在该等级末尾。
    kept.sort(key=lambda z: z.get('d') or '', reverse=True)
    kept.sort(key=lambda z: {'S': 0, 'A': 1}.get(z.get('level'), 2))
    deduped = []
    fingerprints = []
    for x in kept:
        fp = _event_fingerprint(x['t'])
        if len(fp) >= 8 and any(len(old) >= 8 and (fp in old or old in fp) for old in fingerprints):
            archive.append(x)
            continue
        fingerprints.append(fp)
        deduped.append(x)
    return deduped, archive
