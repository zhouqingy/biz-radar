# -*- coding: utf-8 -*-
"""安徽省发改委 / 省能源局「项目核准 + 节能审查 + 项目公示」采集器（2026-10-28 新增）。

为什么做这个
────────────
用户要的是「安徽沿江重点市的热电联产 / 资源综合利用发电规划」。实测跑了一圈发现：

  · 芜湖 fgw.wuhu.gov.cn 根本不通（http=000）
  · 马鞍山 fgw.mas.gov.cn、安庆 fgw.anqing.gov.cn 栏目页是**空壳**（curl 拿到 2~3 万字节
    但一个列表条目都没有，全靠 JS 渲染，而且渲染也失败）
  · 铜陵 www.tl.gov.cn 的 queryList 接口能通，但栏目里全是人大会议决定、慰问信
  · 宣城 fgw.xuancheng.gov.cn 的栏目树能拿到（「规划信息」id=99619），列表走
    pagination-ajax.js 异步加载，浏览器渲染出来是 0 字节

市县这条路走不通，于是换到**省级通道**——反而是更好的选择，理由：
  1. 安徽的电力项目核准权在**省发改委 / 省能源局**，不在市里。市里发的规划是「计划」，
     省里发的核准 / 节能审查是「项目」——后者直接点名**业主 + 装机 + 地点**，离商机更近。
  2. 省级栏目覆盖全省，沿江五市（芜湖/马鞍山/铜陵/安庆/宣城）的业主一个不漏。

安徽省站实测（2026-10-28）
────────────────────────
  · 列表是**异步**的：/site/label/8888?labelName=publicInfoList&siteId=49631471
    &organId=7011&pageSize=20&pageIndex=N&type=4&action=list&isJson=true&catIds=<catId>
    （从页面内联 JS 的 `me.listParams` 里挖出来的；直接 curl 即可，返回 JSON，数据在 data[]）
  · 栏目 ID 从 https://fzggw.ah.gov.cn/49631471/7011.js 这棵栏目树里取：
        catId=49945391  企业投资项目核准   ← 标题直给「业主 + 项目名」
        catId=49947011  节能审查           ← **正文最肥**：项目代码/总投资/装机/技术方案
        catId=49948151  项目公示           ← 只有 16 条，顺手带上
  · 详情页 https://fzggw.ah.gov.cn/public/7011/<contentId>.html
    元数据（索引号/发布机构/生成日期/文号/名称）在 conTxt 容器里，正文在「来源：」之后。
  · ⚠ 省能源局**没有独立 organId**（试过 7012/7013/7014/7021/7031 全是 404），
    它挂靠在省发改委 7011 下发文。

三条提取经验（都是踩过的坑）
──────────────────────────
  1. **数字被 HTML 标签切碎**：正文里项目代码渲染成「2408- 34 0 222 - 0 4 -0 2 - 554533」、
    金额渲染成「4900 万元」，因为每个数字段外面裹了 span。必须先生成一份**去空白的紧凑
    文本**再跑正则，否则什么都匹配不到。
  2. **项目代码 = 精确的行政区划**：`YYMM-CCCCCC-TT-SS-NNNNNN`，CCCCCC 是 6 位区划码，
    前 4 位就是地级市（3402 芜湖 / 3405 马鞍山 / 3407 铜陵 / 3408 安庆 / 3418 宣城）。
    比猜标题里的地名准得多——标题经常一个地名都不写。
  3. **正文开头就是业主**：节能审查意见的抬头写成「芜湖市富鑫钢铁有限公司 ：」，
    直接匹配「全称 + 冒号」就能拿到，比从标题里抠「福莱特」「南玻」这种简称靠谱。
  · ⚠ 「核准前公示」（马钢北区 30MW / 铜陵有色三期 10MW / 福莱特四期 2×15MW，项目代码
    2603- / 2605- 开头）在省站的公开库里**搜不到**，只在北极星、电力项目网等转载站能
    看到全文，推测发布在省投资项目在线审批监管平台（tzxm.ahzwfw.gov.cn）。
    所以本采集器抓的是**核准批复 + 节能审查意见**——比核准前公示晚一步，但一样是项目级
    一手信息，且带文号，可溯源。

产出：raw/early/ah-nygs-latest.json，early='热电规划'
（build_data.py 的 EARLY_SRC 已把 '热电规划' 映射为「立项公示」层，无需再改映射）

用法：python crawl_ah_nygs.py [--dry] [--pages 20]
"""
import argparse
import html as html_mod
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
ROOT = os.path.dirname(os.path.abspath(__file__))
EARLY_DIR = os.path.join(ROOT, 'raw', 'early')
SITE = 'https://fzggw.ah.gov.cn'
LABEL = SITE + '/site/label/8888'

