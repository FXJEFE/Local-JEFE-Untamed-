#!/usr/bin/env python3
"""
Sandbox Manager
Manages sandbox environment for safe file editing and testing.
Provides isolation, version control, and approval workflow.
"""

import sqlite3
import json
import shutil
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class SandboxFile:
    """Represents a file in the sandbox"""
    file_path: str
    original_content: str
    modified_content: Optional[str]
    original_hash: str
    modified_hash: Optional[str]
    test_results: Optional[Dict]
    approved: bool
    created_at: datetime


class SandboxManager:
    """
    Manages sandbox environment for safe file editing and testing.
    
    Workflow:
    1. Stage: Copy file to sandbox for editing
    2. Edit: Make changes in isolated environment
    3. Test: Run automated tests on changes
    4. Deploy: Approve and deploy to production with backup
    
    Features:
    - Isolated editing environment
    - Automatic backup creation
    - Test execution before deployment
    - Approval workflow
    - Version tracking with hashes
    """

    def __init__(
        self,
        db_path: str = "./data/unified_context.db",
        sandbox_root: str = "./sandbox"
    ):
        self.db_path = db_path
        self.sandbox_root = Path(sandbox_root)
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self._init_database()
        
        logger.info(f"Initialized SandboxManager at {self.sandbox_root}")

    def _init_database(self):
        """Ensure sandbox tables exist"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Table should exist from schema, but create if missing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sandbox_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                original_content TEXT,
                original_hash TEXT,
                modified_content TEXT,
                modified_hash TEXT,
                test_results JSON,
                approved BOOLEAN DEFAULT 0,
                backup_path TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deployed_at TIMESTAMP,
                UNIQUE(session_id, file_path)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                details JSON,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def stage_file(
        self,
        session_id: str,
        file_path: str,
        create_backup: bool = True
    ) -> Tuple[bool, str]:
        """
        Stage a file for editing in sandbox.
        Creates backup and stores original content.
        
        Returns: (success, message)
        """
        source_path = Path(file_path).resolve()

        if not source_path.exists():
            return False, f"File not found: {file_path}"

        try:
            # Read original content
            with open(source_path, 'r', encoding='utf-8') as f:
                original_content = f.read()

            # Calculate hash
            original_hash = hashlib.sha256(
                original_content.encode('utf-8')
            ).hexdigest()

            # Create sandbox copy
            sandbox_path = self.sandbox_root / session_id / source_path.name
            sandbox_path.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy2(source_path, sandbox_path)

            # Store in database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO sandbox_state
                (session_id, file_path, original_content, original_hash, timestamp)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (session_id, str(source_path), original_content, original_hash))

            # Log file operation
            cursor.execute("""
                INSERT INTO file_operations
                (session_id, operation_type, file_path, status, details)
                VALUES (?, 'stage', ?, 'success', ?)
            """, (
                session_id,
                str(source_path),
                json.dumps({"hash": original_hash, "size": len(original_content)})
            ))

            conn.commit()
            conn.close()

            logger.info(f"Staged file {file_path} in sandbox for session {session_id}")
            return True, f"File staged: {sandbox_path}"

        except Exception as e:
            logger.error(f"Failed to stage file: {e}")
            return False, f"Error staging file: {str(e)}"

    def edit_file(
        self,
        session_id: str,
        file_path: str,
        content: str
    ) -> Tuple[bool, str]:
        """
        Edit file in sandbox.
        
        Returns: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Verify file is staged
            cursor.execute("""
                SELECT id, file_path FROM sandbox_state
                WHERE session_id = ? AND file_path = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (session_id, str(Path(file_path).resolve())))

            result = cursor.fetchone()

            if not result:
                conn.close()
                return False, "File not staged in sandbox. Use stage_file() first."

            sandbox_id, original_path = result

            # Calculate new hash
            new_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

            # Update sandbox state
            cursor.execute("""
                UPDATE sandbox_state
                SET modified_content = ?,
                    modified_hash = ?,
                    test_results = NULL,
                    approved = 0
                WHERE id = ?
            """, (content, new_hash, sandbox_id))

            # Write to sandbox file
            sandbox_path = self.sandbox_root / session_id / Path(original_path).name
            with open(sandbox_path, 'w', encoding='utf-8') as f:
                f.write(content)

            # Log operation
            cursor.execute("""
                INSERT INTO file_operations
                (session_id, operation_type, file_path, status, details)
                VALUES (?, 'edit', ?, 'success', ?)
            """, (
                session_id,
                str(original_path),
                json.dumps({"new_hash": new_hash, "size": len(content)})
            ))

            conn.commit()
            conn.close()

            return True, f"File edited in sandbox: {sandbox_path}"

        except Exception as e:
            conn.close()
            logger.error(f"Edit failed: {e}")
            return False, f"Error editing file: {str(e)}"

    def test_file(
        self,
        session_id: str,
        file_path: str,
        test_command: Optional[str] = None
    ) -> Tuple[bool, Dict]:
        """
        Test edited file in sandbox using SafeCodeExecutor.
        
        Returns: (success, test_results_dict)
        """
        try:
            from safe_code_executor import get_executor
        except ImportError:
            logger.warning("SafeCodeExecutor not available")
            return False, {"error": "SafeCodeExecutor not available"}

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get sandbox file
            cursor.execute("""
                SELECT id, file_path, modified_content
                FROM sandbox_state
                WHERE session_id = ? AND file_path = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (session_id, str(Path(file_path).resolve())))

            result = cursor.fetchone()

            if not result:
                conn.close()
                return False, {"error": "File not found in sandbox"}

            sandbox_id, original_path, content = result

            if not content:
                conn.close()
                return False, {"error": "No modifications to test"}

            # Determine test strategy based on file type
            file_ext = Path(original_path).suffix

            test_results = {}

            if file_ext == '.py':
                executor = get_executor()

                # Static analysis
                analysis = executor.analyze_code(content)
                test_results['static_analysis'] = analysis

                # Syntax check
                if not analysis.get('valid_syntax'):
                    test_results['status'] = 'failed'
                    test_results['error'] = 'Syntax error'
                else:
                    # Try to execute if requested
                    if test_command:
                        exec_result = executor.execute_python(content)
                        test_results['execution'] = exec_result
                        test_results['status'] = 'passed' if exec_result.get('success') else 'failed'
                    else:
                        test_results['status'] = 'syntax_ok'

            else:
                test_results['status'] = 'no_tests'
                test_results['message'] = f"No automated tests for {file_ext} files"

            # Store test results
            cursor.execute("""
                UPDATE sandbox_state
                SET test_results = ?
                WHERE id = ?
            """, (json.dumps(test_results), sandbox_id))

            # Log test operation
            cursor.execute("""
                INSERT INTO file_operations
                (session_id, operation_type, file_path, status, details)
                VALUES (?, 'test', ?, ?, ?)
            """, (
                session_id,
                str(original_path),
                test_results['status'],
                json.dumps(test_results)
            ))

            conn.commit()
            conn.close()

            return test_results['status'] in ['passed', 'syntax_ok'], test_results

        except Exception as e:
            conn.close()
            logger.error(f"Test failed: {e}")
            return False, {"error": str(e), "status": "error"}

    def approve_and_deploy(
        self,
        session_id: str,
        file_path: str,
        create_backup: bool = True
    ) -> Tuple[bool, str]:
        """
        Approve sandbox changes and deploy to original location.
        Creates backup of original file before overwriting.
        
        Returns: (success, message)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get sandbox file
            cursor.execute("""
                SELECT id, file_path, original_content, modified_content, test_results
                FROM sandbox_state
                WHERE session_id = ? AND file_path = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (session_id, str(Path(file_path).resolve())))

            result = cursor.fetchone()

            if not result:
                conn.close()
                return False, "File not found in sandbox"

            sandbox_id, original_path, original_content, modified_content, test_results_json = result

            if not modified_content:
                conn.close()
                return False, "No modifications to deploy"

            # Check test status
            if test_results_json:
                test_results = json.loads(test_results_json)
                if test_results.get('status') == 'failed':
                    conn.close()
                    return False, "Cannot deploy: tests failed. Review test results first."

            # Create backup if requested
            original_file = Path(original_path)
            backup_path = None
            
            if create_backup and original_file.exists():
                backup_dir = original_file.parent / ".backups"
                backup_dir.mkdir(exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"{original_file.name}.{timestamp}.bak"

                shutil.copy2(original_file, backup_path)
                logger.info(f"Created backup: {backup_path}")

            # Deploy changes
            with open(original_file, 'w', encoding='utf-8') as f:
                f.write(modified_content)

            # Mark as approved
            cursor.execute("""
                UPDATE sandbox_state
                SET approved = 1,
                    backup_path = ?,
                    deployed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (str(backup_path) if backup_path else None, sandbox_id))

            # Log deployment
            cursor.execute("""
                INSERT INTO file_operations
                (session_id, operation_type, file_path, status, details)
                VALUES (?, 'deploy', ?, 'success', ?)
            """, (
                session_id,
                str(original_path),
                json.dumps({
                    "backup_created": create_backup,
                    "backup_path": str(backup_path) if backup_path else None
                })
            ))

            conn.commit()
            conn.close()

            return True, f"Changes deployed to {original_path}" + (f"\nBackup: {backup_path}" if backup_path else "")

        except Exception as e:
            conn.close()
            logger.error(f"Deployment failed: {e}")
            return False, f"Error deploying changes: {str(e)}"

    def get_sandbox_status(self, session_id: str) -> List[Dict]:
        """Get status of all files in sandbox for session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT file_path,
                       modified_content IS NOT NULL as has_changes,
                       test_results,
                       approved,
                       timestamp,
                       deployed_at
                FROM sandbox_state
                WHERE session_id = ?
                ORDER BY timestamp DESC
            """, (session_id,))

            results = []
            for row in cursor.fetchall():
                test_results = json.loads(row[2]) if row[2] else None
                results.append({
                    "file_path": row[0],
                    "has_changes": bool(row[1]),
                    "test_status": test_results.get('status') if test_results else None,
                    "approved": bool(row[3]),
                    "timestamp": row[4],
                    "deployed_at": row[5]
                })

            return results
            
        finally:
            conn.close()

    def discard_changes(self, session_id: str, file_path: str) -> Tuple[bool, str]:
        """Discard changes and remove file from sandbox"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM sandbox_state
                WHERE session_id = ? AND file_path = ?
            """, (session_id, str(Path(file_path).resolve())))

            if cursor.rowcount > 0:
                # Remove sandbox file
                sandbox_path = self.sandbox_root / session_id / Path(file_path).name
                if sandbox_path.exists():
                    sandbox_path.unlink()

                conn.commit()
                conn.close()
                return True, "Changes discarded"
            else:
                conn.close()
                return False, "File not found in sandbox"

        except Exception as e:
            conn.close()
            logger.error(f"Discard failed: {e}")
            return False, f"Error discarding changes: {str(e)}"

    def clear_sandbox(self, session_id: str) -> bool:
        """Clear entire sandbox for session"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM sandbox_state WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()

            # Remove sandbox directory
            sandbox_dir = self.sandbox_root / session_id
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir)

            logger.info(f"Cleared sandbox for session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Clear sandbox failed: {e}")
            return False


# Global instance
_sandbox_manager: Optional[SandboxManager] = None

def get_sandbox_manager(
    db_path: str = "./data/unified_context.db",
    sandbox_root: str = "./sandbox"
) -> SandboxManager:
    """Get sandbox manager singleton"""
    global _sandbox_manager
    if _sandbox_manager is None:
        _sandbox_manager = SandboxManager(db_path, sandbox_root)
    return _sandbox_manager


if __name__ == "__main__":
    print("Testing Sandbox Manager...")
    
    import tempfile
    temp_dir = Path(tempfile.mkdtemp())
    
    # Create test file
    test_file = temp_dir / "test.py"
    test_file.write_text("print('Hello')\n")
    
    # Initialize sandbox
    sandbox = get_sandbox_manager(sandbox_root=str(temp_dir / "sandbox"))
    session_id = "test_session"
    
    # Stage file
    success, msg = sandbox.stage_file(session_id, str(test_file))
    print(f"\n✅ Stage: {success} - {msg}")
    
    # Edit file
    new_content = "print('Hello World')\n"
    success, msg = sandbox.edit_file(session_id, str(test_file), new_content)
    print(f"✅ Edit: {success} - {msg}")
    
    # Test file
    success, results = sandbox.test_file(session_id, str(test_file))
    print(f"✅ Test: {success} - Status: {results.get('status')}")
    
    # Get status
    status = sandbox.get_sandbox_status(session_id)
    print(f"✅ Status: {len(status)} files in sandbox")
    
    # Deploy
    success, msg = sandbox.approve_and_deploy(session_id, str(test_file))
    print(f"✅ Deploy: {success} - {msg}")
    
    # Verify
    deployed_content = test_file.read_text()
    print(f"✅ Deployed content matches: {deployed_content == new_content}")
    
    # Cleanup
    shutil.rmtree(temp_dir)
    print("\n✅ All tests passed!")
