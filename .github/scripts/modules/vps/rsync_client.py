"""
Rsync client for file transfers
"""

import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class RsyncClient:
    """Handles file transfers using rsync"""
    
    def __init__(self, config):
        self.config = config
        self.debug_mode = config.get('debug_mode', False)
    
    def upload_packages(self, source_dir):
        """Upload packages to VPS"""
        if self.debug_mode:
            print(f"🔧 [DEBUG] Uploading packages from {source_dir}", flush=True)
        else:
            logger.info(f"Uploading packages from {source_dir}")
        
        # Build rsync command
        vps_user = self.config['vps_user']
        vps_host = self.config['vps_host']
        remote_dir = self.config['remote_dir']
        
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          {source_dir}/*.pkg.tar.* \
          {source_dir}/{self.config['repo_name']}.* \
          '{vps_user}@{vps_host}:{remote_dir}/'
        """
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Running rsync command: {rsync_cmd}", flush=True)
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Rsync upload successful", flush=True)
                else:
                    logger.info("✅ Rsync upload successful")
                return True
            else:
                if self.debug_mode:
                    print(f"❌ [DEBUG] Rsync upload failed: {result.stderr}", flush=True)
                else:
                    logger.error(f"Rsync upload failed: {result.stderr}")
                return False
                
        except Exception as e:
            if self.debug_mode:
                print(f"❌ [DEBUG] Rsync execution error: {e}", flush=True)
            else:
                logger.error(f"Rsync execution error: {e}")
            return False