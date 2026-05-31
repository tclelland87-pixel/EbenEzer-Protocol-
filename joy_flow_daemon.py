#!/usr/bin/env python3
"""
Telemetry Engine v4.6 - Enterprise Production Core Runtime System
Combines exact rational calculus, thread-safe asynchronous disk auditing,
dynamic boundary hot-reloading, and an operational TCP server interface.
Optimized for standalone open-source simulation deployment.

Licensed under the MIT License.
Verified using parallel design patterns for distributed computing telemetry.
"""

import os
import sys
import time
import math
import queue
import json
import socket
import threading
import socketserver
from datetime import datetime, timezone
from fractions import Fraction
from collections import deque
from typing import Dict, Any, List, Optional

# Configuration and Infrastructure Constants
CONFIG_PATH = "cluster_config.json"
LOG_PATH = "cluster_audit.jsonl"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 9999
MAX_SERVER_THREADS = 50  # Enforces an upper limit to prevent thread exhaustion

# ============================================================================
# MODULE 1: CORE INVARIANT STRUCTURAL DEFINITIONS
# ============================================================================

class TelemetryZone:
    """Manages exact rational state, window buffers, and network heartbeat metrics with strict thread safety."""
    
    def __init__(self, zone_name: str, safety_ratio: Fraction, adjacent_zones: List[str], window_size: int = 5):
        self.lock = threading.RLock()
        self.name = zone_name
        self.t_critical = Fraction(100, 1)
        self.t_operating_max = self.t_critical * safety_ratio
        self.adjacent_zones = adjacent_zones
        self.window_size = max(1, window_size)
        
        # Ingestion metrics
        self.current_friction = Fraction(0, 1)
        self.history: deque = deque(maxlen=self.window_size)
        self.last_seen_epoch = time.time()
        
        # State tracking markers
        self.status = "OPERATIONAL_STABLE"
        self.current_temp = 0.0
        self.integrity = 100.0
        self.is_alive = True

    def update_bounds(self, safety_ratio: Fraction, window_size: int):
        """Atomically re-targets boundary parameters mid-flight via configuration reloaders."""
        with self.lock:
            self.t_operating_max = self.t_critical * safety_ratio
            validated_window = max(1, window_size)
            if validated_window != self.window_size:
                self.window_size = validated_window
                old_history = list(self.history)
                self.history = deque(old_history, maxlen=validated_window)

    def push_friction(self, friction_fraction: Fraction):
        """Appends external friction metrics to history sequentially to maintain strict timeline integrity."""
        with self.lock:
            self.current_friction = friction_fraction
            self.history.append(friction_fraction)
            self.last_seen_epoch = time.time()

    def calculate_metrics(self, timeout_limit_sec: float) -> Dict[str, Any]:
        """Calculates temperature and integrity metrics, enforcing dead-man kill-switch limits without side effects."""
        with self.lock:
            if time.time() - self.last_seen_epoch > timeout_limit_sec:
                self.is_alive = False
                self.status = "DISCONNECTED // AIR_GAPPED_SAFE_MODE"
                self.current_temp = 22.0
                self.integrity = 100.0
                return self._build_payload()
            
            self.is_alive = True
            
            # Read rolling history safely without mutating the history deque mid-poll
            history_snapshot = list(self.history)
            if not history_snapshot:
                history_snapshot = [self.current_friction]
                
            rolling_avg_friction = sum(history_snapshot) / Fraction(len(history_snapshot), 1)
            temp_fraction = rolling_avg_friction * self.t_critical
            self.current_temp = float(temp_fraction)
            
            # Sanitize friction float for the integrity curve to prevent Overflow/Underflow panics
            friction_float = float(self.current_friction)
            friction_float = min(max(friction_float, -50.0), 50.0)
            
            try:
                # FUNCTIONAL STRETCHY MATH: Adjustable Sigmoid Curve
                # k = steepness of the elastic snap
                # x_0 = threshold where the stretch begins to give way significantly
                k = 0.8
                x_0 = 4.0
                
                # Sigmoid formulation ensuring smooth decay that holds firm then stretches and snaps down
                integrity_curve = 100.0 / (1.0 + math.exp(k * (abs(friction_float) - x_0)))
                self.integrity = min(max(integrity_curve, 0.0), 100.0)
            except (OverflowError, ValueError):
                self.integrity = 0.0
                
            if temp_fraction >= self.t_operating_max:
                self.status = "FAILOVER_ACTIVATED // REVERTING TO BASELINE"
                self.current_temp = 22.0
                # Fixed: Integrity is no longer falsely overwritten to 100.0 here, preserving stretchy physics
            else:
                self.status = "OPERATIONAL_STABLE"
                
            return self._build_payload()

    def _build_payload(self) -> Dict[str, Any]:
        return {
            "zone_id": self.name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "friction_fraction": f"{self.current_friction.numerator}/{self.current_friction.denominator}",
            "temperature": round(self.current_temp, 2),
            "integrity": round(self.integrity, 2),
            "status": self.status
        }


