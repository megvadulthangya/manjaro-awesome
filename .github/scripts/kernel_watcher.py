#!/usr/bin/env python3
"""
Kernel Watcher entry point - instantiates Seraph and runs watch()
"""

import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

try:
    from modules.common.config_loader import ConfigLoader
    from modules.seraph import Seraph
except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    sys.exit(1)


def main():
    try:
        repo_root = ConfigLoader.get_repo_root()
    except RuntimeError as e:
        logger.error(f"Cannot determine repo root: {e}")
        return 1

    seraph = Seraph(repo_root)
    return seraph.watch()


if __name__ == "__main__":
    sys.exit(main())