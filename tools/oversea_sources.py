#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出海速览 · 自动通道（公开源，2026-11-08 新增，§5.52）

为什么换掉搜狗
────────────────────────────────────────────────────────────────────────
搜狗微信搜索对机房 IP 已封死：本机直连 weixin.sogou.com 得到
302 → /antispider/?antip=wx_sh2，任何关键词都 0 条。GitHub Actions 的
Azure IP 更是从第一天就在它的黑名单里 —— 这也是「8 天还是 11 条」的根因。
旧的 mine_oversea_wechat.py 不删（代码留着做人工检索用），但**不再当主通道**，
它 0 条也 exit 0 的假绿行为在本文件里明确禁止。

现在的两条腿
────────────────────────────────────────────────────────────────────────
  A 自动（本文件）  直连公开中文源，抓标题 + 摘要 + 真实链接 + 发布日期
  B 人工（oversea_manual.py）用户把公众号链接发过来，逐条抓真实标题入库

信源与实测（2026-11-08 全部可用，服务端渲染、无需 JS、无需登录）
────────────────────────────────────────────────────────────────────────
  印尼商报 shangbaoindonesia.com   /read/YYYY/MM/DD/economy-<ts>  中资印尼投资/电厂/冶炼
  国复咨询 news.goalfore.cn        /latest|topstories/detail/<id> 中资海外工程/有色/电力
  我的钢铁 news.mysteel.com        /a/<yymmddNN>/<hash>.html      钢铁/能耗/产能政策

判定（绝不另起一套口径）
────────────────────────────────────────────────────────────────────────
  · semantic_drop()  入库前硬过滤，来自 biz_rules.py（唯一规则源）
  · pick_odi.judge() 出海备案口径 S/A/W/X，复用，不重写
  · 只收 tier ∈ {S, A}：S = 工程本体就是我们的活；A = 客户行业建厂配能源
    W（行业但无产能）/X（不相关）直接丢，速览不是资讯大全。

用法
────────────────────────────────────────────────────────────────────────
    python3 oversea_sources.py             # 采集并落盘 raw/oversea_flash.json
    python3 oversea_sources.py --dry       # 只看命中，不写盘
    python3 oversea_sources.py --days 14   # 只看最近 14 天
