import re
import time
import asyncio
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ScaleSettings:
    enabled: bool = True
    connection_type: str = 'usb'
    baud_rate: int = 9600
    stable_reads_required: int = 2
    stable_tolerance: float = 0.02
    read_timeout_ms: int = 3000
    request_command: str = ''

class ScaleServiceLogic:
    def __init__(self, settings: ScaleSettings = ScaleSettings()):
        self.settings = settings
        self._previous_weight: Optional[float] = None
        self._stable_hits: int = 0

    def extract_weight(self, raw_line: str) -> Optional[float]:
        """Matches the Dart regex: r'[-+]?\\d+(\\.\\d+)?'"""
        cleaned = raw_line.strip().replace(',', '.')
        if not cleaned: return None
        
        match = re.search(r'[-+]?\d+(\.\d+)?', cleaned)
        if not match: return None
        
        try:
            return float(match.group(0))
        except ValueError:
            return None

    def check_stability(self, current_weight: float) -> bool:
        """Implements the Dart stability logic: 
        (parsed - previous!).abs() <= config.stableTolerance
        """
        if self._previous_weight is None:
            self._previous_weight = current_weight
            self._stable_hits = 1
        elif abs(current_weight - self._previous_weight) <= self.settings.stable_tolerance:
            self._previous_weight = current_weight
            self._stable_hits += 1
        else:
            self._previous_weight = current_weight
            self._stable_hits = 1

        if self._stable_hits >= self.settings.stable_reads_required:
            return True
        return False

    def reset_stability(self):
        self._previous_weight = None
        self._stable_hits = 0

    def decode_escapes(self, input_str: str) -> bytes:
        """Matches the Dart escape decoding for \r and \n"""
        return input_str.encode('ascii').decode('unicode_escape').encode('ascii')

# Example usage for integration:
# logic = ScaleServiceLogic()
# if logic.check_stability(parsed_weight):
#     print("STABLE!")
