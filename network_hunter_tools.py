
"""
Network Hunter - Active Reconnaissance and Network Discovery Tools
Scans network topology, discovers devices, fingerprints services
"""

import subprocess
import json
import logging
import sys
import re
import socket
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass
from ipaddress import ip_network, IPv4Network

@dataclass
class NetworkTarget:
    """Target network definition"""
    network_range: str  # CIDR notation (e.g., 192.168.1.0/24)
    excluded_ips: List[str] = None
    ports_to_scan: List[int] = None

class NetworkHunter:
    """Active reconnaissance and network discovery"""

    def __init__(self, output_dir: str = "security_reports"):
        self.output_dir = output_dir
        Path(output_dir).mkdir(exist_ok=True)
        self.setup_logging()
        self.discovered_hosts = {}
        self.services = {}

    def setup_logging(self):
        """Setup logging"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"{self.output_dir}/network_hunter_{timestamp}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-8s | %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    def discover_hosts(self, target: NetworkTarget) -> Dict:
        """Discover active hosts on network"""
        self.logger.info(f"\n{'='*80}")
        self.logger.info("NETWORK DISCOVERY")
        self.logger.info(f"{'='*80}")
        self.logger.info(f"Target: {target.network_range}")
        
        results = {
            'network': target.network_range,
            'discovery_method': 'ARP/ICMP',
            'hosts_found': [],
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Parse CIDR network
            network = ip_network(target.network_range, strict=False)
            excluded = set(target.excluded_ips or [])
            
            self.logger.info(f"Scanning {network.num_addresses} addresses...")
            
            # Generate IP list
            ips = [str(ip) for ip in network.hosts() if str(ip) not in excluded]
            
            # Use ARP scan (faster for local networks)
            try:
                arp_cmd = f"arp-scan -l 2>/dev/null || sudo arp-scan -l 2>/dev/null"
                result = subprocess.run(arp_cmd, shell=True, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and result.stdout:
                    self.logger.info("ARP scan results:")
                    for line in result.stdout.split('\n'):
                        if re.match(r'\d+\.\d+\.\d+\.\d+', line):
                            parts = line.split()
                            if len(parts) >= 2:
                                ip = parts[0]
                                mac = parts[1] if len(parts) > 1 else "unknown"
                                vendor = ' '.join(parts[2:]) if len(parts) > 2 else "unknown"
                                
                                self.logger.info(f"  ✓ {ip:15} {mac:20} {vendor}")
                                results['hosts_found'].append({
                                    'ip': ip,
                                    'mac': mac,
                                    'vendor': vendor,
                                    'discovery_method': 'ARP',
                                    'timestamp': datetime.now().isoformat()
                                })
            except Exception as e:
                self.logger.warning(f"ARP scan failed: {e}")
            
            # Fallback to ICMP ping sweep
            if not results['hosts_found']:
                self.logger.info("Fallback: ICMP ping sweep...")
                for ip in ips[:10]:  # Limit to first 10 for speed
                    try:
                        result = subprocess.run(f"ping -c 1 -W 1 {ip}", shell=True, 
                                              capture_output=True, timeout=5)
                        if result.returncode == 0:
                            self.logger.info(f"  ✓ {ip} is reachable")
                            results['hosts_found'].append({
                                'ip': ip,
                                'reachable': True,
                                'discovery_method': 'ICMP',
                                'timestamp': datetime.now().isoformat()
                            })
                    except Exception as e:
                        self.logger.debug(f"Ping {ip}: {e}")
            
            self.discovered_hosts = results
            return results
            
        except Exception as e:
            self.logger.error(f"Host discovery failed: {e}")
            return results

    def scan_services(self, hosts: List[str], ports: List[int] = None) -> Dict:
        """Scan for running services on discovered hosts"""
        self.logger.info(f"\n{'='*80}")
        self.logger.info("SERVICE DETECTION")
        self.logger.info(f"{'='*80}")
        
        if ports is None:
            ports = [22, 80, 443, 8080, 8081, 5560, 8082, 3306, 5432, 6379, 27017]
        
        results = {
            'hosts': hosts,
            'ports_scanned': ports,
            'services': [],
            'timestamp': datetime.now().isoformat()
        }
        
        for host in hosts:
            self.logger.info(f"\nScanning {host}...")
            
            for port in ports:
                try:
                    # Try socket connection
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        self.logger.info(f"  ✓ Port {port:5} is OPEN")
                        
                        # Try to identify service
                        service_name = self.identify_service(host, port)
                        
                        results['services'].append({
                            'host': host,
                            'port': port,
                            'status': 'open',
                            'service': service_name,
                            'timestamp': datetime.now().isoformat()
                        })
                        
                except Exception as e:
                    self.logger.debug(f"  Port {port}: {e}")
        
        self.services = results
        return results

    def identify_service(self, host: str, port: int) -> str:
        """Try to identify service on port"""
        service_map = {
            22: "SSH",
            80: "HTTP",
            443: "HTTPS",
            3306: "MySQL",
            5432: "PostgreSQL",
            6379: "Redis",
            27017: "MongoDB",
            8080: "FXJEFE Main Server",
            8081: "FXJEFE Sentiment Server",
            5560: "FXJEFE AI Ensemble",
            8082: "FXJEFE HFT Transformer",
        }
        
        if port in service_map:
            return service_map[port]
        
        # Try banner grabbing
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((host, port))
            banner = sock.recv(1024).decode('utf-8', errors='ignore')
            sock.close()
            
            if banner:
                return f"Custom ({banner[:30]})"
        except:
            pass
        
        return "Unknown"

    def fingerprint_os(self, hosts: List[str]) -> Dict:
        """Attempt OS fingerprinting"""
        self.logger.info(f"\n{'='*80}")
        self.logger.info("OS FINGERPRINTING")
        self.logger.info(f"{'='*80}")
        
        results = {
            'fingerprints': [],
            'timestamp': datetime.now().isoformat()
        }
        
        for host in hosts:
            self.logger.info(f"\nFingerprinting {host}...")
            
            try:
                # TTL-based fingerprinting
                cmd = f"ping -c 1 -W 1 {host} | grep ttl"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                
                if result.stdout:
                    ttl_match = re.search(r'ttl=(\d+)', result.stdout)
                    if ttl_match:
                        ttl = int(ttl_match.group(1))
                        
                        # Basic OS detection from TTL
                        if ttl >= 64 and ttl <= 128:
                            os_type = "Linux/Unix"
                        elif ttl >= 32 and ttl <= 64:
                            os_type = "Windows"
                        elif ttl >= 200:
                            os_type = "Cisco/Network Device"
                        else:
                            os_type = "Unknown"
                        
                        self.logger.info(f"  TTL: {ttl} -> Likely: {os_type}")
                        
                        results['fingerprints'].append({
                            'host': host,
                            'ttl': ttl,
                            'os_guess': os_type,
                            'confidence': 'low'
                        })
            
            except Exception as e:
                self.logger.warning(f"Fingerprinting {host}: {e}")
        
        return results

    def check_network_security(self, hosts: List[str]) -> Dict:
        """Check for common security issues"""
        self.logger.info(f"\n{'='*80}")
        self.logger.info("SECURITY CHECKS")
        self.logger.info(f"{'='*80}")
        
        results = {
            'security_issues': [],
            'recommendations': [],
            'timestamp': datetime.now().isoformat()
        }
        
        for host in hosts:
            self.logger.info(f"\nChecking {host}...")
            
            checks = [
                ("SSH on default port", 22, "Consider using non-standard port"),
                ("HTTP (unencrypted)", 80, "Use HTTPS instead"),
                ("Telnet", 23, "Never use - use SSH"),
                ("FTP (unencrypted)", 21, "Use SFTP instead"),
                ("Database exposed", 3306, "Ensure DB is not internet-facing"),
            ]
            
            for check_name, port, recommendation in checks:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        self.logger.warning(f"  ⚠ {check_name} is accessible on port {port}")
                        results['security_issues'].append({
                            'host': host,
                            'issue': check_name,
                            'port': port,
                            'severity': 'high' if port in [21, 23] else 'medium'
                        })
                        
                        if recommendation not in results['recommendations']:
                            results['recommendations'].append(recommendation)
                
                except Exception as e:
                    self.logger.debug(f"Check {check_name}: {e}")
        
        return results

    def generate_report(self) -> str:
        """Generate network discovery report"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"{self.output_dir}/network_hunter_report_{timestamp}.json"
        
        report = {
            'discovery': self.discovered_hosts,
            'services': self.services,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"\nReport saved: {report_file}")
        return report_file

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Network Hunter - Network Discovery & Reconnaissance")
    parser.add_argument("--network", default="192.168.1.0/24", help="CIDR network to scan")
    parser.add_argument("--exclude", nargs="+", default=[], help="IPs to exclude from scan")
    parser.add_argument("--ports", nargs="+", type=int, default=[22, 80, 443, 8080, 8081, 5560, 8082],
                       help="Ports to scan")
    parser.add_argument("--output", default="security_reports", help="Output directory")
    
    args = parser.parse_args()
    
    hunter = NetworkHunter(args.output)
    
    # Stage 1: Discover hosts
    target = NetworkTarget(network_range=args.network, excluded_ips=args.exclude, ports_to_scan=args.ports)
    discovery_results = hunter.discover_hosts(target)
    
    if discovery_results['hosts_found']:
        discovered_ips = [h.get('ip') for h in discovery_results['hosts_found']]
        
        # Stage 2: Scan services
        hunter.scan_services(discovered_ips, args.ports)
        
        # Stage 3: Fingerprint OS
        hunter.fingerprint_os(discovered_ips)
        
        # Stage 4: Security checks
        hunter.check_network_security(discovered_ips)
    
    # Generate report
    hunter.generate_report()

if __name__ == "__main__":
    main()
