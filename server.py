import json
import asyncio
from typing import Dict, Any
from aiohttp import web, WSMsgType

class TelemetryNetworkServer:
    def __init__(self, engine):
        self.engine = engine

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        origin = request.headers.get('Origin', '')
        
        if "*" not in self.engine.cors_origins and origin not in self.engine.cors_origins:
            return web.Response(text="CORS Origin Policy Violation", status=403)
            
        await ws.prepare(request)
        self.engine.connected_clients.add(ws)
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT and msg.data == 'close':
                    await ws.close()
                elif msg.type == WSMsgType.ERROR:
                    print(f'[-] Infrastructure connection exception: {ws.exception()}', flush=True)
        finally:
            self.engine.connected_clients.remove(ws)
        return ws

    async def handle_http_cors_preflight(self, request: web.Request) -> web.Response:
        origin = request.headers.get('Origin', '')
        headers = {
            'Access-Control-Allow-Origin': origin if origin in self.engine.cors_origins or "*" in self.engine.cors_origins else '',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization',
            'Access-Control-Max-Age': '86400'
        }
        return web.Response(status=204, headers=headers)

    async def broadcast_telemetry(self, data: Dict[str, Any]):
        if not self.engine.connected_clients: 
            return
        payload = json.dumps(data)
        await asyncio.gather(
            *[c.send_str(payload) for c in self.engine.connected_clients], 
            return_exceptions=True
        )
      
