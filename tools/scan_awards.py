# -*- coding: utf-8 -*-
"""
中标结果公告「全文扫描」——按中标单位字段建反向索引（2026-10-26 新增）

用户原话：
  「淮安市洪泽区润湖热力发展有限公司洪泽主城片区热电联产异地项目
    另外这个项目的中标也是华光环保为什么没有找到，豆包上都可以看到项目情况，
    你这不能全都是我自己挨个项目给你你再加上去吧」

根因（三条叠加，逐条实测确认）：
  ① crawl_rival_perf.py 是**按标题搜公司名**（fields='title'，且要求标题含关键词）。
     而真实公告的标题是「洪泽主城片区热电联产异地建设项目EPC工程总承包中标结果公告」——
     标题里根本没有中标单位名字。**中标单位写在正文表格里**。
     所以只要业主不把公司名写进标题，这家公司的业绩就永远搜不到。
     → 这是漏抓的**主因**，跟关键词选得好不好无关。
  ② 每天增量只回补 3 天（--backfill-days 3），2024-11-12 的公告早就过期了。
  ③ 采集只覆盖 浙江/江苏/合肥 三个站的**搜索接口**，没走"中标结果公告"这个栏目。

本办法：反着来 —— 不去搜公司名，而是**把中标结果公告一条条拉下来，
读出「中标单位名称」字段**，建成 `单位名 → [记录]` 的反向索引。
一次扫完某个月的全部中标结果公告，所有中标过的单位都能被反查到，
不需要事先知道「要搜谁」。这正是"不能全靠用户一个个喂"的解法。

用法：
  python3 scan_awards.py --month 2024-11              # 扫 2024 年 11 月
  python3 scan_awards.py --from 2024-01 --to 2026-10  # 扫区间
  python3 scan_awards.py --month 2024-11 --max 200    # 限量（调试）
  python3 scan_awards.py --month 2024-11 --dry        # 只统计条数不抓详情

产出：raw/award_index.json
  {"updated": "...", "records": {"<招标编号|标题>": {t,d,owner,win,amt,url,city,cat,proj}}}
  消费方：build_web.py 把 win 字段灌进 rival_perf 的匹配池；
         前端 rperfRecs 命中时能显示「这条是从中标结果公告正文里读出来的」。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(BASE, 'raw')
OUT = os.path.join(RAW, 'award_index.json')

API = 'https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew'
HOST = 'https://jsggzy.jszwfw.gov.cn'

# 中标结果 / 候选人公示 / 合同 —— 这三类公告里才带中标单位字段
CATS = {
    'result': '003001008',    # 建工 · 中标结果公告
    'cand':   '003001007',    # 建工 · 中标候选人公示
    'contract': '003001011',  # 建工 · 中标合同
}

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


def curl_json(payload, timeout=45):
    r = subprocess.run(
        ['curl', '-sk', '-m', str(timeout), '-X', 'POST', API,
         '-H', 'Content-Type: application/json;charset=utf-8',
         '-H', 'User-Agent: ' + UA,
         '-d', json.dumps(payload, ensure_ascii=False)],
        capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def curl_html(url, timeout=30):
    """省站证书链不完整，必须 -k（否则返回 0 字节，这个坑踩过）"""
    r = subprocess.run(['curl', '-sk', '-m', str(timeout), '-H', 'User-Agent: ' + UA, url],
                       capture_output=True, text=True)
    return r.stdout or ''


def search(cat_num, d1, d2, pn, rn=100, city=''):
    cond = [{"fieldName": "categorynum", "isLike": True, "likeType": 2,
             "equal": cat_num, "equalList": None}]
    p = {
        "token": "", "pn": pn, "rn": rn, "sdt": "", "edt": "", "wd": "",
        "inc_wd": "", "exc_wd": "", "fields": "title", "cnum": "001",
        "sort": '{"infodatepx":"0"}', "ssort": "title", "cl": 200,
        "terminal": "", "highlights": "title", "statistics": None,
        "unionCondition": None, "accuracy": "", "noParticiple": "1", "isBusiness": "1",
        "condition": cond,
        "time": json.dumps([{"fieldName": "infodate", "startTime": d1,
                             "endTime": d2, "index": 1}]),
    }
    res = curl_json(p).get('result') or {}
    return res


def strip_tags(s):
    s = re.sub(r'<script[\s\S]*?</script>', ' ', s or '', flags=re.I)
    s = re.sub(r'<style[\s\S]*?</style>', ' ', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', s).strip()


# 中标单位：两种最常见写法
# 单位名必须长得像单位名：以「公司/院/集团/局/厂/中心/所/大学/研究院」这类结尾。
# 不这么卡的话，正文里「…中标人已经确定」会被抓成单位名「已经确定」（实测踩到过）。
# ⚠ 2026-10-26 踩的坑：字符类里加了（）：把全角括号排掉，
#    结果「华光环保能源（西安）设计研究院有限公司」被截成「华光环保能源」，
#    既不以机构后缀结尾、又被 ok_org 丢掉，洪泽那条 6.22 亿的 EPC 就是这么漏的。
#    单位名里带括号是常态（（西安）（集团）（牵头单位）），绝不能当分隔符。
_RE_WIN1 = re.compile(r'中标单位名称\s*[:：]?\s*([^\s，,。；;]{4,60})')
_RE_WIN2 = re.compile(r'中标人\s*[:：]?\s*([^\s，,。；;]{4,60})')
_RE_OWNER = re.compile(r'建设单位名称\s*[:：]?\s*([^\s，,。；;]{4,60})')
# 单位名合法性：必须带机构后缀，且不能是这些高频误抓词
_ORG_TAIL = ('公司', '集团', '研究院', '设计院', '工程院', '科学院', '设计研究院',
             '局', '厂', '中心', '事务所', '大学', '学院', '研究所', '总队', '大队',
             '合作社', '联合体', '分行', '支行', '医院', '学校')
_BAD_WIN = ('已经确定', '已确定', '如下', '公示', '候选人', '名单', '详见', '附件',
            '无', '待定', '重新招标', '流标', '废标', '以上', '本项目中', '招标人')
_RE_PRICE = re.compile(r'中标(?:价格|价|金额)\s*[:：]?\s*([0-9][0-9,\.]*\s*(?:元|万元|亿元|%))')
_RE_PRICE2 = re.compile(r'投标报价\s*[:：]?\s*([0-9][0-9,\.]*\s*(?:元|万元|亿元))')
_RE_PROJNO = re.compile(r'(?:项目|标段)编号\s*[:：]?\s*([A-Z0-9\-]{8,40})')
_RE_PROJNAME = re.compile(r'(?:项目|标段)名称\s*[:：]?\s*([^\n]{4,120}?)\s*(?:建设单位|标段编号|项目编号|中标)')


def parse_amt(v):
    """统一成「亿元」数字。省站原文是「70794022.25元」这种**元**为单位。"""
    if not v:
        return 0.0
    s = str(v).replace(',', '').strip()
    m = re.match(r'([0-9]+(?:\.[0-9]+)?)\s*(亿元|亿|万元|万|元|%)?', s)
    if not m:
        return 0.0
    n = float(m.group(1))
    u = m.group(2) or ''
    if u in ('亿元', '亿'):
        return n
    if u in ('万元', '万'):
        return n / 1e4
    if u == '%':
        return 0.0          # 费率报价（如材料检测「36.80%」）不折算金额
    return n / 1e8          # 元


_RE_PDF = re.compile(r'(?:href|src)="([^"]*\.pdf)"', re.I)


def pdf_text(url, timeout=40):
    """下载 PDF 并抽文字（浙江站把中标结果放在 PDF 附件里，正文是空的）。"""
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        r = subprocess.run(['curl', '-sk', '-L', '-m', str(timeout),
                            '-H', 'User-Agent: ' + UA, url, '-o', path],
                           capture_output=True, text=True)
        if not os.path.exists(path) or os.path.getsize(path) < 3000:
            return ''
        # -layout 保留表格列对齐，否则单位名会被拆成「太原锅炉集团有 / 限公司」
        t = subprocess.run(['pdftotext', '-layout', path, '-'],
                           capture_output=True, text=True)
        return t.stdout or ''
    except Exception:
        return ''
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def parse_zj_pdf(txt):
    """从浙江站「中标结果公告」PDF 里读中标人 / 中标价。

    pdftotext -layout 之后的真实版面（多份样本一致）：
        中标人       中标价（元） 工期/服务期（天） 质量承诺     项目负责人
                                     符合现行国
        衢州光明电力投                      家有关工程
        资集团有限公                      施工验收规
                  39922734.59   60              程楠
        司;衢州光明电                     范和标准的
        力设计有限公司                     一次性验收
                                     合格要求
        中标内容

    关键点：**列位置是固定的**（实测表头三份样本一致）：
        中标人 0 列 / 中标价 10 列 / 工期 17 列 / 质量承诺 27 列 / 项目负责人 46~47 列
    所以直接按「质量承诺列」之前切一刀，只留左边那一段；缩进在这里完全不可靠
    （「  39922734.59」缩进 10，而「符合现行国」缩进 34，「司;衢州光明电」缩进 0）。
    """
    if not txt:
        return None
    lines = [re.sub(r'\s+$', '', l) for l in txt.splitlines()]
    idx = None
    for i, l in enumerate(lines):
        if '中标人' in l and ('中标价' in l or '中标金额' in l):
            idx = i
            break
    if idx is None:
        return None

    # 用表头定位「质量承诺」列，切出名字列宽（默认 27）
    hdr = lines[idx]
    cut = hdr.find('质量承诺')
    if cut < 8:
        cut = 26
    amt_col = hdr.find('中标价')
    if amt_col < 2:
        amt_col = 10

    # ⚠ 行间夹大量空行，遇空行不能 break（踩过：整段读空）
    buf, amt = [], 0.0
    for l in lines[idx + 1: idx + 45]:
        if not l.strip():
            continue
        if '中标内容' in l or '行政监督机构' in l:
            break
        left = l[:cut]                       # 只取名字列
        right = l[cut:]                      # 工期/质量/负责人
        seg = ''.join(re.findall(r'[\u4e00-\u9fa5A-Za-z（）();；]', left))
        if seg:
            buf.append(seg)
        if not amt:
            m2 = re.search(r'(?<![0-9])([0-9]{6,}(?:\.[0-9]{1,2})?)(?![0-9])', right) \
                 or re.search(r'(?<![0-9])([0-9]{6,}(?:\.[0-9]{1,2})?)(?![0-9])', left)
            if m2:
                amt = float(m2.group(1))

    name = ''.join(buf)
    # 掐掉尾部粘上的噪声：优先在「中标内容 / 招标范围 / 质量标准 …」这些词处截断
    for cutw in ('中标内容', '招标范围', '质量标准', '行政监督', '招标人提供',
                 '工程所有物资', '设计规范'):
        k = name.find(cutw)
        if k >= 4:
            name = name[:k]
    # 名字被行换行拆开过（「太原锅炉集团有」+「限公司」），上面已拼成一条流；
    # 这里按机构后缀切，**联合体用 ; 连接，后缀在切点之前就闭合**，所以切完再拼回去。
    parts = []
    while name:
        m3 = re.match(r'^(.{4,}?(?:公司|集团|研究院|设计院|工程院|局|厂|中心|大学|学院|事务所))',
                      name)
        if not m3:
            break
        got = m3.group(1)
        if not got.endswith('公司'):
            m3b = re.match(r'^(.{4,}?公司)', name)
            if m3b and len(m3b.group(1)) <= len(got) + 20:
                got = m3b.group(1)
        parts.append(got)
        name = name[len(got):].lstrip(';；')
        if len(parts) >= 2:      # 联合体最多两家
            break
    name = ';'.join(parts) if parts else name.strip(';；')
    if len(name) < 4:
        return None
    return {'win': name, 'amt': amt / 1e8, 'price': ('%s元' % int(amt)) if amt else ''}


def parse_zj_cands(txt):
    """浙江站「中标候选人公示」PDF：一张表，每行一个投标企业 + 报价。
    典型版面（pdftotext -layout，单位名占 2~3 行、金额在中间某行）：
                  中标价      工期/服务
        企业名称                   质量要求   项目负责人
                  （元）      期（天）
        太原锅炉集团有 92500000
                           480   无
          限公司      .00
        四川川锅锅炉有 92888800
        无锡华光环保能
                95500000
        源集团股份有限            540   无
           公司
    比「中标结果」信息量更大 —— 能看到**所有**同场竞标的企业和报价（含没中的）。
    返回 [{win, amt, price}] 列表（第一行即第一名）。

    解析思路（踩过四版坑才稳，pdftotext -layout 的缩进完全不可靠）：
      1. 跳过三行表头，逐行只提取「名字片段」和「金额」；
      2. **名字片段合并成一条流**，遇到机构后缀（公司/集团/研究院…）就切出来当一个单位
         —— 这是唯一稳定成立的规律，跟缩进、跟金额位置都无关；
      3. 金额单独按出现顺序排成一条队列，与切出来的单位一一配对（先进先出）。
         实测金额数 == 单位数（表里每家都报价），配对可信。
    """
    if not txt or '企业名称' not in txt:
        return []
    lines = txt.splitlines()

    idx = None
    for i, l in enumerate(lines):
        if '企业名称' in l and '无效标' not in l:
            idx = i
            break
    if idx is None:
        return []
    start = idx + 1
    for i in range(idx, min(idx + 4, len(lines))):
        if '（元）' in lines[i] or '(元)' in lines[i]:
            start = i + 1
            break

    CN = re.compile('[\u4e00-\u9fa5A-Za-z（）()]')
    AMT_RE = re.compile(r'(?<![0-9])([0-9]{6,})(?:\.([0-9]{1,2}))?')
    STOP = ('无效标', '联合体信息', '其他事项', '异议渠道', '投诉')
    # 长后缀优先，避免「设计研究院」被「研究院」截断
    TAIL_ALT = '|'.join(sorted(_ORG_TAIL, key=len, reverse=True))
    TAIL_RE = re.compile('^(.*?(?:%s))' % TAIL_ALT)

    stream = ''
    amts = []
    for l in lines[start:]:
        core = l.strip()
        if not core:
            continue
        if any(k in core for k in STOP):
            break
        col0 = len(l) - len(l.lstrip())
        m6 = AMT_RE.search(core)
        # 金额：名字部分一定在左侧、金额在右侧；名字部分为空或只有空白 → 纯金额行
        head = l[:m6.start()] if m6 else l
        nm = ''.join(CN.findall(head))
        if m6 and not nm:
            amts.append(float(m6.group(1) + ('.' + m6.group(2) if m6.group(2) else '')))
            continue
        if not nm:
            # 纯数字行（单价/工期/百分号等），既不是名字也不是中标价
            continue
        # 只取第一段（两个以上空格切分），后续列是工期/质量要求
        nm = re.split(r'\s{2,}', head.strip())[0]
        nm = ''.join(CN.findall(nm))
        stream += nm
        if m6:
            amts.append(float(m6.group(1) + ('.' + m6.group(2) if m6.group(2) else '')))
        if col0 >= 12:
            # 深度缩进的多半是「质量要求」等长文本列，不参与名字流
            stream = stream[:len(stream) - len(nm)]

    # 按机构后缀把名字流切成单位。
    # ⚠ 不能简单地「遇到第一个后缀就切」——「太原锅炉集团有限公司」会在「集团」处被
    #   误切。单位名普遍以「公司」收尾，所以优先匹配「…公司」，没有「公司」时才退回
    #   「集团/研究院/…」。
    names = []
    while stream:
        m = TAIL_RE.match(stream)
        if not m:
            break
        got = m.group(1)
        if not got.endswith('公司'):
            m2 = re.match(r'^(.*?公司)', stream)
            if m2 and len(m2.group(1)) <= len(got) + 20:
                got = m2.group(1)
        if len(got) < 4:
            stream = stream[m.end():].lstrip()
            continue
        names.append(got)
        stream = stream[len(got):].lstrip()

    out = []
    for i, name in enumerate(names):
        amt = amts[i] if i < len(amts) else 0.0
        if len(name) >= 4 and amt > 0:
            out.append({'win': name, 'amt': amt / 1e8, 'price': '%s元' % int(amt)})
    return out


def parse_detail(html):
    """从公告正文里读出 中标单位 / 建设单位 / 中标价 / 项目名。
    ⚠ 这里是整个方案的关键：信息在**正文**里，不在标题里。"""
    txt = strip_tags(html)
    if len(txt) < 200:
        return None
    def ok_org(x):
        if not x or len(x) < 4 or len(x) > 40:
            return False
        if any(b in x for b in _BAD_WIN):
            return False
        return any(x.endswith(t) for t in _ORG_TAIL)

    win = ''
    for rex in (_RE_WIN1, _RE_WIN2):
        for m in rex.finditer(txt):
            cand = m.group(1).strip()
            if ok_org(cand):
                win = cand
                break
        if win:
            break
    if not win:
        return None
    owner = ''
    for m in _RE_OWNER.finditer(txt):
        cand = m.group(1).strip()
        if ok_org(cand):
            owner = cand
            break
    price = ''
    m = _RE_PRICE.search(txt) or _RE_PRICE2.search(txt)
    if m:
        price = m.group(1).replace(' ', '')
    return {'win': win, 'owner': owner, 'price': price, 'amt': parse_amt(price), 'txt': txt}


# ── 浙江站（2026-10-26 扩展）────────────────────────────────────────
# 江苏站可以按"栏目+日期"整月扫全量；浙江站的 cnum=001 下有 38 万条中标成交公告，
# 绝大多数是政府采购（办公用品、食堂配送），整月全扫代价太大且噪声极高。
# 实测更有效的方式：用**赛道关键词**搜（热电联产 770 条、集中供热 318 条、
# 燃气轮机 36 条……），命中率接近 100%，且天然只含我们关心的项目。
ZJ_API = 'https://ggzy.zj.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew'
ZJ_HOST = 'https://ggzy.zj.gov.cn'
ZJ_KW = ['热电联产', '集中供热', '供热管网', '蒸汽管道', '锅炉', '燃气轮机',
         '余热利用', '生物质发电', '垃圾焚烧发电', '热电', '热力', '储能电站',
         '背压机组', '抽凝', '能源站', '分布式能源']


def zj_search(kw, pn=0, rn=20):
    p = {"token": "", "pn": pn, "rn": rn, "fields": "title", "cnum": "001",
         "sort": '{"infodate":"0"}', "wd": kw}
    r = subprocess.run(
        ['curl', '-sk', '-m', '30', '-X', 'POST', ZJ_API,
         '-H', 'Content-Type: application/json;charset=utf-8',
         '-H', 'User-Agent: ' + UA,
         '-d', json.dumps(p, ensure_ascii=False)],
        capture_output=True, text=True)
    try:
        return json.loads(r.stdout).get('result') or {}
    except Exception:
        return {}


def scan_zj(max_per_kw=40, dry=False, workers=8):
    """浙江站：按赛道关键词搜，命中后抓详情读中标单位。"""
    todo, seen = [], set()
    for kw in ZJ_KW:
        res = zj_search(kw, 0, 20)
        got = 0
        pn = 0
        while got < max_per_kw:
            res = zj_search(kw, pn, 20)
            recs = res.get('records') or []
            for x in recs:
                t = re.sub(r'</?em[^>]*>', '', x.get('title') or '')
                # 只要中标结果/中标公示这类带中标单位的
                if not re.search(r'中标(结果|公告|公示|候选人)|成交(结果|公告)|定标', t):
                    continue
                link = x.get('linkurl') or ''
                url = (ZJ_HOST + link) if link.startswith('/') else link
                if url in seen:
                    continue
                seen.add(url)
                todo.append({'cat': 'zj-' + kw, 't': t,
                             'd': (x.get('infodate') or '')[:10], 'url': url,
                             'city': x.get('infod') or '浙江', 'id': x.get('id') or ''})
                got += 1
            pn += len(recs)
            if not recs or pn >= int(res.get('totalcount') or 0) or got >= max_per_kw:
                break
            time.sleep(0.3)
        print('  浙江「%s」→ 收 %d 条' % (kw, got), flush=True)
        time.sleep(0.3)
    if dry:
        return todo, []
    print('  浙江待抓详情 %d 条…' % len(todo), flush=True)

    def one(it):
        try:
            html = curl_html(it['url'])
        except Exception:
            return None
        d = parse_detail(html)
        if d:
            rec = dict(it)
            rec.update({'win': d['win'], 'owner': d['owner'],
                        'amt': d['amt'], 'price': d['price']})
            return rec
        # 正文没有「中标单位名称」→ 浙江站大概率是把结果放在 PDF 附件里
        m = _RE_PDF.search(html or '')
        if not m:
            return None
        purl = m.group(1)
        if purl.startswith('/'):
            purl = ZJ_HOST + purl
        elif not purl.startswith('http'):
            purl = ZJ_HOST + '/' + purl.lstrip('./')
        ptext = pdf_text(purl)
        # ⚠ 顺序很重要：候选人公示的表头是「企业名称」，中标结果公告是「中标人」。
        #   实测有的 PDF 两种字样都有，先按候选人表解（信息更全，含落标企业）。
        cands = parse_zj_cands(ptext) if '企业名称' in (ptext or '') else []
        if cands:
            # 一份 PDF 里好几家：**每家单独一条记录**（旧版拼成一个字符串，名字全糊了）
            return [dict(it, win=c['win'], owner='', amt=c['amt'],
                         price=c['price'], rank=i + 1, amt_rank=i + 1)
                    for i, c in enumerate(cands)]
        d2 = parse_zj_pdf(ptext)
        if d2:
            rec = dict(it)
            rec.update({'win': d2['win'], 'owner': '', 'amt': d2['amt'], 'price': d2['price']})
            return rec
        return None

    got = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(one, todo), 1):
            if r:
                if isinstance(r, list):
                    got.extend(r)
                else:
                    got.append(r)
            if i % 100 == 0:
                print('    zj %d/%d 命中 %d' % (i, len(todo), len(got)), flush=True)
    return todo, got


def scan_month(ym, cats, max_n=0, dry=False, workers=8):
    y, m = ym.split('-')
    y, m = int(y), int(m)
    nm = (m % 12) + 1
    ny = y + (1 if m == 12 else 0)
    d1 = '%04d-%02d-01 00:00:00' % (y, m)
    d2 = '%04d-%02d-01 00:00:00' % (ny, nm)   # 下月 1 号，含端点不影响（跨月边界会去重）
    todo = []
    for cat, num in cats.items():
        pn, total = 0, None
        while True:
            res = search(num, d1, d2, pn)
            recs = res.get('records') or []
            total = int(res.get('totalcount') or 0)
            for x in recs:
                link = x.get('linkurl') or ''
                todo.append({
                    'cat': cat,
                    't': re.sub(r'</?em[^>]*>', '', x.get('title') or ''),
                    'd': (x.get('infodateformat') or (x.get('infodate') or '')[:10]),
                    'url': (HOST + link) if link.startswith('/') else link,
                    'city': x.get('zhuanzai') or '',
                    'id': x.get('infoid') or '',
                })
            pn += len(recs)
            if not recs or pn >= total:
                break
            if max_n and len(todo) >= max_n:
                break
            time.sleep(0.3)
        print('  %s %-9s %5d 条' % (ym, cat, total or 0), flush=True)
    if max_n:
        todo = todo[:max_n]
    if dry:
        return todo, []
    print('  %s 待抓详情 %d 条，开始并发抓取…' % (ym, len(todo)), flush=True)

    def one(it):
        try:
            html = curl_html(it['url'])
        except Exception:
            return None
        d = parse_detail(html)
        if not d:
            return None
        rec = dict(it)
        rec['win'] = d['win']
        rec['owner'] = d['owner']
        rec['amt'] = d['amt']
        rec['price'] = d['price']
        return rec

    got = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(one, todo), 1):
            if r:
                got.append(r)
            if i % 100 == 0:
                print('    %d/%d 命中 %d' % (i, len(todo), len(got)), flush=True)
    return todo, got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--month', default='', help='YYYY-MM，单月')
    ap.add_argument('--from', dest='frm', default='', help='起始月 YYYY-MM')
    ap.add_argument('--to', dest='to', default='', help='结束月 YYYY-MM')
    ap.add_argument('--max', type=int, default=0, help='每月最多抓多少条详情（调试）')
    ap.add_argument('--dry', action='store_true', help='只统计，不抓详情')
    ap.add_argument('--cats', default='result,cand', help='result,cand,contract')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--zj', action='store_true', help='同时跑浙江站（赛道关键词）')
    ap.add_argument('--zj-only', action='store_true', help='只跑浙江站')
    ap.add_argument('--zj-per-kw', type=int, default=40, help='浙江每个关键词最多收多少条')
    args = ap.parse_args()

    cats = {k: v for k, v in CATS.items() if k in args.cats.split(',')}

    months = []
    if args.month:
        months = [args.month]
    else:
        a = args.frm or '2024-01'
        b = args.to or '2026-10'
        y, m = map(int, a.split('-'))
        y2, m2 = map(int, b.split('-'))
        while (y, m) <= (y2, m2):
            months.append('%04d-%02d' % (y, m))
            m += 1
            if m > 12:
                y, m = y + 1, 1

    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding='utf-8'))
    recs = old.get('records') or {}

    if args.zj_only:
        months = []

    for ym in months:
        todo, got = scan_month(ym, cats, args.max, args.dry, args.workers)
        for r in got:
            key = (r.get('id') or '') + '|' + re.sub(r'\s+', '', r.get('t') or '')[:60]
            # 同一份「候选人公示 PDF」里有多家企业，靠 rank 区分，否则互相覆盖
            if r.get('rank'):
                key += '#%s' % r['rank']
            recs[key] = {'t': r['t'], 'd': r['d'], 'url': r['url'], 'city': r['city'],
                         'cat': r['cat'], 'win': r['win'], 'owner': r['owner'],
                         'amt': r['amt'], 'price': r['price'],
                         'rank': r.get('rank')}
        print('  %s 累计 %d 条' % (ym, len(recs)), flush=True)
        # 每扫完一个月就落盘，避免长跑中断全丢
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M:%S'), 'records': recs},
                  open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)

    if args.zj or args.zj_only:
        print('\n== 浙江站（赛道关键词）==', flush=True)
        _, got = scan_zj(args.zj_per_kw, args.dry, args.workers)
        for r in got:
            key = (r.get('id') or '') + '|' + re.sub(r'\s+', '', r.get('t') or '')[:60]
            # 同一份「候选人公示 PDF」里有多家企业，靠 rank 区分，否则互相覆盖
            if r.get('rank'):
                key += '#%s' % r['rank']
            recs[key] = {'t': r['t'], 'd': r['d'], 'url': r['url'], 'city': r['city'],
                         'cat': r['cat'], 'win': r['win'], 'owner': r['owner'],
                         'amt': r['amt'], 'price': r['price'],
                         'rank': r.get('rank')}
        print('  浙江并入 %d 条，索引共 %d 条' % (len(got), len(recs)), flush=True)

    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M:%S'), 'records': recs},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)

    # 统计：有多少家单位被反查到
    wins = {}
    for r in recs.values():
        wins[r['win']] = wins.get(r['win'], 0) + 1
    print('\n总共 %d 条带中标单位的公告，涉及 %d 家单位' % (len(recs), len(wins)))
    for k, v in sorted(wins.items(), key=lambda x: -x[1])[:15]:
        print('  %3d 次  %s' % (v, k))


if __name__ == '__main__':
    main()
