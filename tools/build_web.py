# -*- coding: utf-8 -*-
"""生成前端数据包 data.js"""
import json, os, re, random, datetime
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
# 2026-10-22：输出目录改成可配置。
#   原来硬编码 '/workspace/biz-radar'，那是沙盒里的路径；搬到 GitHub Actions 后
#   目录结构是 repo/tools/ 和 repo/ 的关系，写死了就往不存在的地方写。
#   现在默认仍是沙盒路径（本地跑不受影响），Actions 里用 BIZ_OUT 覆盖。
OUT = os.environ.get('BIZ_OUT') or '/workspace/biz-radar'
os.makedirs(OUT, exist_ok=True)

D = json.load(open(os.path.join(ROOT, 'merged.json'), encoding='utf-8'))

# ── 业务分层与门槛（2026-10-21 用户逐条确认版）────────────────────────────
# 用户原话：「正常情况我们是跟踪1亿以上，但是你要是觉得关联性特别大也算上」
#          「有色冶炼供能一级大半合同额来自于此」
# 定义全在 seg_biz.py，判定全在 seg_match.py，这里只调用。
# 关键变化：不再用 is_watch 的「A/B 级兜底」，改成三段式
#   ≥1亿 → 进；0.3~1亿 必须「核心工艺词+总承包」双命中；<0.3亿 → 不进。
import seg_biz as SB
import seg_match as SM

# ---- 死链标记（2026-10-21） ----
# 用户反馈「宝山那个项目还是跳转不了」。根因不是链接写错，是采集源本身是空壳站：
# 知了标讯 / 谛听招标网 / 千里马 / 必联网 详情页返回 200 + 13 字节空白，或要登录。
# probe_deadlinks.py 探出来的结果在这里挂到记录上，前端据此把「原文」降级成
# 「原文可能打不开 + 用标题搜」，不再让人点进白屏。
_LH_PATH = os.path.join(ROOT, 'raw', 'link_health.json')
LINKBAD = {}
if os.path.exists(_LH_PATH):
    _lh = json.load(open(_LH_PATH, encoding='utf-8')).get('items', {})
    LINKBAD = {u: v for u, v in _lh.items() if not v.get('ok')}
    print('[死链] %d 条链接不可直达，前端会降级展示' % len(LINKBAD))
else:
    print('[死链] 未找到 link_health.json，跳过（先跑 probe_deadlinks.py）')

# ---- 中标单位回填（2026-10-21） ----
# mine_notice.py 把公告正文里的「中标人：XXX」抠出来落到 raw/notice_extra.json，
# 但一直没人并回主数据。结果：648 条中标类记录里 394 条 win 字段是空的，
# 「已出结果」档点开一片「中标情况：未公示」——等于白给。
# 这里按 url 对齐，只填空值，不动已有内容。
_NE_PATH = os.path.join(ROOT, 'raw', 'notice_extra.json')
if os.path.exists(_NE_PATH):
    _ne = json.load(open(_NE_PATH, encoding='utf-8')).get('items', {})
    _filled = 0
    for _r in D:
        if (_r.get('win') or '').strip():
            continue
        _e = _ne.get(_r.get('url') or '')
        if not _e:
            continue
        _w = (_e.get('win') or '').strip()
        if len(_w) >= 4:
            _r['win'] = _w
            _filled += 1
        # 联系人/电话也是公告里最有用的两栏，顺手挂上（前端没展示就不占体积）
        if _e.get('contact') and not _r.get('contact'):
            _r['contact'] = _e['contact']
        if _e.get('phone') and not _r.get('phone'):
            _r['phone'] = _e['phone']
    print('[中标回填] notice_extra 补上 %d 条中标单位' % _filled)

IND = json.load(open(os.path.join(ROOT, 'raw', 'industry.json'), encoding='utf-8'))
AB = json.load(open(os.path.join(ROOT, 'raw', 'clients_abroad.json'), encoding='utf-8'))
AB2_PATH = os.path.join(ROOT, 'raw', 'clients_abroad2.json')
AB2 = json.load(open(AB2_PATH, encoding='utf-8')) if os.path.exists(AB2_PATH) else {'clients': []}
PT_PATH = os.path.join(ROOT, 'raw', 'partners.json')
PARTNERS = json.load(open(PT_PATH, encoding='utf-8')) if os.path.exists(PT_PATH) else []

# 行业分组：钢铁 / 有色 / 化工化纤 / 水泥建材 / 其他制造
# ── 海外机会客户名单（2026-10-21 用户确认口径）─────────────────────────
# 用户原话：「我们的海外是，中国企业（江浙沪皖）去海外建造电厂，所以叫海外」
#          「海外板块的地域范围江浙沪皖优先，外地大厂也算」
#          「海外的数据中心、水泥这类也是能源大户也可以算在里面」
#
# 名单维护在 oversea_clients.py（70 家 / 7 个行业 / pri=1 江浙沪皖 48 家、pri=2 外地 22 家）。
# 这里不再硬编码，避免两处名单打架。
import oversea_clients as OC

GROUP = {}
for _c in OC.ALL:
    GROUP[_c['kw']] = _c['grp']

CLIENTS = [c['name'] for c in OC.ALL]
_CMAP = {c['name']: c for c in OC.ALL}

# 精简明细记录
def infer_ind(r):
    t = r['t'] + ' ' + (r['buyer'] or '') + ' ' + (r['snip'] or '')
    if re.search(r'钢|铁矿|焦化|烧结|高炉|转炉|炼钢|轧|不锈钢|带钢|冶金', t): return '钢铁'
    if re.search(r'铝|铜|镍|钴|锌|铅|硅|氧化铝|电解|有色|冶炼|金属|锂', t): return '有色'
    if re.search(r'水泥|玻璃|陶瓷|建材|混凝土|耐材', t): return '水泥建材'
    if re.search(r'化工|化学|石化|炼化|树脂|橡胶|聚酯|化纤|甲醇|乙烯|烃|苯|酯|胺|酸|碱|油气|石油', t): return '化工'
    if re.search(r'电厂|发电|电力|电网|储能电站|供电|电源|核电|风电', t): return '电力'
    if re.search(r'市政|污水|供水|环境|园林|环卫|河道|管廊|城投|城建|建设中心|小镇|乡村', t): return '市政'
    return '其他'

# ---- 有色金属期货价格（每次构建时抓取实时价；失败则回退上次成功快照）----
import urllib.request, time
RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
METALS_CACHE = os.path.join(RAW, 'metals_cache.json')
def fetch_metals():
    cfg = [('CU','沪铜','元/吨','电缆/电机/变压器成本直接项，是项目造价与报价的风向标'),
           ('AL','沪铝','元/吨','电解铝新扩建（几内亚-印尼-新疆线）是自备电厂+余热利用大单来源'),
           ('ZN','沪锌','元/吨','镀锌与压铸需求指标，锌价走强反映有色冶炼扩产意愿'),
           ('PB','沪铅','元/吨','铅酸储能与冶炼景气参考，关注再生铅配套环保需求'),
           ('NI','沪镍','元/吨','镍价走强 → 印尼/非洲镍冶炼扩产，海外用能需求 ↑；下跌则关注客户资本开支收缩'),
           ('SN','沪锡','元/吨','焊料与高端制造用锡，价高代表电子/半导体链景气'),
           ('AO','氧化铝','元/吨','电解铝核心原料，氧化铝新扩建项目是余热发电+废水零排放的大单来源'),
           ('SS','不锈钢','元/吨','不锈钢利润=镍铁成本传导，钢厂技改/脱硝意愿先行指标'),
           ('LC','碳酸锂','元/吨','锂价决定盐湖/锂云母项目景气度，直接影响储能配套投资意愿'),
           ('RB','螺纹钢','元/吨','钢厂利润风向标：螺价走高 → 钢厂技改、环保与煤气发电投入意愿强'),
           ('HC','热轧卷板','元/吨','制造业用钢景气度，板材厂资本开支与涂镀环保需求的先行指标'),
           ('I','铁矿石','元/吨','钢厂成本大头，矿价坚挺说明钢厂生产积极，配套供电供汽需求稳定'),
           ('JM','焦煤','元/吨','钢铁成本端+焦化配套：焦煤利润好 → 焦化废水/脱硫提标需求释放')]
    UAS = ['Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
           'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
           'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0']
    REFS = ['https://finance.sina.com.cn/futuremarket/', 'https://finance.sina.com.cn/futures/', 'https://finance.sina.com.cn/']
    def try_once():
        codes = ','.join('nf_' + c + '0' for c, *_ in cfg)
        req = urllib.request.Request('https://hq.sinajs.cn/list=' + codes, headers={
            'Referer': REFS[random.randrange(len(REFS))],
            'User-Agent': UAS[random.randrange(len(UAS))],
            'Accept': '*/*', 'Accept-Language': 'zh-CN,zh;q=0.9'})
        raw = urllib.request.urlopen(req, timeout=12).read().decode('gbk', 'ignore')
        rows = {}
        for line in raw.split(';'):
            m = re.search(r'hq_str_nf_(\w+)="([^"]*)"', line)
            if m and m.group(2):
                rows[m.group(1)] = m.group(2).split(',')
        out = []
        for code, name, unit, hint in cfg:
            f = rows.get(code + '0')
            if not f or len(f) < 12: continue
            try:
                price = float(f[8]); prev = float(f[10])
                if price <= 0 or prev <= 0: continue
                out.append({'code': code, 'name': name, 'unit': unit,
                            'price': price, 'chg': round((price / prev - 1) * 100, 2),
                            'date': f[17][:10] if len(f) > 17 else '', 'hint': hint})
            except (ValueError, IndexError): continue
        return out
    for attempt in range(6):
        try:
            out = try_once()
            if out:
                try: json.dump(out, open(METALS_CACHE, 'w', encoding='utf-8'), ensure_ascii=False)
                except Exception: pass
                return out
        except Exception as e:
            print('[WARN] 金属行情第 %d 次抓取失败: %r' % (attempt + 1, e))
        time.sleep(1.2 * (attempt + 1))
    if os.path.exists(METALS_CACHE):
        print('[WARN] 实时行情不可用，回退上次成功快照')
        return json.load(open(METALS_CACHE, encoding='utf-8'))
    print('[WARN] 金属行情为空，页面将不展示该模块')
    return []

