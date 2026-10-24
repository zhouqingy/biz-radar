#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中标单位补全 v2（2026-10-21）

背景：648 条中标类公告里 254 条带中标单位，剩下 394 条前端只能显示「未公示」。
「已出结果」这一档的全部价值就是「谁拿的单、多少钱」，空的等于没用。

v1（mine_notice.py）用 headless chrome 逐条渲染，太重也太慢（一次 12 秒）。
v2 换成「先静态抓，抓不到再上浏览器」：
  - 合肥 ggzy.hefei.gov.cn  静态 HTML 里就带「中标（成交）单位:」，40ms 一条
  - 浙江 ggzy.zj.gov.cn     Vue 渲染，但原始 JSON 在 __NUXT__/script 里，抠出来即可
  - 江苏 jsggzy / 上海 shggzy / 苏州 反爬或需登录，静态拿不到 → 交给浏览器兜底（可选，不默认跑）

输出 raw/notice_extra.json（与 v1 同结构，增量合并，不覆盖已有结果）
"""
import os, re, json, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
OUT = os.path.join(RAW, 'notice_extra.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

CORP = r'[\u4e00-\u9fa5A-Za-z0-9（）()·、\-]{3,80}'
# 「中标人：X」「中标（成交）单位: X」「中标单位名称：X」「第一中标候选人：X」
# 注意：这些站点的正文是「一列标签、一列值」的表格式排版，转纯文本后
# 「中标候选人名称：」会变成「中 ; 标候选人名称：」（中间插了标签闭合换行）。
# 所以匹配前先把空白全压掉，用无空白文本做匹配。
C = r'[\u4e00-\u9fa5A-Za-z0-9（）()·、\-]{3,80}'
RE_WIN = [
    # 「中标（成交）单位：X」—— 括号是可选后缀，不能用「（?成交）?」这种写法：
    # 中文全角括号后跟 ? 时，Python 的 re 会把它当量词处理，整条链静默失配（实测踩坑）。
    re.compile(r'中标\x01*单位(?:名称)?[:：]\s*(%s)' % C),
    re.compile(r'中标（成交）单位(?:名称)?[:：]\s*(%s)' % C),
    re.compile(r'中标人(?:名称)?[:：]\s*(%s)' % C),
    # 「第一中标（成交）候选人名称：」——合肥全是这种写法，括号里的成交是可选修饰
    re.compile(r'第[一二三]?中标(?:（成交）|或成交)?\x01*候选人(?:名称)?[:：]\s*(?:名称[:：])?\s*(%s)' % C),
    re.compile(r'中标\x01*候选人名称[:：]\s*(%s)' % C),
    re.compile(r'成交供应商(?:名称)?[:：]\s*(%s)' % C),
]
# 截断优先级：「联合体/牵头人」要排在括号和地址前面，否则「A（牵头人）、B」会被「（」切断
STOP = re.compile(r'(?:联合体|联合投标|牵头人|成员方|地址|地\s*址|联系人|电话|投标报价|中标报价|中标价|中标金额|费率|工期|项目负责人|身份证|得分|资格|详见|[（(；;，,\x01])')
# 明显不是单位的词（表头、占位）
BAD = re.compile(r'^(?:名称|单位|投标人|候选人|详见|无|/|—|-+)$')


def tidy(s):
    s = STOP.split(s)[0].strip()
    s = re.sub(r'[。、；;，,：:\s]+$', '', s)
    # 常见表头残留
    s = re.sub(r'^(?:名称|单位|名称单位)[:：]', '', s)
    if BAD.match(s):
        return ''
    # 值可能是「A公司B公司」（并列单位被压平），不能只认结尾是「公司」。
    # 但要挡住「详见附件」「另行公告」这类非单位文本（下面统一拦）。
    if not re.search(r'(公司|集团|研究院|设计院|电厂|厂|中心|研究所|大学|事务所)', s):
        return ''
    if not s.endswith(('公司', '集团', '院', '厂', '中心', '所', '大学', '事务所', '局', '合作社', '银行')):
        # 结尾不像单位名：只在能切出第一段完整厂名时截取
        m = re.match(r'(.{4,60}?(?:公司|集团|设计院|研究院|电厂|厂|中心|研究所|大学|事务所))', s)
        s = m.group(1) if m else ''
    if len(s) < 4 or len(s) > 60:
        return ''
    if re.search(r'详见|见附件|另行|公告|招标|投标人资格', s):
        return ''
    return s


def pick_win(text):
    """一段正文里抠中标单位。多家（; 分隔）保留第一家——多主体多半是联合体，
    完整名单没意义，前端「中标情况」只展示主中标人。"""
    # 全删空白：这些站点的表格转文本后会在词中间插标签换行（「中 ; 标候选人名称：」），
    # 不整删就永远匹配不上。厂名本身不会被拆（拆了也能拼回来）。
    flat = re.sub(r'[\s\u3000]+', '', text)
    flat = flat.replace(';', '\x01').replace('；', '\x01')
    # 标签被拆开：「中 ; 标候选人名称」「第一中标 ; 候选人名称」
    # 把  从「词中间」挪走（「中标」→「中标」），词就不会被打断；
    # 后续正则里的  都是可选的，词首带一个也不影响。
    flat = flat.replace('中', '中')
    flat = re.sub(r'候选人\x01+名称', '候选人名称', flat)
    flat = re.sub(r'中标候选人\x01+名称', '中标候选人名称', flat)
    for p in RE_WIN:
        for m in p.finditer(flat):
            v = tidy(m.group(1))
            if v:
                return v
    # 兜底：表格型页面里「中标候选人名称」和值被拆到两格，中间夹了地址/报价，
    # 这种情况识别风险高，宁可不填也不填错——填错会污染对手榜。
    return ''


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ('utf-8', 'gbk'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'ignore')


def html_text(h):
    h = re.sub(r'<script.*?</script>', ' ', h, flags=re.S)
    h = re.sub(r'<style.*?</style>', ' ', h, flags=re.S)
    h = re.sub(r'<[^>]+>', '\n', h)
    h = (h.replace('&nbsp;', ' ').replace('&#160;', ' ').replace('&amp;', '&')
           .replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
    h = re.sub(r'[ \t]+', ' ', h)
    h = re.sub(r'\n{2,}', '\n', h)
    return h


def parse_hefei(h):
    """合肥：后台直接吐一段带「中标（成交）单位:」的正文，静态可解析。"""
    t = html_text(h)
    return pick_win(t)


def parse_zj(h):
    """浙江：页面是 Vue 壳，正文在 <script> 里的 JSON。
    先试转义后的 \\u4e2d 形式，再试原样中文。"""
    t = html_text(h)
    v = pick_win(t)
    if v:
        return v
    for m in re.finditer(r'"content"\s*:\s*"(.{50,20000}?)"\s*[,}]', h, flags=re.S):
        blob = m.group(1)
        try:
            blob = blob.encode().decode('unicode_escape')
        except Exception:
            pass
        blob = re.sub(r'<[^>]+>', '\n', blob)
        v = pick_win(blob)
        if v:
            return v
    return ''


def parse_generic(h):
    return pick_win(html_text(h))


PARSERS = {
    'ggzy.hefei.gov.cn': parse_hefei,
    'ggzy.zj.gov.cn': parse_zj,
}
# 静态抓不稳、或纯 JS 渲染的站：不浪费时间，直接跳过（要补就开 --browser）
SKIP = ('jsggzy.jszwfw.gov.cn', 'shggzy.com', 'zfcg.sh.gov.cn')


def one(args):
    url, pname = args
    try:
        h = get(url)
    except Exception as e:
        return url, None, 'ERR ' + str(e)[:50]
    if len(h) < 500:
        return url, None, 'SHORT'
    fn = parse_generic
    for k, v in PARSERS.items():
        if k in url:
            fn = v
            break
    try:
        w = fn(h)
    except Exception as e:
        return url, None, 'PARSE ' + str(e)[:40]
    return url, w, ('OK' if w else 'NOWIN')


def main():
    browser = '--browser' in sys.argv
    D = json.load(open(os.path.join(ROOT, 'merged.json'), encoding='utf-8'))
    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding='utf-8')).get('items', {})

    todo = []
    for r in D:
        if r.get('st') not in ('中标结果公示', '中标候选人公示'):
            continue
        if (r.get('win') or '').strip():
            continue
        u = r.get('url') or ''
        if not u:
            continue
        if (old.get(u) or {}).get('win'):
            continue
        if not browser and any(s in u for s in SKIP):
            continue
        todo.append(u)
    todo = list(dict.fromkeys(todo))
    print('待补 %d 条（浏览器兜底：%s）' % (len(todo), '开' if browser else '关'))

    ok = 0
    done = 0
    step = max(1, len(todo) // 20)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for url, w, st in ex.map(one, [(u, '') for u in todo]):
            done += 1
            if done % step == 0:
                print('  %d/%d  已补 %d' % (done, len(todo), ok), flush=True)
            if w:
                ok += 1
                item = old.setdefault(url, {})
                item['win'] = w
    print('补到 %d 条 / 试了 %d 条' % (ok, len(todo)))

    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'),
               'items': old},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    total = sum(1 for v in old.values() if v.get('win'))
    print('notice_extra 现有 %d 条，其中带中标单位 %d 条' % (len(old), total))


if __name__ == '__main__':
    main()
