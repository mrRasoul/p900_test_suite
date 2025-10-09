#!/usr/bin/env python3
"""
Integrated P900 Network Performance Tester
تستر یکپارچه برای اندازه‌گیری تأثیر ترافیک MAVLink بر RTT شبکه P900

این تستر ترکیبی از:
- TrafficSimulator: برای تولید ترافیک MAVLink واقعی
- ProbeInjector: برای اندازه‌گیری RTT
- تحلیل همبستگی بین ترافیک و تأخیر
"""

import time
import json
import threading
import queue
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
import logging
import numpy as np
import serial
import sys

# Import existing components
from traffic_simulator import TrafficSimulator
from probe_injector import ProbeInjector
from mavlink_profile import MAVLinkProfile
from packet_generator import PacketGenerator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Data Structures and Enums
# ═══════════════════════════════════════════════════════════════════

class TestScenario(Enum):
    """انواع سناریوهای تست"""
    BASELINE = "baseline"           # فقط probe، بدون ترافیک
    LIGHT_TRAFFIC = "light"        # 10% bandwidth utilization
    MEDIUM_TRAFFIC = "medium"      # 50% bandwidth utilization
    HEAVY_TRAFFIC = "heavy"        # 90% bandwidth utilization
    BURST_TRAFFIC = "burst"        # ترافیک متغیر
    CUSTOM = "custom"              # تنظیمات سفارشی

@dataclass
class ScenarioConfig:
    """پیکربندی یک سناریو تست"""
    name: str
    description: str
    traffic_enabled: bool
    target_bandwidth_bps: float
    probe_interval_ms: float
    probe_count: int
    test_duration_seconds: float
    warmup_seconds: float = 2.0
    cooldown_seconds: float = 1.0

@dataclass
class TestMetadata:
    """متادیتای یک تست"""
    test_id: str
    timestamp: str
    scenario: str
    serial_ports: Dict[str, str]
    baudrate: int
    total_duration: float = 0.0

@dataclass
class CombinedResults:
    """نتایج ترکیبی تست"""
    metadata: TestMetadata
    baseline_metrics: Optional[Dict] = None
    traffic_metrics: Optional[Dict] = None
    under_traffic_metrics: Optional[Dict] = None
    correlation_analysis: Optional[Dict] = None
    raw_measurements: List[Dict] = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════════
# Scenario Manager - مدیریت سناریوهای تست
# ═══════════════════════════════════════════════════════════════════

class ScenarioManager:
    """مدیریت سناریوهای مختلف تست"""

    # تعریف سناریوهای استاندارد
    PREDEFINED_SCENARIOS = {
        TestScenario.BASELINE: ScenarioConfig(
            name="Baseline",
            description="RTT measurement without traffic",
            traffic_enabled=False,
            target_bandwidth_bps=0,
            probe_interval_ms=100,
            probe_count=100,
            test_duration_seconds=30
        ),
        TestScenario.LIGHT_TRAFFIC: ScenarioConfig(
            name="Light Traffic",
            description="10% bandwidth utilization",
            traffic_enabled=True,
            target_bandwidth_bps=5760,  # 10% of 57600
            probe_interval_ms=100,
            probe_count=100,
            test_duration_seconds=30
        ),
        TestScenario.MEDIUM_TRAFFIC: ScenarioConfig(
            name="Medium Traffic",
            description="50% bandwidth utilization",
            traffic_enabled=True,
            target_bandwidth_bps=28800,  # 50% of 57600
            probe_interval_ms=100,
            probe_count=100,
            test_duration_seconds=30
        ),
        TestScenario.HEAVY_TRAFFIC: ScenarioConfig(
            name="Heavy Traffic",
            description="90% bandwidth utilization",
            traffic_enabled=True,
            target_bandwidth_bps=51840,  # 90% of 57600
            probe_interval_ms=100,
            probe_count=100,
            test_duration_seconds=30
        )
    }

    @classmethod
    def get_scenario(cls, scenario_type: TestScenario) -> ScenarioConfig:
        """دریافت پیکربندی سناریو"""
        return cls.PREDEFINED_SCENARIOS.get(
            scenario_type,
            cls.PREDEFINED_SCENARIOS[TestScenario.BASELINE]
        )

    @classmethod
    def create_custom_scenario(cls, **kwargs) -> ScenarioConfig:
        """ایجاد سناریو سفارشی"""
        defaults = asdict(cls.PREDEFINED_SCENARIOS[TestScenario.BASELINE])
        defaults.update(kwargs)
        defaults['name'] = kwargs.get('name', 'Custom')
        defaults['description'] = kwargs.get('description', 'Custom scenario')
        return ScenarioConfig(**defaults)

