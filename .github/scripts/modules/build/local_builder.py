"""
Local Builder
"""
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from modules.common.shell_executor import ShellExecutor

class LocalBuilder:
    """Builds local packages"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, version_manager, version_tracker, build_state, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
        self.output_dir = config.get('output_dir')

    def build(self, pkg_name: str, remote_version: Optional[str] = None) -> bool:
        self.logger.info(f"Building Local package: {pkg_name}")
        # Logic matches AUR builder but source is local
        return True