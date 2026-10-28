# -*- coding: utf-8 -*-
"""规划 PDF 自动提取器（2026-10-27 新增）

为什么做这个
────────────
浙江全省各县市的热电联产规划只有「征求公众意见」这一环公开，公示正文**不点名企业**，
真正的干货（谁是新热源点的业主、装几台炉、多大供热能力）全在附件《规划（报批稿）》
PDF 里。实测这份 PDF 能直接下载、pdftotext 一秒出全文（不是扫描件），所以干脆
下载 → 提文本 → 抽出热源点清单，跟盐城那份人工提取的结果汇到同一个目录。

和人工提取的分工
────────────────
  · 本脚本：全省批量跑，覆盖广，产出结构化的热源点/规模/投资
  · 人工版 raw/plan_pdf/yancheng-2026-2030.json：只做重点市，字段更全
两边结构一致（meta / chp_sources / resource_projects / surplus_resource_owners），
后面都交给 conv_plan_pdf.py 转成 raw/early/ 入库格式。

输入：raw/early/plan-fgw-latest.json 里带 files[] 的记录（crawl_fgw_plan.py 产出）
输出：raw/plan_pdf/<key>.json（已存在的文件默认跳过，不覆盖人工版）

用法：python plan_pdf_auto.py [--dry] [--force]
"""
import argparse
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(ROOT, 'raw', 'plan_pdf')
EARLY_DIR = os.path.join(ROOT, 'raw', 'early')
DL = '/tmp/plan_pdf_dl'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

# 和 crawl_fgw_plan.py 保持一致：后缀里不放单独的「集团」，否则「XX集团XX有限公司」
# 会在「集团」处提前截断
CO_PAT = re.compile(r'([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,30}?'
                    r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司|总厂|发电厂|公司|厂))')
# ⚠ 从**句子里现拼**企业名会拼出「哲丰能源技改利用厂」这种怪物（原文是
# 「哲丰能源技改利用厂内预留场地」，贪婪匹配把「利用厂」吃进去了）。
# 所以改成先扫全文攒出候选池（后缀必须落在 有限公司/发电厂/热电厂 这种完整结尾上），
# 再回句子里做整串匹配。
CO_FULL = re.compile(r'[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,24}?'
                     r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司|发电厂|热电厂)')
# 不是业主的
NOT_CO = re.compile(r'自备|发展改革委|发改委|人民政府|管委会|设计院|办公室|委员会|'
                    r'区块$|片区$|分区$|园区$|热电联产|集中供热|规划|'
                    r'工业区|企业|加强|督促|新建的|供热|热负荷|厂址|现状|本项目|本工程|'
                    r'垃圾焚烧|污水处理厂')

# 候选名清洗：候选是从句子里截出来的，前面常常粘着引导语/从句
# 「拟由常山工业发展集团有限公司」「主要来自于哲丰新材料有限公司」
# 「将结束婺城经开区以及城区附近由于金华中燃热力科技有限公司」
# ⚠ 长词必须排在短词前面，否则「主要来自于XX」会被「来自」先截一刀，留下「于XX」
CUT = re.compile(r'(?:主要来自于|来自于|来自|由于|以及|并且|因此|所以|结束|开展|'
                 r'进行|通过|位于|依托|拟由|已由|下属子公司|子公司|新建的|新建|'
                 r'建设|现有|规划|包括|即|为)([\u4e00-\u9fa5A-Za-z0-9（）()·]{4,})$')
HEAD = re.compile(r'^(?:拟|将|已|由|与|和|或|在|对|把|使|让|为|作为|依托|依靠|支持|'
                  r'同意|加强|督促|上述|该|其|及|及其|的|是|、|，|,|；|：|\(|（)')


def clean_name(c):
    """把候选企业名里粘着的从句/引导词剥掉。可能粘了好几层，反复剥。"""
    for _ in range(4):
        m = CUT.search(c)
        if not m:
            break
        c = m.group(1)
    # 括号里塞了长注释的（「能源（补充辅助热源点）金华雅境再生能源…」）截到括号后
    m = re.match(r'^[\u4e00-\u9fa5A-Za-z0-9·]{0,6}[（(]([^）)]{5,})[）)]'
                 r'([\u4e00-\u9fa5A-Za-z0-9·]{4,})', c)
    if m:
        c = m.group(2)
    for _ in range(6):
        c2 = HEAD.sub('', c).strip()
        if c2 == c:
            break
        c = c2
    return c

# 有动作才收（conv_plan_pdf.py 的 ACT_TYPES 会从 type 里找这些词）
ACT = re.compile(r'新建|扩建|改建|技改|改扩建|替代|在建|规划新增|新增热源|规划建设')
# 「维持现状/维持不变」不收
KEEP = re.compile(r'维持|暂不|暂无|适时')

