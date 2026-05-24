#!/usr/bin/env python3
"""
Build script for Locked/Encrypted version of Larry G-Force Agent.

This creates a hardened, single-file executable using PyInstaller + PyArmor.

Requirements (will be installed automatically):
    pip install pyinstaller pyarmor

Usage:
    python build_locked.py

Output:
    GITHUB\dist\LarryGForce-Locked\LarryGForce.exe   (protected)
    Plus a user_config.json template next to it.

Important:
- User config is read from an external JSON file so it works for multiple PCs/accounts.
- The source code is obfuscated and encrypted.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

def main():
    print("=== Building Locked Larry G-Force Executable ===")

    # 1. Install build tools
    print("[1/4] Installing PyInstaller and PyArmor...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "pyarmor"])

    # 2. Obfuscate with PyArmor (protects the code)
    print("[2/4] Obfuscating source with PyArmor...")
    obfuscated_dir = ROOT / "obfuscated"
    if obfuscated_dir.exists():
        import shutil
        shutil.rmtree(obfuscated_dir)
    subprocess.check_call([
        sys.executable, "-m", "PyArmor", "gen",
        "--output", str(obfuscated_dir),
        str(ROOT / "src" / "agent_v2.py")
    ])

    # 3. Build with PyInstaller (single file exe)
    print("[3/4] Building single-file executable with PyInstaller...")
    dist_dir = ROOT / "dist" / "LarryGForce-Locked"
    dist_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "LarryGForce",
        "--distpath", str(dist_dir),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{ROOT / 'config'};config",
        str(obfuscated_dir / "agent_v2.py")
    ]
    subprocess.check_call(cmd)

    # 4. Create external user config template
    print("[4/4] Creating external user_config.json template...")
    config_template = {
        "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN_HERE",
        "allowed_chat_ids": [123456789],
        "brave_api_key": "YOUR_BRAVE_API_KEY",
        "github_token": "YOUR_GITHUB_TOKEN",
        "default_model": "dolphin-mixtral:8x7b",
        "ollama_host": "http://127.0.0.1:11434"
    }
    import json
    with open(dist_dir / "user_config.json", "w", encoding="utf-8") as f:
        json.dump(config_template, f, indent=2)

    print("\n✅ Build complete!")
    print(f"Locked executable is at: {dist_dir / 'LarryGForce.exe'}")
    print("Edit user_config.json next to the .exe for different PCs/accounts.")
    print("The source code inside the exe is protected and cannot be easily read.")

if __name__ == "__main__":
    main()
