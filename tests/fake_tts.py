"""Fake TTS server: receives the client's messages on an ephemeral port and can answer the listener."""
from __future__ import annotations

import json
import re
import socket
import threading
import time


class FakeTTS:
    def __init__(self, reply_port: int | None = None, return_value=None):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.received: list[dict] = []
        self.reply_port = reply_port
        self.return_value = return_value
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _loop(self):
        self.srv.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
            msg = json.loads(data.decode("utf-8"))
            self.received.append(msg)
            if self.reply_port and msg.get("messageID") == 3:
                try:
                    value = self.return_value(msg) if callable(self.return_value) else self.return_value
                except Exception as exc:      # a gap in a fake table fails the call, never kills the server thread
                    value = {"__error__": f"FakeTTS: {type(exc).__name__}: {exc}"}
                rid = re.search(r"local __rid = (\d+)", msg.get("script", ""))
                if rid:     # like the real TTS: no messageID 5; the reply comes back through sendExternalMessage (4)
                    reply = {"sparring_reply": float(rid.group(1))}
                    if isinstance(value, dict) and "__error__" in value:
                        reply["err"] = value["__error__"]
                    else:
                        reply["value"] = value if isinstance(value, str) else json.dumps(value)
                    self.push({"messageID": 4, "customMessage": reply})
                elif isinstance(value, dict) and "__error__" in value:
                    self.push({"messageID": 3, "error": value["__error__"]})

    @property
    def lua_messages(self) -> int:
        """Lua messages (messageID 3) received: what they would cost in real TTS (~0.5 s each)."""
        return sum(1 for m in self.received if m.get("messageID") == 3)

    def push(self, payload: dict, port: int | None = None):
        """A full suite opens thousands of short connections: on Windows the pool of ephemeral ports runs out
        (WinError 10048) while the previous ones are still in TIME_WAIT; it retries for a while instead of failing."""
        data = json.dumps(payload).encode("utf-8")
        for attempt in range(20):
            try:
                with socket.create_connection(("127.0.0.1", port or self.reply_port), timeout=2) as s:
                    s.sendall(data)
                return
            except OSError as e:
                if getattr(e, "winerror", None) != 10048 or attempt == 19:
                    raise
                time.sleep(0.25)

    def close(self):
        self._stop.set()
        self._t.join(timeout=2)
        self.srv.close()
