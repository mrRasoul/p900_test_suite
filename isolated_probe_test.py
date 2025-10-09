#!/usr/bin/env python3
"""
isolated_probe_test.py - تست مستقل ProbeInjector
برای تشخیص مشکل 91% packet loss
"""

import serial
import time
import struct

def test_serial_loopback():
    """تست ساده: آیا اصلاً پورت‌ها به هم وصل هستند؟"""
    
    print("=" * 60)
    print("STEP 1: Testing Physical Connection")
    print("=" * 60)
    
    try:
        # باز کردن پورت‌ها با تنظیمات مینیمال
        master = serial.Serial(
            '/dev/ttyUSB0',
            baudrate=57600,
            timeout=1,        # 1 ثانیه timeout
            write_timeout=1,
            # اضافه کردن تنظیمات مهم
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        
        slave = serial.Serial(
            '/dev/ttyUSB1', 
            baudrate=57600,
            timeout=1,
            write_timeout=1,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False
        )
        
        print("✓ Ports opened successfully")
        
        # پاک کردن buffer ها
        master.reset_input_buffer()
        master.reset_output_buffer()
        slave.reset_input_buffer()
        slave.reset_output_buffer()
        time.sleep(0.5)
        
        # تست 1: ارسال یک بایت ساده
        print("\nTest 1: Single byte...")
        master.write(b'A')
        master.flush()
        time.sleep(0.1)
        
        response = slave.read(1)
        if response == b'A':
            print("✓ Single byte: SUCCESS")
        else:
            print(f"✗ Single byte: FAILED (got {response})")
            return False
            
        # تست 2: ارسال 10 بایت
        print("\nTest 2: 10 bytes...")
        test_data = b'0123456789'
        master.write(test_data)
        master.flush()
        time.sleep(0.1)
        
        response = slave.read(10)
        if response == test_data:
            print("✓ 10 bytes: SUCCESS")
        else:
            print(f"✗ 10 bytes: FAILED")
            print(f"  Sent: {test_data}")
            print(f"  Got:  {response}")
            return False
            
        # تست 3: دو طرفه
        print("\nTest 3: Bidirectional...")
        slave.write(b'BACK')
        slave.flush()
        time.sleep(0.1)
        
        response = master.read(4)
        if response == b'BACK':
            print("✓ Bidirectional: SUCCESS")
        else:
            print(f"✗ Bidirectional: FAILED (got {response})")
            return False
            
        print("\n✅ HARDWARE CONNECTION IS OK!")
        
        # بستن پورت‌ها
        master.close()
        slave.close()
        
        return True
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return False

def test_probe_only():
    """تست فقط ارسال و دریافت probe بدون traffic"""
    
    print("\n" + "=" * 60)
    print("STEP 2: Testing Probe Injection (No Traffic)")
    print("=" * 60)
    
    try:
        # Import فقط ProbeInjector
        from core.probe_injector import ProbeInjector
        
        # باز کردن پورت‌ها
        master = serial.Serial('/dev/ttyUSB0', 57600, timeout=0.5)
        slave = serial.Serial('/dev/ttyUSB1', 57600, timeout=0.5)
        
        # ایجاد ProbeInjector ساده
        injector = ProbeInjector(
            master_serial=master,
            slave_serial=slave,
            interval_ms=200,    # هر 200ms یک probe
            timeout_ms=1000,    # 1 ثانیه timeout
            size_mode='fixed',
            fixed_size=64       # پکت کوچک
        )
        
        print("Starting probe injection for 10 seconds...")
        injector.start()
        
        # نمایش آمار هر 2 ثانیه
        for i in range(5):
            time.sleep(2)
            stats = injector.get_statistics()
            
            print(f"\nTime {(i+1)*2}s:")
            print(f"  Sent: {stats.total_sent}")
            print(f"  Received: {stats.total_received}")
            print(f"  Lost: {stats.total_lost}")
            print(f"  Loss%: {stats.loss_rate:.1f}%")
            
            if stats.total_received > 0:
                print(f"  RTT: {stats.avg_rtt_ms:.2f}ms")
        
        # توقف
        injector.stop()
        
        # نتیجه نهایی
        final = injector.get_statistics()
        print("\n" + "-" * 40)
        print("FINAL RESULTS:")
        print(f"Total Sent: {final.total_sent}")
        print(f"Total Received: {final.total_received}")
        print(f"Loss Rate: {final.loss_rate:.1f}%")
        
        if final.loss_rate < 10:
            print("\n✅ PROBE INJECTION WORKS!")
            return True
        else:
            print(f"\n⚠️ HIGH LOSS RATE: {final.loss_rate:.1f}%")
            return False
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """اجرای تست‌های تشخیصی"""
    
    print("\n🔍 P900 DIAGNOSTIC TEST")
    print("This will identify the root cause of 91% packet loss")
    print("-" * 60)
    
    # مرحله 1: تست سخت‌افزار
    if not test_serial_loopback():
        print("\n" + "="*60)
        print("🔴 DIAGNOSIS: Hardware/Cable Problem!")
        print("="*60)
        print("\nSOLUTION:")
        print("1. Check cable connections")
        print("2. Verify P900 serial settings")
        print("3. Try different baudrate (9600, 115200)")
        print("4. Test with minicom/screen")
        return
    
    # مرحله 2: تست Probe
    if not test_probe_only():
        print("\n" + "="*60)
        print("🟡 DIAGNOSIS: ProbeInjector Problem!")
        print("="*60)
        print("\nPOSSIBLE CAUSES:")
        print("1. Thread synchronization issue")
        print("2. Packet format mismatch")
        print("3. Buffer overflow")
        print("\nNEXT STEP: Simplify ProbeInjector code")
        return
    
    # اگر هر دو کار کردند
    print("\n" + "="*60)
    print("🟢 DIAGNOSIS: Components OK - Integration Problem!")
    print("="*60)
    print("\nTHE ISSUE IS:")
    print("Traffic and Probe interfere with each other")
    print("\nSOLUTION:")
    print("Use single-threaded serial access with queue")

if __name__ == "__main__":
    main()
