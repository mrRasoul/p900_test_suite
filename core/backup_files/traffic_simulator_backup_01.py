#!/usr/bin/env python3
"""
MAVLink Traffic Simulator Module
شبیه‌ساز ترافیک MAVLink برای ایجاد بار واقعی
"""

import time
import serial
import logging
from typing import Optional, Dict, Any
from packet_generator import PacketGenerator
from mavlink_profile import MAVLinkProfile

logger = logging.getLogger(__name__)

class TrafficSimulator:
    """
    شبیه‌ساز ترافیک MAVLink با استفاده از PacketGenerator
    فاز 1: Simple loop implementation
    """
    
    def __init__(self, serial_port: Optional[serial.Serial] = None, 
                 target_bandwidth: float = 2373.0):
        """
        Args:
            serial_port: پورت سریال برای ارسال ترافیک
            target_bandwidth: پهنای باند هدف (bytes/sec)
        """
        self.serial_port = serial_port
        self.target_bandwidth = target_bandwidth
        self.running = False
        
        # استفاده از کامپوننت‌های موجود
        self.profile = MAVLinkProfile()
        self.packet_generator = PacketGenerator(self.profile)
        
        # آمار ساده
        self.stats = {
            'packets_sent': 0,
            'bytes_sent': 0,
            'start_time': None,
            'errors': 0
        }
        
        # محاسبه پارامترهای timing
        self._calculate_timing_params()
        
        logger.info(f"TrafficSimulator initialized - Target: {target_bandwidth} bytes/sec")
        
    def _calculate_timing_params(self):
        """محاسبه پارامترهای زمان‌بندی بر اساس bandwidth"""
        # میانگین اندازه پکت از پروفایل
        self.avg_packet_size = self.profile.statistics.get('mean_size', 34.69)
        
        # تعداد پکت در ثانیه برای رسیدن به bandwidth هدف
        self.packets_per_second = self.target_bandwidth / self.avg_packet_size
        
        # فاصله زمانی بین پکت‌ها (ثانیه)
        self.packet_interval = 1.0 / self.packets_per_second if self.packets_per_second > 0 else 0.1
        
        logger.info(f"Timing: {self.packets_per_second:.2f} pps, interval: {self.packet_interval*1000:.2f}ms")
    
    def start(self):
        """شروع تولید ترافیک - فاز 1: Simple blocking loop"""
        if not self.serial_port or not self.serial_port.is_open:
            logger.error("Serial port not available or not open")
            return False
            
        self.running = True
        self.stats['start_time'] = time.time()
        self.stats['packets_sent'] = 0
        self.stats['bytes_sent'] = 0
        self.stats['errors'] = 0
        
        logger.info("Traffic generation started (Phase 1: Simple loop)")
        
        try:
            self._run_traffic_loop()
        except KeyboardInterrupt:
            logger.info("Traffic generation interrupted by user")
        except Exception as e:
            logger.error(f"Error in traffic loop: {e}")
        finally:
            self.running = False
            self._print_stats()
            
        return True
    
    def _run_traffic_loop(self):
        """حلقه اصلی تولید ترافیک - ساده‌ترین حالت"""
        next_send_time = time.time()
        
        while self.running:
            current_time = time.time()
            
            # زمان ارسال پکت بعدی رسیده؟
            if current_time >= next_send_time:
                # تولید و ارسال پکت
                if self._send_single_packet():
                    # زمان‌بندی پکت بعدی
                    next_send_time = current_time + self.packet_interval
                else:
                    # در صورت خطا، کمی صبر کن
                    time.sleep(0.01)
            else:
                # صبر تا زمان ارسال بعدی
                sleep_time = next_send_time - current_time
                if sleep_time > 0:
                    time.sleep(min(sleep_time, 0.01))  # حداکثر 10ms sleep
    
    def _send_single_packet(self) -> bool:
        """تولید و ارسال یک پکت MAVLink"""
        try:
            # انتخاب اندازه از پروفایل (حالت realistic)
            packet_size = self.profile.get_packet_sizes(1, mode='realistic')[0]
            
            # تولید پکت MAVLink با PacketGenerator
            packet = self.packet_generator.generate_mavlink_traffic(packet_size)
            
            # ارسال به پورت سریال
            if self.serial_port and self.serial_port.is_open:
                bytes_written = self.serial_port.write(packet)
                
                # بروزرسانی آمار
                self.stats['packets_sent'] += 1
                self.stats['bytes_sent'] += bytes_written
                
                # لاگ پیشرفت هر 100 پکت
                if self.stats['packets_sent'] % 100 == 0:
                    self._log_progress()
                    
                return True
            else:
                logger.warning("Serial port not available")
                return False
                
        except Exception as e:
            logger.error(f"Error sending packet: {e}")
            self.stats['errors'] += 1
            return False
    
    def stop(self):
        """توقف تولید ترافیک"""
        logger.info("Stopping traffic generation...")
        self.running = False
    
    def _log_progress(self):
        """نمایش پیشرفت"""
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            if elapsed > 0:
                actual_bps = self.stats['bytes_sent'] / elapsed
                logger.info(f"Progress: {self.stats['packets_sent']} packets, "
                          f"{self.stats['bytes_sent']} bytes, "
                          f"Rate: {actual_bps:.2f} bps "
                          f"(Target: {self.target_bandwidth:.2f})")
    
    def _print_stats(self):
        """نمایش آمار نهایی"""
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            print("\n" + "="*50)
            print("Traffic Generation Statistics:")
            print("="*50)
            print(f"Duration: {elapsed:.2f} seconds")
            print(f"Packets sent: {self.stats['packets_sent']}")
            print(f"Bytes sent: {self.stats['bytes_sent']}")
            print(f"Errors: {self.stats['errors']}")
            if elapsed > 0:
                print(f"Average rate: {self.stats['bytes_sent']/elapsed:.2f} bytes/sec")
                print(f"Target rate: {self.target_bandwidth:.2f} bytes/sec")
                accuracy = (self.stats['bytes_sent']/elapsed) / self.target_bandwidth * 100
                print(f"Rate accuracy: {accuracy:.1f}%")
    
    def get_stats(self) -> Dict[str, Any]:
        """دریافت آمار فعلی"""
        stats = self.stats.copy()
        if self.stats['start_time']:
            elapsed = time.time() - self.stats['start_time']
            if elapsed > 0:
                stats['actual_bandwidth'] = self.stats['bytes_sent'] / elapsed
                stats['elapsed_time'] = elapsed
        return stats
    
    def adjust_rate(self, new_bandwidth: float):
        """تنظیم نرخ ترافیک"""
        self.target_bandwidth = new_bandwidth
        self._calculate_timing_params()
        logger.info(f"Bandwidth adjusted to {new_bandwidth} bytes/sec")