METALS = fetch_metals()

# ══════════════════════════════════════════════════════════════════════
# 关注门槛（2026-10-21 用户明确要求）
# 「这种几百万的项目放上去有什么用只会污染数据库」
# 投标是要花设计院人力的：一个 300 万的标，光投标成本就吃掉大半利润，
# 何况还有资质、业绩门槛。所以库里的项目分两类：
#   关注档  —— 金额 ≥ 3000 万  或  综合分为 A/B（能源主业中大型 / 有明确规模证据）
#   其余    —— 只做背景，不进主列表、不计入对手战绩、不计入客户金额
# ══════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════
# 2026-10-21 用户第三次强调「几百万的没价值还会污染库」。
# 上一版留了个后门：A/B 级就算几百万也放进来（理由是「主业中大型」），
# 结果「能投的标」里混进 28 条 200 万-3000 万的：屋顶光伏 EPC、单一锅炉改造、
# 设计服务、EMC 合同能源管理…… 这些放主列表里，真正值得投的 3 亿储能站就被挤到第 2 页。
#
# 现在一刀切：**招标类必须金额 ≥ 3000 万**，金额扒不出来的一律不进主列表。
# A/B 级只在「金额未知」这一种情况下作为兜底（有规模证据但数字没写在标题里）。
# 立项线索（还没招标的）不卡金额——那是「我们可以去谈的」，几百万的聊一聊也可能
# 养成大单，塞进线索池不碍事，反正不在主列表。
# ══════════════════════════════════════════════════════════════════════
WATCH_AMT = 0.3          # 亿元，即 3000 万


def _seg_text(r):
    """判业务用的文本：标题 + 摘要 + 业主。标题权重最高，摘要补细节。"""
    return ' '.join(str(r.get(k) or '') for k in ('t', 'snip', 'buyer'))


def seg_of(r):
    """这条记录属于哪个业务层级"""
    return SM.classify(_seg_text(r))


def is_watch(r):
    """这条项目值不值得派人跟。

    2026-10-21 用户第四次定门槛，改成三段式（详见 seg_match.judge）：
      ≥1 亿 → 进
      0.3~1 亿 → 必须「核心工艺词 + 总承包标的」双命中，否则不进
      <0.3 亿 → 不进
      金额未知 → 一级业务 + 核心工艺词 才进
    旧的「A/B 级兜底」已废弃：它把大量几百万的屋顶光伏、单一锅炉改造放进来了。
    """
    ok, _why, _note = SM.judge(r, _seg_text(r))
    return ok


# 立项/审批/重点项目名单：潜在机会，不是招标公告。
# 这类记录（浙江投资在线审批、江苏投资在线审批、各省重点项目清单）共 637 条，
# 用来看「哪些业主今年要动」很有用，但会挤占「能投的标」的位置，所以单独成区。
# 链接前缀压缩表：省市级站的 url 前缀高度重复，换成 #代码 存，
# 前端 href=U(u) 再拼回来。顺序敏感——长前缀必须排在短前缀前面，
# 否则 'http://jsggzy.jszwfw.gov.cn' 会先被 'http://' 之类的短前缀吃掉。
SITE_PREFIX = [
    ('http://jsggzy.jszwfw.gov.cn', 'js'),
    ('https://ggzy.zj.gov.cn', 'zj'),
    ('https://ggzy.hefei.gov.cn', 'hf'),
    ('https://ggzy.suzhou.gov.cn', 'sz'),
    ('https://ggzy.changzhou.gov.cn', 'cz'),
    ('https://www.shggzy.com', 'sh'),
    ('https://www.zbytb.com', 'zb'),
    ('https://www.gxxszb.com', 'gx'),
]

ST_LEAD = ('立项公示',)# 能投的标（有招标文件、有截止时间、能报名）
ST_TENDER = ('招标公告', '招标计划', '变更公告')
# 已结束（看结果、看对手）
ST_WIN = ('中标结果公示', '中标候选人公示')


def bucket(st):
    if st in ST_LEAD:
        return 'lead'
    if st in ST_WIN:
        return 'win'
    return 'tender'


brief = []
for r in D:
    # ── items 瘦身（2026-10-21 用户反馈「加载时间太长」）────────────────
    # items 原来 1.17MB，逐字段量过后发现三处纯浪费：
    #   url    220KB（18.8%）—— 省市级站的链接前半段完全一样，只存路径 + 一个域代码
    #   stages  19KB（ 1.6%）—— 前端根本没用到，纯占位
    #   hist   102KB（ 8.8%）—— 只有 438 条有，且只在卡片底部画「阶段链」，留 2 条够了
    # 省下来的空间让首屏渲染明显变快，信息一点没少。
    _u = r['url'] or ''
    for _pre, _code in SITE_PREFIX:
        if _u.startswith(_pre):
            _u = '#' + _code + _u[len(_pre):]
            break
    # 业务分层：sg=层级短码（省体积），sG=命中词，sR=层级序号，hm=是否主场
    _si = seg_of(r)
    b = {
        'id': r['id'], 't': r['t'], 'rg': r['rg'], 'city': r['city'], 'st': r['st'],
        'g': r['g'], 'sg': _si['seg'], 'sG': _si['kw'], 'sR': _si['rank'],
        'hm': 1 if SM.is_home(_si['seg']) else 0,
        # biz/sub 保留：前端 CSV、旧筛选还有零散引用，且和上游数据对得上时便于回溯
        'biz': r.get('biz') or '', 'sub': r.get('sub') or '',
        'buyer': r['buyer'], 'win': r['win'],
        'amt': r['amtY'], 'amtTxt': r['amtTxt'][:40], 'd': r['d'], 'dl': r['dl'], 'p': r['p'],
        'url': _u, 'mode': r['mode'], 'snip': (r['snip'] or '')[:180],
        'sc': round(r['score']), 'nw': 1 if r.get('_new') else 0,
        'ind': infer_ind(r),
        'early': r.get('early') or '',
        'expect': r.get('expect') or '',
        'hist': [{'st': h['st'], 'd': h['d'], 'url': h['url']} for h in (r.get('hist') or [])][:2],
        # 分区 + 关注标记：前端据此分成「能投的标 / 已出的结果 / 立项线索」三栏，
        # 小项目收进「不关注」统计，不占主列表位置。
        'bk': bucket(r['st']),
        'w': 1 if is_watch(r) else 0,
        # linkbad=1 表示原文链接打不开（空壳站/登录墙），前端不给主按钮，改给搜索入口
        # 注意别用 dl：那个字段已经是「投标截止日」了
        'linkbad': 1 if (r.get('url') in LINKBAD) else 0,
    }
    # 附件清单 + 原始发布平台 + 信源分级
    _f = r.get('files') or []
    if _f:
        b['files'] = [{'n': x.get('n', ''), 'u': x.get('u', ''),
                       'ok': x.get('ok'), 'sz': x.get('sz')} for x in _f[:10]]
    _o = r.get('origin') or {}
    if _o.get('n') or _o.get('u'):
        b['org'] = {'n': _o.get('n', ''), 'u': _o.get('u', '')}
    if r.get('srcType') == 'reprint':
        b['rp'] = 1          # 转载站：链接不稳，前端提示
    if r.get('shell'):
        b['sh'] = 1          # 空壳页：原文抓不到，前端给搜索兜底
    brief.append(b)

# ---- 聚合：竞争对手（中标单位）----
def pure_pipe(r):
    t = r['t'] + ' ' + (r['snip'] or '')
    return bool(re.search(r'管网|管道|管廊|厂外管道|供热线路', t)) and not re.search(r'热电|发电|余热|锅炉|机组|电厂|储能|光伏|汽轮|煤气', t)

