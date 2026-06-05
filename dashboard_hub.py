#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — COMMAND CENTRAL v3.0                              ║
║   Unified dashboard: AI Models · Network · Security · System        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, subprocess, threading, time, socket, logging
import webbrowser, shutil, psutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

try:
    from flask import Flask, jsonify, request, render_template_string
    from flask_cors import CORS
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "flask", "flask-cors", "-q"], check=True)
    from flask import Flask, jsonify, request, render_template_string
    from flask_cors import CORS

try:
    import requests as _req
except ImportError:
    _req = None

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from activity_stream import ActivityStream

# Pre-import security modules (no app reference yet)
try:
    from security_command_center import SecurityCommandCenter, register_security_routes
    from bash_script_runner import BashScriptRunner
    _sec_center = SecurityCommandCenter()
    _bash_runner = BashScriptRunner()
    _SEC_IMPORT_OK = True
    _SEC_IMPORT_ERR = None
except Exception as _ste:
    _sec_center = None
    _bash_runner = None
    _SEC_IMPORT_OK = False
    _SEC_IMPORT_ERR = _ste

PROJECT_ROOT = Path(__file__).parent.resolve()
DASHBOARD_PORT = 3777
HOST = "127.0.0.1"

app = Flask(__name__)
CORS(app)

# Register security routes now that app exists
if _SEC_IMPORT_OK:
    try:
        register_security_routes(app, _sec_center)
        SECURITY_TOOLS_AVAILABLE = True
    except Exception as _ste2:
        SECURITY_TOOLS_AVAILABLE = False
        logger.warning(f"Security route registration failed: {_ste2}")
else:
    SECURITY_TOOLS_AVAILABLE = False
    if _SEC_IMPORT_ERR:
        logger.warning(f"Security tools not available: {_SEC_IMPORT_ERR}")

# Hide server version banner from HTTP responses
import werkzeug.serving
werkzeug.serving.WSGIRequestHandler.server_version = ""
werkzeug.serving.WSGIRequestHandler.sys_version = ""
running_services: Dict[str, subprocess.Popen] = {}

AVAILABLE_SERVICES = {
    "agent_larry":   {"name": "Larry Agent CLI",     "script": "agent_v2.py",                "port": None, "icon": "🤖", "cwd": None, "terminal": True},
    "telegram_bot":  {"name": "Telegram Bot",        "script": "telegram_bot.py",            "port": None, "icon": "✈️",  "cwd": None},
    "xgboost_api":   {"name": "XGBoost API",         "script": "xgboost_predictions_api.py", "port": 5562, "icon": "📈", "cwd": None},
    "ai_server":     {"name": "AI Server",           "script": "ai_servernwew.py",           "port": 5000, "icon": "🧠", "cwd": None},
    "fxjefe_main":   {"name": "FXJEFE Trading",      "script": "fxjefe_main_server.py",      "port": 8080, "icon": "💹", "cwd": None},
    "crypto_ai":     {"name": "Crypto AI Server",    "script": "crypto_ai_server.py",        "port": 8081, "icon": "🔮", "cwd": str(Path.home() / "cryptobot")},
    "crypto_bot":    {"name": "Crypto Bot (Binance)","script": "crypto_bot.py",              "port": None, "icon": "💰", "cwd": str(Path.home() / "cryptobot"), "args": ["--live"]},
    "security_sentinel": {"name": "Security Sentinel","script": "security_sentinel.py",      "port": None, "icon": "🛡️", "cwd": None},
}

# DB folder for prompts/scripts/apps
DB_ROOT = PROJECT_ROOT / "db"
DB_ROOT.mkdir(exist_ok=True)
for sub in ("prompts", "scripts", "apps", "chats"):
    (DB_ROOT / sub).mkdir(exist_ok=True)

# Friendly temperature sensor names
TEMP_LABELS = {
    "k10temp": "CPU", "coretemp": "CPU", "zenpower": "CPU",
    "amdgpu": "GPU", "nouveau": "GPU", "nvidia": "GPU",
    "nvme": "NVMe SSD", "iwlwifi_1": "WiFi Card",
    "acpitz": "Motherboard", "pch": "Chipset PCH",
    "it8686": "Motherboard VRM", "nct6775": "Motherboard Fan",
}

# ═══════════════════════════════════════════════════════════════════════
# SYSTEM DATA COLLECTORS
# ═══════════════════════════════════════════════════════════════════════

def get_system_health():
    try:
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        temps = {}
        try:
            t = psutil.sensors_temperatures()
            if t:
                for name, entries in t.items():
                    if entries:
                        temps[name] = round(entries[0].current, 1)
        except Exception:
            pass
        net = psutil.net_io_counters()
        boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M")
        uptime_s = int(time.time() - psutil.boot_time())
        h, r = divmod(uptime_s, 3600)
        m = r // 60
        return {
            "cpu_percent": cpu,
            "cpu_cores": psutil.cpu_count(),
            "cpu_freq": round(psutil.cpu_freq().current) if psutil.cpu_freq() else 0,
            "mem_percent": mem.percent,
            "mem_used_gb": round(mem.used / 1e9, 1),
            "mem_total_gb": round(mem.total / 1e9, 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / 1e9, 1),
            "disk_total_gb": round(disk.total / 1e9, 1),
            "net_sent_mb": round(net.bytes_sent / 1e6, 1),
            "net_recv_mb": round(net.bytes_recv / 1e6, 1),
            "temperatures": temps,
            "boot_time": boot_time,
            "uptime": f"{h}h {m}m",
            "processes": len(psutil.pids()),
        }
    except Exception as e:
        return {"error": str(e)}

def get_gpu_info():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw",
             "--format=csv,noheader,nounits"],
            timeout=5, text=True, stderr=subprocess.DEVNULL
        )
        lines = [l.strip() for l in out.strip().splitlines() if l.strip()]
        gpus = []
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                gpus.append({
                    "name": parts[0],
                    "temp": parts[1],
                    "util": parts[2],
                    "mem_used": parts[3],
                    "mem_total": parts[4],
                    "power": parts[5] if parts[5] != "[N/A]" else "N/A",
                })
        return gpus
    except Exception:
        return []

def get_ollama_models():
    if _req is None:
        return []
    try:
        r = _req.get("http://localhost:11434/api/tags", timeout=3)
        models = r.json().get("models", [])
        result = []
        for m in models:
            size_gb = round(m.get("size", 0) / 1e9, 1)
            result.append({"name": m["name"], "size_gb": size_gb,
                           "modified": m.get("modified_at", "")[:10]})
        return result
    except Exception:
        return []

def get_ollama_running():
    """Which model is currently loaded in VRAM."""
    if _req is None:
        return []
    try:
        r = _req.get("http://localhost:11434/api/ps", timeout=3)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []

def get_public_ip():
    """Get public IP address (goes through VPN if active)."""
    if _req is None:
        return "--"
    try:
        r = _req.get("https://api.ipify.org?format=json", timeout=5)
        return r.json().get("ip", "--")
    except Exception:
        return "--"

def get_network_info():
    info = {"interfaces": [], "connections": 0, "listening_ports": [], "active_connections": [], "public_ip": "--"}
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            stats = psutil.net_if_stats().get(iface)
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    info["interfaces"].append({
                        "name": iface,
                        "ip": addr.address,
                        "netmask": addr.netmask,
                        "up": stats.isup if stats else False,
                        "speed": stats.speed if stats else 0,
                    })
    except Exception:
        pass
    try:
        conns = psutil.net_connections(kind="inet")
        info["connections"] = len(conns)
        listening = set()
        active = []
        for c in conns:
            if c.status == "LISTEN" and c.laddr:
                listening.add(c.laddr.port)
            elif c.status == "ESTABLISHED" and c.raddr:
                # Get process name
                pname = "--"
                try:
                    if c.pid:
                        pname = psutil.Process(c.pid).name()[:20]
                except Exception:
                    pass
                active.append({
                    "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "--",
                    "remote": f"{c.raddr.ip}:{c.raddr.port}",
                    "pid": c.pid or "--",
                    "process": pname,
                    "status": c.status,
                })
        info["listening_ports"] = sorted(listening)[:30]
        info["active_connections"] = active[:50]  # cap at 50
    except Exception:
        pass
    # Public IP (cached for 60s to avoid hammering the API)
    info["public_ip"] = get_public_ip()
    return info

def get_vpn_status():
    """Detect common VPN interfaces."""
    vpn_ifaces = []
    try:
        for iface in psutil.net_if_addrs().keys():
            low = iface.lower()
            if any(x in low for x in ["tun", "tap", "wg", "vpn", "proton", "nordlynx", "mullvad", "ovpn"]):
                stats = psutil.net_if_stats().get(iface)
                vpn_ifaces.append({"name": iface, "up": stats.isup if stats else False})
    except Exception:
        pass
    return vpn_ifaces

def get_telegram_status():
    """Check if telegram_bot.py is running."""
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
            if "telegram_bot.py" in cmd:
                return {"running": True, "pid": proc.pid}
        except Exception:
            pass
    return {"running": False, "pid": None}

def run_nmap_quick(target: str = "10.0.0.0/24"):
    """Fast nmap ping sweep. Requires nmap installed."""
    if not shutil.which("nmap"):
        return {"error": "nmap not installed. Run: sudo apt install nmap"}
    try:
        out = subprocess.check_output(
            ["nmap", "-sn", "-T4", target],
            timeout=45, text=True, stderr=subprocess.DEVNULL
        )
        hosts = []
        for line in out.splitlines():
            if "Nmap scan report" in line:
                parts = line.split()
                ip = parts[-1].strip("()")
                hostname = parts[-2] if len(parts) > 5 else ip
                hosts.append({"ip": ip, "hostname": hostname})
        return {"target": target, "hosts": hosts, "count": len(hosts)}
    except subprocess.TimeoutExpired:
        return {"error": "Scan timed out"}
    except Exception as e:
        return {"error": str(e)}

def run_port_scan(target: str = "localhost", ports: str = "1-1024"):
    if not shutil.which("nmap"):
        return {"error": "nmap not installed. Run: sudo apt install nmap"}
    try:
        # Use -sT (TCP connect) for wide ranges, -sV (version detect) only for narrow ranges
        # Parse port range to decide scan type
        use_version = True
        timeout_val = 90
        try:
            if "-" in ports:
                lo, hi = ports.split("-", 1)
                span = int(hi) - int(lo)
                if span > 5000:
                    use_version = False
                    timeout_val = 120
        except ValueError:
            pass
        # Use -sT (TCP connect) — works without root. Add -sV for version detection on small ranges.
        cmd = ["nmap", "-sT", "--open", "-T4", "-p", ports, target]
        if use_version:
            cmd.insert(2, "-sV")
        out = subprocess.check_output(
            cmd, timeout=timeout_val, text=True, stderr=subprocess.DEVNULL
        )
        open_ports = []
        for line in out.splitlines():
            if "/tcp" in line and "open" in line:
                parts = line.split()
                port = parts[0].split("/")[0]
                state = parts[1]
                service = parts[2] if len(parts) > 2 else ""
                version = " ".join(parts[3:]) if len(parts) > 3 else ""
                open_ports.append({"port": int(port), "state": state, "service": service, "version": version[:40]})
        return {"target": target, "ports": ports, "open": open_ports, "count": len(open_ports)}
    except subprocess.TimeoutExpired:
        return {"error": "Scan timed out (try a smaller port range)"}
    except Exception as e:
        return {"error": str(e)}

def get_top_processes(n=10):
    # Normalize CPU% to % of the whole system (like Task Manager); psutil sums
    # across all logical cores, so a busy process can read >100% otherwise.
    ncpu = psutil.cpu_count() or 1
    candidates = [p for p in psutil.process_iter(["pid","name","cpu_percent","memory_percent","status"])
                  if p.info.get("pid") and (p.info.get("name") or "") != "System Idle Process"]
    procs = []
    for p in sorted(candidates, key=lambda x: x.info.get("cpu_percent") or 0, reverse=True)[:n]:
        procs.append({
            "pid": p.info["pid"],
            "name": (p.info.get("name") or "?")[:20],
            "cpu": round((p.info.get("cpu_percent") or 0) / ncpu, 1),
            "mem": round(p.info.get("memory_percent") or 0, 1),
            "status": p.info.get("status", ""),
        })
    return procs

def get_listening_services():
    """Get listening services with PID and process name."""
    services = []
    try:
        conns = psutil.net_connections(kind="inet")
        seen_ports = set()
        for c in conns:
            if c.status == "LISTEN" and c.laddr and c.laddr.port not in seen_ports:
                seen_ports.add(c.laddr.port)
                pname = "--"
                try:
                    if c.pid:
                        pname = psutil.Process(c.pid).name()[:25]
                except Exception:
                    pass
                services.append({
                    "port": c.laddr.port,
                    "pid": c.pid or "--",
                    "process": pname,
                    "ip": c.laddr.ip,
                })
    except Exception:
        pass
    return sorted(services, key=lambda x: x["port"])

# ═══════════════════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/health")
def api_health():
    return jsonify({"system": get_system_health(), "gpu": get_gpu_info(),
                    "processes": get_top_processes()})

@app.route("/api/ollama")
def api_ollama():
    return jsonify({"models": get_ollama_models(), "running": get_ollama_running()})

@app.route("/api/network")
def api_network():
    return jsonify({**get_network_info(), "vpn": get_vpn_status(),
                    "telegram": get_telegram_status()})

@app.route("/api/services/status")
def api_services_status():
    out = {}
    for sid, sinfo in AVAILABLE_SERVICES.items():
        proc = running_services.get(sid)
        out[sid] = {
            "running": proc is not None and proc.poll() is None,
            "port": sinfo["port"],
            "name": sinfo["name"],
            "icon": sinfo["icon"],
        }
    return jsonify({"services": out})

