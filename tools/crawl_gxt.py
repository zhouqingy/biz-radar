# -*- coding: utf-8 -*-
"""省工信厅「技改 / 制造强省 / 产能置换」名单采集器（2026-10-27 新增）。

为什么做这个
────────────
用户看到安徽省工信厅「2026年制造强省建设系列政策拟支持项目（第一批）公示」，
说「这个公布的信息很有用，其他省的有没有」。
这类名单的定位是**立项线索层**（政府已批 / 拟支持，企业确定要建，还没挂招标公告），
比业务信号实、比能投的标早，是营销经理提前 3~9 个月介入的最好时机。

两省实测（2026-10-27，均为静态页 curl 可直抓，**不需要浏览器**）：
  · 江苏 /col/col6281/ 公告公示 —— 产能置换方案公示（标题就含企业+项目：南钢 3#高炉、
    永钢 3#高炉、中天钢铁绿钢）、各批次「制造强省专项资金拟安排项目」、绿色工厂名单
  · 安徽 /sy/wjgg/ 文件公告 —— 链接是绝对 URL、标题在 title 属性、日期在 span.date
    （⚠ 别用 `<a>文本` 抓，文本在内部 span，会抓空）

只收「结果类」公示（名单已出、方案已公示），不收「组织申报/征集通知」（那是过程，还不知道谁中）。
名单类附件（PDF/Excel）本期不解析 —— 用户定了「先收标题级」。

产出：raw/early/gxt-<日期>.json，early='工信厅名单'（→ build_data 映射为立项公示）。
江苏产能置换类会从标题拆出 buyer（企业全称）。

用法：python crawl_gxt.py [--dry]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')
ROOT = os.path.dirname(os.path.abspath(__file__))
EARLY_DIR = os.path.join(ROOT, 'raw', 'early')

# (站点名, 列表页, 省份, 解析器)
FEEDS = [
    ('江苏省工信厅·公告公示', 'https://gxt.jiangsu.gov.cn/col/col6281/index.html', '江苏', 'js'),
    ('安徽省工信厅·文件公告', 'https://jx.ah.gov.cn/sy/wjgg/index.html', '安徽', 'ah'),
]

# 结果类名单/方案公示才收录（拟支持、拟安排、名单、入围、产能置换、认定）
WANT = re.compile(r'拟支持|拟安排|拟认定|入围名单|入选名单|名单公示|产能置换|'
                  r'技术改造.*项目|技改.*项目|节能降碳|绿色工厂|绿色制造|智能工厂|'
                  r'制造强省|增资扩产|转型升级.*项目|示范项目')
# 过程类/噪声一律丢弃（申报通知、大赛、职称、征求意见、税收优惠…跟「谁要建」无关）
SKIP = re.compile(r'组织申报|组织推荐|申报工作|征集|技能大赛|职业技能|工艺美术|职称|'
                  r'资格评审|征求意见|增值税|加计抵减|专精特新|揭榜挂帅|典型案例|'
                  r'行政处罚|裁量|服务体系|试点县|试点城市|动态管理|评估工作|'
                  r'融资对接|对接会|研修班|培训|博士后|先进个人|先进集体')

# 从标题拆企业（产能置换/技改类）：「关于{企业}{项目}产能置换方案…」
OWNER_PAT = re.compile(r'关于\s*([一-龥（）()]{4,30}?(?:有限公司|有限责任公司|集团|股份公司|股份有限公司|厂))')


def fetch(url, timeout=25):
    r = subprocess.run(['curl', '-sk', '-m', str(timeout), url, '-H', 'User-Agent: ' + UA],
                       capture_output=True)
    return r.stdout.decode('utf-8', 'ignore')


def guess_city(rg, text):
    cities = {
        '江苏': ['南京', '无锡', '徐州', '常州', '苏州', '南通', '连云港', '淮安', '盐城',
                 '扬州', '镇江', '泰州', '宿迁', '江阴', '宜兴', '张家港', '常熟', '昆山'],
        '安徽': ['合肥', '芜湖', '蚌埠', '淮南', '马鞍山', '淮北', '铜陵', '安庆', '黄山',
                 '滁州', '阜阳', '宿州', '六安', '亳州', '池州', '宣城'],
    }
    for c in cities.get(rg, []):
        if c in text:
            return c
    return ''


def parse_js(html, rg):
    """江苏：链接 /art/年/月/日/art_6281_xxx.html，标题在 <a> 文本。"""
    out = []
    for m in re.finditer(r'<a[^>]+href="(/art/(\d{4})/(\d{1,2})/(\d{1,2})/(art_6281_\d+\.html))"[^>]*>([\s\S]{0,120}?)</a>', html):
        href, y, mo, da, _f, raw = m.groups()
        t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', raw)).strip()
        if len(t) < 8 or len(t) > 90:
            continue
        d = '%s-%02d-%02d' % (y, int(mo), int(da))
        out.append({'t': t, 'url': 'https://gxt.jiangsu.gov.cn' + href, 'd': d})
    return out


def parse_ah(html, rg):
    """安徽：绝对 URL，标题在 title 属性，日期在后面的 span.date。"""
    out = []
    for m in re.finditer(
            r'<a[^>]+href="(https://jx\.ah\.gov\.cn/sy/wjgg/\d+\.html)"[^>]*title="([^"]+)"[\s\S]{0,400}?class="right date">(\d{4}-\d{2}-\d{2})<', html):
        url, t, d = m.groups()
        t = t.strip()
        if len(t) < 8 or len(t) > 90:
            continue
        out.append({'t': t, 'url': url, 'd': d})
    return out


PARSERS = {'js': parse_js, 'ah': parse_ah}


def crawl_feed(name, url, rg, pk):
    html = fetch(url)
    if len(html) < 3000:
        print('  %s 抓取失败（%d 字节）' % (name, len(html)))
        return []
    rows = PARSERS[pk](html, rg)
    out, seen = [], set()
    for x in rows:
        t = x['t']
        if not WANT.search(t) or SKIP.search(t):
            continue
        key = t[:30]
        if key in seen:
            continue
        seen.add(key)
        buyer = ''
        om = OWNER_PAT.search(t)
        if om:
            buyer = om.group(1).strip('，。 ')
        out.append({
            't': t, 'rg': rg, 'city': guess_city(rg, t), 'buyer': buyer,
            'amt': None, 'amtTxt': '', 'd': x['d'], 'dl': '',
            'p': name, 'url': x['url'],
            'snip': '省工信厅公示（%s）。属立项线索：政府已批/拟支持，企业确定要建，'
                    '尚未挂招标公告，是提前介入时机。名单类详见附件。' % name,
            'mode': '', 'early': '工信厅名单', 'expect': '',
        })
    print('  %s %d 条（列表 %d 条里命中）' % (name, len(out), len(rows)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    print('== 省工信厅技改/制造强省名单 ==')
    items = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        for got in ex.map(lambda f: crawl_feed(*f), FEEDS):
            items.extend(got)

    # 去重（标题前 30 字）
    seen, uniq = set(), []
    for x in items:
        if x['t'][:30] in seen:
            continue
        seen.add(x['t'][:30])
        uniq.append(x)
    print('合计 %d 条（去重后）' % len(uniq))
    for x in uniq[:12]:
        print('   [%s] %s | %s%s' % (x['rg'], x['d'], (x['buyer'] + '｜') if x['buyer'] else '', x['t'][:42]))

    if a.dry:
        print('--dry 不落盘')
        return 0
    os.makedirs(EARLY_DIR, exist_ok=True)
    fp = os.path.join(EARLY_DIR, 'gxt-%s.json' % __import__('time').strftime('%Y-%m-%d'))
    json.dump(uniq, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('✅ 写入 %s' % fp)
    return 0


if __name__ == '__main__':
    sys.exit(main())
