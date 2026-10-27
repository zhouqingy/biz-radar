# -*- coding: utf-8 -*-
"""数据清洗 + 重分类 + 融合引擎
把「老版1383条」与「新一轮检索272条」统一到一套对齐公司主业的分类规则下。
"""
import json, re, os, hashlib
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')

# ============ 1. 分类规则（对齐公司四大主业） ============
# 顺序即优先级：越靠前越优先命中。每条 (子类, 一级业务, [关键词])
RULES = [
    # ---- 能源清洁高效利用（核心主业）----
    ('热电联产',      '能源清洁高效利用', ['热电联产','热电机组','热电扩建','热电改扩建','背压机组','背压式','抽背','抽凝','供热机组','热电有限公司','热电厂','热电集团','热电二期']),
    ('余热发电',      '能源清洁高效利用', ['余热发电','余热利用','余热回收','余热锅炉','余能利用','烧结环冷','环冷机余热','干熄焦','CDQ','水泥窑余热','玻璃窑余热','低温余热','ORC','有机朗肯','烟气余热','余热资源','余压利用','压差发电','TRT','煤气锅炉']),
    ('煤气发电',      '能源清洁高效利用', ['煤气','煤气发电','高炉煤气','焦炉煤气','转炉煤气','煤气综合利用','CCPP','燃气-蒸汽联合循环','燃气蒸汽联合循环','煤气资源','煤气精制','燃气发电','燃机']),
    ('光伏与储能',    '能源清洁高效利用', ['光伏','光伏发电','分布式光伏','屋顶光伏','渔光互补','农光互补','储能','电化学储能','储能电站','光储','绿电','源网荷储','屋顶分布式','屋面光伏','储能系统','压缩空气储能','熔盐储热','氢储能','配套新能源','新能源项目','新能源发电','集中式光伏','风光储']),
    ('燃煤火电',      '能源清洁高效利用', ['燃煤发电','燃煤机组','燃煤火电','火力发电','火电厂','燃煤锅炉','电站锅炉','循环流化床','CFB','锅炉岛','汽轮机','发电机组','燃煤机组','电厂扩建','发电工程','发电项目','锅炉房','锅炉改造','锅炉扩容','锅炉更新','锅炉系统','锅炉本体','锅炉设备','锅炉烟气','#3锅炉','3#锅炉','锅炉检修','锅炉技改','2×660MW','输煤系统','储煤场','卸煤','斗轮堆取料','采样装置','煤场','掺烧','调峰火电','火电机组']),
    ('柴油发电机',    '能源清洁高效利用', ['柴油发电','柴发','柴油发电机组','备用电源','应急电源','柴油机组','柴机']),
    ('供热与综合能源','能源清洁高效利用', ['集中供热','供热管网','热力管网','供暖锅炉','供热改造','供热管道','综合能源','综合能源站','多能互补','分布式能源','能源站','供汽','蒸汽管网','余热供暖','生物质锅炉','生物质热电','掺烧','燃煤替代','清洁供热','供热','供暖','换热站','热力站','热网','冷热联供','冷热三联供','区域能源','区域集中','供冷','园区供热','供热中心','热力公司','热网','智慧热网','启动锅炉','工业供汽','蒸汽管道','智慧能源','智慧综合能源','能源中心','蒸汽管道建设','热力管道']),
    # ---- 废气处理 ----
    ('脱硫脱硝',      '废气处理', ['脱硫','脱硝','SCR','SNCR','烟气脱硫','烟气脱硝','半干法','氨法脱硫','低氮改造','低氮燃烧','精准喷氨']),
    ('除尘与超低排放','废气处理', ['除尘','电除尘','布袋除尘','超低排放','烟气治理','烟气净化','烟气除尘','烧结机头','焦炉烟气','排放改造']),
    ('VOCs治理',      '废气处理', ['VOCs','VOC','有机废气','RTO','RCO','沸石转轮','恶臭治理','异味治理','挥发性有机物']),
    # ---- 废水处理 ----
    ('海水淡化',      '废水处理', ['海水淡化','苦咸水淡化','反渗透淡化','淡化']),
    ('废水零排放',    '废水处理', ['零排放','废水零排','分盐','蒸发结晶','高盐废水','脱硫废水','浓盐水','结晶分盐','近零排放']),
    ('冶金/工业废水', '废水处理', ['工业废水','工业污水','冶金废水','焦化废水','冷轧废水','园区污水','工业污水处理','中水回用','废水处理站','废水站','水处理站','污水处理站']),
    ('市政污水',      '废水处理', ['污水处理厂','污水厂','生活污水','城镇污水','污水管网','污水处理','提标改造','水质净化','再生水']),
    # ---- 环境修复 ----
    ('土壤与场地修复','环境修复', ['土壤修复','场地修复','污染土壤','土壤污染','土壤和地下水','地下水修复','地下水污染','矿山修复','矿山治理','生态修复','污染地块','场地污染','地块污染','污染修复','修复处置','应急处置','重金属污染','土壤治理','修复工程','地块)','污染地块']),
    # ---- 明确非主业 ----
    # ⚠ 2026-10-22：这里原来还有一条
    #   ('垃圾焚烧发电', '其他非主业', ['垃圾焚烧','焚烧发电','焚烧厂','生活垃圾焚烧','炉渣'])
    #   已删除 —— 垃圾焚烧现在归能源主业（见 classify() 开头的前置判断）。
    #   留着会变成两条冲突规则：前置判断先命中归主业，这条永远轮不到，
    #   看着像还在生效、实际是死代码，最容易误导后来改的人。
    ('固废与污泥',    '其他非主业', ['污泥','固废','一般工业固废','危险废物','危废','餐厨','垃圾处置','垃圾处理','飞灰','填埋','农业废弃','秸秆']),
    ('燃气与输配',    '其他非主业', ['天然气','燃气管网','燃气管道','LNG','门站','加气站','调压站']),
    ('输变电与配电',  '其他非主业', ['变电站','输变电','配电工程','开闭所','电缆','线路工程','增容']),
    ('市政园林房建',  '其他非主业', ['道路','桥梁','园林','绿化','公园','房建','厂房','装修','停车场','雨污分流','河道','驳岸','照明','景观','市政道路','学校','医院','体育场','公厕','社区','办公楼']),
    ('市政供水',      '其他非主业', ['供水改造','供水管网','供水管线','给水','自来水管网','二次供水','泵站','水厂','自来水','城市供水','城乡供水','供水设施','供水保障','供水项目','水质提升','供水压力','城乡一体化供水']),
    ('化工冶金工艺',  '其他非主业', ['甲醇','乙烯','化学品','精细化工','生产线','设备更新','设备供货','设备采购','供货','竞价销售','招标预告','大修','检修','维修','保养','检测','监理','勘察设计','可行性研究','劳务','运维服务','运输','装车台','油气回收','油库','堆场','仓储','采矿','选矿','球团','烧结机','炼铁','炼钢','转炉','连铸','轧钢']),
    ('环卫与物业',    '其他非主业', ['环卫','保洁','物业','食堂','安保','绿化养护','停车',]),
]

