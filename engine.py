import os
import csv
import math
import json
import asyncio
import psutil
from typing import Dict, Any, Set
from fractions import Fraction
from datetime import datetime
from prometheus_client import Gauge

class EnterpriseTelemetryDaemon:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.connected_clients: Set = set()
        self.last_config_mtime = 0.0
        
        self.config = self._load_config()
        self.last_config_mtime = os.path.getmtime(self.config_path) if os.path.exists(self.config_path) else 0.0
        self._apply_runtime_configurations(self.config)
        
        self.last_net_bytes = 0
        self.raw_net_throughput = 0.0
        self.ema_net_throughput_fraction = Fraction(0, 1)
        
        self._init_prometheus_instruments()
        self._initialize_matrix_log()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            default_config = {
                "networking": {
                    "host": "0.0.0.0", "port": 8765, "prometheus_port": 8000,
                    "allowed_cors_origins": ["*"]
                },
                "metrics": {
                    "thermal_max_ceiling_celsius": 100.0, "safety_limit_ratio_percentage": 76.0,
                    "net_saturation_threshold_mb": 50.0, "net_max_capacity_mb": 100.0,
                    "ema_smoothing_span_seconds": 5, "sample_rate_seconds": 2.0
                },
                "storage": {"log_path": "./system_telemetry_matrix.csv"}
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
            return default_config
            
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _apply_runtime_configurations(self, config: Dict[str, Any]):
        metrics_cfg = config["metrics"]
        
        # FIXED: Pass floating numeric conversions directly to Fraction to avoid integer truncation
        self.thermal_max_ceiling = Fraction(float(metrics_cfg["thermal_max_ceiling_celsius"]))
        self.safety_limit_ratio = Fraction(float(metrics_cfg["safety_limit_ratio_percentage"])) / 100
        self.thermal_operating_max = self.thermal_max_ceiling * self.safety_limit_ratio
        
        self.NET_SATURATION_THRESHOLD = int(metrics_cfg["net_saturation_threshold_mb"] * 1024 * 1024)
        self.NET_MAX_CAPACITY = int(metrics_cfg["net_max_capacity_mb"] * 1024 * 1024)
        
        span = max(1, int(metrics_cfg["ema_smoothing_span_seconds"]))
        self.ema_alpha = Fraction(2, span + 1)
        
        self.sample_rate = float(metrics_cfg.get("sample_rate_seconds", 2.0))
        self.host = config["networking"]["host"]
        self.port = config["networking"]["port"]
        self.prom_port = config["networking"].get("prometheus_port", 8000)
        self.cors_origins = config["networking"].get("allowed_cors_origins", ["*"])
        self.log_path = config["storage"]["log_path"]
        
        log_dir = os.path.dirname(self.log_path)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

    def _init_prometheus_instruments(self):
        try:
            self.prom_temp = Gauge('system_calculated_temperature_celsius', 'Calculated infrastructure core thermal mapping')
            self.prom_health = Gauge('system_health_index_percentage', 'Aggregated overall performance integrity register')
            self.prom_raw_net = Gauge('system_network_throughput_raw_bytes', 'Instant unfiltered network throughput link byte metric')
            self.prom_smooth_net = Gauge('system_network_throughput_smoothed_bytes', 'Exponential moving average filtered network metric')
            self.prom_regulation = Gauge('system_performance_regulation_active', 'Binary state flag representing active load constraints')
        except ValueError:
            pass 

    def _initialize_matrix_log(self):
        if not os.path.exists(self.log_path):
            with open(self.log_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "performance_regulation_active", "cpu_load_numerator", 
                    "smoothed_network_bytes", "smoothed_network_readable", "normalized_load_ratio", 
                    "calculated_temperature_celsius", "system_health_index_pct", "operational_status"
                ])

    async def watch_config_lifecycle_worker(self):
        while True:
            await asyncio.sleep(2.0)
            try:
                if os.path.exists(self.config_path):
                    current_mtime = os.path.getmtime(self.config_path)
                    if current_mtime > self.last_config_mtime:
                        print(f"[*] Configuration delta shift detected on disk. Executing live hot-reload sequence...")
                        self._apply_runtime_configurations(self._load_config())
                        self.last_config_mtime = current_mtime
                        print(f"[+] Hot-reload executed flawlessly. Active alpha smoothing weight is now: {self.ema_alpha}", flush=True)
            except Exception as e:
                print(f"[!] Config hot-watcher loop caught processing anomaly: {e}", file=sys.stderr, flush=True)

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
            
        # FIXED: Clamp against baseline raw bytes instead of hardcoded kilo-units to protect micro-precision
        denominator_clamped = max(1.0, min(smoothed_net_bytes, self.NET_MAX_CAPACITY))
        num = int(round(cpu_load * 100))
        # FIXED: Store true raw byte metrics without division to prevent idle clamping rounding down to 1
        den = int(round(denominator_clamped))
        return max(1, num), max(1, den)

    def process_telemetry_state(self, num: int, den: int, performance_regulation_active: bool) -> Dict[str, Any]:
        load_ratio = Fraction(num, den)
        x_ratio = load_ratio * Fraction(1, 4) if performance_regulation_active else load_ratio

        x_ratio = min(max(x_ratio, Fraction(0, 1)), Fraction(1, 1))
        calculated_temp_fraction = x_ratio * self.thermal_max_ceiling
        calculated_temp_float = float(calculated_temp_fraction)

        # FIXED: Tightly isolate input vector domain bounds into a hard [0.0, 1.0] mathematical space
        ratio_float = min(max(float(x_ratio), 0.0), 1.0)
        
        # FIXED: Implement absolute full precision of Euler's constant minus one (e - 1)
        EULER_MINUS_ONE = 1.718281828459045
        health_index = 100.0 - (50.0 * math.log1p(ratio_float * EULER_MINUS_ONE))
        health_index = min(max(health_index, 0.0), 100.0)

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

    def _convert_bytes_to_readable_string(self, raw_bytes: int) -> str:
        if raw_bytes < 1024:
            return f"{raw_bytes} B"
        elif raw_bytes < 1024 * 1024:
            return f"{raw_bytes / 1024:.2f} KB"
        else:
            return f"{raw_bytes / (1024 * 1024):.2f} MB"

    def write_matrix_csv_row(self, performance_regulation_active: bool, num: int, den: int, state: Dict[str, Any]):
        # FIXED: Generate re-scaled clean metrics representations for storage arrays
        readable_net = self._convert_bytes_to_readable_string(den)
        with open(self.log_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(), int(performance_regulation_active),
                num, den, readable_net, state["normalized_load_ratio"],
                state["calculated_temperature"], state["system_health_index"],
                state["operational_status"]
            ])
          
