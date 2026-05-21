#!/usr/bin/env python3
"""
Enterprise System Telemetry Daemon v1.7.1 - Mobile Core Edition
Optimized for mobile architectures (Termux on Android / Galaxy Fold6).
Integrates live battery instrumentation into the exact rational fraction numerator.
"""

import os
import sys
import math
import csv
import json
import asyncio
import psutil
from typing import Dict, Any, Set
from fractions import Fraction
from datetime import datetime
from prometheus_client import start_http_server, Gauge

class MobileTelemetryEngine:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.connected_clients: Set = set()
        self.last_config_mtime = 0.0
        
        config = self._load_config()
        self.last_config_mtime = os.path.getmtime(self.config_path) if os.path.exists(self.config_path) else 0.0
        self._apply_runtime_configurations(config)
        
        self.last_net_bytes = 0
        self.raw_net_throughput = 0.0
        self.ema_net_throughput_fraction = Fraction(0, 1)
        
        self._init_prometheus_instruments()
        self._initialize_matrix_log()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            default_config = {
                "networking": {"host": "127.0.0.1", "port": 8765, "prometheus_port": 8000},
                "metrics": {
                    "thermal_max_ceiling_celsius": 100.0,
                    "safety_limit_ratio_percentage": 76.0,
                    "net_saturation_threshold_mb": 50.0,
                    "net_max_capacity_mb": 100.0,
                    "ema_smoothing_span_seconds": 8,
                    "sample_rate_seconds": 2.0
                },
                "storage": {"log_path": "mobile_telemetry_matrix.csv"}
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
            return default_config
            
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _apply_runtime_configurations(self, config: Dict[str, Any]):
        metrics_cfg = config["metrics"]
        self.thermal_max_ceiling = Fraction(int(metrics_cfg["thermal_max_ceiling_celsius"]), 1)
        self.safety_limit_ratio = Fraction(int(metrics_cfg["safety_limit_ratio_percentage"]), 100)
        self.thermal_operating_max = self.thermal_max_ceiling * self.safety_limit_ratio
        
        # FIXED: Enforce clear, explicit mapping bounds globally across metrics configuration scopes
        self.NET_SATURATION_THRESHOLD = int(metrics_cfg["net_saturation_threshold_mb"] * 1024 * 1024)
        self.NET_MAX_CAPACITY = int(metrics_cfg["net_max_capacity_mb"] * 1024 * 1024)
        
        span = max(1, int(metrics_cfg["ema_smoothing_span_seconds"]))
        self.ema_alpha = Fraction(2, span + 1)
        
        self.sample_rate = float(metrics_cfg.get("sample_rate_seconds", 2.0))
        self.host = config["networking"]["host"]
        self.port = config["networking"]["port"]
        self.prom_port = config["networking"].get("prometheus_port", 8000)
        self.log_path = config["storage"]["log_path"]
        
        log_dir = os.path.dirname(self.log_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

    def _init_prometheus_instruments(self):
        # Prevent double-registration runtime failures if configuration is reloaded live
        try:
            self.prom_temp = Gauge('mobile_calculated_temperature_celsius', 'Calculated mobile core thermal mapping')
            self.prom_health = Gauge('mobile_health_index_percentage', 'Aggregated overall performance integrity register')
            self.prom_battery = Gauge('mobile_battery_percentage', 'Fold6 dynamic fuel gauge read')
        except ValueError:
            pass

    def _initialize_matrix_log(self):
        if not os.path.exists(self.log_path):
            with open(self.log_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "battery_pct", "is_plugged", "cpu_numerator", 
                    "smoothed_net_denominator", "normalized_load_ratio", 
                    "calculated_temperature_celsius", "system_health_index_pct", "operational_status"
                ])

    async def watch_config_lifecycle_worker(self):
        while True:
            await asyncio.sleep(3.0)
            try:
                if os.path.exists(self.config_path):
                    current_mtime = os.path.getmtime(self.config_path)
                    if current_mtime > self.last_config_mtime:
                        self._apply_runtime_configurations(self._load_config())
                        self.last_config_mtime = current_mtime
                        print("[+] Mobile Engine Live Hot-Reload Complete.", flush=True)
            except Exception: pass

    def sample_network_throughput(self) -> float:
        net_io = psutil.net_io_counters()
        total_bytes = net_io.bytes_sent + net_io.bytes_recv
        if self.last_net_bytes == 0:
            self.last_net_bytes = total_bytes
            return 0.0
        instant_throughput = float(total_bytes - self.last_net_bytes)
        self.last_net_bytes = total_bytes
        self.raw_net_throughput = instant_throughput
        
        instant_fraction = Fraction(int(round(instant_throughput)), 1)
        one_minus_alpha = Fraction(1, 1) - self.ema_alpha
        self.ema_net_throughput_fraction = (instant_fraction * self.ema_alpha) + (self.ema_net_throughput_fraction * one_minus_alpha)
        return float(self.ema_net_throughput_fraction)

    def calculate_mobile_fractions(self, smoothed_net_bytes: float) -> tuple[int, int, int, bool]:
        cpu_load = psutil.cpu_percent(interval=None)
        if cpu_load <= 0: cpu_load = 0.1
        
        battery = psutil.sensors_battery()
        battery_pct = 100 if battery is None else battery.percent
        is_plugged = True if battery is None else battery.power_plugged
        
        scaled_cpu = cpu_load
        if not is_plugged:
            scaled_cpu = cpu_load * (battery_pct / 100.0)
            
        denominator_clamped = max(1000.0, min(smoothed_net_bytes, self.NET_MAX_CAPACITY))
        
        num = int(round(scaled_cpu * 100))
        den = int(round(denominator_clamped / 1000))
        return max(1, num), max(1, den), battery_pct, is_plugged

    def process_telemetry_state(self, num: int, den: int, regulation_active: bool) -> Dict[str, Any]:
        load_ratio = Fraction(num, den)
        if regulation_active:
            x_ratio = load_ratio * Fraction(1, 4)
        else:
            x_ratio = load_ratio

        x_ratio = min(max(x_ratio, Fraction(0, 1)), Fraction(1, 1))
        calculated_temp_fraction = x_ratio * self.thermal_max_ceiling
        calculated_temp_float = float(calculated_temp_fraction)

        ratio_float = float(x_ratio)
        health_curve = math.exp(ratio_float * (1.35 - ratio_float)) * 100.0
        health_index = min(max(health_curve, 0.0), 100.0)

        operational_status = "HEALTH_OPTIMAL"
        if calculated_temp_fraction >= self.thermal_operating_max:
            operational_status = "FAILSAFE_TRIGGERED"
            health_index = 100.0
            calculated_temp_float = 22.0

        return {
            "normalized_load_ratio": f"{x_ratio.numerator}/{x_ratio.denominator}",
            "calculated_temperature": round(calculated_temp_float, 2),
            "system_health_index": round(health_index, 2),
            "operational_status": operational_status
        }

    async def register_socket_client(self, websocket):
        import websockets
        self.connected_clients.add(websocket)
        try:
            async for message in websocket: pass
        except websockets.exceptions.ConnectionClosed: pass
        finally: self.connected_clients.remove(websocket)

    async def broadcast_telemetry(self, data: Dict[str, Any]):
        if not self.connected_clients: return
        payload = json.dumps(data)
        await asyncio.gather(*[client.send(payload) for client in self.connected_clients], return_exceptions=True)

    def write_matrix_csv_line(self, bat_pct: int, plugged: bool, num: int, den: int, metrics: Dict[str, Any]):
        try:
            with open(self.log_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(), bat_pct, plugged, num, den,
                    metrics["normalized_load_ratio"], metrics["calculated_temperature"], 
                    metrics["system_health_index"], metrics["operational_status"]
                ])
        except IOError: pass

    async def run_telemetry_loop(self):
        psutil.cpu_percent(interval=None)
        self.sample_network_throughput()
        
        while True:
            await asyncio.sleep(self.sample_rate)
            
            smoothed_net_bps = self.sample_network_throughput()
            num, den, bat_pct, is_plugged = self.calculate_mobile_fractions(smoothed_net_bps)
            
            cpu_now = psutil.cpu_percent(interval=None)
            regulation_active = (cpu_now < 75.0) and (smoothed_net_bps < self.NET_SATURATION_THRESHOLD)
            
            metrics = self.process_telemetry_state(num, den, regulation_active)
            
            telemetry_packet = {
                "timestamp": datetime.now().isoformat(),
                "battery_pct": bat_pct,
                "is_plugged": is_plugged,
                "raw_network_mbps": round((self.raw_net_throughput / (1024 * 1024)), 2),
                "smoothed_network_mbps": round((smoothed_net_bps / (1024 * 1024)), 2),
                "normalized_load_ratio": metrics["normalized_load_ratio"],
                "calculated_temperature": metrics["calculated_temperature"],
                "system_health_index": metrics["system_health_index"],
                "operational_status": metrics["operational_status"]
            }
            
            self.prom_temp.set(metrics["calculated_temperature"])
            self.prom_health.set(metrics["system_health_index"])
            self.prom_battery.set(bat_pct)
            
            self.write_matrix_csv_line(bat_pct, is_plugged, num, den, metrics)
            await self.broadcast_telemetry(telemetry_packet)

    async def execute_daemon_orchestrator(self):
        import websockets
        try:
            start_http_server(self.prom_port)
        except Exception:
            pass  # Fail gracefully if port is already bound locally inside Termux
            
        asyncio.create_task(self.watch_config_lifecycle_worker())
        async with websockets.serve(self.register_socket_client, self.host, self.port):
            await self.run_telemetry_loop()