# 有些关键词带歧义，需要排除：(关键词组合)-> 强制归类
OVERRIDE_NONCORE = ['垃圾焚烧', '焚烧发电', '生活垃圾']  # 含这些词的优先归"垃圾焚烧发电"

# 关键词带了但是【非总承包标的】，公司做 EPC/F+EPC/EPC+O/EP，这些零散标不应占高优先级
DOWNGRADE = ['监理','可行性研究','可研','评估咨询','招标代理','造价咨询','备件','备品备件','物资采购',
             '检修','维修','保养','维护','运维服务','检测','检验','运输','租赁','询价','竞价','谈判采购',
             '单一来源','定点采购','打印','保安','保洁','劳务','培训','软件','云平台','系统设计']
# 只要带这些，说明是真·工程总承包标的（公司能吃下的）
STRUCK = ['EPC','工程总承包','施工总承包','总承包','EPCO','EP+','PC总承包','交钥匙','BOT','PC工程']

CORE_BIZ = '能源清洁高效利用'
BIZ_SCORE = {'能源清洁高效利用': 50, '废气处理': 34, '废水处理': 32, '环境修复': 24, '其他非主业': 4}
STAGE_OP = {'招标公告': 20, '招标计划': 18, '中标候选人公示': 11, '立项公示': 8, '变更公告': 4, '中标结果公示': 3}

CITY_MAP = {
    '江苏': ['南京','苏州','无锡','常州','镇江','南通','扬州','泰州','盐城','淮安','连云港','徐州','宿迁'],
    '浙江': ['杭州','宁波','温州','绍兴','湖州','嘉兴','金华','衢州','台州','丽水','舟山'],
    '安徽': ['合肥','芜湖','马鞍山','铜陵','安庆','滁州','阜阳','蚌埠','淮南','淮北','六安','宿州','宣城','黄山','池州','亳州'],
    '上海': ['上海','浦东','宝山','金山','化工区','临港','嘉定','松江','奉贤','闵行','杨浦','徐汇','崇明','青浦'],
}


def classify(text):
    """返回 (一级业务, 子类)"""
    s = text or ''
    # 垃圾焚烧：归「能源清洁高效利用」主业的**垃圾焚烧发电**细分。
    #
    # ⚠ 2026-10-22 改：原来这里 return '其他非主业', '垃圾焚烧发电'
    #   —— 注释写的是「优先归垃圾焚烧发电」，代码却把它丢进非主业（4 分），
    #   而能源主业是 50 分，一进一出差 46 分。结果：全库 67 条垃圾焚烧
    #   有 55 条被判 D 档、A/B 档 0 条，在「找商机」里基本等于隐形。
    #   但都市环保的垃圾焚烧厂 EPC 和余热利用是实打实在做的活
    #   （用户口径：余热锅炉+发电是最大业绩来源之一），不该当非主业。
    #   现在归主业，但在 grade() 里单独降一档 —— 它确实不是第一优先级。
    if any(k in s for k in OVERRIDE_NONCORE) and '焚烧' in s:
        return '能源清洁高效利用', '垃圾焚烧发电'
    for sub, biz, kws in RULES:
        for k in kws:
            if k in s:
                return biz, sub
    return '其他非主业', '未分类'


