# -*- coding: utf-8 -*-
"""把《江浙沪皖供热规划可做项目清单》生成平台独立的「规划前瞻」模块 data.plan.js

为什么单独一个模块（用户 2026-11-02 定）：
  这批 124 条是**规划/批复阶段的前瞻项目**，不是招投标公告。塞进「找商机」
  会和真实标的混在一起——商机库里那些是有招标文件、有开标时间的，这些是
  规划里点了个名。混着放，销售分不清哪个现在能投。
  所以做成一级页签「规划前瞻」，独立筛选、独立统计，商机库保持纯招投标流。

为什么复用 build_data.classify / grade：
  分数（sc）和档位（g）必须和商机库同一套算法，否则同一个项目在两处显示
  两个优先级，用户会立刻发现。这里直接 import 那三个函数，不另写一套。

输入：/workspace/规划资料-2026-2030/江浙沪皖供热规划可做项目清单.xlsx
输出：/workspace/biz-radar/data.plan.js   （window.DATA_PLAN）
"""
import json
import os
import re
import sys
import time

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_scoring():
    """只取 build_data.py 的评分逻辑，不跑它的主流程。

    build_data.py 没有 if __name__ == '__main__' 保护 —— 直接 import 会把
    整个采集/去重/写 merged.json 的流程跑一遍（实测 2 分钟没跑完）。
    前 262 行是纯常量 + 函数（已核过，无 open/json.load/subprocess），
    到这里切断再 exec，拿到的就是同一套 classify / grade，口径不会漂。
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build_data.py')
    lines = open(path, encoding='utf-8').read().split('\n')
    cut = next(i for i, l in enumerate(lines) if l.startswith('# ============ 2.'))
    ns = {'__name__': '_scoring', '__file__': path}
    exec('\n'.join(lines[:cut]), ns)
    return ns


_NS = _load_scoring()
classify = _NS['classify']
grade = _NS['grade']
parse_scale = _NS['parse_scale']

# 路径不能写死 /workspace —— GitHub Actions 里 workspace 是 $GITHUB_WORKSPACE，
# 接进 daily.yml 之后直接跑会 FileNotFoundError。
#
# ⚠ 两处目录结构不一样，不能一个变量套到底：
#     本地：输入 /workspace/规划资料-2026-2030/*.xlsx，输出 /workspace/biz-radar/data.plan.js
#     CI  ：输入 <root>/规划资料-2026-2030/*.xlsx，输出 <root>/data.plan.js
#           （daily.yml 里 build_web.py 用的是 BIZ_OUT=${{ github.workspace }}，
#             所有 data.*.js 直接落在仓库根，没有 biz-radar 这一层）
# 所以输出目录单独给一个 BIZ_SITE 覆盖口，默认才退到 biz-radar/
_HERE = os.path.dirname(os.path.abspath(__file__))
_OUTDIR = os.environ.get('BIZ_OUT') or os.path.dirname(_HERE)
def _pick_site(outdir):
    """输出目录：显式 BIZ_SITE > 有 data.core.js 的那一层。

    2026-11-08 补：原来只写了 `BIZ_SITE or 上级/biz-radar`，
    CI 里不传 BIZ_SITE 时会拼成 <workspace>/biz-radar —— 那个目录不存在，
    写盘直接 FileNotFoundError。改成先看哪层真的有 data.core.js。
    """
    env = os.environ.get('BIZ_SITE')
    if env:
        return env
    nested = os.path.join(outdir, 'biz-radar')
    if os.path.isfile(os.path.join(nested, 'data.core.js')):
        return nested
    return outdir


_SITE = _pick_site(_OUTDIR)

SRC = os.path.join(_OUTDIR, '规划资料-2026-2030', '江浙沪皖供热规划可做项目清单.xlsx')
OUT = os.path.join(_SITE, 'data.plan.js')

# 热网/管网类：用户明确「不入商机库，只挂画像」。在模块里仍然展示（不然看不全），
# 但单独打标、单独计数，排序时沉底。
PIPE_KW = ('热网', '管网', '蒸汽管道', '供热管道', '换热站', '热力站')

# 来源类型 → 「提前量」徽标文字。和商机库 early 字段同一套 vocabulary。
EARLY_MAP = {
    '规划已批复': '规划批复',
    '规划批复': '规划批复',
    '报批/公示中': '供热规划',
    '已核准/备案': '发改委核准',
    '前期论证': '规划论证',
    '已开工/总包已定': '已开工',
}

# 关闭级别：0 正常 / 1 部分关闭（还有剩余标段）/ 2 整条关闭
#
# 踩过的坑：最早用一条正则 `已开工|总包已定|...` 扫排他说明，结果
# 「怀远龙亢……⚠ 2021 年的规划，**需核实是否已开工**」被判成已开工，
# 一条业主未定、正该去争取的项目被打成红叉沉底。说明文字里的"待核实"
# 不是事实。所以先剔掉核实/是否这类不确定表述，再看有没有转折。
CLOSED_HARD = re.compile(r'已开工|总包已定|主包已定|已完成.{0,4}招标|已定标|EPC ?已定'
                         r'|已中标|已投产|已建成|主包已结束|主体已完成')
CLOSED_SOFT = re.compile(r'但|还开着|还在|可能还在|剩余|窗口|部分')


def close_level(stage, lk):
    t = str(lk or '')
    t = re.sub(r'(需|待|应)?核实[^。；]{0,16}', '', t)
    t = re.sub(r'是否[^。；]{0,16}', '', t)
    hard = stage == '已开工/总包已定' or bool(CLOSED_HARD.search(t))
    if not hard:
        return 0
    return 1 if CLOSED_SOFT.search(t) else 2


def classify_plan(name, content, buyer, kind):
    """规划项目的专用分类。

    为什么不直接用 build_data.classify：那套规则是按**招标标题**写的，
    规划文本的写法它认不出来。实测反例——「上海梅山钢铁余气资源综合
    利用发电（热电）项目」不含任何规则词，被判成「其他非主业」拿 4 分、
    D 档；而钢铁余气发电恰恰是公司 90% 市占率的王牌业务。这类误判会把
    最该看的项目埋掉。

    这里按公司主业的优先级重排判据：钢铁煤气/余热 → 热电联产 → 热网。
    """
    t = f'{name} {content} {buyer}'
    k = str(kind or '')

    if '垃圾' in t and '焚烧' in t:
        return '能源清洁高效利用', '垃圾焚烧发电'

    # 钢铁/焦化/铁合金的副产煤气与余热余压——公司最硬的业务
    if re.search(r'煤气|高炉|焦炉|转炉|CCPP|干熄焦|烧结|球团|余气|余压|TRT|熔融还原', t):
        if re.search(r'煤气|CCPP|高炉|焦炉|转炉', t):
            return '能源清洁高效利用', '煤气发电'
        return '能源清洁高效利用', '余热发电'
    if re.search(r'余热|烟气回收|低温余热|ORC|冷凝水', t):
        return '能源清洁高效利用', '余热发电'

    # 热网类：先于「热电联产」判，否则「XX 热网」会被当成热源点
    if k in ('热网', '热网+换热站') or re.search(r'热网|管网|蒸汽管道|供热管道|换热站|热力站', t):
        return '能源清洁高效利用', '供热与综合能源'

    if re.search(r'热电联产|热源点|背压|抽背|抽凝|供热机组|汽轮|机组|锅炉|锅炉岛|'
                 r'分布式能源|能源站|扩建|技改|迁建|搬迁|新建|改造', t):
        return '能源清洁高效利用', '热电联产'

    if re.search(r'热泵|污水源', t):
        return '其他非主业', '未分类'

    return '能源清洁高效利用', '热电联产'   # 兜底：这批全是供热规划里的热源项目


def amt_to_yuan(v):
    """清单里的投资额单位是亿元，grade() 要的是元。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f * 1e8 if f else None


