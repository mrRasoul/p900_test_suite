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
            master_port: پورت محلی (Master)
            slave_port: پورت دور (Slave) 
            baudrate: سرعت سریال
        """
        self.master_port = master_port
        self.slave_port = slave_port
        self.baudrate = baudrate
        
        # کامپوننت‌ها
        self.traffic_simulator: Optional[TrafficSimulator] = None
        self.probe_injector: Optional[ProbeInjector] = None
        self.mavlink_profile: Optional[MAVLinkProfile] = None
        
        # Serial connections
        self.master_port: Optional[serial.Serial] = None
        self.slave_port: Optional[serial.Serial] = None
        
        # Component status
        self.components_ready = False
        self.serial_lock = threading.Lock()  # اضافه کنید
        
    def initialize_serial_ports(self) -> bool:
        """راه‌اندازی پورت‌های سریال"""
        try:
            # Master port
            self.master_port = serial.Serial(
                port=self.master_port,
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=1.0
            )
            logger.info(f"✅ Master serial port opened: {self.master_port}")
            
            # Slave port  
            self.slave_port = serial.Serial(
                port=self.slave_port,
                baudrate=self.baudrate,
                timeout=0.1,
                write_timeout=1.0
            )
            logger.info(f"✅ Slave serial port opened: {self.slave_port}")
            
            # Clear buffers
            self.master_port.reset_input_buffer()
            self.master_port.reset_output_buffer()
            self.slave_port.reset_input_buffer()
            self.slave_port.reset_output_buffer()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize serial ports: {e}")
            return False
    
    def create_traffic_simulator(self, target_bandwidth: float) -> TrafficSimulator:
        """ایجاد شبیه‌ساز ترافیک"""
        if not self.master_port:
            raise RuntimeError("Serial ports not initialized")
            
        self.traffic_simulator = TrafficSimulator(
            serial_port=self.master_port,
            target_bandwidth=target_bandwidth,
            write_lock=self.serial_lock 
        )
        logger.info(f"✅ Traffic simulator created (target: {target_bandwidth} bps)")
        return self.traffic_simulator
    
    def create_probe_injector(self) -> ProbeInjector:
        """ایجاد تزریق‌کننده probe"""
        if not self.master_port or not self.slave_port:
            raise RuntimeError("Serial ports not initialized")
            
        self.probe_injector = ProbeInjector(
            master_port=self.master_port,
            slave_port=self.slave_port
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
        if self.master_port and self.master_port.is_open:
            self.master_port.close()
            logger.info("Master serial port closed")
            
        if self.slave_port and self.slave_port.is_open:
            self.slave_port.close()
            logger.info("Slave serial port closed")

# ═══════════════════════════════════════════════════════════════════
# Test Orchestrator - هماهنگ‌کننده اصلی تست
# ═══════════════════════════════════════════════════════════════════

class IntegratedP900Tester:
    """تستر یکپارچه P900 - ترکیب ترافیک و اندازه‌گیری RTT"""
    
    def __init__(self, master_port: str, slave_port: str, baudrate: int = 57600):
        """
        Args:
            master_port: پورت Master (محلی)
            slave_port: پورت Slave (دور)
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
        self.integrator.load_mavlink_profile()
        
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
    