# (栏目名, catId, 翻页数)
CATS = [
    ('企业投资项目核准', '49945391', 16),
    ('节能审查', '49947011', 30),
    ('项目公示', '49948151', 1),
]

# 必须命中「电力/热力」核心词才算数。
# ⚠ 最初写的 WANT 里含泛词「综合利用|水泥|玻璃|化工」，结果捞进来一堆跟发电毫无关系的
#   项目：多金属再生资源处理、水泥用灰岩矿年产7000万吨、瓶级聚酯、酚醛树脂、钛石膏…
#   这类占了一半以上。安徽的节能审查栏目化工/矿山项目极多，必须用电力的硬词卡。
WANT = re.compile(
    r'余热|余气|余压|煤气|热电|热电厂|发电|供热|热力|能源站|'
    r'生物质|垃圾焚烧|焚烧|燃煤机组|机组|背压|抽凝|干熄焦|蒸汽|锅炉|汽轮机')
# 交通/基建/社会事业/非电化工矿山——标题里带这些的一律丢掉
SKIP = re.compile(
    r'公路|高速公路|铁路|机场|航道|码头|港口|车站|地铁|桥梁|隧道|'
    r'学校|医院|学院|大学|中学|小学|病房|宿舍|实训|体育馆|博物馆|'
    r'铁矿|采矿|矿山|灰岩矿|石灰岩矿|房地产|棚户区|安置房|景区|旅游|'
    r'输变电|变电站|送出工程|电网|光伏|风电|风电场|抽水蓄能|储能|充电|'
    r'锂电池|废旧电池|再生铝|废钢|废旧|拆解|脱硝|脱硫|超低排放|'
    r'聚酯|酚醛树脂|钛石膏|高岭土|废盐|甲醇|可降解塑料|排土场|生态修复|'
    # 「直升机组装」里带「机组」会误命中 WANT；「高空风能」同理
    r'直升机|通用航空|风能')

# 企业全称
CO_PAT = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,32}?'
                    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司|总厂|发电厂|公司))')
# 正文抬头：「芜湖市富鑫钢铁有限公司 ：」
HEAD_CO = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,34}?'
                     r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司|总厂|发电厂))\s*[:：]')
# 标题前缀：把「安徽省发展改革委关于」「省发展改革委核准」这类官方套话抹掉
TITLE_PREFIX = re.compile(
    r'^(?:安徽省发展改革委|安徽省发展和改革委员会|安徽省发展改革委员会|省发展改革委|'
    r'安徽省能源局|省能源局|安徽省发改委)?\s*(?:关于|核准|同意)?\s*(?:核准|同意|'
    r'同意变更|同意再次变更|出具|发布|原则同意)?\s*(?:关于)?\s*')
NOT_CO = re.compile(r'发展改革委|发改委|人民政府|管委会|办公室|委员会|能源局|'
                    r'工业和信息化|住房城乡建设|生态环境')

# 项目代码：2408-340222-04-02-554533，第 2 段是 6 位行政区划码。
# ⚠ 只能当兜底用：「芜湖孙村经济开发区热电联产项目」的代码是 2018-341721-…，
#   341721 = 池州东至，可项目明明在芜湖繁昌。登记时填错区划码的情况不少见，
#   所以优先级排在「项目建设地点」和标题之后。
CODE_PAT = re.compile(r'(\d{4})-(\d{6})-(\d{2})-(\d{2})-(\d{6})')
# 正文里这两个字段比标题和抬头都准
BUILD_ORG = re.compile(
    r'项目(?:建设)?单位[:：]\s*([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,40}?'
    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司|总厂|发电厂))')