# 规模
BOILER = re.compile(r'(\d+(?:\.\d+)?)\s*吨\s*/\s*小时|(\d+(?:\.\d+)?)\s*t\s*/\s*h')
MEGAW = re.compile(r'(\d+(?:\.\d+)?)\s*(?:兆瓦|MW|Mw|万千瓦)')
# 片区/区块名
AREA = re.compile(r'([\u4e00-\u9fa5]{2,6}(?:区块|片区|分区|园区|工业区|开发区))')
# 投资额（万元/亿元）
INVEST = re.compile(r'(\d+(?:\.\d+)?)\s*亿元|(\d+(?:\.\d+)?)\s*万元')


def fetch_pdf(url, dest, referer=None):
    cmd = ['curl', '-sk', '-L', '-m', '180', url, '-H', 'User-Agent: ' + UA, '-o', dest,
           '-w', '%{http_code} %{size_download}']
    if referer:
        cmd += ['-H', 'Referer: ' + referer]
    r = subprocess.run(cmd, capture_output=True, timeout=200)
    out = r.stdout.decode('utf-8', 'ignore').strip()
    if not os.path.isfile(dest) or os.path.getsize(dest) < 5000:
        return False, '下载失败: ' + out
    with open(dest, 'rb') as f:
        head = f.read(5)
    if head != b'%PDF-':
        return False, '不是 PDF: ' + out + ' head=' + repr(head)
    return True, out


def to_text(pdf, txt):
    r = subprocess.run(['pdftotext', '-layout', pdf, txt], capture_output=True, timeout=180)
    if not os.path.isfile(txt):
        return False, (r.stderr.decode('utf-8', 'ignore') or 'pdftotext 无输出')[:160]
    return True, ''


def key_of(rec):
    """文件名 key：城市 + 规划期，如 changshan-2026-2030"""
    city = (rec.get('city') or '').strip()
    m = re.search(r'(20\d{2})\s*[—~\-－至]\s*(20\d{2})', rec.get('t') or '')
    period = ('%s-%s' % (m.group(1), m.group(2))) if m else '2026-2030'
    # 城市拼音太麻烦，直接用标题里的地名（中文文件名 GitHub 没问题）
    m2 = re.match(r'([\u4e00-\u9fa5]{2,8}?(?:市|县|区))', rec.get('t') or '')
    nm = m2.group(1) if m2 else (city or 'plan')
    return '%s-%s' % (nm, period)


def paragraphs(txt):
    """PDF 是按版面断行的，一句话常被拆成好几行（「拟由常山工业」/「发展集团有限
    公司进行建设」）。直接逐行抽会把企业名截成半截，所以先按句号把行拼回段落，
    同时把页眉页脚（设计院名、章节名、页码）剔掉——它们也带「股份有限公司」后缀，
    不剔会被当成业主。"""
    out, buf = [], ''
    for raw in txt.split('\n'):
        s = raw.strip()
        s = re.sub(r'\s{2,}', ' ', s)
        if not s:
            continue
        if re.match(r'^[\-—]?[\u4e00-\u9fa5]{2,10}[\-—]?$', s):      # 章节页眉「-热源规划-」
            continue
        if re.match(r'^\d{1,4}$', s):                                  # 页码
            continue
        if len(s) < 30 and re.search(r'设计院|研究院|咨询有限公司$', s):  # 页脚编制单位
            continue
        buf += s
        if re.search(r'[。；：]$', s):
            out.append(buf)
            buf = ''
    if buf:
        out.append(buf)
    return out


