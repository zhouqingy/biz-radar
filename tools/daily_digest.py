#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旧命令兼容入口；实际生成、筛选和发送全部收口到 send_daily.py。"""
import sys

from send_daily import main as unified_main


def main():
    args = sys.argv[1:]
    if '--mail' not in args:
        args.insert(0, '--dry')
    return unified_main(args)


if __name__ == '__main__':
    raise SystemExit(main())