# ═══════════════════════════════════════════════════════════════════
# Component Integrator - یکپارچه‌سازی کامپوننت‌ها
# ═══════════════════════════════════════════════════════════════════

class ComponentIntegrator:
    """یکپارچه‌سازی و مدیریت کامپوننت‌های موجود"""

    def __init__(self, master_port: str, slave_port: str, baudrate: int = 57600):
        """
        Args:
            master_port: پورت محلی (Master) - مسیر پورت سریال
            slave_port: پورت دور (Slave) - مسیر پورت سریال
            baudrate: سرعت سریال
        """
        self.master_port = master_port  # رشته مسیر پورت
        self.slave_port = slave_port    # رشته مسیر پورت
        self.baudrate = baudrate

        # کامپوننت‌ها
        self.traffic_simulator: Optional[TrafficSimulator] = None
        self.probe_injector: Optional[ProbeInjector] = None
        self.mavlink_profile: Optional[MAVLinkProfile] = None

        # Serial connections - اینها شیء Serial هستند
        self.master_serial: Optional[serial.Serial] = None
        self.slave_serial: Optional[serial.Serial] = None

        # Component status
        self.components_ready = False
        self.serial_lock = threading.Lock()

    def initialize_serial_ports(self) -> bool:
        """راه‌اندازی پورت‌های سریال"""
        try:
            # Master port - ایجاد و باز کردن
            logger.info(f"Opening master port: {self.master_port}")
            self.master_serial = serial.Serial(
                port=self.master_port,  # مسیر پورت
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=1.0
            )
            
            # بررسی وضعیت پورت
            if not self.master_serial.is_open:
                logger.warning("Master port created but not open, attempting to open...")
                self.master_serial.open()
            
            if self.master_serial.is_open:
                logger.info(f"✅ Master serial port opened successfully: {self.master_serial}")
            else:
                raise RuntimeError(f"Failed to open master port: {self.master_port}")

            # Slave port - ایجاد و باز کردن
            logger.info(f"Opening slave port: {self.slave_port}")
            self.slave_serial = serial.Serial(
                port=self.slave_port,  # مسیر پورت
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=1.0
            )
            
            # بررسی وضعیت پورت
            if not self.slave_serial.is_open:
                logger.warning("Slave port created but not open, attempting to open...")
                self.slave_serial.open()
                
            if self.slave_serial.is_open:
                logger.info(f"✅ Slave serial port opened successfully: {self.slave_serial}")
            else:
                raise RuntimeError(f"Failed to open slave port: {self.slave_port}")

            # Clear buffers - فقط اگر پورت‌ها باز باشند
            if self.master_serial.is_open:
                self.master_serial.reset_input_buffer()
                self.master_serial.reset_output_buffer()
                logger.debug("Master port buffers cleared")
            
            if self.slave_serial.is_open:
                self.slave_serial.reset_input_buffer()
                self.slave_serial.reset_output_buffer()
                logger.debug("Slave port buffers cleared")

            logger.info("✅ Both serial ports initialized successfully")
            return True

        except serial.SerialException as e:
            logger.error(f"❌ Serial port error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to initialize serial ports: {e}")
            # تلاش برای بستن پورت‌های نیمه‌باز
            if self.master_serial and self.master_serial.is_open:
                self.master_serial.close()
            if self.slave_serial and self.slave_serial.is_open:
                self.slave_serial.close()
            return False

    def create_traffic_simulator(self, target_bandwidth: float) -> TrafficSimulator:
        """ایجاد شبیه‌ساز ترافیک"""
        if not self.master_serial or not self.master_serial.is_open:
            raise RuntimeError("Master serial port not initialized or not open")

        # TrafficSimulator انتظار serial object دارد، نه string
        self.traffic_simulator = TrafficSimulator(
            serial_port=self.master_serial,  # شیء Serial
            target_bandwidth=target_bandwidth,
            write_lock=self.serial_lock
        )
        logger.info(f"✅ Traffic simulator created (target: {target_bandwidth} bps)")
        return self.traffic_simulator

    def create_probe_injector(self) -> ProbeInjector:
        """ایجاد تزریق‌کننده probe"""
        if not self.master_serial or not self.slave_serial:
            raise RuntimeError("Serial ports not initialized")
        
        if not self.master_serial.is_open or not self.slave_serial.is_open:
            raise RuntimeError("Serial ports not open")

        # ProbeInjector انتظار serial objects دارد
        # توجه: نام پارامترها در ProbeInjector باید بررسی شود
        self.probe_injector = ProbeInjector(
            master_serial=self.master_serial,  # شیء Serial (نه string)
            slave_serial=self.slave_serial      # شیء Serial (نه string)
        )
        logger.info("✅ Probe injector created")
        return self.probe_injector

    def load_mavlink_profile(self, profile_path: Optional[str] = None) -> MAVLinkProfile:
        """بارگذاری پروفایل MAVLink"""
        self.mavlink_profile = MAVLinkProfile(profile_path)
        logger.info("✅ MAVLink profile loaded")
        return self.mavlink_profile

    def cleanup(self):
        """پاکسازی منابع"""
        try:
            if self.master_serial and self.master_serial.is_open:
                self.master_serial.close()
                logger.info("Master serial port closed")

            if self.slave_serial and self.slave_serial.is_open:
                self.slave_serial.close()
                logger.info("Slave serial port closed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

# ═══════════════════════════════════════════════════════════════════
# Test Orchestrator - هماهنگ‌کننده اصلی تست
# ═══════════════════════════════════════════════════════════════════

class IntegratedP900Tester:
    """تستر یکپارچه P900 - ترکیب ترافیک و اندازه‌گیری RTT"""

    def __init__(self, master_port: str, slave_port: str, baudrate: int = 57600):
        """
        Args:
            master_port: پورت Master (محلی) - مسیر پورت
            slave_port: پورت Slave (دور) - مسیر پورت
            baudrate: سرعت سریال
        """
        # Configuration
        self.master_port = master_port
        self.slave_port = slave_port
        self.baudrate = baudrate

        # Components
        self.integrator = ComponentIntegrator(master_port, slave_port, baudrate)
        self.scenario_manager = ScenarioManager()

        # Results storage
        self.test_results: List[CombinedResults] = []
        self.current_test: Optional[CombinedResults] = None

        # Thread management
        self.traffic_thread: Optional[threading.Thread] = None
        self.probe_thread: Optional[threading.Thread] = None
        self.monitor_thread: Optional[threading.Thread] = None

        # Synchronization
        self.test_running = False
        self.traffic_active = threading.Event()
        self.results_queue = queue.Queue()

        # Statistics
        self.traffic_stats = {}
        self.probe_stats = {}

    def initialize(self) -> bool:
        """راه‌اندازی اولیه سیستم"""
        logger.info("="*60)
        logger.info("🚀 Initializing Integrated P900 Tester")
        logger.info("="*60)

        # Initialize serial ports
        if not self.integrator.initialize_serial_ports():
            logger.error("Failed to initialize serial ports")
            return False

        # Load MAVLink profile
        try:
            self.integrator.load_mavlink_profile()
        except Exception as e:
            logger.error(f"Failed to load MAVLink profile: {e}")
            # این خطا critical نیست، می‌توانیم ادامه دهیم
            
        logger.info("✅ System initialized successfully")
        return True

    def run_scenario(self, scenario: TestScenario) -> CombinedResults:
        """اجرای یک سناریو تست کامل"""
        config = self.scenario_manager.get_scenario(scenario)
        logger.info(f"\n📋 Running scenario: {config.name}")
        logger.info(f"   Description: {config.description}")

        # Create test metadata
        test_id = f"p900_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        metadata = TestMetadata(
            test_id=test_id,
            timestamp=datetime.now().isoformat(),
            scenario=config.name,
            serial_ports={
                'master': self.master_port,
                'slave': self.slave_port
            },
            baudrate=self.baudrate
        )

        # Initialize results container
        self.current_test = CombinedResults(metadata=metadata)

        # Execute test phases
        start_time = time.perf_counter()

        try:
            # Phase 1: Baseline measurement (always)
            logger.info("\n📊 Phase 1: Baseline Measurement")
            baseline_metrics = self._run_baseline_measurement(config)
            self.current_test.baseline_metrics = baseline_metrics

            # Phase 2: Traffic + Probe (if traffic enabled)
            if config.traffic_enabled:
                logger.info("\n📊 Phase 2: Combined Traffic + Probe Measurement")
                combined_metrics = self._run_combined_measurement(config)
                self.current_test.under_traffic_metrics = combined_metrics['probe_metrics']
                self.current_test.traffic_metrics = combined_metrics['traffic_metrics']

                # Phase 3: Correlation analysis
                logger.info("\n📊 Phase 3: Correlation Analysis")
                correlation = self._analyze_correlation()
                self.current_test.correlation_analysis = correlation

            # Update metadata
            self.current_test.metadata.total_duration = time.perf_counter() - start_time

            # Store results
            self.test_results.append(self.current_test)

            logger.info(f"\n✅ Scenario '{config.name}' completed successfully!")
            return self.current_test

        except Exception as e:
            logger.error(f"❌ Error during scenario execution: {e}")
            raise

    def _run_baseline_measurement(self, config: ScenarioConfig) -> Dict:
        """اجرای اندازه‌گیری baseline (بدون ترافیک)"""
        logger.info("  ⏱️ Starting baseline measurement...")

        try:
            # Create probe injector با تنظیمات baseline
            probe = self.integrator.create_probe_injector()

            # تنظیم پارامترها
            probe.interval_ms = config.probe_interval_ms
            probe.timeout_ms = 500  # 500ms timeout

            # شروع probe injection
            probe.start()

            # اجرا برای مدت مشخص
            test_duration = min(config.test_duration_seconds, 30)  # حداکثر 30 ثانیه برای baseline
            logger.info(f"  Running baseline for {test_duration} seconds...")

            start_time = time.perf_counter()
            while time.perf_counter() - start_time < test_duration:
                # نمایش پیشرفت هر 5 ثانیه
                if int(time.perf_counter() - start_time) % 5 == 0:
                    stats = probe.get_statistics()
                    logger.info(f"    Progress: Sent={stats.total_sent}, "
                              f"Received={stats.total_received}, "
                              f"Loss={stats.loss_rate:.1f}%")
                time.sleep(1)

            # توقف و دریافت نتایج
            probe.stop()
            final_stats = probe.get_statistics()

            # تبدیل به فرمت استاندارد
            baseline_metrics = {
                'probe_count': final_stats.total_sent,
                'successful_probes': final_stats.total_received,
                'loss_rate': final_stats.loss_rate,
                'rtt': {
                    'mean': final_stats.avg_rtt_ms,
                    'min': final_stats.min_rtt_ms,
                    'max': final_stats.max_rtt_ms,
                    'std': final_stats.std_rtt_ms,
                    'p95': final_stats.percentile_95_ms,
                    'p99': final_stats.percentile_99_ms
                },
                'jitter': {
                    'mean': final_stats.avg_jitter_ms,
                    'max': final_stats.max_jitter_ms
                },
                'test_duration': test_duration
            }

            logger.info(f"  ✅ Baseline complete: RTT={final_stats.avg_rtt_ms:.2f}ms, "
                       f"Loss={final_stats.loss_rate:.1f}%")

            return baseline_metrics

        except Exception as e:
            logger.error(f"❌ Error in baseline measurement: {e}")
            raise

    def _run_combined_measurement(self, config: ScenarioConfig) -> Dict:
        """اجرای اندازه‌گیری ترکیبی (ترافیک + پروب)"""
        logger.info("  🔄 Starting combined measurement...")

        try:
            # Phase 2.1: Start traffic generation
            traffic_sim = self.integrator.create_traffic_simulator(
                target_bandwidth=config.target_bandwidth_bps
            )

            # شروع ترافیک در thread جداگانه
            self.traffic_active.clear()
            traffic_thread = threading.Thread(
                target=self._run_traffic_generator,
                args=(traffic_sim, config.test_duration_seconds),
                name="TrafficGenerator"
            )
            traffic_thread.start()

            # صبر برای warmup ترافیک
            logger.info(f"  ⏳ Warming up traffic for {config.warmup_seconds}s...")
            time.sleep(config.warmup_seconds)

            # Phase 2.2: Start probe injection with traffic
            probe = self.integrator.create_probe_injector()
            probe.interval_ms = config.probe_interval_ms
            probe.timeout_ms = 500

            probe.start()

            # Monitor both traffic and probes
            monitor_start = time.perf_counter()
            probe_duration = config.test_duration_seconds - config.warmup_seconds

            logger.info(f"  📊 Measuring RTT under traffic load for {probe_duration}s...")

            # جمع‌آوری آمار دوره‌ای
            periodic_stats = []

            while time.perf_counter() - monitor_start < probe_duration:
                # ثبت آمار هر ثانیه
                current_time = time.perf_counter() - monitor_start

                # دریافت آمار لحظه‌ای
                probe_stats = probe.get_statistics()
                traffic_stats = traffic_sim.get_stats()

                periodic_stats.append({
                    'timestamp': current_time,
                    'probe_stats': {
                        'sent': probe_stats.total_sent,
                        'received': probe_stats.total_received,
                        'rtt_ms': probe_stats.avg_rtt_ms,
                        'loss_rate': probe_stats.loss_rate
                    },
                    'traffic_stats': {
                        'packets_sent': traffic_stats.get('packets_sent', 0),
                        'bytes_sent': traffic_stats.get('bytes_sent', 0),
                        'actual_bandwidth': traffic_stats.get('actual_bandwidth', 0)
                    }
                })

                # نمایش پیشرفت هر 5 ثانیه
                if int(current_time) % 5 == 0 and int(current_time) > 0:
                    logger.info(f"    Progress: Time={int(current_time)}s, "
                              f"RTT={probe_stats.avg_rtt_ms:.2f}ms, "
                              f"Traffic={traffic_stats.get('actual_bandwidth', 0):.0f}bps")

                time.sleep(1)

            # توقف کامپوننت‌ها
            logger.info("  🛑 Stopping components...")
            probe.stop()
            self.traffic_active.set()  # سیگنال توقف به traffic
            traffic_thread.join(timeout=2)

            # دریافت آمار نهایی
            final_probe_stats = probe.get_statistics()
            final_traffic_stats = traffic_sim.get_stats()

            # ساختار نتایج ترکیبی
            combined_metrics = {
                'probe_metrics': {
                    'probe_count': final_probe_stats.total_sent,
                    'successful_probes': final_probe_stats.total_received,
                    'loss_rate': final_probe_stats.loss_rate,
                    'rtt': {
                        'mean': final_probe_stats.avg_rtt_ms,
                        'min': final_probe_stats.min_rtt_ms,
                        'max': final_probe_stats.max_rtt_ms,
                        'std': final_probe_stats.std_rtt_ms,
                        'p95': final_probe_stats.percentile_95_ms,
                        'p99': final_probe_stats.percentile_99_ms
                    },
                    'jitter': {
                        'mean': final_probe_stats.avg_jitter_ms,
                        'max': final_probe_stats.max_jitter_ms
                    }
                },
                'traffic_metrics': {
                    'target_bandwidth': config.target_bandwidth_bps,
                    'actual_bandwidth': final_traffic_stats.get('actual_bandwidth', 0),
                    'total_packets': final_traffic_stats.get('packets_sent', 0),
                    'total_bytes': final_traffic_stats.get('bytes_sent', 0),
                    'duration': final_traffic_stats.get('elapsed_time', 0),
                    'errors': final_traffic_stats.get('errors', 0)
                },
                'periodic_measurements': periodic_stats
            }

            # ذخیره در raw measurements برای تحلیل بعدی
            self.current_test.raw_measurements = periodic_stats

            logger.info(f"  ✅ Combined measurement complete: "
                       f"RTT={final_probe_stats.avg_rtt_ms:.2f}ms under "
                       f"{final_traffic_stats.get('actual_bandwidth', 0):.0f}bps traffic")

            return combined_metrics

        except Exception as e:
            logger.error(f"❌ Error in combined measurement: {e}")
            # تلاش برای توقف کامپوننت‌ها
            self.traffic_active.set()
            raise

    def _run_traffic_generator(self, traffic_sim: TrafficSimulator, duration: float):
        """اجرای traffic generator در thread جداگانه"""
        try:
            logger.debug(f"Traffic generator thread started for {duration}s")
            start_time = time.perf_counter()
            
            # شروع تولید ترافیک
            traffic_sim.running = True
            
            while time.perf_counter() - start_time < duration:
                if self.traffic_active.is_set():
                    logger.debug("Traffic generation stopped by signal")
                    break
                    
                # ارسال پکت
                traffic_sim._send_single_packet()
                
                # کنترل نرخ ارسال
                time.sleep(traffic_sim.packet_interval)
            
            traffic_sim.running = False
            logger.debug("Traffic generator thread completed")
            
        except Exception as e:
            logger.error(f"Error in traffic generator thread: {e}")

    def _analyze_correlation(self) -> Dict:
        """تحلیل همبستگی بین ترافیک و تأخیر"""
        if not self.current_test or not self.current_test.raw_measurements:
            return {}

        try:
            measurements = self.current_test.raw_measurements
            
            # استخراج سری‌های زمانی
            timestamps = [m['timestamp'] for m in measurements]
            rtt_values = [m['probe_stats']['rtt_ms'] for m in measurements]
            bandwidth_values = [m['traffic_stats']['actual_bandwidth'] for m in measurements]
            
