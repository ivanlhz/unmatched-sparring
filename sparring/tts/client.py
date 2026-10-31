from __future__ import annotations

import itertools
import json
import os
import queue
import socket
import threading
import time
from collections import deque
from typing import Callable

from . import lua
from .lua import is_sendable

SEND_PORT = 39999
LISTEN_PORT = 39998
MSG_CUSTOM = 2
MSG_EXECUTE = 3
ALLOWED_OUT = frozenset({MSG_CUSTOM, MSG_EXECUTE})
WSAEADDRINUSE = 10048     # Windows: no ephemeral port free (the previous connections are still in TIME_WAIT)
PORT_RETRIES = 20
PORT_RETRY_WAIT = 0.25

IN_NEW_GAME, IN_PRINT, IN_ERROR, IN_CUSTOM, IN_RETURN, IN_SAVED = 1, 2, 3, 4, 5, 6


class UnsafeMessage(Exception):
    pass


class TTSLuaError(Exception):
    pass


class Listener:
    """Servidor TCP donde TTS conecta de vuelta; un mensaje JSON por conexion."""

    def __init__(self, host: str = "127.0.0.1", port: int = LISTEN_PORT):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((host, port))
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]
        self.messages: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        self._srv.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(2.0)
                chunks = []
                try:
                    while (data := conn.recv(65536)):
                        chunks.append(data)
                except socket.timeout:
                    pass
            try:
                self.messages.put(json.loads(b"".join(chunks).decode("utf-8")))
            except ValueError:
                continue

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._srv.close()