def create_simulator(port_name: Optional[str] = None, 
                    baudrate: int = 57600,
                    target_bandwidth: float = 2373.0) -> TrafficSimulator:
    """ایجاد یک نمونه simulator
    
    Args:
        port_name: نام پورت سریال
        baudrate: سرعت پورت
        target_bandwidth: پهنای باند هدف
        
    Returns:
        TrafficSimulator instance
    """
    serial_port = None
    if port_name:
        try:
            serial_port = serial.Serial(
                port=port_name,
                baudrate=baudrate,
                timeout=0.1
            )
            logger.info(f"Serial port {port_name} opened at {baudrate} baud")
        except Exception as e:
            logger.error(f"Failed to open serial port: {e}")
            
    return TrafficSimulator(serial_port, target_bandwidth)


if __name__ == "__main__":
    import sys
    
    # تنظیم logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("="*60)
    print("MAVLink Traffic Simulator - Phase 1 Test")
    print("="*60)
    
    # برای تست بدون پورت سریال (dry run)
    if len(sys.argv) > 1:
        port = sys.argv[1]
        print(f"Using serial port: {port}")
    else:
        port = None
        print("Dry run mode (no serial port)")
    
    # ایجاد simulator
    sim = create_simulator(port_name=port)
    
    if not port:
        # Dry run - فقط timing را تست کن
        print("\nDry run test - 5 seconds simulation")
        sim.serial_port = type('DummySerial', (), {
            'is_open': True,
            'write': lambda self, data: len(data)
        })()
    
    try:
        # شروع تولید ترافیک برای 10 ثانیه
        print("\nStarting traffic generation for 10 seconds...")
        print("Press Ctrl+C to stop early\n")
        
        # شروع در حالت blocking (فاز 1)
        import threading
        sim_thread = threading.Thread(target=sim.start)
        sim_thread.start()
        
        # صبر 10 ثانیه یا تا وقفه کاربر
        time.sleep(10)
        
        # توقف
        sim.stop()
        sim_thread.join(timeout=2)
        
    except KeyboardInterrupt:
        print("\nStopping...")
        sim.stop()
    
    # نمایش آمار نهایی
    final_stats = sim.get_stats()
    print(f"\nFinal bandwidth achieved: {final_stats.get('actual_bandwidth', 0):.2f} bytes/sec")
