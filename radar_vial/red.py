"""Pedidos HTTP con tiempo límite, reintentos y una pausa mínima entre pedidos a un mismo servidor."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config


class _Reintento(Retry):
    """Respeta el `Retry-After` de los servidores, pero con un tope: el 21-11-2026 una respuesta de espera larga
    dejó la recuperación histórica parada más de diez minutos."""

    TOPE_ESPERA = 60

    def get_retry_after(self, response):
        valor = super().get_retry_after(response)
        return None if valor is None else min(valor, self.TOPE_ESPERA)


class Red:
    """Sesión compartida por toda la corrida. Una fuente caída devuelve error, nunca cuelga la corrida."""

    def __init__(self, timeout: float | None = None, reintentos: int | None = None, pausa: float | None = None):
        rec = config.general()["recoleccion"]
        self.timeout = timeout if timeout is not None else rec["timeout_segundos"]
        self.pausa = pausa if pausa is not None else rec["pausa_segundos"]
        self.sesion = requests.Session()
        self.sesion.headers.update({
            "User-Agent": rec["user_agent"],
            "Accept-Language": "es-AR,es;q=0.9",
        })
        reintento = _Reintento(
            total=reintentos if reintentos is not None else rec["reintentos"],
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            respect_retry_after_header=True,
        )
        adaptador = HTTPAdapter(max_retries=reintento, pool_maxsize=8)
        self.sesion.mount("https://", adaptador)
        self.sesion.mount("http://", adaptador)
        self._ultimo: dict[str, float] = {}
        self._lock = threading.Lock()

    def _esperar_turno(self, url: str) -> None:
        host = urlparse(url).netloc
        with self._lock:
            espera = self._ultimo.get(host, 0) + self.pausa - time.monotonic()
            self._ultimo[host] = max(time.monotonic(), self._ultimo.get(host, 0) + self.pausa)
        if espera > 0:
            time.sleep(espera)

    def get(self, url: str, **kwargs) -> requests.Response:
        self._esperar_turno(url)
        kwargs.setdefault("timeout", self.timeout)
        return self.sesion.get(url, **kwargs)