def parse_amt(v):
    """把各种金额文本/数字转成元"""
    if v is None: return None
    if isinstance(v, (int, float)):
        v = float(v)
        return None if (v == 0 or v > 1e10) else v
    s = str(v).strip()
    if not s or s in ('—', '-', 'None', 'null', '无'): return None
    try:
        return float(s)
    except ValueError:
        pass
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*(亿元|万元|亿|万|元)', s)
    if m:
        try:
            n = float(m.group(1).replace(',', ''))
            u = m.group(2)
            if u.startswith('亿'): v = n * 1e8
            elif u.startswith('万'): v = n * 1e4
            else: v = n
            return None if v > 1e10 else v
        except ValueError:
            pass
    return None


def parse_scale(text):
    """从摘要/标题提取装机规模信号，返回 MW 等效值"""
    s = (text or '')
    mw = 0.0
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(MW|兆瓦)', s, re.I):
        mw += float(m.group(1))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(?:万?千瓦|kW)(?![Ww])', s):
        v = float(m.group(1))
        mw += v / 1000.0
    kw = 0.0
    for m in re.finditer(r'(\d+(?:,\d{3})+)\s*kW', s, re.I):
        kw += float(m.group(1).replace(',', ''))
    mw += kw / 1000.0
    # 锅炉吨位 -> 粗略折算发电 MW（约 1t/h ≈ 0.22MW 热工当量粗估）
    b = 0.0
    for m in re.finditer(r'(?<![\d.])(\d+(?:\.\d+)?)\s*t/h', s):
        b += float(m.group(1))
    for m in re.finditer(r'(\d+)\s*(?:吨/小时|蒸吨)', s):
        b += float(m.group(1))
    return {'mw': round(mw, 2), 'boiler_tph': round(b, 1)}


def size_score(amt, sc, text):
    mw, tph = sc['mw'], sc['boiler_tph']
    if amt:
        if amt >= 3e8: return 30
        if amt >= 1e8: return 22
        if amt >= 3e7: return 14
        if amt >= 1e7: return 9
        return 4
    if mw >= 100: return 30
    if mw >= 30: return 22
    if mw >= 10: return 14
    if mw > 0: return 9
    if tph >= 500: return 26
    if tph >= 200: return 18
    if tph > 0: return 10
    if re.search(r'(\d+(\.\d+)?\s*亿)', text or ''): return 20
    return 0


def guess_city(rg, text):
    for c in CITY_MAP.get(rg, []):
        if c in (text or ''):
            return c
    return ''


def strike_score(title, amt, sc):
    """总承包标的加成 / 零散标降权，返回调整分。只看标题，避免摘要噪声抬升等级"""
    t = (title or '')
    up = any(k.upper() in t.upper() for k in STRUCK)
    down = any(k in t for k in DOWNGRADE)
    if up: return 12
    if down and not up: return -28
    return 0


def is_pure_pipe(title, snip):
    """纯管网/管道施工（无发电/热电设备内容）＝非公司目标标的"""
    t = (title or '') + (snip or '')
    has_pipe = re.search(r'管网|管道|管廊|厂外管道|供热线路', t)
    has_core = re.search(r'热电|发电|余热|锅炉|机组|电厂|储能|光伏|汽轮|煤气', t)
    return bool(has_pipe and not has_core)


def grade(biz, sub, st, amt, sc, text, title='', snip=''):
    sco = BIZ_SCORE.get(biz, 4) + size_score(amt, sc, text) + STAGE_OP.get(st, 4) + strike_score(title, amt, sc)
    core = (biz == CORE_BIZ)
    # 垃圾焚烧归了主业，但它不是我们的第一优先级（热电联产/余热发电才是）。
    # 减 12 分：一个 3 亿的垃圾焚烧 EPC 算下来 ≈ 76 分，仍然进不了 A 档（门槛 78），
    # 但能稳稳进 B 档 —— 从"完全隐形"变成"值得看一眼"，这个位置是合适的。
    if sub == '垃圾焚烧发电':
        sco -= 12
    if is_pure_pipe(title, snip):
        sco = min(sco, 44)          # 纯管网施工最多给 C
    big = (amt and amt >= 1e8) or sc['mw'] >= 30 or sc['boiler_tph'] >= 220
    if core and sco >= 78 and big and not is_pure_pipe(title, snip):
        return 'A', sco
    if core and sco >= 62:
        return 'B', sco
    if sco >= 62:
        return 'B', sco
    if sco >= 45:
        return 'C', sco
    return 'D', sco


