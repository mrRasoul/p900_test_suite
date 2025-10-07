#!/usr/bin/env python3
"""
P900 Network Tester - Main Entry Point
تست‌کننده شبکه P900 - نقطه ورود اصلی
"""

import sys
import os
import argparse
import logging
from datetime import datetime
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.p900_tester import P900NetworkTesterEnhanced
from utils.logger import setup_logger

# Setup logger
logger = setup_logger('Main')

def run_isolated_test(master_port='/dev/ttyUSB0', 
                      slave_port='/dev/ttyUSB1',
                      packets=100,
                      packet_size=64,
                      output_prefix='isolated_test',
                      enable_random_size=False,
                      enable_mavlink=False,
                      realistic_distribution=True,
                      verbose=False):
    """
    اجرای تست isolated RTT
    """
    
    logger.info("=" * 60)
    logger.info("🚀 Starting ISOLATED RTT Test")
    logger.info("=" * 60)
    
    # نمایش تنظیمات
    logger.info(f"Configuration:")
    logger.info(f"  Master Port: {master_port}")
    logger.info(f"  Slave Port: {slave_port if slave_port else 'None (Single port mode)'}")
    logger.info(f"  Packets: {packets}")
    logger.info(f"  Base Packet Size: {packet_size} bytes")
    logger.info(f"  Random Size: {'✅ Enabled' if enable_random_size else '❌ Disabled'}")
    logger.info(f"  MAVLink Mode: {'✅ Enabled' if enable_mavlink else '❌ Disabled'}")
    
    if enable_random_size:
        logger.info(f"  Distribution: {'Realistic' if realistic_distribution else 'Uniform'}")
    
    logger.info("-" * 60)
    
    try:
        # ایجاد tester
        logger.info("📡 Initializing tester...")
        tester = P900NetworkTesterEnhanced(
            master_port=master_port,
            slave_port=slave_port,
            baudrate=57600,
            slave_mode=(slave_port is not None),
            verbose=verbose
        )
        
        # ⭐ مهم: تنظیمات را قبل از شروع تست اعمال کن!
        logger.info("🔧 Applying test settings...")
        
        if enable_random_size:
            tester.set_random_size_mode(True, realistic=realistic_distribution)
            logger.info("  ✅ Random size mode enabled")
            if realistic_distribution:
                logger.info("     📊 Using realistic MAVLink distribution")
            else:
                logger.info("     📊 Using uniform distribution (8-279 bytes)")
        
        if enable_mavlink:
            tester.set_mavlink_payload(True)
            logger.info("  ✅ MAVLink payload mode enabled")
            logger.info("     🚁 Simulating real MAVLink messages")
        
        # اتصال به پورت‌ها
        logger.info("🔌 Connecting to serial ports...")
        if not tester.connect():
            logger.error("❌ Failed to connect to ports!")
            return None
        
        logger.info("✅ Connected successfully")
        
        # شروع سرویس‌ها (thread ها)
        logger.info("🔄 Starting background services...")
        tester.start_services()
        
        # اجرای تست
        logger.info("-" * 60)
        logger.info(f"📊 Running RTT measurement with {packets} packets...")
        logger.info("-" * 60)
        
        results = tester.measure_latency(
            num_packets=packets,
            packet_size=packet_size
        )
        
        # نمایش نتایج
        logger.info("-" * 60)
        logger.info("📈 Test Results:")
        logger.info(f"  Total Packets: {results['total_packets']}")
        logger.info(f"  Successful: {results['successful_packets']}")
        logger.info(f"  Failed: {results['failed_packets']}")
        logger.info(f"  Packet Loss: {results['packet_loss']:.2f}%")
        
        if results['successful_packets'] > 0:
            logger.info(f"  Min RTT: {results['min_rtt']:.3f} ms")
            logger.info(f"  Max RTT: {results['max_rtt']:.3f} ms")
            logger.info(f"  Avg RTT: {results['avg_rtt']:.3f} ms")
            logger.info(f"  Std Dev: {results['std_dev']:.3f} ms")
            
            if 'percentiles' in results:
                logger.info(f"  P50 (Median): {results['percentiles']['p50']:.3f} ms")
                logger.info(f"  P95: {results['percentiles']['p95']:.3f} ms")
                logger.info(f"  P99: {results['percentiles']['p99']:.3f} ms")
        
        # ذخیره نتایج
        if results['successful_packets'] > 0:
            logger.info("-" * 60)
            logger.info("💾 Saving results...")
            tester.save_results(output_prefix)
            logger.info(f"  ✅ Results saved with prefix: {output_prefix}")
        else:
            logger.warning("⚠️  No successful packets, skipping save")
        
        # توقف سرویس‌ها
        logger.info("🛑 Stopping services...")
        tester.stop_services()
        
        # قطع اتصال
        logger.info("🔌 Disconnecting...")
        tester.disconnect()
        
        logger.info("=" * 60)
        logger.info("✅ Test completed successfully!")
        logger.info("=" * 60)
        
        return results
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Test interrupted by user")
        if 'tester' in locals():
            tester.stop_services()
            tester.disconnect()
        return None
        
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        if 'tester' in locals():
            tester.stop_services()
            tester.disconnect()
        return None


