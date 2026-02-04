"""
DEPRECATED: Package Builder Module - Split-brain guard

This file is no longer a pipeline orchestrator. Use .github/scripts/builder.py
as the only pipeline entrypoint. This module remains as a library/helper only.
"""

import os
import sys
import logging

logger = logging.getLogger(__name__)

class PackageBuilder:
    """
    DEPRECATED: This class is no longer a pipeline orchestrator.
    
    Use .github/scripts/builder.py as the only pipeline entrypoint.
    This class remains for backward compatibility as a helper module only.
    """
    
    def __init__(self):
        """Initialize with split-brain guard warning."""
        logger.warning("Split-brain guard: modules/orchestrator/package_builder.py is deprecated as orchestrator.")
        logger.warning("Use .github/scripts/builder.py as the only pipeline entrypoint.")
        raise RuntimeError(
            "Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.\n"
            "This module is now a library/helper only - cannot be instantiated as orchestrator."
        )
    
    def run(self, *args, **kwargs):
        """Block pipeline execution - use builder.py instead."""
        raise RuntimeError(
            "Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.\n"
            "This method is disabled to prevent split-brain orchestration."
        )
    
    def build_packages(self, *args, **kwargs):
        """Block pipeline execution - use builder.py instead."""
        raise RuntimeError(
            "Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.\n"
            "This method is disabled to prevent split-brain orchestration."
        )
    
    def upload_packages(self, *args, **kwargs):
        """Block pipeline execution - use builder.py instead."""
        raise RuntimeError(
            "Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.\n"
            "This method is disabled to prevent split-brain orchestration."
        )
    
    def phase_i_vps_sync(self, *args, **kwargs):
        """Block pipeline execution - use builder.py instead."""
        raise RuntimeError(
            "Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.\n"
            "This method is disabled to prevent split-brain orchestration."
        )
    
    def create_artifact_archive_for_github(self, *args, **kwargs):
        """Block pipeline execution - use builder.py instead."""
        raise RuntimeError(
            "Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.\n"
            "This method is disabled to prevent split-brain orchestration."
        )

# Guard against direct execution
if __name__ == "__main__":
    print("Split-brain guard: use .github/scripts/builder.py as the only pipeline entrypoint.", file=sys.stderr)
    sys.exit(1)
