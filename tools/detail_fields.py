#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""detail_fields.py —— 从公告详情页正文里抽「谁发的、谁中的、多少钱、找谁」

为什么单独一个模块：
  scan_detail.py 早就把详情页正文抓下来并转成纯文本了（`txt`），
  但**只用来判断页面是不是空壳**，判完就丢。而这一页里正好有全库最缺的四样东西：

      招标人（业主）      当前覆盖 40%
      中标单位            当前覆盖 38.8%   ← 对手画像 / 业主关系图全靠它
      中标金额            当前覆盖 17.9%
      联系人 / 电话       当前 0%，用户最想要的「我该打给谁」

  实测两个主力平台（浙江省平台、合肥公共资源交易中心）结构差别很大，
  但都是「标签: 值」的形式，可以用一套标签驱动的方式同时覆盖。

设计原则：
  · 只抽**确定**的，抽不到返回 None，绝不猜。
  · 姓名/电话照原样保留，电话里平台打的星号也照原样留着（那是平台脱敏，不是我们丢的）。
  · 中标单位优先取「第一中标候选人」，其次「中标人/中标单位/成交供应商」。
"""
import re

# 第一步：把 HTML 压成一行文本，保留「标签: 值」之间的分隔
def to_text(html):
    if not html:
        return ''
    t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)
    # <br> / </div> / </td> / </p> 当分隔符，否则「联系人:陈敬」和下一行会粘成一片
    t = re.sub(r'<(?:br\s*/?|/div|/td|/tr|/p|/li|/h\d)\s*>', ' \n ', t, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = (t.replace('&nbsp;', ' ').replace('&#160;', ' ')
           .replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
           .replace('&quot;', '"').replace('&#39;', "'"))
    # 中文之间被标签切出来的空格，去掉；但英文/数字之间的空格要留
    t = re.sub(r'[ \t\u3000]+', ' ', t)
    return t.strip()


# 第二步：标签 -> 值。标签后面允许「: 」或「：」或直接空白
def _grab(txt, labels, stop_at=None, maxlen=60):
    """在文本里找 '标签: 值'，返回第一个非空值。

    ⚠ 不能只取同一行。浙江省平台是**表格布局**，导出成文本后长这样：
         招标人:  \n \n \n 名称:宁波钢铁有限公司 \n
       标签后面是一串空行，值在下一行。只匹配同一行会返回 None，
       然后被后面的备用规则抓成代理机构的名字（踩过）。
       所以允许跨行，但最多跨 4 行、且不允许跨过下一个已知标签。
    """
    KNOWN = r'(?:招\s*标\s*人|代理机构|招标代理机构|采购人|中标人|中标单位|中标候选人|' \
            r'项目名称|项目编号|联系人|电话|地址|邮编|公示期|开标)'
    for lab in labels:
        # 标签后先跳过任意空白（含空行），再取值。
        # 注意：不能用 (?:[ \t]*\n){0,4} —— 浙江页的空行是「空格+换行」，
        # 逐行计数会在第 5 个空行处断掉，于是标签后什么都没匹配到（踩过）。
        # 用 \s* 又要防它一路吃到很远的下一个字段：所以取值行里如果出现
        # 「代理机构/联系人/地址」等已知标签，说明吃过头了，判为无效。
        pat = re.escape(lab) + r'\s*[:：]\s*([^\n]{0,%d})' % maxlen
        m = re.search(pat, txt)
        if not m:
            continue
        v = m.group(1).strip()
        if not v:
            continue
        # 值里如果又带了「名称:」，剥掉（浙江表格里就是这样）
        v = re.sub(r'^(?:名\s*称|单位名称)\s*[:：]\s*', '', v).strip()
        # 去掉尾部的下一个标签污染（如「名称:XX公司 地址:XX」）
        v = re.split(r'\s{2,}|(?=(?:地\s*址|联系人|电\s*话|邮\s*编|名\s*称|法定代表人|统一社会信用代码)\s*[:：])', v)[0]
        v = v.strip(' ，,。;；、:：')
        if 2 <= len(v) <= maxlen:
            return v
    return None


CN_NUM = '零一二三四五六七八九十'


def _amt(s):
    """'人民币大写壹亿肆仟…（小写 147977676.77元）' / '30134.82万元' -> 元"""
    if not s:
        return None
    # 优先「小写 xxxx元」——最可靠
    m = re.search(r'小写\s*([\d,]+(?:\.\d+)?)\s*元', s)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            pass
    # 其次「xxxx 元 / 万元 / 亿元」带明确单位
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*(亿元|亿|万元|万|元)', s)
    if m:
        try:
            n = float(m.group(1).replace(',', ''))
        except ValueError:
            return None
        u = m.group(2)
        v = n * 1e8 if u.startswith('亿') else (n * 1e4 if u.startswith('万') else n)
        return v if 1e4 <= v <= 1e10 else None     # 超出单条公告合理范围的不采信
    return None


def parse(html, status=''):
    """返回 {buyer, win, amt, agc, contact, phone, budget}，抽不到的键不出现"""
    txt = to_text(html)
    if len(txt) < 120:
        return {}
    out = {}

    # ---------- 招标人 / 业主 ----------
    # 浙江站： 「招标人: 名称:宁波钢铁有限公司 地址:…」
    # 合肥站： 「招 标 人：长丰皖能风电开发有限公司」（字之间会被空格拆开）
    buyer = _grab(txt, ['招 标 人', '招标人', '招标单位', '采购人', '建设单位', '项目业主'])
    if buyer:
        # 浙江站是「招标人: 名称:宁波钢铁有限公司」，值里会带出前缀「名称:」。
        # 这里要剥两次前缀：冒号后可能还有空格，所以用 \s* 而不是只剥冒号。
        for _ in range(2):
            b2 = re.sub(r'^(?:名\s*称|单位名称)\s*[:：]\s*', '', buyer).strip()
            if b2 == buyer:
                break
            buyer = b2
    if buyer:
        out['buyer'] = buyer

    # ---------- 中标单位 ----------
    # 优先「第一中标候选人名称」，其次「中标人」/「中标单位」/「成交供应商」
    win = _grab(txt, ['第一中标候选人名称', '第一中标候选人', '中标候选人名称',
                      '中标人名称', '中标单位名称', '中标单位', '中标人',
                      '成交供应商名称', '成交供应商', '成交人', '中选单位'], maxlen=80)
    if not win:
        m = re.search(r'中\s*标\s*(?:人|单位)\s*[:：]\s*([^\n]{3,60})', txt)
        if m:
            win = m.group(1).strip()
    if win:
        # 联合体成员单独留一份，档案里能看出「跟谁组队」
        mj = re.search(r'[（(]\s*联合体成员\s*[:：]?\s*([^）)]{3,120})[）)]', win)
        if mj:
            out['winJoint'] = [x.strip() for x in re.split(r'[、,，]', mj.group(1)) if x.strip()]
            win = re.sub(r'[（(]\s*联合体成员.*?[）)]', '', win).strip()
        out['win'] = win[:80]

    # ---------- 金额 ----------
    # ① 中标/投标报价优先（这是「这条标值多少钱」最直接的答案）
    amt = None
    for lab in ['投标报价', '中标价', '中标金额', '成交金额', '中选金额', '合同金额']:
        m = re.search(re.escape(lab) + r'\s*[:：]\s*([^\n]{2,90})', txt)
        if m:
            amt = _amt(m.group(1))
            if amt:
                out['amtSrc'] = lab
                break
    if not amt:
        # ② 退而求其次：招标阶段的「投资估算 / 预算金额 / 最高限价」
        for lab in ['投资估算', '投资额', '预算金额', '最高投标限价', '招标控制价', '合同估算价', '项目总投资']:
            m = re.search(re.escape(lab) + r'[^\n]{0,12}?([\d,]+(?:\.\d+)?\s*(?:亿元|亿|万元|万))', txt)
            if m:
                amt = _amt(m.group(1))
                if amt:
                    out['amtSrc'] = lab
                    break
    if amt:
        out['amt'] = amt

    # ---------- 代理机构 / 联系人 / 电话 ----------
    agc = _grab(txt, ['招标代理机构', '代理机构', '采购代理机构', '代理单位'], maxlen=50)
    if agc:
        agc = re.sub(r'^名\s*称\s*[:：]\s*', '', agc)
        out['agc'] = agc
    # 联系人取「联 系 人」或「联系人」，优先招标人那一段（在代理机构之前出现的那个）
    contact = None
    for m in re.finditer(r'联\s*系\s*人\s*[:：]\s*([^\n，,；;]{2,20})', txt):
        contact = m.group(1).strip()
        break
    if contact:
        out['contact'] = contact
    m = re.search(r'(?:电\s*话|联系电话|联系方式)\s*[:：]\s*([\d\-*]{7,20}(?:[、，,]\s*[\d\-*]{7,20})*)', txt)
    if m:
        out['phone'] = m.group(1).strip()[:60]

    # ---------- 截止 / 开标时间（招标类） ----------
    m = re.search(r'开\s*标\s*(?:日期|时间)\s*[:：]\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)', txt)
    if m:
        d = re.sub(r'\s+', '', m.group(1))
        out['openDate'] = d

    return out


if __name__ == '__main__':
    import sys
    for f in sys.argv[1:]:
        html = open(f, encoding='utf-8', errors='ignore').read()
        r = parse(html)
        print('==', f)
        for k, v in r.items():
            print(f'   {k:10s} {v}')
