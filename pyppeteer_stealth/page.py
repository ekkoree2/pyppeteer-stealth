import asyncio
import base64
from typing import Any, Optional

from .connection import CdpConnection
from .constants import DEFAULT_TIMEOUT_MS, STEALTH_SCRIPT
from .mode import Mode


class NavigationError(RuntimeError):
    def __init__(self, url: str, errorText: str) -> None:
        self.url: str = url
        self.errorText: str = errorText
        super().__init__(f"navigation to {url} failed: {errorText}")


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
        await self._send("DOM.enable")

    async def applyStealth(self) -> None:
        await self._send(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": STEALTH_SCRIPT},
        )

    def _loadFuture(self, timeoutMs: int = DEFAULT_TIMEOUT_MS) -> asyncio.Future:
        loadComplete = asyncio.get_event_loop().create_future()

        def onLoad(params: dict, sessionId: Optional[str]) -> None:
            if sessionId == self.sessionId and not loadComplete.done():
                loadComplete.set_result(True)

        self.connection.on("Page.loadEventFired", onLoad)
        return loadComplete

    async def _waitForLoad(self, timeoutMs: int = DEFAULT_TIMEOUT_MS) -> None:
        await asyncio.wait_for(self._loadFuture(timeoutMs), timeoutMs / 1000)

    async def evaluateOnNewDocument(self, source: str) -> str:
        result = await self._send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": source}
        )
        return result.get("identifier")

    async def removeInitScript(self, identifier: str) -> None:
        await self._send(
            "Page.removeScriptToEvaluateOnNewDocument", {"identifier": identifier}
        )

    async def waitForNavigation(self, timeoutMs: int = DEFAULT_TIMEOUT_MS) -> None:
        await self._waitForLoad(timeoutMs)

    async def reload(self, timeoutMs: int = DEFAULT_TIMEOUT_MS) -> None:
        loadComplete = self._loadFuture(timeoutMs)
        await self._send("Page.reload")
        await asyncio.wait_for(loadComplete, timeoutMs / 1000)

    async def goto(self, url: str) -> None:
        loadComplete = self._loadFuture()
        result = await self._send("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise NavigationError(url, result["errorText"])
        await asyncio.wait_for(loadComplete, DEFAULT_TIMEOUT_MS / 1000)
        result = await self._send("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise NavigationError(url, result["errorText"])
        await self._waitForLoad()

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

    async def waitForFunction(
        self,
        expression: str,
        timeoutMs: int = DEFAULT_TIMEOUT_MS,
        pollMs: int = 500,
    ) -> Any:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeoutMs / 1000
        while True:
            value = await self.evaluate(expression)
            if value:
                return value
            if loop.time() >= deadline:
                raise asyncio.TimeoutError(
                    f"waitForFunction timed out after {timeoutMs}ms: {expression}"
                )
            await asyncio.sleep(pollMs / 1000)

    async def content(self) -> str:
        return await self.evaluate("document.documentElement.outerHTML")

    async def screenshot(self, path: str) -> None:
        result = await self._send("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as fileHandle:
            fileHandle.write(base64.b64decode(result["data"]))

    def _buildExpression(self, selector: str, mode: Mode) -> str:
        if mode is Mode.XPATH:
            return (
                f"document.evaluate({selector!r}, document, null, "
                "XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue"
            )
        return f"document.querySelector({selector!r})"

    async def _locate(self, selector: str, mode: Mode, timeoutMs: int) -> str:
        expression = self._buildExpression(selector, mode)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeoutMs / 1000
        while True:
            result = await self._send("Runtime.evaluate", {"expression": expression})
            objectId = result.get("result", {}).get("objectId")
            if objectId:
                return objectId
            if loop.time() >= deadline:
                raise RuntimeError(f"element not found: {selector}")
            await asyncio.sleep(0.1)

    async def click(
        self,
        selector: str,
        mode: Mode = Mode.CSS,
        timeoutMs: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        objectId = await self._locate(selector, mode, timeoutMs)
        box = await self._send("DOM.getBoxModel", {"objectId": objectId})
        quad = box["model"]["content"]
        x = (quad[0] + quad[4]) / 2
        y = (quad[1] + quad[5]) / 2
        await self._send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        await self._send(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
        )
        await self._send(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
        )

    async def type(
        self,
        selector: str,
        text: str,
        mode: Mode = Mode.CSS,
        timeoutMs: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        await self.click(selector, mode, timeoutMs)
        for char in text:
            await self._send("Input.dispatchKeyEvent", {"type": "keyDown", "text": char})
            await self._send("Input.dispatchKeyEvent", {"type": "keyUp", "text": char})
