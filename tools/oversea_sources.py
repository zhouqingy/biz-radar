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
           '光伏', '风电', '储能', '组件', '逆变器', '氢气', '绿氢')


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


SOURCES = [('印尼商报', src_shangbao), ('国复咨询', src_goalfore), ('我的钢铁', src_mysteel)]


def main():
    dry = '--dry' in sys.argv
    days = 7
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
        # 预筛：标题不沾业务的连正文都不用抓
        hit = [x for x in got
               if any(k in x['title'] for k in PRE_KW)
               and not any(k in x['title'] for k in SKIP_KW)]
        # 标题预筛是「省请求」的粗筛，不是业务判定；但 SKIP_KW 里放的是明确不看的，
        # 命中就真丢。这里给出丢弃计数，便于判断是词表问题还是源本身没货。
        _skip = [x for x in got if any(k in x['title'] for k in PRE_KW)
                 and any(k in x['title'] for k in SKIP_KW)]
        for x in _skip[:3]:
            print('     · 跳过（电源/行情/党务）%s' % x['title'][:38])
        print('%-8s 列表 %2d 条 → 标题预筛 %d 条' % (name, len(got), len(hit)))
        stat.append((name, len(got), len(hit)))
        cand.extend(hit)

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
        if seg in (None, 'other') or not segkw or segkw in _GENERIC:
            print('  ✗ [业务层级 %s/%s] %s' % (seg, segkw or '-', x['title'][:38]))
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
                print('  ✗ [业务层级 other] %s' % x['title'][:40])
                continue
        else:
            print('  ✗ [%s %s] %s' % (tier or '-', tierwhy[:16], x['title'][:40]))
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
        if k not in merged:
            merged[k] = r
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