@app.route("/api/services/<sid>/start", methods=["POST"])
def api_start_service(sid):
    if sid not in AVAILABLE_SERVICES:
        return jsonify({"success": False, "error": "Unknown service"}), 404
    sinfo = AVAILABLE_SERVICES[sid]
    proc = running_services.get(sid)
    if proc and proc.poll() is None:
        return jsonify({"success": False, "error": "Already running"}), 400
    work_dir = Path(sinfo["cwd"]) if sinfo.get("cwd") else PROJECT_ROOT
    script = work_dir / sinfo["script"]
    if not script.exists():
        return jsonify({"success": False, "error": f"Script not found: {script}"}), 404
    try:
        # Use the venv python for cryptobot services
        if sinfo.get("cwd") and "cryptobot" in str(sinfo["cwd"]):
            venv_py = Path(sinfo["cwd"]) / "venv" / "bin" / "python"
            py = str(venv_py) if venv_py.exists() else sys.executable
        else:
            py = sys.executable
        env = os.environ.copy()

        # Interactive services need a real terminal window
        if sinfo.get("terminal"):
            # Try gnome-terminal, then xterm as fallback
            term_bin = shutil.which("gnome-terminal") or shutil.which("xfce4-terminal") or shutil.which("xterm")
            if not term_bin:
                return jsonify({"success": False, "error": "No terminal emulator found (gnome-terminal/xterm)"}), 500
            title = sinfo["name"]
            # Use the py3 launcher if available (activates venv312)
            py3_launcher = PROJECT_ROOT.parent / "py3"
            if py3_launcher.exists():
                run_cmd = [str(py3_launcher), str(script)]
            else:
                run_cmd = [py, str(script)]
            if "gnome-terminal" in term_bin:
                p = subprocess.Popen(
                    [term_bin, "--title", title, "--"] + run_cmd,
                    cwd=str(work_dir), env=env
                )
            elif "xfce4-terminal" in term_bin:
                p = subprocess.Popen(
                    [term_bin, "--title", title, "-e", " ".join(run_cmd)],
                    cwd=str(work_dir), env=env
                )
            else:
                p = subprocess.Popen(
                    [term_bin, "-title", title, "-e", " ".join(run_cmd)],
                    cwd=str(work_dir), env=env
                )
            running_services[sid] = p
            return jsonify({"success": True, "message": f"{sinfo['name']} opened in terminal (PID {p.pid})"})

        # Background/daemon services
        log_dir = work_dir / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_out = open(log_dir / f"{sid}.log", "a")
        cmd = [py, str(script)] + sinfo.get("args", [])
        p = subprocess.Popen(cmd, cwd=str(work_dir),
                              stdout=log_out, stderr=log_out, env=env)
        running_services[sid] = p
        return jsonify({"success": True, "message": f"{sinfo['name']} started (PID {p.pid})"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/services/<sid>/stop", methods=["POST"])
def api_stop_service(sid):
    proc = running_services.get(sid)
    if not proc:
        return jsonify({"success": False, "error": "Not running"}), 400
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    del running_services[sid]
    return jsonify({"success": True})

@app.route("/api/process/kill", methods=["POST"])
def api_kill_process():
    """Kill a process by PID. Sends SIGTERM first, SIGKILL after 3s."""
    data = request.json or {}
    pid = data.get("pid")
    if not pid:
        return jsonify({"success": False, "error": "No PID provided"}), 400
    try:
        pid = int(pid)
        # Safety: never kill PID 1, own PID, or dashboard PID
        if pid in (1, os.getpid(), os.getppid()):
            return jsonify({"success": False, "error": "Protected process"}), 403
        proc = psutil.Process(pid)
        name = proc.name()
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        return jsonify({"success": True, "message": f"Killed {name} (PID {pid})"})
    except psutil.NoSuchProcess:
        return jsonify({"success": False, "error": f"PID {pid} not found"}), 404
    except psutil.AccessDenied:
        return jsonify({"success": False, "error": f"Access denied for PID {pid}"}), 403
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ollama/unload", methods=["POST"])
def api_ollama_unload():
    """Unload a model from VRAM by sending keep_alive=0."""
    if _req is None:
        return jsonify({"success": False, "error": "requests not installed"}), 500
    data = request.json or {}
    model = data.get("model", "")
    if not model:
        return jsonify({"success": False, "error": "No model specified"}), 400
    try:
        r = _req.post("http://localhost:11434/api/generate",
                       json={"model": model, "prompt": "", "keep_alive": 0},
                       timeout=10)
        return jsonify({"success": True, "message": f"Unloaded {model} from VRAM"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ollama/stop", methods=["POST"])
def api_ollama_stop():
    """Stop the Ollama server process entirely."""
    try:
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                if proc.info["name"] == "ollama" or "ollama" in " ".join(proc.info.get("cmdline") or []):
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return jsonify({"success": True, "message": "Ollama server stopped"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/db/list")
def api_db_list():
    """List files in the DB folder."""
    category = request.args.get("cat", "")
    target = DB_ROOT / category if category else DB_ROOT
    if not target.exists():
        return jsonify({"files": [], "categories": []})
    categories = [d.name for d in DB_ROOT.iterdir() if d.is_dir()]
    files = []
    for f in sorted(target.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "category": category or "root",
            })
    return jsonify({"files": files, "categories": categories})


@app.route("/api/db/read")
def api_db_read():
    """Read a file from the DB folder."""
    cat = request.args.get("cat", "")
    name = request.args.get("name", "")
    if not name:
        return jsonify({"error": "No filename"}), 400
    target = DB_ROOT / cat / name if cat else DB_ROOT / name
    if not target.exists() or not target.is_file():
        return jsonify({"error": "File not found"}), 404
    try:
        content = target.read_text(encoding="utf-8", errors="replace")[:50000]
        return jsonify({"name": name, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/save", methods=["POST"])
def api_db_save():
    """Save a file to the DB folder."""
    data = request.json or {}
    cat = data.get("category", "prompts")
    name = data.get("name", "")
    content = data.get("content", "")
    if not name:
        return jsonify({"success": False, "error": "No filename"}), 400
    # Sanitize filename
    safe_name = "".join(c for c in name if c.isalnum() or c in "._- ").strip()
    if not safe_name:
        return jsonify({"success": False, "error": "Invalid filename"}), 400
    target = DB_ROOT / cat / safe_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return jsonify({"success": True, "message": f"Saved {safe_name}"})


@app.route("/api/db/delete", methods=["POST"])
def api_db_delete():
    """Delete a file from the DB folder."""
    data = request.json or {}
    cat = data.get("category", "")
    name = data.get("name", "")
    if not name:
        return jsonify({"success": False, "error": "No filename"}), 400
    target = DB_ROOT / cat / name if cat else DB_ROOT / name
    if target.exists() and target.is_file():
        target.unlink()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Not found"}), 404


@app.route("/api/listening")
def api_listening():
    """Get listening services with PID and process name."""
    return jsonify({"services": get_listening_services()})


@app.route("/api/chat/save", methods=["POST"])
def api_chat_save():
    """Save chat conversation to db/chats."""
    data = request.json or {}
    model = data.get("model", "unknown")
    messages = data.get("messages", [])
    if not messages:
        return jsonify({"success": False, "error": "No messages"}), 400
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"chat_{model.replace(':', '-')}_{ts}.json"
    target = DB_ROOT / "chats" / fname
    target.write_text(json.dumps({"model": model, "timestamp": ts, "messages": messages}, indent=2), encoding="utf-8")
    return jsonify({"success": True, "file": fname})


@app.route("/api/chat/history")
def api_chat_history():
    """List saved chat histories."""
    chats_dir = DB_ROOT / "chats"
    files = []
    for f in sorted(chats_dir.iterdir(), reverse=True):
        if f.is_file() and f.suffix == ".json":
            try:
                meta = json.loads(f.read_text(encoding="utf-8"))
                files.append({"name": f.name, "model": meta.get("model", "?"), "count": len(meta.get("messages", []))})
            except Exception:
                files.append({"name": f.name, "model": "?", "count": 0})
    return jsonify({"chats": files[:30]})


@app.route("/api/kali/run", methods=["POST"])
def api_kali_run():
    """Run a Kali/recon tool against a target."""
    data = request.json or {}
    tool = data.get("tool", "")
    target = data.get("target", "")
    if not tool or not target:
        return jsonify({"error": "Missing tool or target"}), 400
    # Sanitize target: only allow alphanumeric, dots, colons, slashes, hyphens
    import re
    if not re.match(r'^[a-zA-Z0-9.:/_\-]+$', target):
        return jsonify({"error": "Invalid target characters"}), 400
    # Strip subnet mask for tools that need a single host
    host_target = target.split("/")[0] if "/" in target else target
    tool_cmds = {
        "whatweb": ["whatweb", "-v", target],
        "nikto": ["nikto", "-h", host_target, "-maxtime", "30"],
        "whois": ["whois", host_target],
        "dig": ["dig", host_target, "+short"],
        "traceroute": ["traceroute", "-m", "15", host_target],
        "sslscan": ["sslscan", "--no-colour", host_target],
    }
    if tool not in tool_cmds:
        return jsonify({"error": f"Unknown tool: {tool}"}), 400
    cmd = tool_cmds[tool]
    if not shutil.which(cmd[0]):
        return jsonify({"error": f"{cmd[0]} not installed. Run: sudo apt install {cmd[0]}"}), 404
    try:
        out = subprocess.check_output(cmd, timeout=60, text=True, stderr=subprocess.STDOUT)
        return jsonify({"output": out[:10000], "tool": tool, "target": target})
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"{tool} timed out (60s limit)"})
    except subprocess.CalledProcessError as e:
        return jsonify({"output": (e.output or "")[:5000], "tool": tool, "target": target})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/security/quickscan", methods=["POST"])
def api_security_quickscan():
    """Run a quick security assessment of the local system."""
    results = []
    # Check for open ports
    try:
        conns = psutil.net_connections(kind="inet")
        listen_ports = set()
        for c in conns:
            if c.status == "LISTEN" and c.laddr:
                listen_ports.add(c.laddr.port)
        results.append({"check": "Listening Ports", "status": "info", "detail": f"{len(listen_ports)} ports open: {sorted(listen_ports)[:15]}"})
    except Exception:
        pass
    # Check SSH
    try:
        auth_log = Path("/var/log/auth.log")
        if auth_log.exists():
            lines = auth_log.read_text(errors="replace").splitlines()[-200:]
            fails = sum(1 for l in lines if "Failed password" in l or "authentication failure" in l)
            status = "warn" if fails > 5 else "ok"
            results.append({"check": "SSH Brute-Force", "status": status, "detail": f"{fails} failed attempts in recent log"})
    except PermissionError:
        results.append({"check": "SSH Brute-Force", "status": "info", "detail": "Cannot read auth.log (need root)"})
    except Exception:
        pass
    # Check VPN
    vpn_up = False
    for iface in psutil.net_if_addrs().keys():
        if any(x in iface.lower() for x in ["tun", "tap", "wg", "nordlynx", "proton", "mullvad"]):
            stats = psutil.net_if_stats().get(iface)
            if stats and stats.isup:
                vpn_up = True
                break
    results.append({"check": "VPN Status", "status": "ok" if vpn_up else "warn", "detail": "VPN active" if vpn_up else "NO VPN — traffic unprotected"})
    # Check resources
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().percent
    results.append({"check": "CPU Load", "status": "warn" if cpu > 85 else "ok", "detail": f"{cpu:.0f}%"})
    results.append({"check": "Memory", "status": "warn" if mem > 90 else "ok", "detail": f"{mem:.0f}%"})
    # Check critical files
    for path in ["/etc/passwd", "/etc/shadow", "/etc/sudoers"]:
        p = Path(path)
        if p.exists():
            try:
                import stat
                mode = p.stat().st_mode
                world_readable = bool(mode & stat.S_IROTH)
                if path == "/etc/shadow" and world_readable:
                    results.append({"check": f"File: {path}", "status": "critical", "detail": "WORLD READABLE — fix permissions!"})
                else:
                    results.append({"check": f"File: {path}", "status": "ok", "detail": f"Permissions: {oct(mode)[-3:]}"})
            except PermissionError:
                results.append({"check": f"File: {path}", "status": "ok", "detail": "Access restricted (normal)"})
    return jsonify({"results": results, "timestamp": datetime.now().strftime("%H:%M:%S")})


@app.route("/api/activity/stream")
def api_activity_stream():
    """Return recent AI activity events for the dashboard terminal."""
    since = float(request.args.get("since", 0))
    limit = int(request.args.get("limit", 100))
    events = ActivityStream.read_recent(since=since, limit=limit)
    return jsonify({"events": events})


# ═══════════════════════════════════════════════════════════════════════
# CRYPTO TRADING API
# ═══════════════════════════════════════════════════════════════════════

CRYPTOBOT_DIR = Path.home() / "cryptobot"
CRYPTO_STATE_FILE = CRYPTOBOT_DIR / "data" / "Trades" / "crypto" / "bot_state.json"
CRYPTO_CONFIG_FILE = CRYPTOBOT_DIR / "crypto_config.json"

def _crypto_bot_state():
    """Read crypto bot state file."""
    try:
        if CRYPTO_STATE_FILE.exists():
            with open(CRYPTO_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _crypto_config():
    """Read crypto config."""
    try:
        if CRYPTO_CONFIG_FILE.exists():
            with open(CRYPTO_CONFIG_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _crypto_bot_running():
    """Check if crypto_bot.py --live is running."""
    result = {"running": False, "pid": None, "live": False}
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline') or []
            cmd_str = ' '.join(cmd)
            if 'crypto_bot.py' in cmd_str:
                is_live = '--live' in cmd_str
                is_python = (proc.info.get('name') or '').startswith('python')
                # Prefer the actual python process over bash wrappers
                if is_python or not result["running"]:
                    result = {"running": True, "pid": proc.info['pid'],
                              "live": is_live or result.get("live", False)}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return result

def _crypto_ai_running():
    """Check if crypto_ai_server.py is running and healthy."""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmd = proc.info.get('cmdline') or []
            if any('crypto_ai_server.py' in c for c in cmd):
                healthy = False
                if _req:
                    try:
                        r = _req.get("http://127.0.0.1:8081/health", timeout=2)
                        healthy = r.status_code == 200
                    except Exception:
                        pass
                return {"running": True, "pid": proc.info['pid'], "healthy": healthy}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return {"running": False, "pid": None, "healthy": False}

def _crypto_log_tail(n=30):
    """Get last N lines from the most recent bot log."""
    log_dir = CRYPTOBOT_DIR / "Logs" / "crypto"
    try:
        logs = sorted(log_dir.glob("bot_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if logs:
            lines = logs[0].read_text(errors='replace').strip().splitlines()
            return lines[-n:]
    except Exception:
        pass
    # Fallback to nohup log
    fallback = Path("/tmp/crypto_bot_live.log")
    try:
        if fallback.exists():
            lines = fallback.read_text(errors='replace').strip().splitlines()
            return lines[-n:]
    except Exception:
        pass
    return []

@app.route("/api/crypto/status")
def api_crypto_status():
    """Full crypto trading status: state, config, servers, log tail."""
    st = _crypto_bot_state()
    cfg = _crypto_config()
    bot = _crypto_bot_running()
    ai = _crypto_ai_running()
    log_lines = _crypto_log_tail(40)

    # Parse open positions for display
    positions = st.get("open_positions", {})
    closed = st.get("closed_trades", [])

    return jsonify({
        "bot": bot,
        "ai_server": ai,
        "balance": st.get("equity_hwm", 0) if not bot["running"] else None,
        "state": {
            "start_of_day_balance": st.get("start_of_day_balance", 0),
            "equity_hwm": st.get("equity_hwm", 0),
            "total_pnl": round(st.get("total_pnl", 0), 2),
            "n_trades": st.get("n_trades", 0),
            "n_wins": st.get("n_wins", 0),
            "win_rate": round(100 * st.get("n_wins", 0) / max(st.get("n_trades", 1), 1), 1),
            "open_positions": positions,
            "n_open": len(positions),
            "recent_trades": closed[-10:] if closed else [],
        },
        "config": {
            "exchange": cfg.get("exchange", {}).get("name", "?"),
            "paper": cfg.get("bot", {}).get("paper_trading", True),
            "symbols": [s.get("base", "?") for s in cfg.get("symbols", [])],
            "n_symbols": len(cfg.get("symbols", [])),
            "risk_per_trade": cfg.get("risk", {}).get("risk_per_trade_pct", 0),
            "max_dd": cfg.get("risk", {}).get("max_daily_drawdown_pct", 0),
            "max_positions": cfg.get("risk", {}).get("max_open_positions", 0),
            "min_confidence": cfg.get("risk", {}).get("min_confidence", 0),
            "primary_tf": cfg.get("primary_timeframe", "?"),
        },
        "log": log_lines,
    })

@app.route("/api/crypto/log")
def api_crypto_log():
    """Return last N lines of bot log."""
    n = int(request.args.get("n", 50))
    return jsonify({"lines": _crypto_log_tail(n)})

@app.route("/api/crypto/pipeline/<action>", methods=["POST"])
def api_crypto_pipeline(action):
    """Start/stop crypto pipeline components: ai_server, bot, fetch_data."""
    cryptobot_dir = str(CRYPTOBOT_DIR)
    venv_py = CRYPTOBOT_DIR / "venv" / "bin" / "python"
    py = str(venv_py) if venv_py.exists() else sys.executable
    env = os.environ.copy()
    # Load .env from cryptobot dir
    env_file = CRYPTOBOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()

    if action == "start_all":
        results = []
        # Start AI server
        ai = _crypto_ai_running()
        if not ai["running"]:
            log_dir = CRYPTOBOT_DIR / "Logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_out = open(log_dir / "crypto_ai.log", "a")
            p = subprocess.Popen([py, str(CRYPTOBOT_DIR / "crypto_ai_server.py")],
                                  cwd=cryptobot_dir, stdout=log_out, stderr=log_out, env=env)
            running_services["crypto_ai"] = p
            results.append(f"AI Server started (PID {p.pid})")
        else:
            results.append(f"AI Server already running (PID {ai['pid']})")
        # Start bot
        bot = _crypto_bot_running()
        if not bot["running"]:
            log_out2 = open(CRYPTOBOT_DIR / "Logs" / "crypto_bot.log", "a")
            p2 = subprocess.Popen([py, str(CRYPTOBOT_DIR / "crypto_bot.py"), "--live"],
                                   cwd=cryptobot_dir, stdout=log_out2, stderr=log_out2, env=env)
            running_services["crypto_bot"] = p2
            results.append(f"Bot started LIVE (PID {p2.pid})")
        else:
            results.append(f"Bot already running (PID {bot['pid']}, live={bot['live']})")
        return jsonify({"success": True, "results": results})

    elif action == "stop_all":
        results = []
        for name in ["crypto_bot", "crypto_ai"]:
            proc = running_services.get(name)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                del running_services[name]
                results.append(f"{name} stopped")
            else:
                # Try to find and kill by process scan
                for p in psutil.process_iter(['pid', 'cmdline']):
                    try:
                        cmd = p.info.get('cmdline') or []
                        script_name = "crypto_bot.py" if name == "crypto_bot" else "crypto_ai_server.py"
                        if any(script_name in c for c in cmd):
                            psutil.Process(p.info['pid']).terminate()
                            results.append(f"{name} killed (PID {p.info['pid']})")
                    except Exception:
                        pass
        return jsonify({"success": True, "results": results})

    elif action == "start_ai":
        ai = _crypto_ai_running()
        if ai["running"]:
            return jsonify({"success": False, "error": f"Already running (PID {ai['pid']})"}), 400
        log_out = open(CRYPTOBOT_DIR / "Logs" / "crypto_ai.log", "a")
        p = subprocess.Popen([py, str(CRYPTOBOT_DIR / "crypto_ai_server.py")],
                              cwd=cryptobot_dir, stdout=log_out, stderr=log_out, env=env)
        running_services["crypto_ai"] = p
        return jsonify({"success": True, "message": f"AI Server started (PID {p.pid})"})

    elif action == "stop_ai":
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = p.info.get('cmdline') or []
                if any('crypto_ai_server.py' in c for c in cmd):
                    psutil.Process(p.info['pid']).terminate()
                    running_services.pop("crypto_ai", None)
                    return jsonify({"success": True, "message": f"AI Server stopped (PID {p.info['pid']})"})
            except Exception:
                pass
        return jsonify({"success": False, "error": "Not running"}), 400

    elif action == "start_bot":
        bot = _crypto_bot_running()
        if bot["running"]:
            return jsonify({"success": False, "error": f"Already running (PID {bot['pid']})"}), 400
        log_out = open(CRYPTOBOT_DIR / "Logs" / "crypto_bot.log", "a")
        p = subprocess.Popen([py, str(CRYPTOBOT_DIR / "crypto_bot.py"), "--live"],
                              cwd=cryptobot_dir, stdout=log_out, stderr=log_out, env=env)
        running_services["crypto_bot"] = p
        return jsonify({"success": True, "message": f"Bot started LIVE (PID {p.pid})"})

    elif action == "stop_bot":
        for p in psutil.process_iter(['pid', 'cmdline']):
            try:
                cmd = p.info.get('cmdline') or []
                if any('crypto_bot.py' in c for c in cmd):
                    psutil.Process(p.info['pid']).terminate()
                    running_services.pop("crypto_bot", None)
                    return jsonify({"success": True, "message": f"Bot stopped (PID {p.info['pid']})"})
            except Exception:
                pass
        return jsonify({"success": False, "error": "Not running"}), 400

    elif action == "fetch_data":
        # Run data fetcher in background thread
        def _fetch():
            try:
                log_out = open(CRYPTOBOT_DIR / "Logs" / "data_fetch_dash.log", "w")
                subprocess.run([py, str(CRYPTOBOT_DIR / "crypto_data_fetcher.py")],
                               cwd=cryptobot_dir, stdout=log_out, stderr=log_out, env=env, timeout=600)
            except Exception as e:
                logger.error(f"Data fetch failed: {e}")
        threading.Thread(target=_fetch, daemon=True).start()
        return jsonify({"success": True, "message": "Data fetch started in background"})

    return jsonify({"success": False, "error": f"Unknown action: {action}"}), 400


@app.route("/api/nmap/sweep", methods=["POST"])
def api_nmap_sweep():
    target = request.json.get("target", "192.168.1.0/24") if request.is_json else "192.168.1.0/24"
    return jsonify(run_nmap_quick(target))

@app.route("/api/nmap/ports", methods=["POST"])
def api_nmap_ports():
    data = request.json or {}
    return jsonify(run_port_scan(data.get("target", "localhost"), data.get("ports", "1-1024")))

@app.route("/api/ollama/chat", methods=["POST"])
def api_ollama_chat():
    if _req is None:
        return jsonify({"error": "requests not installed"}), 500
    data = request.json or {}
    model = data.get("model", "dolphin-mistral:latest")
    prompt = data.get("prompt", "")
    try:
        r = _req.post("http://localhost:11434/api/generate",
                      json={"model": model, "prompt": prompt, "stream": False},
                      timeout=120)
        resp = r.json().get("response", "")
        # Emit activity event for dashboard chat usage
        stream = ActivityStream("dashboard_chat")
        stream.emit(ActivityStream.GENERATING, f"Chat: {model}", {"model": model, "prompt_len": len(prompt)})
        return jsonify({"response": resp, "model": model})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════════════════
# BASH SCRIPT RUNNER API
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/bash/list")
def api_bash_list():
    """List all bash security scripts with availability status."""
    if not _bash_runner:
        return jsonify({"error": "BashScriptRunner not available", "scripts": {}})
    return jsonify({"scripts": _bash_runner.list_scripts()})


@app.route("/api/bash/run", methods=["POST"])
def api_bash_run():
    """Run a bash script by registry key (background, captured output)."""
    if not _bash_runner:
        return jsonify({"success": False, "error": "BashScriptRunner not available"}), 503
    data = request.json or {}
    key = data.get("key", "")
    extra_args = data.get("args", [])
    if not key:
        return jsonify({"success": False, "error": "No script key provided"}), 400
    # Validate key contains only safe chars
    import re
    if not re.match(r'^[a-zA-Z0-9_\-]+$', key):
        return jsonify({"success": False, "error": "Invalid script key"}), 400

    stream = ActivityStream("dashboard_bash")
    stream.emit(ActivityStream.TOOL_DISPATCH, f"Bash: {key} {' '.join(extra_args)}")

    def _run_bg():
        result = _bash_runner.run(key, extra_args=extra_args or None,
                                  stream_output=False, capture=True)
        status = "Done" if result.get("success") else "Failed"
        stream.emit(ActivityStream.RESPONSE_DONE, f"Bash {key} {status}",
                    {"exit_code": result.get("exit_code")})

    threading.Thread(target=_run_bg, daemon=True).start()
    return jsonify({"success": True, "message": f"Script '{key}' started — watch Activity stream"})


# ═══════════════════════════════════════════════════════════════════════
# PORT INVESTIGATOR API
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/port/investigate")
def api_port_investigate():
    """Run port investigation with optional single-port deep-dive."""
    if not _sec_center:
        return jsonify({"error": "SecurityCommandCenter not available"}), 503
    port = request.args.get("port", type=int)
    no_geo = request.args.get("no_geo", "false").lower() == "true"
    try:
        data = _sec_center.investigate_ports(port=port, no_geo=no_geo)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/port/quick")
def api_port_quick():
    """Quick security overview from SecurityCommandCenter."""
    if not _sec_center:
        return jsonify({"error": "SecurityCommandCenter not available"}), 503
    try:
        return jsonify(_sec_center.quick_overview())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════
# AUTONOMOUS AGENT DISPATCH API
# ═══════════════════════════════════════════════════════════════════════

@app.route("/api/agent/dispatch", methods=["POST"])
def api_agent_dispatch():
    """
    Autonomous agent dispatch — runs a security/bash/kali task from the dashboard.
    Emits events to the activity stream; returns immediately with task ID.
    """
    data = request.json or {}
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"success": False, "error": "No task provided"}), 400
    # Cap task length to prevent abuse
    task = task[:500]

    task_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stream = ActivityStream("dashboard_dispatch")
    stream.emit(ActivityStream.QUERY_RECEIVED, f"[DISPATCH] {task[:80]}")

    def _run():
        import re as _re
        try:
            task_lower = task.lower()

            # ── Security Command Center dispatch ──────────────────────
            if _sec_center:
                sec_map = {
                    ("quick", "overview", "scan status"): "quick",
                    ("investigate", "port investigation", "connections"): "investigate",
                    ("hunt", "discover hosts", "network scan"): "hunt",
                    ("traffic", "flows", "traffic analysis"): "traffic",
                    ("firewall",): "firewall",
                    ("full audit", "audit everything"): "audit",
                }
                for keywords, subcmd in sec_map.items():
                    if any(kw in task_lower for kw in keywords):
                        stream.emit(ActivityStream.TOOL_DISPATCH, f"Security: {subcmd}")
                        result = _sec_center.handle_command("security", subcmd)
                        stream.emit(ActivityStream.RESPONSE_DONE, f"Security/{subcmd} done",
                                    {"preview": result[:200]})
                        return

            # ── Bash script dispatch ──────────────────────────────────
            if _bash_runner:
                bash_map = {
                    ("verify network", "check network", "network check"): "verify",
                    ("looting larry", "looting scan", "network discovery"): "looting-scan",
                    ("homelab audit", "nmap audit", "homelab scan"): "homelab-audit",
                    ("ipv6 scan", "ipv6"): "scan-ipv6",
                }
                for keywords, key in bash_map.items():
                    if any(kw in task_lower for kw in keywords):
                        stream.emit(ActivityStream.TOOL_DISPATCH, f"Bash: {key}")
                        result = _bash_runner.run(key, stream_output=False, capture=True)
                        status = "Done" if result.get("success") else "Failed"
                        stream.emit(ActivityStream.RESPONSE_DONE, f"Bash/{key} {status}",
                                    {"exit_code": result.get("exit_code")})
                        return

            # ── Kali tool dispatch ────────────────────────────────────
            from kali_tools import TOOLS, parse_args_with_preset, run_tool
            # Attempt to match "run <toolname> [target]" pattern
            m = _re.search(r'\b(?:run|use|execute)\s+(\w+)\s+(.+)', task, _re.I)
            if m:
                tool_name = m.group(1).lower()
                tool_args = m.group(2).strip()
                if tool_name in TOOLS:
                    tool_obj = TOOLS[tool_name]
                    expanded = parse_args_with_preset(tool_obj, tool_args)
                    if not expanded.startswith("__ERROR__"):
                        stream.emit(ActivityStream.TOOL_DISPATCH, f"Kali: {tool_name} {tool_args[:40]}")
                        success, output = run_tool(tool_name, expanded)
                        status = "Done" if success else "Finished"
                        stream.emit(ActivityStream.RESPONSE_DONE, f"Kali/{tool_name} {status}",
                                    {"preview": output[:200]})
                        return

            # ── Fallback: pass to Ollama for natural language interpretation ──
            if _req:
                try:
                    import json as _json
                    prompt = (
                        f"You are Larry G-Force, a security AI assistant. "
                        f"The user wants to: {task}\n"
                        f"Respond with a brief, actionable answer about what security steps to take."
                    )
                    r = _req.post("http://localhost:11434/api/generate",
                                  json={"model": "dolphinecoder:15b", "prompt": prompt, "stream": False},
                                  timeout=60)
                    resp = r.json().get("response", "No response from model")
                    stream.emit(ActivityStream.RESPONSE_DONE, f"LLM response: {resp[:100]}")
                except Exception as llm_e:
                    stream.emit(ActivityStream.ERROR, f"LLM fallback failed: {llm_e}")
            else:
                stream.emit(ActivityStream.ERROR, f"No matching handler for: {task[:60]}")

        except Exception as e:
            stream.emit(ActivityStream.ERROR, f"Dispatch error: {e}")

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "task_id": task_id,
                    "message": "Task dispatched — watch the AI Activity stream"})


@app.route("/api/tools/status")
def api_tools_status():
    """Return availability of security/bash tools."""
    return jsonify({
        "security_tools": SECURITY_TOOLS_AVAILABLE,
        "bash_scripts": _bash_runner.list_available() if _bash_runner else {},
        "security_modules": _sec_center.check_modules() if _sec_center else {},
    })


# ═══════════════════════════════════════════════════════════════════════
# FRONTEND — COMMAND CENTRAL
# ═══════════════════════════════════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LARRY G-FORCE // COMMAND CENTRAL</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@300;400;600;700&family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap" rel="stylesheet">
<style>
:root {
  --bg:        #040810;
  --bg2:       #070d1a;
  --panel:     rgba(8, 20, 40, 0.85);
  --border:    rgba(0, 200, 255, 0.18);
  --border-hi: rgba(0, 200, 255, 0.6);
  --gold:      #f0b429;
  --gold2:     #ffd700;
  --cyan:      #00c8ff;
  --cyan2:     #00f0ff;
  --green:     #00ff88;
  --red:       #ff3860;
  --orange:    #ff8c00;
  --dim:       rgba(160,200,255,0.35);
  --text:      #c8deff;
  --text2:     rgba(180,210,255,0.6);
  --glow:      0 0 20px rgba(0,200,255,0.3);
  --glow-gold: 0 0 20px rgba(240,180,40,0.4);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Rajdhani', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Animated grid background ───────────────────────────────────── */
body::before {
  content: '';
  position: fixed; inset: 0; z-index: 0;
  background-image:
    linear-gradient(rgba(0,200,255,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,200,255,0.04) 1px, transparent 1px);
  background-size: 40px 40px;
  animation: gridShift 20s linear infinite;
  pointer-events: none;
}
@keyframes gridShift { 0%{background-position:0 0} 100%{background-position:40px 40px} }

/* ── Scanline overlay ────────────────────────────────────────────── */
body::after {
  content: '';
  position: fixed; inset: 0; z-index: 0;
  background: repeating-linear-gradient(
    0deg, transparent 0px, transparent 3px,
    rgba(0,0,0,0.08) 3px, rgba(0,0,0,0.08) 4px);
  pointer-events: none;
}

/* ── Layout ──────────────────────────────────────────────────────── */
#app { position: relative; z-index: 1; padding: 16px; max-width: 1800px; margin: 0 auto; }

/* ── Header ──────────────────────────────────────────────────────── */
header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 24px;
  background: linear-gradient(90deg, rgba(240,180,40,0.08), transparent, rgba(0,200,255,0.08));
  border: 1px solid var(--border);
  border-top: 2px solid var(--gold);
  margin-bottom: 16px;
  clip-path: polygon(0 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%);
}
.logo { font-family: 'Orbitron', sans-serif; font-size: 1.6rem; font-weight: 900;
  background: linear-gradient(90deg, var(--gold2), var(--cyan2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.logo span { font-size: 0.7rem; font-family: 'Share Tech Mono'; color: var(--dim);
  -webkit-text-fill-color: var(--dim); display: block; letter-spacing: 4px; }
.header-right { display: flex; align-items: center; gap: 24px; }
#clock { font-family: 'Orbitron', sans-serif; font-size: 1.1rem; color: var(--gold); }
#uptime-label { font-family: 'Share Tech Mono'; font-size: 0.75rem; color: var(--dim); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green);
  box-shadow: 0 0 8px var(--green); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

/* ── Tabs ────────────────────────────────────────────────────────── */
.tabs { display: flex; gap: 2px; margin-bottom: 16px; border-bottom: 1px solid var(--border); }
.tab {
  font-family: 'Orbitron', sans-serif; font-size: 0.65rem; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase;
  padding: 10px 20px; cursor: pointer; border: none; background: transparent;
  color: var(--dim); border-bottom: 2px solid transparent;
  transition: all 0.2s; white-space: nowrap;
}
.tab:hover { color: var(--cyan); }
.tab.active { color: var(--gold); border-bottom-color: var(--gold); }

/* ── Grid layouts ────────────────────────────────────────────────── */
.grid-4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; margin-bottom: 16px; }
.grid-3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; margin-bottom: 16px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.grid-main { display: grid; grid-template-columns: 1fr 360px; gap: 12px; margin-bottom: 16px; }
@media(max-width:1200px) { .grid-4{grid-template-columns:repeat(2,1fr)} .grid-main{grid-template-columns:1fr} }
@media(max-width:700px)  { .grid-4{grid-template-columns:1fr} .grid-3{grid-template-columns:1fr} .grid-2{grid-template-columns:1fr} }

/* ── Panel ───────────────────────────────────────────────────────── */
.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-top: 1px solid var(--border-hi);
  backdrop-filter: blur(12px);
  padding: 16px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.3s;
}
.panel::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--cyan), transparent);
  opacity: 0.5;
}
.panel:hover { border-color: rgba(0,200,255,0.35); }
.panel-title {
  font-family: 'Orbitron', sans-serif; font-size: 0.6rem; font-weight: 700;
  letter-spacing: 3px; color: var(--dim); text-transform: uppercase;
  margin-bottom: 14px; display: flex; align-items: center; gap: 8px;
}
.panel-title .icon { font-size: 0.85rem; }

/* ── Stat card ───────────────────────────────────────────────────── */
.stat-card {
  background: rgba(0,200,255,0.04);
  border: 1px solid var(--border);
  padding: 16px;
  position: relative; overflow: hidden;
}
.stat-card::after {
  content: attr(data-label);
  position: absolute; top: 8px; right: 10px;
  font-family: 'Share Tech Mono'; font-size: 0.6rem; color: var(--dim);
  letter-spacing: 2px; text-transform: uppercase;
}
.stat-val { font-family: 'Orbitron', sans-serif; font-size: 1.8rem; font-weight: 700;
  line-height: 1; margin-bottom: 4px; }
.stat-sub { font-family: 'Share Tech Mono'; font-size: 0.7rem; color: var(--dim); }
.color-cyan  { color: var(--cyan2); text-shadow: 0 0 10px rgba(0,240,255,0.5); }
.color-gold  { color: var(--gold);  text-shadow: 0 0 10px rgba(240,180,40,0.5); }
.color-green { color: var(--green); text-shadow: 0 0 10px rgba(0,255,136,0.5); }
.color-red   { color: var(--red);   text-shadow: 0 0 10px rgba(255,56,96,0.5); }
.color-orange{ color: var(--orange);text-shadow: 0 0 10px rgba(255,140,0,0.5); }

/* ── Progress bar ────────────────────────────────────────────────── */
.bar-wrap { margin: 6px 0; }
.bar-label { display: flex; justify-content: space-between;
  font-family: 'Share Tech Mono'; font-size: 0.68rem; color: var(--dim); margin-bottom: 4px; }
.bar { height: 5px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 1s ease; }
.bar-cyan   { background: linear-gradient(90deg, #007aff, var(--cyan2)); box-shadow: 0 0 6px rgba(0,200,255,0.4); }
.bar-gold   { background: linear-gradient(90deg, #d48000, var(--gold2)); box-shadow: 0 0 6px rgba(240,180,40,0.4); }
.bar-green  { background: linear-gradient(90deg, #00aa55, var(--green)); box-shadow: 0 0 6px rgba(0,255,136,0.4); }
.bar-danger { background: linear-gradient(90deg, #cc0030, var(--red));   box-shadow: 0 0 6px rgba(255,56,96,0.4); }

/* ── Badge / pill ────────────────────────────────────────────────── */
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
  font-family: 'Share Tech Mono'; font-size: 0.65rem; border-radius: 2px; }
.badge-on  { background: rgba(0,255,136,0.12); color: var(--green); border: 1px solid rgba(0,255,136,0.3); }
.badge-off { background: rgba(255,56,96,0.12);  color: var(--red);   border: 1px solid rgba(255,56,96,0.3); }
.badge-warn{ background: rgba(255,140,0,0.12);  color: var(--orange);border: 1px solid rgba(255,140,0,0.3); }
.badge-dim { background: rgba(160,200,255,0.08);color: var(--dim);   border: 1px solid var(--border); }

/* ── Table ───────────────────────────────────────────────────────── */
.data-table { width: 100%; border-collapse: collapse; font-family: 'Share Tech Mono'; font-size: 0.72rem; }
.data-table th { color: var(--dim); text-align: left; padding: 6px 8px;
  border-bottom: 1px solid var(--border); letter-spacing: 1px; }
.data-table td { padding: 6px 8px; border-bottom: 1px solid rgba(0,200,255,0.05); color: var(--text); }
.data-table tr:hover td { background: rgba(0,200,255,0.04); }

/* ── Model card ──────────────────────────────────────────────────── */
.model-card { display: flex; justify-content: space-between; align-items: center;
  padding: 9px 12px; border: 1px solid var(--border); margin-bottom: 6px;
  background: rgba(0,200,255,0.03); transition: all 0.2s; cursor: pointer; }
.model-card:hover { border-color: var(--cyan); background: rgba(0,200,255,0.07); }
.model-card.active-model { border-color: var(--gold); background: rgba(240,180,40,0.08); }
.model-name { font-family: 'Share Tech Mono'; font-size: 0.75rem; color: var(--cyan); }
.model-size { font-family: 'Share Tech Mono'; font-size: 0.65rem; color: var(--dim); }

/* ── Chat box ────────────────────────────────────────────────────── */
#chat-history {
  height: 320px; overflow-y: auto; padding: 12px;
  background: rgba(0,0,0,0.3); border: 1px solid var(--border);
  margin-bottom: 10px; scroll-behavior: smooth;
}
#chat-history::-webkit-scrollbar { width: 4px; }
#chat-history::-webkit-scrollbar-thumb { background: var(--border-hi); border-radius: 2px; }
.msg { margin-bottom: 12px; animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:none} }
.msg-user  { text-align: right; }
.msg-larry { text-align: left; }
.bubble {
  display: inline-block; max-width: 85%; padding: 8px 14px;
  font-family: 'Share Tech Mono'; font-size: 0.72rem; line-height: 1.5;
}
.bubble-user  { background: rgba(240,180,40,0.1);  border: 1px solid rgba(240,180,40,0.3); color: var(--gold);  }
.bubble-larry { background: rgba(0,200,255,0.08); border: 1px solid var(--border); color: var(--text); }
.bubble-from  { font-size: 0.6rem; color: var(--dim); margin-bottom: 2px; letter-spacing: 2px; font-family: 'Orbitron', sans-serif; }

.chat-controls { display: flex; gap: 8px; }
.chat-controls select { flex: 0 0 180px; background: rgba(0,0,0,0.5); border: 1px solid var(--border);
  color: var(--text); padding: 8px; font-family: 'Share Tech Mono'; font-size: 0.7rem; }
#chat-input { flex: 1; background: rgba(0,0,0,0.5); border: 1px solid var(--border);
  color: var(--text); padding: 8px 12px; font-family: 'Share Tech Mono'; font-size: 0.75rem;
  outline: none; transition: border-color 0.2s; }
#chat-input:focus { border-color: var(--cyan); }
#chat-input::placeholder { color: var(--dim); }

/* ── Buttons ─────────────────────────────────────────────────────── */
.btn {
  font-family: 'Orbitron', sans-serif; font-size: 0.6rem; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase; cursor: pointer;
  border: 1px solid; padding: 8px 16px; background: transparent;
  transition: all 0.2s; white-space: nowrap;
}
.btn-cyan  { color: var(--cyan);  border-color: var(--cyan);  }
.btn-cyan:hover  { background: rgba(0,200,255,0.12); box-shadow: var(--glow); }
.btn-gold  { color: var(--gold);  border-color: var(--gold);  }
.btn-gold:hover  { background: rgba(240,180,40,0.12); box-shadow: var(--glow-gold); }
.btn-red   { color: var(--red);   border-color: var(--red);   }
.btn-red:hover   { background: rgba(255,56,96,0.12); }
.btn-green { color: var(--green); border-color: var(--green); }
.btn-green:hover { background: rgba(0,255,136,0.12); }
.btn-sm { padding: 5px 10px; font-size: 0.55rem; }

/* ── Service card ────────────────────────────────────────────────── */
.svc-card { padding: 14px; border: 1px solid var(--border); margin-bottom: 8px;
  display: flex; align-items: center; justify-content: space-between;
  background: rgba(0,200,255,0.02); transition: border-color 0.2s; }
.svc-card:hover { border-color: rgba(0,200,255,0.3); }
.svc-info { display: flex; align-items: center; gap: 10px; }
.svc-icon { font-size: 1.2rem; }
.svc-name { font-family: 'Orbitron', sans-serif; font-size: 0.65rem; font-weight: 700;
  color: var(--text); letter-spacing: 1px; }
.svc-port { font-family: 'Share Tech Mono'; font-size: 0.62rem; color: var(--dim); }

/* ── Nmap results ────────────────────────────────────────────────── */
.host-chip { display: inline-block; padding: 3px 8px; margin: 3px;
  background: rgba(0,200,255,0.06); border: 1px solid var(--border);
  font-family: 'Share Tech Mono'; font-size: 0.65rem; color: var(--cyan); }

/* ── Terminal / log ──────────────────────────────────────────────── */
.terminal {
  background: #010508; border: 1px solid var(--border);
  font-family: 'Share Tech Mono'; font-size: 0.7rem; color: #7ec8e3;
  padding: 12px; height: 200px; overflow-y: auto; line-height: 1.6;
}
.terminal .t-ok   { color: var(--green); }
.terminal .t-warn { color: var(--orange); }
.terminal .t-err  { color: var(--red); }
.terminal .t-dim  { color: var(--dim); }
.terminal .t-gold { color: var(--gold); }

/* ── Activity terminal ─────────────────────────────────────── */
.activity-term {
  height: 520px;
  background: linear-gradient(180deg, #010508 0%, #020a14 100%);
  border: 1px solid rgba(0,200,255,0.25);
  box-shadow: inset 0 0 30px rgba(0,200,255,0.05), 0 0 15px rgba(0,200,255,0.08);
}
.activity-term .ev { padding: 3px 0; border-bottom: 1px solid rgba(0,200,255,0.04); animation: fadeIn 0.3s ease; }
.activity-term .ev-time { color: var(--dim); font-size: 0.62rem; margin-right: 6px; }
.activity-term .ev-src  { font-size: 0.6rem; padding: 1px 5px; border-radius: 2px; margin-right: 6px; }
.activity-term .src-agent   { background: rgba(0,200,255,0.15); color: var(--cyan); border: 1px solid rgba(0,200,255,0.3); }
.activity-term .src-telegram { background: rgba(240,180,40,0.15); color: var(--gold); border: 1px solid rgba(240,180,40,0.3); }
.activity-term .src-system  { background: rgba(0,255,136,0.12); color: var(--green); border: 1px solid rgba(0,255,136,0.3); }
.activity-term .ev-type { font-size: 0.6rem; letter-spacing: 1px; margin-right: 6px; }
.activity-term .type-query     { color: var(--gold); }
.activity-term .type-model     { color: var(--cyan); }
.activity-term .type-context   { color: var(--dim); }
.activity-term .type-rag       { color: var(--green); }
.activity-term .type-tool      { color: var(--orange); }
.activity-term .type-thinking  { color: #c084fc; }
.activity-term .type-gen       { color: var(--cyan2); }
.activity-term .type-done      { color: var(--green); }
.activity-term .type-error     { color: var(--red); }
.activity-term .type-system    { color: var(--dim); }

/* ── Spinner ─────────────────────────────────────────────────────── */
.spin { display: inline-block; animation: spinAnim 1s linear infinite; }
@keyframes spinAnim { to{transform:rotate(360deg)} }

/* ── Section visibility ──────────────────────────────────────────── */
.tab-pane { display: none; }
.tab-pane.active { display: block; }

/* ── Input row ───────────────────────────────────────────────────── */
.input-row { display: flex; gap: 8px; margin-bottom: 12px; }
.input-row input, .input-row select {
  flex: 1; background: rgba(0,0,0,0.5); border: 1px solid var(--border);
  color: var(--text); padding: 8px 12px; font-family: 'Share Tech Mono'; font-size: 0.72rem; outline: none;
}
.input-row input:focus { border-color: var(--cyan); }

/* ── Decorative corner clips ─────────────────────────────────────── */
.clipped { clip-path: polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%); }

/* ── Interface indicator ─────────────────────────────────────────── */
.iface-row { display: flex; justify-content: space-between; align-items: center;
  padding: 7px 0; border-bottom: 1px solid rgba(0,200,255,0.06); }
.iface-name { font-family: 'Share Tech Mono'; font-size: 0.72rem; color: var(--cyan2); }
.iface-ip   { font-family: 'Share Tech Mono'; font-size: 0.72rem; color: var(--text2); }

/* ── Gauge arc ───────────────────────────────────────────────────── */
.gauge-wrap { text-align: center; padding: 6px; }
.gauge-val { font-family: 'Orbitron', sans-serif; font-size: 1.4rem; font-weight: 700; line-height: 1; }
.gauge-lbl { font-family: 'Share Tech Mono'; font-size: 0.6rem; color: var(--dim); letter-spacing: 2px; }

/* ── Scrollbar ───────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: rgba(0,0,0,0.3); }
::-webkit-scrollbar-thumb { background: rgba(0,200,255,0.3); border-radius: 3px; }

/* ── Header glow line animation ─────────────────────────── */
header::after {
  content: '';
  position: absolute; bottom: -1px; left: 0; width: 100%; height: 2px;
  background: linear-gradient(90deg, transparent, var(--cyan), var(--gold), var(--cyan), transparent);
  background-size: 300% 100%;
  animation: headerGlow 4s linear infinite;
}
@keyframes headerGlow { 0%{background-position:0% 50%} 100%{background-position:300% 50%} }

/* ── Footer ──────────────────────────────────────────────── */
.dashboard-footer {
  text-align: center; padding: 12px; margin-top: 16px;
  font-family: 'Share Tech Mono'; font-size: 0.6rem; color: var(--dim);
  border-top: 1px solid var(--border);
  letter-spacing: 2px;
}
.dashboard-footer .accent { color: var(--gold); }
</style>
</head>
<body>
<div id="app">

  <!-- ════ HEADER ════ -->
  <header>
    <div>
      <div class="logo">LARRY G-FORCE <span>COMMAND CENTRAL // v4.0</span></div>
    </div>
    <div class="header-right">
      <div>
        <div id="clock" class="color-gold">--:--:--</div>
        <div id="uptime-label" class="stat-sub">UPTIME: <span id="uptime-val">--</span></div>
      </div>
      <div class="status-dot" id="ollama-dot" title="Ollama status"></div>
    </div>
  </header>

  <!-- ════ TABS ════ -->
  <div class="tabs">
    <button class="tab active" onclick="showTab('overview')">⬡ OVERVIEW</button>
    <button class="tab" onclick="showTab('models')">◈ AI MODELS</button>
    <button class="tab" onclick="showTab('network')">◉ NETWORK</button>
    <button class="tab" onclick="showTab('security')">⚔ SECURITY</button>
    <button class="tab" onclick="showTab('services')">⚙ SERVICES</button>
    <button class="tab" onclick="showTab('activity')">⚡ AI ACTIVITY</button>
    <button class="tab" onclick="showTab('tools')">🛠 TOOLS</button>
    <button class="tab" onclick="showTab('db')">◆ DB</button>
    <button class="tab" onclick="showTab('chat')">◎ CHAT</button>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: OVERVIEW
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-overview" class="tab-pane active">
    <!-- KPI row -->
    <div class="grid-4" id="kpi-row">
      <div class="stat-card clipped" data-label="CPU">
        <div class="stat-val color-cyan" id="kpi-cpu">--</div>
        <div class="stat-sub">CORES: <span id="kpi-cores">--</span> · <span id="kpi-freq">--</span> MHz</div>
        <div class="bar-wrap" style="margin-top:8px"><div class="bar"><div class="bar-fill bar-cyan" id="bar-cpu" style="width:0%"></div></div></div>
      </div>
      <div class="stat-card clipped" data-label="MEMORY">
        <div class="stat-val color-gold" id="kpi-mem">--</div>
        <div class="stat-sub" id="kpi-mem-detail">-- / -- GB</div>
        <div class="bar-wrap" style="margin-top:8px"><div class="bar"><div class="bar-fill bar-gold" id="bar-mem" style="width:0%"></div></div></div>
      </div>
      <div class="stat-card clipped" data-label="DISK">
        <div class="stat-val color-green" id="kpi-disk">--</div>
        <div class="stat-sub" id="kpi-disk-detail">-- / -- GB</div>
        <div class="bar-wrap" style="margin-top:8px"><div class="bar"><div class="bar-fill bar-green" id="bar-disk" style="width:0%"></div></div></div>
      </div>
      <div class="stat-card clipped" data-label="GPU">
        <div class="stat-val color-orange" id="kpi-gpu-util">--</div>
        <div class="stat-sub" id="kpi-gpu-detail">-- / -- MB VRAM</div>
        <div class="bar-wrap" style="margin-top:8px"><div class="bar"><div class="bar-fill bar-danger" id="bar-gpu" style="width:0%"></div></div></div>
      </div>
    </div>

    <!-- ══ SYSTEM MONITOR (moved to top): Top Processes · GPU · Heat ══ -->
    <div class="grid-main">
      <div>
        <!-- Top Processes (CPU + MEM) -->
        <div class="panel">
          <div class="panel-title"><span class="icon">◈</span> TOP PROCESSES <span style="margin-left:auto" class="badge badge-dim" id="proc-count">-- procs</span></div>
          <table class="data-table">
            <thead><tr><th>PID</th><th>NAME</th><th>CPU %</th><th>MEM %</th><th>STATUS</th><th></th></tr></thead>
            <tbody id="proc-table"></tbody>
          </table>
        </div>
      </div>
      <div>
        <!-- GPU Status (util · VRAM · temp) -->
        <div class="panel" style="margin-bottom:12px">
          <div class="panel-title"><span class="icon">⚡</span> GPU STATUS</div>
          <div id="gpu-detail"><span class="color-dim">Loading GPU data...</span></div>
        </div>
        <!-- Heat / Temperatures -->
        <div class="panel">
          <div class="panel-title"><span class="icon">🌡</span> HEAT / TEMPERATURES</div>
          <div id="temps-panel"><span class="color-dim" style="font-family:'Share Tech Mono';font-size:0.7rem">No sensor data</span></div>
        </div>
      </div>
    </div>

    <!-- ══ CRYPTO TRADING DASHBOARD ══════════════════════════════════ -->
    <div class="panel" style="margin-bottom:12px;border:1px solid rgba(240,180,40,0.3)">
      <div class="panel-title" style="border-bottom:1px solid rgba(240,180,40,0.2);padding-bottom:8px;margin-bottom:10px">
        <span class="icon">💰</span> CRYPTO TRADING — LIVE
        <span style="margin-left:auto;display:flex;gap:6px;align-items:center">
          <span class="badge" id="crypto-mode-badge" style="padding:2px 8px">--</span>
          <span class="badge" id="crypto-exchange-badge" style="padding:2px 8px">--</span>
          <span id="crypto-bot-badge"></span>
          <span id="crypto-ai-badge"></span>
        </span>
      </div>

      <!-- Crypto KPIs -->
      <div class="grid-4" style="margin-bottom:10px">
        <div class="stat-card clipped" data-label="BALANCE" style="border-color:rgba(240,180,40,0.3)">
          <div class="stat-val color-gold" id="crypto-balance" style="font-size:1.6rem">$--</div>
          <div class="stat-sub">HWM: <span id="crypto-hwm">--</span> | DD: <span id="crypto-dd" class="color-green">0%</span></div>
        </div>
        <div class="stat-card clipped" data-label="P&L" style="border-color:rgba(0,255,136,0.3)">
          <div class="stat-val" id="crypto-pnl" style="font-size:1.6rem">$0.00</div>
          <div class="stat-sub">TRADES: <span id="crypto-trades">0</span> | WR: <span id="crypto-wr">0%</span></div>
        </div>
        <div class="stat-card clipped" data-label="POSITIONS" style="border-color:rgba(0,200,255,0.3)">
          <div class="stat-val color-cyan" id="crypto-positions" style="font-size:1.6rem">0</div>
          <div class="stat-sub">MAX: <span id="crypto-max-pos">--</span> | RISK: <span id="crypto-risk">--</span>%</div>
        </div>
        <div class="stat-card clipped" data-label="CONFIDENCE" style="border-color:rgba(0,200,255,0.3)">
          <div class="stat-val color-cyan" id="crypto-conf" style="font-size:1.6rem">--</div>
          <div class="stat-sub">TF: <span id="crypto-tf">--</span> | <span id="crypto-nsymbols">--</span> PAIRS</div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <!-- Left: Open Positions + Recent Trades -->
        <div>
          <div style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--gold);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px">Open Positions</div>
          <div id="crypto-open-positions" style="font-family:'Share Tech Mono';font-size:0.7rem;margin-bottom:12px;min-height:30px">
            <span class="color-dim">No open positions</span>
          </div>
          <div style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--gold);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px">Recent Trades</div>
          <div id="crypto-recent-trades" style="font-family:'Share Tech Mono';font-size:0.68rem;max-height:120px;overflow-y:auto">
            <span class="color-dim">No trades yet</span>
          </div>
        </div>
        <!-- Right: Log Tail -->
        <div>
          <div style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--gold);margin-bottom:6px;text-transform:uppercase;letter-spacing:1px">Bot Log (live)</div>
          <div id="crypto-log-terminal" style="font-family:'Share Tech Mono';font-size:0.62rem;background:rgba(0,0,0,0.4);border:1px solid var(--border);border-radius:4px;padding:6px 8px;max-height:180px;overflow-y:auto;line-height:1.5;white-space:pre-wrap;word-break:break-all">
            <span class="color-dim">Loading log...</span>
          </div>
        </div>
      </div>

      <!-- Pipeline Controls -->
      <div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(240,180,40,0.15);display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <span style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--dim);margin-right:6px">PIPELINE:</span>
        <button class="btn btn-green btn-sm" onclick="cryptoAction('start_all')">▶ START ALL</button>
        <button class="btn btn-red btn-sm" onclick="cryptoAction('stop_all')">■ STOP ALL</button>
        <span style="color:var(--border);margin:0 4px">|</span>
        <button class="btn btn-sm" style="background:rgba(0,200,255,0.15);color:var(--cyan);border:1px solid rgba(0,200,255,0.3)" onclick="cryptoAction('start_ai')">▶ AI SRV</button>
        <button class="btn btn-sm" style="background:rgba(0,200,255,0.15);color:var(--cyan);border:1px solid rgba(0,200,255,0.3)" onclick="cryptoAction('stop_ai')">■ AI SRV</button>
        <button class="btn btn-sm" style="background:rgba(240,180,40,0.15);color:var(--gold);border:1px solid rgba(240,180,40,0.3)" onclick="cryptoAction('start_bot')">▶ BOT</button>
        <button class="btn btn-sm" style="background:rgba(240,180,40,0.15);color:var(--gold);border:1px solid rgba(240,180,40,0.3)" onclick="cryptoAction('stop_bot')">■ BOT</button>
        <button class="btn btn-sm" style="background:rgba(0,255,136,0.1);color:var(--green);border:1px solid rgba(0,255,136,0.3)" onclick="cryptoAction('fetch_data')">↻ FETCH DATA</button>
        <span id="crypto-pipeline-msg" style="font-family:'Share Tech Mono';font-size:0.65rem;color:var(--dim);margin-left:8px"></span>
      </div>
    </div>

    <!-- ══ SERVICES + NETWORK (moved below the monitor row) ══════════════ -->
    <div class="grid-2">
      <!-- Service quick-status -->
      <div class="panel">
        <div class="panel-title"><span class="icon">⚙</span> SERVICE STATUS</div>
        <div id="svc-quick"></div>
      </div>
      <!-- Network + VPN quick -->
      <div class="panel">
        <div class="panel-title"><span class="icon">◉</span> NETWORK</div>
        <div id="net-quick"></div>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: AI MODELS
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-models" class="tab-pane">
    <div class="grid-2">
      <div class="panel">
        <div class="panel-title"><span class="icon">◈</span> INSTALLED MODELS</div>
        <div style="margin-bottom:10px;font-family:'Share Tech Mono';font-size:0.68rem;color:var(--dim)">
          TOTAL: <span id="model-count" class="color-gold">--</span> &nbsp;·&nbsp;
          ACTIVE: <span id="model-active-count" class="color-green">--</span> in VRAM
        </div>
        <div id="model-list">Loading...</div>
      </div>
      <div class="panel">
        <div class="panel-title"><span class="icon">⚡</span> QUICK STATS</div>
        <div id="model-stats">
          <div class="bar-wrap">
            <div class="bar-label"><span>VRAM IN USE</span><span id="vram-used-label">-- / --</span></div>
            <div class="bar"><div class="bar-fill bar-danger" id="bar-vram" style="width:0%"></div></div>
          </div>
        </div>
        <div style="margin-top:16px">
          <div class="panel-title"><span class="icon">▶</span> RUNNING IN VRAM</div>
          <div id="model-running" style="font-family:'Share Tech Mono';font-size:0.72rem;color:var(--dim)">No models loaded</div>
        </div>
        <div style="margin-top:16px">
          <div class="panel-title"><span class="icon">◎</span> OLLAMA STATUS</div>
          <div id="ollama-status" style="font-family:'Share Tech Mono';font-size:0.72rem"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: NETWORK
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-network" class="tab-pane">
    <!-- IP Summary -->
    <div class="grid-4" style="margin-bottom:12px">
      <div class="stat-card clipped" data-label="PUBLIC IP">
        <div class="stat-val color-cyan" id="kpi-public-ip" style="font-size:1.1rem;word-break:break-all">--</div>
        <div class="stat-sub">Through VPN / Direct</div>
      </div>
      <div class="stat-card clipped" data-label="LOCAL IP">
        <div class="stat-val color-gold" id="kpi-local-ip" style="font-size:1.1rem">--</div>
        <div class="stat-sub">LAN Address</div>
      </div>
      <div class="stat-card clipped" data-label="VPN">
        <div id="kpi-vpn-status" style="font-family:'Orbitron';font-size:1.1rem;font-weight:700;color:var(--green)">--</div>
        <div class="stat-sub" id="kpi-vpn-iface">--</div>
      </div>
      <div class="stat-card clipped" data-label="CONNECTIONS">
        <div class="stat-val color-orange" id="kpi-net-conns">--</div>
        <div class="stat-sub">Active Connections</div>
      </div>
    </div>

    <div class="grid-3">
      <div class="panel">
        <div class="panel-title"><span class="icon">◉</span> NETWORK INTERFACES</div>
        <div id="iface-list">Loading...</div>
      </div>
      <div class="panel">
        <div class="panel-title"><span class="icon">🔒</span> VPN &amp; SERVICES</div>
        <div id="vpn-status">Checking...</div>
        <div style="margin-top:16px">
          <div class="panel-title"><span class="icon">✈️</span> TELEGRAM BOT</div>
          <div id="telegram-status">Checking...</div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-title"><span class="icon">◈</span> LISTENING SERVICES</div>
        <div style="font-family:'Share Tech Mono';font-size:0.72rem;margin-bottom:8px">
          TOTAL CONNECTIONS: <span id="net-conns" class="color-cyan">--</span>
        </div>
        <div id="port-list" style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--text2);line-height:1.8"></div>
      </div>
    </div>

    <!-- Bandwidth -->
    <div class="panel" style="margin-bottom:12px">
      <div class="panel-title"><span class="icon">↕</span> BANDWIDTH</div>
      <div class="grid-2">
        <div>
          <div class="bar-label"><span>↑ SENT</span><span id="net-sent" class="color-cyan">-- MB</span></div>
          <div class="bar"><div class="bar-fill bar-cyan" id="bar-sent" style="width:30%"></div></div>
        </div>
        <div>
          <div class="bar-label"><span>↓ RECV</span><span id="net-recv" class="color-gold">-- MB</span></div>
          <div class="bar"><div class="bar-fill bar-gold" id="bar-recv" style="width:30%"></div></div>
        </div>
      </div>
    </div>

    <!-- Live connections table -->
    <div class="panel">
      <div class="panel-title"><span class="icon">⚡</span> LIVE CONNECTIONS <span class="badge badge-dim" style="margin-left:auto" id="conn-count-badge">--</span></div>
      <div style="max-height:300px;overflow-y:auto">
        <table class="data-table">
          <thead><tr><th>LOCAL</th><th>REMOTE</th><th>PID</th><th>PROCESS</th></tr></thead>
          <tbody id="conn-table"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: SECURITY / KALI
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-security" class="tab-pane">

    <!-- ══ Security Command Center — KPI row ══ -->
    <div class="grid-4" style="margin-bottom:12px" id="sec-kpi-row">
      <div class="stat-card clipped" data-label="RISK LEVEL">
        <div class="stat-val" id="sec-risk" style="font-size:1.4rem;color:var(--green)">--</div>
        <div class="stat-sub" id="sec-scan-time">last scan: --</div>
      </div>
      <div class="stat-card clipped" data-label="CONNECTIONS">
        <div class="stat-val color-cyan" id="sec-conns">--</div>
        <div class="stat-sub"><span id="sec-established">--</span> active · <span id="sec-listening">--</span> listening</div>
      </div>
      <div class="stat-card clipped" data-label="REMOTE IPs">
        <div class="stat-val color-gold" id="sec-remote-ips">--</div>
        <div class="stat-sub">unique external IPs</div>
      </div>
      <div class="stat-card clipped" data-label="VPN">
        <div class="stat-val" id="sec-vpn" style="font-size:1.1rem;color:var(--red)">--</div>
        <div class="stat-sub" id="sec-vpn-iface">checking...</div>
      </div>
    </div>

    <!-- ══ Security Command Center — Main Panel ══ -->
    <div class="panel" style="margin-bottom:12px;border-color:rgba(0,200,255,0.3)">
      <div class="panel-title">
        <span class="icon">🛡️</span> SECURITY COMMAND CENTER
        <span id="sec-center-badge" class="badge badge-dim" style="margin-left:8px">CHECKING...</span>
        <div style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn btn-gold btn-sm" onclick="secCmd('quick')">⚡ QUICK</button>
          <button class="btn btn-cyan btn-sm" onclick="secCmd('investigate')">🔍 INVESTIGATE</button>
          <button class="btn btn-cyan btn-sm" onclick="secCmd('hunt')">🎯 HUNT</button>
          <button class="btn btn-green btn-sm" onclick="secCmd('traffic')">📡 TRAFFIC</button>
          <button class="btn btn-sm" style="color:var(--orange);border-color:var(--orange)" onclick="secCmd('firewall')">🧱 FIREWALL</button>
          <button class="btn btn-red btn-sm" onclick="secCmd('audit')">⚔ FULL AUDIT</button>
          <button class="btn btn-sm" style="color:var(--dim);border-color:var(--dim)" onclick="secCmd('modules')">📦 MODULES</button>
        </div>
      </div>
      <!-- Warnings bar -->
      <div id="sec-warnings" style="display:none;background:rgba(255,56,96,0.08);border:1px solid rgba(255,56,96,0.3);padding:8px 12px;margin-bottom:10px;font-family:'Share Tech Mono';font-size:0.7rem;color:var(--red)"></div>
      <!-- Output terminal -->
      <div id="sec-cmd-terminal" class="terminal" style="height:300px">
        <span class="t-dim">// Click any button above to run a Security Command Center operation</span><br>
        <span class="t-dim">// ⚡ QUICK  — fast system snapshot (~2s)</span><br>
        <span class="t-dim">// 🔍 INVESTIGATE — deep port analysis with geolocation (~3-5s)</span><br>
        <span class="t-dim">// 🎯 HUNT  — network discovery + services + OS fingerprint</span><br>
        <span class="t-dim">// 📡 TRAFFIC — flow analysis + anomaly detection</span><br>
        <span class="t-dim">// 🧱 FIREWALL — firewall effectiveness test</span><br>
        <span class="t-dim">// ⚔ FULL AUDIT — all modules (30-60s)</span>
      </div>
      <!-- Module status pills -->
      <div id="sec-module-pills" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px;padding-top:8px;border-top:1px solid var(--border)"></div>
    </div>

    <!-- ══ Port Investigator + Quick Scan ══ -->
    <div class="grid-2" style="margin-bottom:12px">
      <!-- Port Investigator -->
      <div class="panel">
        <div class="panel-title"><span class="icon">🔍</span> PORT INVESTIGATOR (live)</div>
        <div style="font-family:'Share Tech Mono';font-size:0.65rem;color:var(--dim);margin-bottom:8px">
          Enriches connections with process info, geo &amp; reverse DNS
        </div>
        <div class="input-row">
          <input id="portinv-port-sec" placeholder="port (blank=all)" style="flex:0 0 150px">
          <label style="display:flex;align-items:center;gap:5px;font-family:'Share Tech Mono';font-size:0.65rem;color:var(--dim);white-space:nowrap">
            <input type="checkbox" id="portinv-nogeo-sec"> Skip Geo
          </label>
          <button class="btn btn-cyan" onclick="secInvestigate()">▶ INVESTIGATE</button>
        </div>
        <div id="portinv-output" class="terminal" style="height:220px">
          <span class="t-dim">// Port investigator shows process, geo, and DNS for each connection</span>
        </div>
      </div>

      <!-- Quick security assessment (original) -->
      <div class="panel">
        <div class="panel-title"><span class="icon">⚙</span> LOCAL SECURITY CHECKS
          <button class="btn btn-gold btn-sm" style="margin-left:auto" onclick="doQuickScan()">▶ RUN</button>
        </div>
        <div id="quickscan-results" style="font-family:'Share Tech Mono';font-size:0.72rem">
          <span class="color-dim">Click RUN to check system security posture</span>
        </div>
        <div style="margin-top:12px">
          <div class="panel-title"><span class="icon">◈</span> EXPOSED SERVICES</div>
          <div id="sec-exposed" style="font-family:'Share Tech Mono';font-size:0.7rem;color:var(--dim)">
            Run QUICK scan to populate
          </div>
        </div>
      </div>
    </div>

    <!-- ══ nmap + Kali ══ -->
    <div class="grid-2" style="margin-bottom:12px">
      <!-- Network sweep -->
      <div class="panel">
        <div class="panel-title"><span class="icon">◉</span> NETWORK SWEEP (nmap ping)</div>
        <div class="input-row">
          <input id="sweep-target" value="10.0.0.0/24" placeholder="10.0.0.0/24">
          <button class="btn btn-cyan" onclick="doSweep()">▶ SCAN</button>
        </div>
        <div id="sweep-log" class="terminal">
          <span class="t-dim">// Enter subnet and press SCAN</span>
        </div>
      </div>

      <!-- Port scan -->
      <div class="panel">
        <div class="panel-title"><span class="icon">⚔</span> PORT SCAN (nmap)</div>
        <div class="input-row">
          <input id="port-target" value="localhost" placeholder="host / IP">
          <input id="port-range" value="1-65535" placeholder="ports" style="flex:0 0 110px">
          <button class="btn btn-gold" onclick="doPortScan()">▶ SCAN</button>
        </div>
        <div id="port-log" class="terminal">
          <span class="t-dim">// For large port ranges (&gt;5000), version detection is disabled for speed</span>
        </div>
      </div>
    </div>

    <!-- ══ Kali Tools ══ -->
    <div class="panel" style="margin-bottom:12px">
      <div class="panel-title"><span class="icon">⚔</span> KALI TOOLS — QUICK LAUNCH</div>
      <div class="input-row">
        <input id="kali-target" placeholder="target IP, domain, or URL" style="flex:2">
        <select id="kali-tool" style="flex:0 0 160px;background:rgba(0,0,0,0.5);border:1px solid var(--border);color:var(--text);padding:8px;font-family:'Share Tech Mono';font-size:0.7rem">
          <option value="whatweb">WhatWeb (Web Tech)</option>
          <option value="nikto">Nikto (Web Vulns)</option>
          <option value="whois">WHOIS Lookup</option>
          <option value="dig">DNS Dig</option>
          <option value="traceroute">Traceroute</option>
          <option value="sslscan">SSL Scan</option>
        </select>
        <button class="btn btn-cyan" onclick="runKaliTool()">▶ RUN</button>
      </div>
      <div id="kali-log" class="terminal" style="height:220px">
        <span class="t-dim">// Select a tool and target, then press RUN</span>
      </div>
    </div>

    <!-- ══ Listening Services ══ -->
    <div class="panel">
      <div class="panel-title"><span class="icon">▶</span> LOCAL LISTENING SERVICES (live)</div>
      <table class="data-table">
        <thead><tr><th>PORT</th><th>BIND IP</th><th>PROTO</th><th>PID</th><th>PROCESS</th></tr></thead>
        <tbody id="listen-table"></tbody>
      </table>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: SERVICES
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-services" class="tab-pane">
    <div class="grid-2">
      <div class="panel">
        <div class="panel-title"><span class="icon">⚙</span> MANAGED SERVICES</div>
        <div id="svc-list">Loading...</div>
      </div>
      <div class="panel">
        <div class="panel-title"><span class="icon">◎</span> SERVICE LOG</div>
        <div id="svc-log" class="terminal">
          <span class="t-dim">// Actions will appear here</span>
        </div>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: AI ACTIVITY
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-activity" class="tab-pane">
    <div class="grid-main" style="grid-template-columns:1fr 320px">
      <div class="panel">
        <div class="panel-title"><span class="icon">⚡</span> LIVE AI ACTIVITY STREAM
          <span style="margin-left:auto;display:flex;gap:8px;align-items:center">
            <span class="badge badge-dim" id="activity-count">0 events</span>
            <span id="activity-pulse" class="status-dot" style="width:6px;height:6px"></span>
            <button class="btn btn-red btn-sm" style="padding:2px 8px;font-size:0.5rem" onclick="clearActivity()">CLEAR</button>
          </span>
        </div>
        <div id="activity-terminal" class="terminal activity-term">
          <div class="t-dim">// Waiting for AI activity...</div>
          <div class="t-dim">// agent_v2.py and telegram_bot.py events appear here in real-time</div>
        </div>
      </div>
      <div>
        <div class="panel" style="margin-bottom:12px">
          <div class="panel-title"><span class="icon">◈</span> AGENT STATUS</div>
          <div id="activity-agents">
            <div class="iface-row"><span class="iface-name">Agent v2 (CLI)</span><span id="agent-v2-status" class="badge badge-dim">IDLE</span></div>
            <div class="iface-row"><span class="iface-name">Telegram Bot</span><span id="tg-bot-status" class="badge badge-dim">IDLE</span></div>
            <div class="iface-row"><span class="iface-name">Ollama Backend</span><span id="ollama-activity-status" class="badge badge-dim">IDLE</span></div>
          </div>
        </div>
        <div class="panel" style="margin-bottom:12px">
          <div class="panel-title"><span class="icon">◎</span> LAST MODEL USED</div>
          <div id="activity-last-model" style="font-family:'Share Tech Mono';font-size:0.8rem;color:var(--cyan)">--</div>
          <div style="margin-top:8px">
            <div class="panel-title"><span class="icon">▶</span> CONTEXT WINDOW</div>
            <div id="activity-ctx-info" style="font-family:'Share Tech Mono';font-size:0.72rem;color:var(--dim)">--</div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-title"><span class="icon">⬡</span> EVENT STATS</div>
          <div id="activity-stats" style="font-family:'Share Tech Mono';font-size:0.72rem">
            <div class="iface-row"><span class="iface-name">Queries</span><span id="stat-queries" class="color-gold">0</span></div>
            <div class="iface-row"><span class="iface-name">Generations</span><span id="stat-gens" class="color-cyan">0</span></div>
            <div class="iface-row"><span class="iface-name">RAG Searches</span><span id="stat-rag" class="color-green">0</span></div>
            <div class="iface-row"><span class="iface-name">Tool Calls</span><span id="stat-tools" class="color-orange">0</span></div>
            <div class="iface-row"><span class="iface-name">Errors</span><span id="stat-errors" class="color-red">0</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: DB (PROMPTS / SCRIPTS / APPS)
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-db" class="tab-pane">
    <div class="grid-2">
      <div class="panel">
        <div class="panel-title"><span class="icon">◆</span> FILE MANAGER</div>
        <div style="display:flex;gap:6px;margin-bottom:12px">
          <button class="btn btn-cyan btn-sm" onclick="loadDB('prompts')">PROMPTS</button>
          <button class="btn btn-gold btn-sm" onclick="loadDB('scripts')">SCRIPTS</button>
          <button class="btn btn-green btn-sm" onclick="loadDB('apps')">APPS</button>
          <button class="btn btn-sm" style="color:var(--dim);border-color:var(--dim)" onclick="loadDB('')">ALL</button>
        </div>
        <div id="db-file-list" style="font-family:'Share Tech Mono';font-size:0.72rem">Loading...</div>
      </div>
      <div class="panel">
        <div class="panel-title"><span class="icon">◎</span> EDITOR</div>
        <div class="input-row">
          <select id="db-cat-select" style="flex:0 0 120px">
            <option value="prompts">prompts</option>
            <option value="scripts">scripts</option>
            <option value="apps">apps</option>
          </select>
          <input id="db-filename" placeholder="filename.txt">
          <button class="btn btn-gold btn-sm" onclick="saveDB()">SAVE</button>
        </div>
        <textarea id="db-editor" style="width:100%;height:300px;background:rgba(0,0,0,0.4);border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono';font-size:0.72rem;padding:10px;resize:vertical;outline:none" placeholder="File contents..."></textarea>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: CHAT
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-chat" class="tab-pane">
    <div class="panel">
      <div class="panel-title"><span class="icon">◎</span> LARRY G-FORCE AI CHAT
        <span style="margin-left:auto;display:flex;gap:6px">
          <button class="btn btn-green btn-sm" style="padding:3px 8px;font-size:0.5rem" onclick="saveChatHistory()">SAVE</button>
          <button class="btn btn-cyan btn-sm" style="padding:3px 8px;font-size:0.5rem" onclick="loadChatHistoryList()">LOAD</button>
          <span class="badge badge-dim" id="chat-model-label">dolphin-mistral</span>
        </span>
      </div>
      <div id="chat-history"></div>
      <div class="chat-controls">
        <select id="chat-model">
          <option value="dolphin-mistral:latest">dolphin-mistral:latest</option>
        </select>
        <input id="chat-input" placeholder="Send a message to Larry..." onkeydown="if(event.key==='Enter')sendChat()">
        <button class="btn btn-gold" onclick="sendChat()">SEND ▶</button>
        <button class="btn btn-cyan btn-sm" onclick="clearChat()">CLR</button>
      </div>
    </div>
  </div>

  <!-- ════════════════════════════════════════════════════════
       TAB: TOOLS (Bash Scripts · Port Investigator · Agent Dispatch)
  ════════════════════════════════════════════════════════════ -->
  <div id="tab-tools" class="tab-pane">

    <!-- ══ Autonomous Agent Dispatch ══ -->
    <div class="panel" style="margin-bottom:12px;border:1px solid rgba(240,180,40,0.3)">
      <div class="panel-title" style="margin-bottom:10px">
        <span class="icon">🤖</span> AUTONOMOUS AGENT DISPATCH
        <span id="tools-status-badge" class="badge badge-dim" style="margin-left:auto">CHECKING...</span>
      </div>
      <div style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--dim);margin-bottom:10px">
        Type a task in natural language — the agent will autonomously pick and run the right tool.
        Results appear in the <strong style="color:var(--gold)">AI ACTIVITY</strong> stream.
      </div>
      <div class="input-row">
        <input id="dispatch-input" placeholder="e.g. run quick security scan / investigate ports / verify network / run nmap 192.168.1.1"
               style="flex:1" onkeydown="if(event.key==='Enter')agentDispatch()">
        <button class="btn btn-gold" onclick="agentDispatch()">▶ DISPATCH</button>
      </div>
      <div id="dispatch-log" class="terminal" style="height:120px">
        <span class="t-dim">// Dispatch results appear here and in the AI Activity stream</span>
      </div>
      <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
        <span style="font-family:'Share Tech Mono';font-size:0.62rem;color:var(--dim)">QUICK TASKS:</span>
        <button class="btn btn-cyan btn-sm" onclick="quickDispatch('run quick security scan')">🛡 Quick Scan</button>
        <button class="btn btn-cyan btn-sm" onclick="quickDispatch('investigate ports and connections')">🔍 Port Inv.</button>
        <button class="btn btn-cyan btn-sm" onclick="quickDispatch('hunt network discover hosts')">🎯 Net Hunt</button>
        <button class="btn btn-cyan btn-sm" onclick="quickDispatch('verify network connectivity')">📡 Verify Net</button>
        <button class="btn btn-gold btn-sm" onclick="quickDispatch('full audit everything')">⚔ Full Audit</button>
        <button class="btn btn-green btn-sm" onclick="quickDispatch('run looting larry network discovery')">🏴 Looting</button>
      </div>
    </div>

    <div class="grid-2">

      <!-- ══ Bash Script Runner ══ -->
      <div class="panel">
        <div class="panel-title">
          <span class="icon">🐚</span> BASH SECURITY SCRIPTS
          <button class="btn btn-cyan btn-sm" style="margin-left:auto" onclick="loadBashScripts()">↻ REFRESH</button>
        </div>
        <div id="bash-script-list" style="font-family:'Share Tech Mono';font-size:0.72rem;margin-bottom:12px">
          <span class="t-dim">Loading scripts...</span>
        </div>
        <div style="border-top:1px solid var(--border);padding-top:10px;margin-top:4px">
          <div class="panel-title" style="margin-bottom:8px"><span class="icon">▶</span> RUN SCRIPT</div>
          <div class="input-row">
            <select id="bash-key-select" style="flex:0 0 180px;background:rgba(0,0,0,0.5);border:1px solid var(--border);color:var(--text);padding:8px;font-family:'Share Tech Mono';font-size:0.7rem">
              <option value="">Select script...</option>
              <option value="verify-network">verify-network</option>
              <option value="homelab-audit">homelab-audit</option>
              <option value="looting-scan">looting-scan</option>
              <option value="scan-ipv6">scan-ipv6</option>
            </select>
            <input id="bash-args-input" placeholder="extra args (optional)">
            <button class="btn btn-gold" onclick="runBashScript()">▶ RUN</button>
          </div>
          <div id="bash-run-log" class="terminal" style="height:100px">
            <span class="t-dim">// Script output goes to Activity stream</span>
          </div>
        </div>
      </div>

      <!-- ══ Port Investigator ══ -->
      <div class="panel">
        <div class="panel-title">
          <span class="icon">🔍</span> PORT INVESTIGATOR
        </div>
        <div style="font-family:'Share Tech Mono';font-size:0.68rem;color:var(--dim);margin-bottom:10px">
          Deep-dive local connections with geolocation and process info.
        </div>
        <div class="input-row">
          <input id="portinv-port" placeholder="port number (blank = all)" style="flex:0 0 180px">
          <label style="display:flex;align-items:center;gap:6px;font-family:'Share Tech Mono';font-size:0.68rem;color:var(--dim)">
            <input type="checkbox" id="portinv-nogeo"> Skip Geo
          </label>
          <button class="btn btn-cyan" onclick="runPortInvestigator()">▶ INVESTIGATE</button>
        </div>
        <div id="portinv-log" class="terminal" style="height:260px">
          <span class="t-dim">// Click INVESTIGATE to analyze active connections</span>
        </div>
        <div style="margin-top:8px;display:flex;gap:6px">
          <button class="btn btn-gold btn-sm" onclick="runSecurityOp('quick')">🛡 Quick Scan</button>
          <button class="btn btn-cyan btn-sm" onclick="runSecurityOp('hunt')">🎯 Hunt</button>
          <button class="btn btn-green btn-sm" onclick="runSecurityOp('modules')">📦 Modules</button>
        </div>
        <div id="secop-log" class="terminal" style="height:80px;margin-top:8px">
          <span class="t-dim">// Security operation results</span>
        </div>
      </div>
    </div>

    <!-- ══ Security Modules Status ══ -->
    <div class="panel" style="margin-top:12px">
      <div class="panel-title">
        <span class="icon">📦</span> SECURITY MODULES STATUS
        <button class="btn btn-cyan btn-sm" style="margin-left:auto" onclick="loadModuleStatus()">↻ CHECK</button>
      </div>
      <div id="sec-modules-grid" class="grid-4" style="margin-top:10px;margin-bottom:0">
        <span class="t-dim" style="font-family:'Share Tech Mono';font-size:0.7rem">Click CHECK to load module status</span>
      </div>
    </div>

  </div>

  <!-- ════ FOOTER ════ -->
  <div class="dashboard-footer">
    <span class="accent">LARRY G-FORCE</span> COMMAND CENTRAL v4.0 &mdash; ALL SYSTEMS LOCAL &mdash; PORT 3777
  </div>

</div><!-- #app -->

<script>
'use strict';

// ── State ────────────────────────────────────────────────────────────
const state = { health: {}, gpu: [], models: [], running: [], network: {}, services: {}, procs: [] };

// ── Tab switching ─────────────────────────────────────────────────────
function showTab(id) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  event.target.classList.add('active');
  if (id === 'models')   refreshModels();
  if (id === 'network')  refreshNetwork();
  if (id === 'security') { refreshListening(); secCenterInit(); }
  if (id === 'services') refreshServices();
  if (id === 'activity') refreshActivity();
  if (id === 'tools')    initToolsTab();
  if (id === 'db')       loadDB('');
}

// ── Clock ─────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toTimeString().split(' ')[0];
}
setInterval(updateClock, 1000); updateClock();

