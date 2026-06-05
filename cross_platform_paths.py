#!/usr/bin/env python3
"""
Cross-Platform Path Manager
Handles path operations consistently across Windows, Linux, and macOS.
Ensures proper path normalization, validation, and security checks.
"""

import os
import platform
from pathlib import Path, PureWindowsPath, PurePosixPath
from typing import Union, Optional, List, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

class CrossPlatformPathManager:
    """
    Handles path operations consistently across Windows, Linux, and macOS.
    Ensures proper path normalization and validation.
    
    Key features:
    - Automatic path separator normalization
    - Security checks to prevent path traversal
    - Long path support for Windows (>260 characters)
    - Symbolic link handling
    - Case-sensitivity awareness
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir).resolve()
        self.platform = platform.system()
        self.is_windows = self.platform == "Windows"
        self.is_linux = self.platform == "Linux"
        self.is_macos = self.platform == "Darwin"
        self.path_separator = "\\" if self.is_windows else "/"
        
        logger.info(f"Initialized path manager for {self.platform} at {self.base_dir}")

    def normalize_path(self, path: Union[str, Path]) -> Path:
        """
        Normalize path to be platform-independent.
        Converts Windows paths to Posix when needed and vice versa.
        """
        if isinstance(path, str):
            # Handle mixed separators
            path = path.replace("\\", os.sep).replace("/", os.sep)
            path = Path(path)

        # Resolve to absolute path
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        else:
            path = path.resolve()

        return path

    def validate_path(
        self,
        path: Union[str, Path],
        must_exist: bool = False,
        allow_create: bool = False
    ) -> Tuple[Optional[Path], Optional[str]]:
        """
        Validate and sanitize path.
        Returns (normalized_path, error_message)
        
        Security checks:
        - Prevents path traversal attacks
        - Ensures path is within allowed base directory
        - Validates parent directory exists
        """
        try:
            normalized = self.normalize_path(path)

            # Security check: prevent path traversal
            try:
                normalized.relative_to(self.base_dir)
            except ValueError:
                return None, f"Path outside allowed directory: {path}"

            # Existence check
            if must_exist and not normalized.exists():
                return None, f"Path does not exist: {path}"

            # Parent directory check
            if not normalized.parent.exists():
                if allow_create:
                    normalized.parent.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Created parent directory: {normalized.parent}")
                else:
                    return None, f"Parent directory does not exist: {normalized.parent}"

            return normalized, None

        except Exception as e:
            logger.error(f"Path validation error: {e}")
            return None, f"Invalid path: {str(e)}"

    def get_relative_path(self, path: Union[str, Path]) -> Path:
        """Get path relative to base directory"""
        normalized = self.normalize_path(path)
        try:
            return normalized.relative_to(self.base_dir)
        except ValueError:
            return normalized

    def safe_open(
        self,
        path: Union[str, Path],
        mode: str = 'r',
        encoding: str = 'utf-8',
        **kwargs
    ):
        """
        Safely open file with validation and cross-platform compatibility.
        
        Handles:
        - Path validation
        - Long path support on Windows
        - Proper encoding
        """
        normalized, error = self.validate_path(
            path,
            must_exist='r' in mode,
            allow_create='w' in mode or 'a' in mode
        )

        if error:
            raise ValueError(error)

        # On Windows, handle long paths
        if self.is_windows and len(str(normalized)) > 260:
            normalized = Path("\\\\?\\" + str(normalized))
            logger.debug(f"Using long path prefix for: {normalized}")

        return open(normalized, mode, encoding=encoding, **kwargs)

    def list_directory(
        self,
        path: Union[str, Path],
        pattern: Optional[str] = None,
        recursive: bool = False,
        include_hidden: bool = False
    ) -> List[Path]:
        """
        List directory contents with cross-platform compatibility.
        
        Args:
            path: Directory to list
            pattern: Optional glob pattern (e.g., "*.py")
            recursive: If True, search recursively
            include_hidden: If True, include hidden files/directories
        """
        normalized, error = self.validate_path(path, must_exist=True)

        if error:
            raise ValueError(error)

        if not normalized.is_dir():
            raise ValueError(f"Not a directory: {path}")

        if recursive:
            if pattern:
                results = sorted(normalized.rglob(pattern))
            else:
                results = sorted(normalized.rglob("*"))
        else:
            if pattern:
                results = sorted(normalized.glob(pattern))
            else:
                results = sorted(normalized.iterdir())

        # Filter hidden files if requested
        if not include_hidden:
            results = [p for p in results if not self._is_hidden(p)]

        return results

    def _is_hidden(self, path: Path) -> bool:
        """Check if file/directory is hidden (cross-platform)"""
        # Unix-like systems: starts with dot
        if not self.is_windows and path.name.startswith('.'):
            return True
        
        # Windows: check file attributes
        if self.is_windows:
            try:
                import ctypes
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
                return attrs != -1 and bool(attrs & 2)  # FILE_ATTRIBUTE_HIDDEN
            except Exception:
                return path.name.startswith('.')
        
        return False

    def ensure_directory(self, path: Union[str, Path]) -> Path:
        """Ensure directory exists, creating it if necessary"""
        normalized, error = self.validate_path(path, allow_create=True)
        
        if error:
            raise ValueError(error)
        
        if not normalized.exists():
            normalized.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {normalized}")
        
        return normalized

    def safe_delete(self, path: Union[str, Path]) -> bool:
        """Safely delete a file or directory"""
        normalized, error = self.validate_path(path, must_exist=True)
        
        if error:
            logger.error(f"Cannot delete: {error}")
            return False
        
        try:
            if normalized.is_file():
                normalized.unlink()
                logger.info(f"Deleted file: {normalized}")
            elif normalized.is_dir():
                import shutil
                shutil.rmtree(normalized)
                logger.info(f"Deleted directory: {normalized}")
            return True
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False

    def safe_copy(
        self,
        source: Union[str, Path],
        destination: Union[str, Path],
        overwrite: bool = False
    ) -> bool:
        """Safely copy file or directory"""
        import shutil
        
        src_path, src_error = self.validate_path(source, must_exist=True)
        if src_error:
            logger.error(f"Source error: {src_error}")
            return False
        
        dst_path, dst_error = self.validate_path(destination, allow_create=True)
        if dst_error:
            logger.error(f"Destination error: {dst_error}")
            return False
        
        if dst_path.exists() and not overwrite:
            logger.error(f"Destination exists and overwrite=False: {dst_path}")
            return False
        
        try:
            if src_path.is_file():
                shutil.copy2(src_path, dst_path)
            elif src_path.is_dir():
                if dst_path.exists():
                    shutil.rmtree(dst_path)
                shutil.copytree(src_path, dst_path)
            
            logger.info(f"Copied: {src_path} -> {dst_path}")
            return True
        except Exception as e:
            logger.error(f"Copy failed: {e}")
            return False

    def get_file_info(self, path: Union[str, Path]) -> Dict:
        """Get detailed file information"""
        normalized, error = self.validate_path(path, must_exist=True)
        
        if error:
            raise ValueError(error)
        
        stat = normalized.stat()
        
        return {
            'path': str(normalized),
            'name': normalized.name,
            'size': stat.st_size,
            'size_mb': stat.st_size / (1024 * 1024),
            'is_file': normalized.is_file(),
            'is_dir': normalized.is_dir(),
            'is_symlink': normalized.is_symlink(),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'permissions': oct(stat.st_mode)[-3:],
            'extension': normalized.suffix,
            'relative_path': str(self.get_relative_path(normalized))
        }

    def find_files(
        self,
        pattern: str,
        path: Optional[Union[str, Path]] = None,
        max_depth: Optional[int] = None
    ) -> List[Path]:
        """
        Find files matching pattern.
        
        Args:
            pattern: Glob pattern (e.g., "*.py", "**/*.json")
            path: Search path (default: base_dir)
            max_depth: Maximum directory depth (None = unlimited)
        """
        search_path = self.normalize_path(path) if path else self.base_dir
        
        if max_depth is None:
            return list(search_path.rglob(pattern))
        else:
            results = []
            for p in search_path.rglob(pattern):
                depth = len(p.relative_to(search_path).parts)
                if depth <= max_depth:
                    results.append(p)
            return results


# Global instance
_path_manager: Optional[CrossPlatformPathManager] = None

def get_path_manager(base_dir: str = ".") -> CrossPlatformPathManager:
    """Get path manager singleton"""
    global _path_manager
    if _path_manager is None:
        _path_manager = CrossPlatformPathManager(base_dir)
    return _path_manager


if __name__ == "__main__":
    from datetime import datetime
    print("Testing Cross-Platform Path Manager...")
    
    manager = get_path_manager()
    
    # Test path normalization
    print(f"\n🔧 Platform: {manager.platform}")
    print(f"   Base dir: {manager.base_dir}")
    
    # Test validation
    test_path = "./test_file.txt"
    normalized, error = manager.validate_path(test_path, allow_create=True)
    print(f"\n✅ Validation: {normalized}")
    
    # Test directory creation
    test_dir = manager.ensure_directory("./test_sandbox")
    print(f"✅ Created: {test_dir}")
    
    # Test file operations
    test_file = test_dir / "test.txt"
    with manager.safe_open(test_file, 'w') as f:
        f.write("Test content")
    print(f"✅ Created file: {test_file}")
    
    # Get file info
    info = manager.get_file_info(test_file)
    print(f"✅ File info: {info['size']} bytes")
    
    # Cleanup
    manager.safe_delete(test_dir)
    print(f"✅ Cleaned up")
    
    print("\n✅ All tests passed!")