# ادامه کد p900_new_tester.py - بخش دوم
# این کد را به انتهای فایل موجود اضافه کنید

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
                       f"{final_traffic_stats.get('actual_bandwidth', 0):.0f}bps load")
            
            return combined_metrics
            
        except Exception as e:
            logger.error(f"❌ Error in combined measurement: {e}")
            raise
    
    def _run_traffic_generator(self, traffic_sim: TrafficSimulator, duration: float):
        """اجرای traffic generator در thread جداگانه"""
        try:
            logger.debug("Traffic generator thread started")
            
            # استفاده از متد public و استاندارد
            start_time = time.perf_counter()
            
            # اگر TrafficSimulator متد start دارد
            if hasattr(traffic_sim, 'start'):
                # اجرا در حالت non-blocking
                traffic_sim.running = True
                
                while not self.traffic_active.is_set():
                    if time.perf_counter() - start_time > duration:
                        break
                        
                    # بررسی وضعیت هر 100ms
                    time.sleep(0.1)
                
                traffic_sim.running = False
            else:
                # fallback: ارسال دستی پکت‌ها
                while not self.traffic_active.is_set():
                    if time.perf_counter() - start_time > duration:
                        break
                    
                    # تولید و ارسال پکت
                    packet = traffic_sim.packet_generator.generate_mavlink_traffic(100)
                    traffic_sim.serial_port.write(packet)
                    traffic_sim.stats['packets_sent'] += 1
                    traffic_sim.stats['bytes_sent'] += len(packet)
                    
                    # رعایت bandwidth
                    time.sleep(1.0 / traffic_sim.packets_per_second)
                    
        except Exception as e:
            logger.error(f"Error in traffic generator: {e}")

        
    def _analyze_correlation(self) -> Dict:
        """تحلیل همبستگی بین ترافیک و RTT"""
        logger.info("  📈 Analyzing correlation...")
        
        if not self.current_test or not self.current_test.raw_measurements:
            logger.warning("No data available for correlation analysis")
            return {}
        
        try:
            # استخراج داده‌ها از اندازه‌گیری‌های دوره‌ای
            timestamps = []
            rtt_values = []
            bandwidth_values = []
            loss_rates = []
            
            for measurement in self.current_test.raw_measurements:
                timestamps.append(measurement['timestamp'])
                rtt_values.append(measurement['probe_stats']['rtt_ms'])
                bandwidth_values.append(measurement['traffic_stats']['actual_bandwidth'])
                loss_rates.append(measurement['probe_stats']['loss_rate'])
            
            # تبدیل به numpy arrays
            rtt_array = np.array(rtt_values)
            bandwidth_array = np.array(bandwidth_values)
            loss_array = np.array(loss_rates)
            
            # محاسبه همبستگی
            if len(rtt_array) > 1 and len(bandwidth_array) > 1:
                # Correlation between bandwidth and RTT
                rtt_bandwidth_corr = np.corrcoef(bandwidth_array, rtt_array)[0, 1]
                
                # Correlation between bandwidth and loss
                loss_bandwidth_corr = np.corrcoef(bandwidth_array, loss_array)[0, 1] if np.std(loss_array) > 0 else 0
                
                # محاسبه degradation factor
                if self.current_test.baseline_metrics and self.current_test.under_traffic_metrics:
                    baseline_rtt = self.current_test.baseline_metrics['rtt']['mean']
                    traffic_rtt = self.current_test.under_traffic_metrics['rtt']['mean']
                    degradation_factor = traffic_rtt / baseline_rtt if baseline_rtt > 0 else 0
                else:
                    degradation_factor = 0
                
                # یافتن آستانه بحرانی (نقطه‌ای که RTT به شدت افزایش می‌یابد)
                # برای ساده‌سازی: پهنای باندی که RTT بیش از 2x baseline شود
                critical_threshold = None
                if degradation_factor > 2:
                    # پیدا کردن اولین نقطه که RTT > 2x baseline
                    baseline_rtt = self.current_test.baseline_metrics['rtt']['mean']
                    for i, rtt in enumerate(rtt_values):
                        if rtt > 2 * baseline_rtt:
                            critical_threshold = bandwidth_values[i]
                            break
                
                correlation_analysis = {
                    'rtt_traffic_correlation': float(rtt_bandwidth_corr) if not np.isnan(rtt_bandwidth_corr) else 0,
                    'loss_traffic_correlation': float(loss_bandwidth_corr) if not np.isnan(loss_bandwidth_corr) else 0,
                    'degradation_factor': degradation_factor,
                    'critical_bandwidth_threshold': critical_threshold,
                    'analysis_summary': {
                        'correlation_strength': self._interpret_correlation(rtt_bandwidth_corr),
                        'impact_level': self._interpret_degradation(degradation_factor)
                    }
                }
                
            else:
                correlation_analysis = {
                    'error': 'Insufficient data for correlation analysis'
                }
            
            logger.info(f"  ✅ Correlation analysis complete")
            return correlation_analysis
            
        except Exception as e:
            logger.error(f"Error in correlation analysis: {e}")
            return {'error': str(e)}

    def _interpret_correlation(self, correlation: float) -> str:
        """تفسیر مقدار همبستگی"""
        if np.isnan(correlation):
            return "No correlation"
        
        abs_corr = abs(correlation)
        if abs_corr < 0.3:
            return "Weak"
        elif abs_corr < 0.7:
            return "Moderate"
        else:
            return "Strong"
    
    def _interpret_degradation(self, factor: float) -> str:
        """تفسیر میزان افت کیفیت"""
        if factor < 1.5:
            return "Minimal impact"
        elif factor < 2.0:
            return "Moderate impact"
        elif factor < 3.0:
            return "Significant impact"
        else:
            return "Severe impact"
    