// ── Helpers ───────────────────────────────────────────────────────────
const pct = v => `${v}%`;
const setW = (id, v) => { const el = document.getElementById(id); if(el) el.style.width = v + '%'; };
const setText = (id, v) => { const el = document.getElementById(id); if(el) el.textContent = v; };
const barColor = (v) => v > 85 ? 'bar-danger' : v > 60 ? 'bar-gold' : 'bar-cyan';

function badge(on, label='') {
  if (on === true) return `<span class="badge badge-on">● ONLINE${label ? ' · '+label : ''}</span>`;
  if (on === 'warn') return `<span class="badge badge-warn">⚠ ${label||'WARN'}</span>`;
  return `<span class="badge badge-off">○ OFFLINE</span>`;
}

function svcLog(msg, cls='') {
  const el = document.getElementById('svc-log');
  el.innerHTML += `<div class="${cls || ''}">> ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}

// ── Fetch health ──────────────────────────────────────────────────────
async function refreshHealth() {
  try {
    const d = await fetch('/api/health').then(r => r.json());
    const h = d.system || {};
    const g = d.gpu || [];
    state.health = h; state.gpu = g; state.procs = d.processes || [];

    // KPI
    if (h.cpu_percent !== undefined) {
      const cpu = h.cpu_percent;
      document.getElementById('kpi-cpu').textContent = cpu + '%';
      document.getElementById('kpi-cores').textContent = h.cpu_cores || '--';
      document.getElementById('kpi-freq').textContent = h.cpu_freq || '--';
      setW('bar-cpu', cpu);
      // change bar colour
      const bc = document.getElementById('bar-cpu');
      bc.className = 'bar-fill ' + barColor(cpu);
    }
    if (h.mem_percent !== undefined) {
      document.getElementById('kpi-mem').textContent = h.mem_percent + '%';
      document.getElementById('kpi-mem-detail').textContent = h.mem_used_gb + ' / ' + h.mem_total_gb + ' GB';
      setW('bar-mem', h.mem_percent);
      const bm = document.getElementById('bar-mem');
      bm.className = 'bar-fill ' + barColor(h.mem_percent);
    }
    if (h.disk_percent !== undefined) {
      document.getElementById('kpi-disk').textContent = h.disk_percent + '%';
      document.getElementById('kpi-disk-detail').textContent = h.disk_used_gb + ' / ' + h.disk_total_gb + ' GB';
      setW('bar-disk', h.disk_percent);
    }

    // Uptime
    if (h.uptime) setText('uptime-val', h.uptime);
    if (h.processes) setText('proc-count', h.processes + ' procs');

    // GPU KPI
    if (g.length > 0) {
      const gp = g[0];
      document.getElementById('kpi-gpu-util').textContent = gp.util + '%';
      document.getElementById('kpi-gpu-detail').textContent = gp.mem_used + ' / ' + gp.mem_total + ' MB';
      const pctV = Math.round(gp.mem_used / gp.mem_total * 100);
      setW('bar-gpu', pctV);
    }

    // GPU detail panel
    let gpuHtml = '';
    if (g.length === 0) {
      gpuHtml = '<span style="font-family:\'Share Tech Mono\';font-size:0.72rem;color:var(--dim)">No NVIDIA GPU detected</span>';
    } else {
      g.forEach(gp => {
        const mp = Math.round(parseInt(gp.mem_used) / parseInt(gp.mem_total) * 100);
        gpuHtml += `
          <div style="margin-bottom:10px">
            <div style="font-family:'Orbitron',sans-serif;font-size:0.7rem;color:var(--gold);margin-bottom:8px">${gp.name}</div>
            <div class="grid-3">
              <div><div class="bar-label"><span>GPU UTIL</span><span class="color-orange">${gp.util}%</span></div>
                <div class="bar"><div class="bar-fill bar-danger" style="width:${gp.util}%"></div></div></div>
              <div><div class="bar-label"><span>VRAM</span><span class="color-cyan">${gp.mem_used}/${gp.mem_total} MB</span></div>
                <div class="bar"><div class="bar-fill bar-cyan" style="width:${mp}%"></div></div></div>
              <div><div class="bar-label"><span>TEMP</span><span class="color-gold">${gp.temp}°C</span></div>
                <div class="bar"><div class="bar-fill bar-gold" style="width:${Math.min(100,gp.temp)}%"></div></div></div>
            </div>
            ${gp.power !== 'N/A' ? `<div style="font-family:'Share Tech Mono';font-size:0.65rem;color:var(--dim);margin-top:4px">POWER: ${gp.power} W</div>` : ''}
          </div>`;
      });
    }
    document.getElementById('gpu-detail').innerHTML = gpuHtml;

    // Temperatures — map sensor names to friendly labels
    const TEMP_LABELS = {
      k10temp:'CPU', coretemp:'CPU', zenpower:'CPU',
      amdgpu:'GPU', nouveau:'GPU', nvidia:'GPU',
      nvme:'NVMe SSD', iwlwifi_1:'WiFi Card',
      acpitz:'Motherboard', pch:'Chipset PCH',
      it8686:'Motherboard VRM', nct6775:'Fan Controller',
    };
    const temps = h.temperatures || {};
    const tColor = v => (v > 80 ? 'color-red' : v > 65 ? 'color-orange' : 'color-green');
    let tempRows = [];
    // GPU temp comes from nvidia-smi (psutil exposes no temp sensors on Windows)
    if (g.length > 0 && g[0].temp !== undefined && g[0].temp !== 'N/A') {
      const gv = parseInt(g[0].temp);
      tempRows.push(`<div class="iface-row"><span class="iface-name">GPU · ${g[0].name}</span><span class="${tColor(gv)}" style="font-family:'Orbitron';font-size:0.8rem">${gv}°C</span></div>`);
    }
    Object.keys(temps).forEach(k => {
      const v = temps[k];
      const label = TEMP_LABELS[k] || k;
      tempRows.push(`<div class="iface-row"><span class="iface-name">${label}</span><span class="${tColor(v)}" style="font-family:'Orbitron';font-size:0.8rem">${v}°C</span></div>`);
    });
    const hasCpu = Object.keys(temps).some(k => (TEMP_LABELS[k] || '').includes('CPU'));
    if (!hasCpu) {
      tempRows.push('<div class="iface-row"><span class="iface-name color-dim">CPU die</span><span class="color-dim" style="font-family:\'Share Tech Mono\';font-size:0.6rem">install HWiNFO/LHM to read</span></div>');
    }
    document.getElementById('temps-panel').innerHTML = tempRows.length
      ? tempRows.join('')
      : '<span style="font-family:\'Share Tech Mono\';font-size:0.7rem;color:var(--dim)">No sensor data</span>';

    // Processes table with KILL button
    let procHtml = '';
    state.procs.forEach(p => {
      const cpuCls = p.cpu > 50 ? 'color-red' : p.cpu > 20 ? 'color-orange' : 'color-green';
      procHtml += `<tr><td class="color-dim">${p.pid}</td><td>${p.name}</td>
        <td class="${cpuCls}">${p.cpu}%</td><td class="color-gold">${p.mem}%</td>
        <td><span class="badge ${p.status==='running'?'badge-on':'badge-dim'}">${p.status}</span></td>
        <td><button class="btn btn-red btn-sm" style="padding:2px 6px;font-size:0.5rem" onclick="killProc(${p.pid},'${p.name}')">KILL</button></td></tr>`;
    });
    document.getElementById('proc-table').innerHTML = procHtml;

  } catch(e) { console.warn('health fetch error', e); }
}

// ── Fetch models ──────────────────────────────────────────────────────
async function refreshModels() {
  try {
    const d = await fetch('/api/ollama').then(r => r.json());
    state.models = d.models || [];
    state.running = d.running || [];

    const ollamaUp = state.models.length > 0 || state.running.length > 0;
    document.getElementById('ollama-dot').style.background = ollamaUp ? 'var(--green)' : 'var(--red)';
    document.getElementById('ollama-dot').style.boxShadow = ollamaUp ? '0 0 8px var(--green)' : '0 0 8px var(--red)';

    setText('model-count', state.models.length);
    setText('model-active-count', state.running.length);

    // populate chat model select — PRESERVE current selection
    const sel = document.getElementById('chat-model');
    const prevModel = sel.value || localStorage.getItem('larry_chat_model') || '';
    sel.innerHTML = '';
    state.models.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.name; opt.textContent = m.name;
      sel.appendChild(opt);
    });
    // Restore user's selection, fallback to dolphin-mistral, then first available
    if (prevModel && [...sel.options].some(o => o.value === prevModel)) {
      sel.value = prevModel;
    } else if ([...sel.options].some(o => o.value === 'dolphin-mistral:latest')) {
      sel.value = 'dolphin-mistral:latest';
    }
    // Persist choice
    sel.onchange = () => localStorage.setItem('larry_chat_model', sel.value);

    // Model list with UNLOAD button for running models
    let html = '';
    state.models.forEach(m => {
      const isRunning = state.running.includes(m.name);
      html += `<div class="model-card ${isRunning?'active-model':''}">
        <div>
          <div class="model-name">${m.name}</div>
          <div class="model-size">${m.size_gb} GB · ${m.modified}</div>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          ${isRunning ? '<span class="badge badge-on">IN VRAM</span><button class="btn btn-red btn-sm" style="padding:2px 6px;font-size:0.5rem" onclick="unloadModel(\''+m.name+'\')">UNLOAD</button>' : '<span class="badge badge-dim">IDLE</span>'}
        </div>
      </div>`;
    });
    if (html === '') html = '<span style="font-family:\'Share Tech Mono\';font-size:0.72rem;color:var(--dim)">Ollama not running or no models installed</span>';
    document.getElementById('model-list').innerHTML = html;

    // Running in VRAM
    if (state.running.length > 0) {
      document.getElementById('model-running').innerHTML = state.running.map(
        m => `<div class="badge badge-on" style="margin:2px 0;display:block">${m}</div>`).join('');
    } else {
      document.getElementById('model-running').innerHTML = '<span style="color:var(--dim)">No models loaded</span>';
    }

    // Ollama status
    document.getElementById('ollama-status').innerHTML =
      ollamaUp ? `${badge(true)} <span class="color-dim" style="margin-left:8px">localhost:11434</span>`
               : badge(false);

    // VRAM bar (from GPU data)
    if (state.health.gpu && state.health.gpu !== undefined) {
      // handled in health
    }

    // Overview service quick panel
    refreshServicesQuick();
  } catch(e) { console.warn('ollama fetch', e); }
}

// ── Fetch network ─────────────────────────────────────────────────────
async function refreshNetwork() {
  try {
    const d = await fetch('/api/network').then(r => r.json());
    state.network = d;

    // Public IP KPI
    const pubIpEl = document.getElementById('kpi-public-ip');
    if (pubIpEl) pubIpEl.textContent = d.public_ip || '--';

    // Local IP KPI — find first non-loopback UP interface
    const mainIface = (d.interfaces || []).find(i => i.up && i.ip !== '127.0.0.1' && !i.ip.startsWith('172.17') && !i.ip.startsWith('192.168.122')) || {};
    const localIpEl = document.getElementById('kpi-local-ip');
    if (localIpEl) localIpEl.textContent = mainIface.ip || '--';

    // VPN KPI
    const vpns = d.vpn || [];
    const vpnActive = vpns.some(v => v.up);
    const vpnStatEl = document.getElementById('kpi-vpn-status');
    const vpnIfEl = document.getElementById('kpi-vpn-iface');
    if (vpnStatEl) {
      vpnStatEl.textContent = vpnActive ? 'PROTECTED' : 'EXPOSED';
      vpnStatEl.style.color = vpnActive ? 'var(--green)' : 'var(--red)';
    }
    if (vpnIfEl) vpnIfEl.textContent = vpnActive ? vpns.find(v=>v.up).name : 'No VPN active';

    // Connections KPI
    const connKpi = document.getElementById('kpi-net-conns');
    if (connKpi) connKpi.textContent = d.connections || 0;

    // Interfaces
    let ifHtml = '';
    (d.interfaces || []).forEach(iface => {
      ifHtml += `<div class="iface-row">
        <span class="iface-name">${iface.name} ${iface.up ? '<span class="badge badge-on" style="padding:1px 5px">UP</span>' : '<span class="badge badge-off" style="padding:1px 5px">DOWN</span>'}</span>
        <span class="iface-ip">${iface.ip || '--'}</span>
      </div>`;
    });
    document.getElementById('iface-list').innerHTML = ifHtml || '<span style="font-family:\'Share Tech Mono\';font-size:0.72rem;color:var(--dim)">No interfaces</span>';

    // VPN
    if (vpns.length === 0) {
      document.getElementById('vpn-status').innerHTML = badge(false) + ' <span style="font-family:\'Share Tech Mono\';font-size:0.7rem;color:var(--dim);margin-left:8px">No VPN interfaces detected</span>';
    } else {
      document.getElementById('vpn-status').innerHTML = vpns.map(
        v => `<div style="margin-bottom:6px">${badge(v.up, v.name)} <span style="font-family:\'Share Tech Mono\';font-size:0.7rem;color:var(--cyan);margin-left:8px">${v.name}</span></div>`
      ).join('');
    }

    // Telegram
    const tg = d.telegram || {};
    document.getElementById('telegram-status').innerHTML =
      tg.running
        ? `${badge(true)} <span style="font-family:\'Share Tech Mono\';font-size:0.7rem;color:var(--dim);margin-left:8px">PID ${tg.pid}</span>`
        : badge(false) + ' <span style="font-family:\'Share Tech Mono\';font-size:0.7rem;color:var(--dim);margin-left:8px">Bot not running</span>';

    // Connections / listening ports
    setText('net-conns', d.connections || 0);
    const lPorts = (d.listening_ports || []).map(
      p => `<span style="margin-right:6px;color:var(--cyan)">${p}</span>`).join('');
    document.getElementById('port-list').innerHTML = lPorts || '<span style="color:var(--dim)">none</span>';

    // Bandwidth
    setText('net-sent', (d.sent_mb || d.net_sent_mb || 0) + ' MB');
    setText('net-recv', (d.recv_mb || d.net_recv_mb || 0) + ' MB');

    // Live connections table
    const conns = d.active_connections || [];
    const connBadge = document.getElementById('conn-count-badge');
    if (connBadge) connBadge.textContent = conns.length + ' established';
    let connHtml = '';
    conns.forEach(c => {
      connHtml += `<tr>
        <td class="color-dim">${c.local}</td>
        <td class="color-cyan">${c.remote}</td>
        <td class="color-dim">${c.pid}</td>
        <td>${c.process}</td>
      </tr>`;
    });
    const connTable = document.getElementById('conn-table');
    if (connTable) connTable.innerHTML = connHtml || '<tr><td colspan="4" class="color-dim">No established connections</td></tr>';

    // Overview net quick
    const netQ = document.getElementById('net-quick');
    if (netQ) {
      netQ.innerHTML = `
        <div class="iface-row"><span class="iface-name">Public IP</span><span class="iface-ip color-cyan">${d.public_ip || '--'}</span></div>
        <div class="iface-row"><span class="iface-name">Local IP</span><span class="iface-ip color-gold">${mainIface.ip || '--'}</span></div>
        <div class="iface-row"><span class="iface-name">VPN</span>${vpnActive ? badge(true, vpns.find(v=>v.up).name) : badge(false)}</div>
        <div class="iface-row"><span class="iface-name">TELEGRAM</span>${tg.running ? badge(true) : badge(false)}</div>
        <div class="iface-row"><span class="iface-name">CONNECTIONS</span><span class="color-gold">${d.connections || 0}</span></div>`;
    }
  } catch(e) { console.warn('network fetch', e); }
}

// ── Services ──────────────────────────────────────────────────────────
async function refreshServices() {
  try {
    const d = await fetch('/api/services/status').then(r => r.json());
    state.services = d.services || {};
    let html = '';
    Object.entries(state.services).forEach(([id, svc]) => {
      const on = svc.running;
      html += `<div class="svc-card">
        <div class="svc-info">
          <span class="svc-icon">${svc.icon || '⚙'}</span>
          <div>
            <div class="svc-name">${svc.name}</div>
            <div class="svc-port">${svc.port ? 'PORT ' + svc.port : 'no port'}</div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          ${badge(on)}
          <button class="btn ${on?'btn-red':'btn-green'} btn-sm"
            onclick="${on?'stopSvc':'startSvc'}('${id}')">
            ${on ? '■ STOP' : '▶ START'}
          </button>
        </div>
      </div>`;
    });
    document.getElementById('svc-list').innerHTML = html || '<span style="font-family:\'Share Tech Mono\';font-size:0.72rem;color:var(--dim)">No services configured</span>';
  } catch(e) { console.warn('svc fetch', e); }
}

async function refreshServicesQuick() {
  try {
    const d = await fetch('/api/services/status').then(r => r.json());
    state.services = d.services || {};
    let html = '';
    Object.entries(state.services).forEach(([id, svc]) => {
      html += `<div class="iface-row">
        <span class="iface-name">${svc.icon} ${svc.name}</span>
        ${badge(svc.running)}
      </div>`;
    });
    const el = document.getElementById('svc-quick');
    if (el) el.innerHTML = html;
  } catch(e) {}
}

async function startSvc(id) {
  svcLog(`Starting ${id}...`, 't-gold');
  try {
    const r = await fetch(`/api/services/${id}/start`, {method:'POST'}).then(r=>r.json());
    svcLog(r.success ? `✓ ${r.message}` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
    setTimeout(refreshServices, 1500);
  } catch(e) { svcLog('Request failed: ' + e, 't-err'); }
}

async function stopSvc(id) {
  svcLog(`Stopping ${id}...`, 't-warn');
  try {
    const r = await fetch(`/api/services/${id}/stop`, {method:'POST'}).then(r=>r.json());
    svcLog(r.success ? `✓ Stopped` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
    setTimeout(refreshServices, 1000);
  } catch(e) { svcLog('Request failed: ' + e, 't-err'); }
}

// ── Listening services ────────────────────────────────────────────────
async function refreshListening() {
  try {
    const d = await fetch('/api/listening').then(r => r.json());
    const svcs = d.services || [];
    let html = svcs.map(s => `<tr>
      <td class="color-cyan">${s.port}</td>
      <td class="color-dim">${s.ip || '0.0.0.0'}</td>
      <td class="color-dim">TCP</td>
      <td class="color-dim">${s.pid}</td>
      <td>${s.process}</td>
    </tr>`).join('');
    document.getElementById('listen-table').innerHTML = html || '<tr><td colspan="5" style="color:var(--dim)">No listening ports detected</td></tr>';
  } catch(e) {}
}

// ── Nmap ──────────────────────────────────────────────────────────────
async function doSweep() {
  const target = document.getElementById('sweep-target').value.trim();
  const el = document.getElementById('sweep-log');
  el.innerHTML = `<span class="t-gold"><span class="spin">⠋</span> Scanning ${target}... (may take 10-30s)</span>`;
  try {
    const d = await fetch('/api/nmap/sweep', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({target})
    }).then(r => r.json());

    if (d.error) {
      el.innerHTML = `<span class="t-err">✗ ${d.error}</span>`;
      return;
    }
    let out = `<span class="t-ok">● Scan complete — ${d.count} hosts found on ${target}</span>\n\n`;
    if (d.hosts.length === 0) {
      out += `<span class="t-dim">No live hosts detected</span>`;
    } else {
      d.hosts.forEach(h => {
        out += `<span class="t-gold">▸</span> <span class="color-cyan">${h.ip}</span>  <span class="t-dim">${h.hostname !== h.ip ? h.hostname : ''}</span>\n`;
      });
    }
    el.innerHTML = out;
  } catch(e) {
    el.innerHTML = `<span class="t-err">✗ Fetch error: ${e}</span>`;
  }
}

async function doPortScan() {
  const target = document.getElementById('port-target').value.trim();
  const ports = document.getElementById('port-range').value.trim();
  const el = document.getElementById('port-log');
  el.innerHTML = `<span class="t-gold"><span class="spin">⠋</span> Scanning ${target}:${ports}... (may take 30-60s)</span>`;
  try {
    const d = await fetch('/api/nmap/ports', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({target, ports})
    }).then(r => r.json());

    if (d.error) {
      el.innerHTML = `<span class="t-err">✗ ${d.error}</span>`;
      return;
    }
    let out = `<span class="t-ok">● ${d.count} open port(s) on ${target} [${ports}]</span>\n\n`;
    if (d.open.length === 0) {
      out += `<span class="t-dim">No open ports found</span>`;
    } else {
      d.open.forEach(p => {
        out += `<span class="t-gold">▸</span> <span class="color-cyan">${p.port}</span>/<span class="t-dim">${p.service}</span>  <span class="color-gold">${p.version}</span>\n`;
      });
    }
    el.innerHTML = out;
  } catch(e) {
    el.innerHTML = `<span class="t-err">✗ Fetch error: ${e}</span>`;
  }
}

// ── Chat ──────────────────────────────────────────────────────────────
function addMsg(role, text) {
  const box = document.getElementById('chat-history');
  const isUser = role === 'user';
  box.innerHTML += `<div class="msg msg-${isUser?'user':'larry'}">
    <div class="bubble-from">${isUser ? 'YOU' : 'LARRY G-FORCE'}</div>
    <div class="bubble ${isUser?'bubble-user':'bubble-larry'}">${text.replace(/\n/g,'<br>')}</div>
  </div>`;
  box.scrollTop = box.scrollHeight;
}

function clearChat() {
  document.getElementById('chat-history').innerHTML = '';
  chatMessages = [];
}

async function sendChat() {
  const inp = document.getElementById('chat-input');
  const model = document.getElementById('chat-model').value;
  const prompt = inp.value.trim();
  if (!prompt) return;
  inp.value = '';
  addMsg('user', prompt);
  chatMessages.push({role:'user', text:prompt});

  // Update model label and persist choice
  const labelEl = document.getElementById('chat-model-label');
  if (labelEl) labelEl.textContent = model.split(':')[0];
  localStorage.setItem('larry_chat_model', model);

  const box = document.getElementById('chat-history');
  box.innerHTML += `<div class="msg msg-larry" id="chat-thinking">
    <div class="bubble-from">LARRY G-FORCE</div>
    <div class="bubble bubble-larry"><span class="spin">⠋</span> Thinking with ${model.split(':')[0]}...</div>
  </div>`;
  box.scrollTop = box.scrollHeight;

  try {
    const d = await fetch('/api/ollama/chat', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({model, prompt})
    }).then(r => r.json());

    document.getElementById('chat-thinking')?.remove();
    const resp = d.response || d.error || 'No response';
    addMsg('larry', resp);
    chatMessages.push({role:'larry', text:resp});
  } catch(e) {
    document.getElementById('chat-thinking')?.remove();
    addMsg('larry', '✗ Error: ' + e);
  }
}

// ── Kill process ──────────────────────────────────────────────────────
async function killProc(pid, name) {
  if (!confirm(`Kill process ${name} (PID ${pid})?`)) return;
  try {
    const r = await fetch('/api/process/kill', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({pid})
    }).then(r => r.json());
    if (r.success) {
      svcLog(`✓ ${r.message}`, 't-ok');
    } else {
      svcLog(`✗ ${r.error}`, 't-err');
    }
    setTimeout(refreshHealth, 500);
  } catch(e) { svcLog('Kill failed: ' + e, 't-err'); }
}

// ── Unload Ollama model from VRAM ────────────────────────────────────
async function unloadModel(model) {
  if (!confirm(`Unload ${model} from VRAM?`)) return;
  try {
    const r = await fetch('/api/ollama/unload', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({model})
    }).then(r => r.json());
    svcLog(r.success ? `✓ ${r.message}` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
    setTimeout(refreshModels, 1500);
  } catch(e) { svcLog('Unload failed: ' + e, 't-err'); }
}

async function stopOllama() {
  if (!confirm('Stop Ollama server entirely?')) return;
  try {
    const r = await fetch('/api/ollama/stop', {method:'POST'}).then(r => r.json());
    svcLog(r.success ? `✓ ${r.message}` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
    setTimeout(refreshModels, 2000);
  } catch(e) { svcLog('Stop failed: ' + e, 't-err'); }
}

// ── DB file manager ──────────────────────────────────────────────────
let currentDbCat = '';
async function loadDB(cat) {
  currentDbCat = cat;
  try {
    const d = await fetch(`/api/db/list?cat=${cat}`).then(r => r.json());
    let html = '';
    if (d.categories && !cat) {
      d.categories.forEach(c => {
        html += `<div class="iface-row" style="cursor:pointer" onclick="loadDB('${c}')">
          <span class="iface-name" style="color:var(--gold)">📁 ${c}/</span>
          <span class="badge badge-dim">FOLDER</span>
        </div>`;
      });
    }
    (d.files || []).forEach(f => {
      const sizeKb = (f.size / 1024).toFixed(1);
      html += `<div class="iface-row">
        <span style="cursor:pointer;color:var(--cyan)" onclick="openDB('${f.category}','${f.name}')">${f.name}</span>
        <span style="display:flex;align-items:center;gap:6px">
          <span class="color-dim" style="font-size:0.62rem">${sizeKb}KB · ${f.modified}</span>
          <button class="btn btn-red btn-sm" style="padding:1px 5px;font-size:0.45rem" onclick="deleteDB('${f.category}','${f.name}')">DEL</button>
        </span>
      </div>`;
    });
    if (!html) html = '<span style="color:var(--dim)">Empty</span>';
    document.getElementById('db-file-list').innerHTML = html;
  } catch(e) { console.warn('db list err', e); }
}

async function openDB(cat, name) {
  try {
    const d = await fetch(`/api/db/read?cat=${cat}&name=${encodeURIComponent(name)}`).then(r => r.json());
    if (d.error) return;
    document.getElementById('db-filename').value = name;
    document.getElementById('db-cat-select').value = cat;
    document.getElementById('db-editor').value = d.content;
  } catch(e) {}
}

async function saveDB() {
  const name = document.getElementById('db-filename').value.trim();
  const cat = document.getElementById('db-cat-select').value;
  const content = document.getElementById('db-editor').value;
  if (!name) return alert('Enter a filename');
  try {
    const r = await fetch('/api/db/save', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({category: cat, name, content})
    }).then(r => r.json());
    if (r.success) { svcLog(`✓ ${r.message}`, 't-ok'); loadDB(cat); }
    else svcLog(`✗ ${r.error}`, 't-err');
  } catch(e) { svcLog('Save failed: ' + e, 't-err'); }
}

async function deleteDB(cat, name) {
  if (!confirm(`Delete ${name}?`)) return;
  try {
    await fetch('/api/db/delete', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({category: cat, name})
    });
    loadDB(currentDbCat);
  } catch(e) {}
}

// ── Quick Security Scan ─────────────────────────────────────────────────
async function doQuickScan() {
  const el = document.getElementById('quickscan-results');
  el.innerHTML = '<span class="t-gold"><span class="spin">⠋</span> Running security assessment...</span>';
  try {
    const d = await fetch('/api/security/quickscan', {method:'POST'}).then(r => r.json());
    let html = `<div style="margin-bottom:8px;color:var(--dim)">Scan at ${d.timestamp}</div>`;
    (d.results || []).forEach(r => {
      const icon = r.status === 'ok' ? '<span class="color-green">✓</span>' :
                   r.status === 'warn' ? '<span class="color-orange">⚠</span>' :
                   r.status === 'critical' ? '<span class="color-red">✗</span>' :
                   '<span class="color-dim">ℹ</span>';
      html += `<div class="iface-row" style="padding:4px 0">
        <span>${icon} <span style="color:var(--text)">${r.check}</span></span>
        <span class="color-dim">${r.detail}</span>
      </div>`;
    });
    el.innerHTML = html;
  } catch(e) { el.innerHTML = `<span class="t-err">✗ ${e}</span>`; }
}

// ── Kali tool runner ──────────────────────────────────────────────────
async function runKaliTool() {
  const target = document.getElementById('kali-target').value.trim();
  const tool = document.getElementById('kali-tool').value;
  const el = document.getElementById('kali-log');
  if (!target) { el.innerHTML = '<span class="t-err">Enter a target first</span>'; return; }

  // Build nmap/command calls per tool
  const toolCmds = {
    whatweb: {endpoint:'/api/kali/run', body:{tool:'whatweb',target}},
    nikto: {endpoint:'/api/kali/run', body:{tool:'nikto',target}},
    whois: {endpoint:'/api/kali/run', body:{tool:'whois',target}},
    dig: {endpoint:'/api/kali/run', body:{tool:'dig',target}},
    traceroute: {endpoint:'/api/kali/run', body:{tool:'traceroute',target}},
    sslscan: {endpoint:'/api/kali/run', body:{tool:'sslscan',target}},
  };
  const cmd = toolCmds[tool];
  el.innerHTML = `<span class="t-gold"><span class="spin">⠋</span> Running ${tool} on ${target}...</span>`;
  try {
    const d = await fetch(cmd.endpoint, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(cmd.body)
    }).then(r => r.json());
    if (d.error) { el.innerHTML = `<span class="t-err">✗ ${d.error}</span>`; return; }
    el.innerHTML = `<span class="t-ok">● ${tool} complete</span>\n\n<pre style="white-space:pre-wrap;color:var(--text)">${d.output || 'No output'}</pre>`;
  } catch(e) { el.innerHTML = `<span class="t-err">✗ ${e}</span>`; }
}

// ── Chat save/load ──────────────────────────────────────────────────
let chatMessages = [];

async function saveChatHistory() {
  if (chatMessages.length === 0) return alert('No messages to save');
  const model = document.getElementById('chat-model').value;
  try {
    const r = await fetch('/api/chat/save', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({model, messages: chatMessages})
    }).then(r => r.json());
    if (r.success) svcLog('✓ Chat saved: ' + r.file, 't-ok');
  } catch(e) { svcLog('Save failed: ' + e, 't-err'); }
}

async function loadChatHistoryList() {
  try {
    const d = await fetch('/api/chat/history').then(r => r.json());
    const chats = d.chats || [];
    if (chats.length === 0) return alert('No saved chats');
    const names = chats.map((c,i) => `${i+1}. ${c.name} (${c.model}, ${c.count} msgs)`).join('\n');
    const idx = prompt('Enter chat number to load:\n\n' + names);
    if (!idx) return;
    const chat = chats[parseInt(idx)-1];
    if (!chat) return;
    // Load from DB
    const file = await fetch(`/api/db/read?cat=chats&name=${encodeURIComponent(chat.name)}`).then(r => r.json());
    if (file.error) return;
    const data = JSON.parse(file.content);
    clearChat();
    chatMessages = data.messages || [];
    chatMessages.forEach(m => addMsg(m.role, m.text));
    if (data.model) {
      const sel = document.getElementById('chat-model');
      for (let opt of sel.options) { if (opt.value === data.model) { sel.value = data.model; break; } }
    }
  } catch(e) { console.warn(e); }
}

// ── AI Activity stream ─────────────────────────────────────────────────
let activitySince = 0;
let activityStats = { queries: 0, gens: 0, rag: 0, tools: 0, errors: 0 };

const TYPE_CLASS = {
  query_received: 'type-query',
  model_selected: 'type-model',
  context_budget: 'type-context',
  rag_search: 'type-rag',
  tool_dispatch: 'type-tool',
  thinking: 'type-thinking',
  generating: 'type-gen',
  response_done: 'type-done',
  error: 'type-error',
  system: 'type-system',
};

const TYPE_LABEL = {
  query_received: 'QUERY',
  model_selected: 'MODEL',
  context_budget: 'CTX',
  rag_search: 'RAG',
  tool_dispatch: 'TOOL',
  thinking: 'THINK',
  generating: 'GEN',
  response_done: 'DONE',
  error: 'ERROR',
  system: 'SYS',
};

function srcClass(src) {
  if (src === 'agent_v2') return 'src-agent';
  if (src === 'telegram_bot') return 'src-telegram';
  return 'src-system';
}

function srcLabel(src) {
  if (src === 'agent_v2') return 'AGENT';
  if (src === 'telegram_bot') return 'TG-BOT';
  return 'SYS';
}

async function refreshActivity() {
  try {
    const d = await fetch(`/api/activity/stream?since=${activitySince}&limit=50`).then(r => r.json());
    const events = d.events || [];
    if (events.length === 0) return;

    const term = document.getElementById('activity-terminal');
    const wasAtBottom = term.scrollTop + term.clientHeight >= term.scrollHeight - 20;

    events.forEach(ev => {
      activitySince = Math.max(activitySince, ev.ts || 0);

      // Update stats
      if (ev.type === 'query_received') activityStats.queries++;
      if (ev.type === 'generating') activityStats.gens++;
      if (ev.type === 'rag_search') activityStats.rag++;
      if (ev.type === 'tool_dispatch') activityStats.tools++;
      if (ev.type === 'error') activityStats.errors++;

      // Update sidebar
      if (ev.type === 'model_selected' && ev.detail) {
        document.getElementById('activity-last-model').textContent = ev.detail.model || ev.msg;
      }
      if (ev.type === 'context_budget' && ev.detail) {
        document.getElementById('activity-ctx-info').textContent =
          `${ev.detail.ctx_limit} tokens / ${ev.detail.history_budget} chars history`;
      }

      // Update agent status indicators
      if (ev.source === 'agent_v2') {
        const el = document.getElementById('agent-v2-status');
        if (ev.type === 'generating') { el.className = 'badge badge-warn'; el.textContent = 'GENERATING'; }
        else if (ev.type === 'response_done') { el.className = 'badge badge-on'; el.textContent = 'READY'; }
        else if (ev.type === 'query_received') { el.className = 'badge badge-warn'; el.textContent = 'THINKING'; }
        else if (ev.type === 'system') { el.className = 'badge badge-on'; el.textContent = 'ONLINE'; }
      }
      if (ev.source === 'telegram_bot') {
        const el = document.getElementById('tg-bot-status');
        if (ev.type === 'generating') { el.className = 'badge badge-warn'; el.textContent = 'GENERATING'; }
        else if (ev.type === 'response_done') { el.className = 'badge badge-on'; el.textContent = 'READY'; }
        else if (ev.type === 'query_received') { el.className = 'badge badge-warn'; el.textContent = 'PROCESSING'; }
        else if (ev.type === 'system') { el.className = 'badge badge-on'; el.textContent = 'ONLINE'; }
      }

      // Render event line
      const typeCls = TYPE_CLASS[ev.type] || 'type-system';
      const typeLabel = TYPE_LABEL[ev.type] || ev.type.toUpperCase();
      const line = document.createElement('div');
      line.className = 'ev';
      line.innerHTML = `<span class="ev-time">${ev.time || '--'}</span>`
        + `<span class="ev-src ${srcClass(ev.source)}">${srcLabel(ev.source)}</span>`
        + `<span class="ev-type ${typeCls}">[${typeLabel}]</span>`
        + `<span>${ev.msg || ''}</span>`;
      term.appendChild(line);
    });

    // Update stats display
    setText('stat-queries', activityStats.queries);
    setText('stat-gens', activityStats.gens);
    setText('stat-rag', activityStats.rag);
    setText('stat-tools', activityStats.tools);
    setText('stat-errors', activityStats.errors);
    setText('activity-count', (activityStats.queries + activityStats.gens + activityStats.rag + activityStats.tools) + ' events');

    // Pulse indicator
    const pulse = document.getElementById('activity-pulse');
    if (pulse) { pulse.style.background = 'var(--gold)'; setTimeout(() => pulse.style.background = 'var(--green)', 500); }

    // Auto-scroll if at bottom
    if (wasAtBottom) term.scrollTop = term.scrollHeight;

    // Limit terminal lines
    while (term.children.length > 300) term.removeChild(term.firstChild);
  } catch(e) { /* silent */ }
}

function clearActivity() {
  document.getElementById('activity-terminal').innerHTML = '<div class="t-dim">// Terminal cleared</div>';
  activityStats = { queries: 0, gens: 0, rag: 0, tools: 0, errors: 0 };
}

// ── Crypto Trading Dashboard ──────────────────────────────────────────
async function refreshCrypto() {
  try {
    const d = await fetch('/api/crypto/status').then(r => r.json());
    const s = d.state || {};
    const c = d.config || {};
    const bot = d.bot || {};
    const ai = d.ai_server || {};

    // Mode & exchange badges
    const modeEl = document.getElementById('crypto-mode-badge');
    if (modeEl) {
      const isLive = bot.live && !c.paper;
      modeEl.textContent = isLive ? 'LIVE' : 'PAPER';
      modeEl.style.background = isLive ? 'rgba(255,56,96,0.3)' : 'rgba(0,255,136,0.2)';
      modeEl.style.color = isLive ? 'var(--red)' : 'var(--green)';
    }
    const exEl = document.getElementById('crypto-exchange-badge');
    if (exEl) {
      exEl.textContent = (c.exchange || '?').toUpperCase();
      exEl.style.background = 'rgba(240,180,40,0.2)';
      exEl.style.color = 'var(--gold)';
    }

    // Server badges
    const botBadge = document.getElementById('crypto-bot-badge');
    if (botBadge) botBadge.innerHTML = bot.running
      ? `<span class="badge badge-on" style="padding:2px 6px">BOT ${bot.pid}</span>`
      : '<span class="badge badge-off" style="padding:2px 6px">BOT OFF</span>';
    const aiBadge = document.getElementById('crypto-ai-badge');
    if (aiBadge) aiBadge.innerHTML = ai.running
      ? `<span class="badge badge-on" style="padding:2px 6px">AI ${ai.healthy?'OK':'!'} ${ai.pid}</span>`
      : '<span class="badge badge-off" style="padding:2px 6px">AI OFF</span>';

    // KPIs — extract balance from log status line
    const logLines = d.log || [];
    let liveBalance = s.start_of_day_balance || 0;
    for (let i = logLines.length - 1; i >= 0; i--) {
      const m = logLines[i].match(/Status:\s*\$([0-9.]+)/);
      if (m) { liveBalance = parseFloat(m[1]); break; }
    }
    const hwm = s.equity_hwm || liveBalance;
    const dd = hwm > 0 ? ((hwm - liveBalance) / hwm * 100) : 0;

    setText('crypto-balance', '$' + liveBalance.toFixed(2));
    setText('crypto-hwm', '$' + hwm.toFixed(2));
    const ddEl = document.getElementById('crypto-dd');
    if (ddEl) {
      ddEl.textContent = dd.toFixed(1) + '%';
      ddEl.style.color = dd > 1 ? 'var(--red)' : 'var(--green)';
    }

    // P&L
    const pnlEl = document.getElementById('crypto-pnl');
    if (pnlEl) {
      const pnl = s.total_pnl || 0;
      pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
      pnlEl.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
    }
    setText('crypto-trades', s.n_trades || 0);
    setText('crypto-wr', (s.win_rate || 0) + '%');

    // Positions
    setText('crypto-positions', s.n_open || 0);
    setText('crypto-max-pos', c.max_positions || '--');
    setText('crypto-risk', c.risk_per_trade || '--');
    setText('crypto-conf', (c.min_confidence * 100 || 0).toFixed(0) + '%');
    setText('crypto-tf', c.primary_tf || '--');
    setText('crypto-nsymbols', c.n_symbols || '--');

    // Open positions
    const posEl = document.getElementById('crypto-open-positions');
    if (posEl) {
      const pos = s.open_positions || {};
      const keys = Object.keys(pos);
      if (keys.length === 0) {
        posEl.innerHTML = '<span class="color-dim">No open positions</span>';
      } else {
        posEl.innerHTML = keys.map(k => {
          const p = pos[k];
          const side = (p.side || 'buy').toUpperCase();
          const sideColor = side === 'BUY' ? 'var(--green)' : 'var(--red)';
          return `<div style="margin-bottom:3px"><span style="color:${sideColor}">${side}</span> <span class="color-cyan">${k}</span> @ ${(p.entry_price||0).toFixed(4)} <span class="color-dim">qty:${(p.amount||0).toFixed(6)}</span></div>`;
        }).join('');
      }
    }

    // Recent trades
    const tradesEl = document.getElementById('crypto-recent-trades');
    if (tradesEl) {
      const trades = (s.recent_trades || []).slice().reverse();
      if (trades.length === 0) {
        tradesEl.innerHTML = '<span class="color-dim">No trades yet</span>';
      } else {
        tradesEl.innerHTML = trades.map(t => {
          const pnlColor = (t.pnl||0) >= 0 ? 'var(--green)' : 'var(--red)';
          const pnlStr = (t.pnl||0) >= 0 ? '+' : '';
          const timeStr = t.time ? t.time.substring(5, 16).replace('T',' ') : '';
          return `<div style="margin-bottom:2px"><span class="color-dim">${timeStr}</span> <span class="color-cyan">${t.symbol||'?'}</span> <span style="color:${pnlColor}">${pnlStr}$${(t.pnl||0).toFixed(2)}</span> <span class="color-dim">${t.reason||''}</span></div>`;
        }).join('');
      }
    }

    // Log tail
    const logEl = document.getElementById('crypto-log-terminal');
    if (logEl) {
      const wasAtBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 20;
      if (logLines.length === 0) {
        logEl.innerHTML = '<span class="color-dim">No log data</span>';
      } else {
        logEl.innerHTML = logLines.slice(-25).map(line => {
          let cls = 'color-dim';
          if (line.includes('ERROR') || line.includes('REJECTED')) cls = 't-err';
          else if (line.includes('BUY') || line.includes('SELL') || line.includes('ORDER')) cls = 'color-gold';
          else if (line.includes('LIVE') || line.includes('Status:')) cls = 'color-cyan';
          else if (line.includes('WARNING') || line.includes('paused')) cls = 't-warn';
          else if (line.includes('INFO')) cls = 'color-dim';
          // Strip long timestamp prefix for readability
          const shortLine = line.replace(/^\d{4}-\d{2}-\d{2}\s/, '');
          return `<div class="${cls}">${shortLine}</div>`;
        }).join('');
      }
      if (wasAtBottom) logEl.scrollTop = logEl.scrollHeight;
    }
  } catch(e) { console.warn('crypto fetch', e); }
}

async function cryptoAction(action) {
  const msgEl = document.getElementById('crypto-pipeline-msg');
  if (msgEl) msgEl.innerHTML = `<span class="color-gold">⠋ ${action}...</span>`;
  try {
    const d = await fetch(`/api/crypto/pipeline/${action}`, {method:'POST'}).then(r=>r.json());
    if (msgEl) {
      const ok = d.success;
      const msg = d.message || (d.results||[]).join(' | ') || d.error || '';
      msgEl.innerHTML = `<span class="${ok?'color-green':'color-red'}">${ok?'✓':'✗'} ${msg}</span>`;
      setTimeout(() => { if (msgEl) msgEl.innerHTML = ''; }, 8000);
    }
    setTimeout(refreshCrypto, 2000);
  } catch(e) {
    if (msgEl) msgEl.innerHTML = `<span class="color-red">✗ ${e}</span>`;
  }
}

// ── Tools Tab ─────────────────────────────────────────────────────────

function dispatchLog(msg, cls='') {
  const el = document.getElementById('dispatch-log');
  if (!el) return;
  el.innerHTML += `<div class="${cls || 't-dim'}">> ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}

