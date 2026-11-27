#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高耗能产业投资线索：采集端与邮件端共用的展示层规则。

只回答“是否值得作为潜在能源配套线索跟踪”，不判断①库能不能投，
不调用、不替代 biz_rules.judge()/semantic_drop()，也不回写①库。
"""
import json
import os
import re

# 海外产业投资才进入本链；国内钢铁/园区热电仍走原有审批、招标主链。
GEO = (
    '海外', '出海', '境外', '国外', '一带一路', '印尼', '印度尼西亚', '越南', '泰国',
    '马来', '菲律宾', '缅甸', '柬埔寨', '老挝', '新加坡', '巴淡', '印度', '巴基斯坦',
    '孟加拉', '哈萨克', '乌兹别克', '吉尔吉斯', '沙特', '阿联酋', '阿布扎比', '卡塔尔',
    '科威特', '阿曼', '伊拉克', '伊朗', '土耳其', '埃及', '摩洛哥', '阿尔及利亚',
    '尼日利亚', '南非', '肯尼亚', '埃塞俄比亚', '坦桑尼亚', '加纳', '喀麦隆', '安哥拉',
    '莫桑比克', '津巴布韦', '刚果', '赞比亚', '几内亚', '加蓬', '科特迪瓦', '塞内加尔',
    '俄罗斯', '塞尔维亚', '匈牙利', '巴西', '阿根廷', '智利', '秘鲁', '墨西哥', '澳大利亚',
)

# 行业词是“潜在用能场景”，不是①库收标词。能源机会只作跟进方向，不断言已经采购。
INDUSTRIES = (
    ('电解铝/氧化铝', ('电解铝', '氧化铝', '铝冶炼'), '自备电厂、余热利用、储能'),
    ('镍钴铜冶炼', ('镍', '钴', '铜冶炼', '铜业', '锌冶炼', '冶炼厂', '矿热炉', 'RKEF'),
     '自备电厂、煤气/余热发电、热电联产'),
    ('钢铁焦化', ('钢铁', '钢厂', '高炉', '烧结', '焦化', '焦炉', '焦炭', '热镀锌'),
     '煤气发电、余热余压、热电联产'),
    ('水泥建材', ('水泥', '熟料', '粉磨站'), '余热发电、自备电厂、供热'),
    ('化工化纤', ('化工', '石化', '化肥', '轮胎', '化纤', '聚酯', '造纸'),
     '热电联产、集中供热供汽、余热利用'),
    ('数据中心', ('数据中心', '算力中心', '智算中心', 'IDC'),
     '柴发、储能、分布式能源'),
)

STAGES = (
    ('能源配套采购', ('能源招标', '电力招标', '自备电站招标', '余热发电招标', '采购推进', '招中标', '中标')),
    ('投产/扩建', ('投产', '投运', '试运行', '扩建', '扩产', '二期', '三期')),
    ('开工/奠基', ('开工', '在建', '奠基', '动工', '施工建设', '落地建设')),
    ('备案/核准', ('备案', '核准', '审批通过', '批复', '获批')),
    ('签约/框架', ('正式签约', '签约', '框架协议', '合作框架', '签署', 'MOU', '备忘录')),
    ('拟投/磋商', ('拟投', '拟建', '新建', '计划投资', '投资建设', '落子', '磋商', '洽谈', '意向', '拟落地', '布局')),
)
ENERGY_WORDS = (
    '自备电厂', '自备电站', '余热发电', '余热补汽', '热电联产', '集中供热', '供热供汽',
    '煤气发电', '燃气电站', '燃煤电站', '电厂', '电站', '发电设施', '柴发', '柴油发电',
    '储能', '海水淡化', '能源岛', '动力岛',
)
NOISE = (
    '行情', '报价', '期货', '股价', '涨停', '跌停', '融资余额', '同比', '环比', '营收',
    '净利润', '利润', '招聘', '人事任免', '论坛', '峰会', '展会', '价格指数',
)
BACKGROUND = ('盘点', '全景图', '一文看懂', '企业百科', '公司介绍')
CN_WORDS = ('中资', '中企', '中国企业', '中方', '中国投资')


def _load_watch():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw', 'company_watch.json')
    try:
        data = json.load(open(path, encoding='utf-8'))
        groups = data.get('groups') or {}
        names = list(data.get('companies') or [])
        for values in groups.values():
            names += list(values or [])
        # 英文名/外资主体不能仅凭“在名单里”就判中资。
        return tuple(x for x in names if x and re.search(r'[\u4e00-\u9fff]', x))
    except Exception:
        return ()


WATCH = _load_watch()


def text_of(row):
    return ' '.join(str(row.get(k) or '') for k in (
        'title', 't', 'summary', 'snip', 'desc', 'm', 'name', 'buyer', 'win', 'tag'))


def _actor(text, known_owners=()):
    for name in tuple(known_owners) + WATCH:
        if name and re.search(r'[\u4e00-\u9fff]', str(name)) and str(name) in text:
            return str(name)
    for word in CN_WORDS:
        if word in text:
            return word
    # 新企业可由“中国××集团”泛化识别；普通中文译名不足以证明中资，避免外资集团混入。
    match = re.search(r'(中国[\u4e00-\u9fff]{1,14}(?:股份|集团|控股|有限公司|有限责任公司))', text)
    return match.group(1) if match else ''


def _stage(text):
    hits = [(label, word) for label, words in STAGES for word in words if word in text]
    # 有能源采购证据时优先显示，否则按项目生命周期中最明确的动作展示。
    for label, _ in hits:
        if label == '能源配套采购' and any(k in text for k in ENERGY_WORDS):
            return label
    for label, _words in STAGES[1:]:
        if any(word in text for word in _words):
            return label
    return hits[0][0] if hits else ''


def _source_status(row):
    url = (row.get('url') or row.get('u') or '').lower()
    if any(k in url for k in ('gov.cn', 'cninfo', 'sse.com', 'szse.cn', 'hkexnews')):
        return '公告/政府源'
    if any(k in url for k in ('mp.weixin.qq.com', '163.com', 'sohu.com', 'toutiao.com')):
        return '媒体线索·待核'
    return '公开媒体·待核'


def evaluate(row, known_owners=()):
    text = text_of(row)
    title = str(row.get('title') or row.get('t') or '')
    if not title or not any(k in text for k in GEO):
        return {'ok': False, 'reason': '非明确海外事件'}
    if any(k in title for k in BACKGROUND):
        return {'ok': False, 'reason': '企业背景盘点，非新增投资'}
    if any(k in title for k in NOISE):
        return {'ok': False, 'reason': '行情/经营/人事噪声'}
    industry = next(((name, words, energy) for name, words, energy in INDUSTRIES
                     if any(k in text for k in words)), None)
    if not industry:
        return {'ok': False, 'reason': '非目标高耗能产业'}
    stage = _stage(title) or _stage(text)
    if not stage:
        return {'ok': False, 'reason': '无新增投资或项目状态动作'}
    actor = _actor(text, known_owners)
    if not actor:
        return {'ok': False, 'reason': '中资主体待核'}
    name, _words, energy = industry
    explicit = [k for k in ENERGY_WORDS if k in text]
    geo = next((k for k in GEO if k in text), '海外')
    capacities = re.findall(r'\d+(?:\.\d+)?\s*(?:万吨|万金吨|万金属吨|吨/日|吨|t/d|MW|GW|兆瓦|万千瓦)', title, re.I)
    if not capacities:
        capacities = re.findall(r'\d+(?:\.\d+)?\s*(?:万吨|万金吨|万金属吨|吨/日|吨|t/d|MW|GW|兆瓦|万千瓦)', text, re.I)
    key = '|'.join((actor, geo, name, capacities[0] if capacities else ''))
    return {
        'ok': True, 'leadKey': key, 'leadActor': actor, 'leadIndustry': name,
        'leadStage': stage, 'leadGeo': geo,
        'energyOpportunity': ('已明确：' + '、'.join(explicit[:3])) if explicit else ('潜在：' + energy),
        'sourceStatus': _source_status(row),
    }


def enrich(row, known_owners=()):
    result = evaluate(row, known_owners)
    if not result.get('ok'):
        return None
    out = dict(row)
    out.update(dict((k, v) for k, v in result.items() if k != 'ok'))
    return out


def latest(rows, known_owners=()):
    """同一主体+国家+行业+产能只保留最新状态，旧阶段不重复邮件。"""
    chosen = {}
    audits = []
    for row in rows:
        item = enrich(row, known_owners)
        if not item:
            audits.append({'title': row.get('title') or row.get('t'),
                           'reason': evaluate(row, known_owners).get('reason')})
            continue
        old = chosen.get(item['leadKey'])
        if not old or str(item.get('date') or item.get('d') or '') >= str(old.get('date') or old.get('d') or ''):
            chosen[item['leadKey']] = item
    return list(chosen.values()), audits
