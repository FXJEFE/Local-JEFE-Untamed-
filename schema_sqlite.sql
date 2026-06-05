-- Larry G-Force SQLite Schema
-- Used for persistent memory, conversation logs, and metadata

-- 1. Conversation History
CREATE TABLE IF NOT EXISTS conversation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL, -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    model TEXT,
    tokens INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. Knowledge Graph (Simplified)
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT, -- 'person', 'place', 'tech', 'project'
    description TEXT,
    observations TEXT, -- JSON array of observations
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES entities(id),
    target_id INTEGER REFERENCES entities(id),
    relation_type TEXT, -- 'member_of', 'works_on', 'depends_on'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 3. File Metadata & Analysis Cache
CREATE TABLE IF NOT EXISTS file_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    last_modified REAL,
    hash TEXT,
    summary TEXT,
    language TEXT,
    lines_count INTEGER,
    last_indexed DATETIME
);

-- 4. Agent Skills & Tools Usage
CREATE TABLE IF NOT EXISTS tool_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    success BOOLEAN,
    duration REAL,
    error_message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_session ON conversation_history(session_id);
CREATE INDEX IF NOT EXISTS idx_file_path ON file_cache(file_path);
CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_usage(tool_name);
