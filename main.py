#!/usr/bin/env python3
import sys
import asyncio
from prometheus_client import start_http_server
from aiohttp import web

from engine import EnterpriseTelemetryDaemon
from server import TelemetryNetworkServer

async def telemetry_orchestration_loop(engine, server):
    print(f"[*] Activating Scraped Prometheus Endpoint Instance on Port {engine.prom_port}...")
    start_http_server(engine.prom_port)
    
    print("[*] Engine System Processing Active. Synthesizing Metric Structures...")
    while True:
        smoothed_bytes = engine.sample_network_throughput()
        num, den = engine.calculate_resource_fractions(smoothed_bytes)
        
        performance_regulation_active = engine.raw_net_throughput > engine.NET_SATURATION_THRESHOLD
        state = engine.process_telemetry_state(num, den, performance_regulation_active)
        
        # Populate live enterprise monitoring instances
        engine.prom_temp.set(state["calculated_temperature"])
        engine.prom_health.set(state["system_health_index"])
        engine.prom_raw_net.set(engine.raw_net_throughput)
        engine.prom_smooth_net.set(smoothed_bytes)
        engine.prom_regulation.set(int(performance_regulation_active))
        
        # Commit to disk logs
        engine.write_matrix_csv_row(performance_regulation_active, num, den, state)
        
        # Dispatch to active dashboard relays
        await server.broadcast_telemetry({
            "metrics": state,
            "raw_fractions": {"numerator": num, "denominator": den, "raw_bytes_throughput": engine.raw_net_throughput}
        })
        
        await asyncio.sleep(engine.sample_rate)

async def main():
    engine = EnterpriseTelemetryDaemon()
    server = TelemetryNetworkServer(engine)
    
    app = web.Application()
    app.router.add_route('OPTIONS', '/ws', server.handle_http_cors_preflight)
    app.router.add_get('/ws', server.handle_websocket)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, engine.host, engine.port)
    await site.start()
    print(f"[*] Enterprise Network Gateway running on ws://{engine.host}:{engine.port}/ws")

    tasks = [
        asyncio.create_task(engine.watch_config_lifecycle_worker()),
        asyncio.create_task(telemetry_orchestration_loop(engine, server))
    ]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[-] Enterprise System Core Shutdown Signalled. Terminal Pipeline Purged Cleanly.")
        sys.exit(0)
      
