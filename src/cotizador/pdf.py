"""PDF de la cotización: réplica de la plantilla de Google Docs (carta, 612×792 pt).

Medidas tomadas de la plantilla original (membrete, posiciones, colores y tipografías).
Mejoras sobre el original: varios productos (con salto de página y encabezado repetido),
SKU opcional bajo cada artículo, fecha de emisión, versión del folio, leyenda de precios
y número de página.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from . import config
from .calculos import dinero

H = 792.0
W = 612.0
COLS = (63.8, 282.8, 359.2, 434.2, 551.2)     # bordes de la tabla
FILA_MIN = 28.0
LIMITE_INFERIOR = 742.0                         # no dibujar filas más abajo de esto
TOP_TABLA_P1 = 445.5
TOP_TABLA_CONT = 232.0

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

_FUENTES: Optional[Dict[str, str]] = None


def fecha_larga(d: Any) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fuentes() -> Dict[str, str]:
    """Roboto y Merriweather si están en /fuentes; si no, Helvetica y Times (incluidas en el PDF)."""
    global _FUENTES
    if _FUENTES is not None:
        return _FUENTES
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    elegidas = {"sans": "Helvetica", "sans_b": "Helvetica-Bold", "serif": "Times-Roman", "serif_b": "Times-Bold"}
    archivos = {"sans": "Roboto-Regular.ttf", "sans_b": "Roboto-Bold.ttf",
                "serif": "Merriweather-Regular.ttf", "serif_b": "Merriweather-Bold.ttf"}
    for clave, archivo in archivos.items():
        ruta = config.FUENTES_DIR / archivo
        if ruta.is_file():
            try:
                nombre = ruta.stem
                pdfmetrics.registerFont(TTFont(nombre, str(ruta)))
                elegidas[clave] = nombre
            except Exception:  # noqa: BLE001 - archivo dañado: seguimos con la fuente estándar
                pass
    _FUENTES = elegidas
    return elegidas


def _color(hexa: str):
    from reportlab.lib.colors import HexColor
    return HexColor(hexa)


class _Lienzo:
    """Ayudante con coordenadas 'desde arriba' como en la plantilla."""

    def __init__(self, c, marca: Dict[str, Any]):
        self.c = c
        self.f = fuentes()
        col = marca["colores"]
        self.texto = _color(col["texto"])
        self.gris = _color(col["gris"])
        self.beige = _color(col["beige"])
        self.lineas = _color(col["lineas"])
        self.azul = _color(col["azul"])
        self.gris_claro = _color("#9a9a9a")

    def t(self, x: float, top: float, s: str, fuente: str, tam: float, color, alinear: str = "izq") -> None:
        c = self.c
        c.setFont(self.f[fuente], tam)
        c.setFillColor(color)
        base = H - top - tam * 0.8
        if alinear == "der":
            c.drawRightString(x, base, s)
        elif alinear == "centro":
            c.drawCentredString(x, base, s)
        else:
            c.drawString(x, base, s)

    def ancho(self, s: str, fuente: str, tam: float) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        return stringWidth(s, self.f[fuente], tam)

    def partir(self, s: str, fuente: str, tam: float, ancho: float) -> List[str]:
        from reportlab.lib.utils import simpleSplit
        return simpleSplit(s, self.f[fuente], tam, ancho) or [""]

    def rect(self, x0: float, top: float, x1: float, bottom: float, color) -> None:
        self.c.setFillColor(color)
        self.c.rect(x0, H - bottom, x1 - x0, bottom - top, stroke=0, fill=1)

    def imagen(self, ruta: Optional[Path], x0: float, top: float, x1: float, bottom: float) -> None:
        if ruta:
            self.c.drawImage(str(ruta), x0, H - bottom, width=x1 - x0, height=bottom - top, mask="auto")

    def lineas_tabla(self, top: float, bottom: float, horizontales: List[float], verticales_hasta: float) -> None:
        c = self.c
        c.setStrokeColor(self.lineas)
        c.setLineWidth(1)
        for x in COLS:
            hasta = bottom if x in (COLS[0], COLS[-1]) else verticales_hasta
            c.line(x, H - top, x, H - hasta)
        for y in horizontales:
            c.line(COLS[0] - 0.8, H - y, COLS[-1] + 0.8, H - y)


def _fila_alto(lz: _Lienzo, it: Dict[str, Any], mostrar_sku: bool) -> Tuple[float, List[str]]:
    lineas = lz.partir(it["nombre"], "sans", 10, COLS[1] - COLS[0] - 6)[:8]
    alto = 10 + len(lineas) * 12 + (9 if mostrar_sku and it.get("sku") else 0) + 6
    return max(FILA_MIN, alto), lineas


def _maquetar(lz: _Lienzo, items: List[Dict[str, Any]], mostrar_sku: bool, con_notas: bool = False):
    """Reparte las filas en páginas. Devuelve [(top_tabla, [(item|None, alto, lineas)]), ...]."""
    paginas, actual = [], []
    top = TOP_TABLA_P1 + 32.3
    y = top
    pendientes = [(it, *_fila_alto(lz, it, mostrar_sku)) for it in items]
    pendientes += [(None, 27.0, [])] * max(0, 4 - len(pendientes))   # filas vacías como en la plantilla
    cierre = 32.0 + 31.5 + 34.0 + (33.0 if con_notas else 0)         # envío + total + leyenda (+ notas)
    for i, fila in enumerate(pendientes):
        ultima = i == len(pendientes) - 1
        necesita = fila[1] + (cierre if ultima else 0)
        if y + necesita > LIMITE_INFERIOR and actual:
            paginas.append((top, actual))
            actual, top = [], TOP_TABLA_CONT + 32.3
            y = top
        actual.append(fila)
        y += fila[1]
    if y + cierre > LIMITE_INFERIOR:                  # no cupo el cierre: va solo en otra página
        paginas.append((top, actual))
        actual, top = [], TOP_TABLA_CONT + 32.3
    paginas.append((top, actual))
    return paginas


def _encabezado_tabla(lz: _Lienzo, top: float) -> None:
    lz.rect(COLS[0], top, COLS[-1], top + 32.3, lz.beige)
    lz.t(72, top + 12.1, "Artículo", "serif_b", 10, lz.texto)
    lz.t((COLS[1] + COLS[2]) / 2, top + 12.1, "Cantidad", "serif_b", 10, lz.texto, "centro")
    lz.t((COLS[2] + COLS[3]) / 2, top + 5.3, "Precio", "serif_b", 10, lz.texto, "centro")
    lz.t((COLS[2] + COLS[3]) / 2, top + 18.8, "Unitario", "serif_b", 10, lz.texto, "centro")
    lz.t(546.8, top + 12.1, "Total", "serif_b", 10, lz.texto, "der")


def _membrete(lz: _Lienzo, con_logo: bool = True) -> None:
    lz.imagen(config.archivo_marca("membrete"), -1.5, 0.0, 613.5, 195.8)
    if con_logo:
        lz.imagen(config.archivo_marca("logo"), 11.2, 9.0, 160.5, 120.0)


def _pie(lz: _Lienzo, folio_txt: str, n: int, total: int) -> None:
    lz.t(W / 2, 772, f"Cotización {folio_txt}  ·  Página {n} de {total}", "sans", 7.5, lz.gris, "centro")


def _pagina_condiciones(lz: _Lienzo, marca: Dict[str, Any]) -> None:
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    lz.imagen(config.archivo_marca("membrete"), 1.9, 5.2, 687.4, 201.0)
    condiciones = [f"{i}-{escape(t)}" for i, t in enumerate(marca.get("condiciones") or [], 1)]
    tarjeta = config.archivo_marca("tarjeta")
    alto_tarjeta = 176.3 if tarjeta else 0.0
    tam = 17.0
    while True:
        estilo = ParagraphStyle("c", fontName=lz.f["sans"], fontSize=tam, leading=tam * 1.19,
                                textColor=lz.gris, alignment=TA_JUSTIFY)
        parrafos = [Paragraph(t, estilo) for t in condiciones]
        altos = [p.wrap(432, 1000)[1] for p in parrafos]
        total = sum(altos) + tam * 1.19 * max(0, len(altos) - 1) + 14 + 18 + 4 + alto_tarjeta
        if 197 + total < LIMITE_INFERIOR or tam <= 10:
            break
        tam -= 1
    y = 197.0
    for p, alto in zip(parrafos, altos):
        p.drawOn(lz.c, 108, H - y - alto)
        y += alto + tam * 1.19
    y = y - tam * 1.19 + 14 if parrafos else y
    if marca.get("despedida"):
        lz.t(307.6, y, marca["despedida"], "sans_b", 18, lz.azul, "centro")
        y += 18 + 1.6
    if tarjeta:
        lz.imagen(tarjeta, 130.9, y, 481.1, y + alto_tarjeta)


def generar(cot: Dict[str, Any], ruta_salida: Path, marca: Optional[Dict[str, Any]] = None) -> Path:
    """Dibuja el PDF. `cot` necesita: folio, version, fecha, fecha_exp, cliente{}, items[], totales{}."""
    from reportlab.pdfgen import canvas

    marca = marca or config.marca()
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    folio_txt = str(cot["folio"]) + (f" · v{cot['version']}" if int(cot.get("version") or 1) > 1 else "")
    c = canvas.Canvas(str(ruta_salida), pagesize=(W, H), pageCompression=1)
    c.setTitle(f"Cotización {folio_txt}")
    c.setAuthor(marca.get("empresa", ""))
    c.setSubject(f"Cotización para {cot['cliente'].get('empresa', '')}")
    lz = _Lienzo(c, marca)
    mostrar_sku = bool(marca.get("mostrar_sku"))
    paginas = _maquetar(lz, cot["items"], mostrar_sku, bool(cot.get("notas_cliente")))
    hay_condiciones = bool(marca.get("condiciones") or marca.get("despedida") or config.archivo_marca("tarjeta"))
    total_pag = len(paginas) + (1 if hay_condiciones else 0)
    cli = cot["cliente"]

    for n, (top_filas, filas) in enumerate(paginas, 1):
        _membrete(lz)
        if n == 1:
            lz.t(72, 209.0, marca.get("empresa", ""), "sans", 17, lz.gris)
            if marca.get("direccion"):
                lz.t(72, 231.2, marca["direccion"], "sans", 12, lz.texto)
            lz.t(65.2, 289.1, f"Preparada para: {cli.get('empresa') or 'Cliente'}", "sans_b", 9, lz.texto)
            datos = " · ".join(v for v in (cli.get("correo"), cli.get("telefono")) if v)
            if datos:
                lz.t(65.2, 300.6, datos, "sans", 8.5, lz.gris)
            saludo = f"Atención: {cli['contacto']}" if cli.get("contacto") else marca.get("saludo_sin_contacto", "")
            lz.t(65.2, 334.1, saludo, "sans", 9, lz.texto)
            lz.t(517.5, 289.1, "Fecha", "sans_b", 9, lz.texto, "der")
            lz.t(517.5, 299.6, fecha_larga(cot["fecha"]), "sans", 9, lz.texto, "der")
            lz.t(517.5, 312.3, "Expiración", "sans_b", 9, lz.texto, "der")
            lz.t(517.5, 322.8, fecha_larga(cot["fecha_exp"]), "sans", 9, lz.texto, "der")
            lz.t(72, 376.7, "Cotización", "serif_b", 30, lz.texto)
            lz.t(72, 414.7, f"Número {folio_txt}", "serif", 16, lz.beige)
            top_tabla = TOP_TABLA_P1
        else:
            lz.t(72, 205.0, f"Cotización {folio_txt} (continuación)", "serif_b", 14, lz.texto)
            top_tabla = TOP_TABLA_CONT
        _encabezado_tabla(lz, top_tabla)
        horizontales = [top_tabla, top_tabla + 32.3]
        y = top_filas
        for it, alto, lineas in filas:
            if it is not None:
                ty = y + 9.0
                for ln in lineas:
                    lz.t(66, ty + 1, ln, "sans", 10, lz.gris)
                    ty += 12
                if mostrar_sku and it.get("sku"):
                    lz.t(66, ty + 1, f"SKU {it['sku']}", "sans", 7.5, lz.gris_claro)
                lz.t((COLS[1] + COLS[2]) / 2, y + 10, str(it["cantidad"]), "sans", 11, lz.gris, "centro")
                lz.t(432.0, y + 10, dinero(it["precio"]), "sans", 11, lz.gris, "der")
                lz.t(549.0, y + 10, dinero(it["precio"] * it["cantidad"]), "sans", 11, lz.gris, "der")
            y += alto
            horizontales.append(y)
        ultima = n == len(paginas)
        fondo = y
        if ultima:
            env = cot["totales"]["envio"]
            lz.t(66, y + 12.3, "ENVIO", "sans", 10, lz.gris)
            lz.t((COLS[1] + COLS[2]) / 2, y + 11.7, "1", "sans", 11, lz.gris, "centro")
            texto_env = dinero(env) if env else "Sin costo"
            lz.t(432.0, y + 11.7, texto_env, "sans", 11, lz.gris, "der")
            lz.t(549.0, y + 11.7, texto_env, "sans", 11, lz.gris, "der")
            y += 32.0
            horizontales.append(y)
            lz.rect(COLS[0], y, COLS[-1], y + 31.5, lz.beige)
            lz.t(72, y + 11.5, "TOTAL", "serif_b", 11, lz.texto)
            lz.t(546.7, y + 7.9, dinero(cot["totales"]["total"]), "serif_b", 18, lz.texto, "der")
            fondo = y
            y += 31.5
            horizontales.append(y)
        lz.lineas_tabla(top_tabla, y, horizontales, fondo)
        if ultima:
            leyenda = marca.get("leyenda_precios") or ""
            vig = f"Vigencia: hasta el {fecha_larga(cot['fecha_exp'])}."
            lz.t(COLS[0] + 2, y + 9, f"{leyenda} {vig}".strip(), "sans", 8.5, lz.gris)
            if cot.get("notas_cliente"):
                for i, ln in enumerate(lz.partir(cot["notas_cliente"], "sans", 8.5, COLS[-1] - COLS[0] - 4)[:3]):
                    lz.t(COLS[0] + 2, y + 21 + i * 11, ln, "sans", 8.5, lz.gris)
        _pie(lz, folio_txt, n, total_pag)
        c.showPage()

    if hay_condiciones:
        _pagina_condiciones(lz, marca)
        _pie(lz, folio_txt, total_pag, total_pag)
        c.showPage()
    c.save()
    return ruta_salida