class TTSClient:
    def __init__(self, host: str = "127.0.0.1", send_port: int = SEND_PORT, listen_port: int = LISTEN_PORT,
                 timeout: float = 5.0, late_grace: float = 8.0):
        self.host, self.send_port, self.listen_port, self.timeout = host, send_port, listen_port, timeout
        # a busy TTS (31/10: 5 s timeouts in pairs, the second call queued behind the first) still answers: after the
        # timeout the same request gets this long to reply before it is given up (a later call would find it busy too)
        self.late_grace = late_grace
        self.listener: Listener | None = None
        self._events: list[dict] = []        # botones pulsados mientras esperabamos una respuesta de Lua
        self._salt = int.from_bytes(os.urandom(3), "big") * 100000   # ids de esta ejecucion distintos de los de otras
        self._seq = itertools.count(1)   # rid = salt + n (< 1e15, exacto como float)
        self.reloads = 0                     # messageID 1 recibidos (TTS recargo la partida)
        self.foreign_errors: deque[str] = deque(maxlen=50)   # errores de Lua que no son de nuestra peticion
        self.graces = 0                      # llamadas que pasaron del plazo y siguieron esperando su respuesta
        self.stale_replies = 0               # respuestas descartadas por no corresponder a la peticion en curso
        self._calling = False                # dentro de call_lua: un clic que llega ahora trae una mesa anterior a su respuesta
        self.calls = 0                       # mensajes de Lua enviados (cada uno cuesta ~0.5 s en TTS real)
        self.call_seconds = 0.0              # tiempo total esperando respuesta
        self.trace: Callable[[str], None] | None = None     # con --timing: una linea por llamada

    def start_listening(self) -> Listener:
        if self.listener is None:
            self.listener = Listener(self.host, self.listen_port)
        return self.listener

    def close(self) -> None:
        if self.listener:
            self.listener.close()
            self.listener = None

    def send(self, payload: dict) -> None:
        if payload.get("messageID") not in ALLOWED_OUT:
            raise UnsafeMessage(f"messageID {payload.get('messageID')!r} no permitido (solo 2 y 3)")
        if payload["messageID"] == MSG_EXECUTE and not is_sendable(payload.get("script", "")):
            raise UnsafeMessage("solo se envia Lua generado por los constructores de sparring.tts.lua")
        data = json.dumps(payload).encode("utf-8")
        # cada mensaje abre una conexion corta: en Windows el pool de puertos efimeros se agota (WinError 10048)
        # mientras los anteriores siguen en TIME_WAIT; se reintenta un rato en vez de fallar (como FakeTTS.push)
        for attempt in range(PORT_RETRIES):
            try:
                with socket.create_connection((self.host, self.send_port), timeout=self.timeout) as s:
                    s.sendall(data)
                return
            except OSError as e:
                if getattr(e, "winerror", None) != WSAEADDRINUSE or attempt == PORT_RETRIES - 1:
                    raise
                time.sleep(PORT_RETRY_WAIT)

    def send_custom(self, data) -> None:
        self.send({"messageID": MSG_CUSTOM, "customMessage": data})

    def execute_lua(self, script: str, guid: str = "-1") -> None:
        self.send({"messageID": MSG_EXECUTE, "guid": guid, "script": script})

    def _absorb(self, msg: dict) -> bool:
        """Maneja lo que no es respuesta a una peticion (botones, recarga, errores ajenos). True si lo consumio.

        TTS no envia messageID 5: las respuestas llegan como messageID 4 con `sparring_reply` en el mensaje."""
        kind = msg.get("messageID")
        if kind == IN_CUSTOM:
            data = msg.get("customMessage")
            if isinstance(data, dict) and "sparring_reply" in data:
                return False
            if self._calling and isinstance(data, dict) and "snapshot" in data:
                data = {k: v for k, v in data.items() if k != "snapshot"}      # mesa anterior a la escritura en curso
            self._events.append(data)
        elif kind == IN_NEW_GAME:
            self.reloads += 1
        elif kind == IN_ERROR:
            # Un fallo de nuestros scripts vuelve como respuesta con `err` (van dentro de pcall); un
            # messageID 3 suelto es de otro script de la partida y no se le puede atribuir a esta llamada.
            self.foreign_errors.append(str(msg.get("error", msg)))
        return True                                   # prints (2), guardados (6), retornos (5): nada que hacer

    def take_reload(self) -> bool:
        """True (una vez) si TTS recargo la partida desde la ultima consulta."""
        seen, self.reloads = self.reloads > 0, 0
        return seen

    def call_lua(self, script: str, guid: str = "-1", timeout: float | None = None):
        """Ejecuta Lua y espera su respuesta, contando la llamada y su tiempo (ver `_call_lua`)."""
        started = time.monotonic()
        self._calling = True
        try:
            return self._call_lua(script, guid, timeout)
        finally:
            self._calling = False
            took = time.monotonic() - started
            self.calls += 1
            self.call_seconds += took
            if self.trace is not None:
                self.trace(f"{took * 1000:6.0f} ms  {script.split(chr(10), 1)[0].removeprefix('-- sparring:')}")

    def _call_lua(self, script: str, guid: str = "-1", timeout: float | None = None):
        """Ejecuta Lua y espera SU respuesta (messageID 4 con `sparring_reply` igual al id de la peticion).

        Antes de enviar se vacia la cola (respuestas tardias de llamadas que ya dieron timeout); una respuesta
        con otro id se descarta y un error de Lua solo es de esta llamada si vuelve con su id."""
        if not is_sendable(script):
            raise UnsafeMessage("solo se envia Lua generado por los constructores de sparring.tts.lua")
        listener = self.start_listening()
        while True:
            try:
                msg = listener.messages.get_nowait()
            except queue.Empty:
                break
            if not self._absorb(msg):
                self.stale_replies += 1
        rid = self._salt + next(self._seq)
        self.execute_lua(lua.request(script, rid), guid)
        deadline = time.monotonic() + (timeout or self.timeout)
        graced = self.late_grace <= 0
        while True:
            try:
                msg = listener.messages.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                if not graced:
                    graced, deadline = True, time.monotonic() + self.late_grace
                    self.graces += 1
                    continue
                raise TimeoutError("TTS no devolvio valor (esta ocupado, en pausa o recargando: revisa la ventana de TTS)") from None
            if self._absorb(msg):
                continue
            data = msg["customMessage"]
            reply = data["sparring_reply"]
            if isinstance(reply, bool) or not isinstance(reply, (int, float)) or int(reply) != rid:
                self.stale_replies += 1               # respuesta de una llamada anterior (timeout)
                continue
            if "err" in data:
                raise TTSLuaError(data["err"])
            value = data.get("value")
            try:
                return json.loads(value) if isinstance(value, str) else value
            except ValueError:
                return value

    def poll_events(self) -> list[dict]:
        """Pulsaciones de boton del humano (sendExternalMessage -> messageID 4), sin bloquear."""
        out, self._events = self._events, []
        if self.listener is None:
            return out
        while True:
            try:
                msg = self.listener.messages.get_nowait()
            except queue.Empty:
                break
            if not self._absorb(msg):
                self.stale_replies += 1               # respuesta tardia de una llamada que ya dio timeout: se descarta
        out.extend(self._events)
        self._events = []
        return out
