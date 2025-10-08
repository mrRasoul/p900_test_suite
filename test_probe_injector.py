#!/usr/bin/env python3
"""
Test script for ProbeInjector with PacketGenerator
تست مستقل ProbeInjector با اندازه‌های متغیر
"""

import sys
import os
import time
import serial
import threading
from pathlib import Path

# اضافه کردن مسیر به sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

# حالا import ها کار می‌کنند
from core.probe_injector import ProbeInjector
from core.packet_generator import PacketGenerator, create_generator

def test_probe_injector_standalone():
    """تست مستقل بدون نیاز به سریال واقعی"""
    print("=" * 60)
    print("ProbeInjector Test with Variable Sizes")
    print("=" * 60)
    
    # ایجاد PacketGenerator
    packet_gen = create_generator()
    print(f"\n✅ PacketGenerator created")
    print(f"Representative sizes: {packet_gen.get_representative_sizes()}")
    
    # ایجاد ProbeInjector با serial های mock
    injector = ProbeInjector(
        master_serial=None,  # فعلاً None
        slave_serial=None,   # فعلاً None
        interval_ms=100,     # هر 100ms یک پروب
        timeout_ms=500,      # تایم‌اوت 500ms
        packet_generator=packet_gen,
        size_mode='representative'
    )
    
    print(f"\n✅ ProbeInjector created")
    print(f"  Interval: {injector.interval_ms}ms")
    print(f"  Timeout: {injector.timeout_ms}ms")
    print(f"  Size mode: {injector.size_mode}")
    print(f"  Variable sizes: {injector.variable_sizes}")
    
    # تست تولید اندازه‌ها
    print("\n📊 Testing size generation:")
    for i in range(10):
        size = injector._get_next_packet_size()
        print(f"  Probe {i+1}: {size} bytes")
    
    # تست تولید پکت با اندازه‌های مختلف
    print("\n📦 Testing probe packet generation:")
    for i in range(5):
        probe_id = 5000 + i
        size = injector.variable_sizes[i % len(injector.variable_sizes)]
        
        # تولید پکت
        packet = injector.packet_generator.generate_probe_packet(
            size=size,
            probe_id=probe_id
        )
        
        print(f"  Probe {probe_id}: size={size}B, actual={len(packet)}B")
        
        # تجزیه برای تأیید
        parsed = injector.packet_generator.parse_probe_packet(packet)
        if parsed and parsed['valid']:
            print(f"    ✓ Valid probe, ID={parsed['probe_id']}, Size={parsed['size']}")
        else:
            print(f"    ✗ Invalid probe packet")
    
    print("\n✅ All tests completed successfully!")

def test_with_virtual_serial():
    """تست با استفاده از virtual serial ports (socat)"""
    print("\n" + "=" * 60)
    print("ProbeInjector Test with Virtual Serial Ports")
    print("=" * 60)
    
    print("\n⚠️  This test requires virtual serial ports.")
    print("Run this command in another terminal:")
    print("  socat -d -d pty,raw,echo=0 pty,raw,echo=0")
    print("\nThen update the port names below and press Enter...")
    input()
    
    # پورت‌های مجازی - باید با خروجی socat تنظیم شوند
    MASTER_PORT = "/dev/pts/2"  # به‌روزرسانی با مقدار واقعی
    SLAVE_PORT = "/dev/pts/3"   # به‌روزرسانی با مقدار واقعی
    
    try:
        # باز کردن پورت‌ها
        master_serial = serial.Serial(
            port=MASTER_PORT,
            baudrate=57600,
            timeout=0.1
        )
        
        slave_serial = serial.Serial(
            port=SLAVE_PORT,
            baudrate=57600,
            timeout=0.1
        )
        
        print(f"✅ Serial ports opened:")
        print(f"  Master: {MASTER_PORT}")
        print(f"  Slave: {SLAVE_PORT}")
        
        # ایجاد injector
        packet_gen = create_generator()
        injector = ProbeInjector(
            master_serial=master_serial,
            slave_serial=slave_serial,
            interval_ms=200,
            timeout_ms=1000,
            packet_generator=packet_gen,
            size_mode='representative'
        )
        
        # شروع تست
        print("\n🚀 Starting probe injection...")
        injector.start()
        
        # اجرا برای 5 ثانیه
        for i in range(5):
            time.sleep(1)
            stats = injector.get_statistics()
            print(f"\n📊 After {i+1} seconds:")
            print(f"  Sent: {stats.total_sent}")
            print(f"  Received: {stats.total_received}")
            print(f"  Lost: {stats.total_lost}")
            if stats.total_received > 0:
                print(f"  Avg RTT: {stats.avg_rtt_ms:.2f}ms")
                print(f"  Min RTT: {stats.min_rtt_ms:.2f}ms")
                print(f"  Max RTT: {stats.max_rtt_ms:.2f}ms")
            
            # نمایش آمار بر حسب اندازه
            if stats.stats_by_size:
                print("  By size:")
                for size, size_stat in stats.stats_by_size.items():
                    if size_stat['sent'] > 0:
                        print(f"    {size}B: sent={size_stat['sent']}, "
                              f"received={size_stat['received']}, "
                              f"lost={size_stat['lost']}")
        
        # توقف
        print("\n🛑 Stopping injection...")
        injector.stop()
        
        # آمار نهایی
        final_stats = injector.get_statistics()
        print("\n📊 Final Statistics:")
        print(f"  Total sent: {final_stats.total_sent}")
        print(f"  Total received: {final_stats.total_received}")
        print(f"  Total lost: {final_stats.total_lost}")
        print(f"  Loss rate: {final_stats.loss_rate:.2f}%")
        print(f"  Bytes sent: {final_stats.bytes_sent}")
        print(f"  Bytes received: {final_stats.bytes_received}")
        
        # بستن پورت‌ها
        master_serial.close()
        slave_serial.close()
        
    except serial.SerialException as e:
        print(f"❌ Serial error: {e}")
        print("Make sure virtual ports are created with socat")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    # اول تست standalone
    test_probe_injector_standalone()
    
    # سوال برای تست با virtual serial
    print("\n" + "=" * 60)
    response = input("\nDo you want to test with virtual serial ports? (y/n): ")
    if response.lower() == 'y':
        test_with_virtual_serial()
    else:
        print("✅ Standalone test completed.")
