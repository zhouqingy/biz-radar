#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""
上市公司「募投 / 投资 / 建设」公告采集（巨潮资讯网 cninfo）。

⛔ 已下线（2026-10-27，用户决定）——不要重新启用，理由：
   实测 56 家上市公司回溯 180 天只命中 **2 条**，且这 2 条在库里早就有。
   原因不是 bug，是这个渠道本身产出就低：钢铁/水泥企业的扩产技改多在子公司层面，
   达不到「单独公告」的披露标准，母公司公告里几乎全是担保、股东会、季报这类程序性内容。
   更糟的是 STOCKS 里沙钢(002075)、华友(603799) 的 orgId 前缀取法返回 0 条，
   等于一半名单是死的。投入产出比太差，不值得每天跑。
   数据文件已移到 raw/early/_off/，build_data.py 扫不到，不再重复入池。
   ⚠ 但已采到的 2 条有效情报不能跟着埋掉（华光环能北非燃机余热锅炉、首创环保铜陵 EPCO，
     都是竞对动向），已单列为 raw/early/cninfo-legacy-static.json 静态存量继续在库。
     **这个文件别删**——它是固定内容，不存在「重复采集」问题。
   ────────────────────────────────────────────────────────────────────

为什么做这个：上市公司公告会**明确披露未来 2-3 年要建什么、投多少钱**，
是所有渠道里质量最高的提前量——有业主（上市公司本身）、有金额、有时间表，
而且比发改委批复更早（董事会决议阶段就公告了）。

边界（实测确认，2026-10-10）：
  - 巨潮有稳定 JSON API（POST /new/hisAnnouncement/query），返回 PDF 直链，不需浏览器。
  - 沪市 column=sse + orgId 前缀 gssh0；深市 column=szse + 前缀 gssz0。
  - 只返回标题，没有正文，所以**地域只能靠标题里的地名判断**（见 guess_rg）。
  - 未上市的客户（青山、中天钢铁、沙钢集团、力勤、振石）不在此渠道覆盖内，
    要靠技改备案和重大项目清单补。

产出：raw/early/cninfo-<日期>.json，early 字段填「上市公告」。

用法：
  python3.11 mine_cninfo.py                # 默认近 120 天
  python3.11 mine_cninfo.py --days 30
  python3.11 mine_cninfo.py --dry          # 只打印不落盘