# ادامه فایل p900_new_tester.py از خط 370

    def save_results(self, output_dir: str = "results"):
        """ذخیره نتایج تست‌ها"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        for test_result in self.test_results:
            # نام فایل بر اساس test_id
            filename = f"{test_result.metadata.test_id}_results.json"
            filepath = output_path / filename
            
            # تبدیل به dictionary برای ذخیره
            result_dict = {
                'metadata': asdict(test_result.metadata),
                'baseline_metrics': test_result.baseline_metrics,
                'traffic_metrics': test_result.traffic_metrics,
                'under_traffic_metrics': test_result.under_traffic_metrics,
                'correlation_analysis': test_result.correlation_analysis,
                'raw_measurements': test_result.raw_measurements[:10] if test_result.raw_measurements else []  # فقط 10 نمونه اول برای کاهش حجم
            }
            
            # ذخیره به JSON
            with open(filepath, 'w') as f:
                json.dump(result_dict, f, indent=2, default=str)
            
            logger.info(f"📁 Results saved to: {filepath}")
            
            # ایجاد فایل خلاصه متنی
            summary_file = output_path / f"{test_result.metadata.test_id}_summary.txt"
            self._create_summary_report(test_result, summary_file)
    
    def _create_summary_report(self, result: CombinedResults, filepath: Path):
        """ایجاد گزارش خلاصه متنی"""
        with open(filepath, 'w') as f:
            f.write("="*70 + "\n")
            f.write(" P900 INTEGRATED TEST REPORT\n")
            f.write("="*70 + "\n\n")
            
            # Metadata
            f.write(f"Test ID: {result.metadata.test_id}\n")
            f.write(f"Scenario: {result.metadata.scenario}\n")
            f.write(f"Timestamp: {result.metadata.timestamp}\n")
            f.write(f"Duration: {result.metadata.total_duration:.2f} seconds\n")
            f.write(f"Serial Ports: {result.metadata.serial_ports['master']} <-> {result.metadata.serial_ports['slave']}\n")
            f.write(f"Baudrate: {result.metadata.baudrate}\n")
            f.write("\n")
            
            # Baseline Results
            if result.baseline_metrics:
                f.write("-"*70 + "\n")
                f.write("BASELINE MEASUREMENTS (No Traffic)\n")
                f.write("-"*70 + "\n")
                f.write(f"Probes Sent: {result.baseline_metrics['probe_count']}\n")
                f.write(f"Successful: {result.baseline_metrics['successful_probes']}\n")
                f.write(f"Loss Rate: {result.baseline_metrics['loss_rate']:.2f}%\n")
                f.write(f"RTT Mean: {result.baseline_metrics['rtt']['mean']:.3f} ms\n")
                f.write(f"RTT Min/Max: {result.baseline_metrics['rtt']['min']:.3f} / {result.baseline_metrics['rtt']['max']:.3f} ms\n")
                f.write(f"RTT Std Dev: {result.baseline_metrics['rtt']['std']:.3f} ms\n")
                f.write(f"RTT 95th %ile: {result.baseline_metrics['rtt']['p95']:.3f} ms\n")
                f.write(f"Jitter Mean: {result.baseline_metrics['jitter']['mean']:.3f} ms\n")
                f.write("\n")
            
            # Traffic Results
            if result.traffic_metrics:
                f.write("-"*70 + "\n")
                f.write("TRAFFIC GENERATION\n")
                f.write("-"*70 + "\n")
                f.write(f"Target Bandwidth: {result.traffic_metrics['target_bandwidth']:.0f} bps\n")
                f.write(f"Actual Bandwidth: {result.traffic_metrics['actual_bandwidth']:.0f} bps\n")
                f.write(f"Accuracy: {(result.traffic_metrics['actual_bandwidth']/result.traffic_metrics['target_bandwidth']*100):.1f}%\n")
                f.write(f"Total Packets: {result.traffic_metrics['total_packets']}\n")
                f.write(f"Total Bytes: {result.traffic_metrics['total_bytes']}\n")
                f.write(f"Errors: {result.traffic_metrics['errors']}\n")
                f.write("\n")
            
            # Under Traffic Results
            if result.under_traffic_metrics:
                f.write("-"*70 + "\n")
                f.write("RTT MEASUREMENTS UNDER TRAFFIC\n")
                f.write("-"*70 + "\n")
                f.write(f"Probes Sent: {result.under_traffic_metrics['probe_count']}\n")
                f.write(f"Successful: {result.under_traffic_metrics['successful_probes']}\n")
                f.write(f"Loss Rate: {result.under_traffic_metrics['loss_rate']:.2f}%\n")
                f.write(f"RTT Mean: {result.under_traffic_metrics['rtt']['mean']:.3f} ms\n")
                f.write(f"RTT Min/Max: {result.under_traffic_metrics['rtt']['min']:.3f} / {result.under_traffic_metrics['rtt']['max']:.3f} ms\n")
                f.write(f"RTT Std Dev: {result.under_traffic_metrics['rtt']['std']:.3f} ms\n")
                f.write(f"RTT 95th %ile: {result.under_traffic_metrics['rtt']['p95']:.3f} ms\n")
                f.write(f"Jitter Mean: {result.under_traffic_metrics['jitter']['mean']:.3f} ms\n")
                f.write("\n")
            
            # Correlation Analysis
            if result.correlation_analysis:
                f.write("-"*70 + "\n")
                f.write("CORRELATION ANALYSIS\n")
                f.write("-"*70 + "\n")
                
                if 'error' not in result.correlation_analysis:
                    f.write(f"RTT-Traffic Correlation: {result.correlation_analysis.get('rtt_traffic_correlation', 0):.3f}\n")
                    f.write(f"Loss-Traffic Correlation: {result.correlation_analysis.get('loss_traffic_correlation', 0):.3f}\n")
                    f.write(f"Performance Degradation Factor: {result.correlation_analysis.get('degradation_factor', 0):.2f}x\n")
                    
                    if result.correlation_analysis.get('critical_bandwidth_threshold'):
                        f.write(f"Critical Bandwidth Threshold: {result.correlation_analysis['critical_bandwidth_threshold']:.0f} bps\n")
                    
                    if 'analysis_summary' in result.correlation_analysis:
                        summary = result.correlation_analysis['analysis_summary']
                        f.write(f"Correlation Strength: {summary.get('correlation_strength', 'Unknown')}\n")
                        f.write(f"Impact Level: {summary.get('impact_level', 'Unknown')}\n")
                else:
                    f.write(f"Error: {result.correlation_analysis['error']}\n")
                f.write("\n")
            
            # Comparison Summary
            if result.baseline_metrics and result.under_traffic_metrics:
                f.write("="*70 + "\n")
                f.write("IMPACT SUMMARY\n")
                f.write("="*70 + "\n")
                
                baseline_rtt = result.baseline_metrics['rtt']['mean']
                traffic_rtt = result.under_traffic_metrics['rtt']['mean']
                rtt_increase = traffic_rtt - baseline_rtt
                rtt_increase_percent = (rtt_increase / baseline_rtt * 100) if baseline_rtt > 0 else 0
                
                baseline_loss = result.baseline_metrics['loss_rate']
                traffic_loss = result.under_traffic_metrics['loss_rate']
                loss_increase = traffic_loss - baseline_loss
                
                f.write(f"RTT Increase: {rtt_increase:.3f} ms ({rtt_increase_percent:+.1f}%)\n")
                f.write(f"Loss Rate Change: {loss_increase:+.2f}%\n")
                
                # تفسیر نتایج
                f.write("\nInterpretation:\n")
                if rtt_increase_percent < 20:
                    f.write("✅ Minimal impact on latency - Network handling traffic well\n")
                elif rtt_increase_percent < 50:
                    f.write("⚠️ Moderate impact on latency - Some congestion occurring\n")
                elif rtt_increase_percent < 100:
                    f.write("⚠️ Significant impact on latency - Notable congestion\n")
                else:
                    f.write("❌ Severe impact on latency - Heavy congestion detected\n")
                
                if loss_increase < 1:
                    f.write("✅ No significant packet loss increase\n")
                elif loss_increase < 5:
                    f.write("⚠️ Minor packet loss increase\n")
                else:
                    f.write("❌ Significant packet loss under load\n")
            
            f.write("\n" + "="*70 + "\n")
            f.write("END OF REPORT\n")
            f.write("="*70 + "\n")
        
        logger.info(f"📄 Summary report saved to: {filepath}")
    
    def run_all_scenarios(self):
        """اجرای تمام سناریوهای استاندارد"""
        scenarios = [
            TestScenario.BASELINE,
            TestScenario.LIGHT_TRAFFIC,
            TestScenario.MEDIUM_TRAFFIC,
            TestScenario.HEAVY_TRAFFIC
        ]
        
        logger.info("\n" + "="*60)
        logger.info("🚀 Running ALL Standard Scenarios")
        logger.info("="*60)
        
        for scenario in scenarios:
            try:
                logger.info(f"\n{'='*60}")
                logger.info(f"📋 Scenario: {scenario.value}")
                logger.info(f"{'='*60}")
                
                result = self.run_scenario(scenario)
                
                # اضافه کردن delay بین سناریوها
                if scenario != scenarios[-1]:
                    logger.info("\n⏳ Waiting 5 seconds before next scenario...")
                    time.sleep(5)
                    
            except Exception as e:
                logger.error(f"Failed to run scenario {scenario.value}: {e}")
                continue
        
        # ذخیره نتایج نهایی
        self.save_results()
        
        logger.info("\n" + "="*60)
        logger.info("✅ All scenarios completed!")
        logger.info(f"📊 Total tests run: {len(self.test_results)}")
        logger.info("="*60)
    
    def cleanup(self):
        """پاکسازی منابع"""
        logger.info("Cleaning up resources...")
        
        # توقف thread ها در صورت فعال بودن
        self.traffic_active.set()
        
        # بستن پورت‌های سریال
        self.integrator.cleanup()
        
        logger.info("Cleanup completed")

# ═══════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════

def main():
    """نقطه ورود اصلی برنامه"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='P900 Integrated Network Performance Tester'
    )
    parser.add_argument('--master', '-m', 
                       default='/dev/pts/6',
                       help='Master serial port')
    parser.add_argument('--slave', '-s',
                       default='/dev/pts/8', 
                       help='Slave serial port')
    parser.add_argument('--baudrate', '-b',
                       type=int, default=57600,
                       help='Serial baudrate')
    parser.add_argument('--scenario',
                       choices=['baseline', 'light', 'medium', 'heavy', 'all'],
                       default='all',
                       help='Test scenario to run')
    parser.add_argument('--output', '-o',
                       default='results',
                       help='Output directory for results')
    
    args = parser.parse_args()
    
    # ایجاد تستر
    tester = IntegratedP900Tester(
        master_port=args.master,
        slave_port=args.slave,
        baudrate=args.baudrate
    )
    
    try:
        # راه‌اندازی سیستم
        if not tester.initialize():
            logger.error("Failed to initialize system")
            return 1
        
# ادامه فایل p900_new_tester.py از خط 560
# این کد را به انتهای فایل اضافه کنید

        # اجرای سناریو(ها)
        if args.scenario == 'all':
            tester.run_all_scenarios()
        else:
            # اجرای یک سناریو خاص
            scenario_map = {
                'baseline': TestScenario.BASELINE,
                'light': TestScenario.LIGHT_TRAFFIC,
                'medium': TestScenario.MEDIUM_TRAFFIC,
                'heavy': TestScenario.HEAVY_TRAFFIC
            }
            
            scenario = scenario_map.get(args.scenario)
            if scenario:
                result = tester.run_scenario(scenario)
                tester.save_results(args.output)
            else:
                logger.error(f"Unknown scenario: {args.scenario}")
                return 1
        
        logger.info("\n" + "="*60)
        logger.info("✅ Test execution completed successfully!")
        logger.info("="*60)
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️ Test interrupted by user")
        
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        # پاکسازی نهایی
        tester.cleanup()
        logger.info("👋 Goodbye!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