def norm_stage(s):
    s = (s or '').strip()
    # 顺序敏感：先判最具体的表述，再判泛化词
    if '候选人' in s or '评标' in s: return '中标候选人公示'
    if '中标' in s and ('结果' in s or '公告' in s): return '中标结果公示'
    if '中标' in s: return '中标结果公示'
    if '变更' in s or '更正' in s or '澄清' in s: return '变更公告'
    if '招标计划' in s or '采购计划' in s or '意向公开' in s or '计划' in s: return '招标计划'
    if '立项' in s or '审批' in s or '备案' in s or '核准' in s or '批复' in s: return '立项公示'
    if '招标' in s or '磋商' in s or '询价' in s or '竞谈' in s or '谈判采购' in s: return '招标公告'
    return '其他'


def clean_url(u):
    u = (u or '').strip()
    if u in ('None', 'null', '无', ''): return ''
    return u


# 程序性/阶段性词汇：同一项目在不同阶段会挂不同标题，去重时必须剥掉，
# 否则「评标结果公示」和「中标结果公告」会被当成两个项目各占一行（2026-10-10 用户实测发现）。
# 注意：**不能剥掉括号里的标段信息**（(二期)、(一阶段)、上煤系统、锅炉等），
# 否则会把同一项目的不同标段错误合并。
STAGE_NOISE = ['中标候选人公示', '评标结果公示', '定标结果公示', '中标结果公示', '中标结果公告',
               '资格后审公告', '资格预审公告', '公开谈判采购', '谈判采购', '中标候选人',
               '评标结果', '定标结果', '中标结果', '中标公告', '中标公示', '招标公告',
               '资格后审', '资格预审', '候选人', '二次公示', '重新招标', '评标', '定标',
               '预审', '后审', '招标', '中标', '公示', '公告', '结果', '重新', '变更',
               '更正', '澄清', '补充', '第一次', '第二次', '第三次', '一次', '二次', '三次']


def key_of(t, buyer, d):
    """去重键：标题归一化（剥程序性词汇，保留标段信息）。
    早期版本返回 (标题[:45], 业主[:6])，两个问题：
      1) 业主常缺失，导致「宿松县生物质热电联产项目」和带公司名的同一条无法合并；
      2) 截断到 45 字，长标题的不同标段会被误并。
    现改为返回**完整归一化标题**，业主不再进键；业主冲突改在子串合并那一步单独保护。
    """
    tn = t or ''
    # ① 先整块剥掉标段/公告编号，如 [A3302060260026708001001]、[E3300000007...]
    #    不剥的话，括号被后面的规则剥掉、只剩字母数字串，同一条公告会被判成两条
    tn = re.sub(r'[\[【]\s*[A-Za-z]{0,4}\d{6,}[^\]】]{0,24}[\]】]', '', tn)
    tn = re.sub(r'[（(]\s*[A-Za-z]{0,4}\d{6,}[^)）]{0,24}[)）]', '', tn)
    # ② 只剥纯程序性的括号后缀，(二期)/(一阶段)/上煤系统等标段信息必须保留
    tn = re.sub(r'[（(](?:二次公示|第[一二三四五\d]+次|重新招标|更正|澄清|补充|变更)[)）]', '', tn)
    tn = re.sub(r'[\s\u3000,，。、;；:：·\-—_/（）()【】\[\]]+', '', tn)
    for w in STAGE_NOISE:
        tn = tn.replace(w, '')
    tn = re.sub(r'项目{2,}$', '项目', tn)
    return tn


def info_score(r):
    """信息完整度：用于去重时择优保留"""
    return (1 if r.get('win') else 0) * 4 + (1 if r.get('amt') else 0) * 3 + \
           (1 if r.get('url') else 0) * 2 + (1 if r.get('buyer') else 0) + \
           len(r.get('snip') or '') / 300.0


# ============ 2. 载入新采集数据 ============
def guess_rg(text):
    """从标题/摘要里的城市名反推省份（供每周增量数据补全 rg）"""
    for rg, cities in CITY_MAP.items():
        for c in cities:
            if c in (text or ''):
                return rg
    return ''


def make_rec(x, prov):
    return {
            't': (x.get('t') or '').strip(),
            'rg': prov,
            'city': (x.get('city') or '').strip() or guess_city(prov, (x.get('t') or '') + (x.get('snip') or '')),
            'st': norm_stage(x.get('st')),
            'buyer': (x.get('buyer') or '').strip(),
            'win': (x.get('win') or '').strip(),
            'amt': parse_amt(x.get('amt')),
            'amtTxt': (x.get('amtTxt') or '').strip(),
            'd': (x.get('d') or '')[:10],
            'dl': '' if str(x.get('dl')) in ('None', 'null') else (str(x.get('dl'))[:10]),
            'p': (x.get('p') or '').strip(),
            'url': clean_url(x.get('url')),
            'snip': (x.get('snip') or '').strip()[:400],
            'mode': (x.get('mode') or '').strip(),
            # 提前量标记：发改委核准/备案、招标计划预公告、环评公示等「正式招标之前」的信号
            # 取值见 EARLY_SRC，为空表示普通交易中心公告
            'early': (x.get('early') or '').strip(),
            # 信源分级：official=公共资源交易平台原文；reprint=转载站/聚合站
            'srcType': (x.get('srcType') or '').strip(),
            'platLevel': (x.get('platLevel') or '').strip(),
            # 附件清单：[{n:文件名, u:下载地址}]，由扫描详情页得到
            'files': x.get('files') if isinstance(x.get('files'), list) else [],
            # 原始发布平台：{'n':平台名, 'u':原始链接(可空)}，来自详情页「来源：XX平台」
            'origin': x.get('origin') if isinstance(x.get('origin'), dict) else None,
            # 空壳页标记：抓取时详情页正文为空/打不开
            'shell': 1 if x.get('shell') else 0,
            '_new': True,
    }


