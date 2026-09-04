#!/usr/bin/env python3
"""
从 Google 官方 IP 段数据源(cloud.json + goog.json)提取所有 IPv4/IPv6 CIDR,
合并去重、聚合(合并相邻网段/剔除被包含的子网段)、排序后,生成指定格式的规则文件。

数据源:
  https://www.gstatic.com/ipranges/cloud.json
  https://www.gstatic.com/ipranges/goog.json

输出格式:
{
  "version": 5,
  "rules": [
    {
      "ip_cidr": [ "8.8.4.0/24", "8.8.8.0/24", ... ]   # IPv4 在前,IPv6 在后
    }
  ]
}
"""

import json
import ipaddress
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

SOURCES = {
    "cloud": "https://www.gstatic.com/ipranges/cloud.json",
    "goog": "https://www.gstatic.com/ipranges/goog.json",
}

OUTPUT_PATH = Path("output/google-ip-rules.json")
OUTPUT_VERSION = 3
REQUEST_TIMEOUT = 30


def fetch_json(name: str, url: str) -> dict:
    """下载并解析一个 IP 段 JSON 源"""
    req = urllib.request.Request(url, headers={"User-Agent": "googleipmonitor-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[OK] 已获取 {name}: {len(data.get('prefixes', []))} 条记录")
            return data
    except Exception as e:
        print(f"[ERROR] 获取 {name} 失败: {e}", file=sys.stderr)
        raise


def extract_prefixes(data: dict) -> tuple[set, set]:
    """从一个数据源的 prefixes 列表里提取 ipv4 / ipv6 集合"""
    ipv4_set = set()
    ipv6_set = set()
    for entry in data.get("prefixes", []):
        if "ipv4Prefix" in entry:
            ipv4_set.add(entry["ipv4Prefix"])
        elif "ipv6Prefix" in entry:
            ipv6_set.add(entry["ipv6Prefix"])
    return ipv4_set, ipv6_set


def sort_key_v4(cidr: str):
    net = ipaddress.ip_network(cidr, strict=False)
    return (int(net.network_address), net.prefixlen)


def sort_key_v6(cidr: str):
    net = ipaddress.ip_network(cidr, strict=False)
    return (int(net.network_address), net.prefixlen)


def aggregate_cidrs(cidr_set: set) -> list:
    """
    对一组 CIDR 做聚合(collapse):
    - 若存在包含关系(如 A 是 B 的父网段),去掉冗余的子网段
    - 若干相邻/连续的网段能合并成一个更大的网段时,合并之
    返回聚合后的 CIDR 字符串列表(未排序)
    """
    if not cidr_set:
        return []
    networks = [ipaddress.ip_network(c, strict=False) for c in cidr_set]
    collapsed = ipaddress.collapse_addresses(networks)
    return [str(net) for net in collapsed]


def main():
    all_ipv4 = set()
    all_ipv6 = set()

    for name, url in SOURCES.items():
        data = fetch_json(name, url)
        v4, v6 = extract_prefixes(data)
        all_ipv4 |= v4
        all_ipv6 |= v6

    print(f"合并去重后: IPv4 {len(all_ipv4)} 条, IPv6 {len(all_ipv6)} 条, 共 {len(all_ipv4) + len(all_ipv6)} 条")

    # IP 聚合:合并相邻/连续网段,剔除被包含的子网段
    agg_ipv4 = aggregate_cidrs(all_ipv4)
    agg_ipv6 = aggregate_cidrs(all_ipv6)

    print(f"聚合后: IPv4 {len(agg_ipv4)} 条, IPv6 {len(agg_ipv6)} 条, 共 {len(agg_ipv4) + len(agg_ipv6)} 条")

    ipv4_sorted = sorted(agg_ipv4, key=sort_key_v4)
    ipv6_sorted = sorted(agg_ipv6, key=sort_key_v6)

    merged_cidr_list = ipv4_sorted + ipv6_sorted

    result = {
        "version": OUTPUT_VERSION,
        "rules": [
            {
                "ip_cidr": merged_cidr_list
            }
        ]
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"[DONE] 已写入 {OUTPUT_PATH} (更新时间 UTC: {datetime.now(timezone.utc).isoformat()})")


if __name__ == "__main__":
    main()