"""
import argparse, json, os, re, sys, time
import urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, 'raw')
EARLY_DIR = os.path.join(RAW, 'early')
API = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'

# ---- 业务相关 A 股名单 ----
# (代码, 市场 sse/szse, 简称, 注册地/空=非四地, 角色 owner=业主/epc=工程方)
#
# 关键设计：**业主与工程方必须分开**。
# 第一版把环保工程公司（龙净、菲达、高能）混在一起，结果捞到的全是它们的「中标公告」——
# 那是竞对情报，不是我们要投的标，等于白忙。
# 真正有价值的是业主（钢铁/化工/水泥/有色企业）的扩产与技改公告：那才是「未来要建什么」。
# 工程方只保留「自己投资建设」类，含「中标」的一律丢弃。
#
# 「注册地」用于标题里没有明确地名时兜底归类；非四地公司若标题无四地地名则丢弃。
STOCKS = [
    # ===== 业主：四地钢铁 / 有色 / 水泥 / 化工（我们的客户群）=====
    ('600282', 'sse', '南钢股份', '江苏', 'owner'),
    ('002075', 'szse', '沙钢股份', '江苏', 'owner'),
    ('600019', 'sse', '宝钢股份', '上海', 'owner'),
    ('600808', 'sse', '马钢股份', '安徽', 'owner'),
    ('603799', 'sse', '华友钴业', '浙江', 'owner'),
    ('000630', 'szse', '铜陵有色', '安徽', 'owner'),
    ('601609', 'sse', '金田股份', '浙江', 'owner'),
    ('601137', 'sse', '博威合金', '浙江', 'owner'),
    ('603995', 'sse', '甬金股份', '浙江', 'owner'),
    ('002318', 'szse', '久立特材', '浙江', 'owner'),
    ('600585', 'sse', '海螺水泥', '安徽', 'owner'),
    ('600985', 'sse', '淮北矿业', '安徽', 'owner'),
    ('600063', 'sse', '皖维高新', '安徽', 'owner'),
    ('002538', 'szse', '司尔特', '安徽', 'owner'),
    ('603599', 'sse', '广信股份', '安徽', 'owner'),
    ('002648', 'szse', '卫星化学', '浙江', 'owner'),
    ('002493', 'szse', '荣盛石化', '浙江', 'owner'),
    ('000703', 'szse', '恒逸石化', '', 'owner'),
    ('603225', 'sse', '新凤鸣', '浙江', 'owner'),
    ('601233', 'sse', '桐昆股份', '浙江', 'owner'),
    ('600889', 'sse', '南京化纤', '江苏', 'owner'),
    ('002165', 'szse', '红宝丽', '江苏', 'owner'),
    ('600688', 'sse', '上海石化', '上海', 'owner'),
    ('600623', 'sse', '华谊集团', '上海', 'owner'),
    ('600618', 'sse', '氯碱化工', '上海', 'owner'),
    # ===== 业主：能源投资运营平台（热电 / 发电 / 固废）=====
    ('600023', 'sse', '浙能电力', '浙江', 'owner'),
    ('000543', 'szse', '皖能电力', '安徽', 'owner'),
    ('600982', 'sse', '宁波能源', '浙江', 'owner'),
    ('002015', 'szse', '协鑫能科', '江苏', 'owner'),
    ('002479', 'szse', '富春环保', '浙江', 'owner'),
    ('601222', 'sse', '林洋能源', '江苏', 'owner'),
    ('601200', 'sse', '上海环境', '上海', 'owner'),
    ('600008', 'sse', '首创环保', '', 'owner'),
    ('601330', 'sse', '绿色动力', '', 'owner'),
    ('000035', 'szse', '中国天楹', '江苏', 'owner'),
    ('000967', 'szse', '盈峰环境', '浙江', 'owner'),
    ('300388', 'szse', '节能国祯', '安徽', 'owner'),
    ('300172', 'szse', '中电环保', '江苏', 'owner'),
    ('600475', 'sse', '华光环能', '江苏', 'owner'),
    # ===== 工程 / 设备方：只收它们「自己投资建设」的，中标类不要 =====
    ('600388', 'sse', '龙净环保', '', 'epc'),
    ('600526', 'sse', '菲达环保', '浙江', 'epc'),
    ('603588', 'sse', '高能环境', '', 'epc'),
    ('002573', 'szse', '清新环境', '', 'epc'),
    ('600970', 'sse', '中材国际', '', 'epc'),
    ('603126', 'sse', '中材节能', '', 'epc'),
    ('601868', 'sse', '中国能建', '', 'epc'),
    ('601669', 'sse', '中国电建', '', 'epc'),
    ('000928', 'szse', '中钢国际', '', 'epc'),
    ('601068', 'sse', '中铝国际', '', 'epc'),
    ('601727', 'sse', '上海电气', '上海', 'epc'),
    ('600481', 'sse', '双良节能', '江苏', 'epc'),
    ('002534', 'szse', '西子洁能', '浙江', 'epc'),
    ('002255', 'szse', '海陆重工', '江苏', 'epc'),
    ('002630', 'szse', '华西能源', '', 'epc'),
    ('603903', 'sse', '中持股份', '', 'epc'),
    ('002266', 'szse', '浙富控股', '浙江', 'epc'),
]

# 四地省名与主要城市（标题命中即确定地域）
CITY2RG = {}
for _rg, _cs in {
    '江苏': ['江苏', '南京', '苏州', '无锡', '常州', '南通', '徐州', '扬州', '镇江', '盐城',
             '泰州', '淮安', '连云港', '宿迁', '张家港', '江阴', '宜兴', '太仓', '昆山'],
    '浙江': ['浙江', '杭州', '宁波', '温州', '绍兴', '嘉兴', '台州', '金华', '湖州', '衢州',
             '丽水', '舟山', '慈溪', '余姚', '诸暨', '桐乡', '海宁'],
    '安徽': ['安徽', '合肥', '芜湖', '马鞍山', '铜陵', '安庆', '滁州', '阜阳', '宿州', '六安',
             '宣城', '淮南', '淮北', '蚌埠', '黄山', '亳州', '池州'],
    '上海': ['上海'],
}.items():
    for _c in _cs:
        CITY2RG[_c] = _rg
# 明确的外地标识：命中且没同时命中四地地名，则判为外地
OTHER_HINT = ['广东', '广西', '福建', '山东', '河北', '河南', '湖北', '湖南', '四川', '重庆',
              '江西', '陕西', '山西', '云南', '贵州', '甘肃', '辽宁', '吉林', '黑龙江',
              '内蒙古', '新疆', '宁夏', '青海', '海南', '天津', '北京', '深圳', '广州',
              '印尼', '越南', '几内亚', '刚果', '赞比亚', '沙特', '阿曼', '马来', '菲律宾']

# 项目实体词：必须出现，否则就是程序性公告（转股、制度、专项报告之类全是噪音）
# 第一版只要求「前瞻性事件词」，结果捞进来一堆「可转债转股结果暨股份变动」
# 「募集资金管理与使用制度」，这类跟项目毫无关系，宁缺毋滥，收紧为实体项目词。
PROJ_KW = ['项目', '工程', 'EPC', 'EPCO', 'BOT', '特许经营', '中标', '合同', '建设',
           '新建', '扩建', '技改', '改造', '开工', '投产', '签署', '签订', '承建',
           '总承包', '示范', '机组', '产线', '基地']
# 业务词：确保跟我们主业相关
BIZ_KW = ['热电', '余热', '发电', '供热', '锅炉', '机组', '储能', '光伏', '污水', '废水',
          # 2026-10-19 补：燃气（天然气）发电系列，属「能源清洁高效利用/热电联产」本业，此前词表缺失
          '燃气', '天然气', '燃气轮机', '联合循环', 'LNG', '分布式能源', '三联供', '冷热电',
          '中水', '脱硫', '脱硝', '超低排放', '除尘', '节能', '环保', '固废', '垃圾',
          '海水淡化', '修复', '能源', '电厂', '煤气', '烧结', '焦化', '冶金', '水泥',
          '热电联产', '综合利用', '循环', '绿色', '低碳', '零排放']
# 已完成：这类是「已经建完」，不是提前量（168 小时试运行、并网、投产、竣工）
DONE_KW = ['试运行', '168', '投产', '竣工', '并网', '投运', '验收', '移交', '达产', '结项']
# 噪音：这些一律丢弃（程序性公告）
NOISE_KW = ['股东', '董事会', '监事会', '章程', '聘任', '辞职', '担保', '理财', '回购',
            '减持', '增持', '业绩', '年度报告', '半年度报告', '季度报告', '权益分派',
            '法律意见书', '独立董事', '关联交易', '会计', '审计', '评级', '投资者关系',
            '接待日', '管理办法', '工作制度', '实施细则', '议事规则', '会议通知', '决议',
            '制度', '转股', '股份变动', '专项报告', '存放', '进展公告', '延期', '问询',
            '异动', '澄清', '风险提示', '可行性报告', '募集说明书摘要']


def fetch(code, market, se_date, page_size=30, timeout=30):
    org = ('gssh0' if market == 'sse' else 'gssz0') + code
    data = {
        'pageNum': 1, 'pageSize': page_size, 'column': market, 'tabName': 'fulltext',
        'plate': '', 'stock': '%s,%s' % (code, org), 'searchkey': '', 'secid': '',
        'category': '', 'trade': '', 'seDate': se_date, 'sortName': '', 'sortType': '',
        'isHLtitle': 'true',
    }
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(API, data=body, method='POST', headers={
        'User-Agent': UA,
        'Referer': 'http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'ignore')) or {}
    except Exception as e:
        print('   [WARN] %s 请求失败：%s' % (code, e))
        return {}


def guess_rg(title, home):
    """标题优先定地域；没地名时按公司注册地兜底；命中外地标识则判 None。"""
    hit = [rg for c, rg in CITY2RG.items() if c in title]
    if hit:
        return hit[0]
    if any(h in title for h in OTHER_HINT):
        return None
    return home or None     # 注册地非四地则 None


def keep(title):
    if any(k in title for k in NOISE_KW) or any(k in title for k in DONE_KW):
        return False
    return any(k in title for k in PROJ_KW) and any(k in title for k in BIZ_KW)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=120, help='回溯天数（默认 120）')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    end = time.strftime('%Y-%m-%d')
    start = time.strftime('%Y-%m-%d', time.localtime(time.time() - a.days * 86400))
    se = '%s~%s' % (start, end)

    out, seen = [], set()
    print('[cninfo] 回溯 %s（%d 家上市公司）' % (se, len(STOCKS)))
    checked = 0
    for code, market, name, home, role in STOCKS:
        j = fetch(code, market, se)
        anns = j.get('announcements') or []
        n = 0
        for x in anns:
            # 代码可能写错，校验返回的证券简称与预期是否对得上，对不上直接跳过该股
            sn = (x.get('secName') or '').strip()
            if sn and sn != name and name[:2] not in sn and sn[:2] not in name:
                print('   [WARN] %s 简称不符：预期 %s，实际 %s → 跳过该股' % (code, name, sn))
                break
            checked += 1
            t = (x.get('announcementTitle') or '').strip()
            t = re.sub(r'<.*?>', '', t)
            if not t or t in seen or not keep(t):
                continue
            # 工程方自己中标不算我们要投的标（那是竞对情报，微信/交易中心渠道已覆盖）
            if role == 'epc' and ('中标' in t or '候选人' in t):
                continue
            rg = guess_rg(t, home)
            if not rg:
                continue
            ts = x.get('announcementTime')
            d = time.strftime('%Y-%m-%d', time.localtime(ts / 1000)) if ts else end
            url = 'http://static.cninfo.com.cn/' + (x.get('adjunctUrl') or '').lstrip('/')
            if not x.get('adjunctUrl'):
                url = ''
            seen.add(t)
            out.append({
                't': '%s｜%s' % (name, t),
                'rg': rg, 'city': '', 'st': '', 'buyer': name, 'win': '',
                'amt': None, 'amtTxt': '', 'd': d, 'dl': '',
                'p': '巨潮资讯·上市公司公告', 'url': url,
                'snip': '上市公司公告（%s，%s）。标题未披露金额与地点细节时，'
                        '地域按标题地名或公司注册地归类，需打开原文核对。' % (name, code),
                'mode': '', 'early': '上市公告', 'expect': '',
            })
            n += 1
        if n:
            print('   %-8s %-6s 命中 %d 条' % (code, name, n))
        time.sleep(0.4)      # 低频礼貌请求

    out.sort(key=lambda x: x['d'], reverse=True)
    print('[cninfo] 合计 %d 条' % len(out))
    if a.dry:
        for x in out[:15]:
            print('   [%s] %s | %s' % (x['rg'], x['d'], x['t'][:60]))
        return

    os.makedirs(EARLY_DIR, exist_ok=True)
    fp = os.path.join(EARLY_DIR, 'cninfo-%s.json' % end)
    json.dump(out, open(fp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('[cninfo] 已写入 %s' % fp)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        # 网络类渠道失败不应阻断主流程
        print('[cninfo] 采集失败（不影响主流程）：%s' % e)
        sys.exit(0)