# 2026-10-21 改：战绩按「业务层级」统计，不再按老的 biz 五大类。
# 老口径下「废水处理」和「能源清洁高效利用」并列，结果对手榜 TOP12 里
# 一半是污水处理公司——这些人根本不是我们的对手，是同行的分公司业务对手。
win_rank = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'seg': Counter(), 'rg': Counter(),
                                'items': [], 'home': 0, 'side': 0,
                                # name 存**首次见到的原写法**；键是规范化后的，
                                # 所以显示名要单独留一份，不能拿键当名字。
                                'name': ''})


def split_lead(w):
    """从「中标单位」字段里取出牵头单位。
    原始公告写法极其混乱，实测到的分隔符就有：、 , ， / ； ; + ＋ 以及「联合体：」
    例：
      「郑州康宁特环境工程科技有限公司+上海四方无锡锅炉工程有限公司联合体」
      「安徽省城建设计研究总院股份有限公司;中交上海航道局有限公司」
      「安徽君澜建工集团有限公司（联合体：安徽开源路桥第二工程有限责任公司」
    以前只切了 、 , ， / 四种，结果上面这些整串被当成一家公司，
    导致同一个对手在榜上分散成好几个名字、战绩算不准。

    ⚠⚠ 2026-10-22 修了一个**把公司名腰斩**的 bug：
       老代码把**所有**括号都换成 '|' 当分隔符：
           s = re.sub(r'[）)]', '|', s)
       于是「华光环保能源（西安）设计研究院有限公司」被切成
           ['华光环保能源', '西安', '设计研究院有限公司']
       取第一个 → 「华光环保能源」，后半截「（西安）设计研究院有限公司」直接没了。
       在页面上表现为集团汇总行里出现一个残缺的名字「华光环保能源（西安」，
       四库一平台也因此匹配不到（名字都不对，当然查不到）。
       正确做法：只有**「（联合体：…）」这类附注**才当分隔符，
       名称自带的括号（地区/专业/曾用名）必须原样保留。
    """
    s = (w or '').strip()
    s = re.sub(r'\s*联合体\s*$', '', s)
    # 全角/半角括号统一：同一家单位在公告里常一半写「（西安）」一半写「(西安)」，
    # 不统一就会被当成两家，战绩各算一半（实测华光环保能源就撞上了）。
    s = s.replace('（', '(').replace('）', ')')
    # 只把「(联合体: xxx」这种附注摊平，其余括号原地保留
    s = re.sub(r'\(\s*联合体\s*[:：]?\s*', '\x00|', s)
    if '\x00' in s:
        # 有联合体附注时，它的右括号才需要变成分隔符
        head, _, tail = s.partition('\x00')
        tail = re.sub(r'[）)]', '|', tail)
        s = head + '|' + tail.replace('\x00', '')
    parts = [p for p in re.split(r'[、,，/;；+＋|]', s) if p.strip()]
    for p in parts:
        # 去掉「（第一中标候选人）」这类**尾部**注释；
        # 注意只剥位于末尾的括号，不要剥名称中间的（西安）（华东）这种
        p = re.sub(r'[（(](?:第[一二三]中标候选人|中标候选人|中标人|成交供应商|联合体|投标报价[^）)]*)[）)]\s*$', '', p)
        p = re.sub(r'^(第[一二三]中标候选人|中标人|成交供应商)\s*[:：]?\s*', '', p)
        p = p.strip()
        if len(p) >= 4:
            return p
    return ''


for r in D:
    w = (r['win'] or '').strip()
    if not w or len(w) < 4: continue
    if pure_pipe(r): continue        # 纯管网/管道施工不计入对手战绩
    if not is_watch(r): continue     # 几百万的小标不计入战绩，否则对手榜全是噪音
    lead = split_lead(w)
    if len(lead) < 4: continue
    # 聚合键：全角括号统一成半角、去掉多余空格。
    # 同一家单位在公告里常一半写「（西安）」一半写「(西安)」，
    # 不归一会当成两家、战绩各算一半（实测华光环保能源就撞上了）。
    # 但**显示仍用原写法**——不能为了算账把人家名字改了。
    nkey = lead.replace('（', '(').replace('）', ')').replace(' ', '')
    _si2 = seg_of(r)
    v = win_rank[nkey]
    v['name'] = v.get('name') or lead
    v['n'] += 1
    if r['amt']: v['amt'] += r['amt']
    v['seg'][_si2['segname']] += 1
    v['rg'][r['rg']] += 1
    if SM.is_home(_si2['seg']): v['home'] += 1
    else: v['side'] += 1
    if len(v['items']) < 6:
        v['items'].append({'t': r['t'][:60], 'amt': r['amtY'], 'd': r['d'], 'rg': r['rg'], 'url': r['url']})

rivals = []
for nkey, v in win_rank.items():
    name = v.get('name') or nkey
    rivals.append({
        'name': name, 'kw': name[:6], 'n': v['n'], 'amt': round(v['amt'] / 1e8, 3),
        'main': v['seg'].most_common(1)[0][0] if v['seg'] else '',
        'segs': dict(v['seg']),
        # hm=主场(一级/二级)中标次数，sd=兼营(三级分公司业务)次数。
        # 前端靠这两个数把「真对手」和「污水口的人」分开排。
        'hm': v['home'], 'sd': v['side'],
        'rg': ','.join([k for k, _ in v['rg'].most_common(3)]),
        'items': v['items'],
    })

# ---- 集团归并：把同一集团内不同投标主体的战绩按集团口径聚合 ----
# 目的：华光环能这类「母体 + 设计院 + 子公司」分散投标的对手，按名称分行会让其
# 真实体量从榜单里隐身（单看母体仅 596 万，集团口径实为 6 亿+）。
_ALIAS_PATH = os.path.join(ROOT, 'raw', 'alias_groups.json')
GROUPS = []
if os.path.exists(_ALIAS_PATH):
    try:
        GROUPS = json.load(open(_ALIAS_PATH, encoding='utf-8')).get('groups', [])
    except Exception as e:
        print('[WARN] alias_groups.json 解析失败，跳过集团归并：%s' % e)


def match_group(name):
    for g in GROUPS:
        for kw in g.get('match', []):
            if kw in name:
                return g
    return None


grp_map = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'biz': Counter(), 'rg': Counter(),
                               'subs': [], 'hm': 0, 'sd': 0, 'segs': Counter()})
ungrouped = []
for r in rivals:
    g = match_group(r['name'])
    if not g:
        r['group'] = ''
        r['subs'] = []
        ungrouped.append(r)
        continue
    r['group'] = g['name']
    r['subs'] = []
    if not g.get('merge', True):
        # 各局/各院独立投标，只打标签不合并
        ungrouped.append(r)
        continue
    v = grp_map[g['name']]
    v['n'] += r['n']
    v['amt'] += r['amt']
    v['biz'][r['main']] += r['n']
    # 集团口径也要累计主场/兼营次数，否则合并后的行会缺字段
    v['hm'] += r.get('hm', 0)
    v['sd'] += r.get('sd', 0)
    for _k, _c in (r.get('segs') or {}).items():
        v['segs'][_k] += _c
    for rg in r['rg'].split(','):
        if rg:
            v['rg'][rg] += 1
    v['subs'].append(r)

merged = []
for gname, v in grp_map.items():
    subs = sorted(v['subs'], key=lambda x: -x['amt'])
    if len(subs) < 2:
        # 只有一个主体命中，没必要聚合成「系」
        for s in subs:
            s['group'] = gname
            s['subs'] = []
            ungrouped.append(s)
        continue
    merged.append({
        'name': gname, 'kw': subs[0]['kw'], 'n': v['n'], 'amt': round(v['amt'], 3),
        'main': v['biz'].most_common(1)[0][0] if v['biz'] else '',
        'segs': dict(v['segs']), 'hm': v['hm'], 'sd': v['sd'],
        'rg': ','.join([k for k, _ in v['rg'].most_common(3)]),
        'items': [it for s in subs for it in s['items']][:6],
        'group': gname, 'subs': [{'name': s['name'], 'n': s['n'], 'amt': s['amt'],
                                 'rg': s['rg'], 'items': s['items']} for s in subs],
    })

rivals = merged + ungrouped
# 排序：主场中标次数优先。理由——一家只在污水口中标的公司，对我们没有任何威胁，
# 不该排在拿了 3 个煤气发电标的设计院前面。
rivals.sort(key=lambda x: (-x['hm'], -x['n'], -x['amt']))
print('[集团归并] 合并出 %d 个集团行（另有 %d 家打标签未合并）'
      % (len(merged), sum(1 for r in rivals if r.get('group') and not r.get('subs'))))

# ---- 聚合：业主 ----
# 业主榜只统计关注档项目：一个业主一年买 20 个几十万的零活，
# 不该把它顶到「战略客户」的位置上。
# 2026-10-21 用户口径：「业主我只有兴趣那些在（7个细分）招标较多的」
#          「有些业主画像都是看个名字差不多，可是他历史上都没有招过我们这些标的」
#
# 所以业主拆两块：
#   有效业主 (valid)  = 库内确实发过一级/二级业务的标 → 排前面，给完整档案卡
#   潜在业主 (latent) = 只在三级业务（污水/土壤）发过标，或者压根没发过
#                       → 二级位置简单展示，不放项目列表、不参与排序
# 判断依据用「主场标数 hm」，不用总条数。一个业主发了 20 个污水标，
# 对我们毫无意义，不能因此被当成大客户。
buyer_rank = defaultdict(lambda: {'n': 0, 'amt': 0.0, 'items': [], 'rg': '',
                                  'hm': 0, 'sd': 0, 'segs': Counter(),
                                  # 2026-10-22 新增：联系人 / 代理机构。
                                  # 前端 index.html 早就写好了展示代码（可点击拨号），
                                  # 但后端从来没产出过这两个字段 —— 那一块永远是空的。
                                  # 现在从公告详情里抽到的 contact/phone/agc 聚到这里。
                                  'contacts': [], 'agent': []})