def extract(txt):
    """从规划正文里抽热源点清单。"""
    # 候选池：全文扫一遍，出现过的完整企业名
    # pool: [(匹配用名, 规范名)]，匹配用名长的排前面，避免简称抢先命中
    pool, alias = {}, {}
    for para in paragraphs(txt):
        for c0 in CO_FULL.findall(para):
            c = clean_name(c0.strip())
            # 「加强热电厂」「年）热电厂」这种通用词不是业主：带「热电厂/发电厂」后缀的
            # 要求前面至少 4 个汉字
            if len(c) < 5 or NOT_CO.search(c):
                continue
            if re.search(r'(?:热电厂|发电厂)$', c) and len(c) < 6:
                continue
            pool[c] = c
            # 简称：规划正文里常常一会儿写全称「浙江哲丰能源发展有限公司」、
            # 一会儿写简称「哲丰能源」。只认全称的话，写在简称那句里的动作就漏了。
            short = re.sub(r'^(?:浙江|江苏|安徽|上海|金华|江山|常山|衢州|杭州|宁波)', '', c)
            short = re.sub(r'(?:股份有限公司|有限责任公司|有限公司|集团公司|总公司)$', '', short)
            if len(short) >= 4 and short != c and not NOT_CO.search(short):
                # 简称统一指向更长的那个全称
                if len(c) > len(pool.get(short, '')):
                    pool[short] = c
    pool = sorted(pool.items(), key=lambda kv: len(kv[0]), reverse=True)

    srcs, seen = [], set()
    cur_area = ''
    for para in paragraphs(txt):
        # 一段里可能讲好几句，按句号拆开逐句判断
        for ln in re.split(r'[。；]', para):
            ln = ln.strip()
            if len(ln) < 10:
                continue
            m = AREA.search(ln)
            if m:
                cur_area = m.group(1)
            if not ('热源' in ln or '供热' in ln or '锅炉' in ln or '机组' in ln):
                continue
            if not ACT.search(ln) and not KEEP.search(ln):
                continue

            # 企业名：只认候选池里出现过的完整名（整串匹配），不现拼
            name = ''
            for k, canon in pool:
                if k in ln:
                    name = canon
                    break
            if not name or name in seen:
                continue

            # 规模
            b = BOILER.findall(ln)
            bo = [x or y for x, y in b][:4]
            mw = MEGAW.findall(ln)[:2]
            scale = ''
            if bo:
                scale = '锅炉 %s t/h' % '、'.join(bo)
            if mw:
                scale = (scale + '；' if scale else '') + '机组 %s MW' % '、'.join(mw)

            # 供热能力 t/h
            cap = None
            m = re.search(r'供热能力[^\d]{0,10}(\d+(?:\.\d+)?)', ln)
            if m:
                cap = float(m.group(1))

            ty = ('新建' if ('新建' in ln or '新增' in ln or '规划建设' in ln)
                  else ('扩建' if '扩建' in ln
                        else ('技改' if ('技改' in ln or '改造' in ln) else '维持')))

            # 投资（同一句里的「XX万元」）
            inv = None
            m = INVEST.search(ln)
            if m:
                inv = float(m.group(1)) * 10000 if m.group(1) else float(m.group(2))

            # 简称/全称都撞上的（「哲丰新材料」vs「浙江哲丰新材料」）留长的那个
            dup = [s0 for s0 in srcs if s0['name'] in name or name in s0['name']]
            if dup:
                if len(name) > len(dup[0]['name']):
                    dup[0]['name'] = name
                continue
            seen.add(name)
            srcs.append({
                'area': cur_area,
                'name': name,
                'now': '',
                'plan': re.sub(r'\s+', ' ', ln)[:180],
                'cap_tph': cap,
                'type': ty,
                'scale': scale,
                'invest_wan': inv,
            })
    return srcs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--force', action='store_true', help='已存在的 key 也重新提取（会覆盖人工版！）')
    a = ap.parse_args()

    src = os.path.join(EARLY_DIR, 'plan-fgw-latest.json')
    if not os.path.isfile(src):
        print('没有 %s，先跑 crawl_fgw_plan.py' % src)
        return 1
    recs = [x for x in json.load(open(src, encoding='utf-8')) if x.get('files')]
    print('带附件的规划记录 %d 条' % len(recs))

    os.makedirs(PDF_DIR, exist_ok=True)
    os.makedirs(DL, exist_ok=True)
    n = 0
    for rec in recs:
        key = key_of(rec)
        dest = os.path.join(PDF_DIR, key + '.json')
        if os.path.isfile(dest) and not a.force:
            print('  ⏭  %s 已存在，跳过（加 --force 覆盖）' % key)
            continue
        pdf = os.path.join(DL, key + '.pdf')
        txt = os.path.join(DL, key + '.txt')
        ok, msg = fetch_pdf(rec['files'][0]['u'], pdf, rec.get('url'))
        if not ok:
            print('  ❌ %s %s' % (key, msg))
            continue
        ok, msg = to_text(pdf, txt)
        if not ok:
            print('  ❌ %s %s' % (key, msg))
            continue
        body = open(txt, encoding='utf-8', errors='ignore').read()
        srcs = extract(body)
        print('  ✅ %s：%d 页文本 %d 字 → 热源点 %d 个'
              % (key, body.count('\f') + 1, len(body), len(srcs)))
        for s in srcs:
            print('       %-6s %-26s %-22s %s'
                  % (s['type'], s['name'][:26], (s['area'] or '-')[:22], s['scale'][:30]))
        if a.dry or not srcs:
            continue
        m = re.search(r'《([^》]{4,80})》', rec.get('t') or '')
        json.dump({
            'meta': {
                'src_files': [rec['files'][0]['n']],
                'region': '%s %s' % (rec.get('rg', ''), rec.get('city', '')),
                'plan_period': key.split('-')[-1] if '-' in key else '2026-2030',
                'layer': '立项线索',
                'pub_date': rec.get('d', ''),
                'pub_url': rec.get('url', ''),
                'plan_name': m.group(1) if m else rec.get('t', ''),
                'extracted': 'auto',
                'note': 'plan_pdf_auto.py 自动提取（PDF → pdftotext → 热源点清单）',
            },
            'chp_sources': srcs,
            'resource_projects': [],
            'surplus_resource_owners': [],
        }, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        n += 1
    print('\n写出 %d 份%s' % (n, '（--dry 未写盘）' if a.dry else ''))
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