function bashLog(msg, cls='') {
  const el = document.getElementById('bash-run-log');
  if (!el) return;
  el.innerHTML += `<div class="${cls || 't-dim'}">> ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}

function portInvLog(msg, cls='') {
  const el = document.getElementById('portinv-log');
  if (!el) return;
  el.innerHTML += `<div class="${cls || 'color-dim'}">> ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}

function secopLog(msg, cls='') {
  const el = document.getElementById('secop-log');
  if (!el) return;
  el.innerHTML += `<div class="${cls || 't-dim'}">> ${msg}</div>`;
  el.scrollTop = el.scrollHeight;
}

// ── Security Command Center JS ────────────────────────────────────────

function secTermLog(msg, cls) {
  const el = document.getElementById('sec-cmd-terminal');
  if (!el) return;
  el.innerHTML += `<span class="${cls||'t-dim'}">${msg}</span>\n`;
  el.scrollTop = el.scrollHeight;
}

function secPortLog(msg, cls) {
  const el = document.getElementById('portinv-output');
  if (!el) return;
  el.innerHTML += `<span class="${cls||'t-dim'}">${msg}</span>\n`;
  el.scrollTop = el.scrollHeight;
}

const SEC_API_MAP = {
  quick:      '/api/security/quick',
  investigate:'/api/security/investigate',
  hunt:       '/api/security/hunt',
  traffic:    '/api/security/traffic',
  firewall:   '/api/security/firewall',
  audit:      '/api/security/audit',
  modules:    '/api/security/modules',
};

