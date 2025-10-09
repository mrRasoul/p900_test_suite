#!/usr/bin/env python3
"""
Serial Port Monitor - برای مشاهده ترافیک
"""

import serial
import sys
import time
from datetime import datetime

def monitor_port(port_name, baudrate=57600):
    """نمایش داده‌های دریافتی از پورت سریال"""
    
    print(f"📡 Monitoring port: {port_name} @ {baudrate} baud")
    print("="*60)
    
    bytes_received = 0
    packets_received = 0
    start_time = time.time()
    last_report = time.time()
    
    try:
        with serial.Serial(port_name, baudrate, timeout=0.1) as ser:
            print("✅ Port opened successfully")
            print("Waiting for data... (Press Ctrl+C to stop)\n")
            
            while True:
                if ser.in_waiting > 0:
                    data = ser.read(ser.in_waiting)
                    bytes_received += len(data)
                    packets_received += 1
                    
                    # نمایش پیشرفت هر ثانیه
                    current_time = time.time()
                    if current_time - last_report >= 1.0:
                        elapsed = current_time - start_time
                        rate = bytes_received / elapsed if elapsed > 0 else 0
                        
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        print(f"[{timestamp}] Packets: {packets_received:5d} | "
                              f"Bytes: {bytes_received:7d} | "
                              f"Rate: {rate:7.2f} B/s")
                        
                        last_report = current_time
                        
    except serial.SerialException as e:
        print(f"❌ Error opening port: {e}")
        return 1
        
    except KeyboardInterrupt:
        print("\n\n" + "="*60)
        print("📊 Final Statistics:")
        elapsed = time.time() - start_time
        print(f"  Duration: {elapsed:.2f} seconds")
        print(f"  Total Packets: {packets_received}")
        print(f"  Total Bytes: {bytes_received}")
        if elapsed > 0:
            print(f"  Average Rate: {bytes_received/elapsed:.2f} B/s")
        print("="*60)
        return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python serial_monitor.py <port>")
        print("Example: python serial_monitor.py /dev/pts/4")
        sys.exit(1)
    
    port = sys.argv[1]
    sys.exit(monitor_port(port))
