#!/usr/bin/env python3
"""
Packet Generator Module
تولیدکننده پکت‌ها با اندازه‌های متغیر برای تست RTT
"""

import struct
import random
from typing import List, Optional, Tuple, Dict, Any
from mavlink_profile import MAVLinkProfile
import logging

logger = logging.getLogger(__name__)


class PacketGenerator:
    """تولیدکننده پکت با قابلیت‌های مختلف"""
    
    # ساختار پروب پکت (برای RTT)
    PROBE_HEADER = struct.Struct('<BHI')  # Type(1), Size(2), ProbeID(4) = 7 bytes
    PROBE_TYPE = 0xAA  # شناسه پکت پروب
    
    # ساختار MAVLink (برای ترافیک عادی)
    MAVLINK_HEADER_V1 = struct.Struct('<BBBBBB')  # 6 bytes
    MAVLINK_STX_V1 = 0xFE
    
    def __init__(self, profile: Optional[MAVLinkProfile] = None):
        """
        Args:
            profile: پروفایل ترافیک MAVLink
        """
        self.profile = profile or MAVLinkProfile()
        self.sequence = 0
        self.probe_sequence = 0
        
        # کش برای اندازه‌های رایج
        self._size_cache = {}
        self._representative_sizes = None
        
        logger.info("PacketGenerator initialized with MAVLink profile")
    
    def generate_probe_packet(self, size: int, probe_id: int) -> bytes:
        """تولید پکت پروب برای تست RTT
        
        این پکت‌ها ساختار خاص خودشون دارند و MAVLink نیستند!
        ساختار: [Type(1)][Size(2)][ProbeID(4)][Payload(n)][Checksum(2)]
        
        Args:
            size: اندازه کل پکت مورد نظر
            probe_id: شناسه یکتای پروب
            
        Returns:
            پکت پروب با اندازه دقیق
        """
        # حداقل اندازه = header(7) + checksum(2) = 9
        if size < 9:
            size = 9
            logger.warning(f"Probe packet size adjusted to minimum: {size}")
        
        # محاسبه اندازه payload
        header_size = 7  # Type + Size + ProbeID
        checksum_size = 2
        payload_size = size - header_size - checksum_size
        
        if payload_size < 0:
            payload_size = 0
        
        # ساخت header پروب
        header = self.PROBE_HEADER.pack(
            self.PROBE_TYPE,  # نوع پکت
            size,              # اندازه کل
            probe_id           # شناسه پروب
        )
        
        # تولید payload (الگوی تست برای اعتبارسنجی)
        # استفاده از الگوی تکرارشونده برای تشخیص خرابی
        pattern = bytes([(i + probe_id) % 256 for i in range(payload_size)])
        
        # محاسبه checksum
        data = header + pattern
        checksum = struct.pack('<H', self._calculate_checksum(data))
        
        packet = data + checksum
        
        # اطمینان از اندازه دقیق
        if len(packet) != size:
            logger.error(f"Packet size mismatch: expected {size}, got {len(packet)}")
        
        return packet
    
    def generate_variable_probes(self, 
                               base_probe_id: int,
                               count: int = 10,
                               mode: str = 'representative') -> List[Tuple[int, int, bytes]]:
        """تولید مجموعه‌ای از پروب‌ها با اندازه‌های متغیر
        
        Args:
            base_probe_id: شناسه پایه (برای هر پروب increment می‌شود)
            count: تعداد پروب
            mode: نحوه انتخاب اندازه ('representative', 'realistic', 'random')
            
        Returns:
            لیست تاپل (probe_id, size, packet)
        """
        probes = []
        
        # دریافت اندازه‌ها از پروفایل
        if mode == 'representative':
            sizes = self.get_representative_sizes()
            # تکرار اندازه‌ها اگر count بیشتر از تعداد اندازه‌های نماینده است
            sizes = sizes * (count // len(sizes) + 1)
            sizes = sizes[:count]
        else:
            sizes = self.profile.get_packet_sizes(count, mode)
        
        for i, size in enumerate(sizes):
            probe_id = base_probe_id + i
            packet = self.generate_probe_packet(size, probe_id)
            probes.append((probe_id, size, packet))
            
        logger.info(f"Generated {count} probe packets in '{mode}' mode")
        return probes
    
    def generate_payload(self, size: int, pattern: str = 'random') -> bytes:
        """تولید payload با اندازه مشخص
        
        Args:
            size: اندازه payload
            pattern: نوع الگو ('random', 'zero', 'sequence', 'mavlink_like')
            
        Returns:
            payload با اندازه دقیق
        """
        if size <= 0:
            return b''
        
        if pattern == 'random':
            return bytes([random.randint(0, 255) for _ in range(size)])
        elif pattern == 'zero':
            return bytes(size)
        elif pattern == 'sequence':
            return bytes([i % 256 for i in range(size)])
        elif pattern == 'mavlink_like':
            # شبیه‌سازی داده MAVLink (ترکیبی از مقادیر)
            data = []
            for i in range(size):
                if i % 4 == 0:  # شبیه float
                    data.append(random.randint(0, 255))
                elif i % 2 == 0:  # شبیه int16
                    data.append(random.randint(0, 127))
                else:  # شبیه flags/enums
                    data.append(random.randint(0, 15))
            return bytes(data)
        else:
            return bytes([0x55] * size)  # الگوی 0x55 برای تست
    
    def generate_mavlink_traffic(self, size: int, msg_id: Optional[int] = None) -> bytes:
        """تولید پکت MAVLink برای شبیه‌سازی ترافیک
        
        این برای ایجاد ترافیک پس‌زمینه است، نه برای پروب!
        
        Args:
            size: اندازه پکت
            msg_id: شناسه پیام MAVLink
            
        Returns:
            پکت MAVLink
        """
        if size < 10:  # حداقل MAVLink
            size = 10
        
        payload_size = min(size - 8, 255)  # محدودیت MAVLink v1
        
        header = self.MAVLINK_HEADER_V1.pack(
            self.MAVLINK_STX_V1,
            payload_size,
            self.sequence % 256,
            1,  # System ID
            1,  # Component ID  
            msg_id or random.randint(0, 255)
        )
        
        payload = self.generate_payload(payload_size, 'mavlink_like')
        checksum = struct.pack('<H', self._calculate_checksum(header + payload))
        
        self.sequence += 1
        return header + payload + checksum
    
    def get_representative_sizes(self) -> List[int]:
        """دریافت اندازه‌های نماینده از پروفایل
        
        Returns:
            لیست اندازه‌های نماینده (کش می‌شود)
        """
        if self._representative_sizes is None:
            self._representative_sizes = self.profile.get_representative_sizes()
        return self._representative_sizes
    
    def get_size_for_probe(self, probe_number: int, mode: str = 'representative') -> int:
        """انتخاب اندازه برای یک پروب خاص
        
        Args:
            probe_number: شماره پروب
            mode: نحوه انتخاب اندازه
            
        Returns:
            اندازه انتخاب شده
        """
        if mode == 'representative':
            sizes = self.get_representative_sizes()
            return sizes[probe_number % len(sizes)]
        elif mode == 'realistic':
            return self.profile.get_packet_sizes(1, 'realistic')[0]
        elif mode == 'random':
            return random.randint(10, 280)  # محدوده MAVLink
        else:
            return 64  # پیش‌فرض
    
    def parse_probe_packet(self, packet: bytes) -> Optional[Dict[str, Any]]:
        """تجزیه پکت پروب دریافتی
        
        Args:
            packet: پکت دریافتی
            
        Returns:
            دیکشنری حاوی اطلاعات پروب یا None
        """
        if len(packet) < 9:
            return None
        
        try:
            # بررسی نوع پکت
            if packet[0] != self.PROBE_TYPE:
                return None
            
            # استخراج header
            pkt_type, size, probe_id = self.PROBE_HEADER.unpack(packet[:7])
            
            # بررسی checksum
            data = packet[:-2]
            received_checksum = struct.unpack('<H', packet[-2:])[0]
            calculated_checksum = self._calculate_checksum(data)
            
            if received_checksum != calculated_checksum:
                logger.warning(f"Checksum mismatch for probe {probe_id}")
                return None
            
            return {
                'type': pkt_type,
                'size': size,
                'probe_id': probe_id,
                'payload': packet[7:-2],
                'valid': True
            }
            
        except Exception as e:
            logger.error(f"Error parsing probe packet: {e}")
            return None
    
    def _calculate_checksum(self, data: bytes) -> int:
        """محاسبه checksum
        
        Args:
            data: داده برای checksum
            
        Returns:
            checksum 16-bit
        """
        # الگوریتم ساده checksum (می‌تواند پیچیده‌تر باشد)
        checksum = 0
        for byte in data:
            checksum = (checksum + byte) & 0xFFFF
            checksum = ((checksum & 0xFF) + (checksum >> 8)) & 0xFFFF
        return checksum
    
    def get_statistics(self) -> Dict[str, Any]:
        """آمار تولید پکت"""
        return {
            'probe_sequence': self.probe_sequence,
            'mavlink_sequence': self.sequence,
            'representative_sizes': self.get_representative_sizes(),
            'profile_loaded': self.profile is not None
        }


def create_generator(profile_path: Optional[str] = None) -> PacketGenerator:
    """ایجاد نمونه generator
    
    Args:
        profile_path: مسیر فایل پروفایل (اختیاری)
        
    Returns:
        نمونه PacketGenerator
    """
    profile = MAVLinkProfile(profile_path) if profile_path else MAVLinkProfile()
    return PacketGenerator(profile)


if __name__ == "__main__":
    import binascii
    
    # تست عملکرد
    print("="*60)
    print("Packet Generator Test")
    print("="*60)
    
    gen = create_generator()
    
    # 1. تست تولید پروب‌های متغیر
    print("\n1. Variable Probe Generation:")
    probes = gen.generate_variable_probes(1000, count=5, mode='representative')
    for probe_id, size, packet in probes:
        print(f"  Probe {probe_id}: Size={size}B, Actual={len(packet)}B, "
              f"Header={binascii.hexlify(packet[:7]).decode()}")
    
    # 2. تست parse پروب
    print("\n2. Probe Parsing Test:")
    test_probe = gen.generate_probe_packet(50, 9999)
    parsed = gen.parse_probe_packet(test_probe)
    if parsed:
        print(f"  Parsed: ID={parsed['probe_id']}, Size={parsed['size']}, Valid={parsed['valid']}")
    
    # 3. تست تولید ترافیک MAVLink
    print("\n3. MAVLink Traffic Generation:")
    for _ in range(3):
        size = random.choice(gen.get_representative_sizes())
        traffic = gen.generate_mavlink_traffic(size)
        print(f"  MAVLink packet: Size={len(traffic)}B, Header={binascii.hexlify(traffic[:6]).decode()}")
    
    # 4. آمار
    print("\n4. Statistics:")
    stats = gen.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
