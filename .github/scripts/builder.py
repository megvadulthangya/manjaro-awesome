def upload_packages(self):
    """Upload packages to server using RSYNC WITHOUT --delete flag (Chemotox cleanup handles orphans)."""
    # Get all package files and database files
    pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
    db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
    
    all_files = pkg_files + db_files
    
    if not all_files:
        logger.warning("No files to upload")
        self._upload_successful = False  # Set flag
        return False
    
    # Log upload start with GPG status
    if self.gpg_enabled:
        logger.info("Starting upload (including signatures)...")
    else:
        logger.info("Starting upload...")
    
    # Ensure remote directory exists first
    self._ensure_remote_directory()
    
    # Collect files using glob patterns
    file_patterns = [
        str(self.output_dir / "*.pkg.tar.*"),
        str(self.output_dir / f"{self.repo_name}.*")
    ]
    
    files_to_upload = []
    for pattern in file_patterns:
        files_to_upload.extend(glob.glob(pattern))
    
    if not files_to_upload:
        logger.error("No files found to upload!")
        self._upload_successful = False  # Set flag
        return False
    
    # Log files to upload
    logger.info(f"Files to upload ({len(files_to_upload)}):")
    for f in files_to_upload:
        size_mb = os.path.getsize(f) / (1024 * 1024)
        file_type = "DATABASE"
        if self.repo_name in os.path.basename(f):
            if f.endswith('.sig'):
                file_type = "SIGNATURE"
            else:
                file_type = "DATABASE"
        else:
            file_type = "PACKAGE"
        logger.info(f"  - {os.path.basename(f)} ({size_mb:.1f}MB) [{file_type}]")
    
    # Build RSYNC command WITHOUT --delete (Chemotox cleanup handles orphans)
    rsync_cmd = f"""
    rsync -avz \
      --progress \
      --stats \
      {" ".join(f"'{f}'" for f in files_to_upload)} \
      '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
    """
    
    # Log the command
    logger.info(f"RUNNING RSYNC COMMAND WITHOUT --delete (Chemotox cleanup handles orphans):")
    logger.info(rsync_cmd.strip())
    logger.info(f"SOURCE: {self.output_dir}/")
    logger.info(f"DESTINATION: {self.vps_user}@{self.vps_host}:{self.remote_dir}/")
    logger.info(f"IMPORTANT: Using Chemotox SSH cleanup for zero-residue policy")
    
    # FIRST ATTEMPT
    start_time = time.time()
    
    try:
        result = subprocess.run(
            rsync_cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=False
        )
        
        end_time = time.time()
        duration = int(end_time - start_time)
        
        logger.info(f"EXIT CODE (attempt 1): {result.returncode}")
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.strip():
                    logger.info(f"RSYNC: {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                if line.strip() and "No such file or directory" not in line:
                    logger.error(f"RSYNC ERR: {line}")
        
        if result.returncode == 0:
            logger.info(f"✅ RSYNC upload successful! ({duration} seconds)")
            self._upload_successful = True  # CRITICAL: Set success flag
            
            # Run Chemotox cleanup after successful upload ONLY
            self._server_cleanup()
            
            # Verification
            try:
                self._verify_uploaded_files()
            except Exception as e:
                logger.warning(f"⚠️ Verification error (upload still successful): {e}")
            return True
        else:
            logger.warning(f"⚠️ First RSYNC attempt failed (code: {result.returncode})")
            self._upload_successful = False  # Set flag
            
    except Exception as e:
        logger.error(f"RSYNC execution error: {e}")
        self._upload_successful = False  # Set flag
    
    # SECOND ATTEMPT (with different SSH options)
    logger.info("⚠️ Retrying with different SSH options...")
    time.sleep(5)
    
    # Use -e option with SSH command this time
    rsync_cmd_retry = f"""
    rsync -avz \
      --progress \
      --stats \
      -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3" \
      {" ".join(f"'{f}'" for f in files_to_upload)} \
      '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
    """
    
    logger.info(f"RUNNING RSYNC RETRY COMMAND WITHOUT --delete:")
    logger.info(rsync_cmd_retry.strip())
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            rsync_cmd_retry,
            shell=True,
            capture_output=True,
            text=True,
            check=False
        )
        
        end_time = time.time()
        duration = int(end_time - start_time)
        
        logger.info(f"EXIT CODE (attempt 2): {result.returncode}")
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.strip():
                    logger.info(f"RSYNC RETRY: {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                if line.strip() and "No such file or directory" not in line:
                    logger.error(f"RSYNC RETRY ERR: {line}")
        
        if result.returncode == 0:
            logger.info(f"✅ RSYNC upload successful on retry! ({duration} seconds)")
            self._upload_successful = True  # CRITICAL: Set success flag
            
            # Run Chemotox cleanup after successful upload ONLY
            self._server_cleanup()
            
            # Verification
            try:
                self._verify_uploaded_files()
            except Exception as e:
                logger.warning(f"⚠️ Verification error (upload still successful): {e}")
            return True
        else:
            logger.error(f"❌ RSYNC upload failed on both attempts!")
            self._upload_successful = False  # Set flag
            return False
            
    except Exception as e:
        logger.error(f"RSYNC retry execution error: {e}")
        self._upload_successful = False  # Set flag
        return False