_ckey = defaultdict(set)      # 去重：同一个业主，同一个人/电话只留一次
_akey = defaultdict(set)
for r in D:
    b = (r['buyer'] or '').strip()
    if not b or len(b) < 4: continue
    if not is_watch(r): continue
    _si3 = seg_of(r)
    _home3 = SM.is_home(_si3['seg'])
    v = buyer_rank[b]
    v['n'] += 1
    v['rg'] = r['rg']
    v['segs'][_si3['segname']] += 1
    if _home3: v['hm'] += 1
    else: v['sd'] += 1
    if r['amt']: v['amt'] += r['amt']
    # 联系人：只收真名的，同一个人只记一次，计数=它出现在几个公告里
    _cn = (r.get('contact') or '').strip()
    _ph = (r.get('phone') or '').strip()
    if _cn or _ph:
        _k = _cn + '|' + _ph
        if _k not in _ckey[b] and len(v['contacts']) < 8:
            _ckey[b].add(_k)
            v['contacts'].append({'name': _cn, 'phone': _ph, 'n': 1,
                                  't': r['t'][:40], 'url': r.get('url') or ''})
    # 代理机构：同一家代理多次出现就累加次数，多的排前面
    _ag = (r.get('agc') or '').strip()
    if _ag:
        for a in v['agent']:
            if a['name'] == _ag:
                a['n'] += 1
                if not a.get('phone') and _ph:
                    a['phone'] = _ph
                break
        else:
            if len(v['agent']) < 5:
                v['agent'].append({'name': _ag, 'phone': _ph, 'n': 1})
    # 潜在业主只需要 1 条样例说明「它发过什么」，不需要 6 条列表
    _cap = 6 if _home3 else 1
    if len(v['items']) < _cap:
        v['items'].append({'t': r['t'][:60], 'amt': r['amtY'], 'd': r['d'], 'st': r['st'],
                           'win': r['win'], 'url': r['url'], 'sg': _si3['segname']})

_all_buyers = [{'name': k, 'n': v['n'], 'amt': round(v['amt'] / 1e8, 3), 'rg': v['rg'],
                'hm': v['hm'], 'sd': v['sd'], 'segs': dict(v['segs']),
                'contacts': sorted(v['contacts'], key=lambda x: -x['n'])[:5],
                'agent': sorted(v['agent'], key=lambda x: -x['n'])[:3],
                'items': v['items']}
               for k, v in buyer_rank.items()]
# 有效业主：主场标数 ≥ VALID_OWNER_MIN_ITEMS
buyers = [x for x in _all_buyers if x['hm'] >= SB.VALID_OWNER_MIN_ITEMS]
buyers.sort(key=lambda x: (-x['hm'], -x['n'], -x['amt']))
latent = [x for x in _all_buyers if x['hm'] < SB.VALID_OWNER_MIN_ITEMS]
latent.sort(key=lambda x: (-x['n'], -x['amt']))
print('[业主拆分] 有效业主 %d 家（发过一级/二级业务的标）· 潜在业主 %d 家（只发过三级/未发过）'
      % (len(buyers), len(latent)))

# ---- 重点客户：拆「国内」与「海外」两块（2026-10-21 用户要求） ----
# 旧版只有海外中资出海，国内是用一份人工写的 44 家名单去撞库，撞中率极低（多数 0 条）。
# 现在国内改成【从业主库里自动筛】：凡是采购过我们能干的活（热电/供热/环保/新能源）
# 且项目数或金额够看的业主，就是值得维护的国内重点客户，按赛道分类。
ABMAP = {}
for c in AB.get('clients', []):
    key = c['name'].replace('（', '(').split('(')[0][:4]
    if key: ABMAP[key] = c

# ① 国内重点客户：从 buyers（业主聚合）反推
_D90 = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()   # 近 90 天活跃度基线
CLIENT_MIN_N = 2          # 至少 2 个项目才进重点客户（1 条的多是偶发）
CLIENT_MIN_AMT = 0.5      # 或金额 ≥ 0.5 亿
domestic = []
for b in buyers:
    nm = b['name']
    if len(nm) < 4:
        continue
    subs = Counter()
    # 用业主名下记录反查赛道（buyers 里没带 biz，回 D 里找）
    rel = [r for r in D if r['buyer'] == nm]
    for r in rel:
        subs[r['biz']] += 1
    main_biz = subs.most_common(1)[0][0] if subs else ''
    n = b['n']
    # 2026-10-21 关键修正：分档必须看「主场标数 hm」，不能看总条数 n。
    # 一个业主发了 6 个农村污水标（三级分公司业务），按老规则会被判成 S 战略客户，
    # 但它从来没买过我们主场的活——这种业主对我们毫无意义。
    hm = b.get('hm') or 0
    amt = b.get('amt') or 0
    if hm < 1 and amt < CLIENT_MIN_AMT:
        continue
    # 分档：战略（主场≥2 或金额≥3亿）/ 重点（主场≥1 且金额≥1亿）/ 观察
    tier = 'S' if (hm >= 2 or amt >= 3) else ('A' if (hm >= 1 and amt >= 1) else 'B')
    # 赛道标签
    tags = [k for k, _ in subs.most_common(3)]
    # ── 业主画像（2026-10-21 补）：用户要的「业主画像 / 竞争对手画像」不是两张皮，
    #    核心就是回答三件事：这家业主爱买什么、给谁做、什么价位。
    #    ① buyN/buyAmt 采购频率与体量；② winList 主要供应商（谁在这家业主手里拿单最多）；
    #    ③ modeMix 承包模式偏好（EPC/F+EPC/EPC+O）；④ amtRange 单项目金额区间。
    win_cnt = Counter()
    mode_cnt = Counter()
    amts = []
    for r in rel:
        w = (r.get('win') or '').strip()
        if w and len(w) >= 3:
            win_cnt[w] += 1
        if r.get('mode'):
            mode_cnt[r['mode']] += 1
        # 注意：merged.json 里 amt 的单位是「元」，算区间要用 amtY（亿元），
        # 否则 3.2e9 这种原始值会直接显示成「3203779500.00 亿」。
        if r.get('amtY') and 0 < r['amtY'] < 100:
            amts.append(r['amtY'])
    win_top = [{'n': k, 'c': v} for k, v in win_cnt.most_common(4)]
    mode_top = [k for k, _ in mode_cnt.most_common(2)]
    rng = ''
    if amts:
        lo, hi = min(amts), max(amts)
        rng = ('%.2f–%.2f 亿' % (lo, hi)) if hi - lo > 0.01 else ('%.2f 亿' % lo)
    domestic.append({
        'name': nm, 'n': n, 'amt': round(amt, 3), 'rg': b.get('rg', ''),
        'latest': max([it['d'] for it in (b.get('items') or []) if it.get('d')], default=''),
        'main': main_biz, 'tags': tags, 'tier': tier,
        # hm=主场标数（一级/二级业务），sd=兼营标数（三级分公司业务）
        'hm': hm, 'sd': b.get('sd') or 0,
        'segs': b.get('segs') or {},
        'items': (b.get('items') or [])[:8],
        'wins': win_top, 'modes': mode_top, 'rng': rng,
        'recent': sum(1 for r in rel if (r.get('d') or '') >= _D90),
    })
