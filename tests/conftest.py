"""Reloj adelantado para las pruebas: `RADAR_VIAL_DIAS_ADELANTE=40 python -m pytest -q`.

Las pruebas corren antes del radar en cada corrida programada, así que una prueba que depende de la fecha de hoy
puede frenar la recolección sin que nadie haya tocado el código. Pasó el 26-11-2026: tres pruebas usaban notas de
ejemplo publicadas el 18-11 y la cola descarta lo que tiene más de 7 días. Con esta variable, las pruebas corren
como si hoy fuera N días más tarde: sirve para encontrar esas fechas antes de que venzan. El workflow lo hace en
cada corrida (como aviso, sin frenar).

Se reemplazan `datetime.datetime` y `datetime.date` del módulo estándar antes de que se importe `radar_vial`.
"""
import datetime as _dt
import os

DIAS = int(os.environ.get("RADAR_VIAL_DIAS_ADELANTE") or 0)

if DIAS:
    _FechaHora, _Fecha = _dt.datetime, _dt.date
    _ADELANTE = _dt.timedelta(days=DIAS)

    class _MetaFechaHora(type(_FechaHora)):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _FechaHora)

    class _MetaFecha(type(_Fecha)):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _Fecha)

    class FechaHoraAdelantada(_FechaHora, metaclass=_MetaFechaHora):
        @classmethod
        def now(cls, tz=None):
            r = _FechaHora.now(tz) + _ADELANTE
            return cls(r.year, r.month, r.day, r.hour, r.minute, r.second, r.microsecond, tzinfo=r.tzinfo)

        @classmethod
        def today(cls):
            return cls.now()

        @classmethod
        def utcnow(cls):
            return cls.now(_dt.timezone.utc).replace(tzinfo=None)

    class FechaAdelantada(_Fecha, metaclass=_MetaFecha):
        @classmethod
        def today(cls):
            r = _Fecha.today() + _ADELANTE
            return cls(r.year, r.month, r.day)

    _dt.datetime, _dt.date = FechaHoraAdelantada, FechaAdelantada
