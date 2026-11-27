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
    '孟加拉', '哈萨克', '乌兹别克', '吉尔吉斯', '蒙古', '沙特', '阿联酋', '阿布扎比', '卡塔尔',
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
    ('化工化纤', ('化工', '石化', '炼化', '化肥', 'DAP', '轮胎', '化纤', '聚酯', '造纸',
                '乙烯', '聚乙烯', '聚丙烯'),
     '热电联产、集中供热供汽、余热利用'),
    ('有色金属加工', ('铜箔', '铜材', '铝板带', '铝型材', '铜加工', '铝加工'),
     '自备电厂、余热利用、储能'),
    ('电子制造', ('PCB', '印制电路板', '覆铜板', '电子材料'),
     '自备电厂、余热利用、储能'),
    ('数据中心', ('数据中心', '算力中心', '智算中心', 'IDC'),
     '柴发、储能、分布式能源'),
)

STAGES = (
    ('能源配套采购', ('能源招标', '电力招标', '自备电站招标', '余热发电招标', '采购推进', '招中标', '中标')),
    ('投产/扩建', ('投产', '投运', '试运行', '扩建', '扩产', '扩能', '二期', '三期')),
    ('开工/奠基', ('开工', '在建', '奠基', '动工', '施工建设', '落地建设', '参与建设',
                '参建', '承建')),
    ('备案/核准', ('备案', '核准', '审批通过', '批复', '获批')),
    ('签约/框架', ('正式签约', '签约', '框架协议', '合作框架', '签署', 'MOU', '备忘录', '增资')),
    ('拟投/磋商', ('拟投', '拟建', '新建', '计划投资', '投资计划', '投资建设', '落子',
                '磋商', '洽谈', '谈判', '意向', '拟落地', '布局')),
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
CN_WORDS = ('中资', '中企', '中国企业', '中方', '中国投资', '中国云厂商', '中国厂商')


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
    names = tuple(known_owners) + WATCH
    matched = [str(name) for name in names
               if name and re.search(r'[\u4e00-\u9fff]', str(name)) and str(name) in text]
    if matched:
        # “协鑫”与“协鑫集团”同时命中时取全称，否则同一项目会生成两个跟踪键。
        return max(matched, key=len)
    # 关注名单里的“振石控股”正文常只写“振石”；仅对 3 字以上核心名做简称匹配，
    # 避免“通用股份”这类核心词过短造成误命中。
    for name in names:
        core = re.sub(r'(?:集团|控股|股份|有限公司|公司)$', '', str(name or ''))
        if len(core) >= 3 and core in text:
            return core
    # 中国央企/工程平台的常用简称；外企中文译名不在这些前缀内。
    group = re.search(
        r'(中国化学工程[\u4e00-\u9fff]{0,12}?(?:有限公司|集团|公司|化建|建设局|工程局)|'
        r'中国(?:能建|电建|中冶|有色|建材|机械|港湾|交建|中铁|中建|中铝)'
        r'[\u4e00-\u9fff]{0,8}?(?:集团|股份|有限公司|公司)?|'
        r'中(?:材建设|色股份|钢国际|冶赛迪|冶京诚|铝国际|工国际)|国机集团|中国电工|永福股份)', text)
    if group:
        return group.group(1)
    # A股公告语境下，公司简称本身就是中资判据；外企中文译名没有这层语境。
    if re.search(r'A股|上市公司|证券代码|公告编号|公告|上交所|深交所|创业板|主板|股份有限公司', text):
        listed = re.search(r'([\u4e00-\u9fff]{2,10}(?:股份|集团|科技|控股))', text)
        if listed:
            return listed.group(1)
    # “中资企业鼎森钢铁公司”这类明确中资语境，可在语境后提取实际主体，避免全部归成“中资”。
    chinese = re.search(
        r'(?:中资企业|中资公司|中企|中国企业|中方企业)'
        r'([\u4e00-\u9fff]{2,14}(?:公司|集团|股份|钢铁|水泥|化工|轮胎|科技|建设))', text)
    if chinese:
        return chinese.group(1)
    # 省级企业全称可证明中资来源，如“湖南省力宇燃气动力有限公司”。
    provincial = re.search(
        r'((?:北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|'
        r'河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|陕西|甘肃|青海|宁夏|新疆)'
        r'(?:省|市|自治区)?[\u4e00-\u9fff]{2,14}(?:有限公司|集团|股份))', text)
    if provincial:
        return provincial.group(1)
    # 标题常用“湖南力宇签署”“广东某公司拟建”这类省名+简称，缺少“有限公司”后缀。
    provincial_short = re.search(
        r'((?:北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|'
        r'河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|陕西|甘肃|青海|宁夏|新疆)'
        r'[\u4e00-\u9fff]{2,8})(?=签署|签约|拟|计划|投资|扩建|新建|建设|中标|启动|开工)', text)
    if provincial_short:
        return provincial_short.group(1)
    for word in CN_WORDS:
        if word in text:
            # 明确中资语境但未给全称时，取标题开头的动作主体作为跟踪键
            # （如“振石印尼…”“字节跳动拟…”），不能把“拟/印尼”吃进公司名。
            lead = re.match(
                r'([\u4e00-\u9fff]{2,8}?)(?=印尼|越南|马来|泰国|菲律宾|印度|沙特|阿联酋|'
                r'埃及|摩洛哥|阿尔及利亚|尼日利亚|南非|肯尼亚|坦桑尼亚|津巴布韦|赞比亚|'
                r'几内亚|加蓬|巴西|哈萨克|蒙古|澳大利亚|拟|计划|将|正|扩|投资|签署|签约|启动|参与)', text)
            return lead.group(1) if lead else word
    # 新企业可由“中国××集团”泛化识别；普通中文译名不足以证明中资，避免外资集团混入。
    match = re.search(r'(中国[\u4e00-\u9fff]{1,14}(?:股份|集团|控股|有限公司|有限责任公司))', text)
    return match.group(1) if match else ''


def _stage(text):
    # “拟扩建/拟新建”是计划动作，不能因为出现“扩建/新建”就误显示为已投产或在建。
    if re.search(r'拟(?:投资|建设|扩建|新建|落地|布局)|计划(?:投资|建设|扩建|新建)', text):
        return '拟投/磋商'
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
    # 标题里同时出现“钢铁厂配套水泥厂”时，以标题中最后出现的行业词为准，
    # 不能按固定行业顺序把水泥项目误归钢铁；标题无行业词才回退正文。
    ranked = []
    for order, (name, words, energy) in enumerate(INDUSTRIES):
        hits = [title.rfind(k) for k in words if k in title]
        if hits:
            ranked.append((max(hits), -order, (name, words, energy)))
    if not ranked:
        for order, (name, words, energy) in enumerate(INDUSTRIES):
            hits = [text.rfind(k) for k in words if k in text]
            if hits:
                ranked.append((max(hits), -order, (name, words, energy)))
    industry = max(ranked, default=(0, 0, None))[2]
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
    if geo in ('出海', '境外', '国外'):
        geo = '海外'
    capacities = re.findall(r'\d+(?:\.\d+)?\s*(?:万吨|万金吨|万金属吨|吨/日|吨|t/d|MW|GW|兆瓦|万千瓦)', title, re.I)
    if not capacities:
        capacities = re.findall(r'\d+(?:\.\d+)?\s*(?:万吨|万金吨|万金属吨|吨/日|吨|t/d|MW|GW|兆瓦|万千瓦)', text, re.I)
    # 跟踪键用去掉“集团/股份/控股”等后缀的主体核心名，避免“协鑫”和“协鑫集团”
    # 被当成两个项目重复输出；展示名仍保留正文里的正式称呼。
    key_actor = re.sub(r'(?:集团|控股|股份|有限公司|公司)$', '', actor) or actor
    key = '|'.join((key_actor, geo, name, capacities[0] if capacities else ''))
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