# 排序必须按档位权重，不能按字符串——'S' > 'B' 但字典序里 'S' 排最后，
# 会导致 S 档全部被截断丢掉（曾踩过这个坑）
TIER_RANK = {'S': 0, 'A': 1, 'B': 2}
domestic.sort(key=lambda x: (TIER_RANK.get(x['tier'], 9), -x['amt'], -x['n']))
DOM_TOP = domestic[:120]      # 页面只展示前 120 家，避免过长
# ② 海外重点客户：人工维护的中资出海名单 + 关联本库记录
overseas = []
_seen_clear = set()
for c in CLIENTS:
    _ci = _CMAP.get(c) or {}
    kw = _ci.get('kw') or c
    kw = re.sub(r'(集团有限公司|股份有限公司|控股集团|集团|公司|股份|（[^）]*）|\([^)]*\)|（\d+）|\d{6})', '', kw)
    kw = kw.strip()
    if not kw or len(kw) < 2: kw = c[:4]
    hits = [r for r in D if kw and kw in (r['buyer'] + r['win'] + r['t'] + r['snip'])]
    hits.sort(key=lambda x: (x['amt'] or 0), reverse=True)
    grp = _ci.get('grp') or '其他制造'
    ab = ABMAP.get(kw[:4]) or ABMAP.get(c[:4]) or {}
    for c2 in AB2.get('clients', []):
        k2 = c2.get('name', '').replace('（', '(').split('(')[0][:4]
        if (k2 and k2 == kw[:4]) or k2 == c[:4]:
            ab = {'items': (ab.get('items') or []) + (c2.get('items') or [])}
            break
    abitems = [x for x in (ab.get('items') or [])
               if x.get('title') and (x.get('url') or x.get('desc'))]
    _seen_clear.add(kw[:4])
    overseas.append({
        'name': c, 'kw': kw, 'n': len(hits), 'grp': grp,
        # pri=1 江浙沪皖（第一优先）· pri=2 外地大厂（也接）
        'pri': _ci.get('pri') or 2,
        # why = 为什么这家会有海外能源需求（用户看这一句判断值不值得跟）
        'why': _ci.get('why') or '',
        # proj = 已知海外在建/规划基地
        'proj': _ci.get('proj') or '',
        'rg': _ci.get('rg') or '',
        'amt': round(sum(h['amt'] for h in hits if h['amt']) / 1e8, 3),
        'latest': max([h['d'] for h in hits if h['d']], default=''),
        'items': [{'t': h['t'][:60], 'amt': h['amtY'], 'd': h['d'], 'st': h['st'], 'win': h['win'], 'url': h['url']}
                  for h in hits[:8]],
        'abroad': [{'title': x['title'][:70], 'date': x.get('date') or '', 'tag': x.get('tag') or '',
                    'desc': (x.get('desc') or '')[:130], 'url': x.get('url') or ''} for x in abitems[:4]],
    })
# 只在 AB / AB2 里出现、但不在人工名单里的海外客户，补进来（标 pri=3 表示「挖掘到的，未确认」）
for src in (AB.get('clients', []), AB2.get('clients', [])):
    for c in src:
        nm = c.get('name', '')
        k = nm.replace('（', '(').split('(')[0][:4]
        if not k or k in _seen_clear:
            continue
        _seen_clear.add(k)
        grp = c.get('group') or '其他制造'
        items = [x for x in (c.get('items') or []) if x.get('title')]
        overseas.append({
            'name': nm, 'kw': k, 'n': 0, 'grp': grp, 'pri': 3,
            'why': '新闻/公告中发现的出海动向，尚未确认是否属于我们业务范围',
            'proj': '', 'rg': '', 'amt': 0, 'latest': '',
            'items': [],
            'abroad': [{'title': x['title'][:70], 'date': x.get('date') or '', 'tag': x.get('tag') or '',
                        'desc': (x.get('desc') or '')[:130], 'url': x.get('url') or ''} for x in items[:4]],
        })
# 排序：江浙沪皖优先（用户口径），再按行业，最后按库内命中数。
# 行业顺序按用户点名的重点：有色 → 水泥 → 数据中心 → 钢铁 → 化工 → 造纸 → 玻璃
gorder = {'有色冶炼':0, '水泥':1, '数据中心':2, '钢铁':3, '化工化纤':4, '造纸':5, '玻璃':6}
overseas.sort(key=lambda x: (x['pri'], gorder.get(x['grp'], 9), -x['n'], -x['amt']))
clients = overseas   # 兼容旧代码引用

# ---- 平台：把库里实际出现的来源归并到清单平台，其余长尾按条数门槛收录 ----
plat_cnt = Counter(r['p'] for r in D if r['p'])
platforms = []
matched = set()
for p in IND.get('platforms', []):
    key = p['name'].split('（')[0].split('(')[0][:8]
    cnt = 0
    for name, c in plat_cnt.items():
        if key[:6] and (key[:6] in name or name[:6] in key):
            cnt += c
            matched.add(name)
    platforms.append({**p, 'cnt': cnt})
for name, cnt in plat_cnt.most_common():
    if name not in matched and cnt >= 3:
        platforms.append({'name': name, 'level': '行业/地方', 'url': '', 'cover': '', 'freq': '', 'cnt': cnt})
platforms.sort(key=lambda x: -x.get('cnt', 0))

# 海外信号汇总：全部客户动态平铺，按与我司业务关联度排序
REL_KW = ['发电','自备','电厂','电站','热','海水淡化','氧化铝','电解铝','镍','冶炼','园区','产业园','储能','余热','锅炉','蒸汽']
# ---- 微信线索（只进独立页签，绝不进商机库主表）----
_wx_path = os.path.join(ROOT, 'raw', 'wechat_leads.json')
wechat = {'updated': '', 'days': 0, 'items': []}
# 情报精选：竞对官网自动抓 + 微信深度稿，由 merge_digest.py 产出，这里只读不生成
digest = {'updated': '', 'n_src': 0, 'items': []}
_dg_path = os.path.join(ROOT, 'raw', 'digest.json')
if os.path.exists(_dg_path):
    try:
        digest = json.load(open(_dg_path, encoding='utf-8'))
        digest.setdefault('items', [])
        print('  情报精选 %d 条（官网 %d / 微信 %d）' % (
            len(digest['items']),
            sum(1 for x in digest['items'] if x.get('srcKind') == '官网'),
            sum(1 for x in digest['items'] if x.get('srcKind') == '微信')))
    except Exception as e:
        print('[WARN] digest.json 解析失败：%s' % e)
if os.path.exists(_wx_path):
    try:
        wechat = json.load(open(_wx_path, encoding='utf-8'))
        wechat.setdefault('items', [])
    except Exception as e:
        print('[WARN] wechat_leads.json 解析失败：%s' % e)
print('微信线索 %d 条（竞对 %d / 行业 %d）'
      % (len(wechat['items']),
         sum(1 for x in wechat['items'] if x.get('cat') == '竞对动态'),
         sum(1 for x in wechat['items'] if x.get('cat') == '行业动态')))

overseas = []
for cl in clients:
    for a in cl.get('abroad', []):
        txt = a['title'] + ' ' + a.get('desc') or ''
        rel = sum(1 for k in REL_KW if k in txt)
        overseas.append({'name': cl['name'], 'grp': cl['grp'], 'kw': cl['kw'], **a, 'rel': rel})
# ---- 三行业出海增量（数据中心/化肥/水泥，2026-10-19 上线）----
# 历史 bug（务必牢记）：这批增量最初只写进了 data.js，没落盘到 raw/ 持久源，
# 结果每次 update_weekly.py 全量重建就把它们冲掉（竞对 65→59、海外 76→71）。
# 现在统一从 raw/oversea_extra.json 读取并入，重建也不会丢。
try:
    _ex = json.load(open(os.path.join(RAW, 'oversea_extra.json'), encoding='utf-8'))
    _ex = _ex.get('items', _ex) if isinstance(_ex, dict) else _ex
    _seen = {(o.get('name'), (o.get('title') or o.get('t') or '')) for o in overseas}
    _n = 0
    for x in _ex:
        k = (x.get('name'), (x.get('title') or x.get('t') or ''))
        if k in _seen:
            continue
        txt = (x.get('title') or x.get('t') or '') + ' ' + (x.get('desc') or '')
        x = dict(x)
        x['rel'] = x.get('rel') or sum(1 for _k in REL_KW if _k in txt)
        overseas.append(x)
        _seen.add(k)
        _n += 1
    if _n:
        print('海外增量（三行业）并入 %d 条' % _n)
except Exception as e:
    print('[WARN] oversea_extra.json 未并入：%s' % e)

# ---- 微信深度稿里的海外项目 → 并入海外信号（2026-10-19，用户反馈）----
# 「情报精选」里的 S 级海外项目（如海螺印尼四类新能源）海外板块看不到——两个板块管道割裂。
# digest 本身已落盘 raw/digest.json，重建时可确定性派生，规则：
# 标题/摘要命中已知企业名才并入（挂到该企业、归入对应行业组），命中不了就不并（宁缺毋滥）。
FIRM_ALIAS = {'海螺': '安徽海螺集团有限责任公司', '华新': '华新水泥股份有限公司',
              '红狮': '红狮控股集团有限公司', '润泽': '润泽科技发展有限公司',
              '云天化': '云天化集团有限责任公司', '新洋丰': '新洋丰农业科技股份有限公司',
              '云图': '云图控股', '六国': '六国化工', '川金诺': '川金诺',
              '青山': '青山控股集团有限公司', '华友': '华友钴业股份有限公司'}