LOC_PAT = re.compile(r'项目(?:建设)?(?:地点|选址|拟建地点)?(?:为|位于|在)?[:：]?\s*'
                     r'([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,40}?)'
                     r'(?:经济开发区|开发区|工业园区|产业园|化工园区|新区|厂区)')
# 安徽地级市区划码前 4 位
AREA2CITY = {
    '3401': '合肥', '3402': '芜湖', '3403': '蚌埠', '3404': '淮南',
    '3405': '马鞍山', '3406': '淮北', '3407': '铜陵', '3408': '安庆',
    '3410': '黄山', '3411': '滁州', '3412': '阜阳', '3413': '宿州',
    '3415': '六安', '3416': '亳州', '3417': '池州', '3418': '宣城',
}
# 装机：2×660MW / 55MW / 30兆瓦（紧凑文本里没有空格）
CAP_PAT = re.compile(r'(\d+(?:\.\d+)?(?:[×xX*]\d+(?:\.\d+)?)?)\s*(MW|兆瓦|万千瓦)')
# 装机优先取「装机规模/机组/发电」附近的数字
CAP_CTX = re.compile(
    r'(?:装机规模|装机容量|装机|新建|改建|扩建|建设|配置|拟建|采用)[^。；]{0,40}?'
    r'(\d+(?:\.\d+)?(?:[×xX*]\d+(?:\.\d+)?)?)(MW|兆瓦|万千瓦)')
# 投资：项目总投资4900万元
AMT_PAT = re.compile(r'(?:项目总投资|总投资|投资总额|静态投资|动态投资)[^0-9]{0,10}'
                     r'(\d+(?:\.\d+)?)(亿元|万元)')

CITIES_AH = ['合肥', '芜湖', '蚌埠', '淮南', '马鞍山', '淮北', '铜陵', '安庆', '黄山',
             '滁州', '阜阳', '宿州', '六安', '亳州', '池州', '宣城']
