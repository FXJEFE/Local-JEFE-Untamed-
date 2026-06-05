#!/usr/bin/env python3
"""
vm_manager.py — no-op stub for autonomous_security_toolkit compatibility.

Real VM management (VirtualBox/Hyper-V/WSL2) can be wired up here later.
Provides the minimal interface that autonomous_security_toolkit expects.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class VMState(str, Enum):
    RUNNING  = "running"
    STOPPED  = "stopped"
    PAUSED   = "paused"
    UNKNOWN  = "unknown"


class VMProvider(str, Enum):
    VIRTUALBOX = "virtualbox"
    HYPER_V    = "hyper-v"
    WSL2       = "wsl2"
    STUB       = "stub"


@dataclass
class VMConfig:
    name: str = "larry-vm"
    provider: VMProvider = VMProvider.STUB
    memory_mb: int = 2048
    cpus: int = 2
    disk_gb: int = 20
    os_type: str = "linux"
    network: str = "nat"


@dataclass
class VMInfo:
    name: str
    state: VMState = VMState.UNKNOWN
    ip: Optional[str] = None
    os_type: str = "unknown"
    provider: VMProvider = VMProvider.STUB


class VMManager:
    """Stub VM manager — no hypervisor integration yet."""

    def list_vms(self) -> List[VMInfo]:
        return []

    def create_vm(self, config: VMConfig) -> Tuple[bool, str]:
        return False, "VM manager stub — no hypervisor configured"

    def start_vm(self, name: str) -> Tuple[bool, str]:
        return False, "VM manager stub"

    def stop_vm(self, name: str) -> Tuple[bool, str]:
        return False, "VM manager stub"

    def delete_vm(self, name: str) -> Tuple[bool, str]:
        return False, "VM manager stub"

    def get_vm_status(self, name: str) -> Optional[VMInfo]:
        return None

    def create_snapshot(self, name: str, snapshot_name: str) -> Tuple[bool, str]:
        return False, "VM manager stub"

    # ------------------------------------------------------------------
    # Additional methods expected by autonomous_security_toolkit.py
    # ------------------------------------------------------------------
    def generate_report(self) -> str:
        """Generate a simple VM status report (stub)."""
        return "VM Report (stub): No hypervisor configured. List/create/start/stop operations are no-ops."

    def get_vm(self, name: str) -> Optional[VMInfo]:
        """Alias / compatibility for get_vm_status used in toolkit."""
        return self.get_vm_status(name)

    def restart_vm(self, name: str, **kwargs) -> Tuple[bool, str]:
        return False, "VM manager stub — restart not available in stub mode"

    def get_vm_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Extra compatibility helper."""
        return None