# 按「项目标题」去重而不是按企业名——同一企业本来就应该有多条海外项目
_ovtitles = {(o.get('title') or o.get('t') or '')[:40] for o in overseas}
_n2 = 0
for _di in digest.get('items', []):
    if _di.get('tag') != '海外项目':
        continue
    _txt = (_di.get('t') or '') + (_di.get('sum') or '')
    _hit = next((v for k, v in FIRM_ALIAS.items() if k in _txt), None)
    if not _hit or (_di.get('t') or '')[:40] in _ovtitles:
        continue
    # 同一事件可能有两个来源（微信稿标题 + 手工整理的摘要措辞），标题不像但说的是一回事
    import difflib as _dl
    if any(o.get('name') == _hit and _dl.SequenceMatcher(
            None, (o.get('title') or ''), (_di.get('t') or '')).ratio() >= 0.5
           for o in overseas):
        continue
    _g2 = ('水泥建材' if any(z in _txt for z in ('海螺', '华新', '红狮'))
           else '数据中心' if '润泽' in _txt
           else '化肥' if any(z in _txt for z in ('云天化', '新洋丰', '云图', '六国', '川金诺'))
           else '有色' if ('华友' in _txt or '青山' in _txt) else '其他制造')
    overseas.append({'name': _hit, 'grp': _g2, 'kw': _hit,
                     'title': _di.get('t', ''), 'desc': _di.get('sum', ''),
                     'date': _di.get('d', ''), 'tag': '海外投资',
                     'url': _di.get('url', ''), 'rel': 6, 'src': _di.get('src', '')})
    _ovtitles.add((_di.get('t') or '')[:40])
    _n2 += 1
if _n2:
    print('微信深度稿海外项目并入 %d 条' % _n2)
overseas.sort(key=lambda x: (x['rel'], x.get('date') or ''), reverse=True)

# 页面顶部“数据更新”日期
# ------------------------------------------------------------------
# 历史 bug（务必牢记）：早期版本把「文件名里的日期」直接当作页面更新日期。
# 后果有两个：
#   ① 正则只认 2026-10-07.json 这类裸文件名，而 raw/early/ 下都是
#      early-2026-10-12.json、jigai-js-2026-10-10.json 这种带前缀的，全部落空；
#   ② 即便匹配上了，只要本周没产出命名规范的增量文件，页面日期就永远停在旧值，
#      数据其实已经更新了却显示没更新 —— 用户多次反馈“怎么还是 X 号的数据”根因在此。
# 现在改为：updated = 真实构建时刻（用户关心的是“今天有没有跑”），
#          dataAsOf = 源文件里的最新日期（溯源用，不影响展示）。
_build_day = time.strftime('%Y-%m-%d')
_latest_weekly = time.strftime('%Y-%m-%d')
_dates = []
for _sub in ('weekly', 'early'):
    _d = os.path.join(ROOT, 'raw', _sub)
    if not os.path.isdir(_d): continue
    for f in os.listdir(_d):
        # 从任意文件名（含前缀、含渠道名）中提取日期，不再要求裸文件名
        _dates.extend(re.findall(r'\d{4}-\d{2}-\d{2}', f))
if _dates:
    _latest_weekly = max(_dates)

# 行业动态先算出来，供「重点客户打通」复用（2026-10-20）
TRENDS = ([t for t in IND.get('trends', [])
           if '微信' not in (t.get('source') or '')
           and (t.get('tag') or '') != '微信快讯']
          + [{'title': d.get('t', ''), 'desc': d.get('sum', ''),
              'date': d.get('d', ''), 'source': d.get('src', ''),
              'tag': '行业动向' if d.get('tag') in ('行业动向', '政策资质') else d.get('tag', ''),
              'url': d.get('url', '')}
             for d in digest.get('items', [])
             if d.get('tag') in ('行业动向', '政策资质')])

# 北极星电力网（2026-10-20 新增渠道）：行业动态原来只靠微信快讯，微信渠道堵死后断粮，
# 北极星是电力/环保垂直媒体且静态可直抓，实测每轮 190+ 条。只收 30 天内、带日期的。
try:
    _bjx = json.load(open(os.path.join(RAW, 'bjx_news.json'), encoding='utf-8'))
    _bjx = _bjx.get('items', _bjx) if isinstance(_bjx, dict) else _bjx
    _cut = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    _add = [{'title': x['t'], 'desc': '', 'date': x.get('d', ''),
             'source': x.get('src', ''), 'tag': x.get('cat', '电力'),
             'url': x.get('url', '')}
            for x in _bjx if x.get('d') and x['d'] >= _cut]
    _have = {t['title'][:34] for t in TRENDS}
    _add = [x for x in _add if x['title'][:34] not in _have]
    TRENDS += _add
    print('北极星电力网并入行业动态 %d 条（近 30 天）' % len(_add))
except Exception as e:
    print('[WARN] bjx_news.json 未并入：%s' % e)

# ---- 打通：重点客户 ← 情报精选 + 行业动态（2026-10-20，用户反馈）----
# 原本四个板块各自孤立：客户卡片只有招标项目，看不到该客户的新闻和行业动向。
# 现在按客户名关键词把「情报精选」和「行业动态」里提到该客户的内容聚合到客户卡片上。
_cli_hit = 0
for _c in clients:
    _kw = (_c.get('kw') or '').strip()
    # 太短的词（如「沙钢」2 字）容易满屏误匹配，至少要 3 个字才做聚合
    _core = _kw if 3 <= len(_kw) <= 6 else _kw[:4]
    _c['news'] = []
    _c['newsN'] = 0
    if len(_core) < 3:
        continue
    _pool = []
    for _x in digest.get('items', []):
        if _core in ((_x.get('t') or '') + (_x.get('sum') or '')):
            _pool.append({'t': _x.get('t', ''), 'd': _x.get('d', ''),
                          'src': _x.get('src', ''), 'tag': _x.get('tag', ''),
                          'lvl': _x.get('level', ''), 'url': _x.get('url', '')})
    for _x in TRENDS:
        if _core in ((_x.get('title') or '') + (_x.get('desc') or '')):
            _pool.append({'t': _x.get('title', ''), 'd': _x.get('date', ''),
                          'src': _x.get('source', ''), 'tag': _x.get('tag', ''),
                          'lvl': '', 'url': _x.get('url', '')})
    _seenk = set()
    _out = []
    for _n in sorted(_pool, key=lambda z: (z.get('d') or ''), reverse=True):
        _k = _n['t'][:30]
        if _k in _seenk:
            continue
        _seenk.add(_k)
        _out.append(_n)
    _c['news'] = _out[:6]
    _c['newsN'] = len(_out)
    if _out:
        _cli_hit += 1
print('重点客户打通：%d 家命中精选/行业动态' % _cli_hit)

# 业主 / 供应商关系图谱（由 build_owner_graph.py 预计算）
_GRAPH = {'owners': [], 'suppliers': [], 'nOwner': 0, 'nSupplier': 0, 'nRel': 0}
_gp = os.path.join(RAW, 'owner_graph.json')
if os.path.exists(_gp):
    try:
        _GRAPH = json.load(open(_gp, encoding='utf-8'))
        print('关系图谱：业主 %d 家 / 供应商 %d 家'
              % (_GRAPH.get('nOwner', 0), _GRAPH.get('nSupplier', 0)))
    except Exception as e:
        print('[WARN] owner_graph.json 解析失败：%s' % e)
else:
    print('[WARN] 缺 owner_graph.json，业主画像板块将为空（先跑 build_owner_graph.py）')

# ── 竞企/伙伴档案挂「库内战绩」（2026-10-21）──────────────────────────
# 用户原话：「画像还是同业与伙伴这块是重点画像」。现有 65 家竞企 + 52 家伙伴，
# strength 描述都很厚（平均 183 字），但完全是「百度百科式的静态介绍」，
# 跟本库 1954 条真实中标数据一点没打通——看的人不知道它到底在江浙沪皖拿过什么。
# 这里按「名称/简称/别名」三重匹配把中标记录反向挂到档案上：
#   hits  该单位在本库的中标记录（只留关注档：≥3000 万或 A/B 级）
#   wStat {n 次数, amt 累计金额, rg 区域分布, first/last 时间, top 最大单}
# 匹配不到的空档案也会标 hit=0，前端好区分「没证据」和「真没有」。
def _aliases(o):
    """从档案名里拆出所有可用于匹配的写法。"""
    nm = o.get('name') or ''
    out = []
    cands = [nm]
    for m in re.finditer(r'[（(]([^）)]+)[）)]', nm):
        cands.append(m.group(1))
    for seg in re.split(r'[/、]', nm):
        cands.append(seg)
    for seg in re.split(r'[（(/、]', nm):
        cands.append(seg)
    for c in cands:
        c = re.sub(r'\s+', '', c or '')
        # 太短的名字（"上海"、"设计院"）会误伤，统一要求 ≥4 字
        if len(c) >= 4 and c not in out:
            out.append(c)
    return out