# 安徽县市 → 设区市。批复标题常只写「萧县林平纸业」「怀远县南国环保热电」
COUNTY2CITY = {
    '无为': '芜湖', '繁昌': '芜湖', '南陵': '芜湖', '湾沚': '芜湖', '弋江': '芜湖',
    '和县': '马鞍山', '含山': '马鞍山', '当涂': '马鞍山', '花山': '马鞍山',
    '枞阳': '铜陵', '义安': '铜陵',
    '怀宁': '安庆', '潜山': '安庆', '太湖': '安庆', '宿松': '安庆',
    '望江': '安庆', '岳西': '安庆', '桐城': '安庆', '迎江': '安庆',
    '郎溪': '宣城', '泾县': '宣城', '绩溪': '宣城', '旌德': '宣城',
    '宁国': '宣城', '广德': '宣城', '宣州': '宣城',
    '东至': '池州', '石台': '池州', '青阳': '池州', '贵池': '池州',
    '明光': '滁州', '全椒': '滁州', '来安': '滁州', '凤阳': '滁州',
    '定远': '滁州', '天长': '滁州', '琅琊': '滁州', '南谯': '滁州',
    '临泉': '阜阳', '太和': '阜阳', '颍上': '阜阳', '阜南': '阜阳', '界首': '阜阳',
    '砀山': '宿州', '萧县': '宿州', '灵璧': '宿州', '泗县': '宿州', '埇桥': '宿州',
    '霍邱': '六安', '金寨': '六安', '霍山': '六安', '舒城': '六安', '叶集': '六安',
    '蒙城': '亳州', '涡阳': '亳州', '利辛': '亳州', '谯城': '亳州',
    '固镇': '蚌埠', '五河': '蚌埠', '怀远': '蚌埠', '淮上': '蚌埠',
    '凤台': '淮南', '寿县': '淮南', '潘集': '淮南',
    '长丰': '合肥', '肥东': '合肥', '肥西': '合肥', '巢湖': '合肥', '庐江': '合肥',
    '黟县': '黄山', '歙县': '黄山', '休宁': '黄山', '祁门': '黄山',
    '濉溪': '淮北', '烈山': '淮北',
}
# 标题只写简称的，靠这层补全称 + 落城市（都是安徽余热/余气发电的老面孔）
ALIAS = {
    '福莱特': ('安徽福莱特光伏玻璃有限公司', '滁州'),
    '南玻': ('安徽南玻新能源材料科技有限公司', '滁州'),
    '海控三鑫': ('海控三鑫（凤阳）新能源材料有限公司', '滁州'),
    '首矿大昌': ('安徽首矿大昌金属材料有限公司', '六安'),
    '铜陵泰富': ('铜陵泰富特种材料有限公司', '铜陵'),
    '林平纸业': ('安徽省萧县林平纸业有限公司', '宿州'),
    '信义光伏': ('安徽信义光伏玻璃有限公司', '芜湖'),
    '长江钢铁': ('安徽长江钢铁股份有限公司', '马鞍山'),
    '马钢': ('马鞍山钢铁股份有限公司', '马鞍山'),
    '铜陵有色': ('铜陵有色金属集团股份有限公司', '铜陵'),
    '淮河能源': ('淮河能源控股集团有限责任公司', '淮南'),
    '淮北矿业': ('淮北矿业（集团）有限责任公司', '淮北'),
    '中安联合': ('中安联合煤化有限责任公司', '淮南'),
    '皖能': ('安徽省皖能股份有限公司', '合肥'),
    '丰原': ('安徽丰原生物技术股份有限公司', '蚌埠'),
    '中粮': ('中粮生物科技股份有限公司', '蚌埠'),
    '古井': ('安徽古井集团有限责任公司', '亳州'),
    '司尔特': ('司尔特肥业股份有限公司', '宣城'),
    '圣戈班': ('圣戈班管道系统有限公司', '马鞍山'),
    '中煤六安': ('中煤六安能源有限公司', '六安'),
    '钱营孜': ('安徽钱营孜发电有限公司', '宿州'),
    '淮南矿业': ('淮南矿业（集团）有限责任公司', '淮南'),
    '潘集电厂': ('淮南矿业（集团）有限责任公司', '淮南'),
    '合肥新能': ('合肥热电集团有限公司', '合肥'),
    '光大': ('光大生物能源（萧县）有限公司', '宿州'),
    '凯迪': ('凯迪生态环境科技股份有限公司', '亳州'),
    '鑫皖': ('鑫皖新能源有限公司', '合肥'),
    '皖江江南': ('皖江江南新兴产业集中区管委会', '池州'),
}


def fetch(url, timeout=30, referer=None):
    cmd = ['curl', '-sk', '-m', str(timeout), url, '-H', 'User-Agent: ' + UA]
    if referer:
        cmd += ['-H', 'Referer: ' + referer]
    r = subprocess.run(cmd, capture_output=True)
    return r.stdout.decode('utf-8', 'ignore')


def guess_city(text):
    """只在标题里找城市名 / 县市名。

    ⚠ 绝不能用正文兜底：安徽每篇正文页脚都写「地址：合肥市中山路1号」（省发改委自己的
    地址），一兜底就全归合肥——和浙江那次「杭州市西湖区省府路8号」是同一个坑。
    """
    for c in CITIES_AH:
        if c in text:
            return c
    for k, v in COUNTY2CITY.items():
        if k in text:
            return v
    return ''


def html_text(h):
    """返回 (分行文本, 去空白紧凑文本)。

    紧凑文本是必须的：安徽站的正文把每个数字段裹进 span，渲染出来是
    「2408- 34 0 222 - 0 4 -0 2 - 554533」「4900 万元」，不压掉空白正则全废。
    """
    t = re.sub(r'<script[\s\S]*?</script>', ' ', h)
    t = re.sub(r'<style[\s\S]*?</style>', ' ', t)
    t = re.sub(r'<[^>]+>', '\n', t)
    t = html_mod.unescape(t).replace('&nbsp;', ' ').replace('&amp;', '&')
    lines = [l.strip() for l in t.split('\n') if l.strip()]
    return '\n'.join(lines), re.sub(r'\s+', '', ''.join(lines))


