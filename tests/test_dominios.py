"""Lectura de sitemaps de noticias con una red simulada (sin conexión)."""
from radar_vial.dominios import dominio_de, leer_sitemap

SITEMAP_NOTICIAS = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.medio.com.ar/policiales/choque-ruta-9-n1</loc>
    <news:news>
      <news:publication><news:name>Medio</news:name><news:language>es</news:language></news:publication>
      <news:publication_date>2026-11-18T10:30:00-03:00</news:publication_date>
      <news:title>Choque frontal en la Ruta 9: dos heridos</news:title>
    </news:news>
  </url>
  <url><loc>https://www.medio.com.ar/economia/dolar-n2</loc><lastmod>2026-11-18</lastmod></url>
</urlset>"""

INDICE = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.medio.com.ar/sitemap-news-1.xml</loc></sitemap>
  <sitemap><loc>https://www.medio.com.ar/sitemap-news-2.xml</loc></sitemap>
</sitemapindex>"""

# Un XML con entidad externa no debe resolverse (los sitemaps vienen de sitios de terceros)
MALICIOSO = b"""<?xml version="1.0"?>
<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>&xxe;</loc></url></urlset>"""


class _Resp:
    def __init__(self, contenido, ok=True):
        self.content, self.ok = contenido, ok


class _RedFalsa:
    def __init__(self, paginas):
        self.paginas, self.pedidos = paginas, []

    def get(self, url, **kw):
        self.pedidos.append(url)
        return _Resp(self.paginas.get(url, b""), ok=url in self.paginas)


def test_sitemap_de_noticias_con_titulo_y_fecha():
    red = _RedFalsa({"https://m/s.xml": SITEMAP_NOTICIAS})
    entradas = leer_sitemap(red, "https://m/s.xml")
    assert len(entradas) == 2
    assert entradas[0].titulo == "Choque frontal en la Ruta 9: dos heridos"
    assert entradas[0].fecha == "2026-11-18T10:30:00-03:00"
    assert entradas[1].titulo == "" and entradas[1].fecha == "2026-11-18"


def test_indice_de_sitemaps_sigue_solo_los_primeros_hijos():
    red = _RedFalsa({
        "https://m/indice.xml": INDICE,
        "https://www.medio.com.ar/sitemap-news-1.xml": SITEMAP_NOTICIAS,
        "https://www.medio.com.ar/sitemap-news-2.xml": SITEMAP_NOTICIAS,
    })
    assert len(leer_sitemap(red, "https://m/indice.xml", max_hijos=1)) == 2
    assert "https://www.medio.com.ar/sitemap-news-2.xml" not in red.pedidos


def test_no_resuelve_entidades_externas():
    red = _RedFalsa({"https://m/x.xml": MALICIOSO})
    for e in leer_sitemap(red, "https://m/x.xml"):
        assert "root:" not in e.url


def test_dominio_de():
    assert dominio_de("https://www.lagaceta.com.ar/nota/1") == "lagaceta.com.ar"
    assert dominio_de("lagaceta.com.ar") == "lagaceta.com.ar"
    assert dominio_de("") == ""