def attach_track(orgs):
    """把本库中标记录挂到竞企/伙伴档案上，原地修改并返回。"""
    if not orgs:
        return orgs
    # all_wins 是全口径（含几百万的小项目），wins 是关注档。
    # 档案卡上「N 次中标」按全口径数，金额按关注档算——次数骗不了人，
    # 但把 200 万的服务采购也算进去会让人以为它拿了 200 个大标。
    all_wins = [b for b in brief if b['win']]
    wins = [b for b in all_wins if is_watch(b)]
    # 同一家单位在 industry.json 里可能存在两条档案（一条全称、一条简称），
    # 别名一交叉就互相抢命中，页面上会出现两个都写「命中 2 次」的重复卡。
    # 先按别名集合做一次去重：候选别名被另一条档案的「全称」完全包含时，
    # 说明是同一个主体，直接跳过（保留名字更长的那个）。
    for _o in orgs:
        _o['_aliases'] = _aliases(_o)
    _owner = {}
    for _o in orgs:
        for _a in _o['_aliases']:
            _owner.setdefault(_a, []).append(_o)
    for o in orgs:
        # 只留「本档案自己的全称 + 自己独有的别名」：
        # 若某个别名同时也是一份更长名字档案的全称，说明它属于那家，让出去。
        _full = (o.get('name') or '')
        aliases = []
        for a in o['_aliases']:
            rivals = _owner.get(a, [])
            longer = [z for z in rivals if z is not o and len(z.get('name') or '') > len(_full)]
            if longer and a != _full:
                continue
            aliases.append(a)
        hits, seen = [], set()
        for b in wins:
            if b['id'] in seen:
                continue
            for a in aliases:
                if a in b['win']:
                    hits.append(b)
                    seen.add(b['id'])
                    break
        # 口径：只数关注档（≥3000 万 或 综合分 A/B）。
        # 2026-10-21 用户原话「几百万的项目放上去只会污染数据库」——
        # 之前这里用了全口径，结果「中国联合工程」显示命中 3 次、金额 0 亿，
        # 看着像拿了三个大标却一分钱没花。现在次数和金额同一口径，不再自相矛盾。
        n_all = len(hits)
        hits.sort(key=lambda x: (x.get('amt') or 0), reverse=True)
        o['hits'] = [{k: h.get(k) for k in ('id', 't', 'buyer', 'win', 'amt', 'd', 'rg', 'st', 'url')}
                     for h in hits[:8]]
        o['wStat'] = {
            'n': len(hits),
            'nAll': n_all,
            'amt': round(sum(h.get('amt') or 0 for h in hits), 3),
            'rg': dict(Counter(h['rg'] for h in hits if h.get('rg')).most_common()),
            'last': max((h.get('d') or '' for h in hits), default=''),
            'top': (max(hits, key=lambda h: h.get('amt') or 0)['amt'] if hits else 0),
            'topT': (max(hits, key=lambda h: h.get('amt') or 0)['t'][:60] if hits else ''),
        }
        o.pop('_aliases', None)
    return orgs


# 竞企和伙伴放在一起认领：一条中标记录只能归一家，否则同一笔 4.475 亿的
# 联合体标会被「阜阳城投建设」和「阜阳生态环境科技」各算一遍，排行榜直接失真。
IND['competitors'] = attach_track(IND.get('competitors', []))
IND['partners'] = attach_track(PARTNERS if 'PARTNERS' in globals() else IND.get('partners', []))
_all_orgs = (IND.get('competitors') or []) + (IND.get('partners') or [])
if _all_orgs:
    # 重建一份「行内多个主体」的映射：同一条记录被几家认领，就按几家均分金额
    _claim = {}
    for _o in _all_orgs:
        for _h in (_o.get('hits') or []):
            _claim.setdefault(_h['id'], []).append(_o)
    _multi = sum(1 for v in _claim.values() if len(v) > 1)
    if _multi:
        print('[联合体分摊] %d 条中标记录被多家同时认领，按家数均分金额' % _multi)
    for _hid, _owners in _claim.items():
        if len(_owners) < 2:
            continue
        _k = len(_owners)
        for _o in _owners:
            _ws = _o.get('wStat') or {}
            _ws['n'] = max(1, int(round((_ws.get('n') or 0) / _k)))
            # 金额：从原值里扣掉重复部分（原值把同一笔算了 _k 次）
            _ws['amt'] = round((_ws.get('amt') or 0) * (1 - (_k - 1) / _k), 3)
            _ws['joint'] = 1
            _o['wStat'] = _ws

data = {
    'metals': {'updated': METALS[0]['date'] if METALS else '',
               'at': time.strftime('%H:%M') if METALS else '',
               'items': METALS},
    'partners': PARTNERS,
    'overseas': overseas,
    'wechat': wechat,
    'digest': digest,
    'meta': {
        # 页面展示用：真实构建时刻。用户判断“今天有没有更新”只看这个。
        'updated': _build_day,
        'at': time.strftime('%H:%M'),
        # 溯源用：源文件（weekly/early）里的最新日期，可能早于构建日
        'dataAsOf': _latest_weekly,
        'total': len(D),
        'new': sum(1 for r in D if r.get('_new')),
        'withAmt': sum(1 for r in D if r['amt']),
        'withWin': sum(1 for r in D if r['win']),
        'amtSum': round(sum(r['amt'] for r in D if r['amt']) / 1e8, 1),
        'bizTop': Counter(r['biz'] for r in D).most_common(),
        'gradeTop': Counter(r['g'] for r in D).most_common(),
        'rgTop': Counter(r['rg'] for r in D).most_common(),
        'stTop': Counter(r['st'] for r in D).most_common(),
        'subTop': Counter(r['sub'] for r in D).most_common(40),
        'platTop': Counter(r['p'] for r in D if r['p']).most_common(20),
    },
    'items': brief,
    'rivals': rivals,
    # 关注门槛说明 + 三栏计数，前端顶栏直接读这个
    'watch': {
        'amt': WATCH_AMT,
        'tender': sum(1 for b in brief if b['bk'] == 'tender' and b['w']),
        'win': sum(1 for b in brief if b['bk'] == 'win' and b['w']),
        'lead': sum(1 for b in brief if b['bk'] == 'lead'),
        'tenderAll': sum(1 for b in brief if b['bk'] == 'tender'),
        'winAll': sum(1 for b in brief if b['bk'] == 'win'),
        'all': len(brief),
    },
    'buyers': buyers,
    # 潜在业主：名字/行业像但库里没发过我们这类标，只在「客户与业主」页二级位置简单展示
    'latent': latent,
    'clients': clients,
    # 国内重点客户：从业主库自动筛（采购过热电/供热/环保/新能源且规模够看的）
    'domestic': DOM_TOP,
    'domStat': {'total': len(domestic), 'shown': len(DOM_TOP),
                'S': sum(1 for x in domestic if x['tier'] == 'S'),
                'A': sum(1 for x in domestic if x['tier'] == 'A'),
                'B': sum(1 for x in domestic if x['tier'] == 'B')},
    # 行业动态：非微信原始条目 + 情报精选里的「行业动向/政策资质」（2026-10-19 改）
    # 旧逻辑把微信条目全过滤掉，结果 80 条只剩 25 条、最新停在 09-16——微信渠道堵死后
    # 这个板块等于断粮。现在改用竞对官网采集来的行业动向（带真实直链）补上，
    # 且只取精选层（S/A 级、有摘要），不与下层快讯重复。
    'trends': TRENDS,
    'competitors': IND.get('competitors', []),
    # partners 已在上面用 PARTNERS（含 52 家真实伙伴池）赋过值，
    # 这里绝不能再写 'partners': IND.get('partners', [])——那会用空列表覆盖掉。
    'platforms': platforms,
    # 业主画像 + 供应商关系图谱（2026-10-21，领导意见）：由 build_owner_graph.py 预计算落盘
    'graph': _GRAPH,
}

js = 'window.DATA=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';'
open(os.path.join(OUT, 'data.js'), 'w', encoding='utf-8').write(js)

# ── 分模块输出（2026-10-21，解决「加载时间太长」）──────────────────────
# 单文件 2.1MB 一次性下完才能渲染首屏。拆成 5 个文件后：
#   data.core.js  顶栏/KPI/口径/平台/行情  —— 首屏必需，约 100KB
#   data.items.js 商机明细 1954 条          —— 商机库渲染必需，约 900KB（最大）
#   data.org.js   同业/业主/客户/图谱        —— 点对应 tab 才加载
#   data.news.js  行业动态/情报/海外/伙伴    —— 点对应 tab 才加载
# 页面先出骨架 + KPI，商机库一到就能看；其他三个点开才拉。
# 同时保留单片 data.js 作为兜底（万一某模块加载失败，回退整包）。
def dump(name, obj):
    s = 'window.DATA_%s=' % name.upper() + json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + ';'
    open(os.path.join(OUT, 'data.%s.js' % name), 'w', encoding='utf-8').write(s)
    return len(s.encode('utf-8'))


# ── items 列式存储（2026-10-21）────────────────────────────────────
# 1954 条记录平均 573 字节，其中近三分之一是重复出现的字段名
# （"url":、"buyer":、"st":…）。改成「字段名只写一次 + 每字段一个数组」后，
# 体积直接掉四成，前端用 packItems() 还原成对象——纯搬运，不丢任何字段。
# 稀疏字段（只有少数记录有的，如 files/org/rng）不参与列式，单独挂到 ext 里，
# 否则会塞进去一堆 null，反而变大。
# 2026-10-21 补 sg/sG/sR/hm：业务分层改造后这四个字段是前端筛选和标签的依据，
# 漏加进白名单的直接后果是「业务分层筛选器为空、卡片全被过滤掉」——
# 白名单是列式打包的唯一入口，加了 brief 字段必须同步加这里。
ITEM_COLS = ['id', 't', 'st', 'g', 'sg', 'sG', 'sR', 'hm', 'ind', 'rg', 'city', 'buyer', 'win',
             'amt', 'amtTxt', 'd', 'dl', 'p', 'url', 'mode', 'snip', 'sc', 'nw',
             'early', 'expect', 'bk', 'w', 'linkbad']
