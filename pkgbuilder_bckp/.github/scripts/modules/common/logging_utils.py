"""
Logging utilities for the package builder system
Handles logging configuration with support for debug mode
"""

import logging
import os
from typing import Optional


def setup_logging(debug_mode: bool = False, log_file: str = 'builder.log') -> None:
    """
    Configure logging for the application
    
    Args:
        debug_mode: If True, sets log level to DEBUG and adds more verbose output
        log_file: Path to log file
    """
    # Determine log level
    log_level = logging.DEBUG if debug_mode else logging.INFO
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplication
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create formatters
    console_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    
    file_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s - %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler
    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO if debug_mode else logging.WARNING)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    except (IOError, PermissionError) as e:
        # Log but don't fail if we can't create log file
        root_logger.warning(f"Could not create log file {log_file}: {e}")
    
    # Suppress overly verbose logs from dependencies
    logging.getLogger('paramiko').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('git').setLevel(logging.WARNING)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance
    
    Args:
        name: Logger name (usually __name__ of the calling module)
    
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)