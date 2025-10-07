#!/usr/bin/env python3
"""
تست عملکرد MAVLink Payload Mode
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.p900_tester import P900NetworkTesterEnhanced
from utils.config import MASTER_PORT, SLAVE_PORT
from utils.logger import setup_logger

logger = setup_logger('TestMAVLink')

def test_mavlink_mode():
    """تست با payload واقعی MAVLink"""
    logger.info("🚁 Starting MAVLink mode test...")
    
    tester = P900NetworkTesterEnhanced(MASTER_PORT, SLAVE_PORT)
    
    if not tester.connect():
        logger.error("Failed to connect")
        return False
    
    # تست 1: فقط MAVLink payload با سایز ثابت
    logger.info("\n📌 Test 1: Fixed size with MAVLink payload")
    tester.use_mavlink_payload(True)
    tester.set_packet_size(108)
    results1 = tester.measure_latency(num_packets=50, interval_ms=100)
    
    # تست 2: MAVLink با سایز رندوم
    logger.info("\n📌 Test 2: Random size with MAVLink payload")
    tester.set_random_size_mode(True, distribution='realistic')
    results2 = tester.measure_latency(num_packets=100, interval_ms=100)
    
    # تست 3: مقایسه با داده dummy
    logger.info("\n📌 Test 3: Random size with dummy payload (comparison)")
    tester.use_mavlink_payload(False)
    results3 = tester.measure_latency(num_packets=100, interval_ms=100)
    
    # نمایش آمار توزیع پیام‌ها
    distribution = tester.get_mavlink_message_distribution()
    logger.info("\n📊 MAVLink Message Distribution:")
    for msg_type, count in distribution.items():
        logger.info(f"  {msg_type}: {count} packets")
    
    # ذخیره نتایج
    tester.save_results("mavlink_test")
    tester.disconnect()
    
    logger.info("✅ MAVLink mode test completed!")
    return True

if __name__ == "__main__":
    test_mavlink_mode()
