#!/usr/bin/env python3
"""
MAVLink Traffic Profile Module
ماژول پروفایل ترافیک MAVLink - فقط برای تحلیل و مدیریت پروفایل
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np
import logging

logger = logging.getLogger(__name__)

@dataclass
class PacketProfile:
    """پروفایل یک نوع پیام MAVLink"""
    msg_type: str
    msg_id: int
    size: int
    frequency_hz: float
    weight: float
    description: str = ""


class MAVLinkProfile:
    """
    مدیریت پروفایل ترافیک MAVLink
    فقط مسئول: بارگذاری پروفایل، تحلیل آماری، و ارائه اطلاعات توزیع
    """
    
    def __init__(self, profile_path: Optional[str] = None):
        """
        Args:
            profile_path: مسیر فایل JSON پروفایل (اختیاری)
        """
        self.packet_profiles: List[PacketProfile] = []
        self.size_distribution: Dict = {}
        self.statistics: Dict = {}
        self.representative_sizes: List[int] = []
        
        if profile_path and Path(profile_path).exists():
            self.load_profile(profile_path)
        else:
            self._load_default_profile()
    
    def _load_default_profile(self):
        """بارگذاری پروفایل پیش‌فرض بر اساس تحلیل واقعی"""
        # توزیع اندازه بر اساس تحلیل واقعی
        self.size_distribution = {
            'tiny': {
                'probability': 0.2934,
                'min_bytes': 0,
                'max_bytes': 25,
                'representative': 13
            },
            'small': {
                'probability': 0.2088,
                'min_bytes': 25,
                'max_bytes': 40,
                'representative': 30
            },
            'medium': {
                'probability': 0.4063,
                'min_bytes': 40,
                'max_bytes': 50,
                'representative': 40
            },
            'large': {
                'probability': 0.0096,
                'min_bytes': 50,
                'max_bytes': 60,
                'representative': 55
            },
            'xlarge': {
                'probability': 0.0819,
                'min_bytes': 60,
                'max_bytes': 280,
                'representative': 82
            }
        }
        
        # پیام‌های رایج MAVLink
        self.packet_profiles = [
            PacketProfile("ATTITUDE", 30, 40, 5.74, 0.2837),
            PacketProfile("MISSION_CURRENT", 42, 13, 9.54, 0.206),
            PacketProfile("GLOBAL_POSITION_INT", 33, 40, 1.91, 0.0944),
            PacketProfile("VFR_HUD", 74, 31, 1.53, 0.0755),
            PacketProfile("HEARTBEAT", 0, 21, 1.0, 0.0494),
            PacketProfile("SYS_STATUS", 1, 44, 0.95, 0.0426),
            PacketProfile("GPS_RAW_INT", 24, 37, 0.88, 0.038),
            PacketProfile("NAV_CONTROLLER_OUTPUT", 62, 33, 0.67, 0.0243),
            PacketProfile("RC_CHANNELS", 65, 52, 0.52, 0.0189),
            PacketProfile("SERVO_OUTPUT_RAW", 36, 53, 0.45, 0.0163)
        ]
        
        # آمار کلی
        self.statistics = {
            'total_packets': 6067,
            'unique_message_types': 27,
            'min_size': 13,
            'max_size': 82,
            'mean_size': 34.69,
            'median_size': 40,
            'std_dev': 15.77
        }
        
        # اندازه‌های نماینده برای تست
        self.representative_sizes = [13, 21, 30, 31, 33, 37, 40, 44, 52, 82]
        
        logger.info("✅ Default MAVLink profile loaded")
    
    def load_profile(self, profile_path: str) -> bool:
        """بارگذاری پروفایل از فایل JSON
        
        Args:
            profile_path: مسیر فایل پروفایل
            
        Returns:
            موفقیت در بارگذاری
        """
        try:
            with open(profile_path, 'r') as f:
                data = json.load(f)
            
            # بارگذاری توزیع
            if 'size_distribution' in data:
                self.size_distribution = data['size_distribution']
            
            # بارگذاری پروفایل پیام‌ها
            if 'common_messages' in data:
                self.packet_profiles = []
                for msg_type, info in data['common_messages'].items():
                    profile = PacketProfile(
                        msg_type=msg_type,
                        msg_id=0,  # باید از جدول MAVLink بگیریم
                        size=int(info['size']),
                        frequency_hz=info['frequency_hz'],
                        weight=info.get('weight', 0.0)
                    )
                    self.packet_profiles.append(profile)
            
            # بارگذاری آمار
            if 'statistics' in data:
                self.statistics = data['statistics']
            
            # تولید اندازه‌های نماینده
            self._generate_representative_sizes()
            
            logger.info(f"✅ Profile loaded from {profile_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load profile: {e}")
            return False
    
    def _generate_representative_sizes(self):
        """تولید اندازه‌های نماینده بر اساس پروفایل"""
        sizes = set()
        
        # از پروفایل پیام‌ها
        for profile in self.packet_profiles[:10]:
            sizes.add(profile.size)
        
        # از توزیع
        for category in self.size_distribution.values():
            if 'representative' in category:
                sizes.add(category['representative'])
        
        self.representative_sizes = sorted(list(sizes))[:10]
        
        # اگر کمتر از 10 تا داریم، اضافه کنیم
        while len(self.representative_sizes) < 10:
            new_size = random.randint(
                self.statistics.get('min_size', 13),
                self.statistics.get('max_size', 82)
            )
            if new_size not in self.representative_sizes:
                self.representative_sizes.append(new_size)
        
        self.representative_sizes.sort()
    
    def get_packet_sizes(self, count: int = 10, mode: str = 'realistic') -> List[int]:
        """دریافت لیست اندازه پکت‌ها بر اساس حالت انتخاب شده
        
        Args:
            count: تعداد اندازه‌ها
            mode: حالت انتخاب ('realistic', 'representative', 'random')
            
        Returns:
            لیست اندازه‌ها به بایت
        """
        sizes = []
        
        if mode == 'representative':
            # انتخاب از اندازه‌های نماینده
            for _ in range(count):
                sizes.append(random.choice(self.representative_sizes))
                
        elif mode == 'random':
            # تولید تصادفی در محدوده
            min_size = self.statistics.get('min_size', 13)
            max_size = self.statistics.get('max_size', 82)
            for _ in range(count):
                sizes.append(random.randint(min_size, max_size))
                
        else:  # realistic
            # 70% از پیام‌های رایج، 30% از توزیع کلی
            for _ in range(count):
                if random.random() < 0.7 and self.packet_profiles:
                    # انتخاب وزن‌دار از پیام‌های رایج
                    weights = [p.weight for p in self.packet_profiles]
                    profile = random.choices(self.packet_profiles, weights=weights)[0]
                    sizes.append(profile.size)
                else:
                    # انتخاب بر اساس توزیع کلی
                    size = self._sample_from_distribution()
                    sizes.append(size)
        
        return sizes
    
    def _sample_from_distribution(self) -> int:
        """نمونه‌برداری از توزیع اندازه"""
        # انتخاب دسته بر اساس احتمال
        r = random.random()
        cumulative = 0.0
        
        for category, info in self.size_distribution.items():
            cumulative += info['probability']
            if r < cumulative:
                # انتخاب تصادفی در این دسته
                return random.randint(
                    info['min_bytes'],
                    min(info['max_bytes'], 82)  # محدودیت حداکثر
                )
        
        # پیش‌فرض
        return random.choice(self.representative_sizes)
    
    def get_representative_sizes(self) -> List[int]:
        """دریافت اندازه‌های نماینده"""
        return self.representative_sizes.copy()
    
    def analyze_rtt_by_size(self, measurements: List[Dict]) -> Dict:
        """تحلیل RTT بر اساس اندازه پکت
        
        Args:
            measurements: لیست اندازه‌گیری‌ها با فیلدهای packet_size و rtt
            
        Returns:
            دیکشنری آنالیز برای هر اندازه
        """
        # گروه‌بندی بر اساس اندازه
        size_groups = {}
        for m in measurements:
            size = m.get('packet_size', 0)
            rtt = m.get('rtt', 0)
            
            if size not in size_groups:
                size_groups[size] = []
            size_groups[size].append(rtt)
        
        # محاسبه آمار برای هر گروه
        analysis = {}
        for size, rtts in size_groups.items():
            if rtts:
                analysis[size] = {
                    'count': len(rtts),
                    'mean': np.mean(rtts),
                    'median': np.median(rtts),
                    'std': np.std(rtts),
                    'min': np.min(rtts),
                    'max': np.max(rtts),
                    'p95': np.percentile(rtts, 95)
                }
        
        # آمار کلی
        all_rtts = [r for rtts in size_groups.values() for r in rtts]
        if all_rtts:
            analysis['overall'] = {
                'count': len(all_rtts),
                'mean': np.mean(all_rtts),
                'median': np.median(all_rtts),
                'std': np.std(all_rtts)
            }
        
        return analysis
    
    def get_bandwidth_estimate(self) -> float:
        """محاسبه تخمین پهنای باند بر اساس پروفایل
        
        Returns:
            پهنای باند به بایت بر ثانیه
        """
        total_bandwidth = 0.0
        
        for profile in self.packet_profiles:
            if profile.frequency_hz > 0:
                bandwidth = profile.size * profile.frequency_hz
                total_bandwidth += bandwidth
        
        return round(total_bandwidth, 2)
    
    def get_message_frequency(self, msg_type: str) -> float:
        """دریافت فرکانس یک نوع پیام
        
        Args:
            msg_type: نوع پیام
            
        Returns:
            فرکانس به هرتز
        """
        for profile in self.packet_profiles:
            if profile.msg_type == msg_type:
                return profile.frequency_hz
        return 0.0
    
    def validate_profile(self) -> Dict[str, bool]:
        """اعتبارسنجی پروفایل
        
        Returns:
            دیکشنری نتایج اعتبارسنجی
        """
        validation = {
            'has_profiles': len(self.packet_profiles) > 0,
            'has_distribution': len(self.size_distribution) > 0,
            'has_representatives': len(self.representative_sizes) == 10,
            'has_statistics': all(k in self.statistics for k in ['min_size', 'max_size', 'mean_size']),
            'bandwidth_reasonable': 100 < self.get_bandwidth_estimate() < 100000,
            'sizes_in_range': all(13 <= s <= 280 for s in self.representative_sizes),
            'distribution_valid': abs(sum(d['probability'] for d in self.size_distribution.values()) - 1.0) < 0.01
        }
        
        validation['all_valid'] = all(validation.values())
        return validation
    
    def get_summary(self) -> str:
        """خلاصه پروفایل به صورت متنی"""
        lines = []
        lines.append("=" * 50)
        lines.append("MAVLink Traffic Profile Summary")
        lines.append("=" * 50)
        
        # آمار کلی
        lines.append(f"\n📊 Statistics:")
        lines.append(f"  Total packets analyzed: {self.statistics.get('total_packets', 'N/A')}")
        lines.append(f"  Unique message types: {self.statistics.get('unique_message_types', 'N/A')}")
        lines.append(f"  Size range: {self.statistics.get('min_size', 'N/A')}-{self.statistics.get('max_size', 'N/A')} bytes")
        lines.append(f"  Mean size: {self.statistics.get('mean_size', 'N/A'):.2f} bytes")
        lines.append(f"  Estimated bandwidth: {self.get_bandwidth_estimate():.2f} bytes/sec")
        
        # توزیع اندازه
        lines.append(f"\n📈 Size Distribution:")
        for category,info in self.size_distribution.items():
            lines.append(f"  {category}: {info['probability']*100:.1f}% "
                         f"({info['min_bytes']}-{info['max_bytes']} bytes)")

        # پیام‌های رایج
        lines.append("\n📌 Common messages:")
        for profile in sorted(self.packet_profiles, key=lambda p: p.frequency_hz, reverse=True)[:5]:
            lines.append(f"  {profile.msg_type}: {profile.size} bytes, {profile.frequency_hz:.2f} Hz")

        # اندازه‌های نماینده
        lines.append(f"\nRepresentative sizes: {self.representative_sizes}")

        return "\n".join(lines)


def create_default_profile() -> MAVLinkProfile:
    """ایجاد یک نمونه پیش‌فرض پروفایل"""
    return MAVLinkProfile()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    profile = create_default_profile()
    print(profile.get_summary())
    print("\nValidation:", profile.validate_profile())
    print("\nSample realistic sizes:", profile.get_packet_sizes(10, 'realistic'))
