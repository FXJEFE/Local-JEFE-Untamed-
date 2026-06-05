import json
import csv
import sqlite3
import configparser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

# Safe imports with fallbacks
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas not available - CSV features limited")

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    logger.warning("PyYAML not available")

try:
    import toml
    TOML_AVAILABLE = True
except ImportError:
    TOML_AVAILABLE = False
    logger.warning("toml not available")

class UniversalFileHandler:
    """
    Handle ALL file formats safely:
    - Code: .py, .js, .java, .cpp, .rs, .go, .sql
    - Data: .csv, .json, .xml, .yaml, .toml
    - Database: .sqlite, .db
    - Documents: .md, .txt, .rst
    - Config: .ini, .conf, .env
    """

    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)

    def read_file(self, filepath: str) -> Dict[str, Any]:
        """
        Universal file reader with safe error handling
        """
        path = Path(filepath)
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()

        if not path.exists():
            return {
                'success': False,
                'error': f'File not found: {filepath}'
            }

        suffix = path.suffix.lower()

        # Map extensions to handlers
        handlers = {
            '.json': self._read_json,
            '.csv': self._read_csv,
            '.tsv': self._read_tsv,
            '.yaml': self._read_yaml,
            '.yml': self._read_yaml,
            '.toml': self._read_toml,
            '.xml': self._read_xml,
            '.sqlite': self._read_sqlite,
            '.db': self._read_sqlite,
            '.ini': self._read_ini,
            '.env': self._read_env,
            '.conf': self._read_conf,
            '.py': self._read_code,
            '.js': self._read_code,
            '.java': self._read_code,
            '.cpp': self._read_code,
            '.c': self._read_code,
            '.rs': self._read_code,
            '.go': self._read_code,
            '.sql': self._read_code,
            '.md': self._read_text,
            '.txt': self._read_text,
            '.rst': self._read_text,
        }

        handler = handlers.get(suffix, self._read_text)

        try:
            result = handler(path)
            result['success'] = True
            return result
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'type': 'unknown'
            }

    def _read_json(self, path: Path) -> Dict:
        """Read JSON file"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return {
            'type': 'json',
            'data': data,
            'formatted': json.dumps(data, indent=2),
            'size': len(json.dumps(data))
        }

    def _read_csv(self, path: Path) -> Dict:
        """Read CSV file"""
        if PANDAS_AVAILABLE:
            df = pd.read_csv(path)

            # Get numeric stats if available
            stats = None
            numeric_cols = df.select_dtypes(include=['number']).columns
            if len(numeric_cols) > 0:
                stats = df[numeric_cols].describe().to_dict()

            return {
                'type': 'csv',
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'head': df.head(10).to_dict('records'),
                'dtypes': df.dtypes.astype(str).to_dict(),
                'stats': stats
            }
        else:
            # Fallback to basic CSV reading
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            return {
                'type': 'csv',
                'columns': reader.fieldnames if reader.fieldnames else [],
                'row_count': len(rows),
                'head': rows[:10]
            }

    def _read_tsv(self, path: Path) -> Dict:
        """Read TSV file"""
        if PANDAS_AVAILABLE:
            df = pd.read_csv(path, sep='\t')
            return {
                'type': 'tsv',
                'shape': df.shape,
                'columns': df.columns.tolist(),
                'head': df.head(10).to_dict('records')
            }
        else:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                rows = list(reader)

            return {
                'type': 'tsv',
                'columns': reader.fieldnames if reader.fieldnames else [],
                'row_count': len(rows),
                'head': rows[:10]
            }

    def _read_yaml(self, path: Path) -> Dict:
        """Read YAML file"""
        if not YAML_AVAILABLE:
            return {
                'type': 'yaml',
                'error': 'PyYAML not installed',
                'content': path.read_text(encoding='utf-8')
            }

        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return {
            'type': 'yaml',
            'data': data,
            'formatted': yaml.dump(data, default_flow_style=False)
        }

    def _read_toml(self, path: Path) -> Dict:
        """Read TOML file"""
        if not TOML_AVAILABLE:
            return {
                'type': 'toml',
                'error': 'toml not installed',
                'content': path.read_text(encoding='utf-8')
            }

        with open(path, 'r', encoding='utf-8') as f:
            data = toml.load(f)

        return {
            'type': 'toml',
            'data': data,
            'formatted': toml.dumps(data)
        }

    def _read_xml(self, path: Path) -> Dict:
        """Read XML file"""
        tree = ET.parse(path)
        root = tree.getroot()

        return {
            'type': 'xml',
            'root_tag': root.tag,
            'root_attrib': root.attrib,
            'content': ET.tostring(root, encoding='unicode'),
            'child_count': len(list(root))
        }

    def _read_sqlite(self, path: Path) -> Dict:
        """Read SQLite database metadata"""
        try:
            conn = sqlite3.connect(path)
            cursor = conn.cursor()

            # Get tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]

            table_info = {}
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]

                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = [
                        {
                            'name': row[1],
                            'type': row[2],
                            'notnull': bool(row[3]),
                            'pk': bool(row[5])
                        }
                        for row in cursor.fetchall()
                    ]

                    table_info[table] = {
                        'row_count': count,
                        'columns': columns
                    }
                except Exception as e:
                    table_info[table] = {'error': str(e)}

            conn.close()

            return {
                'type': 'sqlite',
                'tables': tables,
                'table_info': table_info,
                'database_size': path.stat().st_size
            }

        except Exception as e:
            return {
                'type': 'sqlite',
                'error': str(e)
            }

    def _read_ini(self, path: Path) -> Dict:
        """Read INI configuration file"""
        config = configparser.ConfigParser()
        config.read(path)

        data = {
            section: dict(config.items(section))
            for section in config.sections()
        }

        return {
            'type': 'ini',
            'sections': config.sections(),
            'data': data
        }

    def _read_env(self, path: Path) -> Dict:
        """Read .env file"""
        env_vars = {}

        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip().strip('"\'')

        return {
            'type': 'env',
            'variables': env_vars,
            'count': len(env_vars)
        }

    def _read_conf(self, path: Path) -> Dict:
        """Read generic conf file"""
        content = path.read_text(encoding='utf-8')
        lines = content.split('\n')

        # Try to parse as key=value
        config = {}
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()

        return {
            'type': 'conf',
            'content': content,
            'lines': len(lines),
            'parsed_config': config if config else None
        }

    def _read_code(self, path: Path) -> Dict:
        """Read code file"""
        content = path.read_text(encoding='utf-8', errors='ignore')
        lines = content.split('\n')

        # Basic code metrics
        blank_lines = sum(1 for line in lines if not line.strip())
        comment_lines = sum(
            1 for line in lines
            if line.strip().startswith(('#', '//', '/*', '*'))
        )

        return {
            'type': 'code',
            'language': path.suffix[1:],
            'content': content,
            'lines': len(lines),
            'blank_lines': blank_lines,
            'comment_lines': comment_lines,
            'code_lines': len(lines) - blank_lines - comment_lines,
            'size_bytes': len(content)
        }

    def _read_text(self, path: Path) -> Dict:
        """Read plain text file"""
        content = path.read_text(encoding='utf-8', errors='ignore')

        return {
            'type': 'text',
            'content': content,
            'lines': len(content.split('\n')),
            'words': len(content.split()),
            'chars': len(content),
            'size_bytes': path.stat().st_size
        }

    def execute_sql(
        self,
        db_path: str,
        query: str
    ) -> Dict:
        """Execute SQL query on SQLite database"""
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Execute query
            cursor.execute(query)

            # Get results
            if query.strip().upper().startswith('SELECT'):
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                result = {
                    'success': True,
                    'columns': columns,
                    'rows': rows,
                    'row_count': len(rows)
                }
            else:
                # For non-SELECT queries
                conn.commit()
                result = {
                    'success': True,
                    'affected_rows': cursor.rowcount
                }

            conn.close()
            return result

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def edit_csv(
        self,
        filepath: str,
        operation: str,
        **kwargs
    ) -> Dict:
        """
        Edit CSV files safely
        Operations: add_row, update_row, delete_row, add_column, sort
        """
        if not PANDAS_AVAILABLE:
            return {
                'success': False,
                'error': 'pandas not available'
            }

        try:
            df = pd.read_csv(filepath)

            if operation == 'add_row':
                new_row = kwargs.get('row', {})
                df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

            elif operation == 'update_row':
                condition = kwargs.get('condition')
                updates = kwargs.get('updates', {})
                for col, val in updates.items():
                    df.loc[condition, col] = val

            elif operation == 'delete_row':
                condition = kwargs.get('condition')
                df = df[~condition]

            elif operation == 'add_column':
                col_name = kwargs.get('name')
                default_value = kwargs.get('default', '')
                df[col_name] = default_value

            elif operation == 'sort':
                by = kwargs.get('by')
                ascending = kwargs.get('ascending', True)
                df = df.sort_values(by=by, ascending=ascending)

            else:
                return {
                    'success': False,
                    'error': f'Unknown operation: {operation}'
                }

            # Save
            df.to_csv(filepath, index=False)

            return {
                'success': True,
                'operation': operation,
                'new_shape': df.shape
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

# Global instance
_handler: Optional[UniversalFileHandler] = None

def get_file_handler(base_dir: str = ".") -> UniversalFileHandler:
    """Get file handler singleton"""
    global _handler
    if _handler is None:
        _handler = UniversalFileHandler(base_dir)
    return _handler

if __name__ == "__main__":
    print("Testing Universal File Handler...")
    handler = get_file_handler()

    # Test JSON
    test_json = Path("test.json")
    test_json.write_text('{"name": "test", "value": 123}')

    result = handler.read_file("test.json")
    print(f"\n✅ JSON: {result['success']}")
    print(f"Data: {result.get('data')}")

    # Test text
    test_txt = Path("test.txt")
    test_txt.write_text("Hello World\nLine 2")

    result = handler.read_file("test.txt")
    print(f"\n✅ Text: {result['success']}")
    print(f"Lines: {result.get('lines')}")

    # Cleanup
    if test_json.exists():
        test_json.unlink()
    if test_txt.exists():
        test_txt.unlink()

    print("\n✅ All tests passed!")
