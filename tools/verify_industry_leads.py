#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产业投资线索的通用回归测试；CI 只读快照，不采集、不发送、不改①库。"""
import json
import os

import industry_leads as IL
from mail_data import load_snapshot
from mail_rules import daily_routes, title_of


def check_fixtures():
    cases = [
        ({'title': '协鑫集团拟投尼日利亚300万吨电解铝项目（前期磋商，未签正式协议）'}, True, '拟投/磋商'),
        ({'title': '海螺水泥坦桑尼亚5000吨/日熟料线奠基，配套30MW自备电站及余热补汽采购推进'}, True, '能源配套采购'),
        ({'title': '中伟股份印尼四大基地近20万金吨镍产能盘点'}, False, ''),
        ({'title': '中国蓝海化工集团拟在沙特新建工厂'}, True, '拟投/磋商'),
        ({'title': '法国拉法基集团拟在越南新建熟料线'}, False, ''),
        ({'title': '印尼镍冶炼厂利用率下降'}, False, ''),
        ({'title': '中企在津巴布韦签署钢铁厂建设备忘录'}, True, '签约/框架'),
        ({'title': '某中资数据中心在巴淡备案，拟配套柴油发电和储能'}, True, '备案/核准'),
        # 2026-11-27 补采暴露的通用盲区：蒙古国、钢铁厂配套水泥厂、A股主体、
        # “拟扩建”阶段、省级企业全称、PCB 高耗能制造。
        ({'title': '中色股份入围蒙古国额尔登特铜冶炼项目，正在进一步谈判'},
         True, '拟投/磋商'),
        ({'title': '中资鼎森钢铁投资津巴布韦曼希泽20万吨水泥厂即将投产'},
         True, '投产/扩建'),
        ({'title': '风神股份公告埃及轮胎扩能项目，总投资26.81亿元'},
         True, '投产/扩建'),
        ({'title': '字节跳动拟扩建巴西AI数据中心二期，中国云厂商投资超100亿美元'},
         True, '拟投/磋商'),
        ({'title': '湖南力宇签署马来西亚沙巴130MW液冷AI智算中心合作备忘录'},
         True, '签约/框架'),
        ({'title': '胜宏科技公告向泰国越南基地增资15亿美元，建设高阶PCB厂房'},
         True, '签约/框架'),
    ]
    for row, wanted, stage in cases:
        result = IL.evaluate(row)
        assert result['ok'] == wanted, (row, result)
        if wanted:
            assert result['leadStage'] == stage, (row, result)
            assert result['energyOpportunity'] and result['leadKey']
    return len(cases)


def check_snapshot():
    snapshot = load_snapshot()
    routes = daily_routes(snapshot)
    rows = routes['industry30']
    keys = [x['leadKey'] for x in rows]
    assert len(keys) == len(set(keys)), '同一产业项目出现多个状态，未按 leadKey 取最新'
    assert all('盘点' not in title_of(x) for x in rows), '背景盘点混入新增投资'
    assert all(x.get('leadStage') and x.get('energyOpportunity') and x.get('sourceStatus') for x in rows)
    assert len(snapshot['items']) == snapshot['counts']['items'], '①库快照被改动'
    return {
        'fixtures': 14,
        'snapshotItems': len(snapshot['items']),
        'industryPool': routes['industryAudit']['pool'],
        'qualifiedLatest': routes['industryAudit']['qualifiedLatest'],
        'industry30': len(rows),
        'rows': [{'date': x.get('date') or x.get('d'), 'title': title_of(x),
                  'industry': x.get('leadIndustry'), 'stage': x.get('leadStage'),
                  'energy': x.get('energyOpportunity'), 'sourceStatus': x.get('sourceStatus'),
                  'leadKey': x.get('leadKey')} for x in rows],
    }


if __name__ == '__main__':
    count = check_fixtures()
    assert count == 14
    report = check_snapshot()
    out = os.environ.get('INDUSTRY_VERIFY_OUT')
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write('\n')
    print('INDUSTRY_LEADS_OK ' + json.dumps(report, ensure_ascii=False))
