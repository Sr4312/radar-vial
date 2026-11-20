"""Normalización geográfica con un Georef simulado (sin red)."""
from radar_vial.geo import Georef, normalizar_ficha


def _loc(id_, nombre, depto_id, depto, prov_id, prov, lat=-30.0, lon=-60.0):
    return {"id": id_, "nombre": nombre, "departamento": {"id": depto_id, "nombre": depto},
            "provincia": {"id": prov_id, "nombre": prov}, "centroide": {"lat": lat, "lon": lon}}


LOCALIDADES = [
    _loc("50112060", "Santa Rosa", "50112", "Santa Rosa", "50", "Mendoza", -33.25, -68.15),
    _loc("42021020", "Santa Rosa", "42021", "Capital", "42", "La Pampa", -36.62, -64.29),
    _loc("10049030", "San Fernando del Valle de Catamarca", "10049", "Capital", "10", "Catamarca", -28.47, -65.78),
    _loc("18112040", "Mocoretá", "18112", "Monte Caseros", "18", "Corrientes", -30.62, -57.98),
    _loc("1401401003", "Córdoba", "14014", "Capital", "14", "Córdoba", -31.41, -64.18),
    _loc("14014010", "Córdoba", "14014", "Capital", "14", "Córdoba", -31.42, -64.19),
]


class GeorefFalso(Georef):
    def __init__(self, tmp_path):
        super().__init__(red=None, archivo=tmp_path / "georef.json")
        self.pedidos = []

    def _consultar(self, recurso, **params):
        clave = recurso + str(sorted(params.items()))
        self.pedidos.append(clave)
        nombre = params.get("nombre", "").lower()
        if recurso == "localidades":
            from radar_vial.texto import normalizar

            return [x for x in LOCALIDADES if normalizar(nombre) in normalizar(x["nombre"])
                    and (not params.get("provincia") or x["provincia"]["id"] == params["provincia"])]
        if recurso == "departamentos":
            return [{"id": "50049", "nombre": "Guaymallén", "centroide": {"lat": -32.89, "lon": -68.73}}] if "guaymall" in nombre else []
        if recurso == "provincias":
            return [{"id": params["id"], "nombre": "X", "centroide": {"lat": -82.5, "lon": -50.7}}]
        return []


def test_misma_localidad_en_dos_provincias_se_resuelve_por_la_provincia(tmp_path):
    g = GeorefFalso(tmp_path)
    mza = normalizar_ficha({"provincia_id": "50", "localidad": "Santa Rosa"}, g)
    lp = normalizar_ficha({"provincia_id": "42", "localidad": "Santa Rosa"}, g)
    assert mza["localidad_id"] == "50112060" and lp["localidad_id"] == "42021020"
    assert mza["nivel"] == "localidad" and mza["lat"] == -33.25


def test_la_capital_se_traduce_a_la_capital_de_la_provincia(tmp_path):
    g = GeorefFalso(tmp_path)
    geo = normalizar_ficha({"provincia_id": "10", "localidad": "la capital catamarqueña"}, g)
    assert geo["localidad"] == "San Fernando del Valle de Catamarca"


def test_prefiere_la_localidad_y_no_el_barrio(tmp_path):
    g = GeorefFalso(tmp_path)
    assert normalizar_ficha({"provincia_id": "14", "localidad": "ciudad de Córdoba"}, g)["localidad_id"] == "14014010"


def test_nombre_de_departamento_y_provincia_sola(tmp_path):
    g = GeorefFalso(tmp_path)
    depto = normalizar_ficha({"provincia_id": "50", "localidad": "Guaymallén"}, g)
    assert depto["nivel"] == "departamento" and depto["departamento"] == "Guaymallén"
    solo = normalizar_ficha({"provincia_id": "50", "localidad": None}, g)
    assert solo["nivel"] == "provincia" and solo["localidad_id"] is None


def test_tierra_del_fuego_usa_su_centro_y_no_el_de_la_antartida(tmp_path):
    g = GeorefFalso(tmp_path)
    geo = normalizar_ficha({"provincia_id": "94", "localidad": None}, g)
    assert geo["lat"] == -54.3 and geo["lon"] == -67.7


def test_provincia_inferida_solo_si_no_hay_dudas(tmp_path):
    g = GeorefFalso(tmp_path)
    unica = normalizar_ficha({"provincia_id": None, "localidad": "Mocoretá"}, g)
    assert unica["provincia_id"] == "18" and unica["provincia_inferida"] is True
    ambigua = normalizar_ficha({"provincia_id": None, "localidad": "Santa Rosa"}, g)
    assert ambigua["provincia_id"] is None and ambigua["nivel"] == "ninguno"
    con_medio = normalizar_ficha({"provincia_id": None, "localidad": "Santa Rosa"}, g, provincia_medio="42")
    assert con_medio["provincia_id"] == "42"


def test_cache_de_respuestas(tmp_path):
    g = Georef(red=None, archivo=tmp_path / "georef.json")
    g._cache["localidades?campos=x&nombre=y"] = [{"id": "1"}]

    class RedQueFalla:
        def get(self, *a, **kw):
            raise AssertionError("no debería salir a la red")

    g.red = RedQueFalla()
    assert g._consultar("localidades", nombre="y", campos="x") == [{"id": "1"}]
    g.guardar()
    assert Georef(red=None, archivo=tmp_path / "georef.json")._cache


def test_provincia_por_pistas_del_medio_o_de_la_busqueda(tmp_path):
    g = GeorefFalso(tmp_path)
    sin_nada = {"provincia_id": None, "localidad": None}
    assert normalizar_ficha(sin_nada, g)["nivel"] == "ninguno"
    medio = normalizar_ficha(sin_nada, g, provincia_medio="70")
    assert medio["provincia_id"] == "70" and medio["provincia_inferida"] and medio["inferida_de"] == "medio"
    busqueda = normalizar_ficha(sin_nada, g, provincias_busqueda=["18"])
    assert busqueda["provincia_id"] == "18" and busqueda["inferida_de"] == "busqueda"
    # si el medio y las búsquedas no coinciden, o hay varias búsquedas, no se adivina
    assert normalizar_ficha(sin_nada, g, provincia_medio="70", provincias_busqueda=["18"])["nivel"] == "ninguno"
    assert normalizar_ficha(sin_nada, g, provincias_busqueda=["18", "54"])["nivel"] == "ninguno"
