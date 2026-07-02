import asyncio
import base64
from typing import Any, Optional

from .connection import CdpConnection
from .constants import STEALTH_SCRIPT


class Page:
    def __init__(self, connection: CdpConnection, sessionId: str, targetId: str) -> None:
        self.connection: CdpConnection = connection
        self.sessionId: str = sessionId
        self.targetId: str = targetId

    async def _send(self, method: str, params: Optional[dict] = None) -> dict:
        return await self.connection.send(method, params, self.sessionId)

    async def initialize(self) -> None:
        await self._send("Page.enable")
        await self._send("Runtime.enable")
        await self._send("Network.enable")

    async def applyStealth(self) -> None:
        await self._send(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": STEALTH_SCRIPT},
        )

    async def goto(self, url: str) -> None:
        loadComplete = asyncio.get_event_loop().create_future()

        def onLoad(params: dict, sessionId: Optional[str]) -> None:
            if sessionId == self.sessionId and not loadComplete.done():
                loadComplete.set_result(True)

        self.connection.on("Page.loadEventFired", onLoad)
        await self._send("Page.navigate", {"url": url})
        await loadComplete

    async def evaluate(self, expression: str) -> Any:
        result = await self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        return result.get("result", {}).get("value")

    async def content(self) -> str:
        return await self.evaluate("document.documentElement.outerHTML")

    async def screenshot(self, path: str) -> None:
        result = await self._send("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as fileHandle:
            fileHandle.write(base64.b64decode(result["data"]))
