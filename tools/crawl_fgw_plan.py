# -*- coding: utf-8 -*-
"""省发改委「十五五」热电联产规划 / 资源综合利用发电规划**批复**采集器（2026-10-27 新增）。

为什么做这个
────────────
用户投喂了两份盐城规划 PDF（热电联产 2026-2030、资源综合利用发电 2026-2030），
说「这类文件里也会存在有关热电联产项目的情况，重点地市的可以收集筛选下」。
实测这类规划 PDF 的含金量**高于招标公告**：
  · 业主名字、装机规模、投资金额、投运年份、技术方案全都写在里面
  · 项目 2027-2029 才投运，现在正是提前 1~3 年拜访的窗口

但逐市找 PDF 太慢，所以主路径换成**省发改委批复**：
各市的这两个规划都要报省发改委批复，批复是 **HTML 纯文本**（不用解析 PDF），
而且正文里**直接点名企业和项目**，例如南京那篇：
  「原则同意南京南钢产业发展有限公司利用余气、余热资源建设资源综合利用发电（热电）项目」
  「原则同意上海梅山钢铁股份有限公司利用余气资源建设…」
  「原则同意中国石化集团南京化学工业有限公司、中国石化扬子石油化工有限公司利用余热资源…」

江苏省站实测（2026-10-27）
────────────────────────
  · 栏目：省发改委「信息公开 > 法定主动公开内容 > 其他文件」 columnid=51012
  · 列表走 /module/web/jpage/dataproxy.jsp?startrecord=1&endrecord=90&...&columnid=51012
    （⚠ col/col51012/index.html 只有最新 45 条且 index_1.html 是 404，翻页必须走 dataproxy）
  · 详情页 /art/年/月/日/art_51012_xxx.html，curl 直抓即可，正文在 <!--begin--> 附近
  · 一页就命中：无锡「十五五」资源综合利用发电规划、南京、盐城市区热电联产、盐城资源综合利用

产出：raw/early/plan-fgw-<日期>.json，early='热电规划'
（build_data.py 的 EARLY_SRC 已把 '热电规划' 映射为「立项公示」层，无需再改映射）

用法：python crawl_fgw_plan.py [--dry]
"""
import argparse
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
ROOT = os.path.dirname(os.path.abspath(__file__))
EARLY_DIR = os.path.join(ROOT, 'raw', 'early')

# (省份, 站点名, 列表接口模板, 栏目首页, 解析器key, 翻页数)
# 列表模板里 {a}/{b} 分别是 startrecord / endrecord（浙江源不支持翻页，填 0）
FEEDS = [
    ('江苏', '江苏省发改委·规划批复',
     'https://fzggw.jiangsu.gov.cn/module/web/jpage/dataproxy.jsp'
     '?startrecord={a}&endrecord={b}&perpage=30&col=1&appid=1&webid=3'
     '&path=%2F&columnid=51012&unitid=394686&webname=&permissiontype=0',
     'https://fzggw.jiangsu.gov.cn/col/col51012/index.html', 'js', 3),
    # 浙江不发「批复」，只把这批规划的**报批稿公示**出来（省发改委「调查征集」栏目）。
    # 栏目页是空壳，列表由 JS 异步拉；真实接口是 jpaas-publish-server/front/page/build/unit
    # （浏览器渲染时抓到的 XHR，实测 curl 可直接调，返回 JSON，列表在 data.html 里）。
    # ⚠ 分页参数试过 pageIndex/pageNo/currentPage/page 都无效，只能拿到最新 15 条——
    #   好在这是「征求意见」栏目，发文频率低，15 条够覆盖近几个月。
    ('浙江', '浙江省发改委·调查征集（规划公示）',
     'https://fzggw.zj.gov.cn/api-gateway/jpaas-publish-server/front/page/build/unit'
     '?parseType=bulidstatic&webId=3185&tplSetId=o0YcVHHq5vWtr3uiCp4SY&pageType=column'
     '&tagId=%E4%BF%A1%E6%81%AF%E5%88%97%E8%A1%A8&editType=null&pageId=1599567',
     'https://fzggw.zj.gov.cn/col/col1599567/index.html', 'zj', 1),
]

# 只要规划类批复本身（不是配套通知、不是征求意见）
WANT = re.compile(r'热电联产规划|资源综合利用.{0,6}发电规划|供热专项规划|热电联产.{0,8}规划|'
                  r'集中供热.{0,4}规划')