def main():
    wb = openpyxl.load_workbook(SRC)
    ws = wb['可做项目清单']
    hdr = [c.value for c in ws[1]]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(hdr, r))
        rows.append(d)

    # ── 2026-11-13 追加：把每日 3.6 抓到的省发改委规划批复并进来 ──────────
    # 原来只吃这一份 xlsx（2026-11-02 版），所以 data.plan.js 的 gen 一直停在 11-02，
    # 明明 tools/raw/early/plan-fgw-latest.json 每天在更新（3.6，江苏 41 条），却从来没进页面。
    # 用户 2026-11-13 17:08 授权「一起接上」。
    # 去重按「去掉括号后的项目名」双向包含，和 xlsx 已有的 124 条完全不重叠（实测 0 重叠 / 41 新增）。
    _fgw_n = 0
    _fgw_path = os.path.join(_HERE, 'raw', 'early', 'plan-fgw-latest.json')
    try:
        _fw = json.load(open(_fgw_path, encoding='utf-8'))
        if isinstance(_fw, dict):
            _fw = _fw.get('items') or []
        _norm = lambda x: re.sub(r'[\s·、,，。（）()]', '', re.sub(r'[（(][^）)]*[）)]', '', str(x or '')))
        _have = [_norm(str(r['项目名称'] or '')) for r in rows]
        for x in _fw:
            _t = str(x.get('t') or '').strip()
            if not _t:
                continue
            _k = _norm(_t)
            if any(_k == a or (len(_k) >= 8 and len(a) >= 8 and (_k in a or a in _k)) for a in _have):
                continue
            _have.append(_k)
            rows.append({
                '省': x.get('rg') or '',
                '市': x.get('city') or '',
                '区县/片区': '',
                '项目名称': _t,
                '业主': x.get('buyer') or '',
                '建设内容与规模': x.get('snip') or '',
                '项目类型': '规划批复',
                '阶段（2026-11 实况）': '规划批复',
                '投资额(亿元)': None,
                '我们的切入方式': '',
                '原文依据': x.get('p') or '省发改委·规划批复',
                '批复依据（文号/日期）': (x.get('d') or ''),
                '来源链接': x.get('url') or '',
                '能进不能进（排他性说明）': '',
            })
            _fgw_n += 1
        print('规划批复并入 %d 条（源 %s）' % (_fgw_n, os.path.basename(_fgw_path)))
    except FileNotFoundError:
        print('⚠ 未找到 %s，规划前瞻只出 xlsx 那部分' % _fgw_path)
    except Exception as _e:
        print('⚠ 规划批复并入失败（%s），继续用 xlsx' % str(_e)[:60])

    cols = {k: [] for k in ('id', 'p', 'c', 'd', 'n', 'b', 'ct', 'k', 'e',
                            'a', 'st', 'src', 'doc', 'u', 'lk', 'ea', 'g', 'sc', 'pp', 'cl')}

    for i, r in enumerate(rows):
        name = str(r['项目名称'] or '')
        content = str(r['建设内容与规模'] or '')
        kind = str(r['项目类型'] or '')
        stage = str(r['阶段（2026-11 实况）'] or '')
        amt_y = amt_to_yuan(r['投资额(亿元)'])

        # 业务分类：拿项目名 + 建设内容 + 业主一起判。业主名里常带行业信息
        # （「XX 钢铁」「XX 化工」），这是规划文本里最可靠的行业信号。
        biz, sub = classify_plan(name, content, r['业主'], kind)
        sc_scale = parse_scale(name + ' ' + content)
        # st 统一成「立项公示」——规划里的项目还没挂网，这是平台里最接近的阶段档
        g, sc = grade(biz, sub, '立项公示', amt_y, sc_scale, name + ' ' + content, name, content)

        is_pipe = any(k in name for k in PIPE_KW) or kind in ('热网', '热网+换热站')
        if is_pipe:
            # ⚠ 平台原逻辑 `min(sco,44)` 有个坑：C 档门槛是 45 分（见 build_data.grade），
            #   压到 44 等于把「纯管网降级为 C」实际做成了「打进 D」。口径说明里写的是 C。
            #   这里按口径给 45~48 区间：进 C 但排在正常 C 的末尾，不会被误当主攻。
            sc = min(max(sc, 45), 48)
            g = 'C'
        elif biz == '能源清洁高效利用' and g == 'D' and not is_pipe:
            # 主业热源项目不该出现在 D 档（D 在平台上等于「非主业」）。
            # 少数条目规划原文只写了一句"供热改造"、没给规模，size_score 拿 0 分，
            # 叠上 is_pure_pipe 误判就掉到 44。按"文本没写清"处理成 C，而不是当成非主业。
            sc, g = 45, 'C'

        # 关闭判定：整条关闭置 X，部分关闭压到 C（还有剩余标段，值得看一眼但别当主攻）
        cl = close_level(stage, r['能进不能进（排他性说明）'])
        if cl == 2:
            g = 'X'
        elif cl == 1 and g in ('A', 'B'):
            g = 'C'

        cols['id'].append('Q%07d' % i)
        cols['p'].append(r['省'] or '')
        cols['c'].append(r['市'] or '')
        cols['d'].append(r['区县/片区'] or '')
        cols['n'].append(name)
        cols['b'].append(r['业主'] or '')
        cols['ct'].append(content)
        cols['k'].append(kind)
        cols['e'].append(r['我们的切入方式'] or '')
        cols['a'].append(amt_y / 1e8 if amt_y else None)
        cols['st'].append(stage)
        cols['src'].append(r['原文依据'] or '')
        cols['doc'].append(r['批复依据（文号/日期）'] or '')
        cols['u'].append(r['来源链接'] or '')
        cols['lk'].append(r['能进不能进（排他性说明）'] or '')
        cols['ea'].append(EARLY_MAP.get(stage, '供热规划'))
        cols['g'].append(g)
        cols['sc'].append(sc)
        cols['pp'].append(1 if is_pipe else 0)
        cols['cl'].append(cl)

    # 排序：已关闭沉底 → 非管网在前 → 分数高在前 → 投资大的在前
    order = sorted(range(len(rows)),
                   key=lambda i: (cols['cl'][i], cols['pp'][i], -cols['sc'][i],
                                  -(cols['a'][i] or 0), cols['p'][i], cols['c'][i]))
    for k in cols:
        cols[k] = [cols[k][i] for i in order]

    n_pipe = sum(cols['pp'])
    data = {
        'n': len(rows),
        'gen': time.strftime('%Y-%m-%d'),
        'cols': cols,
        'meta': {
            'pipe': n_pipe,
            'core': len(rows) - n_pipe,
            'amt': round(sum(cols['a'][i] or 0 for i in range(len(rows))), 2),
            'src': '各地热电联产/供热规划正文 25 份 + 省发改委规划批复原文',
            'fgw': _fgw_n,
        },
    }
    js = 'window.DATA_PLAN=' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';'
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(js)

    from collections import Counter
    print('条数', len(rows), '| 热网类', n_pipe, '| 主业类', len(rows) - n_pipe)
    print('档位', dict(Counter(cols['g'])))
    print('分数区间', min(cols['sc']), '-', max(cols['sc']))
    print('投资合计', data['meta']['amt'], '亿元')
    print('体积', round(os.path.getsize(OUT) / 1024), 'KB ->', OUT)


if __name__ == '__main__':
    main()