"""
import html as _html
import json
import os
import re
import sys
import time

import requests
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight import require_briefing
require_briefing('oversea_sources.py')

import biz_rules as BR
import pick_odi as PO
import seg_match as SM          # 业务层级（12 类口径在 seg_biz.py）
import oversea_manual as OM      # 复用 norm_url / summarize，避免两套实现

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
FLASH = os.path.join(RAW, 'oversea_flash.json')

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

# ── 关键词（用于「值不值得进去看正文」的预筛，不做业务判定）──────────
# ⚠ 业务去留**不在这里**，全部交给 biz_rules.semantic_drop + pick_odi.judge。
#   这里只回答一个问题：这条值不值得多抓一个详情页。所以词要宽，
#   宽了顶多浪费一次请求；窄了会漏掉「镍铁」「自备电厂」这类真线索。
PRE_KW = ('电厂', '电站', '电力', '用电', '发电', '自备', '余热', '热电', '供热',
          '电解铝', '氧化铝', '镍', '钴', '铜', '铝', '锌', '冶炼', '冶炼厂',
          '钢铁', '水泥', '熟料', '矿热炉', 'RKEF',
          '数据中心', '算力', 'IDC', '淡化', '垃圾焚烧', '焚烧发电',
          '工业园', '产业园', '园区',
          '投产', '开工', '签约', '中标', '开工建', '扩建', '新建', '建成',
          'EPC', '总包', '承包', '亿美元', '亿元')

# 明确不看的：光伏/风电/储能电站（我们不做电源投资），矿业纯开采，政策党务
# 用词表前置排除，省一次正文请求。真正的业务判定仍在规则源。
SKIP_KW = ('光伏', '风电', '储能电站', '组件', '逆变器', '铀', '锂矿', '政党', '选举',
           '人事任免', '党建', '座谈', '研讨', '论坛', '峰会', '展会', '展览会',
           '招聘', '同比增', '同比下降', '行情', '报价', '库存', '期货',
           # 光伏：底稿口径里「光伏+储能+柴发」是国内业务形态，海外电源投资不是主线；
           # pick_odi 的 POWER_W 分支对 <20MW 才判 X，580MW 会漏进 A 档。
           # 这里**只管速览收不收**，不改 pick_odi（它管的是备案，口径不同不能混）。
           '光伏', '风电', '储能', '组件', '逆变器', '氢气', '绿氢',
           # 2026-11-19 §5.71：新浪 7x24 接入后带进来的股市人事类噪声
           # （实测「杭州热电聘任副总经理」命中 S_W「热电」进了 S 档）——
           # 人事/股价快讯按 tip 口径「人事股价一律不算」。
           '聘任', '辞职', '上任', '停牌', '回购', '分红', '中签', '解禁',
           # 2026-11-24 §5.106d：核电不是我们业务（主业=火电/余热/热电/焚烧/光储柴），
           # 新浪 7x24 的「东京电力核电站施工」这类纯外国核电动态不该进速览
           '核电', '核电站', '核反应堆', '核电机组')


# ── 新浪 7x24 专属：海外信号闸（§5.106f，2026-11-25）──────────────────
# 「出海区块收的必须是海外的事」——国内省市政策（北京/山东…）、纯国内公司动态
# 一律不收，不管关键词多像。判定只看标题，够宽（60+ 国别/地区 + 海外/出海），
# 漏的顶多是海外小国快讯，会在国复/印尼商报等海外原生源里再出现。
OVERSEA_GEO = ('海外', '出海', '境外', '国外',
               # 亚太
               '印尼', '印度尼西亚', '越南', '泰国', '马来', '马来西亚', '菲律宾',
               '缅甸', '柬埔寨', '老挝', '新加坡', '巴淡', '爪哇', '苏门答腊',
               '日本', '韩国', '朝鲜', '蒙古', '印度', '巴基斯坦', '孟加拉',
               '斯里兰卡', '尼泊尔', '哈萨克', '乌兹别克', '吉尔吉斯',
               # 中东中亚
               '沙特', '阿联酋', '迪拜', '沙迦', '阿布扎比', '卡塔尔', '科威特',
               '阿曼', '巴林', '伊拉克', '伊朗', '土耳其', '以色列', '约旦',
               # 非洲
               '埃及', '摩洛哥', '阿尔及利亚', '利比亚', '突尼斯', '尼日利亚',
               '南非', '肯尼亚', '埃塞俄比亚', '坦桑尼亚', '加纳', '喀麦隆',
               '安哥拉', '莫桑比克', '津巴布韦', '刚果', '赞比亚', '几内亚',
               '科特迪瓦', '塞内加尔', '吉布提', '毛里塔尼亚',
               # 欧洲美洲大洋洲
               '俄罗斯', '白俄罗斯', '乌克兰', '塞尔维亚', '波兰', '匈牙利',
               '捷克', '罗马尼亚', '希腊', '意大利', '西班牙', '葡萄牙',
               '德国', '法国', '英国', '荷兰', '比利时', '瑞典', '芬兰',
               '挪威', '丹麦', '瑞士', '奥地利', '澳大利亚', '新西兰',
               '巴西', '阿根廷', '智利', '秘鲁', '哥伦比亚', '墨西哥',
               '加拿大', '美国', '秘鲁', '玻利维亚', '厄瓜多尔', '委内瑞拉',
               # 通用标识
               '一带一路', '中资', '中企', '海外仓')


def oversea_signal(title):
    """标题里必须能看出「这是海外的事」才收（只用于新浪 7x24 大火灶源）。"""
    return any(k in (title or '') for k in OVERSEA_GEO)


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'ignore')


def strip_tags(s):
    s = re.sub(r'<script.*?</script>', ' ', s, flags=re.S)
    s = re.sub(r'<style.*?</style>', ' ', s, flags=re.S)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = _html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def clean_title(s):
    """清掉列表页带出来的装饰：时间戳前缀、外层【】、置顶/热门标记。

    实测国复列表把整条快讯塞进了 <a> 里：
      「11:09 【伟明环保：印尼垃圾焚烧发电项目争取明年基本建成】 11月6日，伟明环保在2…」
    标题里混着时间和整段正文，规则判定会被后面的正文带偏（也会把标题撑到 200 字）。
    这里只剥**外层装饰**，不猜内容：{时间} + 【核心句】 之后的东西一律归正文。
    """
    s = re.sub(r'^\s*(?:置顶|热门|推荐|[0-2]\d:[0-5]\d)\s*', '', s or '')
    m = re.match(r'^\s*【([^】]{8,})】\s*(.*)$', s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return s.strip(), ''


def longest_block(h):
    """取页面里文本最长的 div/article 块当正文。

    比按 class 名匹配稳：三个源的 class 各不相同（content content-text /
    articleBox article-content-box / 无名 div），但「最长的那个块就是正文」
    对这三家都成立。实测分别取到 943 / 330+ / 600+ 字。
    """
    blocks = re.findall(r'<(?:div|article|section)[^>]*>(.*?)</(?:div|article|section)>', h, re.S)
    best, bl = '', 0
    for b in blocks:
        v = strip_tags(b)
        if len(v) > bl:
            bl, best = len(v), v
    return best


# ── 源 1：印尼商报（中资在印尼的主战场）────────────────────────────────
def src_shangbao(days=7, limit=40):
    out = []
    for ch in ('economy', 'financial'):
        try:
            h = get('https://www.shangbaoindonesia.com/' + ch)
        except Exception as e:
            print('  ✗ 印尼商报/%s 抓取失败：%s' % (ch, type(e).__name__))
            continue
        seen = set()
        for m in re.finditer(r'href="(https://www\.shangbaoindonesia\.com/read/(\d{4})/(\d{2})/(\d{2})/([^"]+))"[^>]*>(.*?)</a>', h, re.S):
            url, y, mo, d, slug, inner = m.groups()
            if url in seen:
                continue
            seen.add(url)
            title = strip_tags(inner)
            title = re.sub(r'^【[^】]*】\s*', '', title)      # 去掉「【财经】」频道前缀
            title, _rest = clean_title(title)
            if len(title) < 10:
                continue
            date = '%s-%s-%s' % (y, mo, d)
            out.append({'title': title, 'url': url, 'date': date, 'src': '印尼商报',
                        'snip': _rest})
            if len(out) >= limit:
                break
        time.sleep(1.0)
    return out


# ── 企业名单（2026-11-23 §5.104 用户勾选 43 家 + 建议补充冶金工程竞对）──
# 命中名单企业名 → 强制收进出海速览（chan=watchlist），不再依赖赛道词。
# 这是「不是用户说一条我做一条」的系统性修法：名单在 raw/company_watch.json，
# 用户增删名单即生效，不用改代码。仍受 SKIP_KW / semantic_drop 双重约束。
_WATCH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw', 'company_watch.json')
try:
    _WJ = json.load(open(_WATCH_PATH, encoding='utf-8'))
    WATCH = [w for w in (_WJ.get('companies') or []) if w]
    for _gl in (_WJ.get('groups') or {}).values():
        WATCH += [w for w in (_gl or []) if w]
    print('企业名单：%d 个名字（company_watch.json）' % len(WATCH))
except Exception as _e:
    WATCH = []
    print('⚠ company_watch.json 读失败，名单强制收退出：%s' % _e)


def watch_hit(text):
    if not WATCH:
        return ''
    for w in WATCH:
        if w in text:
            return w
    return ''


# ── 源 2：国复咨询（中资海外工程头条）──────────────────────────────────
def src_goalfore(days=7, limit=40):
    out = []
    for sec in ('latest', 'topstories'):
        try:
            h = get('https://news.goalfore.cn/' + ('latest' if sec == 'latest' else ''))
        except Exception as e:
            print('  ✗ 国复/%s 抓取失败：%s' % (sec, type(e).__name__))
            continue
        for m in re.finditer(r'href="(https://news\.goalfore\.cn/(?:latest|topstories)/detail/\d+\.html)"[^>]*>(.*?)</a>', h, re.S):
            url, inner = m.groups()
            title, _rest = clean_title(strip_tags(inner))
            if len(title) < 10:
                continue
            if any(x['url'] == url for x in out):
                continue
            out.append({'title': title, 'url': url, 'date': '', 'src': '国复咨询',
                        'snip': _rest})
            if len(out) >= limit:
                break
        time.sleep(1.0)
    return out


# ── 源 3：我的钢铁（钢铁/能耗/产能政策）────────────────────────────────
def src_mysteel(days=7, limit=30):
    try:
        h = get('https://news.mysteel.com/')
    except Exception as e:
        print('  ✗ Mysteel 抓取失败：%s' % type(e).__name__)
        return []
    out, seen = [], set()
    for m in re.finditer(r'href="(https://news\.mysteel\.com/a/(\d{2})(\d{2})(\d{2})\d{2}/[0-9A-F]+\.html)"[^>]*>([^<]{8,80})<', h):
        url, yy, mm, dd, title = m.groups()
        if url in seen:
            continue
        seen.add(url)
        date = '20%s-%s-%s' % (yy, mm, dd)
        title, _rest = clean_title(title.strip())
        out.append({'title': title, 'url': url, 'date': date, 'src': '我的钢铁',
                    'snip': _rest})
        if len(out) >= limit:
            break
    return out


# ── 源 4：新浪财经 7x24 全球快讯（2026-11-19 §5.71 用户拍板「换别的地方，任何新闻推送都可以」）──
# 接口免登录、结构化 JSON、rich_text 即全文（无独立详情页，url 用 7x24 页锚点）。
# 量大约每天 600+ 条，靠主循环的 PRE_KW 标题预筛兜底；每轮只取最新 400 条（≈1 天），
# 日更足够 —— 速览是「当天有什么」，不是回溯历史。
def src_sina724(days=1, pages=8):
    out = []
    for pg in range(1, pages + 1):
        try:
            r = requests.get(
                'https://zhibo.sina.com.cn/api/zhibo/feed?page=%d&page_size=50&zhibo_id=152' % pg,
                headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
            lst = r.json()['result']['data']['feed']['list']
        except Exception as e:
            print('  ✗ 新浪7x24/第%d页 抓取失败：%s' % (pg, type(e).__name__))
            break
        if not lst:
            break
        for x in lst:
            t = (x.get('rich_text') or '').strip()
            ct = (x.get('create_time') or '')[:10]
            if not t or not ct:
                continue
            # 去掉【】公告前缀，标题太长的截断（7x24 一条就是一个完整快讯）
            title = re.sub(r'^【([^】]*)】', r'\1：', t)[:90]
            out.append({'title': title, 'url': 'https://finance.sina.com.cn/7x24/?id=%s&zhibo_id=152' % x.get('id'),
                        'date': ct, 'src': '新浪财经7x24',
                        'snip': t[:160]})
        time.sleep(0.4)
    return out


# ── 源 2b：国复咨询详情页回扫（2026-11-23 §5.104 补漏）─────────────────
# 踩过的坑：用户 11-23 给的样例「中冶京诚签越南 VinMetal 13 亿 EPC」（11-16 发布）
# 不在库里 —— 官网列表页只挂最近几天头条，11-16 那篇在采集轮次到来前已被挤掉。
# 详情页按自增 ID 直达；⚠ 实测 ID 不按时间排序（109015=11-20、109025=7 月），
# 所以回扫按页面日期过滤：扫到的条目只留窗口内的，位置随机不影响正确性，
# 标题照常走 PRE_KW / 名单 / 业务判定 —— 回扫只是「多捞一批候选」，不改变任何入库口径。
def src_goalfore_walk(days=14, back=60):
    out = []
    try:
        h = get('https://news.goalfore.cn/latest')
    except Exception as e:
        print('  ✗ 国复回扫/列表抓取失败：%s' % type(e).__name__)
        return out
    ids = sorted({int(m.group(1)) for m in re.finditer(r'/latest/detail/(\d+)\.html', h)})
    if not ids:
        return out
    top = ids[-1]
    for i in range(top - 1, max(top - 1 - back, 0), -1):
        try:
            pg = get('https://news.goalfore.cn/latest/detail/%d.html' % i)
        except Exception:
            continue
        mt = re.search(r'<title>([^<]*)</title>', pg)
        if not mt:
            continue
        title = mt.group(1).split(' - 电报文章正文')[0].split('- 电报文章正文')[0].strip()
        if len(title) < 10 or 'goalfore' in title.lower():
            continue
        md = re.search(r'20\d\d-\d\d-\d\d', pg)
        date = md.group(0) if md else ''
        # 回扫只补窗口内的（比 days 早上 3 天余量，窗口外的列表早已轮过、回扫意义不大）
        if date and date < time.strftime('%Y-%m-%d', time.localtime(time.time() - (days + 3) * 86400)):
            continue
        out.append({'title': title,
                    'url': 'https://news.goalfore.cn/latest/detail/%d.html' % i,
                    'date': date, 'src': '国复咨询', 'snip': ''})
        time.sleep(0.3)
    return out


# ── 源 5：丝路出海网 gosilu.com（2026-11-23 §5.105 用户推荐，实测不拦截）──
# WordPress 站，wp-json 结构化接口免登录、带日期、标题干净。覆盖中资海外工程/
# 冶金/能源动向，与国复高度互补（用户样例「中冶京诚越南 VinMetal」该站有独立稿）。
def src_gosilu(days=14, limit=30):
    out = []
    try:
        r = requests.get('https://www.gosilu.com/wp-json/wp/v2/posts?per_page=%d' % limit,
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
        posts = r.json()
    except Exception as e:
        print('  ✗ 丝路出海网抓取失败：%s' % type(e).__name__)
        return out
    for p in posts:
        t = re.sub(r'<[^>]+>', '', p.get('title', {}).get('rendered', '')).strip()
        # wp excerpt 里有正文摘要，洗掉标签和实体
        sn = re.sub(r'<[^>]+>', '', p.get('excerpt', {}).get('rendered', ''))
        sn = re.sub(r'&#\d+;|&\w+;', '', sn).strip()[:160]
        if len(t) < 10:
            continue
        out.append({'title': t, 'url': p.get('link', ''), 'date': (p.get('date') or '')[:10],
                    'src': '丝路出海网', 'snip': sn})
    return out


SOURCES = [('印尼商报', src_shangbao), ('国复咨询', src_goalfore), ('国复回扫', src_goalfore_walk),
           ('丝路出海网', src_gosilu),
           ('我的钢铁', src_mysteel),
           ('新浪财经7x24', src_sina724)]


def main():
    dry = '--dry' in sys.argv
    days = 14   # 2026-11-18 从 7 放宽：海螺印尼垃圾焚烧（10-22 发布）就是被 7 天窗口挤掉的
    for i, a in enumerate(sys.argv):
        if a == '--days' and i + 1 < len(sys.argv):
            days = int(sys.argv[i + 1])
    cut = time.strftime('%Y-%m-%d', time.localtime(time.time() - days * 86400))

    cand, stat = [], []
    for name, fn in SOURCES:
        try:
            got = fn(days)
        except Exception as e:
            print('  ✗ %s 异常：%s' % (name, e))
            got = []
        # 预筛：标题不沾业务的连正文都不用抓；名单企业命中也放行（仍受 SKIP_KW 约束）
        # 2026-11-25 §5.106f 新浪地域闸：7x24 是全球财经大火灶（无地域属性），
        # 「北京既有公共建筑供热改造」这种**国内政策**曾因命中「供热」混进出海区块——
        # 用户 11-25 明确开骂。故对新浪条目加硬条件：标题必须含海外信号
        #（国别/地区名 或 海外/出海/中资+海外动词），命中不了直接丢，不进正文请求。
        hit = [x for x in got
               if (any(k in x['title'] for k in PRE_KW) or watch_hit(x['title']))
               and not any(k in x['title'] for k in SKIP_KW)
               and (x.get('src') != '新浪财经7x24' or oversea_signal(x['title']))]
        # 标题预筛是「省请求」的粗筛，不是业务判定；但 SKIP_KW 里放的是明确不看的，
        # 命中就真丢。这里给出丢弃计数，便于判断是词表问题还是源本身没货。
        _skip = [x for x in got if (any(k in x['title'] for k in PRE_KW) or watch_hit(x['title']))
                 and any(k in x['title'] for k in SKIP_KW)]
        for x in _skip[:3]:
            print('     · 跳过（电源/行情/党务）%s' % x['title'][:38])
        print('%-8s 列表 %2d 条 → 标题预筛 %d 条' % (name, len(got), len(hit)))
        stat.append((name, len(got), len(hit)))
        cand.extend(hit)

    # 多源合并去重（国复列表 + 回扫会出同一篇）：同 url 只留一条，列表页的优先（带摘要片段）
    _seen = set()
    cand = [x for x in cand if not (x['url'] in _seen or _seen.add(x['url']))]

    print('\n== 逐条校验（semantic_drop + pick_odi.judge）==')
    keep, review = [], []
    for x in cand:
        if x.get('date') and x['date'] < cut:
            continue
        drop, code, why = BR.semantic_drop(x['title'])
        if drop:
            print('  ✗ [%s] %s' % (code, x['title'][:44]))
            continue
        # 正文只为摘要服务；抓不到正文不影响入库（标题本身已过规则）
        body, date = '', x.get('date') or ''
        try:
            page = get(x['url'])
            body = longest_block(page)
            if not date:
                m = re.search(r'20\d\d-\d\d-\d\d', page)
                date = m.group(0) if m else ''
        except Exception as e:
            print('  · 正文抓取失败（%s），仅用标题：%s' % (type(e).__name__, x['url'][:50]))
        # 摘要把「列表页自带的正文片段」也带上：国复列表把整条快讯塞在 <a> 里，
        # 但最长块取到的是正文 div，两者内容不同，拼一起才不会丢关键口径。
        summ = OM.summarize((x.get('snip') or '') + ' ' + (body or ''), 138)
        if not summ:
            # 摘要是空的，前端就只有一行标题 —— 实测「伊拉克祖拜尔脱气站」就是这样。
            # 抓不到正文时不硬编，如实标出来，让人工看一眼（不假装有摘要）。
            print('  · 无摘要素材（正文与列表片段都为空）')
        # ── 准入口径（写清理由，避免以后又被「放宽一点」带偏）─────────
        # tier S/A  = 工程本体是我们的活 / 客户行业建厂 → 收
        # tier ''   = 两个口径都没命中 → 收进速览但标「待核」，另存待核清单。
        #             （原方案是丢；实测丢了「印尼垃圾发电融资」这种真机会，
        #              它被 pick_odi 的 X_W「垃圾」误杀，所以改成分流不丢。）
        #             试过「'' 也收」，结果轻轨/港口/地铁/防务贷款全进来了 ——
        #             海外速览一旦变成「中资海外工程大全」就没人看了。宁可漏，
        #             不能把港口轻轨塞进能源线索里。漏掉的由人工投喂补（B 通道）。
        # tier W    = 命中客户行业但无产能描述 → 丢（这是软文/行情/政策解读）
        # tier X    = 明确不相关行业（铁路/港口/轻轨/光伏组件/储备数据）→ 丢
        #
        # ── 企业名单强制收（2026-11-23 §5.104 用户勾选名单）────────────
        # 命中 company_watch.json 里的企业名 → 不看 seg/tier，直接收进出海速览。
        # 只绕过「赛道判定」，不绕过 semantic_drop / SKIP_KW —— 名单不是免检通道。
        # 名单也有自己的噪音：名单企业发布的国内行情（「永钢螺纹降80元」）不是出海动向。
        _wh = watch_hit(x['title'] + ' ' + (summ or ''))
        _wl_noise = ('螺纹', '热卷', '早读', '钢价', '报价', '期货', '收盘',
                     '涨', '跌', '涨停', '跌停', '成交额', '融资余额', '股价')
        if _wh and not any(k in x['title'] for k in _wl_noise):
            keep.append({
                'title': x['title'], 'url': x['url'], 'summary': summ,
                'date': date, 'datetime': (date or '') + ' 00:00',
                'src': x['src'], 'kw': 'watchlist',
                'sc': 4, 'tier': 'W', 'tierwhy': '命中企业名单：%s' % _wh,
                'sem': 'KEEP', 'semwhy': '名单企业动向（用户 11-23 勾选）', 'chan': 'watchlist',
            })
            print('  ✓ [名单·%s] %s | %s' % (_wh, date or '????-??-??', x['title'][:40]))
            time.sleep(0.6)
            continue

        # ── 补一道业务层级判断（在定档之前）─────────────────────────────
        # 踩过的坑：伊拉克祖拜尔「脱气站扩建」被判成 A「客户建厂」进了速览。
        # 它命中的是 A_W 里的 '氨'（在「埃尼」→ 没有；实际是正文里"氨"字），
        # 业务上这是油气田地面工程，不是我们做的厂内能源岛。
        # 所以先看 seg_match 的 12 类层级：判到 other 的直接丢，
        # 命中 youse/steelgas/wasteheat/cogen/chemheat/selfplant/datactr/wte
        # 这些能源本体类的才算数。**仍然不新增任何词表**。
        segc = SM.classify(x['title'] + ' ' + summ)
        seg, segkw = segc.get('seg'), segc.get('kw')
        # 命中的关键词太泛（「扩建项目」「项目」这种），层级可信度低 —— 当 other 处理。
        # 实测「伊拉克祖拜尔脱气站扩建」被 seg_match 判成 selfplant，命中词是
        # 「扩建项目」，纯属误配；油气田地面工程不是我们的厂内能源岛。
        # 这里不加剧关键词、不改 seg_match（它服务的是①库判定，改动面太大），
        # 只在速览入口做一道「关键词可信度」过滤，且只影响速览收不收。
        _GENERIC = {'扩建项目', '新建项目', '项目', '改造项目', '建设项目',
                    '工程', 'EPC', '总承包', '承包'}

        # ── E 档兜底（2026-11-19 用户二次拍板：不要「行业动态」，改收「企业动向」）──
        # 上一版 B 档（命中行业词就收）按用户指示撤掉；改成只收「企业海外动向」——
        # 具体企业 + 建厂动作（投产/开工/奠基/签约/扩建/新基地），典型如
        # 「中策越南轮胎工厂投资签约」（微信公众号车与轮，用户给的样例）。
        # 纯行业统计/行业政策（不落到具体企业动作）不收；X_W / THERMO_FALSE 照拦。
        # ⚠ 动作词是速览展示层自有词，只影响出海速览收不收，不进 ①库判定，
        #   不碰 judge()/semantic_drop()。
        E_ACT = ('建厂', '投产', '开工', '奠基', '签约', '扩建', '扩产',
                 '新工厂', '新基地', '投资建设', '投资设立', '落成')
        E_OBJ = PO.A_W + ('工厂', '生产基地', '产业园', '工业园', '生态园',
                          '制造基地', '产线', '生产线')

        def _e_fallback():
            n = x['title'] + ' ' + (summ or '')
            if any(w in n for w in PO.X_W) or any(w in n for w in PO.THERMO_FALSE):
                return None
            act = [w for w in E_ACT if w in n]
            if not act:
                return None
            obj = [w for w in E_OBJ if w in n]
            if not obj:
                return None
            return '企业动向：%s（%s）' % ('、'.join(act[:2]), '、'.join(obj[:2]))

        if seg in (None, 'other') or not segkw or segkw in _GENERIC:
            e = _e_fallback()
            if not e:
                print('  ✗ [业务层级 %s/%s] %s' % (seg, segkw or '-', x['title'][:38]))
                continue
            keep.append({
                'title': x['title'], 'url': x['url'], 'summary': summ,
                'date': date, 'datetime': (date or '') + ' 00:00',
                'src': x['src'], 'kw': 'autoE:' + x['src'],
                'sc': 4, 'tier': 'E', 'tierwhy': e,
                'sem': 'KEEP', 'semwhy': 'E档（企业海外动向，主档未过）', 'chan': 'autoE',
            })
            print('  ✓ [E] %s | %s' % (date or '????-??-??', x['title'][:44]))
            time.sleep(0.6)
            continue
        tier, tierwhy = PO.judge(x['title'] + ' ' + summ)
        # ⚠ 这里**不另写词表**，只决定「用不用 tier 这个结果」。业务口径仍在
        #   pick_odi.judge；要改「什么算客户行业」请改 pick_odi，不要改这里。
        SEM_SOFT = {'sewage', 'wte', 'zero', 'soil'}   # 这三类在备案口径里会被 X 误杀
        semcode = BR.semantic_drop(x['title'])[1]
        if tier in ('S', 'A'):
            pass
        elif tier == 'X' and semcode in SEM_SOFT:
            tier, tierwhy = 'A', '规则源命中 %s（分公司业务），备案口径未覆盖' % semcode
        elif tier == '':
            # 两个口径都没命中 —— 必须再过一道「业务层级」才决定收不收。
            #
            # 为什么不能一律收：实测一律收会进来塞内加尔港口、坦桑尼亚铁路、
            # 槟城轻轨、沙特防务贷款 —— 海外速览变成「中资海外工程大全」就没人看了。
            # 为什么不能一律丢：「印尼 Danantara 垃圾发电项目融资里程碑」被
            # pick_odi 判成「不相关行业」（X_W 里有 '垃圾'），可它恰恰是 wte 的活。
            #
            # 判据用 seg_match.classify（业务层级，12 类是底稿定的口径），
            # 只收层级属于能源/冶炼/固废本体的；港口铁路轻轨会被判 other → 丢。
            # ⚠ 仍然不写新词表，只是「再多问一个已有的口径」。
            if seg in ('youse', 'steelgas', 'wasteheat', 'cogen', 'chemheat',
                       'selfplant', 'datactr', 'wte', 'sewage', 'zero', 'soil'):
                tier, tierwhy = 'A', '业务层级=%s（备案口径未覆盖）' % seg
            else:
                e = _e_fallback()
                if not e:
                    print('  ✗ [业务层级 other] %s' % x['title'][:40])
                    continue
                keep.append({
                    'title': x['title'], 'url': x['url'], 'summary': summ,
                    'date': date, 'datetime': (date or '') + ' 00:00',
                    'src': x['src'], 'kw': 'autoE:' + x['src'],
                    'sc': 4, 'tier': 'E', 'tierwhy': e,
                    'sem': 'KEEP', 'semwhy': 'E档（企业海外动向，主档未过）', 'chan': 'autoE',
                })
                print('  ✓ [E] %s | %s' % (date or '????-??-??', x['title'][:44]))
                time.sleep(0.6)
                continue
        else:
            e = _e_fallback()
            if not e:
                print('  ✗ [%s %s] %s' % (tier or '-', tierwhy[:16], x['title'][:40]))
                continue
            keep.append({
                'title': x['title'], 'url': x['url'], 'summary': summ,
                'date': date, 'datetime': (date or '') + ' 00:00',
                'src': x['src'], 'kw': 'autoE:' + x['src'],
                'sc': 4, 'tier': 'E', 'tierwhy': e,
                'sem': 'KEEP', 'semwhy': 'E档（企业海外动向，主档未过）', 'chan': 'autoE',
            })
            print('  ✓ [E] %s | %s' % (date or '????-??-??', x['title'][:44]))
            time.sleep(0.6)
            continue
        keep.append({
            'title': x['title'], 'url': x['url'], 'summary': summ,
            'date': date, 'datetime': (date or '') + ' 00:00',
            'src': x['src'], 'kw': 'auto:' + x['src'],
            'sc': 8 if tier == 'S' else 6,
            'tier': tier, 'tierwhy': tierwhy,
            'sem': 'KEEP', 'semwhy': why, 'chan': 'auto',
        })
        print('  ✓ [%s] %s | %s' % (tier, date or '????-??-??', x['title'][:44]))
        time.sleep(0.6)

    # 跨源转载去重：同一条新闻在商报和国复都出现，只留先到的
    _seen_t = set()
    _dedup = []
    for r in keep:
        k = re.sub(r'[\s\W]', '', r['title'])[:22]
        if k in _seen_t:
            continue
        _seen_t.add(k)
        _dedup.append(r)
    keep = _dedup
    print('\n候选 %d → 入库 %d' % (len(cand), len(keep)))
    if review:
        rv_path = os.path.join(RAW, 'oversea_review.json')
        old_rv = {'items': []}
        if os.path.exists(rv_path):
            try:
                old_rv = json.load(open(rv_path, encoding='utf-8'))
            except Exception:
                pass
        cur = {x.get('url'): x for x in old_rv.get('items', [])}
        for x in review:
            cur.setdefault(x['url'], x)
        json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'),
                   'n': len(cur), 'items': list(cur.values())},
                  open(rv_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('另存待核清单 %d 条 → raw/oversea_review.json（收进速览，但档位未定）'
              % len(review))
    if dry:
        print('-- dry，不写盘 --')
        return

    old = {'items': []}
    if os.path.exists(FLASH):
        try:
            old = json.load(open(FLASH, encoding='utf-8'))
        except Exception:
            pass
    merged = {OM.norm_url(x.get('url')): x for x in old.get('items', [])}
    # 与存量库做同题去重（2026-11-23 §5.105 用户要求「不要同一条新闻出现多次」）：
    # 不同网站转载同一事件标题高度相似，跨源 title 去重只管本轮候选，
    # 这里补上「与库里已有条目」的同题判定，转载晚到的不再重复入库。
    _tk = {re.sub(r'[\s\W]', '', x.get('title') or '')[:22] for x in old.get('items', [])}
    _dead = 0
    for _k, _x in merged.items():
        if 'weixin.sogou.com' in (_x.get('url') or '') and not _x.get('linkdead'):
            _x['linkdead'] = 1
            _x['linkdeadwhy'] = 'sogou 跳转链对机房 IP 一律 302 antispider（2026-11-08 实测 3/3）'
            _dead += 1
    if _dead:
        print('补标死链 %d 条（sogou 跳转链已全部失效）' % _dead)
    added = 0
    for r in keep:
        k = OM.norm_url(r['url'])
        tk = re.sub(r'[\s\W]', '', r['title'])[:22]
        if k in merged or tk in _tk:
            continue
        merged[k] = r
        _tk.add(tk)
        added += 1
    items = sorted(merged.values(),
                   key=lambda y: (y.get('datetime') or y.get('date') or '', -int(y.get('sc') or 0)),
                   reverse=True)
    cut60 = time.strftime('%Y-%m-%d', time.localtime(time.time() - 120 * 86400))
    items = [x for x in items if (x.get('date') or '') >= cut60]

    os.makedirs(RAW, exist_ok=True)
    json.dump({'updated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(items), 'items': items},
              open(FLASH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # ⚠ 必须再跑一次人工投喂通道，且合并过程只在内存里做、只写一次盘。
    #   踩过的坑：A 先写盘 → B 自己读盘再写一次 → 后写的把先写的覆盖，
    #   结果「你投喂的 3 条不见了」（2026-11-08 18:27 实测丢过一次）。
    try:
        import oversea_manual as _OM
        _recent = _OM.main()
        if _recent:
            _OM.combine(_recent)
    except Exception as _e:
        print('⚠ 人工投喂通道合并失败：%s' % _e)
    print('写入 %s：新增 %d → 合计 %d 条' % (os.path.basename(FLASH), added, len(items)))
    print('\n源统计（列表 / 预筛命中）：' + ' · '.join('%s %d/%d' % s for s in stat))


if __name__ == '__main__':
    main()