# 明显噪声：废止、评估、培训。
# ⚠ 原来这里还有「征求意见」——浙江全省各县市的热电联产规划**只在征求公众意见这一环公开**
#   （附规划报批稿全文），江苏那边正式批复的正文里才点名企业。把「征求意见」写进 SKIP
#   会把浙江整条线滤成空的，所以去掉。
SKIP = re.compile(r'废止|培训|会议|通报|考核|先进|表彰')

# 企业全称。⚠ 后缀里**不能放单独的「集团」**：否则「中国石化集团南京化学工业有限公司」
# 会在「集团」处提前截断成「原则同意中国石化集团」。只保留「集团公司」这种完整写法。
CO_PAT = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,30}?'
                    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司|总厂|发电厂|公司|厂))')

# 句子里的引导词/片区名——先把它们抹掉，再匹配企业名，避免前缀被卷进来
LEAD_NOISE = re.compile(r'原则同意|同意|支持|核准|以现有|现有|由|将已备案的|已备案的|'
                        r'项目建成后关停|项目建成后|关停|在整合关停|整合关停|及其控股的|控股的|'
                        r'[东南西北中]部?供热片区|供热片区|规划期内|规划期')
# 匹配到之后仍可能粘在开头的连词/残词，反复剥离
HEAD_NOISE = re.compile(r'^(?:和|与|及其|或|、|，|,|以|由|将|在|的|是|为|作为|依托|依靠|支持|同意)')
# 明显不是企业名的
NOT_CO = re.compile(r'自备|发展改革委|发改委|人民政府|管委会|供热片区|热电厂$|办公室|委员会')
# 正文里点名项目的句子标志
AGREE_PAT = re.compile(r'(?:原则)?同意|支持|核准')
KIND_PAT = re.compile(r'余热|余气|余压|煤气|生物质|热电联产|资源综合利用|集中供热|背压|抽背')

CITIES = {
    '江苏': ['南京', '无锡', '徐州', '常州', '苏州', '南通', '连云港', '淮安', '盐城',
             '扬州', '镇江', '泰州', '宿迁'],
    '浙江': ['杭州', '宁波', '温州', '嘉兴', '湖州', '绍兴', '金华', '衢州', '舟山',
             '台州', '丽水'],
    '安徽': ['合肥', '芜湖', '蚌埠', '淮南', '马鞍山', '淮北', '铜陵', '安庆', '黄山',
             '滁州', '阜阳', '宿州', '六安', '亳州', '池州', '宣城'],
    '上海': ['上海'],
}


def fetch(url, timeout=30, referer=None):
    cmd = ['curl', '-sk', '-m', str(timeout), url, '-H', 'User-Agent: ' + UA]
    if referer:
        cmd += ['-H', 'Referer: ' + referer]
    r = subprocess.run(cmd, capture_output=True)
    return r.stdout.decode('utf-8', 'ignore')


# 县级市/县 → 所属设区市。批复标题常只写「江阴热电」「丹阳龙江钢铁」，
# 不出现设区市名，靠这层映射归位，免得 city 留空。
COUNTY2CITY = {
    '江阴': '无锡', '宜兴': '无锡',
    '张家港': '苏州', '常熟': '苏州', '昆山': '苏州', '太仓': '苏州',
    '溧阳': '常州', '金坛': '常州',
    '丹阳': '镇江', '扬中': '镇江', '句容': '镇江',
    '兴化': '泰州', '泰兴': '泰州', '靖江': '泰州',
    '如皋': '南通', '海门': '南通', '启东': '南通', '如东': '南通',
    '东台': '盐城', '射阳': '盐城', '阜宁': '盐城', '建湖': '盐城', '滨海': '盐城', '响水': '盐城',
    '沛县': '徐州', '丰县': '徐州', '邳州': '徐州', '新沂': '徐州', '睢宁': '徐州',
    '东海': '连云港', '灌云': '连云港', '灌南': '连云港',
    '涟水': '淮安', '盱眙': '淮安', '金湖': '淮安', '洪泽': '淮安',
    '宝应': '扬州', '高邮': '扬州', '仪征': '扬州',
    '天长': '滁州', '宁国': '宣城', '广德': '宣城', '桐城': '安庆', '无为': '芜湖',
    '慈溪': '宁波', '余姚': '宁波', '象山': '宁波', '宁海': '宁波',
    '海宁': '嘉兴', '平湖': '嘉兴', '桐乡': '嘉兴', '嘉善': '嘉兴', '海盐': '嘉兴',
    '诸暨': '绍兴', '上虞': '绍兴', '嵊州': '绍兴',
    '温岭': '台州', '玉环': '台州', '临海': '台州',
    '乐清': '温州', '瑞安': '温州', '平阳': '温州',
    '义乌': '金华', '东阳': '金华', '永康': '金华', '兰溪': '金华',
    '长兴': '湖州', '德清': '湖州', '安吉': '湖州',
    # 浙江县市（省发改委公示只写「常山县」「江山市」，设区市名根本不出现）
    '常山': '衢州', '江山': '衢州', '龙游': '衢州', '开化': '衢州',
    '婺城': '金华', '金东': '金华', '浦江': '金华', '武义': '金华',
    '淳安': '杭州', '桐庐': '杭州', '建德': '杭州', '临安': '杭州',
    '新昌': '绍兴', '天台': '台州', '仙居': '台州', '三门': '台州',
    '永嘉': '温州', '苍南': '温州', '文成': '温州', '泰顺': '温州',
    '岱山': '舟山', '嵊泗': '舟山', '青田': '丽水', '缙云': '丽水',
    '松阳': '丽水', '遂昌': '丽水', '云和': '丽水', '龙泉': '丽水',
}


