"""
Logging utilities for the package builder
"""

import logging
import sys

def setup_logging(debug_mode=False):
    """Setup logging configuration"""
    level = logging.DEBUG if debug_mode else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('builder.log')
        ]
    )
    
    return logging.getLogger(__name__)

class DebugLogger:
    """Debug logger that bypasses standard logger in debug mode"""
    
    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
    
    def log(self, message):
        """Log message, bypassing logger in debug mode"""
        if self.debug_mode:
            print(f"🔧 [DEBUG] {message}", flush=True)
        else:
            logging.info(message)
    
    def error(self, message):
        """Log error message"""
        if self.debug_mode:
            print(f"❌ [DEBUG] {message}", flush=True)
        else:
            logging.error(message)
    
    def warning(self, message):
        """Log warning message"""
        if self.debug_mode:
            print(f"⚠️ [DEBUG] {message}", flush=True)
        else:
            logging.warning(message)