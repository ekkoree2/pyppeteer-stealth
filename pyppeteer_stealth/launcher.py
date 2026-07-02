import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from typing import Optional

from .constants import CHROME_PATHS, STEALTH_FLAGS


class ChromeLauncher:
    def __init__(self, port: int = 9222, isHeadless: bool = False) -> None:
        self.port: int = port
        self.isHeadless: bool = isHeadless
        self.process: Optional[subprocess.Popen] = None
        self.userDataDir: str = tempfile.mkdtemp(prefix="chrome_prof_")

    def _findBinary(self) -> str:
        for path in CHROME_PATHS:
            if shutil.which(path) or os.path.exists(path):
                return path
        raise RuntimeError("chrome binary not found")

    def launch(self) -> str:
        binary = self._findBinary()
        args = [
            binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.userDataDir}",
            *STEALTH_FLAGS,
        ]
        if self.isHeadless:
            args.append("--headless=new")
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self._getWebSocketUrl()

    def _getWebSocketUrl(self) -> str:
        endpoint = f"http://127.0.0.1:{self.port}/json/version"
        for _ in range(50):
            try:
                with urllib.request.urlopen(endpoint) as response:
                    data = json.loads(response.read())
                    return data["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("chrome did not expose debug endpoint")

    def kill(self) -> None:
        if self.process:
            self.process.terminate()
            self.process.wait()