async function secCmd(subcmd) {
  const terminal = document.getElementById('sec-cmd-terminal');
  if (!terminal) return;
  terminal.innerHTML = `<span class="t-gold"><span class="spin">⠋</span> Running ${subcmd.toUpperCase()}...</span>\n`;

  const url = SEC_API_MAP[subcmd] || `/api/security/${subcmd}`;
  try {
    const d = await fetch(url).then(r => r.json());

    if (d.error) {
      terminal.innerHTML += `<span class="t-err">✗ ${d.error}</span>\n`;
      return;
    }

    // Render structured result
    if (subcmd === 'modules' || d.modules) {
      const mods = d.modules || d;
      terminal.innerHTML += `<span class="t-ok">✓ Module status:</span>\n`;
      Object.entries(mods).forEach(([k, v]) => {
        if (typeof v === 'boolean') {
          terminal.innerHTML += `  <span class="${v?'t-ok':'t-err'}">${v?'✓':'✗'} ${k}</span>\n`;
        }
      });
      secUpdateModulePills(mods);
      return;
    }

    // Generic structured output renderer
    const summary = d.summary || d.overview || d.network_summary || {};
    if (summary.total !== undefined || summary.established !== undefined) {
      secUpdateKpi(d);
    }

    terminal.innerHTML += `<span class="t-ok">✓ ${subcmd.toUpperCase()} complete</span>\n\n`;

    // Show key fields from the result
    function renderObj(obj, indent) {
      indent = indent || '';
      Object.entries(obj).forEach(([k, v]) => {
        if (v === null || v === undefined) return;
        if (Array.isArray(v)) {
          if (v.length === 0) return;
          terminal.innerHTML += `${indent}<span class="color-gold">${k}</span>: <span class="color-cyan">[${v.length} items]</span>\n`;
          v.slice(0, 5).forEach(item => {
            if (typeof item === 'object') {
              terminal.innerHTML += `${indent}  <span class="t-dim">${JSON.stringify(item).substring(0, 120)}</span>\n`;
            } else {
              terminal.innerHTML += `${indent}  <span class="t-dim">• ${item}</span>\n`;
            }
          });
          if (v.length > 5) terminal.innerHTML += `${indent}  <span class="t-dim">... +${v.length-5} more</span>\n`;
        } else if (typeof v === 'object') {
          terminal.innerHTML += `${indent}<span class="color-gold">${k}</span>:\n`;
          renderObj(v, indent + '  ');
        } else {
          const cls = v === true ? 't-ok' : v === false ? 't-err' : 'color-cyan';
          terminal.innerHTML += `${indent}<span class="color-dim">${k}:</span> <span class="${cls}">${v}</span>\n`;
        }
      });
    }
    renderObj(d);

  } catch(e) {
    terminal.innerHTML += `<span class="t-err">✗ ${e}</span>\n`;
  }
  terminal.scrollTop = terminal.scrollHeight;
}