new = []
for prov, fn in [('江苏', 'jiangsu.json'), ('浙江', 'zhejiang.json'), ('安徽', 'anhui.json'), ('上海', 'shanghai.json')]:
    p = os.path.join(RAW, fn)
    if not os.path.exists(p): continue
    for x in json.load(open(p, encoding='utf-8')):
        r = make_rec(x, prov)
        if not r['t']: continue
        new.append(r)

# ---- 城市全生命周期采集（多城市模板：南通 EWB-FRONT / 安徽 ggzy.ah.gov.cn）----
# 出口A：与业务相关的照常走 classify/grade 严筛（judge 在下游统一做）；
#        计划/提前公示 → 招标计划档，公告 → 招标公告，结果/合同 → 中标结果，
#        立项批复 → 立项公示（审批平台源头）
STAGE_MAP = {'plan': '招标计划', 'prep': '招标计划', 'notice': '招标公告',
             'cand': '中标候选人公示', 'result': '中标结果公示', 'contract': '中标结果公示',
             'approval': '立项公示',
             # 江苏省站扩展体系（水利/交通/政采，2026-10-24）
             'sl-plan': '招标计划', 'sl-notice': '招标公告', 'sl-cand': '中标候选人公示',
             'sl-result': '中标结果公示', 'jt-plan': '招标计划', 'jt-notice': '招标公告',
             'jt-cand': '中标候选人公示', 'jt-result': '中标结果公示',
             'cg-notice': '招标公告', 'cg-result': '中标结果公示'}
CITY_FILES = [
    ('nt_lifecycle.json', '南通', '江苏', '南通市公共资源交易平台'),
    ('ah_lifecycle.json', '安徽', '安徽', '安徽省公共资源交易监管平台'),
    # 省站一份接口覆盖江苏 13 市（每条自带 city，经 area 字段落入 _cityval）
    ('js_lifecycle.json', '江苏', '江苏', '江苏省公共资源交易平台'),
]
def _jload_any(*paths):
    """依次尝试路径，支持 .json / .json.gz（CI 仓库只存 gz 省体积）"""
    import gzip
    for _p in paths:
        if os.path.exists(_p):
            try:
                if _p.endswith('.gz'):
                    return json.load(gzip.open(_p, 'rt', encoding='utf-8'))
                return json.load(open(_p, encoding='utf-8'))
            except Exception:
                continue
    return None

for _fn, _city, _rg, _plat in CITY_FILES:
    _fp = _jload_any(os.path.join(RAW, _fn), os.path.join(RAW, _fn + '.gz'))
    if _fp is None:
        continue
    _nn = 0
    _ncon = 0
    # 纯施工标段：标题含「施工」且不带总承包/EPC/设计等关键词 → 剔除
    #（盖住 施工公告 / 施工中标结果公告 / 施工资格后审 / 扩建施工 等各种尾巴）
    _CON_ONLY = re.compile(
        r'施工|[管网道绿化附属亮化路基路面厂区装修]工程?施工|土建施工|零星维修|修缮工程')
    _TURNKEY = re.compile(r'EPC|总承包|设计|监理|勘察|咨询|运营|检测')
    for _x in (_fp.get('items') or []):
        _det = _x.get('detail') or {}
        _cityval = _city
        if _x.get('city'):
            # 省站条目自带干净城市名（南通市/盐城市…）
            _cityval = _x['city']
        elif _x.get('area'):
            _cityval = _x['area'].split('-')[0].strip() or _city
        # 省站(js)无 detail，从列表摘要里抽招标人/中标人
        _snip = _x.get('snip') or ''
        _snb = _snw = ''
        if _snip:
            _m = re.search(r'招标人[为是]([\u4e00-\u9fa5A-Za-z0-9（）()]{4,30})', _snip)
            _snb = _m.group(1) if _m else ''
            _m = re.search(r'(?:中标人|中标单位|第一中标候选人)[名为是]([\u4e00-\u9fa5A-Za-z0-9（）()]{4,40})', _snip)
            _snw = _m.group(1) if _m else ''
        _r = make_rec({
            't': _x.get('t'), 'rg': _rg, 'city': _cityval,
            'st': STAGE_MAP.get(_x.get('cat'), ''),
            'buyer': (_det.get('buyer') or _snb).strip(),
            'win': (_det.get('win') or _snw).strip(),
            # detail.win_amt 单位是亿，merged 体系 amt 单位是元
            'amt': (_det.get('win_amt') or 0) * 1e8 or None,
            'd': _x.get('d'), 'p': _plat,
            'url': _x.get('url'),
            # 立项批复把批复部门带进摘要，页面上能看出是哪个发改委批的；
            # 省站条目把列表摘要截 120 字带出（招标人/候选人信息）
            'snip': ('批复部门：' + _x['dept']) if _x.get('dept') else ('摘要：' + _snip[:120] if _snip else ''),
        }, _rg)
        if not _r['t']:
            continue
        # 纯施工标段剔除（2026-10-24 用户反馈）：「扩建施工」「管网施工」这类
        # 土建/安装标段只进业主/对手画像（出口B直接读原始文件，不受影响），
        # 不进找商机库占版面。带 EPC/总承包/设计/监理/勘察 的仍保留。
        _tt = _r['t']
        if _CON_ONLY.search(_tt) and not _TURNKEY.search(_tt):
            _ncon += 1
            continue
        new.append(_r)
        _nn += 1
    print(f'[城市生命周期:{_city}] 注入 {_nn} 条（纯施工标段剔除 {_ncon} 条）')

