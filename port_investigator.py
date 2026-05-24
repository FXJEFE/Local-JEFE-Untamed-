#!/usr/bin/env python3
"""
Port Investigator — Deep Connection Intelligence for Larry G-Force
====================================================================
Enriches raw port/connection data with:
  - Process info (name, PID, cmdline, user, uptime)
  - Connection duration (estimated from /proc)
  - Data transfer (bytes sent/received per-process)
  - Remote IP geolocation (ip-api.com — free, no key)
  - Reverse DNS hostnames
  - Connection state & socket details

Resource budget: ~0% VRAM, <1% CPU, <5MB RAM, minimal network
Dependencies: psutil (already installed), requests (already installed)
"""

import os
import json
import socket
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
from functools import lru_cache

import psutil

# Robust path bootstrap (works from Windows, WSL, or any cwd)
try:
    import larry_paths
    larry_paths.bootstrap(chdir=True, add_to_sys_path=True)
except Exception:
    pass  # Fallback to __file__ based paths below

log = logging.getLogger("port_investigator")

# ── Geolocation Cache (avoids hammering the API) ────────────────
_GEO_CACHE: Dict[str, dict] = {}
_GEO_CACHE_TTL = 3600  # 1 hour
_GEO_CACHE_TS: Dict[str, float] = {}

# Private/reserved IP ranges — skip geolocation for these
_PRIVATE_PREFIXES = (
    "127.", "10.", "192.168.", "0.0.0.0", "::1", "::", "fe80:",
    "169.254.", "100.64.",  # CGNAT
)

CACHE_FILE = Path(__file__).parent / "logs" / "geo_cache.json"


def _is_private(ip: str) -> bool:
    """Check if IP is private/reserved (no point geolocating)."""
    return any(ip.startswith(p) for p in _PRIVATE_PREFIXES) or ip.startswith("172.") and (
        16 <= int(ip.split(".")[1]) <= 31 if "." in ip.split(
            "172.")[1][:3] else False
    )


def _load_geo_cache():
    """Load persistent geo cache from disk."""
    global _GEO_CACHE, _GEO_CACHE_TS
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            _GEO_CACHE = data.get("cache", {})
            _GEO_CACHE_TS = {k: v for k, v in data.get(
                "timestamps", {}).items()}
    except Exception:
        pass


def _save_geo_cache():
    """Persist geo cache to disk."""
    try:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "cache": _GEO_CACHE,
            "timestamps": _GEO_CACHE_TS,
        }, indent=2))
    except Exception:
        pass


# ── Geolocation (ip-api.com — free, batch endpoint) ─────────────

def geolocate_ips(ips: List[str]) -> Dict[str, dict]:
    """
    Batch geolocate IPs using ip-api.com (free, 45 req/min, 100 per batch).
    Returns {ip: {country, city, region, isp, org, as, lat, lon, ...}}
    """
    _load_geo_cache()
    now = time.time()
    results = {}
    to_lookup = []

    for ip in set(ips):
        if _is_private(ip):
            results[ip] = {"country": "Local",
                           "city": "localhost", "isp": "LAN", "org": "Private"}
            continue
        # Check cache
        if ip in _GEO_CACHE and now - _GEO_CACHE_TS.get(ip, 0) < _GEO_CACHE_TTL:
            results[ip] = _GEO_CACHE[ip]
        else:
            to_lookup.append(ip)

    # Batch API call (up to 100 IPs per request)
    if to_lookup:
        try:
            import requests
            # ip-api.com batch endpoint — free, no key needed
            batch = [{"query": ip, "fields": "status,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query"}
                     for ip in to_lookup[:100]]
            r = requests.post(
                "http://ip-api.com/batch?fields=status,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query",
                json=batch,
                timeout=10,
            )
            if r.status_code == 200:
                for entry in r.json():
                    ip = entry.get("query", "")
                    if entry.get("status") == "success":
                        geo = {
                            "country": entry.get("country", "?"),
                            "country_code": entry.get("countryCode", "?"),
                            "region": entry.get("regionName", "?"),
                            "city": entry.get("city", "?"),
                            "zip": entry.get("zip", ""),
                            "lat": entry.get("lat"),
                            "lon": entry.get("lon"),
                            "timezone": entry.get("timezone", ""),
                            "isp": entry.get("isp", "?"),
                            "org": entry.get("org", "?"),
                            "as_number": entry.get("as", ""),
                        }
                        results[ip] = geo
                        _GEO_CACHE[ip] = geo
                        _GEO_CACHE_TS[ip] = now
                    else:
                        results[ip] = {"country": "Unknown",
                                       "city": "?", "isp": "?"}
                _save_geo_cache()
        except Exception as e:
            log.warning(f"Geolocation batch failed: {e}")
            for ip in to_lookup:
                results[ip] = {"country": "Lookup failed",
                               "city": "?", "isp": "?"}

    return results