async function secInvestigate() {
  const portInput = document.getElementById('portinv-port-sec').value.trim();
  const noGeo = document.getElementById('portinv-nogeo-sec').checked;
  const el = document.getElementById('portinv-output');
  if (!el) return;
  el.innerHTML = `<span class="t-gold"><span class="spin">⠋</span> Investigating ${portInput ? 'port ' + portInput : 'all connections'}...</span>\n`;
  try {
    const params = new URLSearchParams();
    if (portInput) params.set('port', portInput);
    if (noGeo) params.set('no_geo', 'true');
    const d = await fetch('/api/port/investigate?' + params).then(r => r.json());
    if (d.error) { el.innerHTML = `<span class="t-err">✗ ${d.error}</span>\n`; return; }

    secUpdateKpi(d);

    const summary = d.summary || {};
    el.innerHTML = `<span class="t-ok">● Investigation complete</span>\n`;
    el.innerHTML += `<span class="color-gold">Connections: ${summary.total||0} | Active: ${summary.established||0} | Listening: ${summary.listening||0}</span>\n`;
    if (summary.unique_remote_ips) {
      el.innerHTML += `<span class="color-cyan">Remote IPs: ${summary.unique_remote_ips} | Countries: ${summary.countries_connected||0}</span>\n`;
    }
    const byCountry = d.by_country || {};
    const topC = Object.entries(byCountry).sort((a,b)=>b[1]-a[1]).slice(0,5);
    if (topC.length) {
      el.innerHTML += `\n<span class="color-dim">Top countries: ${topC.map(([c,n])=>c+'('+n+')').join(', ')}</span>\n`;
    }
    const connections = d.connections || [];
    if (connections.length) {
      el.innerHTML += `\n<span class="color-dim">─── ACTIVE CONNECTIONS ───</span>\n`;
      connections.slice(0, 20).forEach(c => {
        const remote = c.remote_ip ? `${c.remote_ip}:${c.remote_port}` : 'local';
        const geo = c.geo ? ` [${c.geo.country||'?'}]` : '';
        const proc = c.process_name ? ` (${c.process_name})` : '';
        el.innerHTML += `<span class="color-cyan">${c.state||'?'}</span> <span>:${c.local_port||'?'}</span>→<span class="color-gold">${remote}${geo}</span>${proc}\n`;
      });
    }
  } catch(e) { el.innerHTML = `<span class="t-err">✗ ${e}</span>\n`; }
  el.scrollTop = el.scrollHeight;
}

