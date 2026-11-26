#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""邮件展示路由，不替代①库 judge/semantic_drop，也不回写业务库。"""
import datetime as dt
import difflib
import re

from news_rules import (
    POLICY_DOC, POLICY_VERB, PROJECT_ENTITY, core_relevance, is_policy, is_project, text_of,
)

# 必须有可确认的中资主体；泛动作词（签约/中标/投产）不能冒充中资判据。
CN_ACTOR = re.compile(
    r'中资|中企|中国企业|中国(?:能建|电建|有色|中铝|中冶|中铁|中建|交建|港湾|化学|建材|'
    r'机械|电气|重机|国机|恩菲|瑞林|钢研|节能环保)|国电投|国家电投|国家能源|华能|华电|'
    r'大唐|三峡集团|葛洲坝|上海电气|东方电气|哈尔滨电气|湖南安装|军信股份|双良节能|'
    r'伟明环保|协鑫|晶科|天合|中铝|中色|中钢|中冶|中工国际|中材国际|中机|成达公司|'
    r'中国电工|中国天楹|中国武夷|中地海外|中水对外|中交|中铁|中建|中节能|浙火|秦冶重工')
OLD_NEWS = '旧闻重炒'
MAIL_OUT_SCOPE = (
    '水电', '抽水蓄能', '抽蓄', '地热', '核电', '输变电', '变电站', '送出工程',
    '监理', '除尘器采购', '设备采购', '主变电站', '码头', '泊位',
)
EXTENDED_ACTION = ('融资关闭', '融资', '合同', '授标', '拟投', '落子', '转让', '订单', '协议', '建设', '拟建')
MAIL_CORE_POSITIVE = (
    '燃煤', '煤电', '火电', '热电', '电厂', '煤气', '余热', '余压', '储能', '垃圾发电',
    '焚烧发电', '生物质', '燃气', '天然气', 'LNG', '海水淡化', '集中供热', '供热', '供汽',
    '动力岛', '能源岛', '能源站', '柴油发电', '分布式能源', '源网荷储', '微电网',
)
POLICY_EXCLUDE = ('股份', '集团公司', '有限公司董事长', '院长', '调研监管', '背后的需求', '新增平均')


def title_of(x):
    return (x.get('title') or x.get('t') or '').strip()


def date_of(x):
    value = (x.get('date') or x.get('d') or '')[:10]
    try:
        return dt.date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return ''


def recent(rows, days, today=None, limit=None):
    today = today or dt.date.today()
    start = today - dt.timedelta(days=days - 1)
    out = []
    for row in rows:
        day = date_of(row)
        if not day or OLD_NEWS in title_of(row):
            continue
        parsed = dt.date.fromisoformat(day)
        if start <= parsed <= today:
            out.append(row)
    out.sort(key=lambda x: (date_of(x), title_of(x)), reverse=True)
    return out[:limit] if limit is not None else out


def root_key(title):
    text = re.sub(r'^(新华社|人民网|人民日报)[丨|\s]*', '', title or '')
    text = re.sub(r'(招标公告|中标结果公告|中标候选人公示|澄清公告|变更公告|合同|公告|'
                  r'EPC总承包项目|EPC总承包|EPC招标|EPC|项目)$', '', text)
    return re.sub(r'[\s：:，,。、！？!?（）()《》「」“”‘’·|｜—\-]', '', text)[:36]


def unique(rows, excluded=None):
    excluded = excluded or set()
    seen = set(excluded)
    out = []
    norms = []
    for row in rows:
        title = title_of(row)
        key = root_key(title)
        norm = re.sub(r'[\s：:，,。、！？!?（）()《》「」“”‘’·|｜—\-]', '', title)
        if not key or key in seen:
            continue
        duplicate = False
        numbers = set(re.findall(r'\d+(?:\.\d+)?', norm))
        for old in norms:
            common = difflib.SequenceMatcher(None, norm, old).find_longest_match()
            old_numbers = set(re.findall(r'\d+(?:\.\d+)?', old))
            if common.size >= 14 and numbers and old_numbers and numbers & old_numbers:
                duplicate = True
                break
        if duplicate:
            continue
        seen.add(key)
        norms.append(norm)
        out.append(row)
    return out


