import asyncio
import json
from typing import Any, Callable, Optional

import websockets
from websockets.client import WebSocketClientProtocol


class CdpConnection:
    def __init__(self, webSocketUrl: str) -> None:
        self.webSocketUrl: str = webSocketUrl
        self.socket: Optional[WebSocketClientProtocol] = None
        self.messageId: int = 0
        self.pendingCommands: dict[int, asyncio.Future] = {}
        self.eventListeners: dict[str, list[Callable]] = {}
        self._readerTask: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        self.socket = await websockets.connect(self.webSocketUrl, max_size=None)
        self._readerTask = asyncio.create_task(self._readLoop())

    async def _readLoop(self) -> None:
        async for raw in self.socket:
            message = json.loads(raw)
            self._dispatch(message)

    def _dispatch(self, message: dict) -> None:
        if "id" in message:
            future = self.pendingCommands.pop(message["id"], None)
            if future and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]["message"]))
                else:
                    future.set_result(message.get("result", {}))
        elif "method" in message:
            self._emitEvent(message)

    def _emitEvent(self, message: dict) -> None:
        method = message["method"]
        params = message.get("params", {})
        sessionId = message.get("sessionId")
        listeners = self.eventListeners.get(method, [])
        for callback in listeners:
            callback(params, sessionId)

    async def send(
        self,
        method: str,
        params: Optional[dict] = None,
        sessionId: Optional[str] = None,
    ) -> dict:
        self.messageId += 1
        currentId = self.messageId
        payload = {
            "id": currentId,
            "method": method,
            "params": params or {},
        }
        if sessionId:
            payload["sessionId"] = sessionId
        future = asyncio.get_event_loop().create_future()
        self.pendingCommands[currentId] = future
        await self.socket.send(json.dumps(payload))
        return await future

    def on(self, method: str, callback: Callable) -> None:
        self.eventListeners.setdefault(method, []).append(callback)

    async def close(self) -> None:
        if self._readerTask:
            self._readerTask.cancel()
        if self.socket:
            await self.socket.close()