def guess_city_in(rg, text):
    """严格版：只在**指定文本**里找城市/县市名，不做正文兜底。

    为什么要有这个：浙江公示的正文里一定会写「通信地址：杭州市西湖区省府路8号」，
    那是省发改委自己的地址。用正文兜底会把常山、江山全都归到杭州去。
    """
    for c in CITIES.get(rg, []):
        if c in text:
            return c
    for k, v in COUNTY2CITY.items():
        if k in text:
            return v
    return ''


def guess_city(rg, text):
    for c in CITIES.get(rg, []):
        if c in text:
            return c
    for k, v in COUNTY2CITY.items():
        if k in text:
            return v
    return ''


def html_text(html):
    t = re.sub(r'<script[\s\S]*?</script>', ' ', html)
    t = re.sub(r'<style[\s\S]*?</style>', ' ', t)
    t = re.sub(r'<[^>]+>', '\n', t)
    t = (t.replace('&nbsp;', ' ').replace('&amp;', '&')
          .replace('&ldquo;', '“').replace('&rdquo;', '”')
          .replace('&mdash;', '—').replace('&middot;', '·'))
    return t


def parse_js(html, rg):
    """江苏：从 dataproxy 返回的片段里抽 /art/年/月/日/art_51012_xxx.html + 标题。"""
    out, seen = [], set()
    for m in re.finditer(
            r'href="(/art/(\d{4})/(\d{1,2})/(\d{1,2})/art_\d+_(\d+)\.html)"'
            r'[^>]*>([\s\S]{0,200}?)</a>', html):
        href, y, mo, da, aid, raw = m.groups()
        t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', raw)).strip()
        if len(t) < 8 or len(t) > 120:
            continue
        if aid in seen:
            continue
        seen.add(aid)
        out.append({'t': t, 'd': '%s-%02d-%02d' % (y, int(mo), int(da)), 'aid': aid,
                    'url': 'https://fzggw.jiangsu.gov.cn' + href})
    return out


def parse_zj(raw, rg):
    """浙江：接口返回的是 JSON，列表 HTML 在 data.html 里。"""
    try:
        import json as _json
        d = _json.loads(raw)
        html = (d.get('data') or {}).get('html') or ''
    except Exception:
        html = raw
    out, seen = [], set()
    # <a ... href="/col/col1599567/art/2026/art_xxx.html" ... title="标题">
    for m in re.finditer(r'<a\b[^>]*?>[\s\S]{0,300}?</a>', html):
        tag = m.group(0)
        hm = re.search(r'href="(/col/col\d+/art/(\d{4})/art_[0-9a-f]+\.html)"', tag)
        if not hm:
            continue
        href, year = hm.group(1), hm.group(2)
        tm = re.search(r'title="([^"]*)"', tag)
        t = (tm.group(1) if tm else '') or re.sub(r'<[^>]+>', '', tag)
        t = re.sub(r'\s+', ' ', t).strip()
        if len(t) < 8 or len(t) > 120 or href in seen:
            continue
        seen.add(href)
        # 浙江这条接口不给具体日期，只有年份；详情页正文里会有「发布时间」，交给 parse_detail 补
        out.append({'t': t, 'd': year + '-01-01', 'aid': href.rsplit('/', 1)[-1][:24],
                    'url': 'https://fzggw.zj.gov.cn' + href})
    return out


PARSERS = {'js': parse_js, 'zj': parse_zj}