def mail_core(row):
    text = text_of(row)
    if any(k in text for k in MAIL_OUT_SCOPE):
        return False
    if any(k in text for k in ('光伏', '太阳能')) and '储能' not in text:
        return False
    return any(k in text for k in MAIL_CORE_POSITIVE) or bool(re.search(r'(垃圾焚烧|固废.{0,4}发电)', text))


def concrete_project(row):
    text = text_of(row)
    return (is_project(row) or (any(k in text for k in PROJECT_ENTITY + ('电厂', '电站', '垃圾焚烧', '垃圾发电', '数据中心'))
                               and any(k in text for k in EXTENDED_ACTION))) and mail_core(row)


def formal_policy(row):
    title = title_of(row)
    if not is_policy(row) or any(k in title for k in POLICY_EXCLUDE):
        return False
    return any(k in title for k in POLICY_DOC) and any(k in title for k in ('印发', '出台', '征求意见', '修订', '发布', '解读'))


def project_news(row):
    title = title_of(row)
    return (concrete_project(row) and not is_policy(row)
            and not any(k in title for k in ('十五五”规划', '实施方案', '征求意见')))


def classify_oversea(rows):
    """主区=中资主体+主业+具体项目动作；纯市场仅作参考，其余归档。"""
    main, market, archive = [], [], []
    for row in rows:
        title = title_of(row)
        if OLD_NEWS in title:
            archive.append((row, '旧闻重炒'))
            continue
        text = text_of(row)
        if not mail_core(row):
            archive.append((row, '非主业能源设施'))
        elif not concrete_project(row):
            market.append(row)  # 只有行情/宏观变化，没有可跟进的项目动作。
        elif not CN_ACTOR.search(text):
            archive.append((row, '未识别到中资业主或承包商'))
        else:
            main.append(row)
    return main, market, archive


def daily_routes(snapshot, today=None):
    today = today or dt.date.today()
    ov_main, ov_market, ov_archive = classify_oversea(snapshot['oversea'])
    biz = [x for x in snapshot['items']
           if (x.get('g') or '').upper() in ('A', 'B')]
    biz3 = recent(biz, 3, today)
    biz3.sort(key=lambda x: ((x.get('g') or '') != 'A', -(x.get('amt') or 0), date_of(x)))
    biz_review = [x for x in biz
                  if (today - dt.timedelta(days=10)).isoformat() <= date_of(x)
                  < (today - dt.timedelta(days=3)).isoformat()]
    ov7 = recent(ov_main, 7, today)
    market7 = recent(ov_market, 7, today, 3)
    ov_review = [x for x in ov_main
                 if (today - dt.timedelta(days=10)).isoformat() <= date_of(x)
                 < (today - dt.timedelta(days=3)).isoformat()]
    projects7 = recent([x for x in snapshot['projects'] if project_news(x)], 7, today)
    policies30 = recent([x for x in snapshot['policies'] if formal_policy(x)], 30, today)
    digest30 = recent(snapshot['digest'], 30, today)
    used = set(root_key(title_of(x)) for x in biz3 + ov7)
    projects7 = unique(projects7, used)
    used.update(root_key(title_of(x)) for x in projects7)
    digest30 = unique(digest30, used)
    return {
        'biz3': unique(biz3)[:10], 'watch7': [], 'oversea7': unique(ov7)[:12],
        'projects7': projects7[:8], 'policies30': unique(policies30)[:6],
        'digest30': digest30[:6], 'market7': unique(market7),
        'reviewBiz': unique(biz_review)[:10], 'reviewOversea': unique(ov_review)[:8],
        'overseaAudit': {
            'main': len(ov_main), 'market': len(ov_market), 'archive': len(ov_archive),
            'archiveRows': [{'title': title_of(x), 'reason': why} for x, why in ov_archive],
        },
    }