# ── Reverse DNS ──────────────────────────────────────────────────

def reverse_dns(ip: str, timeout: float = 1.0) -> str:
    """Reverse DNS lookup with timeout. Returns hostname or empty string."""
    if _is_private(ip):
        return "localhost" if ip.startswith("127.") else "LAN"
    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        hostname = socket.gethostbyaddr(ip)[0]
        socket.setdefaulttimeout(old_timeout)
        return hostname
    except (socket.herror, socket.gaierror, socket.timeout, OSError):
        return ""


# ── Process IO Stats ─────────────────────────────────────────────

def get_process_io(pid: int) -> Optional[Dict[str, int]]:
    """Get per-process IO stats from /proc (Linux only)."""
    try:
        io_file = Path(f"/proc/{pid}/io")
        if io_file.exists():
            data = {}
            for line in io_file.read_text().splitlines():
                key, val = line.split(":")
                data[key.strip()] = int(val.strip())
            return {
                "read_bytes": data.get("read_bytes", 0),
                "write_bytes": data.get("write_bytes", 0),
                "read_chars": data.get("rchar", 0),
                "write_chars": data.get("wchar", 0),
            }
    except (PermissionError, FileNotFoundError, ValueError):
        pass
    return None


def get_process_net_io(pid: int) -> Optional[Dict[str, int]]:
    """
    Estimate per-process network IO using /proc/net/netstat + process FDs.
    Falls back to overall process IO if unavailable.
    """
    try:
        proc = psutil.Process(pid)
        io = proc.io_counters()
        return {
            "read_bytes": io.read_bytes,
            "write_bytes": io.write_bytes,
            "read_count": io.read_count,
            "write_count": io.write_count,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
        return get_process_io(pid)


# ── Connection Duration from /proc/net/tcp ───────────────────────

def _parse_proc_net_tcp() -> Dict[str, dict]:
    """
    Parse /proc/net/tcp for socket timer info.
    Returns {inode: {local_addr, remote_addr, state, timer, ...}}
    """
    sockets = {}
    for proto_file in ["/proc/net/tcp", "/proc/net/tcp6"]:
        try:
            with open(proto_file) as f:
                next(f)  # skip header
                for line in f:
                    parts = line.split()
                    if len(parts) < 12:
                        continue
                    inode = parts[9]
                    sockets[inode] = {
                        "local": parts[1],
                        "remote": parts[2],
                        "state": parts[3],
                        "timer_active": parts[5],
                        "retransmit": parts[6],
                        "uid": parts[7],
                        "inode": inode,
                    }
        except (FileNotFoundError, PermissionError):
            pass
    return sockets


def get_process_start_time(pid: int) -> Optional[datetime]:
    """Get when a process started."""
    try:
        proc = psutil.Process(pid)
        return datetime.fromtimestamp(proc.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


# ── ss (Socket Statistics) — richer than netstat ─────────────────

def get_ss_data() -> List[dict]:
    """
    Use `ss -tnpi` for detailed socket info with process and timer data.
    Much richer than psutil alone.
    """
    try:
        result = subprocess.run(
            ["ss", "-tnpi", "--no-header"],
            capture_output=True, text=True, timeout=10,
        )
        connections = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            entry = {
                "state": parts[0],
                "recv_q": int(parts[1]) if parts[1].isdigit() else 0,
                "send_q": int(parts[2]) if parts[2].isdigit() else 0,
                "local": parts[3],
                "remote": parts[4],
            }
            # Extract process info if present
            rest = " ".join(parts[5:])
            if "pid=" in rest:
                import re
                pid_match = re.search(r'pid=(\d+)', rest)
                if pid_match:
                    entry["pid"] = int(pid_match.group(1))
                comm_match = re.search(r'"([^"]+)"', rest)
                if comm_match:
                    entry["process_name"] = comm_match.group(1)
            connections.append(entry)
        return connections
    except Exception as e:
        log.warning(f"ss command failed: {e}")
        return []


# ── Main Investigation Engine ────────────────────────────────────

def investigate_connections(
    include_listening: bool = True,
    include_established: bool = True,
    include_geo: bool = True,
    include_dns: bool = True,
    max_dns_lookups: int = 30,
) -> Dict[str, Any]:
    """
    Full investigation of all active network connections.

    Returns a rich dict with:
      - connections: list of enriched connection dicts
      - summary: aggregate stats
      - geo_map: {ip: geo_info}
      - by_process: connections grouped by process
      - by_country: connections grouped by country
      - listening_ports: detailed listening port info
      - timestamp: when the scan ran
    """
    start = time.time()

    # ── 1. Gather raw connections via psutil ─────────────────────
    all_conns = []
    remote_ips = set()

    for conn in psutil.net_connections(kind="inet"):
        entry = {
            "fd": conn.fd,
            "family": "IPv4" if conn.family.name == "AF_INET" else "IPv6",
            "type": "TCP" if conn.type.name == "SOCK_STREAM" else "UDP",
            "local_ip": conn.laddr.ip if conn.laddr else "",
            "local_port": conn.laddr.port if conn.laddr else 0,
            "remote_ip": conn.raddr.ip if conn.raddr else "",
            "remote_port": conn.raddr.port if conn.raddr else 0,
            "status": conn.status,
            "pid": conn.pid,
        }

        # Filter by type
        if entry["status"] == "LISTEN" and not include_listening:
            continue
        if entry["status"] == "ESTABLISHED" and not include_established:
            continue

        # ── 2. Enrich with process info ─────────────────────────
        if conn.pid:
            try:
                proc = psutil.Process(conn.pid)
                entry["process_name"] = proc.name()
                entry["process_exe"] = proc.exe()
                entry["process_cmdline"] = " ".join(
                    proc.cmdline()[:5])  # first 5 args
                entry["process_user"] = proc.username()
                entry["process_started"] = datetime.fromtimestamp(
                    proc.create_time()).isoformat()
                entry["process_uptime_sec"] = int(
                    time.time() - proc.create_time())
                entry["process_uptime_human"] = str(
                    timedelta(seconds=entry["process_uptime_sec"]))

                # CPU and memory of the owning process
                entry["process_cpu_pct"] = proc.cpu_percent(interval=0)
                entry["process_mem_mb"] = round(
                    proc.memory_info().rss / 1048576, 1)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                entry["process_name"] = "?"
                entry["process_exe"] = ""
        else:
            entry["process_name"] = "kernel/unknown"

        # ── 3. Per-process IO (data pulled/uploaded estimate) ───
        if conn.pid:
            io = get_process_net_io(conn.pid)
            if io:
                entry["io_read_bytes"] = io.get("read_bytes", 0)
                entry["io_write_bytes"] = io.get("write_bytes", 0)
                entry["io_read_human"] = _human_bytes(entry["io_read_bytes"])
                entry["io_write_human"] = _human_bytes(entry["io_write_bytes"])

        # Collect remote IPs for batch geolocation
        if entry["remote_ip"] and entry["remote_ip"] not in ("", "0.0.0.0", "::", "::1"):
            remote_ips.add(entry["remote_ip"])

        all_conns.append(entry)

    # ── 4. Batch geolocation ────────────────────────────────────
    geo_map = {}
    if include_geo and remote_ips:
        geo_map = geolocate_ips(list(remote_ips))
        # Attach geo to each connection
        for conn_entry in all_conns:
            rip = conn_entry.get("remote_ip", "")
            if rip in geo_map:
                conn_entry["geo"] = geo_map[rip]

    # ── 5. Reverse DNS (limited to save time) ───────────────────
    if include_dns:
        dns_done = 0
        for conn_entry in all_conns:
            if dns_done >= max_dns_lookups:
                break
            rip = conn_entry.get("remote_ip", "")
            if rip and not _is_private(rip):
                hostname = reverse_dns(rip)
                if hostname:
                    conn_entry["remote_hostname"] = hostname
                    dns_done += 1

    # ── 6. Aggregate & group ────────────────────────────────────
    by_process = defaultdict(list)
    by_country = defaultdict(list)
    by_state = defaultdict(int)

    for c in all_conns:
        pname = c.get("process_name", "unknown")
        by_process[pname].append(c)
        geo = c.get("geo", {})
        country = geo.get("country", "Unknown")
        if c["status"] != "LISTEN":
            by_country[country].append(c)
        by_state[c["status"]] += 1

    # Listening ports with full detail
    listening = [c for c in all_conns if c["status"] == "LISTEN"]
    established = [c for c in all_conns if c["status"] == "ESTABLISHED"]

    elapsed = round(time.time() - start, 2)

    return {
        "timestamp": datetime.now().isoformat(),
        "scan_time_sec": elapsed,
        "connections": all_conns,
        "summary": {
            "total": len(all_conns),
            "listening": len(listening),
            "established": len(established),
            "unique_remote_ips": len(remote_ips),
            "unique_processes": len(by_process),
            "by_state": dict(by_state),
            "countries_connected": len(by_country),
        },
        "listening_ports": listening,
        "established_connections": established,
        "geo_map": geo_map,
        "by_process": {k: len(v) for k, v in by_process.items()},
        "by_country": {k: len(v) for k, v in by_country.items()},
    }


def investigate_port(port: int) -> Dict[str, Any]:
    """
    Deep-dive investigation of a specific port.
    Returns everything we can find about who/what is using it.
    """
    results = {
        "port": port,
        "timestamp": datetime.now().isoformat(),
        "listeners": [],
        "connections": [],
    }

    for conn in psutil.net_connections(kind="inet"):
        is_match = False
        if conn.laddr and conn.laddr.port == port:
            is_match = True
        if conn.raddr and conn.raddr.port == port:
            is_match = True

        if not is_match:
            continue

        entry = _enrich_connection(conn)

        if conn.status == "LISTEN":
            results["listeners"].append(entry)
        else:
            results["connections"].append(entry)

    # Geolocation for all remote IPs on this port
    remote_ips = [c.get("remote_ip", "")
                  for c in results["connections"] if c.get("remote_ip")]
    if remote_ips:
        geo = geolocate_ips(remote_ips)
        for c in results["connections"]:
            rip = c.get("remote_ip", "")
            if rip in geo:
                c["geo"] = geo[rip]
                c["remote_hostname"] = reverse_dns(rip)

    # Try to identify the service by port number
    try:
        results["known_service"] = socket.getservbyport(port, "tcp")
    except OSError:
        results["known_service"] = None

    return results


def _enrich_connection(conn) -> dict:
    """Enrich a single psutil connection with process and IO details."""
    entry = {
        "local_ip": conn.laddr.ip if conn.laddr else "",
        "local_port": conn.laddr.port if conn.laddr else 0,
        "remote_ip": conn.raddr.ip if conn.raddr else "",
        "remote_port": conn.raddr.port if conn.raddr else 0,
        "status": conn.status,
        "pid": conn.pid,
    }

    if conn.pid:
        try:
            proc = psutil.Process(conn.pid)
            entry["process_name"] = proc.name()
            entry["process_exe"] = proc.exe()
            entry["process_cmdline"] = " ".join(proc.cmdline()[:5])
            entry["process_user"] = proc.username()
            entry["process_started"] = datetime.fromtimestamp(
                proc.create_time()).isoformat()
            entry["process_uptime_human"] = str(
                timedelta(seconds=int(time.time() - proc.create_time())))
            entry["process_cpu_pct"] = proc.cpu_percent(interval=0)
            entry["process_mem_mb"] = round(
                proc.memory_info().rss / 1048576, 1)

            io = get_process_net_io(conn.pid)
            if io:
                entry["io_read_bytes"] = io.get("read_bytes", 0)
                entry["io_write_bytes"] = io.get("write_bytes", 0)
                entry["io_read_human"] = _human_bytes(entry["io_read_bytes"])
                entry["io_write_human"] = _human_bytes(entry["io_write_bytes"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            entry["process_name"] = "?"

    return entry


# ── Formatted Output for CLI / Sentinel ──────────────────────────

def format_investigation_report(data: dict, verbose: bool = False) -> str:
    """Format investigation results for terminal or Telegram output."""
    lines = []
    summary = data.get("summary", {})

    lines.append(
        f"🔍 PORT INVESTIGATION REPORT — {data.get('timestamp', '')[:16]}")
    lines.append(f"   Scan time: {data.get('scan_time_sec', '?')}s")
    lines.append(f"   {summary.get('total', 0)} connections | "
                 f"{summary.get('listening', 0)} listening | "
                 f"{summary.get('established', 0)} established")
    lines.append(f"   {summary.get('unique_remote_ips', 0)} unique remote IPs | "
                 f"{summary.get('countries_connected', 0)} countries")
    lines.append("")

    # Top processes by connection count
    by_proc = data.get("by_process", {})
    if by_proc:
        lines.append("📊 TOP PROCESSES (by connection count):")
        for proc, count in sorted(by_proc.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"   {proc}: {count} connections")
        lines.append("")

    # Countries
    by_country = data.get("by_country", {})
    if by_country:
        lines.append("🌍 CONNECTIONS BY COUNTRY:")
        for country, count in sorted(by_country.items(), key=lambda x: -x[1])[:15]:
            lines.append(f"   {country}: {count}")
        lines.append("")

    # Listening ports detail
    if data.get("listening_ports") and verbose:
        lines.append("🎧 LISTENING PORTS:")
        for lp in sorted(data["listening_ports"], key=lambda x: x["local_port"]):
            lines.append(
                f"   :{lp['local_port']} — {lp.get('process_name', '?')} "
                f"(PID {lp.get('pid', '?')}) | "
                f"up {lp.get('process_uptime_human', '?')} | "
                f"mem {lp.get('process_mem_mb', '?')}MB"
            )
        lines.append("")

    # Established connections with geo (top 20)
    established = data.get("established_connections", [])
    if established and verbose:
        lines.append("🔗 ESTABLISHED CONNECTIONS (top 20):")
        for ec in established[:20]:
            geo = ec.get("geo", {})
            location = f"{geo.get('city', '?')}, {geo.get('country', '?')}" if geo else "?"
            hostname = ec.get("remote_hostname", "")
            host_str = f" ({hostname})" if hostname else ""
            lines.append(
                f"   {ec.get('process_name', '?'):15s} → "
                f"{ec['remote_ip']}:{ec['remote_port']}{host_str}\n"
                f"{'':19s}📍 {location} | ISP: {geo.get('isp', '?')}\n"
                f"{'':19s}⬇ {ec.get('io_read_human', '?')} ⬆ {ec.get('io_write_human', '?')} | "
                f"up {ec.get('process_uptime_human', '?')}"
            )
        lines.append("")

    return "\n".join(lines)


def format_telegram_report(data: dict) -> str:
    """Compact HTML report for Telegram."""
    s = data.get("summary", {})
    lines = [
        f"<b>🔍 PORT INVESTIGATION</b>",
        f"📊 {s.get('total', 0)} conns | {s.get('established', 0)} active | {s.get('listening', 0)} listening",
        f"🌍 {s.get('countries_connected', 0)} countries | {s.get('unique_remote_ips', 0)} unique IPs",
        "",
    ]

    # Top 5 countries
    by_country = data.get("by_country", {})
    if by_country:
        lines.append("<b>Countries:</b>")
        for country, count in sorted(by_country.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {country}: {count}")

    # Top 5 processes
    by_proc = data.get("by_process", {})
    if by_proc:
        lines.append("\n<b>Processes:</b>")
        for proc, count in sorted(by_proc.items(), key=lambda x: -x[1])[:5]:
            lines.append(f"  {proc}: {count}")

    return "\n".join(lines)


# ── Utilities ────────────────────────────────────────────────────

def _human_bytes(b: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(b) < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}PB"


# ── Dashboard API Endpoint (add to dashboard_hub.py) ────────────

def get_dashboard_data() -> dict:
    """
    Returns investigation data structured for the dashboard frontend.
    Call this from a Flask route.
    """
    data = investigate_connections(
        include_listening=True,
        include_established=True,
        include_geo=True,
        include_dns=True,
        max_dns_lookups=20,
    )
    return data


# ── CLI Entry Point ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Port Investigator")
    parser.add_argument("--port", type=int, help="Investigate a specific port")
    parser.add_argument("--verbose", "-v",
                        action="store_true", help="Show full details")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--no-geo", action="store_true",
                        help="Skip geolocation (faster)")
    parser.add_argument("--no-dns", action="store_true",
                        help="Skip reverse DNS (faster)")
    args = parser.parse_args()

    if args.port:
        data = investigate_port(args.port)
        if args.json:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(
                f"\n🔍 Deep investigation of port {args.port}:")
            print(
                f"Known service: {data.get('known_service', 'unknown')}")
            print(
                f"{len(data['listeners'])} listener(s), {len(data['connections'])} connection(s)")
            for l in data["listeners"]:
                print(
                    f"\n   🎧 LISTENER: {l.get('process_name', '?')} (PID {l.get('pid', '?')})")
                print(
                    f"exe: {l.get('process_exe', '?')}")
                print(
                    f"user: {l.get('process_user', '?')}")
                print(
                    f"uptime: {l.get('process_uptime_human', '?')}")
                print(
                    f"mem: {l.get('process_mem_mb', '?')}MB")
            for c in data["connections"]:
                geo = c.get("geo", {})
                print(
                    f"\n   🔗 {c['remote_ip']}:{c['remote_port']}")
                print(
                    f"hostname: {c.get('remote_hostname', '?')}")
                print(
                    f"location: {geo.get('city', '?')}, {geo.get('country', '?')}")
                print(
                    f"ISP: {geo.get('isp', '?')} | Org: {geo.get('org', '?')}")
                print(
                    f"process: {c.get('process_name', '?')} (PID {c.get('pid', '?')})")
                print(
                    f"data: ⬇ {c.get('io_read_human', '?')} ⬆ {c.get('io_write_human', '?')}")
    else:
        data = investigate_connections(
            include_geo=not args.no_geo,
            include_dns=not args.no_dns,
        )
        if args.json:
            print(json.dumps(data, indent=2, default=str))
        else:
            print(format_investigation_report(data, verbose=args.verbose))