# ---- 每周增量：raw/weekly/*.json（定时任务每轮写入，字段与省级采集文件一致）----
WEEKLY = os.path.join(RAW, 'weekly')
if os.path.isdir(WEEKLY):
    nw = 0
    for fn in sorted(os.listdir(WEEKLY)):
        if not fn.endswith('.json'): continue
        try: arr = json.load(open(os.path.join(WEEKLY, fn), encoding='utf-8'))
        except Exception as e:
            print('[WARN] weekly/%s 解析失败: %s' % (fn, e)); continue
        for x in arr:
            txt = (x.get('t') or '') + ' ' + (x.get('snip') or '')
            rg = (x.get('rg') or '').strip() or guess_rg(txt) or ''
            if rg not in ('江苏', '浙江', '安徽', '上海'):
                continue   # 无法归入四地则丢弃，严守区域边界
            r = make_rec(x, rg)
            if not r['t']: continue
            new.append(r); nw += 1
    print('每周增量数据: %d 条（raw/weekly/）' % nw)

# ---- 提前量：raw/early/*.json（发改委批复、招标计划预公告、环评公示、规划批复等）----
# 这类信号出现在「正式招标公告」之前，是本页最稀缺的提前量。
# 字段与 weekly 一致，额外必填 early（渠道标记），可选 expect（预计招标时间）。
EARLY_SRC = {'发改委核准': '立项公示', '发改委备案': '立项公示', '招标计划': '招标计划',
             '环评公示': '立项公示', '节能审查': '立项公示',
             '上市公告': '立项公示',   # 上市公司募投/对外投资公告：董事会阶段就披露，早于批复
             '技改备案': '招标计划',   # 工信/经信技改项目备案：已定项目，距招标近
             '重大项目清单': '立项公示',
             '工信厅名单': '立项公示',   # 2026-10-27 省工信厅制造强省/产能置换名单：政府拟支持，确定要建
             '热电规划': '立项公示'}   # 省市发改委热电联产/集中供热规划批复：比核准更早，点名未来热源点
EARLY_DIR = os.path.join(RAW, 'early')
if os.path.isdir(EARLY_DIR):
    ne = 0
    for fn in sorted(os.listdir(EARLY_DIR)):
        if not fn.endswith('.json'): continue
        try: arr = json.load(open(os.path.join(EARLY_DIR, fn), encoding='utf-8'))
        except Exception as e:
            print('[WARN] early/%s 解析失败: %s' % (fn, e)); continue
        for x in arr:
            txt = (x.get('t') or '') + ' ' + (x.get('snip') or '')
            rg = (x.get('rg') or '').strip() or guess_rg(txt) or ''
            if rg not in ('江苏', '浙江', '安徽', '上海'):
                continue   # 同样严守四地边界
            src = (x.get('early') or '').strip()
            if src and src in EARLY_SRC:
                x['st'] = EARLY_SRC[src]      # 渠道决定阶段，覆盖原始 st
            r = make_rec(x, rg)
            if not r['t']: continue
            r['expect'] = (x.get('expect') or '').strip()   # 预计招标/开工时间
            new.append(r); ne += 1
    print('提前量数据: %d 条（raw/early/）' % ne)

print(f'新采集原始数据: {len(new)} 条')

# ============ 3. 载入老版数据并重新分类 ============
old_raw = json.load(open(os.path.join(ROOT, 'legacy_D.json'), encoding='utf-8'))
old = []
for x in old_raw:
    rg = x.get('rg', '')
    if rg not in ('江苏', '浙江', '安徽', '上海'): continue   # 剔除外省，严守四地边界
    text = (x.get('t') or '') + ' ' + (x.get('snip') or '')
    r = {
        't': (x.get('t') or '').strip(),
        'rg': rg,
        'city': guess_city(rg, text),
        'st': norm_stage(x.get('st')),
        'buyer': (x.get('buyer') or x.get('_buyer') or '').strip(),
        'win': (x.get('win') or '').strip(),
        'amt': parse_amt(x.get('amt')) if x.get('amt') not in ('—', '-', '') else None,
        'amtTxt': (x.get('amt') or '').strip() if x.get('amt') not in ('—',) else '',
        'd': (x.get('d') or '')[:10],
        'dl': '' if str(x.get('dl')) in ('—', 'None', 'null') else str(x.get('dl'))[:10],
        'p': (x.get('p') or '').strip(),
        'url': clean_url(x.get('url')),
        'snip': (x.get('snip') or '').strip()[:400],
        'mode': '',
        'srcType': (x.get('srcType') or '').strip(),
        'platLevel': (x.get('platLevel') or '').strip(),
        'files': x.get('files') if isinstance(x.get('files'), list) else [],
        'origin': x.get('origin') if isinstance(x.get('origin'), dict) else None,
        'shell': 1 if x.get('shell') else 0,
        '_new': False,
    }
    if not r['t']: continue
    old.append(r)