def crawl_list(rg, name, api_tpl, home, pk, pages=3):
    """翻页抓列表，只留规划类批复。"""
    rows, seen = [], set()
    for p in range(max(1, pages)):
        a, b = p * 90 + 1, (p + 1) * 90
        html = fetch(api_tpl.format(a=a, b=b), referer=home)
        if len(html) < 2000:
            print('  %s 第%d页抓取失败（%d 字节）' % (name, p + 1, len(html)))
            break
        got = PARSERS[pk](html, rg)
        if not got:
            break
        for x in got:
            t = x['t']
            if not WANT.search(t) or SKIP.search(t):
                continue
            if t[:34] in seen:
                continue
            seen.add(t[:34])
            rows.append(x)
    return rows


def parse_detail(rg, name, x):
    """抓批复正文，抽出被点名的企业 + 项目方向。"""
    html = fetch(x['url'])
    if len(html) < 2000:
        return []
    txt = html_text(html)

    # 发文日期：页面元信息里的「发文日期: 2026-08-10」
    d = x['d']
    m = re.search(r'发文日期[:：]\s*(\d{4})-(\d{1,2})-(\d{1,2})', txt)
    if m:
        d = '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))

    # 正文主体：从「现就有关事项批复如下」或第一个「原则同意」开始
    body = txt
    m = re.search(r'(批复如下|有关事项通知如下|经研究)[：:]?', txt)
    if m:
        body = txt[m.end():]
    body = re.sub(r'begin-->|end-->|\s+', ' ', body)

    title = x['t']
    city = guess_city(rg, title) or guess_city(rg, body)
    if '热电联产' in title:
        kind = '热电联产'
    elif '资源综合利用' in title:
        kind = '资源综合利用发电'
    else:
        kind = '供热'

    out, seen_co = [], set()
    # 逐句扫描，找含「同意/支持」且含企业名的句子
    for sent in re.split(r'[。；\n]', body):
        if len(sent) < 10 or not AGREE_PAT.search(sent):
            continue
        if not KIND_PAT.search(sent):
            continue
        # 先抹掉引导词和片区名，剩下的才是干净的企业名上下文
        s2 = LEAD_NOISE.sub(' ', sent)
        cos = CO_PAT.findall(s2)
        if not cos:
            continue
        for co in cos:
            co = co.strip()
            for _ in range(4):                    # 反复剥离粘在开头的连词
                co2 = HEAD_NOISE.sub('', co).strip()
                if co2 == co:
                    break
                co = co2
            if len(co) < 5 or co in seen_co:
                continue
            if NOT_CO.search(co):                 # 自备热电厂、XX发改委…不是业主
                continue
            seen_co.add(co)
            snip = re.sub(r'\s+', ' ', sent).strip()
            if len(snip) > 160:
                snip = snip[:160]
            out.append({
                't': '%s%s项目' % (co, kind),
                'rg': rg, 'city': city, 'buyer': co,
                'amt': None, 'amtTxt': '', 'd': d, 'dl': '',
                'p': name, 'url': x['url'],
                'snip': '省发改委规划批复点名（%s）。原文：%s' % (title[:28], snip),
                'mode': '', 'early': '热电规划', 'expect': '',
            })
    return out


