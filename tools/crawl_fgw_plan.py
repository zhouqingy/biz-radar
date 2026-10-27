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

# (省份, 站点名, 列表接口模板, 栏目首页, 解析器key)
# 列表模板里 {a}/{b} 分别是 startrecord / endrecord
FEEDS = [
    ('江苏', '江苏省发改委·规划批复',
     'https://fzggw.jiangsu.gov.cn/module/web/jpage/dataproxy.jsp'
     '?startrecord={a}&endrecord={b}&perpage=30&col=1&appid=1&webid=3'
     '&path=%2F&columnid=51012&unitid=394686&webname=&permissiontype=0',
     'https://fzggw.jiangsu.gov.cn/col/col51012/index.html', 'js'),
]

# 只要规划类批复本身（不是配套通知、不是征求意见）
WANT = re.compile(r'热电联产规划|资源综合利用.{0,6}发电规划|供热专项规划|热电联产.{0,8}规划')
# 明显噪声：征求意见、废止、评估、培训
SKIP = re.compile(r'征求意见|废止|培训|会议|通报|考核|先进|表彰')

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
}


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


PARSERS = {'js': parse_js}


def crawl_list(rg, name, api_tpl, home, pk, pages=3):
    """翻页抓列表，只留规划类批复。"""
    rows, seen = [], set()
    for p in range(pages):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    allrows, seent = [], set()
    for rg, name, api_tpl, home, pk in FEEDS:
        print('[%s] %s' % (rg, name))
        rows = crawl_list(rg, name, api_tpl, home, pk)
        print('  列表命中规划批复: %d 篇' % len(rows))
        with ThreadPoolExecutor(max_workers=4) as ex:
            for got in ex.map(lambda x: parse_detail(rg, name, x), rows):
                for r in got:
                    k = (r['buyer'], r['t'])
                    if k in seent:
                        continue
                    seent.add(k)
                    allrows.append(r)
    # 同一家企业可能被多篇批复点名（如江阴热电出现 3 次），按 buyer 去重，留最新那篇
    by_buyer = {}
    for r in allrows:
        b = r['buyer']
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
    import datetime
    fn = os.path.join(EARLY_DIR, 'plan-fgw-%s.json' % datetime.date.today().isoformat())
    json.dump(allrows, open(fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('写入 %s' % fn)


if __name__ == '__main__':
    main()