_its = data['items']
_cols = {k: [] for k in ITEM_COLS}
_ext = {}
for _i, _x in enumerate(_its):
    for _k in ITEM_COLS:
        _cols[_k].append(_x.get(_k))
    # 稀疏字段：只记非空的，键是行号
    for _k in ('hist', 'files', 'org', 'rp', 'sh'):
        _v = _x.get(_k)
        if _v:
            _ext.setdefault(_k, {})[str(_i)] = _v


# 全量明细分块（2026-10-21 三轮提速）
# 一开始把全量 1954 条塞进一个 data.items.all.js（1.27MB / gzip 275KB）。
# 实测在弱网（沙箱到 GitHub Pages 只有 ~15KB/s）下要下一分半——这不是文件写错了，
# 是单文件太大在高延迟链路上很吃亏，而且用户点「立项线索」时根本不需要
# 「全部」库里那 1550 条无关记录。改成按用途切块，点到哪块拉哪块：
#   chunk-0  能投的标 + 已出结果 的关注档（首屏，已单独输出在 data.items.js）
#   chunk-1  立项线索（637 条）—— 用户点「💡 立项线索」才拉
#   chunk-2  全部库其余部分 —— 用户点「全部」或搜索时才拉
# 每块用同一个 _cols 结构，前端 packItems 直接吃，不需要额外对齐逻辑。
CHUNK_DEFS = [
    ('lead', lambda x: x.get('bk') == 'lead'),
    ('rest', lambda x: x.get('bk') not in ('lead',) and not (x.get('w') and x.get('bk') in ('tender', 'win'))),
]


def dump_item_chunks():
    total = 0
    meta = []
    for name, fn in CHUNK_DEFS:
        idx = [i for i, x in enumerate(_its) if fn(x)]
        if not idx:
            continue
        cc = {k: [_cols[k][i] for i in idx] for k in ITEM_COLS}
        ee = {}
        for k, m in _ext.items():
            for pos, i in enumerate(idx):
                if str(i) in m:
                    ee.setdefault(k, {})[str(pos)] = m[str(i)]
        body = ('window.DATA_CHUNK=' +
                json.dumps({'cols': cc, 'ext': ee, 'n': len(idx), 'order': idx},
                           ensure_ascii=False, separators=(',', ':')) + ';')
        fnm = 'data.chunk-%s.js' % name
        open(os.path.join(OUT, fnm), 'w', encoding='utf-8').write(body)
        sz = len(body.encode('utf-8'))
        total += sz
        meta.append({'name': name, 'file': fnm, 'n': len(idx), 'kb': round(sz / 1024)})
        print('  分块 %-5s %4d 条 %6.0f KB' % (name, len(idx), sz / 1024))
    return total, meta


# ── 首屏明细切片（2026-10-21 二轮提速）──────────────────────────────
# 实测（Playwright 限速 4Mbps）：首屏 3.2 秒里渲染只占 25ms，剩下全是下载 1.27MB。
# 而首屏默认只看「📋 能投的标 / 🏁 已出结果」两个关注库，共约 400 条，
# 另外 1550 条（立项线索 + 全部库）要用户主动点才看得到。
# 所以把明细拆两份：
#   data.items.js       首屏 400 条关注档（约 280KB，gzip 后 ~60KB）—— 阻塞首屏
#   data.items.all.js   全量 1954 条 —— 空闲时预取，点「立项线索/全部」时若还没到就等它
# 索引对不上是致命的（ext 里按行号挂 sparse 字段），所以 all 文件里存全量、
# 首屏文件里存同一批行号的对象，靠 order 数组把「首屏行号 → 全量行号」映射回去。
def dump_items_split():
    keep = [i for i, x in enumerate(_its) if x.get('w') or x.get('bk') == 'lead']
    # 首屏库 = 能投的标 + 已出结果 里的关注档（不含立项线索，立项线索量大且不急着看）
    keep = [i for i in keep if _its[i].get('bk') in ('tender', 'win')]
    sub_cols = {k: [_cols[k][i] for i in keep] for k in ITEM_COLS}
    sub_ext = {}
    for k, m in _ext.items():
        for pos, i in enumerate(keep):
            if str(i) in m:
                sub_ext.setdefault(k, {})[str(pos)] = m[str(i)]
    head = {'cols': sub_cols, 'ext': sub_ext, 'n': len(keep), 'order': keep, 'total': len(_its)}
    s = ('window.DATA_ITEMS=' + json.dumps(head, ensure_ascii=False, separators=(',', ':')) + ';')
    open(os.path.join(OUT, 'data.items.js'), 'w', encoding='utf-8').write(s)
    print('首屏明细 %d 条 / 全量 %d 条' % (len(keep), len(_its)))
    return len(s.encode('utf-8'))


_core = {k: data[k] for k in ('meta', 'metals', 'platforms', 'watch', 'domStat') if k in data}
# org 模块再拆一层（2026-10-21 四轮提速）：
# graph（业主图谱 665KB）只有「客户与业主 → 业主图谱」这个子页才用，
# 却跟竞企/伙伴/客户绑在同一个 1.1MB 文件里，打开同业页要先等它下完。
# 单独拆成 data.graph.js，进图谱子页时才拉。
_org = {k: data[k] for k in ('rivals', 'buyers', 'latent', 'domestic', 'competitors',
                             'clients', 'partners') if k in data}
_graph_mod = {'graph': data['graph']} if 'graph' in data else {}
_news = {k: data[k] for k in ('trends', 'digest', 'wechat', 'overseas') if k in data}
_chunk_total, _chunk_meta = dump_item_chunks()
_extra = {'chunks': _chunk_meta}
# 四库一平台信用代码（2026-10-22）：只有进「深度档案」才用得上，
# 单独一个模块，不塞进 core——它是 1500 条 × 200 字节，塞 core 会让首屏多等 300KB。
_siku_mod = {}
_siku_path = os.path.join(ROOT, 'raw', 'siku.json')
if os.path.exists(_siku_path):
    try:
        _sk = json.load(open(_siku_path, encoding='utf-8'))
        _siku_mod = {'items': _sk.get('items') or {}, 'updated': _sk.get('updated'),
                     'hit': _sk.get('hit'), 'note': _sk.get('note')}
        print('四库一平台：%d 家已查，命中 %d 家（信用代码）'
              % (len(_siku_mod['items']), _sk.get('hit') or 0))
    except Exception as _e:
        print('⚠ raw/siku.json 读失败，跳过：', _e)
_parts = _chunk_total + dump('core', dict(_core, **_extra)) + dump('org', _org) + dump('news', _news) + dump('graph', _graph_mod) + (dump('siku', _siku_mod) if _siku_mod else 0)
print('分模块：core + items(列式) + org + news 合计 %.0f KB（单文件 data.js %.0f KB）'
      % (_parts / 1024, len(js.encode('utf-8')) / 1024))

# 同步更新 index.html 里的 data.js 版本参数（浏览器缓存强制失效）
# 2026-10-21 改成 defer 加载后，版本号就在 script 标签的 src 上。
import time as _time
_ver = _time.strftime('%Y%m%d%H%M')
html_path = os.path.join(OUT, 'index.html')
if os.path.exists(html_path):
    h = open(html_path, encoding='utf-8').read()
    # 版本号同时覆盖 data.js 以及分模块的 data.xxx.js
    h2 = re.sub(r"var VER='\?v=[\w_]*';", "var VER='?v=%s';" % _ver, h)
    h2 = re.sub(r'data\.(?:js|core\.js|items(?:\.all)?\.js|org\.js|news\.js|graph\.js|chunk-[\w-]+\.js)\?v=[\w_]*',
                lambda mm: mm.group(0).split('?')[0] + '?v=' + _ver, h2)
    if 'data.js?v=' not in h2:
        h2 = h2.replace('src="data.js"', 'src="data.js?v=' + _ver + '"')
    open(html_path, 'w', encoding='utf-8').write(h2)
    print('index.html 版本参数 → v=%s' % _ver)

print(f"data.js  {len(js)/1024:.0f} KB")
print(f"明细 {len(brief)} · 竞争对手 {len(rivals)} · 业主 {len(buyers)} · 客户 {len(clients)}")
print(f"行业动态 {len(data['trends'])} · 竞企档案 {len(data['competitors'])} · 平台 {len(data['platforms'])}")
print('\n== 竞争对手 TOP12（按中标次数）==')
for x in rivals[:12]:
    print(f"  {x['n']:>3}次 {x['amt']:>7.2f}亿  {x['name'][:34]:<34} {x['main']}")
print('\n== 业主 TOP10 ==')
for x in buyers[:10]:
    print(f"  {x['n']:>3}条 {x['amt']:>7.2f}亿  {x['name'][:36]}")
print('\n== 客户命中 TOP12 ==')
for x in clients[:12]:
    print(f"  {x['n']:>3}条 {x['amt']:>7.2f}亿  {x['name'][:30]:<30} {x['rg']}")