def parse_detail_zj(rg, name, x):
    """浙江：正文只有「某县发改局编制完成、上报我委审批」，**不点名企业**——
    真正的项目清单在附件规划报批稿 PDF 里。所以这里只产一条「区域规划」线索：
    告诉营销经理哪个县市在做热电联产规划、附件在哪下载。"""
    html = fetch(x['url'])
    if len(html) < 2000:
        return []
    txt = re.sub(r'\s+', ' ', html_text(html))

    d = x['d']
    m = re.search(r'(?:发布|发文)日期[:：]\s*(\d{4})-(\d{1,2})-(\d{1,2})', txt)
    if m:
        d = '%s-%02d-%02d' % (m.group(1), int(m.group(2)), int(m.group(3)))

    m = re.search(r'《([^》]{4,80})》', x['t'])
    pname = m.group(1) if m else re.sub(r'关于公开征求|意见的通知', '', x['t']).strip('《》 ')
    if '热电联产' in pname or '集中供热' in pname:
        kind = '热电联产'
    elif '资源综合利用' in pname:
        kind = '资源综合利用发电'
    else:
        kind = '供热'
    # ⚠ 只从规划名推断城市。正文里那句「杭州市西湖区省府路8号」是省发改委自己的
    #   通信地址，拿正文兜底会把常山、江山全归到杭州去。
    city = guess_city_in(rg, pname)

    # 编制/上报单位：正文里「已由 XX 发展改革局编制完成」
    org = ''
    m = re.search(r'已由([^，。；]{2,30}?)(?:编制完成|组织编制|编制)', txt)
    if m:
        org = m.group(1).strip()

    # 附件（规划报批稿 PDF）
    files, seen_f = [], set()
    for fm in re.finditer(
            r'href="(/api-gateway/jpaas-web-server/front/document/download\?[^"]*)"', html):
        u = fm.group(1).replace('&amp;', '&')
        nm = ''
        qm = re.search(r'fileName=([^&]*)', u)
        if qm:
            try:
                import urllib.parse as _up
                nm = _up.unquote(qm.group(1))
            except Exception:
                nm = qm.group(1)
        # 同一份 PDF 在页面里常常既挂在「附件」区又挂一份隐藏链接，按 URL 去重
        key = re.sub(r'&fileName=.*$', '', u) or u
        if key in seen_f:
            continue
        seen_f.add(key)
        files.append({'n': nm or '规划报批稿', 'u': 'https://fzggw.zj.gov.cn' + u})

    # 公示期
    pub = ''
    m = re.search(r'公开征求意见时间为\s*([^。；]{4,60})', txt)
    if m:
        pub = '公示期 %s' % m.group(1).strip()

    snip = '浙江省发改委%s规划公示' % kind
    if org:
        snip += '：已由%s编制完成并上报审批' % org
    if pub:
        snip += '；%s' % pub
    if files:
        snip += '。附件含规划报批稿全文（热源点布局、装机方案、项目清单），需下载 PDF 查看具体企业项目'
    # 只摘正文第一句（「《XX规划》已由XX编制完成，并上报我委审批…」），
    # 别把整页导航（当前位置：首页 > 政务公开 > …）粘进来。
    m = re.search(r'《[^》]{4,80}》[^。]{0,80}。', txt)
    if m:
        snip += '。原文：%s' % re.sub(r'\s+', ' ', m.group(0))

    return [{
        't': pname, 'rg': rg, 'city': city, 'buyer': '',
        'amt': None, 'amtTxt': '', 'd': d, 'dl': '',
        'p': name, 'url': x['url'], 'snip': snip[:400],
        'mode': '', 'early': '热电规划', 'expect': '', 'files': files,
    }]


DETAIL = {'js': parse_detail, 'zj': parse_detail_zj}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    allrows, seent = [], set()
    for rg, name, api_tpl, home, pk, pages in FEEDS:
        print('[%s] %s' % (rg, name))
        rows = crawl_list(rg, name, api_tpl, home, pk, pages)
        print('  列表命中规划批复: %d 篇' % len(rows))
        fn = DETAIL[pk]
        with ThreadPoolExecutor(max_workers=4) as ex:
            for got in ex.map(lambda x: fn(rg, name, x), rows):
                for r in got:
                    k = (r['buyer'], r['t'])
                    if k in seent:
                        continue
                    seent.add(k)
                    allrows.append(r)
    # 同一家企业可能被多篇批复点名（如江阴热电出现 3 次），按 buyer 去重，留最新那篇。
    # 浙江那批没有 buyer（正文不点名企业），改用标题做键，否则会全被合并成 1 条。
    by_buyer = {}
    for r in allrows:
        b = r['buyer'] or ('T:' + r['t'])
        if b not in by_buyer or r['d'] > by_buyer[b]['d']:
            by_buyer[b] = r
    allrows = sorted(by_buyer.values(), key=lambda x: x['d'], reverse=True)

    for r in allrows:
        print('  · %s | %-4s | %-28s | %s' % (r['d'], r['city'], r['buyer'][:28], r['t'][:40]))

    print('\n合计 %d 条（已按企业去重）' % len(allrows))
    if a.dry or not allrows:
        print('--dry，未写盘' if a.dry else '无数据，未写盘')
        return

    os.makedirs(EARLY_DIR, exist_ok=True)
    # ⚠ 固定文件名、每次覆盖：线上每天跑一次，用日期做文件名会在 raw/early/ 下
    # 堆出一串同名内容的文件（去重虽能兜住，但白白占仓库）。所以先清旧、再写新。
    for fn0 in os.listdir(EARLY_DIR):
        if fn0.startswith('plan-fgw-2') and fn0.endswith('.json'):
            try:
                os.remove(os.path.join(EARLY_DIR, fn0))
            except OSError:
                pass
    fn = os.path.join(EARLY_DIR, 'plan-fgw-latest.json')
    json.dump(allrows, open(fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('写入 %s' % fn)


if __name__ == '__main__':
    main()
