# Local Larry - Unified Context Management System

![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

**Production-grade AI agent with unified context management, cross-platform file operations, and HashiCorp Vault integration**

## Overview

Local Larry is a sophisticated AI agent system built for production environments where security and reliability are paramount. The system features unified context management between CLI and Telegram interfaces, a comprehensive sandbox workflow for safe file operations, and integrated HashiCorp Vault support for secrets management.

### Key Features

The system is architected around several core capabilities. The unified context management provides a single SQLite database that tracks conversations across both CLI and Telegram interfaces, with automatic context summarization when approaching token limits and cross-session persistence enabling seamless switching between interfaces.

The sandbox workflow system ensures safe file operations through a structured process of staging, editing, testing, and deploying changes with automatic backup creation before any production deployments. The system supports automated testing of Python files before deployment and maintains version tracking using content hashes for integrity verification.

Hardware optimization is achieved through predefined profiles tailored for 8GB VRAM and 64GB DDR5 RAM configurations, with persistent user preferences and intelligent task-based auto-selection when preferences are not explicitly set.

Cross-platform compatibility is ensured through comprehensive path handling that works consistently across Windows, Linux, and macOS environments, with automatic long path support for Windows exceeding 260 characters and proper handling of symbolic links and case-sensitive filesystems.

Security integration with HashiCorp Vault provides centralized secrets management, with automatic secret rotation support, lease-based credential management, and Vault Agent sidecar pattern for containerized deployments.

## Architecture

The system is composed of several interconnected components working together to provide a cohesive experience. At the foundation level, the unified context manager handles all conversation state and history using SQLite for persistent storage. It integrates with the token manager for accurate token counting and implements automatic summarization when context limits are approached.

The hardware profile manager sits above the foundation, managing performance profiles optimized for your specific hardware configuration. It stores user preferences persistently and provides task-based automatic profile selection.

The sandbox manager operates alongside the context system, managing isolated file editing environments with integrated testing workflows. It handles backup creation and restoration, tracks changes using content hashes, and maintains approval workflows for production deployments.

Supporting these core components are the cross-platform path manager ensuring consistent file operations across all platforms, the token manager providing accurate token counting with tiktoken integration and content-aware approximation fallback, and the safe code executor enabling isolated Python code execution with static analysis capabilities.

## Installation

Begin by cloning the repository and setting up your Python environment. Create a virtual environment and activate it, then install the production dependencies. After the basic setup, run the unified system initialization script which will create necessary directories, initialize the database schema, configure environment variables, and validate your Ollama installation.

```bash
git clone https://github.com/yourusername/larry-agent.git
cd larry-agent

python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

pip install -r requirements-production.txt
python setup_unified.py
```

### HashiCorp Vault Integration (Optional)

For production deployments requiring secrets management, you can integrate HashiCorp Vault. First ensure Vault is running and accessible, then enable the appropriate authentication method. For Docker Compose deployments, use AppRole authentication. For Kubernetes deployments, use the Kubernetes authentication method. Configure the Vault Agent with your authentication details and secret paths, then start the agent which will automatically fetch and inject secrets into your environment files.

## Quick Start

### CLI Interface

Launch the CLI agent and begin interacting with it. You can set your preferred hardware profile, stage files for editing in the sandbox, make changes and test them, and deploy approved changes to production.

```bash
python agent_v2.py

# In the CLI:
>> /profile ULTRA_CONTEXT
>> /stage ./myproject/app.py
>> Review and suggest improvements to this file
>> /test ./myproject/app.py
>> /deploy ./myproject/app.py
```

### Telegram Bot

Configure your Telegram bot token in the environment file, start the bot service, and use the same commands through Telegram for remote access to all agent capabilities.

```bash
# Configure in .env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_ALLOWED_CHAT_IDS=your_chat_id

python telegram_bot.py
```

## Core Components

### Unified Context Manager

The unified context manager provides the backbone for conversation management across all interfaces. It maintains session state in a SQLite database, automatically summarizes conversations when approaching token limits, enables cross-interface session sharing, and supports conversation export to JSON format for archival purposes.

When you create a session, the manager generates a unique session identifier and tracks the interface type (CLI, Telegram, or API). Messages are stored with accurate token counts, role information, and optional metadata. The system monitors context usage and triggers automatic summarization when reaching 75% of the token limit by default.

### Hardware Profiles

Four predefined profiles are optimized for systems with 8GB VRAM and 64GB DDR5 RAM. The SPEED profile provides fast responses with 16K context using full VRAM. The BALANCED profile offers 32K context with mixed GPU and RAM usage. The ACCURACY profile delivers 65K context optimized for detailed analysis. The ULTRA_CONTEXT profile provides 131K context for massive file analysis using minimal GPU and maximum RAM.

Users can set explicit preferences that persist across sessions, or allow the system to automatically select profiles based on task type and query complexity.

### Sandbox Workflow

The sandbox system implements a rigorous workflow for safe file operations. When you stage a file, the system creates a backup and stores the original content with a content hash. Editing occurs in an isolated sandbox directory without affecting production files. Testing executes automated checks including syntax validation, static analysis, and optional execution tests. Upon approval, the system creates a timestamped backup and deploys changes to the original location.

All operations are logged in the database for audit purposes, and you can discard changes at any point before deployment.

### Cross-Platform Support

The path manager ensures consistent behavior across operating systems through several mechanisms. It normalizes path separators automatically, prevents path traversal attacks through validation, handles long paths on Windows using the extended-length prefix, and respects platform-specific features like case sensitivity and symbolic links.

## Configuration

### Environment Variables

Create a `.env` file in the project root with your configuration settings. Required variables include the Ollama host URL and optional Telegram bot credentials. For HashiCorp Vault integration, specify the Vault address and authentication method. Database configuration allows choosing between SQLite and PostgreSQL for the RAG backend.

```env
# Core Configuration
OLLAMA_HOST=http://localhost:11434

# Telegram (Optional)
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321

# HashiCorp Vault (Optional)
VAULT_ADDR=https://vault.example.com:8200
VAULT_ROLE_ID=your_role_id
VAULT_SECRET_ID=your_secret_id

# Database
RAG_BACKEND=chroma  # or 'postgres'
DATABASE_PATH=./data/unified_context.db
```

### Hardware Profile Configuration

You can customize profiles by editing `hardware_profiles.py` to match your specific hardware configuration. Adjust context sizes based on available RAM, modify GPU layer counts according to VRAM capacity, and tune thread counts for your CPU core count.

## Command Reference

### Context Management Commands

The profile command allows viewing current profile settings or switching between SPEED, BALANCED, ACCURACY, and ULTRA_CONTEXT profiles. The context command displays current usage statistics including message count, token usage, and percentage of limit used. The sessions command lists recent sessions with activity timestamps. The clear command removes all messages from the current session while preserving the session record.

### Sandbox Operations Commands

The sandbox command shows the status of all staged files including modification status, test results, and approval state. The stage command copies a file into the sandbox for safe editing. The test command runs automated validation and testing on sandbox files. The deploy command approves and deploys changes to production with automatic backup creation. The discard command removes files from sandbox and abandons changes.

### File Operations Commands

Standard file operations are supported through the file browser integration, including listing directories, viewing file contents, editing files through the sandbox workflow, searching for files by pattern, and searching within file contents.

## Docker Compose Deployment

For containerized deployments, use the provided Docker Compose configuration. This includes Ollama service with GPU support, Larry agent service with mounted volumes, and HashiCorp Vault service with initialization scripts. Vault Agent runs as a sidecar fetching secrets and rendering them to environment files for the agent service.

The compose file provides persistent volumes for models, data, and sandbox files, with automatic restart policies for production use.

## Kubernetes Deployment

Kubernetes manifests are provided in the `k8s/` directory with base configurations and overlays for development and production environments. The deployment includes StatefulSet for Ollama with GPU node affinity, Deployment for Larry agent with multiple replicas, Vault Agent as init container injecting secrets, ConfigMaps for application configuration, Secrets for sensitive credentials, PersistentVolumeClaims for data persistence, Services for internal communication, and Ingress for external access.

Deploy using Kustomize overlays for environment-specific configurations, choosing between development settings with reduced resources or production settings with autoscaling and GPU support.

## Security Considerations

The system implements multiple security layers. File operations are restricted to configured base directories with validation preventing path traversal attacks. The sandbox environment provides isolated editing and testing before production deployment. HashiCorp Vault centralizes secrets management with automatic rotation support. All file operations maintain audit logs in the database. Backups are created automatically before any destructive operations.

## Troubleshooting

Common issues and their resolutions include database connectivity problems which can be resolved by checking file permissions and verifying the schema is initialized. Context not persisting across sessions indicates the database path is not correctly configured or the session was not properly saved. Sandbox tests failing may require verifying SafeCodeExecutor is available and checking test output in the database. Cross-platform path issues can be debugged using the path normalization test utilities. Vault secrets not loading require checking Vault Agent logs and verifying authentication credentials.

## Development

For local development, install development dependencies and run the test suite. The test suite covers context management functionality, sandbox workflow operations, hardware profile management, token counting accuracy, and cross-platform path operations.

## Performance Optimization

The system is optimized for your hardware configuration with several tuning options. Use SPEED profile for quick interactions requiring minimal context. Switch to ACCURACY or ULTRA_CONTEXT for large file analysis and comprehensive code review. Clear old sessions periodically to maintain database performance. Stage only files actively being edited to minimize sandbox overhead. Use token-aware message retrieval for efficient context management.

## Future Enhancements

Planned improvements include enhanced RAG capabilities with semantic search, multi-user support with separate sandboxes per user, plugin architecture for custom tools and integrations, advanced testing frameworks beyond basic Python validation, and distributed deployment support for high-availability configurations.

## Contributing

Contributions are welcome through GitHub pull requests. Please ensure all tests pass before submitting, follow the existing code style and documentation standards, and add tests for new functionality.

## License

This project is licensed under the MIT License. See the LICENSE file for full details.

## Support

For issues and questions, use the GitHub issue tracker. For discussions and feature requests, use GitHub Discussions. For security vulnerabilities, contact the maintainers privately.