print(f'老版四地有效数据: {len(old)} 条（原1383条，剔除外省{len(old_raw)-len(old)}条）')

# ============ 4. 老数据补newhouse：标题含EPC/总承包/PC的推断承包模式 ============
for r in old:
    t = r['t'] + ' ' + r['snip']
    if 'EPC+O' in t.upper() or 'EPCO' in t.upper(): r['mode'] = 'EPC+O'
    elif 'EPC' in t.upper(): r['mode'] = 'EPC'
    elif 'EP' in t and '总承包' in t: r['mode'] = 'EP'
    elif '总承包' in t or '工程总承包' in t: r['mode'] = '工程总承包'
    elif '设备采购' in t or '采购' in t: r['mode'] = '采购'

# ============ 5. 融合去重（新数据优先，同键保留信息最全）============
merged = {}
dup_count = 0

FILL_FIELDS = ('win', 'amt', 'amtTxt', 'buyer', 'url', 'mode', 'dl', 'snip', 'city',
               'early', 'expect', 'srcType', 'platLevel', 'origin', 'shell')


def merge_into(keep, drop):
    """把 drop 的信息并入 keep：字段互补 + 阶段留痕"""
    for f in FILL_FIELDS:
        if not keep.get(f) and drop.get(f):
            keep[f] = drop[f]
    # 附件清单按 name+url 去重合并
    df = drop.get('files') or []
    if df:
        kf = keep.get('files') or []
        seenf = {(f.get('n'), f.get('u')) for f in kf}
        for f in df:
            if (f.get('n'), f.get('u')) not in seenf:
                kf.append(f); seenf.add((f.get('n'), f.get('u')))
        keep['files'] = kf
    keep.setdefault('hist', [])
    # ⚠ 2026-10-27 用户抓到「宁波钢铁 15MW」弹层里全过程 2 条一模一样：
    #   老代码追加 hist 之前不查重，同一阶段的记录来自两个来源（或子串合并触发两次）就翻倍。
    _hk = (drop['st'], drop['d'], drop['url'])
    if not any((h['st'], h['d'], h['url']) == _hk for h in keep['hist']):
        keep['hist'].append({'st': drop['st'], 'd': drop['d'], 'url': drop['url'],
                             'p': drop['p'], 'win': drop['win'], 'amt': drop['amt']})
    if drop.get('_new'):
        keep['_new'] = True
    return keep


def buyer_conflict(a, b):
    """两条业主都非空且明显不同 → 同名不同项目，不能合并"""
    ba = (a.get('buyer') or '').strip()
    bb = (b.get('buyer') or '').strip()
    if not ba or not bb:
        return False
    if ba[:6] == bb[:6] or ba[:6] in bb or bb[:6] in ba:
        return False
    return True


for r in old + new:
    k = key_of(r['t'], r['buyer'], r['d'])
    # 说明：早期版本曾用业主后缀拆键防误并，实测发现反而造成漏并——
    # 同一项目在不同来源里业主字段会填成不同角色（业主/投资方/采购人/项目管理公司），
    # 例如佛堂污水处理厂两条分别写成「义乌市水处理有限责任公司」和「佛堂污水处理厂」。
    # 标题里通常已含地名与项目名，同名不同项目的风险很低，故主键只按标题。
    if k in merged:
        dup_count += 1
        a, b = merged[k], r
        keep, drop = (a, b) if info_score(a) >= info_score(b) else (b, a)
        if info_score(b) > info_score(a) or b.get('_new'):
            keep['_new'] = True
        merge_into(keep, drop)
        merged[k] = keep
    else:
        r['hist'] = []
        merged[k] = dict(r)

