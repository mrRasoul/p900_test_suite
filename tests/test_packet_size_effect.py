#!/usr/bin/env python3
"""
Test A: Packet Size Effect on Latency
تست اثر اندازه پیام بر تأخیر شبکه P900
"""

import sys
import os
import time
import json
import numpy as np
import matplotlib.pyplot as plt
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.p900_tester import P900NetworkTesterEnhanced
from core.probe_injector import ProbeInjector
from utils.logger import setup_logger
from utils.path_helper import create_result_path, get_timestamp

logger = setup_logger('TestA_PacketSize')

class PacketSizeEffectTest:
    """
    تست اثر اندازه پیام بر تأخیر
    متغیر: Packet Size (8-279 bytes)
    ثابت: Send Rate (10 Hz)
    """
    
    # پارامترهای تست
    MIN_PACKET_SIZE = 8      # حداقل اندازه
    MAX_PACKET_SIZE = 279    # حداکثر اندازه
    PACKET_SIZE_STEP = 10    # گام افزایش اندازه
    SEND_RATE_HZ = 10        # نرخ ارسال ثابت
    PACKETS_PER_SIZE = 100   # تعداد پکت برای هر اندازه
    
    def __init__(self, master_port: str, slave_port: str, baudrate: int = 57600):
        self.master_port = master_port
        self.slave_port = slave_port
        self.baudrate = baudrate
        
        # لیست اندازه‌های تست
        self.packet_sizes = list(range(
            self.MIN_PACKET_SIZE,
            self.MAX_PACKET_SIZE + 1,
            self.PACKET_SIZE_STEP
        ))
        
        # نتایج
        self.results = {
            'packet_sizes': [],
            'forward_delays': [],
            'return_delays': [],
            'rtt_values': [],
            'forward_std': [],
            'return_std': [],
            'loss_rates': []
        }
        
        logger.info(f"Test A initialized:")
        logger.info(f"  Packet sizes: {self.MIN_PACKET_SIZE} to {self.MAX_PACKET_SIZE} bytes")
        logger.info(f"  Step: {self.PACKET_SIZE_STEP} bytes")
        logger.info(f"  Send rate: {self.SEND_RATE_HZ} Hz")
        logger.info(f"  Packets per size: {self.PACKETS_PER_SIZE}")
    
    def run_test(self) -> Dict:
        """اجرای تست کامل"""
        logger.info("="*60)
        logger.info("Starting Test A: Packet Size Effect")
        logger.info("="*60)
        
        # اتصال به رادیوها
        tester = P900NetworkTesterEnhanced(
            self.master_port,
            self.slave_port,
            self.baudrate
        )
        
        if not tester.connect():
            logger.error("Failed to connect to radios!")
            return None
        
        try:
            # تست برای هر اندازه پکت
            for size in self.packet_sizes:
                logger.info(f"\n{'='*40}")
                logger.info(f"Testing packet size: {size} bytes")
                logger.info(f"{'='*40}")
                
                # تنظیم اندازه پکت
                tester.TOTAL_PACKET_SIZE = size
                tester.PAYLOAD_SIZE = size - tester.HEADER_SIZE
                
                # اجرای اندازه‌گیری
                interval_ms = 1000 / self.SEND_RATE_HZ  # 100ms for 10Hz
                measurements = tester.measure_latency(
                    num_packets=self.PACKETS_PER_SIZE,
                    interval_ms=interval_ms
                )
                
                # محاسبه آمار برای این اندازه
                self._process_measurements(size, measurements)
                
                # استراحت بین تست‌ها
                time.sleep(2)
                
        finally:
            tester.disconnect()
        
        # تحلیل رگرسیون خطی
        self._perform_regression_analysis()
        
        # ذخیره نتایج
        self._save_results()
        
        # رسم نمودارها
        self._plot_results()
        
        return self.results
    
    def _process_measurements(self, packet_size: int, measurements: List):
        """پردازش نتایج برای یک اندازه مشخص"""
        ok_measurements = [m for m in measurements if m.status == "OK"]
        
        if not ok_measurements:
            logger.warning(f"No successful measurements for size {packet_size}")
            return
        
        # محاسبه میانگین و انحراف معیار
        forward_delays = [m.forward_delay_ms for m in ok_measurements]
        return_delays = [m.return_delay_ms for m in ok_measurements]
        rtt_values = [m.rtt_ms for m in ok_measurements]
        
        # ذخیره نتایج
        self.results['packet_sizes'].append(packet_size)
        self.results['forward_delays'].append(np.mean(forward_delays))
        self.results['return_delays'].append(np.mean(return_delays))
        self.results['rtt_values'].append(np.mean(rtt_values))
        self.results['forward_std'].append(np.std(forward_delays))
        self.results['return_std'].append(np.std(return_delays))
        
        # محاسبه نرخ خطا
        loss_rate = ((len(measurements) - len(ok_measurements)) / len(measurements)) * 100
        self.results['loss_rates'].append(loss_rate)
        
        # نمایش خلاصه
        logger.info(f"  Size {packet_size}B Results:")
        logger.info(f"    Forward: {np.mean(forward_delays):.2f} ± {np.std(forward_delays):.2f} ms")
        logger.info(f"    Return:  {np.mean(return_delays):.2f} ± {np.std(return_delays):.2f} ms")
        logger.info(f"    RTT:     {np.mean(rtt_values):.2f} ms")
        logger.info(f"    Loss:    {loss_rate:.1f}%")
    
    def _perform_regression_analysis(self):
        """تحلیل رگرسیون خطی: latency = a + b*size"""
        if len(self.results['packet_sizes']) < 2:
            return
        
        # رگرسیون برای Forward Delay
        x = np.array(self.results['packet_sizes'])
        y_forward = np.array(self.results['forward_delays'])
        
        # محاسبه ضرایب با numpy.polyfit
        coeffs_forward = np.polyfit(x, y_forward, 1)
        self.results['forward_regression'] = {
            'a': coeffs_forward[1],  # intercept
            'b': coeffs_forward[0],  # slope
            'r2': np.corrcoef(x, y_forward)[0, 1] ** 2
        }
        
        # رگرسیون برای Return Delay
        y_return = np.array(self.results['return_delays'])
        coeffs_return = np.polyfit(x, y_return, 1)
        self.results['return_regression'] = {
            'a': coeffs_return[1],
            'b': coeffs_return[0],
            'r2': np.corrcoef(x, y_return)[0, 1] ** 2
        }
        
        logger.info("\n" + "="*50)
        logger.info("📊 Regression Analysis Results:")
        logger.info("="*50)
        logger.info(f"Forward Delay = {coeffs_forward[1]:.3f} + {coeffs_forward[0]:.6f} * size")
        logger.info(f"  R² = {self.results['forward_regression']['r2']:.4f}")
        logger.info(f"Return Delay = {coeffs_return[1]:.3f} + {coeffs_return[0]:.6f} * size")
        logger.info(f"  R² = {self.results['return_regression']['r2']:.4f}")
    
    def _plot_results(self):
        """رسم نمودارهای تحلیلی"""
        timestamp = get_timestamp()
        
        # ایجاد figure با 4 subplot
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        fig.suptitle('Test A: Packet Size Effect on P900 Latency', fontsize=16, fontweight='bold')
        
        x = self.results['packet_sizes']
        
        # Plot 1: Forward & Return Delays
        ax1 = axes[0, 0]
        ax1.errorbar(x, self.results['forward_delays'], 
                    yerr=self.results['forward_std'],
                    marker='o', label='Forward Delay', capsize=5)
        ax1.errorbar(x, self.results['return_delays'],
                    yerr=self.results['return_std'],
                    marker='s', label='Return Delay', capsize=5)
        
        # اضافه کردن خط رگرسیون
        if 'forward_regression' in self.results:
            x_fit = np.linspace(min(x), max(x), 100)
            y_forward_fit = (self.results['forward_regression']['a'] + 
                           self.results['forward_regression']['b'] * x_fit)
            y_return_fit = (self.results['return_regression']['a'] + 
                          self.results['return_regression']['b'] * x_fit)
            ax1.plot(x_fit, y_forward_fit, '--', alpha=0.5, label='Forward Fit')
            ax1.plot(x_fit, y_return_fit, '--', alpha=0.5, label='Return Fit')
        
        ax1.set_xlabel('Packet Size (bytes)')
        ax1.set_ylabel('Delay (ms)')
        ax1.set_title('Forward vs Return Delay')
        ax1.grid(True, alpha=0.3)
        ax1.legend()
        
        # Plot 2: RTT
        ax2 = axes[0, 1]
        ax2.plot(x, self.results['rtt_values'], marker='o', color='green')
        ax2.set_xlabel('Packet Size (bytes)')
        ax2.set_ylabel('RTT (ms)')
        ax2.set_title('Round Trip Time')
        ax2.grid(True, alpha=0.3)
        
        # Plot 3: Packet Loss Rate
        ax3 = axes[1, 0]
        ax3.bar(x, self.results['loss_rates'], color='red', alpha=0.7)
        ax3.set_xlabel('Packet Size (bytes)')
        ax3.set_ylabel('Packet Loss (%)')
        ax3.set_title('Packet Loss Rate')
        ax3.grid(True, alpha=0.3)
        
        # Plot 4: Regression Summary
        ax4 = axes[1, 1]
        ax4.axis('off')
        
        if 'forward_regression' in self.results:
            summary_text = (
                "📊 Regression Analysis:\n\n"
                f"Forward Delay Model:\n"
                f"  Latency = {self.results['forward_regression']['a']:.3f} + "
                f"{self.results['forward_regression']['b']:.6f} × Size\n"
                f"  R² = {self.results['forward_regression']['r2']:.4f}\n\n"
                f"Return Delay Model:\n"
                f"  Latency = {self.results['return_regression']['a']:.3f} + "
                f"{self.results['return_regression']['b']:.6f} × Size\n"
                f"  R² = {self.results['return_regression']['r2']:.4f}\n\n"
                f"Interpretation:\n"
                f"  • Base latency (a): ~{self.results['forward_regression']['a']:.1f} ms\n"
                f"  • Size effect (b): ~{self.results['forward_regression']['b']*100:.3f} ms/100bytes"
            )
            ax4.text(0.1, 0.5, summary_text, fontsize=11, 
                    verticalalignment='center', family='monospace')
        
        plt.tight_layout()
        
        # ذخیره نمودار
        filename = create_result_path(f'test_a_packet_size_{timestamp}.png')
        plt.savefig(filename, dpi=300, bbox_inches='tight')
        plt.show()
        
        logger.info(f"📈 Plot saved: {filename}")
    
    def _save_results(self):
        """ذخیره نتایج در فایل JSON"""
        timestamp = get_timestamp()