class NodeRegistry:
    """Manages telemetry topology maps and inter-zone routing fabrics with concurrent read/write protection."""
    
    def __init__(self):
        self.lock = threading.RLock()
        self.zones: Dict[str, TelemetryZone] = {}

    def add_zone(self, name: str, safety_ratio: Fraction, adjacent_zones: List[str], window_size: int = 5):
        """Initializes a TelemetryZone and maps it into the mesh topology."""
        with self.lock:
            self.zones[name] = TelemetryZone(name, safety_ratio, adjacent_zones, window_size)

    def route_flux(self, target: str, friction_fraction: Fraction, timeout_limit_sec: float) -> Optional[Dict[str, Any]]:
        """Pushes delta changes into a target node and runs evaluation."""
        with self.lock:
            if target in self.zones:
                zone = self.zones[target]
                zone.push_friction(friction_fraction)
                return zone.calculate_metrics(timeout_limit_sec)
            return None


class ConfigurationReloader:
    """Watches external changes to adjust zone boundaries safely on the fly."""
    
    def __init__(self, registry: NodeRegistry):
        self.registry = registry

    def hot_swap_zone(self, name: str, new_safety_ratio: Fraction, new_window_size: int) -> bool:
        """Injects updated fractional constraints directly into an active mesh node."""
        if name in self.registry.zones:
            self.registry.zones[name].update_bounds(new_safety_ratio, new_window_size)
            return True
        return False
# ============================================================================
# MODULE 2: NETWORK PROCESSING & ASYNCHRONOUS I/O CORRIDORS
# ============================================================================

class AuditLogger(threading.Thread):
    """Asynchronously drains a thread-safe queue to write telemetry frames cleanly to disk storage."""
    
    def __init__(self, log_path: str):
        super().__init__(daemon=True, name="AuditLoggerThread")
        self.log_path = log_path
        self.queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()

    def log(self, payload: Dict[str, Any]):
        """Enqueues a telemetry payload for non-blocking disk persistence."""
        self.queue.put(payload)

    def stop(self):
        """Signals the background worker to terminate after draining the queue."""
        self._stop_event.set()
        self.queue.put(None)

    def run(self):
        while True:
            try:
                payload = self.queue.get(timeout=0.5)
                if payload is None:
                    break
                
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload) + "\n")
                    f.flush()  # Hard flush to prevent internal buffer data losses during sudden container drops
                self.queue.task_done()
            except queue.Empty:
                if self._stop_event.is_set():
                    break
            except Exception as e:
                sys.stderr.write(f"[AuditLogger Error] Failed to write entry to storage layout: {e}\n")


class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):
    """Handles operational network requests to update friction fractions or query status with explicit byte serialization."""
    
    def handle(self):
        self.request.settimeout(10.0)
        try:
            raw_data = self.request.recv(4096)
            if not raw_data:
                return
                
            data = raw_data.decode('utf-8').strip()
            if not data:
                return
            
            packet = json.loads(data)
            action = packet.get("action")
            server = self.server  # Accesses the fully anchored TelemetryTCPServer runtime context

            if action == "update":
                zone_id = packet.get("zone_id")
                num = packet.get("num", 0)
                den = packet.get("den", 1)
                
                if den == 0:
                    response = {"status": "ERROR", "message": "Zero denominator is a mathematical invalidation."}
                else:
                    fraction_input = Fraction(num, den)
                    metrics = server.registry.route_flux(zone_id, fraction_input, server.timeout_limit)
                    
                    if metrics:
                        server.audit_logger.log(metrics)
                        response = {"status": "SUCCESS", "metrics": metrics}
                    else:
                        response = {"status": "ERROR", "message": f"Zone '{zone_id}' not found in registry."}
                        
            elif action == "query":
                zone_id = packet.get("zone_id")
                target_zone = None
                
                with server.registry.lock:
                    if zone_id in server.registry.zones:
                        target_zone = server.registry.zones[zone_id]
                
                if target_zone is not None:
                    metrics = target_zone.calculate_metrics(server.timeout_limit)
                    response = {"status": "SUCCESS", "metrics": metrics}
                else:
                    response = {"status": "ERROR", "message": f"Zone '{zone_id}' not found."}
            else:
                response = {"status": "ERROR", "message": f"Unknown action: '{action}'"}

            self.request.sendall(json.dumps(response).encode('utf-8'))

        except json.JSONDecodeError:
            error_resp = {"status": "ERROR", "message": "Malformed JSON payload data parameters."}
            try:
                self.request.sendall(json.dumps(error_resp).encode('utf-8'))
            except Exception:
                pass
        except Exception as e:
            sys.stderr.write(f"[Server Request Error] Exception trace: {e}\n")


