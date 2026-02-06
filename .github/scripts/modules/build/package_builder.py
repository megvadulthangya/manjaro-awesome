    def _build_aur_package(self, pkg_dir: Path, pkg_name: str, version: str) -> List[str]:
        """Build AUR package using AURBuilder and return list of built files."""
        try:
            # Clean workspace using ArtifactManager
            self.artifact_manager.clean_workspace(pkg_dir)
            
            # Build package using AURBuilder
            logger.info("   Building package...")
            logger.info("AUR_BUILDER_USED=1")
            
            # Use AURBuilder for the entire build process
            built_files = self.aur_builder.build_aur_package(
                pkg_name=pkg_name,
                target_dir=pkg_dir,
                packager_id=self.packager_id,
                build_flags="-si --noconfirm --clean --nocheck",
                timeout=3600
            )
            
            if built_files:
                # Move built packages to output directory and return list
                moved_files = self._move_built_packages(pkg_dir, pkg_name, version)
                return moved_files
            else:
                logger.error(f"❌ No package files created for {pkg_name}")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error building {pkg_name}: {e}")
            return []