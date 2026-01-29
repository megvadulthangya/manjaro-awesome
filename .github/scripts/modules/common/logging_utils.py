"""
Logging utilities
"""
import logging
import sys
from typing import Optional

def setup_logging(debug_mode: bool = False, log_file: str = 'builder.log') -> None:
    """
    Configure logging
    """
    log_level = logging.DEBUG if debug_mode else logging.INFO
    
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Formatters
    console_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO if debug_mode else logging.WARNING)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except (IOError, PermissionError):
        pass
    
    # Suppress noise
    logging.getLogger('paramiko').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('git').setLevel(logging.WARNING)

def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name)