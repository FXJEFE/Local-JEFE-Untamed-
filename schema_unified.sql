-- Unified Context Management Schema
-- Supports both CLI and Telegram interfaces with shared conversation history

-- Conversations table - tracks all sessions across interfaces
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    interface TEXT NOT NULL CHECK(interface IN ('telegram', 'cli', 'api')),
    chat_id INTEGER,
    user_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSON
);

-- Messages table - stores all conversation messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    tokens INTEGER DEFAULT 0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata JSON,
    FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE
);

-- Context summaries - for automatic context compression
CREATE TABLE IF NOT EXISTS context_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    tokens_saved INTEGER DEFAULT 0,
    messages_summarized INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE
);

-- File operations log - tracks all file-related operations
CREATE TABLE IF NOT EXISTS file_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('read', 'edit', 'test', 'deploy', 'stage', 'delete', 'copy', 'move')),
    file_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'success', 'failed', 'skipped')),
    details JSON,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE
);

-- Sandbox state - manages file editing workflow
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
    FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE,
    UNIQUE(session_id, file_path)
);

-- Settings table - stores user preferences and configuration
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- RAG memory - stores vector embeddings metadata
CREATE TABLE IF NOT EXISTS rag_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    document_id TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE SET NULL
);

-- Vault secrets metadata - tracks secrets from HashiCorp Vault
CREATE TABLE IF NOT EXISTS vault_secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    secret_path TEXT UNIQUE NOT NULL,
    last_rotation TIMESTAMP,
    lease_duration INTEGER,
    next_refresh TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_file_ops_session ON file_operations(session_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_file_ops_type ON file_operations(operation_type);
CREATE INDEX IF NOT EXISTS idx_sandbox_session ON sandbox_state(session_id, file_path);
CREATE INDEX IF NOT EXISTS idx_sandbox_approved ON sandbox_state(approved);
CREATE INDEX IF NOT EXISTS idx_conversations_interface ON conversations(interface);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_session ON rag_memory(session_id);
CREATE INDEX IF NOT EXISTS idx_vault_refresh ON vault_secrets(next_refresh);

-- Triggers for automatic timestamp updates
CREATE TRIGGER IF NOT EXISTS update_conversation_timestamp 
AFTER INSERT ON messages
BEGIN
    UPDATE conversations 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE session_id = NEW.session_id;
END;

CREATE TRIGGER IF NOT EXISTS update_settings_timestamp
AFTER UPDATE ON settings
BEGIN
    UPDATE settings 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE key = NEW.key;
END;

-- Views for convenient querying
CREATE VIEW IF NOT EXISTS recent_sessions AS
SELECT 
    c.session_id,
    c.interface,
    c.chat_id,
    c.created_at,
    c.updated_at,
    COUNT(m.id) as message_count,
    SUM(m.tokens) as total_tokens
FROM conversations c
LEFT JOIN messages m ON c.session_id = m.session_id
GROUP BY c.session_id
ORDER BY c.updated_at DESC;

CREATE VIEW IF NOT EXISTS sandbox_summary AS
SELECT 
    s.session_id,
    COUNT(*) as files_in_sandbox,
    SUM(CASE WHEN s.modified_content IS NOT NULL THEN 1 ELSE 0 END) as modified_files,
    SUM(CASE WHEN s.approved = 1 THEN 1 ELSE 0 END) as approved_files,
    MAX(s.timestamp) as last_activity
FROM sandbox_state s
GROUP BY s.session_id;
