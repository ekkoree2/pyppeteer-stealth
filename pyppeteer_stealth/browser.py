from .connection import CdpConnection
from .page import Page


class Browser:
    def __init__(self, connection: CdpConnection) -> None:
        self.connection: CdpConnection = connection
        self.pages: list[Page] = []

    @classmethod
    async def create(cls, webSocketUrl: str) -> "Browser":
        connection = CdpConnection(webSocketUrl)
        await connection.connect()
        return cls(connection)

    async def newPage(self) -> Page:
        result = await self.connection.send(
            "Target.createTarget",
            {"url": "about:blank"},
        )
        targetId = result["targetId"]
        attachResult = await self.connection.send(
            "Target.attachToTarget",
            {"targetId": targetId, "flatten": True},
        )
        sessionId = attachResult["sessionId"]
        page = Page(self.connection, sessionId, targetId)
        await page.initialize()
        self.pages.append(page)
        return page
