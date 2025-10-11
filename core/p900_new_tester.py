#!/usr/bin/env python3
"""
P900 Network Performance Tester - Integrated Version (DEBUGGED)
تستر یکپارچه برای اندازه‌گیری تأثیر ترافیک بر RTT
Version: 3.1 - Fixed Integration Issues
"""

import time
import serial
import threading
import json
import argparse
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from collections import deque
import logging
import sys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import core components
try:
    from probe_injector import ProbeInjector
    from traffic_simulator import TrafficSimulator
    from packet_generator import PacketGenerator
    from mavlink_profile import MAVLinkProfile
except ImportError as e:
    logger.error(f"Failed to import core components: {e}")
    sys.exit(1)

class ComponentIntegrator:
    """مدیریت یکپارچه کامپوننت‌ها با رفع مشکلات Integration"""
    
    def __init__(self, master_port: str, slave_port: str, 
                 baudrate: int = 57600,
                 target_bandwidth: float = 2373.0):
        """
        Initialize component integrator
        
        Args:
            master_port: Master serial port path
            slave_port: Slave serial port path  
            baudrate: Serial baudrate
            target_bandwidth: Target traffic bandwidth in bytes/sec
        """
        self.master_port = master_port
        self.slave_port = slave_port
        self.baudrate = baudrate
        self.target_bandwidth = target_bandwidth
        
        # Serial objects
        self.master_serial = None
        self.slave_serial = None
        
        # Thread synchronization
        self.serial_lock = threading.Lock()
        
        # Components (initialized later)
        self.probe_injector = None
        self.traffic_simulator = None
        self.packet_generator = None
        
        logger.info(f"ComponentIntegrator initialized:")
        logger.info(f"  Master port: {master_port}")
        logger.info(f"  Slave port: {slave_port}")
        logger.info(f"  Target bandwidth: {target_bandwidth} bytes/sec")
        
    def initialize_serial_ports(self) -> bool:
        """Initialize and open serial ports with proper error handling"""
        try:
            # Open master port
            logger.info(f"Opening master port: {self.master_port}")
            self.master_serial = serial.Serial(
                port=self.master_port,  # ✅ استفاده از رشته پورت
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=0.1
            )
            
            # بررسی وضعیت باز بودن
            if not self.master_serial.is_open:
                self.master_serial.open()
            
            logger.info(f"Master port opened successfully: {self.master_serial.is_open}")
            
            # Open slave port
            logger.info(f"Opening slave port: {self.slave_port}")
            self.slave_serial = serial.Serial(
                port=self.slave_port,  # ✅ استفاده از رشته پورت
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=0.1
            )
            
            # بررسی وضعیت باز بودن
            if not self.slave_serial.is_open:
                self.slave_serial.open()
                
            logger.info(f"Slave port opened successfully: {self.slave_serial.is_open}")
            
            # Clear buffers
            self.master_serial.reset_input_buffer()
            self.master_serial.reset_output_buffer()
            self.slave_serial.reset_input_buffer()
            self.slave_serial.reset_output_buffer()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize serial ports: {e}")
            return False
            
    def initialize_components(self) -> bool:
        """Initialize all testing components with fixed integration"""
        try:
            # Initialize packet generator
            profile = MAVLinkProfile()
            self.packet_generator = PacketGenerator(profile)
            logger.info("PacketGenerator initialized")
            
            # Initialize probe injector with serial objects
            self.probe_injector = ProbeInjector(
                master_serial=self.master_serial,  # ✅ نام صحیح پارامتر
                slave_serial=self.slave_serial,     # ✅ نام صحیح پارامتر
                interval_ms=100,
                timeout_ms=500,
                packet_generator=self.packet_generator,
                size_mode='realistic',
                fixed_size=108
            )
            logger.info("ProbeInjector initialized")
            
            # Initialize traffic simulator - بدون write_lock
            self.traffic_simulator = TrafficSimulator(
                serial_port=self.master_serial,    # ✅ فقط serial_port
                target_bandwidth=self.target_bandwidth  # ✅ فقط target_bandwidth
                # ❌ حذف write_lock - این پارامتر وجود ندارد
            )
            logger.info("TrafficSimulator initialized")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    def cleanup(self):
        """Clean shutdown of all components"""
        logger.info("Starting cleanup...")
        
        # Stop components
        if self.probe_injector:
            self.probe_injector.stop()
            logger.info("ProbeInjector stopped")
            
        if self.traffic_simulator:
            self.traffic_simulator.stop()
            logger.info("TrafficSimulator stopped")
            
        # Close serial ports
        if self.master_serial and self.master_serial.is_open:
            self.master_serial.close()
            logger.info("Master port closed")
            
        if self.slave_serial and self.slave_serial.is_open:
            self.slave_serial.close()
            logger.info("Slave port closed")
            
        logger.info("Cleanup completed")