# ادامه کد از جایی که قطع شده بود...

            # محاسبه همبستگی
            if len(rtt_values) > 1 and len(bandwidth_values) > 1:
                correlation_coefficient = np.corrcoef(rtt_values, bandwidth_values)[0, 1]
                
                # محاسبه رگرسیون خطی ساده
                z = np.polyfit(bandwidth_values, rtt_values, 1)
                p = np.poly1d(z)
                
                # محاسبه R-squared
                y_pred = p(bandwidth_values)
                ss_res = np.sum((rtt_values - y_pred) ** 2)
                ss_tot = np.sum((rtt_values - np.mean(rtt_values)) ** 2)
                r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
                
                correlation_analysis = {
                    'correlation_coefficient': float(correlation_coefficient),
                    'r_squared': float(r_squared),
                    'regression_slope': float(z[0]),
                    'regression_intercept': float(z[1]),
                    'impact_assessment': {
                        'low': 'Minimal impact' if abs(correlation_coefficient) < 0.3 else 'Some impact',
                        'medium': 'Moderate impact' if 0.3 <= abs(correlation_coefficient) < 0.7 else 'Significant impact',
                        'high': 'Strong impact' if abs(correlation_coefficient) >= 0.7 else 'Variable impact'
                    }
                }
                
                # تحلیل تغییرات نسبی
                if self.current_test.baseline_metrics and self.current_test.under_traffic_metrics:
                    baseline_rtt = self.current_test.baseline_metrics['rtt']['mean']
                    traffic_rtt = self.current_test.under_traffic_metrics['rtt']['mean']
                    
                    baseline_loss = self.current_test.baseline_metrics['loss_rate']
                    traffic_loss = self.current_test.under_traffic_metrics['loss_rate']
                    
                    correlation_analysis['relative_changes'] = {
                        'rtt_increase_percent': ((traffic_rtt - baseline_rtt) / baseline_rtt * 100) if baseline_rtt > 0 else 0,
                        'rtt_increase_ms': traffic_rtt - baseline_rtt,
                        'loss_increase_percent': traffic_loss - baseline_loss,
                        'baseline_rtt_ms': baseline_rtt,
                        'traffic_rtt_ms': traffic_rtt
                    }
                    
                logger.info(f"  📊 Correlation coefficient: {correlation_coefficient:.3f}")
                logger.info(f"  📈 RTT increase under traffic: {correlation_analysis.get('relative_changes', {}).get('rtt_increase_percent', 0):.1f}%")
                
                return correlation_analysis
            else:
                logger.warning("Insufficient data for correlation analysis")
                return {}
                
        except Exception as e:
            logger.error(f"Error in correlation analysis: {e}")
            return {}

    def run_all_scenarios(self) -> List[CombinedResults]:
        """اجرای تمام سناریوهای استاندارد"""
        logger.info("\n" + "="*60)
        logger.info("🚀 Running All Standard Scenarios")
        logger.info("="*60)
        
        scenarios = [
            TestScenario.BASELINE,
            TestScenario.LIGHT_TRAFFIC,
            TestScenario.MEDIUM_TRAFFIC,
            TestScenario.HEAVY_TRAFFIC
        ]
        
        results = []
        for scenario in scenarios:
            try:
                logger.info(f"\n{'='*40}")
                logger.info(f"Scenario {scenarios.index(scenario) + 1}/{len(scenarios)}")
                result = self.run_scenario(scenario)
                results.append(result)
                
                # کمی استراحت بین سناریوها
                if scenario != scenarios[-1]:
                    logger.info("⏳ Cooling down for 5 seconds...")
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"Failed to run scenario {scenario.value}: {e}")
                continue
        
        return results

    def generate_report(self, output_dir: str = "results") -> Dict:
        """تولید گزارش جامع از نتایج تست"""
        if not self.test_results:
            logger.warning("No test results to report")
            return {}
        
        # ایجاد دایرکتوری خروجی
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # تولید گزارش خلاصه
        summary = {
            'test_suite': 'P900 Network Performance Analysis',
            'timestamp': datetime.now().isoformat(),
            'total_tests': len(self.test_results),
            'scenarios': []
        }
        
        for result in self.test_results:
            scenario_summary = {
                'name': result.metadata.scenario,
                'test_id': result.metadata.test_id,
                'duration': result.metadata.total_duration,
                'baseline': {
                    'rtt_ms': result.baseline_metrics['rtt']['mean'] if result.baseline_metrics else None,
                    'loss_percent': result.baseline_metrics['loss_rate'] if result.baseline_metrics else None
                }
            }
            
            # اگر تست ترافیک داشت
            if result.under_traffic_metrics:
                scenario_summary['under_traffic'] = {
                    'rtt_ms': result.under_traffic_metrics['rtt']['mean'],
                    'loss_percent': result.under_traffic_metrics['loss_rate'],
                    'jitter_ms': result.under_traffic_metrics['jitter']['mean']
                }
                
            if result.traffic_metrics:
                scenario_summary['traffic'] = {
                    'target_bps': result.traffic_metrics['target_bandwidth'],
                    'actual_bps': result.traffic_metrics['actual_bandwidth'],
                    'total_packets': result.traffic_metrics['total_packets']
                }
                
            if result.correlation_analysis:
                scenario_summary['correlation'] = {
                    'coefficient': result.correlation_analysis['correlation_coefficient'],
                    'r_squared': result.correlation_analysis['r_squared']
                }
                
            summary['scenarios'].append(scenario_summary)
        
        # ذخیره گزارش JSON
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        json_path = output_path / f"p900_test_{timestamp}_results.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        # تولید گزارش متنی
        text_report = self._generate_text_report(summary)
        text_path = output_path / f"p900_test_{timestamp}_summary.txt"
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(text_report)
        
        logger.info(f"\n📊 Reports saved to:")
        logger.info(f"   JSON: {json_path}")
        logger.info(f"   Text: {text_path}")
        
        return summary

    def _generate_text_report(self, summary: Dict) -> str:
        """تولید گزارش متنی قابل خواندن"""
        lines = []
        lines.append("="*70)
        lines.append("P900 NETWORK PERFORMANCE TEST REPORT")
        lines.append("="*70)
        lines.append(f"Generated: {summary['timestamp']}")
        lines.append(f"Total Tests: {summary['total_tests']}")
        lines.append("")
        
        for scenario in summary['scenarios']:
            lines.append("-"*50)
            lines.append(f"SCENARIO: {scenario['name']}")
            lines.append(f"Test ID: {scenario['test_id']}")
            lines.append(f"Duration: {scenario['duration']:.1f} seconds")
            lines.append("")
            
            # Baseline results
            if scenario['baseline']:
                lines.append("Baseline Performance (No Traffic):")
                lines.append(f"  • RTT: {scenario['baseline']['rtt_ms']:.2f} ms")
                lines.append(f"  • Loss: {scenario['baseline']['loss_percent']:.1f}%")
                lines.append("")
            
            # Under traffic results
            if 'under_traffic' in scenario:
                lines.append("Performance Under Traffic:")
                lines.append(f"  • RTT: {scenario['under_traffic']['rtt_ms']:.2f} ms")
                lines.append(f"  • Loss: {scenario['under_traffic']['loss_percent']:.1f}%")
                lines.append(f"  • Jitter: {scenario['under_traffic']['jitter_ms']:.2f} ms")
                
                # Calculate impact
                if scenario['baseline']:
                    rtt_increase = scenario['under_traffic']['rtt_ms'] - scenario['baseline']['rtt_ms']
                    rtt_increase_pct = (rtt_increase / scenario['baseline']['rtt_ms'] * 100) if scenario['baseline']['rtt_ms'] > 0 else 0
                    lines.append(f"  • RTT Increase: +{rtt_increase:.2f} ms ({rtt_increase_pct:+.1f}%)")
                lines.append("")
            
            # Traffic statistics
            if 'traffic' in scenario:
                lines.append("Traffic Generation:")
                lines.append(f"  • Target Bandwidth: {scenario['traffic']['target_bps']:.0f} bps")
                lines.append(f"  • Actual Bandwidth: {scenario['traffic']['actual_bps']:.0f} bps")
                lines.append(f"  • Total Packets: {scenario['traffic']['total_packets']}")
                lines.append("")
            
            # Correlation analysis
            if 'correlation' in scenario:
                lines.append("Correlation Analysis:")
                lines.append(f"  • Correlation Coefficient: {scenario['correlation']['coefficient']:.3f}")
                lines.append(f"  • R-squared: {scenario['correlation']['r_squared']:.3f}")
                
                # Interpret correlation
                corr = abs(scenario['correlation']['coefficient'])
                if corr < 0.3:
                    interpretation = "Weak correlation - traffic has minimal impact on RTT"
                elif corr < 0.7:
                    interpretation = "Moderate correlation - traffic has noticeable impact on RTT"
                else:
                    interpretation = "Strong correlation - traffic significantly affects RTT"
                lines.append(f"  • Interpretation: {interpretation}")
                lines.append("")
        
        lines.append("="*70)
        lines.append("END OF REPORT")
        lines.append("="*70)
        
        return "\n".join(lines)

    def cleanup(self):
        """پاکسازی منابع و بستن اتصالات"""
        logger.info("\n🧹 Cleaning up resources...")
        
        # Stop any running threads
        self.traffic_active.set()
        
        # Wait for threads to complete
        if self.traffic_thread and self.traffic_thread.is_alive():
            self.traffic_thread.join(timeout=2)
            
        if self.probe_thread and self.probe_thread.is_alive():
            self.probe_thread.join(timeout=2)
        
        # Cleanup components
        self.integrator.cleanup()
        
        logger.info("✅ Cleanup completed")

