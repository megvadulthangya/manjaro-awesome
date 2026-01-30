"""
Logging Utilities Module - Configures and manages logging
"""

import logging


def setup_logging():
    """Configure logging for the application"""
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('builder.log')
        ]
    )
    
    return logging.getLogger(__name__)