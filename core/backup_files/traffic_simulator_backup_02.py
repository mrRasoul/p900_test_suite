#!/usr/bin/env python3
"""
TrafficSimulator - Final Working Version
نسخه نهایی و کارا - بدون پیچیدگی اضافی
"""

import time
import serial
import logging
import threading
from typing import Optional
import random

logger = logging.getLogger(__name__)

class TrafficSimulator:
    """
    ترافیک ژنراتور ساده و موثر
    فقط تولید بایت با نرخ مشخص - بدون Token Bucket پیچیده
    """
    
    def __init__(self, 
                 serial_port: serial.Serial,
                 target_bandwidth: float = 10000,  # bytes/sec
                 write_lock: Optional[threading.Lock] = None):
        
        self.serial_port = serial_port
        self.target_bandwidth = target_bandwidth
        self.write_lock = write_lock or threading.Lock()
        self.running = False
        
        # پارامترهای بهینه برای سریال
        self.chunk_size = min(4096, int(target_bandwidth / 10))  # حداکثر 4KB
        self.chunk_size = max(64, self.chunk_size)  # حداقل 64 بایت
        
        # محاسبه تایمینگ
        self.chunks_per_second = target_bandwidth / self.chunk_size
        self.chunk_interval = 1.0 / self.chunks_per_second if self.chunks_per_second > 0 else 0.1
        
        # آمار ساده
        self.stats = {
            'bytes_sent': 0,
            'chunks_sent': 0, 
            'start_time': 0,
            'errors': 0
        }
        
        # بافر داده از پیش آماده شده (کاهش CPU overhead)
        self._prepare_data_pool()
        
        logger.info(f"TrafficSimulator initialized:")
        logger.info(f"  Target: {target_bandwidth} B/s")
        logger.info(f"  Chunk size: {self.chunk_size} bytes")
        logger.info(f"  Interval: {self.chunk_interval*1000:.1f} ms")
    
    def _prepare_data_pool(self):
        """آماده‌سازی داده‌های تصادفی برای ارسال"""
        # 10 بلوک مختلف برای تنوع
        self.data_pool = []
        for i in range(10):
            # داده شبه-تصادفی که شبیه MAVLink است
            data = bytearray()
            # شروع با 0xFE (MAVLink marker)
            data.append(0xFE)
            # بقیه داده‌ها
            for j in range(self.chunk_size - 1):
                data.append((i * j) % 256)
            self.data_pool.append(bytes(data))
    
    def start(self):
        """شروع تولید ترافیک"""
        if self.running:
            return
            
        self.running = True
        self.stats = {
            'bytes_sent': 0,
            'chunks_sent': 0,
            'start_time': time.perf_counter(),
            'errors': 0
        }
        
        # اجرا در thread جداگانه
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        
        logger.info("Traffic generation started")
        return True
    
    def _run(self):
        """حلقه اصلی - بدون پیچیدگی"""
        next_send_time = time.perf_counter()
        chunk_index = 0
        last_log_time = time.perf_counter()
        
        while self.running:
            now = time.perf_counter()
            
            # زمان ارسال بعدی
            if now >= next_send_time:
                # انتخاب داده از pool
                data = self.data_pool[chunk_index % len(self.data_pool)]
                chunk_index += 1
                
                # ارسال با lock کوتاه
                success = False
                if self.write_lock.acquire(timeout=0.001):  # فقط 1ms صبر
                    try:
                        # ارسال بدون flush (سریعتر)
                        written = self.serial_port.write(data[:self.chunk_size])
                        self.stats['bytes_sent'] += written
                        self.stats['chunks_sent'] += 1
                        success = True
                    except serial.SerialTimeoutException:
                        self.stats['errors'] += 1
                        logger.debug("Write timeout - buffer full")
                    except Exception as e:
                        self.stats['errors'] += 1
                        logger.error(f"Write error: {e}")
                    finally:
                        self.write_lock.release()
                
                # برنامه‌ریزی ارسال بعدی
                next_send_time += self.chunk_interval
                
                # اگر عقب افتادیم، ریست کن
                if next_send_time < now - 0.1:
                    next_send_time = now + self.chunk_interval
            
            # لاگ پیشرفت (هر ثانیه)
            if now - last_log_time >= 1.0:
                rate = self.get_current_rate()
                accuracy = (rate / self.target_bandwidth * 100) if self.target_bandwidth > 0 else 0
                logger.info(f"Rate: {rate:.0f} B/s ({accuracy:.1f}% of target)")
                last_log_time = now
            
            # تاخیر کوتاه برای کاهش CPU usage
            sleep_time = next_send_time - time.perf_counter()
            if sleep_time > 0.0001:
                time.sleep(min(sleep_time, 0.01))
    
    def stop(self):
        """توقف تولید ترافیک"""
        self.running = False
        logger.info("Traffic generation stopped")
    
    def get_current_rate(self) -> float:
        """نرخ فعلی ارسال"""
        if self.stats['start_time'] == 0:
            return 0
        elapsed = time.perf_counter() - self.stats['start_time']
        return self.stats['bytes_sent'] / elapsed if elapsed > 0 else 0
    
    def get_stats(self) -> dict:
        """دریافت آمار"""
        stats = self.stats.copy()
        stats['actual_bandwidth'] = self.get_current_rate()
        stats['elapsed_time'] = time.perf_counter() - self.stats['start_time']
        return stats


# تست مستقل
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) < 2:
        print("Usage: python traffic_simulator.py /dev/pts/X [bandwidth]")
        sys.exit(1)
    
    port_name = sys.argv[1]
    bandwidth = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
    
    print(f"\nTesting TrafficSimulator on {port_name} @ {bandwidth} B/s")
    print("-" * 50)
    
    try:
        # باز کردن پورت
        ser = serial.Serial(
            port=port_name,
            baudrate=115200,
            timeout=0.001,
            write_timeout=0.01
        )
        
        # ایجاد و شروع simulator
        sim = TrafficSimulator(ser, bandwidth)
        sim.start()
        
        # اجرا برای 10 ثانیه
        for i in range(10):
            time.sleep(1)
            stats = sim.get_stats()
            print(f"[{i+1}s] Sent: {stats['bytes_sent']} bytes, "
                  f"Rate: {stats['actual_bandwidth']:.0f} B/s, "
                  f"Errors: {stats['errors']}")
        
        sim.stop()
        
        # آمار نهایی
        final_stats = sim.get_stats()
        print("\n" + "="*50)
        print("FINAL RESULTS:")
        print(f"  Total sent: {final_stats['bytes_sent']} bytes")
        print(f"  Average rate: {final_stats['actual_bandwidth']:.0f} B/s")
        print(f"  Target rate: {bandwidth} B/s")
        print(f"  Accuracy: {final_stats['actual_bandwidth']/bandwidth*100:.1f}%")
        print(f"  Errors: {final_stats['errors']}")
        
        ser.close()
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
