"""Controles de privacidad de las fichas (sin red ni claves)."""
from radar_vial.privacidad import limpiar_ficha, nombres_en_texto, quitar_edades, resumen_generico

TEXTO = (
    "La víctima fue identificada como Juan Carlos Pérez, de 34 años, vecino de Banda del Río Salí. "
    "En el auto viajaba también María Rosario Gómez (29), que fue trasladada al Hospital Padilla. "
    "El siniestro ocurrió en la Ruta Nacional 9, a la altura de San Juan y Villa Carmela."
)


def _ficha(**kw):
    f = {"tipo_siniestro": "choque_frontal", "via": "RN 9", "localidad": "Banda del Río Salí", "provincia": "Tucumán",
         "fallecidos": 1, "heridos_graves": None, "heridos_leves": 1, "heridos_sin_detalle": None,
         "resumen": "Choque frontal en la RN 9, en Banda del Río Salí: una persona murió y otra resultó herida."}
    f.update(kw)
    return f


def test_detecta_nombres_con_los_patrones_de_la_prensa():
    nombres = nombres_en_texto(TEXTO)
    assert "Juan Carlos Pérez" in nombres
    assert "María Rosario Gómez" in nombres
    # lugares con mayúscula no son personas
    assert not any("San Juan" == n or "Ruta Nacional" in n for n in nombres)


def test_resumen_con_nombre_se_reemplaza_por_uno_generico():
    nombres = nombres_en_texto(TEXTO)
    f = limpiar_ficha(_ficha(resumen="Murió Juan Pérez en un choque frontal en la RN 9."), nombres)
    assert "Pérez" not in f["resumen"]
    assert f["resumen"].startswith("Choque frontal en RN 9, Banda del Río Salí, Tucumán")
    assert "resumen reemplazado: tenía un nombre" in f["privacidad"]


def test_resumen_neutro_no_se_toca():
    nombres = nombres_en_texto(TEXTO)
    original = _ficha()["resumen"]
    f = limpiar_ficha(_ficha(), nombres)
    assert f["resumen"] == original and f["privacidad"] == []


def test_edades_exactas_se_quitan():
    assert quitar_edades("Murió un motociclista de 23 años en la RP 5.") == "Murió un motociclista en la RP 5."
    assert quitar_edades("Un hombre (45) resultó herido.") == "Un hombre resultó herido."
    f = limpiar_ficha(_ficha(resumen="Un joven de 19 años murió tras chocar en la RN 9."), set())
    assert "19" not in f["resumen"] and "edad quitada del resumen" in f["privacidad"]


def test_nombre_en_otro_campo_de_texto_se_borra():
    nombres = nombres_en_texto(TEXTO)
    f = limpiar_ficha(_ficha(localidad="frente a la casa de María Gómez"), nombres)
    assert f["localidad"] is None


def test_resumen_generico():
    assert resumen_generico(_ficha()) == "Choque frontal en RN 9, Banda del Río Salí, Tucumán: 1 persona fallecida y 1 persona herida."
    assert resumen_generico({"tipo_siniestro": "vuelco"}) == "Vuelco."


def test_figura_publica_al_inicio_de_la_oracion():
    from radar_vial.privacidad import nombres_probables

    texto = "Felipe Fort sufrió un accidente en la Ruta 5. Carlos Casares quedó a pocos kilómetros."
    probables = nombres_probables(texto)
    assert "Felipe Fort" in probables
    f = limpiar_ficha(_ficha(resumen="Felipe Fort sufrió un despiste en la RN 5 sin heridos.", localidad="Carlos Casares"),
                      nombres_en_texto(texto), probables)
    assert "Fort" not in f["resumen"]
    # el patrón débil no borra la localidad (hay pueblos con nombre de persona)
    assert f["localidad"] == "Carlos Casares"


def test_ocupacion_o_vinculo_quedan_marcados_para_revision():
    f = limpiar_ficha(_ficha(resumen="Murió un policía que viajaba en moto junto a su hijo en la RN 12."), set())
    assert any(m.startswith("revisar") for m in f["privacidad"])
    f = limpiar_ficha(_ficha(), set())
    assert f["privacidad"] == []