# ═══════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════

def parse_arguments():
    """پردازش آرگومان‌های خط فرمان"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='P900 Network Performance Tester - Integrated MAVLink Traffic & RTT Analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run baseline test only
  %(prog)s --master /dev/pts/6 --slave /dev/pts/8 --scenario baseline
  
  # Run all standard scenarios
  %(prog)s --master /dev/pts/6 --slave /dev/pts/8 --scenario all
  
  # Run specific traffic level
  %(prog)s --master /dev/pts/6 --slave /dev/pts/8 --scenario heavy
  
  # Custom output directory
  %(prog)s --master /dev/pts/6 --slave /dev/pts/8 --scenario all --output custom_results
        """
    )
    
    parser.add_argument(
        '--master', '-m',
        required=True,
        help='Master serial port path (e.g., /dev/pts/6)'
    )
    
    parser.add_argument(
        '--slave', '-s',
        required=True,
        help='Slave serial port path (e.g., /dev/pts/8)'
    )
    
    parser.add_argument(
        '--baudrate', '-b',
        type=int,
        default=57600,
        help='Serial baudrate (default: 57600)'
    )
    
    parser.add_argument(
        '--scenario',
        choices=['baseline', 'light', 'medium', 'heavy', 'all'],
        default='baseline',
        help='Test scenario to run (default: baseline)'
    )
    
    parser.add_argument(
        '--output', '-o',
        default='results',
        help='Output directory for results (default: results)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser.parse_args()

def main():
    """نقطه ورود اصلی برنامه"""
    args = parse_arguments()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Header
    print("\n" + "="*70)
    print("🚀 P900 NETWORK PERFORMANCE TESTER")
    print("   Integrated MAVLink Traffic & RTT Analysis")
    print("="*70)
    print(f"Master Port: {args.master}")
    print(f"Slave Port:  {args.slave}")
    print(f"Baudrate:    {args.baudrate}")
    print(f"Scenario:    {args.scenario}")
    print(f"Output Dir:  {args.output}")
    print("="*70 + "\n")
    
    # Create tester instance
    tester = IntegratedP900Tester(
        master_port=args.master,
        slave_port=args.slave,
        baudrate=args.baudrate
    )
    
    try:
        # Initialize system
        if not tester.initialize():
            logger.error("Failed to initialize system")
            return 1
        
        # Run scenarios
        if args.scenario == 'all':
            results = tester.run_all_scenarios()
        else:
            # Map string to enum
            scenario_map = {
                'baseline': TestScenario.BASELINE,
                'light': TestScenario.LIGHT_TRAFFIC,
                'medium': TestScenario.MEDIUM_TRAFFIC,
                'heavy': TestScenario.HEAVY_TRAFFIC
            }
            scenario = scenario_map[args.scenario]
            result = tester.run_scenario(scenario)
            results = [result] if result else []
        
        # Generate report
        if results:
            tester.generate_report(args.output)
            
            # Print summary
            print("\n" + "="*70)
            print("📊 TEST SUMMARY")
            print("="*70)
            
            for result in results:
                print(f"\n📌 {result.metadata.scenario}")
                if result.baseline_metrics:
                    print(f"   Baseline RTT: {result.baseline_metrics['rtt']['mean']:.2f} ms")
                if result.under_traffic_metrics:
                    print(f"   Traffic RTT:  {result.under_traffic_metrics['rtt']['mean']:.2f} ms")
                if result.correlation_analysis and 'relative_changes' in result.correlation_analysis:
                    changes = result.correlation_analysis['relative_changes']
                    print(f"   RTT Increase: {changes['rtt_increase_ms']:.2f} ms ({changes['rtt_increase_percent']:.1f}%)")
            
            print("\n" + "="*70)
            print("✅ All tests completed successfully!")
            print("="*70)
        else:
            logger.warning("No test results generated")
            
    except KeyboardInterrupt:
        logger.info("\n⚠️ Test interrupted by user")
        return 130
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}", exc_info=True)
        return 1
        
    finally:
        # Cleanup
        tester.cleanup()
        logger.info("👋 Goodbye!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
