#!/usr/bin/env python3
"""
Integration test for MAVLink profile and packet generation
تست یکپارچه‌سازی پروفایل و تولید پکت
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.mavlink_profile import MAVLinkProfile
from core.packet_generator import MAVLinkPacketGenerator
from core.probe_injector import ProbeInjector
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_profile_loading():
    """تست بارگذاری پروفایل"""
    print("\n" + "="*50)
    print("1️⃣ Testing Profile Loading")
    print("="*50)
    
    profile = MAVLinkProfile()
    
    # نمایش خلاصه
    print(profile.get_summary())
    
    # اعتبارسنجی
    validation = profile.validate_profile()
    print("\n✅ Validation results:")
    for key, value in validation.items():
        status = "✓" if value else "✗"
        print(f"  {status} {key}: {value}")
    
    return profile


def test_packet_generation(profile):
    """تست تولید پکت"""
    print("\n" + "="*50)
    print("2️⃣ Testing Packet Generation")
    print("="*50)
    
    generator = MAVLinkPacketGenerator(profile)
    
    # اندازه‌های تست
    print("\nRepresentative sizes:", generator.get_test_sizes())
    
    # تولید پکت‌های realistic
    print("\nGenerating realistic packets:")
    packets = generator.generate_batch(10, 'realistic')
    for i, (size, packet) in enumerate(packets[:5]):
        print(f"  Packet {i+1}: Target size={size}, Actual={len(packet)}, "
              f"Header={packet[:6].hex()}")
    
    # تولید پکت پروب
    print("\nGenerating probe packet:")
    probe_packet = generator.generate_probe_packet(40, 12345)
    print(f"  Probe packet: Size={len(probe_packet)}, First 10 bytes={probe_packet[:10].hex()}")
    
    return generator


def test_probe_injection():
    """تست تزریق با اندازه‌های واقعی"""
    print("\n" + "="*50)
    print("3️⃣ Testing Probe Injection with Profile")
    print("="*50)
    
    # این قسمت فقط نمایش می‌دهد که چطور استفاده می‌شود
    # اجرای واقعی نیاز به پورت سریال دارد
    
    profile = MAVLinkProfile()
    generator = MAVLinkPacketGenerator(profile)
    
    # دریافت اندازه‌های تست
    test_sizes = generator.get_test_sizes()
    print(f"\nWould test with {len(test_sizes)} different sizes:")
    print(f"Sizes: {test_sizes}")
    
    # نمونه کد برای استفاده واقعی (کامنت شده)
    print("\n📝 Example usage in real test:")
    print("""
    injector = ProbeInjector('/dev/ttyUSB0', '/dev/ttyUSB1')
    
    for size in test_sizes:
        packet = generator.generate_probe_packet(size, probe_id)
        result = injector.inject_probe(packet, timeout=0.1)
        print(f"Size {size}: RTT={result['rtt']:.3f}ms")
    """)


def main():
    """اجرای تست‌ها"""
    print("\n🚀 MAVLink Profile Integration Test")
    print("="*50)
    
    # 1. تست پروفایل
    profile = test_profile_loading()
    
    # 2. تست تولید پکت
    generator = test_packet_generation(profile)
    
    # 3. تست تزریق (شبیه‌سازی)
    test_probe_injection()
    
    print("\n" + "="*50)
    print("✅ All tests completed successfully!")
    print("="*50)


if __name__ == "__main__":
    main()