# ---- 子串合并：标题是另一条的子串、只差业主前缀时，视为同一项目 ----
# 例：「安徽省宿松县经济开发区生物质热电联产项目环评」
#     是「宿松龙瑞热电有限公司安徽省宿松县经济开发区生物质热电联产项目环评」的子串，
#     差额只是业主名，应合并。中煤宝山两条（宝能变扩建 vs 锅炉除灰脱硝）不是子串关系，安全。
keys = sorted(merged.keys(), key=len)
sub_dup = 0
for i, k1 in enumerate(keys):
    if k1 not in merged or len(k1) < 10:
        continue
    for k2 in keys[i + 1:]:
        # 窗口 14：已按长度升序，后面只会更长，超过就停。
        # 为什么是 14 —— 试过 22，会把「上海石化热电机组清洁提效改造项目」和
        # 「…改造工程分系统、整套启动调试劳务协助用工」（差 16 字）误并成一条，
        # 那其实是两个不同的标（主体工程 vs 调试劳务）。14 字差≈一个业主名或
        # 「中标候选人公示」的长度，够覆盖「只差业主前缀」和「阶段演进」两种真重复。
        if len(k2) - len(k1) > 14:
            break
        if k2 not in merged or k1 not in merged:
            continue
        if k1 not in k2:
            continue
        a, b = merged[k1], merged[k2]
        if buyer_conflict(a, b):
            continue
        keep, drop = (a, b) if info_score(a) >= info_score(b) else (b, a)
        tgt = k1 if keep is a else k2
        merged[tgt] = merge_into(keep, drop)
        merged.pop(k2 if keep is a else k1, None)
        sub_dup += 1
        if k1 not in merged:
            break
print(f'去重合并: 剔除重复 {dup_count} 条 + 子串合并 {sub_dup} 条，最终 {len(merged)} 条')

# ============ 6. 统一重算：分类 / 等级 / 城市 / 规模 ============
STAGE_RANK = {'立项公示':1,'招标计划':2,'招标公告':3,'中标候选人公示':4,'中标结果公示':5,'变更公告':3,'其他':0}

out = []
for i, (k, r) in enumerate(merged.items()):
    text = r['t'] + ' ' + (r['snip'] or '')
    biz, sub = classify(text)
    if is_pure_pipe(r['t'], r.get('snip') or '') and biz == '能源清洁高效利用':
        sub = '供热管网施工'
    r['biz'], r['sub'] = biz, sub
    sc = parse_scale(text)
    r['mw'], r['tph'] = sc['mw'], sc['boiler_tph']
    g, sco = grade(biz, sub, r['st'], r['amt'], sc, text, r['t'], r.get('snip') or '')
    # 城市全生命周期（出口A 口径）：只留跟我们业务相关的（A/B/C 级）。
    # 用户明确要求：找商机库是"只做我们能做的"，无关的 D 级
    # （房建/装饰/货物）不能进来 —— 那些走出口B 进对手情报库。
    if r.get('p') in ('南通市公共资源交易平台', '安徽省公共资源交易监管平台',
                      '江苏省公共资源交易平台') and g == 'D':
        continue
    r['g'], r['score'] = g, sco
    if not r['city']: r['city'] = guess_city(r['rg'], text)
    # 阶段取链路中最进展的一环，并保留主要阶段列表
    chain = [h['st'] for h in (r.get('hist') or [])] + [r['st']]
    top = max(chain, key=lambda x: STAGE_RANK.get(x, 0))
    r['stages'] = sorted(set(chain), key=lambda x: STAGE_RANK.get(x, 0))
    r['st'] = top if top != '其他' or r['st'] == '其他' else r['st']
    r['id'] = 'P' + hashlib.md5((r['t'] + r['d']).encode()).hexdigest()[:8]
    r['amtY'] = round(r['amt'] / 1e8, 4) if r['amt'] else None
    out.append(r)

# ============ 6.5 本轮新增判定：与上一版线上库比对 id ============
# 之前 make_rec 无条件给采集数据打 _new=True，导致同一批历史数据每轮都被算成「新增」
# （曾出现 303 条，含 2025 年的旧项目）。改为用持久化基线判定，只认真正新入库的项目。
SEEN_FILE = os.path.join(RAW, 'seen_ids.json')
seen_prev = set()
if os.path.exists(SEEN_FILE):
    try:
        seen_prev = set(json.load(open(SEEN_FILE, encoding='utf-8')))
    except Exception:
        seen_prev = set()
for r in out:
    r['_new'] = r['id'] not in seen_prev
# 回写基线：本次全量 id 即下一版的对照表
json.dump(sorted({r['id'] for r in out}),
          open(SEEN_FILE, 'w', encoding='utf-8'), ensure_ascii=False)
_nnew = sum(1 for r in out if r['_new'])
print('\n新增判定：上一版基线 %d 条 → 本轮真新增 %d 条' % (len(seen_prev), _nnew))

out.sort(key=lambda x: (-x['score'], x['d']), reverse=False)
out.sort(key=lambda x: x['score'], reverse=True)

# ============ 7. 统计 ============
print('\n=== 分类结果 ===')
print('一级业务:', dict(Counter(x['biz'] for x in out).most_common()))
print('等级:', dict(Counter(x['g'] for x in out).most_common()))
print('地区:', dict(Counter(x['rg'] for x in out).most_common()))
print('阶段:', dict(Counter(x['st'] for x in out).most_common()))
print('有金额:', sum(1 for x in out if x['amt']), '有中标单位:', sum(1 for x in out if x['win']))
print('\n二级子类 TOP:')
for k, v in Counter(x['sub'] for x in out).most_common(30):
    print(f'  {k}: {v}')

json.dump(out, open(os.path.join(ROOT, 'merged.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print(f'\n已写出 merged.json 共 {len(out)} 条')
