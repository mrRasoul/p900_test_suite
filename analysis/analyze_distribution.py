#!/usr/bin/env python3
"""
تحلیل داده‌های MAVLink برای استخراج توزیع اندازه پکت‌ها
"""

import json
import os
from pathlib import Path
import numpy as np
from typing import Dict, List, Tuple
from collections import defaultdict

def analyze_mavlink_data():
    """تحلیل فایل‌های JSON موجود از MAVLink logger"""
    
    # مسیر فایل‌های خروجی
    output_dir = Path("analysis/output")
    
    # پیدا کردن فایل traffic_stats
    stats_files = list(output_dir.glob("*traffic_stats.json"))
    
    if not stats_files:
        # جستجو در root
        stats_files = list(Path(".").glob("*traffic_stats.json"))
    
    if not stats_files:
        print("❌ No traffic stats files found!")
        return None
    
    # خواندن آخرین فایل
    latest_file = max(stats_files, key=os.path.getctime)
    print(f"📊 Analyzing: {latest_file.name}")
    
    with open(latest_file, 'r') as f:
        data = json.load(f)
    
    # استخراج اطلاعات پکت‌ها
    packet_sizes = []
    packet_counts = []
    message_details = []
    
    # داده‌ها به صورت dictionary با msg_id به عنوان key هستند
    for msg_id, info in data.items():
        # استخراج اطلاعات
        msg_type = info.get('message_type', f'MSG_{msg_id}')
        size = info.get('avg_size', 0)
        count = info.get('count', 0)
        
        if size > 0 and count > 0:
            # اضافه کردن به لیست (تکرار به تعداد count)
            packet_sizes.extend([size] * count)
            packet_counts.append((msg_type, size, count))
            
            # ذخیره جزئیات برای نمایش
            message_details.append({
                'msg_id': int(msg_id),
                'type': msg_type,
                'size': size,
                'count': count,
                'frequency_hz': info.get('frequency_hz', 0),
                'total_bytes': info.get('total_bytes', 0)
            })
    
    # محاسبه توزیع
    if packet_sizes:
        sizes_array = np.array(packet_sizes)
        
        # تعریف رنج‌های اندازه بر اساس داده‌های واقعی MAVLink
        # بر اساس داده‌های شما: کوچکترین=22، بزرگترین=63
        bins = [0, 25, 40, 50, 60, 280]  # تنظیم شده بر اساس داده‌های واقعی
        bin_labels = ['tiny', 'small', 'medium', 'large', 'xlarge']
        
        # محاسبه هیستوگرام
        hist, _ = np.histogram(sizes_array, bins=bins)
        total = len(sizes_array)
        
        distribution = {}
        for i, label in enumerate(bin_labels):
            probability = hist[i] / total if total > 0 else 0
            size_range = (bins[i], bins[i+1])
            distribution[label] = {
                'probability': round(probability, 4),
                'range': size_range,
                'count': int(hist[i]),
                'percentage': round(probability * 100, 2)
            }
        
        # آمار کلی
        stats = {
            'total_packets': total,
            'unique_message_types': len(packet_counts),
            'min_size': int(sizes_array.min()),
            'max_size': int(sizes_array.max()),
            'mean_size': round(float(sizes_array.mean()), 2),
            'median_size': round(float(np.median(sizes_array)), 2),
            'std_dev': round(float(sizes_array.std()), 2)
        }
        
        # پیدا کردن پیام‌های پرتکرار
        top_messages = sorted(message_details, key=lambda x: x['count'], reverse=True)[:10]
        
        # پیدا کردن پیام‌های با فرکانس بالا
        high_freq_messages = sorted(message_details, key=lambda x: x['frequency_hz'], reverse=True)[:5]
        
        return {
            'distribution': distribution,
            'statistics': stats,
            'top_messages': top_messages,
            'high_frequency_messages': high_freq_messages,
            'all_messages': message_details
        }
    
    return None

def create_mavlink_profile(results: Dict) -> Dict:
    """ایجاد پروفایل MAVLink بر اساس نتایج تحلیل"""
    
    profile = {
        'name': 'Real MAVLink Traffic Profile',
        'description': 'Profile based on actual MAVLink traffic capture',
        
        # توزیع اندازه‌ها
        'size_distribution': {
            category: {
                'probability': info['probability'],
                'min_bytes': info['range'][0],
                'max_bytes': info['range'][1]
            }
            for category, info in results['distribution'].items()
        },
        
        # پیام‌های رایج با اندازه دقیق
        'common_messages': {
            msg['type']: {
                'size': msg['size'],
                'frequency_hz': round(msg['frequency_hz'], 2),
                'weight': round(msg['count'] / results['statistics']['total_packets'], 4)
            }
            for msg in results['top_messages'][:5]  # 5 پیام پرتکرار
        },
        
        # آمار کلی
        'statistics': results['statistics']
    }
    
    return profile

