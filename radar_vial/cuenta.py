"""Claude con la cuenta conectada en Claude Code (`claude -p`), en lugar de la API.

Misma interfaz que `claude.Claude.json`, para usar el filtro, la extracción y el desempate sin gastar créditos de
la API: cada llamada corre `claude -p` con salida estructurada (`--json-schema`). Se usa para la recuperación
histórica, que corre en esta computadora; la corrida diaria de GitHub Actions sigue con la API.

Cuidados:
- Sin `ANTHROPIC_API_KEY` en el entorno del proceso: si la encuentra, Claude Code la usa y factura la API. Además
  se comprueba en cada llamada que la autenticación no sea por clave (`apiKeySource`); si lo es, se corta todo.
- Sin herramientas, sin plugins, sin servidores MCP, sin configuración del usuario y en una carpeta vacía: el
  modelo recibe solo la consigna y la nota (menos tokens y nada de contexto ajeno).
- `--no-session-persistence`: las sesiones no se guardan, así el texto de las notas (con nombres) no queda en el
  historial de Claude Code.
- Cuando la cuenta llega a su límite de uso, se levanta `LimiteCuenta` y la corrida guarda y se frena: se retoma
  con el mismo comando después de la hora de reinicio.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from collections import Counter
from datetime import datetime, timezone

from . import config
from .claude import ErrorClaude

ARCHIVO_USO = config.DIR_DATA / "historico" / "uso_cuenta.jsonl"


class LimiteCuenta(Exception):
    """La cuenta llegó a su límite de uso. No hereda de ErrorClaude: tiene que frenar la corrida, no saltear una nota."""

    def __init__(self, mensaje: str, reinicio: datetime | None = None):
        super().__init__(mensaje)
        self.reinicio = reinicio


class AutenticacionNoEsCuenta(Exception):
    """Claude Code se autenticó con una clave de API: seguir facturaría la API."""


class ClaudeCuenta:
    def __init__(self, comando: str = "historico", ejecutable: str | None = None, ejecutar=subprocess.run):
        self.ejecutable = ejecutable or shutil.which("claude")
        if not self.ejecutable:
            raise ErrorClaude("No se encontró Claude Code (`claude`) en esta computadora.")
        self.comando = comando
        self.ejecutar = ejecutar
        self.entorno = {k: v for k, v in os.environ.items()
                        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
        self.carpeta = config.DIR_CACHE / "cuenta_vacia"     # sin CLAUDE.md ni configuración de proyecto
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.limite = threading.Event()
        self.reinicio: datetime | None = None
        self.estado_limite = None                           # allowed | allowed_warning | rejected
        self.uso: Counter = Counter()
        self._lock = threading.Lock()

    def _argumentos(self, modelo: str, sistema: str, schema: dict, esfuerzo: str) -> list[str]:
        return [self.ejecutable, "-p", "--model", modelo, "--effort", esfuerzo, "--tools", "",
                "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
                "--system-prompt", sistema, "--json-schema", json.dumps(schema, ensure_ascii=False),
                "--output-format", "stream-json", "--verbose"]

    def json(self, etapa: str, modelo: str, sistema: str, mensaje: str, schema: dict,
             esfuerzo: str = "low", max_tokens: int = 16000) -> dict:   # noqa: ARG002 - max_tokens no aplica
        if self.limite.is_set():
            raise LimiteCuenta("La cuenta llegó a su límite de uso.", self.reinicio)
        try:
            r = self.ejecutar(self._argumentos(modelo, sistema, schema, esfuerzo), input=mensaje, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", env=self.entorno, cwd=self.carpeta,
                              timeout=900)
        except subprocess.TimeoutExpired as exc:
            raise ErrorClaude("Claude Code no respondió en 15 minutos") from exc
        resultado, info_limite, fuente_clave = None, None, None
        for linea in (r.stdout or "").splitlines():
            try:
                d = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "system" and d.get("subtype") == "init":
                fuente_clave = d.get("apiKeySource")
            elif d.get("type") == "rate_limit_event":
                info_limite = d.get("rate_limit_info") or {}
            elif d.get("type") == "result":
                resultado = d
        if fuente_clave not in (None, "none"):
            # cualquier otra fuente es una clave de API: se corta para no facturar la API
            raise AutenticacionNoEsCuenta(f"Claude Code usa una clave de API ({fuente_clave}), no la cuenta.")
        if info_limite:
            self.estado_limite = info_limite.get("status")
            if info_limite.get("resetsAt"):
                self.reinicio = datetime.fromtimestamp(info_limite["resetsAt"], tz=timezone.utc)
        texto_error = " ".join(str(x) for x in ((resultado or {}).get("result"), r.stderr) if x)
        if self.estado_limite == "rejected" or ("limit" in texto_error.lower() and (resultado or {}).get("is_error")):
            self.limite.set()
            raise LimiteCuenta("La cuenta llegó a su límite de uso.", self.reinicio)
        if resultado is None:
            raise ErrorClaude(f"Claude Code terminó sin respuesta (código {r.returncode}): {(r.stderr or '')[:200]}")
        self._sumar(etapa, modelo, resultado)
        if resultado.get("is_error"):
            raise ErrorClaude(f"Claude Code respondió con error: {str(resultado.get('result'))[:200]}")
        datos = resultado.get("structured_output")
        if not isinstance(datos, dict):
            try:
                datos = json.loads(resultado.get("result") or "")
            except json.JSONDecodeError as exc:
                raise ErrorClaude("la respuesta no es JSON válido") from exc
        return datos

    def _sumar(self, etapa: str, modelo: str, resultado: dict) -> None:
        u = resultado.get("usage") or {}
        with self._lock:
            clave = f"{etapa}|{modelo}"
            self.uso[clave + "|llamadas"] += 1
            for campo in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                self.uso[f"{clave}|{campo}"] += u.get(campo) or 0

    def guardar_uso(self, extra: dict | None = None) -> dict:
        """Tokens usados de la cuenta (no es costo en dólares: se descuenta del plan)."""
        registro = {"fecha": datetime.now(timezone.utc).isoformat(), "comando": self.comando, "fuente": "cuenta",
                    "uso": dict(self.uso), "estado_limite": self.estado_limite,
                    "reinicio": self.reinicio.isoformat() if self.reinicio else None, **(extra or {})}
        ARCHIVO_USO.parent.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVO_USO, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        return registro