class P900Tester:
    """Main P900 testing orchestrator with correlation analysis"""
    
    # Traffic scenarios با پهنای باند واقعی
    TRAFFIC_SCENARIOS = {
        'light': 5760,      # 5.76 KB/s (46 kbps)
        'medium': 28800,    # 28.8 KB/s (230 kbps)  
        'heavy': 51840      # 51.84 KB/s (414 kbps)
    }
    
    def __init__(self, master_port: str, slave_port: str):
        """
        Initialize P900 tester
        
        Args:
            master_port: Master serial port
            slave_port: Slave serial port
        """
        self.master_port = master_port
        self.slave_port = slave_port
        self.integrator = None
        self.results = {}
        
        logger.info("P900Tester initialized")
        
    def run_baseline_test(self, duration: int = 30) -> Dict:
        """Run baseline RTT test without traffic"""
        logger.info(f"Starting baseline test for {duration} seconds...")
        
        # Initialize components for baseline
        self.integrator = ComponentIntegrator(
            self.master_port,
            self.slave_port,
            target_bandwidth=0  # No traffic for baseline
        )
        
        if not self.integrator.initialize_serial_ports():
            logger.error("Failed to initialize serial ports")
            return None
            
        if not self.integrator.initialize_components():
            logger.error("Failed to initialize components")
            return None
            
        # Start probe injection only
        self.integrator.probe_injector.start()
        
        # Wait for measurement duration
        time.sleep(duration)
        
        # Get statistics
        stats = self.integrator.probe_injector.get_statistics()
        
        # Stop and cleanup
        self.integrator.cleanup()
        
        result = {
            'duration': duration,
            'total_probes': stats.total_sent,
            'received_probes': stats.total_received,
            'lost_probes': stats.total_lost,
            'loss_rate': stats.loss_rate,
            'avg_rtt_ms': stats.avg_rtt_ms,
            'min_rtt_ms': stats.min_rtt_ms,
            'max_rtt_ms': stats.max_rtt_ms,
            'std_rtt_ms': stats.std_rtt_ms,
            'avg_jitter_ms': stats.avg_jitter_ms,
            'percentile_95_ms': stats.percentile_95_ms,
            'percentile_99_ms': stats.percentile_99_ms
        }
        
        logger.info(f"Baseline test completed: RTT={stats.avg_rtt_ms:.2f}ms, "
                   f"Loss={stats.loss_rate:.1f}%")
        
        return result
        
    def run_traffic_test(self, scenario: str, duration: int = 30) -> Dict:
        """Run test with traffic and probe injection"""
        bandwidth = self.TRAFFIC_SCENARIOS.get(scenario, 2373)
        logger.info(f"Starting {scenario} traffic test ({bandwidth} bytes/sec) "
                   f"for {duration} seconds...")
        
        # Initialize components with traffic
        self.integrator = ComponentIntegrator(
            self.master_port,
            self.slave_port,
            target_bandwidth=bandwidth
        )
        
        if not self.integrator.initialize_serial_ports():
            logger.error("Failed to initialize serial ports")
            return None
            
        if not self.integrator.initialize_components():
            logger.error("Failed to initialize components")
            return None
            
        # Start both traffic and probe injection
        self.integrator.probe_injector.start()
        
        # Start traffic in separate thread
        traffic_thread = threading.Thread(
            target=self.integrator.traffic_simulator.start,
            daemon=True
        )
        traffic_thread.start()
        
        # Wait for measurement
        time.sleep(duration)
        
        # Stop traffic first
        self.integrator.traffic_simulator.stop()
        time.sleep(1)  # Let traffic stop cleanly
        
        # Get statistics
        probe_stats = self.integrator.probe_injector.get_statistics()
        traffic_stats = self.integrator.traffic_simulator.get_stats()
        
        # Cleanup
        self.integrator.cleanup()
        
        result = {
            'scenario': scenario,
            'target_bandwidth': bandwidth,
            'actual_bandwidth': traffic_stats.get('actual_bandwidth', 0),
            'duration': duration,
            'traffic_packets_sent': traffic_stats.get('packets_sent', 0),
            'traffic_bytes_sent': traffic_stats.get('bytes_sent', 0),
            'probe_total': probe_stats.total_sent,
            'probe_received': probe_stats.total_received,
            'probe_lost': probe_stats.total_lost,
            'loss_rate': probe_stats.loss_rate,
            'avg_rtt_ms': probe_stats.avg_rtt_ms,
            'min_rtt_ms': probe_stats.min_rtt_ms,
            'max_rtt_ms': probe_stats.max_rtt_ms,
            'std_rtt_ms': probe_stats.std_rtt_ms,
            'avg_jitter_ms': probe_stats.avg_jitter_ms,
            'percentile_95_ms': probe_stats.percentile_95_ms,
            'percentile_99_ms': probe_stats.percentile_99_ms
        }
        
        logger.info(f"{scenario.capitalize()} traffic test completed: "
                   f"RTT={probe_stats.avg_rtt_ms:.2f}ms, "
                   f"Loss={probe_stats.loss_rate:.1f}%, "
                   f"Bandwidth={traffic_stats.get('actual_bandwidth', 0):.0f} bytes/sec")
        
        return result
        
    def calculate_correlation(self, baseline: Dict, traffic_results: List[Dict]) -> Dict:
        """Calculate correlation between traffic and RTT"""
        if not baseline or not traffic_results:
            return None
            
        # Extract data points
        bandwidths = [0]  # Start with baseline (0 bandwidth)
        rtts = [baseline['avg_rtt_ms']]
        jitters = [baseline['avg_jitter_ms']]
        losses = [baseline['loss_rate']]
        
        for result in traffic_results:
            if result:
                bandwidths.append(result['actual_bandwidth'])
                rtts.append(result['avg_rtt_ms'])
                jitters.append(result['avg_jitter_ms'])
                losses.append(result['loss_rate'])
                
        # Calculate correlations
        correlation = {
            'bandwidth_rtt_correlation': np.corrcoef(bandwidths, rtts)[0, 1],
            'bandwidth_jitter_correlation': np.corrcoef(bandwidths, jitters)[0, 1],
            'bandwidth_loss_correlation': np.corrcoef(bandwidths, losses)[0, 1],
            'rtt_increase_percent': ((max(rtts) - baseline['avg_rtt_ms']) / 
                                    baseline['avg_rtt_ms'] * 100),
            'max_rtt_at_bandwidth': bandwidths[rtts.index(max(rtts))],
            'data_points': {
                'bandwidths': bandwidths,
                'rtts': rtts,
                'jitters': jitters,
                'losses': losses
            }
        }
        
        return correlation
        
    def run_complete_test(self, scenarios: List[str] = None) -> Dict:
        """Run complete test suite with all scenarios"""
        if scenarios is None:
            scenarios = ['light', 'medium', 'heavy']
            
        logger.info("="*60)
        logger.info("Starting P900 Complete Test Suite")
        logger.info("="*60)
        
        # Run baseline test
        logger.info("\n>>> Phase 1: Baseline Test (No Traffic)")
        baseline = self.run_baseline_test(duration=30)
        if not baseline:
            logger.error("Baseline test failed!")
            return None
            
        self.results['baseline'] = baseline
        time.sleep(2)  # Brief pause between tests
        
        # Run traffic tests
        traffic_results = []
        for i, scenario in enumerate(scenarios, 1):
            logger.info(f"\n>>> Phase {i+1}: {scenario.capitalize()} Traffic Test")
            result = self.run_traffic_test(scenario, duration=30)
            if result:
                traffic_results.append(result)
                self.results[f'traffic_{scenario}'] = result
            time.sleep(2)  # Brief pause between tests
            
        # Calculate correlations
        logger.info("\n>>> Analyzing Correlations...")
        correlation = self.calculate_correlation(baseline, traffic_results)
        if correlation:
            self.results['correlation'] = correlation
            
        # Generate summary
        self.results['summary'] = self._generate_summary()
        
        logger.info("\n" + "="*60)
        logger.info("Test Suite Completed Successfully!")
        logger.info("="*60)
        
        return self.results
        
    def _generate_summary(self) -> Dict:
        """Generate test summary"""
        summary = {
            'timestamp': datetime.now().isoformat(),
            'test_configuration': {
                'master_port': self.master_port,
                'slave_port': self.slave_port,
                'scenarios_tested': list(self.TRAFFIC_SCENARIOS.keys())
            },
            'key_findings': {}
        }
        
        # Extract key findings
        if 'baseline' in self.results:
            summary['key_findings']['baseline_rtt_ms'] = self.results['baseline']['avg_rtt_ms']
            
        if 'correlation' in self.results:
            corr = self.results['correlation']
            summary['key_findings']['rtt_increase_percent'] = corr['rtt_increase_percent']
            summary['key_findings']['bandwidth_rtt_correlation'] = corr['bandwidth_rtt_correlation']
            
        # Find worst case
        max_rtt = 0
        worst_scenario = None
        for key, value in self.results.items():
            if key.startswith('traffic_') and 'avg_rtt_ms' in value:
                if value['avg_rtt_ms'] > max_rtt:
                    max_rtt = value['avg_rtt_ms']
                    worst_scenario = value['scenario']
                    
        if worst_scenario:
            summary['key_findings']['worst_case_scenario'] = worst_scenario
            summary['key_findings']['worst_case_rtt_ms'] = max_rtt
            
        return summary
        
    def save_results(self, filename: str = None):
        """Save test results to files"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"p900_test_{timestamp}"
            
        # Save JSON results
        json_file = f"{filename}_results.json"
        with open(json_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        logger.info(f"Results saved to {json_file}")
        
        # Save human-readable summary
        summary_file = f"{filename}_summary.txt"
        with open(summary_file, 'w') as f:
            f.write("P900 Network Performance Test Results\n")
            f.write("="*60 + "\n\n")
            
            # Baseline results
            if 'baseline' in self.results:
                f.write("BASELINE (No Traffic):\n")
                f.write(f"  Average RTT: {self.results['baseline']['avg_rtt_ms']:.2f} ms\n")
                f.write(f"  Packet Loss: {self.results['baseline']['loss_rate']:.1f}%\n")
                f.write(f"  Jitter: {self.results['baseline']['avg_jitter_ms']:.2f} ms\n\n")
                
            # Traffic test results
            for scenario in ['light', 'medium', 'heavy']:
                key = f'traffic_{scenario}'
                if key in self.results:
                    f.write(f"{scenario.upper()} TRAFFIC:\n")
                    f.write(f"  Bandwidth: {self.results[key]['actual_bandwidth']:.0f} bytes/sec\n")
                    f.write(f"  Average RTT: {self.results[key]['avg_rtt_ms']:.2f} ms\n")
                    f.write(f"  Packet Loss: {self.results[key]['loss_rate']:.1f}%\n")
                    f.write(f"  Jitter: {self.results[key]['avg_jitter_ms']:.2f} ms\n\n")
                    
            # Correlation results
            if 'correlation' in self.results:
                corr = self.results['correlation']
                f.write("CORRELATION ANALYSIS:\n")
                f.write(f"  Bandwidth-RTT Correlation: {corr['bandwidth_rtt_correlation']:.3f}\n")
                f.write(f"  RTT Increase: {corr['rtt_increase_percent']:.1f}%\n")
                f.write(f"  Max RTT at: {corr['max_rtt_at_bandwidth']:.0f} bytes/sec\n")
                
        logger.info(f"Summary saved to {summary_file}")

def main():
    """Main entry point with improved error handling"""
    parser = argparse.ArgumentParser(description='P900 Network Performance Tester')
    parser.add_argument('--master', required=True, help='Master serial port')
    parser.add_argument('--slave', required=True, help='Slave serial port')
    parser.add_argument('--scenario', choices=['baseline', 'light', 'medium', 'heavy', 'all'],
                       default='all', help='Test scenario to run')
    parser.add_argument('--duration', type=int, default=30,
                       help='Test duration in seconds')
    parser.add_argument('--output', help='Output filename prefix')
    
    args = parser.parse_args()
    
    # Create tester instance
    tester = P900Tester(args.master, args.slave)
    
    try:
        # Run tests based on scenario
        if args.scenario == 'baseline':
            results = {'baseline': tester.run_baseline_test(args.duration)}
        elif args.scenario == 'all':
            results = tester.run_complete_test()
        else:
            # Run baseline first, then specific scenario
            baseline = tester.run_baseline_test(args.duration)
            traffic = tester.run_traffic_test(args.scenario, args.duration)
            results = {
                'baseline': baseline,
                f'traffic_{args.scenario}': traffic
            }
            if baseline and traffic:
                correlation = tester.calculate_correlation(baseline, [traffic])
                results['correlation'] = correlation
                
        # Save results if successful
        if results:
            tester.results = results
            tester.save_results(args.output)
            
            # Print summary to console
            print("\n" + "="*60)
            print("TEST COMPLETED SUCCESSFULLY")
            print("="*60)
            
            if 'baseline' in results and results['baseline']:
                print(f"Baseline RTT: {results['baseline']['avg_rtt_ms']:.2f} ms")
                
            if 'correlation' in results and results['correlation']:
                print(f"RTT Increase: {results['correlation']['rtt_increase_percent']:.1f}%")
                print(f"Correlation: {results['correlation']['bandwidth_rtt_correlation']:.3f}")
                
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        if tester.integrator:
            tester.integrator.cleanup()
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        if tester.integrator:
            tester.integrator.cleanup()
        sys.exit(1)

if __name__ == "__main__":
    main()