class TelemetryTCPServer(socketserver.ThreadingTCPServer):
    """Multi-threaded TCP server leveraging bounded semaphore guards to shield system resources from traffic exhaustion."""
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, registry: NodeRegistry, audit_logger: AuditLogger, timeout_limit: float = 30.0):
        self.registry = registry
        self.audit_logger = audit_logger
        self.timeout_limit = timeout_limit
        self.thread_pool_semaphore = threading.Semaphore(MAX_SERVER_THREADS)
        socketserver.ThreadingTCPServer.__init__(self, server_address, handler_class, bind_and_activate=True)

    def process_request(self, request, client_address):
        """Intercepts processing windows to ensure socket executions stay under global limits."""
        if self.thread_pool_semaphore.acquire(blocking=False):
            super().process_request(request, client_address)
        else:
            try:
                reject_payload = {"status": "ERROR", "message": "Server traffic threshold capacity breached."}
                request.sendall(json.dumps(reject_payload).encode('utf-8'))
                request.close()
            except Exception:
                pass

    def close_request(self, request):
        """Releases the semaphore lock back to the allocation context block upon stream completion."""
        super().close_request(request)
        try:
            self.thread_pool_semaphore.release()
        except ValueError:
            pass

# ============================================================================
# MODULE 3: SYSTEM INITIALIZATION AND RUNTIME ENTRYPOINT
# ============================================================================

def bootstrap_default_config(path: str):
    """Generates an initial operational cluster mesh layout configuration if missing on disk."""
    default_config = {
        "timeout_limit_sec": 15.0,
        "zones": {
            "ALPHA_CORE": {"safety_ratio_num": 4, "safety_ratio_den": 5, "window_size": 5, "adjacencies": ["BETA_WEST"]},
            "BETA_WEST": {"safety_ratio_num": 3, "safety_ratio_den": 4, "window_size": 4, "adjacencies": ["ALPHA_CORE"]}
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(default_config, f, indent=4)


def load_and_apply_config(registry: NodeRegistry, reloader: ConfigurationReloader) -> float:
    """Reads local JSON cluster matrices outside internal locks to eliminate dictionary translation bottlenecks."""
    if not os.path.exists(CONFIG_PATH):
        bootstrap_default_config(CONFIG_PATH)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    timeout_limit = float(config.get("timeout_limit_sec", 30.0))
    zones_data = config.get("zones", {})

    for zone_name, data in zones_data.items():
        ratio = Fraction(data.get("safety_ratio_num", 7), data.get("safety_ratio_den", 10))
        window = int(data.get("window_size", 5))
        adj = list(data.get("adjacencies", []))

        with registry.lock:
            if zone_name in registry.zones:
                reloader.hot_swap_zone(zone_name, ratio, window)
            else:
                registry.add_zone(zone_name, ratio, adj, window)
                
    return timeout_limit


def main():
    print(f"[{datetime.now().isoformat()}] Launching Telemetry Engine v4.6 Core Runtime...")

    # Initialize foundational decoupled processing components
    registry = NodeRegistry()
    reloader = ConfigurationReloader(registry)
    timeout_limit = load_and_apply_config(registry, reloader)

    audit_logger = AuditLogger(LOG_PATH)
    audit_logger.start()

    # Anchor network boundaries securely with upfront socket recycling
    try:
        server = TelemetryTCPServer((SERVER_HOST, SERVER_PORT), ThreadedTCPRequestHandler, registry, audit_logger, timeout_limit)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True, name="TCPServerThread")
        server_thread.start()
        print(f"[*] Telemetry TCP Server executing on tcp://{SERVER_HOST}:{SERVER_PORT}")
    except Exception as e:
        sys.stderr.write(f"[Fatal Launch Failure] Could not anchor network boundary maps: {e}\n")
        audit_logger.stop()
        sys.exit(1)

    # Runtime operational loop: updates status parameters dynamically via periodic configuration sweeps
    print("[*] Runtime operational mesh fully online. Press Ctrl+C to terminate cleanly.")
    try:
        while True:
            try:
                server.timeout_limit = load_and_apply_config(registry, reloader)
            except Exception as e:
                sys.stderr.write(f"[Hot-Reload Warning] Dynamic config parsing pass skipped: {e}\n")

            with registry.lock:
                current_zones = list(registry.zones.values())
                
            for zone in current_zones:
                stale_payload = zone.calculate_metrics(server.timeout_limit)
                if not zone.is_alive:
                    audit_logger.log(stale_payload)

            time.sleep(2.5)
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().isoformat()}] Shutdown sequence triggered by system administrator.")
    finally:
        print("[*] Flushing audit pipelines and severing active network boundaries...")
        server.shutdown()
        server.server_close()
        audit_logger.stop()
        audit_logger.join()
        print("[+] Telemetry Engine structural runtime completely offline.")


if __name__ == "__main__":
    main()
  