def list_page(cat_id, page, kw=''):
    q = ('labelName=publicInfoList&siteId=49631471&organId=7011&pageSize=20'
         '&pageIndex=%d&isDate=true&dateFormat=yyyy-MM-dd&length=50&type=4'
         '&action=list&result=&isJson=true&keyWords=%s&isRel=true&catIds=%s'
         % (page, kw, cat_id))
    try:
        d = json.loads(fetch(LABEL + '?' + q, referer=SITE + '/'))
    except Exception:
        return []
    return [(r.get('contentId'), (r.get('title') or '').strip(),
             (r.get('publishDate') or '')[:10], r.get('link', ''))
            for r in (d.get('data') or [])]


def clean_title(t):
    return TITLE_PREFIX.sub('', re.sub(r'\s+', '', t))


def pick_company(title):
    """从标题里摘业主名（取最长的那个全称）。"""
    best = ''
    for m in CO_PAT.finditer(clean_title(title)):
        nm = m.group(1).strip('、，,。:： ')
        nm = re.sub(r'^(?:同意|核准|关于|原则同意|新建|建设|由|将)', '', nm)
        if len(nm) < 4 or NOT_CO.search(nm):
            continue
        if len(nm) > len(best):
            best = nm
    return best


def pick_cap(flat, title):
    """装机：标题优先，其次正文里挨着「装机/新建/机组」的那个，最后才取正文第一个。"""
    for src in (re.sub(r'\s+', '', title), flat):
        m = CAP_CTX.search(src)
        if m:
            return m.group(1) + m.group(2)
    m = CAP_PAT.search(re.sub(r'\s+', '', title))
    if m:
        return m.group(1) + m.group(2)
    m = CAP_PAT.search(flat)
    if m:
        return m.group(1) + m.group(2)
    return ''


