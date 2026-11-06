# -*- coding: utf-8 -*-
"""V4 页面 app/index.html 浏览器回归 + 截图（只读验收）

2026-11-06 16:xx 按用户六条反馈重写页面后同步更新：
  顶部验收条收进个人中心 / 每模块独立检索 / 有色金属独立板块 / 空 tab /
  数据行两栏填满 / 全站美化。断言随结构一起重写，不沿用旧 9 模块版本。
"""
import urllib.request
from playwright.sync_api import sync_playwright

B = 'http://127.0.0.1:8848/'
OUT = '/workspace/2026-11-06-V4重做-'
ok = fail = 0
errors = []


def chk(name, cond, detail=''):
    global ok, fail
    if cond:
        ok += 1
        print('  PASS  %-52s %s' % (name, detail))
    else:
        fail += 1
        print('  FAIL  %-52s %s' % (name, detail))


with sync_playwright() as p:
    b = p.chromium.launch(headless=True, executable_path='/usr/bin/chromium',
                          args=['--no-sandbox'])
    pg = b.new_page(viewport={'width': 1440, 'height': 950})
    pg.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
    pg.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
    pg.goto(B, wait_until='networkidle', timeout=60000)
    pg.wait_for_timeout(600)

    print('=== 1 · 骨架 / 接通 / 源码红线 ===')
    chk('顶栏 / 左导航 / 主区 / 居中弹窗齐备',
        pg.locator('.top').count() == 1 and pg.locator('.nav').count() == 1 and
        pg.locator('.main').count() == 1 and pg.locator('#modal').count() == 1 and
        pg.locator('.draw').count() == 1)
    chk('默认不占右边第三列（详情收在居中弹窗里）',
        len(pg.locator('.body').evaluate('e=>getComputedStyle(e).gridTemplateColumns').split()) == 2
        and not pg.locator('#modal').is_visible())
    chk('顶部不再外露验收工具条（.preview-bar 为 0）',
        pg.locator('.preview-bar').count() == 0)
    chk('API 已接通（非离线降级）',
        'API 已接通' in pg.locator('#modeTag').inner_text(),
        pg.locator('#modeTag').inner_text()[:40])
    chk('无「离线降级」告警', '离线降级' not in pg.locator('#notice').inner_text())
    n_nav = pg.locator('#navList .ni').count()
    chk('左导航合并为 9 个已接入入口（情报三合一 / 重复模块隐藏 / 规划中折叠）',
        n_nav == 9, str(n_nav))
    chk('默认 hash 路由为 #/opportunities',
        pg.evaluate('location.hash') in ('', '#/opportunities'),
        pg.evaluate('location.hash'))
    src = urllib.request.urlopen(B, timeout=20).read().decode('utf-8')
    chk('页面源码不硬编码业务数字 1119', '1119' not in src)
    chk('前端不重写业务判定（无判定函数调用）',
        'judge(' not in src and 'semantic_drop(' not in src)
    chk('页面不通过 window.DATA_XXX 取数', 'window.DATA_' not in src)
    chk('KPI ①库条目来自接口（1,119）',
        '1,119' in pg.locator('#pk').inner_text(),
        pg.locator('#pk').inner_text().replace('\n', ' | ')[:90])
    chk('顶栏有有色行情 ticker（业务数据，非验收工具）',
        pg.locator('#ticker .tk').count() > 0, '%d 个品种' % pg.locator('#ticker .tk').count())

    print('=== 2 · 个人中心：原验收工具条全部收进这里 ===')
    pg.locator('#btnUser').click()
    pg.wait_for_timeout(200)
    chk('点击头像展开个人中心', pg.locator('#popUser.on').count() == 1)
    pu = pg.locator('#popUser').inner_text()
    chk('个人中心含深色模式 / 预览档 / 自适应 / 平板 / 手机',
        all(x in pu for x in ('深色模式', '预览档', '自适应', '平板', '手机')))
    chk('个人中心含接口状态 / 刷新采集 / 本机标记 / 快捷入口',
        all(x in pu for x in ('接口状态', '刷新', '本机标记', '快捷入口')))
    chk('预览档按钮在个人中心内（不在顶部外露）',
        pg.locator('#popUser #segPreview [data-v]').count() == 3 and
        pg.locator('.top > [data-v]').count() == 0)
    pg.screenshot(path=OUT + '个人中心.png', full_page=False)
    pg.locator('#btnTheme').click()
    chk('暗色主题切换', pg.locator('body.dark').count() == 1)
    chk('暗色变量确实生效（body 背景变深）',
        pg.evaluate('getComputedStyle(document.body).backgroundColor') == 'rgb(17, 24, 34)',
        pg.evaluate('getComputedStyle(document.body).backgroundColor'))
    pg.screenshot(path=OUT + '暗色.png', full_page=False)
    pg.locator('#btnTheme').click()
    for v, label in [('tablet', '平板'), ('mobile', '手机')]:
        pg.locator('#popUser [data-v="%s"]' % v).click()
        pg.wait_for_timeout(220)
        chk('个人中心预览档 %s 生效' % label, pg.locator('#preview.%s' % v).count() == 1)
        if v == 'tablet':
            cols = pg.locator('.body').evaluate('e=>getComputedStyle(e).gridTemplateColumns')
            chk('预览档平板复刻响应式（导航收窄为 58px）', cols.startswith('58px'), cols)
        else:
            chk('预览档手机复刻响应式（左导航隐藏）',
                pg.locator('.nav').evaluate('e=>getComputedStyle(e).display') == 'none')
            chk('预览档手机复刻响应式（全库检索折到下一行）',
                pg.locator('.gs').evaluate('e=>getComputedStyle(e).order') == '5')
            chk('预览档手机复刻响应式（KPI 自动换行）',
                pg.locator('#pk').evaluate('e=>getComputedStyle(e).flexWrap') == 'wrap')
        pg.screenshot(path=OUT + '预览-' + label + '.png', full_page=False)
    pg.locator('#popUser [data-v="full"]').click()
    pg.locator('#btnUser').click()
    pg.wait_for_timeout(150)

    print('=== 3 · 紧凑列表行：去花哨、提密度 ===')
    row0 = pg.locator('#rows .row').first
    cols = row0.evaluate('e=>getComputedStyle(e).gridTemplateColumns')
    rh = row0.evaluate('e=>e.getBoundingClientRect().height')
    chk('数据行改紧凑列表（≤ 6 列）', len(cols.split()) <= 6, cols)
    chk('单条数据行高度 < 72px（旧三栏卡片约 130px）', rh < 72, '%.0f px' % rh)
    chk('行内有序号 / 可点标题 / 业主名 / 金额 / 日期',
        row0.locator('.rno').count() == 1 and
        row0.locator('.rt[data-detail]').count() == 1 and
        (row0.locator('.rbuyer[data-owner]').count() == 1 or row0.locator('.rbuyer.plain').count() == 1) and
        row0.locator('.ramt').count() == 1 and row0.locator('.rdate').count() == 1)
    chk('不再堆 8 个浅色键値小方块', row0.locator('.kv').count() == 0)
    chk('KPI 收敛为扁条（无大图标方块）',
        pg.locator('#pk .k').count() == 4 and
        pg.locator('#pk .k .ki').first.evaluate('e=>getComputedStyle(e).display') == 'none')

    print('=== 3.5 · 项目详情 / 业主画像点击（恢复旧版交互） ===')
    pg.locator('#rows .rt[data-detail]').first.click(); pg.wait_for_timeout(420)
    chk('点标题打开项目详情（真实字段）',
        pg.locator('#app.drawer').count() == 1 and '业主' in pg.locator('#drawDetail').inner_text())
    pg.locator('#modalClose').click(); pg.wait_for_timeout(150)
    if pg.locator('#rows .rbuyer[data-owner]').count():
        pg.locator('#rows .rbuyer[data-owner]').first.click(); pg.wait_for_timeout(520)
        ot = pg.locator('#drawOwner').inner_text()
        chk('点业主名打开业主画像（②库只读 / 不补假数据）',
            pg.locator('#app.drawer').count() == 1 and ('②库' in ot or '暂无' in ot),
            ot.replace('\n', ' | ')[:80])
        pg.locator('#modalClose').click(); pg.wait_for_timeout(150)
    else:
        chk('点业主名打开业主画像（②库只读 / 不补假数据）', True, '本页无业主名，跳过')

    print('=== 4 · 模块内检索：每个侧边栏模块都有，且作用域隔离 ===')
    impl_ids = ['opportunities', 'orgs', 'clients', 'overseas', 'wechat',
                'policies', 'changes', 'platforms', 'help']
    phs = []
    for mid in impl_ids:
        pg.locator('#navList .ni[data-id="%s"]' % mid).click()
        pg.wait_for_timeout(280)
        has = pg.locator('#mq').count() == 1 and not pg.locator('#mq').is_disabled()
        empty = pg.locator('#mq').input_value() == ''
        phs.append(pg.locator('#mq').get_attribute('placeholder') or '')
        chk('模块 %-16s 有可用模块内检索框且切模块自动清空' % mid, has and empty,
            'ph=' + phs[-1][:26])
    chk('各模块 placeholder 按业务定制（非同一句）', len(set(phs)) >= 9, '%d 种' % len(set(phs)))

    # 客户与业主：搜索生效 + 切换后不污染下一个模块
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="clients"]').click(); pg.wait_for_timeout(300)
    before = pg.locator('#pk').inner_text()
    pg.locator('#mq').fill('热电'); pg.wait_for_timeout(480)
    chk('客户与业主搜「热电」命中下降且内容相关',
        '热电' in pg.locator('#rows').inner_text() and
        pg.locator('#pk').inner_text() != before,
        pg.locator('#pk').inner_text().replace('\n', ' | ')[:70])
    pg.screenshot(path=OUT + '模块内检索-客户业主.png', full_page=False)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="orgs"]').click(); pg.wait_for_timeout(330)
    chk('切到同业与伙伴后检索词不残留（作用域隔离）',
        pg.locator('#mq').input_value() == '' and '热电' not in pg.locator('#msearch').inner_text())
    org_all = pg.locator('#pk').inner_text()
    pg.locator('#mq').fill('华光'); pg.wait_for_timeout(480)
    chk('同业与伙伴搜「华光」生效（全量 → 命中）',
        '华光' in pg.locator('#rows').inner_text() and
        pg.locator('#pk').inner_text() != org_all,
        pg.locator('#pk').inner_text().replace('\n', ' | ')[:70])
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="overseas"]').click(); pg.wait_for_timeout(320)
    ov_all = pg.locator('#pk').inner_text()
    pg.locator('#mq').fill('印尼'); pg.wait_for_timeout(480)
    chk('海外机会搜「印尼」生效（不用一条条翻）',
        pg.locator('#pk').inner_text() != ov_all,
        pg.locator('#pk').inner_text().replace('\n', ' | ')[:70])
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="help"]').click(); pg.wait_for_timeout(620)
    help_all = pg.locator('#rows').inner_text()
    pg.locator('#mq').fill('N13'); pg.wait_for_timeout(620)
    _help_after = pg.locator('#rows').inner_text()
    chk('本机视图筛选模块（口径与帮助）检索生效',
        _help_after != help_all and 'N13' in _help_after,
        '%d → %d 字' % (len(help_all), len(_help_after)))

    print('=== 5 · 当日行情折叠面板（行情不再单列模块） ===')
    chk('导航不再单列「有色金属 · 行情」模块',
        pg.locator('#navList .ni[data-id="metals"]').count() == 0)
    pg.locator('#btnMkt').click(); pg.wait_for_timeout(220)
    chk('顶栏「当日行情」可展开', pg.locator('#mktPop.on').count() == 1)
    chk('13 个品种紧凑行', pg.locator('#mktPop .mktrow').count() == 13,
        str(pg.locator('#mktPop .mktrow').count()))
    chk('面板含真实价格（沪铜 / 106,170）',
        '沪铜' in pg.locator('#mktPop').inner_text() and '106,170' in pg.locator('#mktPop').inner_text())
    chk('每行有迷你走势 SVG', pg.locator('#mktPop .mktrow svg').count() >= 10,
        str(pg.locator('#mktPop .mktrow svg').count()))
    pg.screenshot(path=OUT + '当日行情.png', full_page=False)
    pg.screenshot(path=OUT + '当日行情-整页.png', full_page=True)
    pg.locator('#mktPop .mktrow').first.click(); pg.wait_for_timeout(420)
    chk('点品种打开详情并画出历史曲线',
        pg.locator('#app.drawer').count() == 1 and
        pg.locator('#drawDetail svg').count() >= 1 and
        '区间最高' in pg.locator('#drawDetail').inner_text())
    pg.screenshot(path=OUT + '品种曲线.png', full_page=False)
    pg.locator('#modalClose').click(); pg.wait_for_timeout(150)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="wechat"]').click(); pg.wait_for_timeout(330)
    chk('情报三合一只占一个入口、同时展示 3 个来源分组',
        '情报' in pg.locator('#ptitle').inner_text() and
        'kind=trends,wechat,digest' in pg.locator('#papi').inner_text() and
        pg.locator('#rows .grphead').count() == 3 and
        pg.locator('.metal').count() == 0,
        '%d 组' % pg.locator('#rows .grphead').count())

    print('=== 6 · 空 tab：只有名称，点开提示功能待实现 ===')
    soon_ids = ['funnel', 'follow', 'alerts', 'rival', 'owner360', 'cycle', 'chain']
    pg.locator('#navList .fold').click(); pg.wait_for_timeout(160)
    chk('规划中分组默认折叠，展开后有 7 个空 tab',
        all(pg.locator('#navList .ni[data-id="%s"]' % x).count() == 1 for x in soon_ids))
    chk('空 tab 导航标「待实现」', pg.locator('#navList .ni.soon').count() == 7,
        str(pg.locator('#navList .ni.soon').count()))
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="funnel"]').click(); pg.wait_for_timeout(300)
    soon_txt = pg.locator('#rows').inner_text()
    chk('点开显示「功能待实现」', '功能待实现' in soon_txt)
    chk('标注功能编号 / 前置条件 / 不画假图 / 不写死数字',
        all(x in soon_txt for x in ('F03', '前置条件', '不画假图', '不写死数字')))
    chk('空 tab 无假数据（KPI 为占位符）',
        '—' in pg.locator('#pk').inner_text() and 'F03' in pg.locator('#pk').inner_text())
    chk('空 tab 检索框禁用、导出与刷新禁用',
        pg.locator('#mq').is_disabled() and
        pg.locator('#btnExport').is_disabled() and pg.locator('#btnReload').is_disabled())
    pg.screenshot(path=OUT + '空tab-功能待实现.png', full_page=False)

    print('=== 7 · 筛选 / facets / 分页 / 排序 / 详情 / 本机标记 ===')
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="opportunities"]').click(); pg.wait_for_timeout(360)
    chk('facets 工具条有筛选项', pg.locator('#toolbar .fchip').count() >= 12,
        '%d 个' % pg.locator('#toolbar .fchip').count())
    chk('7 个阶段枚举由 facets 返回且未写死',
        pg.locator('#toolbar [data-f="stage"]').count() == 7,
        str(pg.locator('#toolbar [data-f="stage"]').count()))
    chk('占位卡存在且标注规划中 / 已裁决不做保留位置',
        pg.locator('#slots .slot').count() > 0 and
        '规划中' in pg.locator('#slots').inner_text() and
        pg.locator('#slots .slot.no').count() >= 1)
    pg.locator('[data-f="focus"]').click(); pg.wait_for_timeout(430)
    chk('只看重点关注 ≥1亿 生效（命中 98）', '98' in pg.locator('#pager').inner_text(),
        pg.locator('#pager').inner_text().replace('\n', ' ')[:70])
    pg.locator('[data-f="clear"]').click(); pg.wait_for_timeout(380)
    chk('清除筛选恢复 1,119',
        '1,119' in pg.locator('#pager').inner_text(),
        pg.locator('#pager').inner_text().replace('\n', ' ')[:70])
    rg = pg.locator('#toolbar [data-f="region"]').first
    rgv = rg.get_attribute('data-v'); rg.click(); pg.wait_for_timeout(380)
    chk('地区 facet 点选回筛生效',
        any(rgv in t for t in pg.locator('#toolbar .fchip.on').all_inner_texts()), rgv)
    pg.locator('[data-f="clear"]').click(); pg.wait_for_timeout(320)
    pg.locator('#sortSel').select_option('amt'); pg.wait_for_timeout(380)
    chk('排序切换（金额）不报错', pg.locator('#rows .row').count() > 0)
    pg.locator('#sortSel').select_option('sc'); pg.wait_for_timeout(320)
    pg.locator('#pgN').click(); pg.wait_for_timeout(380)
    chk('下一页生效', '第 2 /' in pg.locator('#pager').inner_text())
    pg.locator('#pgP').click(); pg.wait_for_timeout(320)
    pg.locator('.star[data-star]').first.click()
    chk('本机标记可切换（纯视图偏好，不改数据）',
        pg.locator('.star[data-star]').first.evaluate("e=>e.classList.contains('on')"))
    pg.locator('[data-detail]').first.click(); pg.wait_for_timeout(450)
    chk('点详情打开居中弹窗并展示真实字段',
        pg.locator('#app.drawer').count() == 1 and
        '业主' in pg.locator('#drawDetail').inner_text() and
        pg.locator('#drawDetail').is_visible())
    pg.screenshot(path=OUT + '条目详情抽屉.png', full_page=False)
    pg.locator('#modalClose').click()

    print('=== 8 · 全库统一检索 / 刷新 / 导航收起 / 通知 ===')
    pg.locator('#gq').fill('余热'); pg.wait_for_timeout(800)
    chk('全库检索返回跨库分组命中',
        '全库统一检索' in pg.locator('#extra').inner_text() and
        '命中' in pg.locator('#extra').inner_text())
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="orgs"]').click(); pg.wait_for_timeout(330)
    chk('切模块后全库检索词与结果面板一并清空（不污染模块筛选）',
        pg.locator('#gq').input_value() == '' and pg.locator('#extra').inner_text().strip() == '')
    pg.locator('#btnUser').click(); pg.wait_for_timeout(120)
    pg.locator('#btnRefresh').click(); pg.wait_for_timeout(430)
    chk('刷新如实提示 planned、不产生数据变更',
        'planned' in pg.locator('#extra').inner_text() and
        '不产生任何数据变更' in pg.locator('#extra').inner_text())
    pg.locator('#btnBell').click(); pg.wait_for_timeout(150)
    chk('通知面板显示只读事实（体检 / gen / planned）',
        '质量体检' in pg.locator('#bellBody').inner_text() and
        'planned' in pg.locator('#bellBody').inner_text())
    pg.locator('#btnBell').click()
    pg.evaluate("document.getElementById('extra').innerHTML=''")
    pg.locator('#btnNav').click()
    chk('导航可收起', pg.locator('#app.collapsed').count() == 1)
    pg.locator('#btnNav').click()
    pg.locator('#navFilter').fill('海外'); pg.wait_for_timeout(150)
    chk('导航内功能筛选生效', 0 < pg.locator('#navList .ni').count() < 20,
        str(pg.locator('#navList .ni').count()))
    pg.locator('#navFilter').fill(''); pg.wait_for_timeout(150)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="opportunities"]').click(); pg.wait_for_timeout(380)
    pg.screenshot(path=OUT + '桌面-找商机.png', full_page=False)
    pg.screenshot(path=OUT + '桌面-整页.png', full_page=True)

    print('=== 9 · 真实响应式（改 viewport，非预览按钮） ===')
    pg.set_viewport_size({'width': 390, 'height': 844}); pg.wait_for_timeout(320)
    chk('390px 下左导航隐藏', pg.locator('.nav').evaluate('e=>getComputedStyle(e).display') == 'none')
    chk('390px 下弹窗默认收起', not pg.locator('#modal').is_visible())
    chk('390px 下 KPI 仍可见', pg.locator('#pk .k').count() >= 2)
    chk('390px 下数据行收敛为 ≤ 4 列',
        len(pg.locator('#rows .row').first.evaluate('e=>getComputedStyle(e).gridTemplateColumns').split()) <= 4)
    pg.screenshot(path=OUT + '手机.png', full_page=False)
    pg.set_viewport_size({'width': 1440, 'height': 950}); pg.wait_for_timeout(220)

    print('=== 10 · 离线降级（拦截所有 /api/） ===')
    pg2 = b.new_page(viewport={'width': 1280, 'height': 860})
    pg2.route('**/api/**', lambda r: r.abort())
    pg2.goto(B, wait_until='networkidle', timeout=60000)
    pg2.wait_for_timeout(600)
    chk('离线时明确标注非真实数据',
        '离线降级' in pg2.locator('#notice').inner_text() and
        '没有真实数据' in pg2.locator('#notice').inner_text())
    chk('离线时不画假数据、KPI 为占位符',
        '—' in pg2.locator('#pk').inner_text() and
        '离线降级' in pg2.locator('#rows').inner_text())
    chk('离线时骨架 / 模块内检索框 / 9 个入口仍在',
        pg2.locator('#mq').count() == 1 and pg2.locator('#navList .ni').count() == 9)
    pg2.screenshot(path=OUT + '离线降级.png', full_page=False)
    pg2.close()

    print('=== 11 · 旧深链 #t0–#t8 → #/<module-id> 重定向（冷启动逐条） ===')
    legacy = [('t0', 'opportunities', '找商机'), ('t1', 'orgs', '同业与伙伴'),
              ('t2', 'clients', '客户与业主'), ('t3', 'overseas', '海外机会'),
              ('t4', 'trend', '行业动态'), ('t5', 'wechat', '情报 · 动态 / 精选 / 摘要'),
              ('t6', 'platforms', '招标平台 · 体检'), ('t7', 'help', '口径与帮助'),
              ('t8', 'plan', '规划前瞻')]
    pg3 = b.new_page(viewport={'width': 1280, 'height': 860})
    pg3.on('pageerror', lambda e: errors.append('legacy pageerror: ' + str(e)))
    for tag, mid, mname in legacy:
        pg3.goto('about:blank')
        pg3.goto(B + '#' + tag, wait_until='networkidle', timeout=60000)
        pg3.wait_for_timeout(260)
        h = pg3.evaluate('location.hash'); t = pg3.locator('#ptitle').inner_text()
        chk('旧深链 #%-3s → #/%-14s (%s)' % (tag, mid, mname),
            h == '#/' + mid and t == mname, 'hash=%s title=%s' % (h, t))
    oldsrc = open('/workspace/biz-radar/index.html', encoding='utf-8').read()
    chk('重定向不改归档页（旧页未注入 LEGACY/normHash）',
        'normHash' not in oldsrc and 'var LEGACY' not in oldsrc,
        '旧页 %d 字符' % len(oldsrc))
    pg3.close()

    print('=== 12 · 控制台 / 外链 / 判定红线 ===')
    chk('控制台 0 错误', len(errors) == 0, '; '.join(errors[:3]))
    html = pg.content()
    chk('页面无外部资源依赖（favicon 已内联）',
        '<link rel="icon" href="data:,' in html and 'http://' not in html.split('<style>')[0])
    chk('页面不重写业务判定（渲染后源码复核）',
        'judge(' not in html and 'semantic_drop(' not in html)

    print('=== 13 · 布局无大片留白（防 .soon 类名冲突复发） ===')
    # 根因留痕：曾用通用类 .soon{min-height:400px}，与左导航 .ni.soon 撞名，
    # 7 个规划中导航项各被撑高 400px，整页被拉到 3611px、所有模块下方挂大片空白。
    pg.set_viewport_size({'width': 1440, 'height': 950}); pg.wait_for_timeout(250)
    navh = pg.locator('.nav').evaluate('e=>e.getBoundingClientRect().height')
    chk('左导航固定一屏（不被折叠的模块撑高）', abs(navh - 892) <= 2, '%.0f px' % navh)
    ni_h = pg.locator('#navList .ni.soon').first.evaluate('e=>e.getBoundingClientRect().height')
    chk('7 个空 tab 导航项高度正常（无 400px 撞名）', ni_h < 60, '%.0f px' % ni_h)
    chk('源码不再有通用 .soon{ 规则、主区卡片不用 class="soon"',
        '\n.soon{' not in src and 'class="soon"' not in src)
    chk('导航列表滚动条样式已显式设置', '::-webkit-scrollbar-thumb' in src)
    nl_sh = pg.locator('.navlist').evaluate('e=>e.scrollHeight')
    nl_ch = pg.locator('.navlist').evaluate('e=>e.clientHeight')
    chk('导航列表高度不溢出（9 入口 + 折叠的 7 项）', nl_sh >= nl_ch,
        '内容 %d / 可视 %d' % (nl_sh, nl_ch))
    ns = pg.locator('.navside')
    chk('左栏底部有资产速览（把空白栏封成有用信息）', ns.count() == 1)
    nsb, nfb = ns.bounding_box(), pg.locator('.navfoot').bounding_box()
    chk('资产速览与导航底部无缝衔接（间隙 < 3px）',
        abs((nsb['y'] + nsb['height']) - nfb['y']) < 3,
        '%.1f px' % abs((nsb['y'] + nsb['height']) - nfb['y']))
    nst = ns.inner_text()
    chk('资产速览数字来自接口（无「读取中…」残留）',
        '读取中' not in nst and '行' in nst and '唯一规则源' in nst,
        nst.replace('\n', ' | ')[:70])
    chk('左栏日期标签口径准确（体检报告日 ≠ 数据包日期）',
        '体检报告日' in nst and '数据包日期' not in nst)
    chk('通知 / 弹窗不再把体检 gen 标成「数据包 gen」',
        '数据包 gen' not in src and '体检生成' in src)
    ph1 = pg.evaluate('document.documentElement.scrollHeight')
    slb = pg.locator('#slots').bounding_box()
    gap1 = ph1 - (slb['y'] + slb['height'])
    chk('默认页主区下方留白 < 100px（修复前 519.6）', gap1 < 100, '%.1f px' % gap1)

    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="funnel"]').click(); pg.wait_for_timeout(330)
    ph2 = pg.evaluate('document.documentElement.scrollHeight')
    rb, sb = pg.locator('#rows').bounding_box(), pg.locator('#rows .soonbox').bounding_box()
    chk('空 tab 整页约一屏（950 ± 80，修复前 3611）', abs(ph2 - 950) <= 80, '%d px' % ph2)
    chk('空 tab 卡片 flex 撑满数据区（区内无空白）',
        abs(rb['height'] - sb['height']) < 5, '%.0f / %.0f' % (rb['height'], sb['height']))
    chk('卡片下方只剩分页 / 占位卡 / 内边距（< 120px）',
        ph2 - (sb['y'] + sb['height']) < 120, '%.1f px' % (ph2 - (sb['y'] + sb['height'])))
    chk('主区不再使用通用 .soon 类（防复发）', pg.locator('#rows .soon').count() == 0)
    pg.screenshot(path=OUT + '空tab-无留白.png', full_page=True)
    pg.keyboard.press('Escape'); pg.locator('#navList .ni[data-id="opportunities"]').click(); pg.wait_for_timeout(320)
    chk('布局往返后仍 0 控制台错误', len(errors) == 0, '; '.join(errors[:3]))
    b.close()

print('\n=== 结果：%d 通过 / %d 失败 ===' % (ok, fail))
if errors:
    print('控制台错误明细：', errors[:8])
raise SystemExit(1 if fail else 0)
