import os
import re
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
import subprocess
import tempfile
import shutil


class ManifestFactory:
    """
    Generates allowlist of valid package names from PKGBUILD files.
    Source of truth is PKGBUILD pkgname values (single or array).
    """
    
    @staticmethod
    def get_pkgbuild(source: str) -> Optional[str]:
        """
        Load PKGBUILD file content from AUR or local path.
        
        Args:
            source: Either local path to PKGBUILD directory or AUR package name
            
        Returns:
            PKGBUILD content as string, or None if failed
        """
        try:
            # Check if source is a local directory
            pkgbuild_path = Path(source) / "PKGBUILD"
            
            if pkgbuild_path.exists():
                # Local PKGBUILD
                with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                # Try AUR - clone the PKGBUILD
                return ManifestFactory._fetch_aur_pkgbuild(source)
                
        except Exception as e:
            print(f"Error loading PKGBUILD from {source}: {e}")
            return None
    
    @staticmethod
    def _fetch_aur_pkgbuild(pkg_name: str) -> Optional[str]:
        """
        Fetch PKGBUILD from AUR.
        
        Args:
            pkg_name: AUR package name
            
        Returns:
            PKGBUILD content as string, or None if failed
        """
        temp_dir = None
        try:
            # Create temporary directory for cloning
            temp_dir = tempfile.mkdtemp(prefix="aur_")
            
            # Try different AUR URLs
            aur_urls = [
                f"https://aur.archlinux.org/{pkg_name}.git",
                f"git://aur.archlinux.org/{pkg_name}.git"
            ]
            
            for aur_url in aur_urls:
                try:
                    # Clone the AUR package (shallow clone)
                    result = subprocess.run(
                        ["git", "clone", "--depth", "1", aur_url, temp_dir],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    
                    if result.returncode == 0:
                        # Read PKGBUILD
                        pkgbuild_path = Path(temp_dir) / "PKGBUILD"
                        if pkgbuild_path.exists():
                            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            return content
                    
                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    continue
            
            return None
            
        except Exception as e:
            print(f"Error fetching AUR PKGBUILD for {pkg_name}: {e}")
            return None
        finally:
            # Cleanup
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    @staticmethod
    def extract_pkgnames(pkgbuild_text: str) -> List[str]:
        """
        Parse pkgname values from PKGBUILD text.
        Handles both single values and arrays.
        
        Args:
            pkgbuild_text: PKGBUILD content as string
            
        Returns:
            List of package names extracted from PKGBUILD
        """
        pkg_names = []
        
        # Remove comments
        lines = []
        for line in pkgbuild_text.split('\n'):
            line = line.split('#')[0].rstrip()
            if line:
                lines.append(line)
        
        # Join continuation lines
        cleaned_text = ''
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.endswith('\\'):
                # Continuation line
                cleaned_text += line.rstrip('\\')
                i += 1
                while i < len(lines) and lines[i].endswith('\\'):
                    cleaned_text += lines[i].rstrip('\\')
                    i += 1
                if i < len(lines):
                    cleaned_text += lines[i]
            else:
                cleaned_text += line
            cleaned_text += '\n'
            i += 1
        
        # Look for pkgname assignments
        # Pattern for single value: pkgname="value" or pkgname='value' or pkgname=value
        # Pattern for array: pkgname=("val1" "val2") or pkgname=('val1' 'val2')
        
        # Find pkgname assignment
        pkgname_patterns = [
            r'pkgname\s*=\s*["\']([^"\']+)["\']',  # Single quoted
            r'pkgname\s*=\s*\(([^)]+)\)',  # Array
        ]
        
        for pattern in pkgname_patterns:
            matches = re.findall(pattern, cleaned_text, re.MULTILINE | re.DOTALL)
            for match in matches:
                if match.strip():
                    # Check if it's an array
                    if '(' not in pattern:  # Single value pattern
                        pkg_names.append(match.strip())
                    else:
                        # Array - split by spaces and clean quotes
                        items = re.findall(r'["\']([^"\']+)["\']', match)
                        pkg_names.extend([item.strip() for item in items if item.strip()])
        
        # Alternative: Use bash to parse if available (more reliable)
        if not pkg_names:
            try:
                pkg_names = ManifestFactory._parse_with_bash(pkgbuild_text)
            except Exception:
                pass
        
        # Remove duplicates and empty strings
        pkg_names = list(dict.fromkeys([name for name in pkg_names if name]))
        
        return pkg_names
    
    @staticmethod
    def _parse_with_bash(pkgbuild_text: str) -> List[str]:
        """
        Parse PKGBUILD using bash to extract pkgname values.
        More reliable for complex PKGBUILDs.
        """
        # Create a temporary PKGBUILD file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.PKGBUILD', delete=False) as tmp:
            tmp.write(pkgbuild_text)
            tmp_path = tmp.name
        
        try:
            # Use bash to source the PKGBUILD and extract pkgname
            script = f'''
            source "{tmp_path}" 2>/dev/null
            if declare -p pkgname 2>/dev/null | grep -q "declare -a"; then
                # Array
                for name in "${{pkgname[@]}}"; do
                    echo "$name"
                done
            else
                # Single value
                echo "$pkgname"
            fi
            '''
            
            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                names = [name.strip() for name in result.stdout.strip().split('\n') if name.strip()]
                return names
            else:
                return []
                
        finally:
            # Cleanup
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
    
    @staticmethod
    def build_allowlist(package_sources: List[str]) -> Set[str]:
        """
        Build allowlist of valid package names from all PKGBUILDs.
        
        Args:
            package_sources: List of package sources (local paths or AUR package names)
            
        Returns:
            Set of all valid package names from all PKGBUILDs
        """
        allowlist = set()
        
        for source in package_sources:
            pkgbuild_content = ManifestFactory.get_pkgbuild(source)
            
            if pkgbuild_content:
                pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
                
                if pkg_names:
                    print(f"Extracted from {source}: {pkg_names}")
                    allowlist.update(pkg_names)
                else:
                    print(f"Warning: No pkgname found in {source}")
            else:
                print(f"Warning: Could not load PKGBUILD from {source}")
        
        return allowlist


# Optional: Helper function for direct usage
def build_package_allowlist(package_sources: List[str]) -> Set[str]:
    """
    Convenience function to build allowlist from package sources.
    
    Args:
        package_sources: List of package sources (local paths or AUR package names)
        
    Returns:
        Set of all valid package names
    """
    factory = ManifestFactory()
    return factory.build_allowlist(package_sources)


if __name__ == "__main__":
    # Example usage
    test_sources = [
        "/path/to/local/package",  # Local directory with PKGBUILD
        "yay"  # AUR package name
    ]
    
    allowlist = build_package_allowlist(test_sources)
    print(f"Allowlist: {sorted(allowlist)}")