def parse_detail(cid, title, date, link, cat):
    h = fetch(link, referer=SITE + '/')
    if not h or len(h) < 2000:
        return None
    lines, flat = html_text(h)

    # 正文：详情页「来源：」之后才是正文，之前是元数据表 + 导航
    i = lines.find('来源：')
    body = lines[i:] if i > 0 else lines
    for stop in ('扫一扫在手机打开当前页', '文件下载', '友情链接', '网站地图', '返回顶部'):
        j = body.find(stop)
        if j > 60:
            body = body[:j]
    src = ''
    m = re.search(r'来源：\s*([^\n]{2,30})', lines)
    if m:
        src = m.group(1).strip()

    doc = ''
    m = re.search(r'(皖发改[^\s，,。；;）)]{2,30}号)', flat)
    if m:
        doc = m.group(1)

    # 业主：正文「项目建设单位：XXX」最准，其次抬头「XXX公司 ：」，最后才从标题抠
    buyer = ''
    m = BUILD_ORG.search(flat)
    if m and not NOT_CO.search(m.group(1)):
        buyer = m.group(1).strip()
    if not buyer:
        m = HEAD_CO.search(body[:400])
        if m and not NOT_CO.search(m.group(1)):
            buyer = m.group(1).strip()
    if not buyer:
        buyer = pick_company(title)
    if not buyer:
        for k, (full, _ct) in ALIAS.items():
            if k in title:
                buyer = full
                break
    # 业主名清理：
    # ① 「安徽东至经济开发区南部-安徽华尔泰化工股份有限公司」这种把园区名粘在前面的，
    #    按分隔符切一刀，取最后一段带公司后缀的
    if buyer and len(buyer) > 12 and re.search(r'[-—–/]', buyer):
        for seg in re.split(r'[-—–/]', buyer)[::-1]:
            if re.search(r'(?:股份|有限责任|有限公司|集团公司|总公司|总厂|发电厂)$', seg) \
                    and len(seg) >= 6:
                buyer = seg
                break
    # ② 「能源有限公司」这种半截名字（正文抬头被截断），回正文里再找一个更长的
    if len(buyer) < 7:
        for m in CO_PAT.finditer(flat[:600]):
            nm = m.group(1).strip('、，,。:： ')
            if len(nm) >= 7 and not NOT_CO.search(nm) and len(nm) > len(buyer):
                buyer = nm
                break

    # 城市：正文「建设地点」→ 标题地名 → 项目代码区划码 → 业主别名库
    city, code = '', ''
    m = CODE_PAT.search(flat)
    if m:
        code = m.group(0)
    m = LOC_PAT.search(flat)
    if m:
        for src in (m.group(1), m.group(0)):
            c = guess_city(src)
            if c:
                city = c
                break
    if not city:
        city = guess_city(title)
    if not city and code:
        city = AREA2CITY.get(code.split('-')[1][:4], '')
    if not city and buyer:
        for k, (full, ct) in ALIAS.items():
            if k in buyer:
                city = ct
                break

    amt, amt_txt = None, ''
    m = AMT_PAT.search(flat)
    if m:
        amt = float(m.group(1)) * (1e8 if m.group(2) == '亿元' else 1e4)
        amt_txt = m.group(1) + m.group(2)

    cap = pick_cap(flat, title)
    snip = re.sub(r'^来源：[^ ]*\s*', '', re.sub(r'\s+', ' ', body)).strip()[:340]
    snip = re.sub(r'^(?:浏览量|分享)\s*[:：]\s*', '', snip)   # 详情页框架词，没信息量
    snip = re.sub(r'浏览量\s*[:：]\s*分享\s*[:：]\s*', '', snip)
    # ⚠ make_rec() 只搬运固定字段，cap（装机）不在其中，会静默丢失。
    #   所以把装机/项目代码直接拼进摘要前缀，页面上才看得到——这俩是判断项目量级的关键。
    head = ''
    if cap:
        head += '装机 %s；' % cap
    if code:
        head += '项目代码 %s；' % code
    snip = (head + snip)[:420]
    return {
        't': re.sub(r'\s+', '', title),
        'rg': '安徽',
        'city': city,
        'buyer': buyer,
        'amt': amt,
        'amtTxt': amt_txt,
        'd': date,
        'dl': '',
        'p': '安徽省发改委·' + cat,
        'url': link,
        'snip': ('安徽省发改委%s：%s' % (cat, snip))[:520],
        'mode': '',
        'early': '热电规划',
        'expect': '',
        'cap': cap,
        'code': code,
        'doc': doc,
        'files': [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--pages', type=int, default=0, help='覆盖 CATS 里的翻页数')
    a = ap.parse_args()

    seen, rows = set(), []
    for cat, cid, pgs in CATS:
        pgs = a.pages or pgs
        for p in range(1, pgs + 1):
            items = list_page(cid, p)
            if not items:
                break
            for c_, t, d, link in items:
                if not t or not link or c_ in seen:
                    continue
                if SKIP.search(t) or not WANT.search(t):
                    continue
                seen.add(c_)
                rows.append((c_, t, d, link, cat))
            if len(items) < 20:
                break
    print('列表命中 %d 条，开始抓详情页…' % len(rows))

    out = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(parse_detail, *r) for r in rows]
        for i, f in enumerate(futs):
            try:
                r = f.result()
            except Exception as e:
                print('  ✗ %s' % e)
                r = None
            if r:
                out.append(r)

    # 去重：① 同 URL ② 同「业主+项目标题」（省里常就同一项目重复发文）
    ded, k1, k2 = [], set(), set()
    for r in sorted(out, key=lambda x: x['d'], reverse=True):
        a1 = r['url']
        a2 = (r['buyer'], r['t'])
        if a1 in k1 or a2 in k2:
            continue
        k1.add(a1)
        k2.add(a2)
        ded.append(r)

    fn = os.path.join(EARLY_DIR, 'ah-nygs-latest.json')
    os.makedirs(EARLY_DIR, exist_ok=True)
    if not a.dry:
        json.dump(ded, open(fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n写出 %d 条%s → %s' % (len(ded), '（--dry 未写盘）' if a.dry else '', fn))
    for r in ded:
        print('  %s | %-4s | %-26s | %-9s | %-9s | %s' %
              (r['d'], r['city'] or '-', (r['buyer'] or '?')[:26],
               r['cap'] or '-', r['amtTxt'] or '-', r['t'][:46]))


if __name__ == '__main__':
    main()