function secUpdateKpi(d) {
  const summary = d.summary || d.network_summary || d.overview || {};

  const total = summary.total ?? summary.connections ?? null;
  const estab = summary.established ?? null;
  const listen = summary.listening ?? null;
  const remoteIps = summary.unique_remote_ips ?? null;

  if (total !== null) document.getElementById('sec-conns').textContent = total;
  if (estab !== null) document.getElementById('sec-established').textContent = estab;
  if (listen !== null) document.getElementById('sec-listening').textContent = listen;
  if (remoteIps !== null) document.getElementById('sec-remote-ips').textContent = remoteIps;

  const riskEl = document.getElementById('sec-risk');
  if (riskEl && d.risk_level) {
    riskEl.textContent = d.risk_level;
    const riskColors = { LOW:'var(--green)', MEDIUM:'var(--gold)', HIGH:'var(--orange)', CRITICAL:'var(--red)' };
    riskEl.style.color = riskColors[d.risk_level.toUpperCase()] || 'var(--cyan)';
  }

  const scanTime = document.getElementById('sec-scan-time');
  if (scanTime) scanTime.textContent = 'last scan: ' + new Date().toLocaleTimeString();

  const warnings = d.warnings || d.alerts || [];
  const warnEl = document.getElementById('sec-warnings');
  if (warnEl) {
    if (warnings.length) {
      warnEl.style.display = 'block';
      warnEl.innerHTML = warnings.map(w => `⚠ ${w}`).join('<br>');
    } else {
      warnEl.style.display = 'none';
    }
  }
}

