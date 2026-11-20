"""Recolección y resolución de links, sin red."""
from radar_vial.dominios import Entrada
from radar_vial.historial import clave_url, hash_titulo
from radar_vial.recolectar import compilar_prefiltro, fusionar, titulo_desde_url
from radar_vial.resolver import buscar_en_entradas, similitud
from radar_vial.texto import normalizar

TIT = "Tragedia en la Ruta 40: un camión embistió a un auto cerca de Cafayate y hay tres heridos"


def _item(**kw):
    base = {"titulo": TIT, "bajada": "", "url": "", "gn_id": None, "clave": None, "hash_titulo": hash_titulo(TIT),
            "medio": "Medio", "sitio": "medio.com.ar", "provincia_medio": None, "nivel_medio": None,
            "publicada": "2026-11-18T10:00:00+00:00", "tipo_busqueda": "siniestro", "origenes": []}
    base.update(kw)
    return base


def test_misma_nota_por_google_news_y_rss_queda_una_con_url_directa():
    url = "https://www.medio.com.ar/policiales/tragedia-ruta-40-cafayate-n123456"
    gn = _item(url="https://news.google.com/rss/articles/CBMiXYZ", gn_id="CBMiXYZ", id="n_gn",
               origenes=[{"tipo": "google_news", "consulta": "GN choques | Salta", "provincia": "66"}])
    rss = _item(url=url, clave=clave_url(url), id="n_rss", provincia_medio="66",
                origenes=[{"tipo": "rss", "consulta": "RSS Medio", "provincia": "66"}])
    unicos = fusionar([gn, rss])
    assert len(unicos) == 1
    u = unicos[0]
    assert u["url"] == url and u["clave"] == clave_url(url)
    assert u["provincia_medio"] == "66"
    assert {o["consulta"] for o in u["origenes"]} == {"GN choques | Salta", "RSS Medio"}


def test_misma_nota_en_varias_busquedas_de_google_news():
    a = _item(url="https://news.google.com/rss/articles/A", gn_id="A", origenes=[{"tipo": "google_news", "consulta": "q1", "provincia": "66"}])
    b = _item(url="https://news.google.com/rss/articles/A", gn_id="A", origenes=[{"tipo": "google_news", "consulta": "q2", "provincia": "38"}])
    assert len(fusionar([a, b])) == 1


def test_titulos_genericos_de_notas_distintas_no_se_fusionan():
    gen = "Murió un motociclista tras un choque"
    a = _item(titulo=gen, hash_titulo=hash_titulo(gen), url="https://a.com.ar/1", clave=clave_url("https://a.com.ar/1"))
    b = _item(titulo=gen, hash_titulo=hash_titulo(gen), url="https://b.com.ar/2", clave=clave_url("https://b.com.ar/2"))
    assert len(fusionar([a, b])) == 2


def test_prefiltro_por_palabras_clave():
    pf = compilar_prefiltro(["choc", "vuelc", "atropell", "paso a nivel"])
    assert pf.search(normalizar("Chocaron dos autos en la Ruta 2"))
    assert pf.search(normalizar("Volcó... no: VUELCO de un camión"))
    assert pf.search(normalizar("Un tren arrolló a un auto en un paso a nivel"))
    assert not pf.search(normalizar("El gobierno anunció un aumento de salarios"))


def test_titulo_desde_url():
    assert titulo_desde_url("https://www.medio.com.ar/policiales/choque-fatal-en-ruta-9-n1234567.html") == "choque fatal en ruta 9"


def test_similitud_de_titulos():
    assert similitud(TIT, TIT.upper()) == 1.0
    assert similitud(TIT, TIT.replace("Tragedia en la Ruta 40: ", "")) > 0.82
    assert similitud(TIT, "El dólar blue cerró en alza") < 0.4


def test_buscar_en_sitemap_por_titulo_y_por_slug():
    entradas = [
        Entrada("El dólar blue cerró en alza", "https://medio.com.ar/economia/dolar-123"),
        Entrada(TIT, "https://medio.com.ar/policiales/tragedia-ruta-40-456"),
    ]
    url, s = buscar_en_entradas(TIT, entradas, 0.82)
    assert url == "https://medio.com.ar/policiales/tragedia-ruta-40-456" and s == 1.0
    # sitemap sin títulos: se compara con el slug
    sin_titulo = [Entrada("", "https://medio.com.ar/policiales/tragedia-en-la-ruta-40-un-camion-embistio-a-un-auto-cerca-de-cafayate-y-hay-tres-heridos-n789")]
    url, _ = buscar_en_entradas(TIT, sin_titulo, 0.82)
    assert url and url.endswith("n789")
    # si nada se parece, no se inventa una URL
    url, _ = buscar_en_entradas("Choque en Ushuaia: dos heridos leves", entradas, 0.82)
    assert url is None


BING_RSS = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Bing</title>
<item><title>Berazategui: cruzo a pie la Ruta 2 y fue atropellado por un auto</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=1&amp;url=https%3a%2f%2fwww.novabonaerense.com%2fnota.asp%3fid%3d91715&amp;c=1</link></item>
<item><title>Berazategui: cruzo a pie la Ruta 2 y fue atropellado por un auto</title>
<link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fotro-medio.com.ar%2fcopia&amp;c=2</link></item>
</channel></rss>"""


class _R:
    ok = True

    def __init__(self, contenido):
        self.content = contenido


class _RedBing:
    def __init__(self):
        self.pedidos = []

    def get(self, url, **kw):
        self.pedidos.append(url)
        return _R(BING_RSS)


def _resolvedor_sin_red():
    from radar_vial.resolver import Resolvedor

    class _DirVacio:
        def entradas(self, sitio):
            return []

    return Resolvedor(_RedBing(), _DirVacio())


def test_bing_solo_acepta_el_mismo_medio_y_el_mismo_titulo():
    res = _resolvedor_sin_red()
    item = {"gn_id": "X", "clave": None, "sitio": "novabonaerense.com", "url": "https://news.google.com/rss/articles/X",
            "titulo": "Berazategui: cruzó a pie la Ruta 2 y fue atropellado por un auto"}
    url, metodo = res.resolver_con_metodo(item)
    assert url == "https://www.novabonaerense.com/nota.asp?id=91715" and metodo == "bing"
    # otro medio con el mismo título no sirve: no se inventa la URL
    url, _ = res.resolver_con_metodo({**item, "sitio": "lagaceta.com.ar"})
    assert url is None
    url, _ = res.resolver_con_metodo({**item, "titulo": "Volcó un camión en la Ruta 40 cerca de Cafayate"})
    assert url is None