def save_analysis_results(results: Dict, profile: Dict):
    """ذخیره نتایج تحلیل و پروفایل"""
    
    # ذخیره نتایج کامل تحلیل
    analysis_path = Path("analysis") / "mavlink_analysis_complete.json"
    with open(analysis_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"✅ Full analysis saved to: {analysis_path}")
    
    # ذخیره پروفایل
    profile_path = Path("core") / "mavlink_profile.json"
    with open(profile_path, 'w') as f:
        json.dump(profile, f, indent=2)
    print(f"✅ Profile saved to: {profile_path}")
    
    # نمایش خلاصه
    print("\n" + "="*60)
    print("📊 Distribution Summary:")
    print("-"*60)
    for category, info in results['distribution'].items():
        print(f"  {category:8} [{info['range'][0]:3d}-{info['range'][1]:3d} bytes]: "
              f"{info['percentage']:5.1f}% ({info['count']:5d} packets)")
    
    print("\n📈 Statistics:")
    print("-"*60)
    stats = results['statistics']
    print(f"  Total packets: {stats['total_packets']:,}")
    print(f"  Message types: {stats['unique_message_types']}")
    print(f"  Size range: {stats['min_size']}-{stats['max_size']} bytes")
    print(f"  Mean size: {stats['mean_size']} bytes")
    print(f"  Median size: {stats['median_size']} bytes")
    
    print("\n🔝 Top 5 Messages by Count:")
    print("-"*60)
    for msg in results['top_messages'][:5]:
        print(f"  {msg['type']:30} Size: {msg['size']:3d} bytes, "
              f"Count: {msg['count']:5d}, Freq: {msg['frequency_hz']:.1f} Hz")
    
    print("\n⚡ High Frequency Messages:")
    print("-"*60)
    for msg in results['high_frequency_messages']:
        print(f"  {msg['type']:30} {msg['frequency_hz']:6.1f} Hz "
              f"({msg['size']} bytes)")

def generate_packet_generator_code(profile: Dict):
    """تولید کد Python برای PacketGenerator بر اساس پروفایل"""
    
    code = '''#!/usr/bin/env python3
"""
MAVLink-based Packet Generator
Auto-generated from real traffic analysis
"""

import random
from typing import Tuple

class MAVLinkPacketGenerator:
    """تولیدکننده پکت بر اساس پروفایل واقعی MAVLink"""
    
    def __init__(self):
        # توزیع اندازه‌ها
        self.size_distribution = {
'''
    
    # اضافه کردن توزیع
    for category, info in profile['size_distribution'].items():
        code += f"            '{category}': {{'probability': {info['probability']}, "
        code += f"'min': {info['min_bytes']}, 'max': {info['max_bytes']}}},\n"
    
    code += '''        }
        
        # پیام‌های رایج با اندازه دقیق
        self.common_messages = {
'''
    
    # اضافه کردن پیام‌های رایج
    for msg_type, info in profile['common_messages'].items():
        code += f"            '{msg_type}': {{'size': {info['size']}, 'weight': {info['weight']}}},\n"
    
    code += '''        }
        
        # محاسبه احتمال تجمعی برای انتخاب دسته
        self.cumulative_probs = []
        cumsum = 0
        for category, info in self.size_distribution.items():
            cumsum += info['probability']
            self.cumulative_probs.append((cumsum, category))
    
    def generate_packet_size(self) -> int:
        """تولید اندازه پکت بر اساس توزیع MAVLink"""
        
        # 70% احتمال استفاده از پیام‌های رایج
        if random.random() < 0.7:
            # انتخاب از پیام‌های رایج بر اساس وزن
            messages = list(self.common_messages.items())
            weights = [msg[1]['weight'] for msg in messages]
            selected = random.choices(messages, weights=weights)[0]
            return selected[1]['size']
        
        # 30% احتمال تولید اندازه تصادفی از توزیع
        rand = random.random()
        for cumprob, category in self.cumulative_probs:
            if rand <= cumprob:
                size_range = self.size_distribution[category]
                return random.randint(size_range['min'], size_range['max'])
        
        # پیش‌فرض
        return 40  # متوسط اندازه ATTITUDE
    
    def generate_packet_content(self, size: int) -> bytes:
        """تولید محتوای پکت با اندازه مشخص"""
        
        # شبیه‌سازی هدر MAVLink v2
        header = bytes([
            0xFD,  # STX برای MAVLink v2
            size & 0xFF,  # Payload length
            0x00,  # Incompatibility flags
            0x00,  # Compatibility flags
            random.randint(0, 255),  # Sequence
            0x01,  # System ID
            0x01,  # Component ID
            random.randint(1, 255),  # Message ID (low)
            random.randint(0, 255),  # Message ID (mid)
            0x00,  # Message ID (high)
        ])
        
        # Payload با داده‌های تصادفی
        payload = bytes([random.randint(0, 255) for _ in range(max(0, size - 12))])
        
        # CRC (ساده‌شده)
        crc = bytes([random.randint(0, 255), random.randint(0, 255)])
        
        return header + payload + crc

if __name__ == "__main__":
    # تست
    generator = MAVLinkPacketGenerator()
    
    print("Testing packet generation:")
    sizes = []
    for _ in range(1000):
        size = generator.generate_packet_size()
        sizes.append(size)
    
    from collections import Counter
    size_counts = Counter(sizes)
    print(f"\\nGenerated sizes distribution:")
    for size, count in sorted(size_counts.items()):
        print(f"  {size:3d} bytes: {count:4d} times ({count/10:.1f}%)")
'''
    
    # ذخیره کد
    generator_path = Path("core") / "packet_generator.py"
    with open(generator_path, 'w', encoding='utf-8') as f:
        f.write(code)
    
    print(f"\n✅ PacketGenerator code saved to: {generator_path}")

if __name__ == "__main__":
    print("🔍 Starting MAVLink data analysis...")
    print("="*60)
    
    results = analyze_mavlink_data()
    
    if results:
        # ایجاد پروفایل
        profile = create_mavlink_profile(results)
        
        # ذخیره نتایج
        save_analysis_results(results, profile)
        
        # تولید کد PacketGenerator
        generate_packet_generator_code(profile)
        
        print("\n" + "="*60)
        print("✅ Analysis complete! Generated files:")
        print("  1. analysis/mavlink_analysis_complete.json - Full analysis")
        print("  2. core/mavlink_profile.json - Compact profile")
        print("  3. core/packet_generator.py - Packet generator code")
    else:
        print("❌ Analysis failed - no valid data found")