def run_traffic_test(master_port='/dev/ttyUSB0',
                    slave_port='/dev/ttyUSB1',
                    duration=60,
                    traffic_rate=10,
                    probe_interval=5,
                    output_prefix='traffic_test',
                    enable_random_size=False,
                    enable_mavlink=False):
    """
    اجرای تست با ترافیک پس‌زمینه
    """
    logger.info("=" * 60)
    logger.info("🚀 Starting TRAFFIC RTT Test")
    logger.info("=" * 60)
    
    logger.info(f"Configuration:")
    logger.info(f"  Duration: {duration} seconds")
    logger.info(f"  Traffic Rate: {traffic_rate} msg/sec")
    logger.info(f"  Probe Interval: {probe_interval} seconds")
    
    # TODO: پیاده‌سازی تست با ترافیک
    logger.warning("⚠️  Traffic test not yet implemented")
    
    return None


def run_burst_test(master_port='/dev/ttyUSB0',
                  slave_port='/dev/ttyUSB1',
                  burst_size=50,
                  burst_count=10,
                  burst_interval=5,
                  output_prefix='burst_test'):
    """
    اجرای تست burst
    """
    logger.info("=" * 60)
    logger.info("🚀 Starting BURST RTT Test")
    logger.info("=" * 60)
    
    logger.info(f"Configuration:")
    logger.info(f"  Burst Size: {burst_size} packets")
    logger.info(f"  Burst Count: {burst_count}")
    logger.info(f"  Interval: {burst_interval} seconds")
    
    # TODO: پیاده‌سازی تست burst
    logger.warning("⚠️  Burst test not yet implemented")
    
    return None


def main():
    """نقطه ورود اصلی برنامه"""
    
    parser = argparse.ArgumentParser(
        description='P900 Network RTT Tester',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # تست ساده با 100 پکت
  python main.py --test isolated --packets 100
  
  # تست با اندازه رندوم و MAVLink payload
  python main.py --test isolated --random-size --mavlink-payload
  
  # تست با ترافیک پس‌زمینه
  python main.py --test traffic --duration 60 --traffic-rate 20
  
  # تست burst
  python main.py --test burst --burst-size 50 --burst-count 10
        """
    )
    
    # نوع تست
    parser.add_argument('--test', 
                       choices=['isolated', 'traffic', 'burst'],
                       default='isolated',
                       help='Test type to run')
    
    # پورت‌ها
    parser.add_argument('--master-port', 
                       default='/dev/ttyUSB0',
                       help='Master serial port')
    parser.add_argument('--slave-port',
                       default='/dev/ttyUSB1',
                       help='Slave serial port (None for single port)')
    
    # تنظیمات isolated test
    parser.add_argument('--packets', 
                       type=int, 
                       default=100,
                       help='Number of packets to send')
    parser.add_argument('--packet-size', 
                       type=int, 
                       default=64,
                       help='Base packet size in bytes')
    
    # قابلیت‌های جدید
    parser.add_argument('--random-size',
                       action='store_true',
                       help='Enable random packet sizes')
    parser.add_argument('--mavlink-payload',
                       action='store_true',
                       help='Use MAVLink-like payloads')
    parser.add_argument('--uniform-distribution',
                       action='store_true',
                       help='Use uniform distribution instead of realistic')
    
    # تنظیمات traffic test
    parser.add_argument('--duration',
                       type=int,
                       default=60,
                       help='Test duration in seconds')
    parser.add_argument('--traffic-rate',
                       type=int,
                       default=10,
                       help='Background traffic rate (msg/sec)')
    parser.add_argument('--probe-interval',
                       type=int,
                       default=5,
                       help='RTT probe interval (seconds)')
    
    # تنظیمات burst test
    parser.add_argument('--burst-size',
                       type=int,
                       default=50,
                       help='Number of packets per burst')
    parser.add_argument('--burst-count',
                       type=int,
                       default=10,
                       help='Number of bursts')
    parser.add_argument('--burst-interval',
                       type=int,
                       default=5,
                       help='Interval between bursts (seconds)')
    
    # خروجی
    parser.add_argument('--output',
                       help='Output file prefix (default: auto-generated)')
    
    # Verbose
    parser.add_argument('-v', '--verbose',
                       action='store_true',
                       help='Enable verbose output')
    
    args = parser.parse_args()
    
    # تولید نام خروجی اگر مشخص نشده
    if not args.output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"{args.test}_test_{timestamp}"
    
    # اطلاعات سیستم
    logger.info("=" * 60)
    logger.info("P900 Network RTT Tester v2.0")
    logger.info(f"System: {os.uname().sysname}")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # اجرای تست بر اساس نوع
    if args.test == 'isolated':
        results = run_isolated_test(
            master_port=args.master_port,
            slave_port=args.slave_port if args.slave_port != 'None' else None,
            packets=args.packets,
            packet_size=args.packet_size,
            output_prefix=args.output,
            enable_random_size=args.random_size,
            enable_mavlink=args.mavlink_payload,
            realistic_distribution=not args.uniform_distribution,
            verbose=args.verbose
        )
        
    elif args.test == 'traffic':
        results = run_traffic_test(
            master_port=args.master_port,
            slave_port=args.slave_port,
            duration=args.duration,
            traffic_rate=args.traffic_rate,
            probe_interval=args.probe_interval,
            output_prefix=args.output,
            enable_random_size=args.random_size,
            enable_mavlink=args.mavlink_payload
        )
        
    elif args.test == 'burst':
        results = run_burst_test(
            master_port=args.master_port,
            slave_port=args.slave_port,
            burst_size=args.burst_size,
            burst_count=args.burst_count,
            burst_interval=args.burst_interval,
            output_prefix=args.output
        )
    
    # خروج با کد مناسب
    if results:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