function secUpdateModulePills(mods) {
  const pillsEl = document.getElementById('sec-module-pills');
  if (!pillsEl) return;
  pillsEl.innerHTML = Object.entries(mods)
    .filter(([, v]) => typeof v === 'boolean')
    .map(([k, v]) =>
      `<span class="badge ${v ? 'badge-on' : 'badge-warn'}" style="font-size:0.55rem">
        ${v?'✓':'✗'} ${k.replace(/_/g,' ').toUpperCase()}
      </span>`
    ).join('');
}

async function secCenterInit() {
  // Set badge status
  const badge = document.getElementById('sec-center-badge');
  try {
    const d = await fetch('/api/tools/status').then(r => r.json());
    if (badge) {
      if (d.security_tools) {
        badge.className = 'badge badge-on'; badge.textContent = '● SCC ONLINE';
      } else {
        badge.className = 'badge badge-warn'; badge.textContent = '⚠ SCC PARTIAL';
      }
    }
    // Load module pills
    if (d.security_modules) secUpdateModulePills(d.security_modules);
  } catch(e) {
    if (badge) { badge.className = 'badge badge-warn'; badge.textContent = '⚠ API ERROR'; }
  }

  // VPN check from network data
  try {
    const n = await fetch('/api/status').then(r => r.json());
    const vpnEl = document.getElementById('sec-vpn');
    const vpnIface = document.getElementById('sec-vpn-iface');
    const ifaces = n.network_interfaces || n.interfaces || [];
    const vpn = ifaces.find(i => /wg|tun|vpn|proton/i.test(i.name || i));
    if (vpnEl) {
      if (vpn) {
        vpnEl.textContent = '● UP';
        vpnEl.style.color = 'var(--green)';
        if (vpnIface) vpnIface.textContent = (vpn.name || vpn);
      } else {
        vpnEl.textContent = '○ DOWN';
        vpnEl.style.color = 'var(--red)';
        if (vpnIface) vpnIface.textContent = 'no VPN iface detected';
      }
    }
  } catch(e) { /* silent */ }
}

async function initToolsTab() {
  // Load tool status badge + bash scripts on tab open
  try {
    const d = await fetch('/api/tools/status').then(r => r.json());
    const badge = document.getElementById('tools-status-badge');
    if (badge) {
      if (d.security_tools) {
        badge.className = 'badge badge-on'; badge.textContent = '● TOOLS ONLINE';
      } else {
        badge.className = 'badge badge-warn'; badge.textContent = '⚠ TOOLS PARTIAL';
      }
    }
  } catch(e) { /* silent */ }
  loadBashScripts();
}

async function loadBashScripts() {
  const el = document.getElementById('bash-script-list');
  const sel = document.getElementById('bash-key-select');
  try {
    const d = await fetch('/api/bash/list').then(r => r.json());
    const scripts = d.scripts || {};
    if (d.error) {
      el.innerHTML = `<span class="t-err">✗ ${d.error}</span>`;
      return;
    }

    let html = '';
    const catIcons = { discovery:'🔍', audit:'🛡️', monitor:'📡', device:'🎯', utility:'🔧' };
    const byCategory = {};
    Object.entries(scripts).forEach(([key, info]) => {
      const cat = info.category || 'other';
      if (!byCategory[cat]) byCategory[cat] = [];
      byCategory[cat].push([key, info]);
    });

    Object.entries(byCategory).forEach(([cat, items]) => {
      html += `<div style="color:var(--gold);margin:8px 0 4px;font-size:0.62rem;letter-spacing:2px">${catIcons[cat]||'📦'} ${cat.toUpperCase()}</div>`;
      items.forEach(([key, info]) => {
        const avail = info.available;
        html += `<div class="iface-row" style="padding:4px 0">
          <span>
            <span style="color:${avail?'var(--green)':'var(--red)'}">${avail?'✓':'✗'}</span>
            <span style="color:var(--cyan);margin-left:6px">${key}</span>
            <span style="color:var(--dim);font-size:0.62rem;margin-left:8px">${info.description||''}</span>
          </span>
          ${avail && !info.interactive
            ? `<button class="btn btn-green btn-sm" style="padding:2px 7px;font-size:0.5rem" onclick="runBashKey('${key}')">▶</button>`
            : (avail ? '<span class="badge badge-warn" style="font-size:0.55rem">INTERACTIVE</span>' : '')}
        </div>`;
      });
    });

    el.innerHTML = html || '<span class="t-dim">No scripts found</span>';

    // Update select options
    if (sel) {
      sel.innerHTML = '<option value="">Select script...</option>';
      Object.entries(scripts).forEach(([key, info]) => {
        if (info.available && !info.interactive) {
          const opt = document.createElement('option');
          opt.value = key; opt.textContent = key + ' — ' + info.name;
          sel.appendChild(opt);
        }
      });
    }
  } catch(e) {
    el.innerHTML = `<span class="t-err">✗ ${e}</span>`;
  }
}

async function runBashKey(key) {
  bashLog(`Starting ${key}...`, 't-gold');
  try {
    const r = await fetch('/api/bash/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key})
    }).then(r => r.json());
    bashLog(r.success ? `✓ ${r.message}` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
  } catch(e) { bashLog('✗ ' + e, 't-err'); }
}

async function runBashScript() {
  const key = document.getElementById('bash-key-select').value;
  const argsInput = document.getElementById('bash-args-input').value.trim();
  if (!key) { bashLog('Select a script first', 't-err'); return; }
  const args = argsInput ? argsInput.split(/\s+/) : [];
  bashLog(`Dispatching ${key}${args.length ? ' ' + args.join(' ') : ''}...`, 't-gold');
  try {
    const r = await fetch('/api/bash/run', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({key, args})
    }).then(r => r.json());
    bashLog(r.success ? `✓ ${r.message}` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
  } catch(e) { bashLog('✗ ' + e, 't-err'); }
}

async function runPortInvestigator() {
  const portInput = document.getElementById('portinv-port').value.trim();
  const noGeo = document.getElementById('portinv-nogeo').checked;
  const el = document.getElementById('portinv-log');
  el.innerHTML = `<span class="t-gold"><span class="spin">⠋</span> Investigating ${portInput ? 'port ' + portInput : 'all connections'}...</span>`;
  try {
    const params = new URLSearchParams();
    if (portInput) params.set('port', portInput);
    if (noGeo) params.set('no_geo', 'true');
    const d = await fetch('/api/port/investigate?' + params).then(r => r.json());
    if (d.error) { el.innerHTML = `<span class="t-err">✗ ${d.error}</span>`; return; }

    const summary = d.summary || {};
    let html = `<span class="t-ok">● Investigation complete</span>\n`;
    html += `<span class="color-gold">Connections: ${summary.total||0} | Active: ${summary.established||0} | Listening: ${summary.listening||0}</span>\n`;
    if (summary.unique_remote_ips) html += `<span class="color-cyan">Remote IPs: ${summary.unique_remote_ips} | Countries: ${summary.countries_connected||0}</span>\n`;

    const byCountry = d.by_country || {};
    const topCountries = Object.entries(byCountry).sort((a,b)=>b[1]-a[1]).slice(0,5);
    if (topCountries.length) {
      html += `\n<span class="color-dim">Top countries: ${topCountries.map(([c,n])=>c+'('+n+')').join(', ')}</span>\n`;
    }

    const connections = d.connections || [];
    if (connections.length) {
      html += `\n<span class="color-dim">--- ACTIVE CONNECTIONS ---</span>\n`;
      connections.slice(0, 20).forEach(c => {
        const remote = c.remote_ip ? `${c.remote_ip}:${c.remote_port}` : 'local';
        const geo = c.geo ? ` [${c.geo.country||'?'}]` : '';
        const proc = c.process_name ? ` (${c.process_name})` : '';
        html += `<span class="color-cyan">${c.state||'?'}</span> <span>${c.local_port||'?'}</span>→<span class="color-gold">${remote}${geo}</span>${proc}\n`;
      });
    }

    el.innerHTML = html;
  } catch(e) { el.innerHTML = `<span class="t-err">✗ ${e}</span>`; }
}

async function runSecurityOp(subcmd) {
  secopLog(`Running security ${subcmd}...`, 't-gold');
  try {
    const d = await fetch(`/api/security/${subcmd === 'quick' ? 'quick' : subcmd === 'hunt' ? 'hunt' : 'modules'}`).then(r => r.json());
    if (d.error) { secopLog('✗ ' + d.error, 't-err'); return; }
    if (subcmd === 'modules') {
      Object.entries(d).forEach(([k, v]) => {
        secopLog(`${v?'✓':'✗'} ${k}`, v ? 't-ok' : 't-warn');
      });
    } else {
      secopLog('✓ Done — see full data in console', 't-ok');
    }
  } catch(e) { secopLog('✗ ' + e, 't-err'); }
}

async function loadModuleStatus() {
  const grid = document.getElementById('sec-modules-grid');
  try {
    const d = await fetch('/api/tools/status').then(r => r.json());
    const mods = d.security_modules || {};
    let html = '';
    Object.entries(mods).forEach(([name, avail]) => {
      html += `<div class="stat-card" style="padding:10px">
        <div style="font-family:'Share Tech Mono';font-size:0.65rem;color:${avail?'var(--green)':'var(--red)'}">
          ${avail ? '✓' : '✗'} ${name.replace(/_/g,' ').toUpperCase()}
        </div>
      </div>`;
    });
    grid.innerHTML = html || '<span class="t-dim">No module data</span>';
  } catch(e) { grid.innerHTML = `<span class="t-err">✗ ${e}</span>`; }
}

async function agentDispatch() {
  const inp = document.getElementById('dispatch-input');
  const task = inp.value.trim();
  if (!task) return;
  inp.value = '';
  dispatchLog(`Dispatching: "${task}"`, 't-gold');
  try {
    const r = await fetch('/api/agent/dispatch', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({task})
    }).then(r => r.json());
    dispatchLog(r.success ? `✓ ${r.message}` : `✗ ${r.error}`, r.success ? 't-ok' : 't-err');
    if (r.success) dispatchLog('→ Check AI ACTIVITY tab for live results', 't-dim');
  } catch(e) { dispatchLog('✗ ' + e, 't-err'); }
}

function quickDispatch(task) {
  document.getElementById('dispatch-input').value = task;
  agentDispatch();
}

// ── Init & polling ────────────────────────────────────────────────────
async function init() {
  await Promise.all([refreshHealth(), refreshModels(), refreshNetwork(), refreshCrypto()]);
}

init();
setInterval(refreshHealth, 5000);
setInterval(refreshModels, 15000);
setInterval(refreshNetwork, 20000);
setInterval(refreshServicesQuick, 10000);
setInterval(refreshActivity, 3000);
setInterval(refreshCrypto, 5000);
</script>
</body>
</html>"""

@app.route("/")
def dashboard():
    return HTML

# ═══════════════════════════════════════════════════════════════════════
# AUTOSTART ON LOGIN
# ═══════════════════════════════════════════════════════════════════════

def install_autostart():
    """Create a .desktop entry for autostart on login (XDG autostart)."""
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    script = PROJECT_ROOT / "start_dashboard.sh"
    desktop = autostart_dir / "larry-dashboard.desktop"
    desktop.write_text(f"""[Desktop Entry]
Type=Application
Name=Larry G-FORCE Command Central
Comment=Larry AI Dashboard Hub
Exec=bash -c "cd {PROJECT_ROOT} && {sys.executable} {Path(__file__).resolve()} >> {PROJECT_ROOT}/logs/dashboard.log 2>&1"
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
""")
    logger.info(f"Autostart installed: {desktop}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-autostart", action="store_true", help="Install XDG autostart entry")
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.install_autostart:
        install_autostart()
        print("✅ Autostart installed. Dashboard will open on next login.")
        return

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║   LARRY G-FORCE — COMMAND CENTRAL v3.0                       ║
╠══════════════════════════════════════════════════════════════╣
║   Dashboard : http://{HOST}:{args.port:<34} ║
║   Press Ctrl+C to stop                                       ║
╚══════════════════════════════════════════════════════════════╝
""")

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{HOST}:{args.port}")).start()

    app.run(host=HOST, port=args.port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
