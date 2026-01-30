# Manjaro Package Builder Architecture

## Overview
This is a modular package builder system for Manjaro Linux that handles:
- AUR package building
- Local package building
- Repository management
- VPS operations (SSH, Rsync)
- GPG signing
- Zero-Residue cleanup policy

## Module Structure

### scripts/modules/
- **build/**: Package building operations
  - `artifact_manager.py`: Package file management and cleanup
  - `aur_builder.py`: AUR package building and dependency resolution
  - `build_tracker.py`: Build progress tracking and statistics
  - `local_builder.py`: Local package building operations
  - `version_manager.py`: Version extraction, comparison, and management

- **common/**: Shared utilities
  - `config_loader.py`: Configuration loading and validation
  - `environment.py`: Environment validation and setup
  - `logging_utils.py`: Logging configuration
  - `shell_executor.py`: Shell command execution with logging

- **gpg/**: GPG operations
  - `gpg_handler.py`: GPG key import, signing, and pacman-key operations

- **orchestrator/**: Main coordination
  - `package_builder.py`: Main orchestrator for package building
  - `state.py`: Application state management

- **repo/**: Repository management
  - `cleanup_manager.py`: Zero-Residue policy and package cleanup
  - `database_manager.py`: Repository database operations
  - `recovery_manager.py`: Repository recovery operations
  - `version_tracker.py`: Package version tracking and comparison

- **scm/**: Source Code Management
  - `git_client.py`: Git operations for repository management

- **vps/**: VPS operations
  - `db_manager.py`: Remote database operations on VPS
  - `rsync_client.py`: File transfers using Rsync
  - `ssh_client.py`: SSH connections and remote operations

### Main Scripts
- `builder.py`: Main entry point
- `checker.py`: Package validation
- `config.py`: Configuration and secrets
- `packages.py`: Package definitions

## Zero-Residue Policy
The system implements a Zero-Residue policy that:
1. Tracks target versions for all packages
2. Removes old versions before building new ones
3. Performs pre-database and post-upload cleanup
4. Uses target versions as the single source of truth

## Configuration
All configuration is centralized in `scripts/config.py`:
- Environment variables for secrets
- Hardcoded strings and URLs
- Build timeouts and dependencies
- Repository settings

## Key Features
- Modular architecture for maintainability
- Comprehensive logging and debugging
- SSH and Rsync for remote operations
- GPG signing support
- Version comparison using SRCINFO
- Dependency resolution with AUR fallback
- Database generation with zombie protection