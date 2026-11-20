"""Registro de la corrida diaria (sin red ni API)."""
from radar_vial import estado


def test_una_corrida_por_dia(tmp_path):
    archivo = tmp_path / "estado.json"
    assert estado.corrio_hoy(archivo) is False
    estado.marcar_diario({"recolectadas": 10, "eventos": 3, "otra_cosa": "x"}, publicado=True, archivo=archivo)
    assert estado.corrio_hoy(archivo) is True
    datos = estado.cargar(archivo)
    assert datos["resumen"]["eventos"] == 3 and "otra_cosa" not in datos["resumen"]
    datos["ultimo_diario"] = "2026-01-01"
    archivo.write_text(__import__("json").dumps(datos), encoding="utf-8")
    assert estado.corrio_hoy(archivo) is False
