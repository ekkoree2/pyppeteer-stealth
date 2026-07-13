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
        self.contextsByFrame: dict[str, int] = {}
        self.frameUrls: dict[str, str] = {}

    async def _send(self, method: str, params: Optional[dict] = None) -> dict:
        return await self.connection.send(method, params, self.sessionId)

    def _onContextCreated(self, params: dict, sessionId: Optional[str]) -> None:
        if sessionId != self.sessionId:
            return
        context = params.get("context", {})
        aux = context.get("auxData", {}) or {}
        if aux.get("type") == "isolated":
            return
        frameId = aux.get("frameId")
        if frameId:
            self.contextsByFrame[frameId] = context.get("id")

    def _onContextDestroyed(self, params: dict, sessionId: Optional[str]) -> None:
        if sessionId != self.sessionId:
            return
        cid = params.get("id")
        for frameId, ctxId in list(self.contextsByFrame.items()):
            if ctxId == cid:
                del self.contextsByFrame[frameId]

    def _onContextsCleared(self, params: dict, sessionId: Optional[str]) -> None:
        if sessionId != self.sessionId:
            return
        self.contextsByFrame.clear()

    def _onFrameNavigated(self, params: dict, sessionId: Optional[str]) -> None:
        if sessionId != self.sessionId:
            return
        frame = params.get("frame", {})
        fid = frame.get("id")
        if fid:
            self.frameUrls[fid] = frame.get("url", "")

    def _onFrameDetached(self, params: dict, sessionId: Optional[str]) -> None:
        if sessionId != self.sessionId:
            return
        fid = params.get("frameId")
        if fid:
            self.frameUrls.pop(fid, None)
            self.contextsByFrame.pop(fid, None)

    async def initialize(self) -> None:
        self.connection.on("Runtime.executionContextCreated", self._onContextCreated)
        self.connection.on("Runtime.executionContextDestroyed", self._onContextDestroyed)
        self.connection.on("Runtime.executionContextsCleared", self._onContextsCleared)
        self.connection.on("Page.frameNavigated", self._onFrameNavigated)
        self.connection.on("Page.frameDetached", self._onFrameDetached)
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

    async def evaluateInContext(self, contextId: int, expression: str) -> Any:
        result = await self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": contextId,
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        return result.get("result", {}).get("value")

    def contextForFrameUrl(self, fragment: str) -> Optional[int]:
        for frameId, url in self.frameUrls.items():
            if fragment in url:
                ctxId = self.contextsByFrame.get(frameId)
                if ctxId is not None:
                    return ctxId
        return None

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

    async def _clickPoint(self, x: float, y: float, clickCount: int = 1) -> None:
        await self._send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        await self._send(
            "Input.dispatchMouseEvent",
            {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": clickCount},
        )
        await self._send(
            "Input.dispatchMouseEvent",
            {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": clickCount},
        )

    async def _typeText(self, text: str) -> None:
        for char in text:
            await self._send("Input.dispatchKeyEvent", {"type": "keyDown", "text": char})
            await self._send("Input.dispatchKeyEvent", {"type": "keyUp", "text": char})

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
        await self._clickPoint(x, y)

    async def type(
        self,
        selector: str,
        text: str,
        mode: Mode = Mode.CSS,
        timeoutMs: int = DEFAULT_TIMEOUT_MS,
    ) -> None:
        await self.click(selector, mode, timeoutMs)
        await self._typeText(text)
