#!/usr/bin/env python3
"""
بررسی ساختار فایل JSON برای فهم فرمت داده
"""

import json
from pathlib import Path
import pprint

def inspect_mavlink_json():
    """بررسی ساختار فایل JSON"""
    
    # مسیر فایل
    output_dir = Path("analysis/output")
    stats_files = list(output_dir.glob("*traffic_stats.json"))
    
    if not stats_files:
        print("❌ No files found in analysis/output/")
        # بررسی مسیرهای دیگر
        print("\n🔍 Searching in other locations...")
        
        # جستجو در root directory
        root_files = list(Path(".").glob("*traffic_stats.json"))
        if root_files:
            print(f"Found in root: {root_files}")
            stats_files = root_files
        else:
            print("No files found anywhere!")
            return
    
    # خواندن اولین فایل
    file_path = stats_files[0]
    print(f"\n📄 Reading: {file_path}")
    print(f"File size: {file_path.stat().st_size} bytes")
    
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    print("\n📊 JSON Structure:")
    print("=" * 60)
    
    # نمایش کلیدهای اصلی
    print(f"Top-level keys: {list(data.keys())}")
    
    # نمایش ساختار کامل (محدود شده)
    print("\n🔍 Full structure (limited depth):")
    
    pp = pprint.PrettyPrinter(indent=2, depth=3, width=80)
    pp.pprint(data)
    
    # اگر message_types وجود دارد
    if 'message_types' in data:
        print("\n📨 Message Types Sample:")
        msg_types = data['message_types']
        
        # نمایش 3 نمونه اول
        for i, (msg_type, msg_data) in enumerate(msg_types.items()):
            if i >= 3:
                break
            print(f"\n  {msg_type}:")
            print(f"    {msg_data}")
    
    # اگر messages وجود دارد
    if 'messages' in data:
        print(f"\n📦 Messages array length: {len(data['messages'])}")
        if data['messages']:
            print("First message sample:")
            pp.pprint(data['messages'][0])
    
    # اگر summary وجود دارد
    if 'summary' in data:
        print("\n📈 Summary:")
        pp.pprint(data['summary'])
    
    return data

if __name__ == "__main__":
    print("🔍 Inspecting MAVLink JSON structure...")
    data = inspect_mavlink_json()
