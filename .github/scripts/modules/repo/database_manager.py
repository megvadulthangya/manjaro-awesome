"""
Database manager for repository database operations
"""

import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages repository database operations"""
    
    def __init__(self, config):
        self.config = config
        self.debug_mode = config.get('debug_mode', False)
    
    def generate_database(self, repo_name, output_dir):
        """Generate repository database"""
        if self.debug_mode:
            print(f"🔧 [DEBUG] Generating database for {repo_name}", flush=True)
        else:
            logger.info(f"Generating database for {repo_name}")
        
        # Change to output directory
        old_cwd = os.getcwd()
        os.chdir(output_dir)
        
        try:
            db_file = f"{repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{repo_name}.db", f"{repo_name}.db.tar.gz", 
                      f"{repo_name}.files", f"{repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # Generate database
            cmd = f"repo-add {db_file} *.pkg.tar.zst"
            
            if self.debug_mode:
                print(f"🔧 [DEBUG] Running repo-add: {cmd}", flush=True)
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Database created successfully", flush=True)
                else:
                    logger.info("✅ Database created successfully")
                return True
            else:
                if self.debug_mode:
                    print(f"❌ [DEBUG] repo-add failed: {result.stderr}", flush=True)
                else:
                    logger.error(f"repo-add failed: {result.stderr}")
                return False
                
        finally:
            os.chdir(old_cwd)