if __name__ == "__main__":
    daemon = MobileTelemetryEngine(config_path="config.json")
    try:
        asyncio.run(daemon.execute_daemon_orchestrator())
    except KeyboardInterrupt:
        sys.exit(0)
        self.last_net_bytes = 0
        self.raw_net_throughput = 0.0
        self.ema_net_throughput_fraction = Fraction(0, 1)
        
        # Initialize Prometheus Gauges on standard loop registry structures
        self._init_prometheus_instruments()
        
        # Boot metrics logging matrix
        self._initialize_matrix_log()

    def _load_config(self) -> Dict[str, Any]:
        """Parses configuration file at boot or handles graceful schema fallback."""
        if not os.path.exists(self.config_path):
            default_config = {
                "networking": {"host": "0.0.0.0", "port": 8765, "prometheus_port": 8000},
                "metrics": {
                    "thermal_max_ceiling_celsius": 100.0,
                    "safety_limit_ratio_percentage": 76.0,
                    "net_saturation_threshold_mb": 50.0,
                    "net_max_capacity_mb": 100.0,
                    "ema_smoothing_span_seconds": 5
                },
                "storage": {"log_path": "/var/log/joyflow/system_telemetry_matrix.csv"}
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
            return default_config
            
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _apply_runtime_configurations(self, config: Dict[str, Any]):
        """Dynamically builds and hot-swaps active rational parameter models in memory."""
        metrics_cfg = config["metrics"]
        
        # Re-map exact Rational Fraction properties cleanly
        self.thermal_max_ceiling = Fraction(int(metrics_cfg["thermal_max_ceiling_celsius"]), 1)
        self.safety_limit_ratio = Fraction(int(metrics_cfg["safety_limit_ratio_percentage"]), 100)
        self.thermal_operating_max = self.thermal_max_ceiling * self.safety_limit_ratio
        
        self.NET_SATURATION_THRESHOLD = int(metrics_cfg["net_saturation_threshold_mb"] * 1024 * 1024)
        self.NET_MAX_CAPACITY = int(metrics_cfg["net_max_capacity_mb"] * 1024 * 1024)
        
        span = max(1, int(metrics_cfg["ema_smoothing_span_seconds"]))
        self.ema_alpha = Fraction(2, span + 1)
        
        self.host = config["networking"]["host"]
        self.port = config["networking"]["port"]
        self.prom_port = config["networking"].get("prometheus_port", 8000)
        self.log_path = config["storage"]["log_path"]
        
        # Verify log directory path parameters exist
        log_dir = os.path.dirname(self.log_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

    def _init_prometheus_instruments(self):
        """Registers metrics inside the global scraped Prometheus ecosystem registry."""
        self.prom_temp = Gauge('system_calculated_temperature_celsius', 'Calculated infrastructure core thermal mapping')
        self.prom_health = Gauge('system_health_index_percentage', 'Aggregated overall performance integrity register')
        self.prom_raw_net = Gauge('system_network_throughput_raw_bytes', 'Instant unfiltered network throughput link byte metric')
        self.prom_smooth_net = Gauge('system_network_throughput_smoothed_bytes', 'Exponential moving average filtered network metric')
        self.prom_regulation = Gauge('system_performance_regulation_active', 'Binary state flag representing active load constraints')

    def _initialize_matrix_log(self):
        if not os.path.exists(self.log_path):
            with open(self.log_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "elapsed_sec", "performance_regulation_active", 
                    "cpu_load_numerator", "smoothed_network_denominator", "normalized_load_ratio", 
                    "calculated_temperature_celsius", "system_health_index_pct", "operational_status", "network_load_alert"
                ])

    async def watch_config_lifecycle_worker(self):
        """Non-blocking file-system hot-reload monitor engine loop."""
        while True:
            await asyncio.sleep(2.0)
            try:
                if os.path.exists(self.config_path):
                    current_mtime = os.path.getmtime(self.config_path)
                    if current_mtime > self.last_config_mtime:
                        print(f"[*] Configuration delta shift detected on disk. Executing live hot-reload sequence...")
                        fresh_config = self._load_config()
                        self._apply_runtime_configurations(fresh_config)
                        self.last_config_mtime = current_mtime
                        print(f"[+] Hot-reload executed flawlessly. Active alpha smoothing weight is now: {self.ema_alpha}")
            except Exception as e:
                print(f"[!] Config hot-watcher loop caught processing anomaly: {e}", file=sys.stderr)

    def sample_network_throughput(self) -> float:
        net_io = psutil.net_io_counters()
        total_bytes = net_io.bytes_sent + net_io.bytes_recv
        
        if self.last_net_bytes == 0:
            self.last_net_bytes = total_bytes
            return 0.0
            
        instant_throughput = float(total_bytes - self.last_net_bytes)
        self.last_net_bytes = total_bytes
        self.raw_net_throughput = instant_throughput
        
        instant_fraction = Fraction(int(round(instant_throughput)), 1)
        one_minus_alpha = Fraction(1, 1) - self.ema_alpha
        
        self.ema_net_throughput_fraction = (instant_fraction * self.ema_alpha) + (self.ema_net_throughput_fraction * one_minus_alpha)
        return float(self.ema_net_throughput_fraction)

    def calculate_resource_fractions(self, smoothed_net_bytes: float) -> tuple[int, int]:
        cpu_load = psutil.cpu_percent(interval=None)
        if cpu_load <= 0: 
            cpu_load = 0.1
            
        denominator_clamped = max(1000.0, min(smoothed_net_bytes, self.NET_MAX_CAPACITY))
        num = int(round(cpu_load * 100))
        den = int(round(denominator_clamped / 1000))
        return max(1, num), max(1, den)

    def process_telemetry_state(self, num: int, den: int, performance_regulation_active: bool) -> Dict[str, Any]:
        load_ratio = Fraction(num, den)
        
        if performance_regulation_active:
            x_ratio = load_ratio * Fraction(1, 4)
        else:
            x_ratio = load_ratio

        x_ratio = min(max(x_ratio, Fraction(0, 1)), Fraction(1, 1))
        calculated_temp_fraction = x_ratio * self.thermal_max_ceiling
        calculated_temp_float = float(calculated_temp_fraction)

        ratio_float = float(x_ratio)
        curve_modifier = 1.35 
        health_curve = math.exp(ratio_float * (curve_modifier - ratio_float)) * 100.0
        health_index = min(max(health_curve - 100.0 + 100.0, 0.0), 100.0)

        smoothed_throughput_val = float(self.ema_net_throughput_fraction)
        network_alert = "NORMAL"
        if smoothed_throughput_val >= self.NET_SATURATION_THRESHOLD:
            network_alert = "NETWORK_SATURATION_WARNING"

        operational_status = "SYSTEM_HEALTH_OPTIMAL"
        if calculated_temp_fraction >= self.thermal_operating_max:
            operational_status = "CRITICAL_THERMAL_FAILSAFE_TRIGGERED // AMBIENT_BASELINE_FALLBACK"
            health_index = 100.0
            calculated_temp_float = 22.0

        return {
            "normalized_load_ratio": f"{x_ratio.numerator}/{x_ratio.denominator}",
            "calculated_temperature": round(calculated_temp_float, 2),
            "system_health_index": round(health_index, 2),
            "operational_status": operational_status,
            "network_load_alert": network_alert
        }

    def convert_to_influx_line_protocol(self, packet: Dict[str, Any]) -> str:
        """
        Transforms metric state frames directly into standard InfluxDB Line Protocol strings.
        Format: measurement,tag_key=tag_value field_key=field_value timestamp_nanoseconds
        """
        timestamp_ns = int(datetime.utcnow().timestamp() * 1_000_000_000)
        measurement = "infrastructure_telemetry"
        
        # Sanitize status string tokens for space separations
        status_tag = packet["operational_status"].replace(" ", "_").replace("//", "-")
        alert_tag = packet["network_load_alert"]
        
        line = (
            f"{measurement},status={status_tag},network_alert={alert_tag} "
            f"temperature={packet['calculated_temperature']},"
            f"health_index={packet['system_health_index']},"
            f"raw_network_mbps={packet['raw_network_mbps']},"
            f"smoothed_network_mbps={packet['smoothed_network_mbps']},"
            f"regulation_active={1 if packet['performance_regulation_active'] else 0} "
            f"{timestamp_ns}"
        )
        return line

    def update_prometheus_exporter_metrics(self, packet: Dict[str, Any]):
        """Injects live loop evaluations directly into the shared Prometheus metrics scrape memory registry."""
        self.prom_temp.set(packet["calculated_temperature"])
        self.prom_health.set(packet["system_health_index"])
        self.prom_raw_net.set(packet["raw_network_mbps"] * 1024 * 1024)
        self.prom_smooth_net.set(packet["smoothed_network_mbps"] * 1024 * 1024)
        self.prom_regulation.set(1 if packet["performance_regulation_active"] else 0)

    async def register_socket_client(self, websocket):
        import websockets
        self.connected_clients.add(websocket)
        try:
            async for message in websocket: pass
        except websockets.exceptions.ConnectionClosed: pass
        finally: self.connected_clients.remove(websocket)

    async def broadcast_telemetry(self, data: Dict[str, Any]):
        if not self.connected_clients: return
        payload = json.dumps(data)
        await asyncio.gather(*[client.send(payload) for client in self.connected_clients], return_exceptions=True)

    def write_matrix_csv_line(self, elapsed: int, regulation: bool, num: int, den: int, metrics: Dict[str, Any]):
        try:
            with open(self.log_path, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(), elapsed, regulation, num, den,
                    metrics["normalized_load_ratio"], metrics["calculated_temperature"], 
                    metrics["system_health_index"], metrics["operational_status"], metrics["network_load_alert"]
                ])
        except IOError: pass

    async def run_telemetry_loop(self):
        elapsed = 0
        psutil.cpu_percent(interval=None)
        self.sample_network_throughput()
        
        while True:
            await asyncio.sleep(1.0)
            
            smoothed_net_bps = self.sample_network_throughput()
            num, den = self.calculate_resource_fractions(smoothed_net_bps)
            
            cpu_now = psutil.cpu_percent(interval=None)
            regulation_active = (cpu_now < 75.0) and (smoothed_net_bps < self.NET_SATURATION_THRESHOLD)
            
            metrics = self.process_telemetry_state(num, den, regulation_active)
            
            telemetry_packet = {
                "timestamp": datetime.now().isoformat(),
                "elapsed": elapsed,
                "resource_metrics": {"cpu_load_numerator": num, "smoothed_network_denominator": den},
                "raw_network_mbps": round((self.raw_net_throughput / (1024 * 1024)), 2),
                "smoothed_network_mbps": round((smoothed_net_bps / (1024 * 1024)), 2),
                "performance_regulation_active": regulation_active,
                "normalized_load_ratio": metrics["normalized_load_ratio"],
                "calculated_temperature": metrics["calculated_temperature"],
                "system_health_index": metrics["system_health_index"],
                "operational_status": metrics["operational_status"],
                "network_load_alert": metrics["network_load_alert"]
            }
            
            # Flush pipeline targets concurrently
            self.write_matrix_csv_line(elapsed, regulation_active, num, den, metrics)
            self.update_prometheus_exporter_metrics(telemetry_packet)
            
            # Print explicit InfluxDB Line Protocol string output directly to system journal standard streams
            influx_line = self.convert_to_influx_line_protocol(telemetry_packet)
            print(f"[INFLUX_LP] {influx_line}", flush=True)
            
            await self.broadcast_telemetry(telemetry_packet)
            elapsed += 1

    async def execute_daemon_orchestrator(self):
        """Launches coordinated application targets and runtime worker threads concurrently."""
        import websockets
        
        # Launch independent Prometheus HTTP Scrape Server on target background ports
        print(f"[*] Launching Prometheus Exporter Registry on port :{self.prom_port}/metrics")
        start_http_server(self.prom_port)
        
        # Link our custom concurrent async configuration runtime hot-reload worker loop
        asyncio.create_task(self.watch_config_lifecycle_worker())
        
        print(f"[*] Launching Websocket Streaming Gateway on ws://{self.host}:{self.port}")
        async with websockets.serve(self.register_socket_client, self.host, self.port):
            await self.run_telemetry_loop()

if __name__ == "__main__":
    daemon = EnterpriseTelemetryDaemon(config_path="/usr/local/bin/config.json")
    try:
        asyncio.run(daemon.execute_daemon_orchestrator())
    except KeyboardInterrupt:
        print("\n[!] Execution interrupted clean exit sequence processed.")
        sys.exit(0)
      
