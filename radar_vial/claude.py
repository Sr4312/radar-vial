"""Llamadas a la API de Claude con salida estructurada, y registro de tokens y costo por corrida.

- Salida estructurada (`output_config.format` con JSON schema): la respuesta siempre es JSON válido según el
  schema. Es el equivalente de "tool use con schema estricto": en Sonnet 5.5 no se puede forzar una herramienta.
- El razonamiento no se puede apagar en estos modelos: se controla con `effort` (config.yaml, `esfuerzo`).
- El prompt de sistema va con `cache_control`: en una corrida se repite en cada llamada y se cobra a ~10%.
- Sonnet 5.5 lleva respaldo por rechazo (`fallbacks: "default"`): si la API rechaza la nota por sus filtros de
  seguridad, la reintenta con otro modelo en la misma llamada.
- Nunca se manda `temperature` (estos modelos la rechazan).
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config

ARCHIVO_COSTOS = config.DIR_DATA / "costos.jsonl"
BETA_RESPALDO = "server-side-fallback-2026-07-01"


class ErrorClaude(Exception):
    """La llamada no devolvió un JSON utilizable (rechazo, respuesta cortada o error de la API)."""


@dataclass
class Uso:
    llamadas: int = 0
    entrada: int = 0
    salida: int = 0
    cache_lectura: int = 0
    cache_escritura: int = 0
    rechazos: int = 0
    errores: int = 0

    def costo(self, precios: dict) -> float:
        return (self.entrada * precios["entrada"] + self.salida * precios["salida"]
                + self.cache_lectura * precios["cache_lectura"]
                + self.cache_escritura * precios["cache_escritura"]) / 1_000_000


@dataclass
class RegistroCostos:
    """Acumula el uso por (etapa, modelo) durante una corrida y lo guarda en data/costos.jsonl."""

    comando: str
    usos: dict[tuple[str, str], Uso] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def sumar(self, etapa: str, modelo: str, usage=None, rechazo=False, error=False) -> None:
        with self._lock:
            u = self.usos.setdefault((etapa, modelo), Uso())
            u.llamadas += 1
            u.rechazos += int(rechazo)
            u.errores += int(error)
            if usage is not None:
                u.entrada += getattr(usage, "input_tokens", 0) or 0
                u.salida += getattr(usage, "output_tokens", 0) or 0
                u.cache_lectura += getattr(usage, "cache_read_input_tokens", 0) or 0
                u.cache_escritura += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def resumen(self) -> dict:
        precios = config.general()["precios"]
        etapas = []
        total = 0.0
        for (etapa, modelo), u in sorted(self.usos.items()):
            costo = u.costo(precios[modelo]) if modelo in precios else 0.0
            total += costo
            etapas.append({"etapa": etapa, "modelo": modelo, "llamadas": u.llamadas, "tokens_entrada": u.entrada,
                           "tokens_salida": u.salida, "tokens_cache_lectura": u.cache_lectura,
                           "tokens_cache_escritura": u.cache_escritura, "rechazos": u.rechazos,
                           "errores": u.errores, "costo_usd": round(costo, 4)})
        return {"etapas": etapas, "costo_total_usd": round(total, 4)}

    def guardar(self, extra: dict | None = None) -> dict:
        registro = {"fecha": datetime.now(timezone.utc).isoformat(), "comando": self.comando, **self.resumen(),
                    **(extra or {})}
        ARCHIVO_COSTOS.parent.mkdir(parents=True, exist_ok=True)
        with open(ARCHIVO_COSTOS, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        return registro


class Claude:
    """Cliente mínimo: una llamada = un mensaje de usuario y una respuesta JSON según el schema."""

    def __init__(self, registro: RegistroCostos, cliente=None):
        if cliente is None:
            import anthropic

            if not config.secreto("ANTHROPIC_API_KEY"):
                raise ErrorClaude("Falta ANTHROPIC_API_KEY (en .env o como variable de entorno).")
            cliente = anthropic.Anthropic(max_retries=3, timeout=180.0)
        self.cliente = cliente
        self.registro = registro
        self.con_respaldo = set(config.general().get("respaldo_por_rechazo") or [])

    def json(self, etapa: str, modelo: str, sistema: str, mensaje: str, schema: dict,
             esfuerzo: str = "low", max_tokens: int = 16000) -> dict:
        """Devuelve el JSON de la respuesta. Lanza ErrorClaude si no hay un JSON utilizable."""
        import anthropic

        params = dict(
            model=modelo,
            max_tokens=max_tokens,  # incluye el razonamiento: si queda corto, la respuesta se corta
            system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": mensaje}],
            output_config={"effort": esfuerzo, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if modelo in self.con_respaldo:
                resp = self.cliente.beta.messages.create(betas=[BETA_RESPALDO], fallbacks="default", **params)
            else:
                resp = self.cliente.messages.create(**params)
        except anthropic.APIStatusError as exc:
            self.registro.sumar(etapa, modelo, error=True)
            raise ErrorClaude(f"la API respondió {exc.status_code}: {getattr(exc, 'message', exc)}") from exc
        except anthropic.APIConnectionError as exc:
            self.registro.sumar(etapa, modelo, error=True)
            raise ErrorClaude(f"sin conexión con la API: {exc}") from exc

        if resp.stop_reason == "refusal":
            self.registro.sumar(etapa, modelo, resp.usage, rechazo=True)
            categoria = getattr(getattr(resp, "stop_details", None), "category", None)
            raise ErrorClaude(f"el modelo rechazó el pedido (categoría: {categoria})")
        self.registro.sumar(etapa, modelo, resp.usage)
        if resp.stop_reason == "max_tokens":
            raise ErrorClaude(f"respuesta cortada por max_tokens ({resp.usage.output_tokens} tokens de salida): subir max_tokens")
        texto = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if not texto:
            raise ErrorClaude("la respuesta no trajo texto")
        try:
            return json.loads(texto)
        except json.JSONDecodeError as exc:
            raise ErrorClaude(f"la respuesta no es JSON válido: {exc}") from exc
