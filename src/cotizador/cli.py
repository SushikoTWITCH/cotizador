"""Comandos:  serve (por defecto) · fuentes · respaldo · exportar · version."""
from __future__ import annotations

import argparse
import sys
import urllib.request
from typing import List, Optional

from . import CREDITO, __version__, config, servicio

# Fuentes estáticas de Google Fonts (licencia libre) publicadas en npm por Expo; versión fija.
FUENTES_URL = {
    "Roboto-Regular.ttf": "https://cdn.jsdelivr.net/npm/@expo-google-fonts/roboto@0.2.3/Roboto_400Regular.ttf",
    "Roboto-Bold.ttf": "https://cdn.jsdelivr.net/npm/@expo-google-fonts/roboto@0.2.3/Roboto_700Bold.ttf",
    "Merriweather-Regular.ttf": "https://cdn.jsdelivr.net/npm/@expo-google-fonts/merriweather@0.2.3/Merriweather_400Regular.ttf",
    "Merriweather-Bold.ttf": "https://cdn.jsdelivr.net/npm/@expo-google-fonts/merriweather@0.2.3/Merriweather_700Bold.ttf",
}
_MAGIA_TTF = (b"\x00\x01\x00\x00", b"true")


def _bajar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cotizador/" + __version__})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(5_000_000)


def descargar_fuentes() -> int:
    """Baja Roboto y Merriweather (TTF estáticos) a la carpeta 'fuentes'. Mensajes en ASCII (consola de Windows)."""
    config.FUENTES_DIR.mkdir(parents=True, exist_ok=True)
    listas = 0
    for nombre, url in FUENTES_URL.items():
        destino = config.FUENTES_DIR / nombre
        if destino.is_file() and destino.read_bytes()[:4] in _MAGIA_TTF:
            listas += 1
            continue
        try:
            datos = _bajar(url)
        except Exception as e:  # noqa: BLE001
            print(f"  x {nombre}: no se pudo bajar ({type(e).__name__})", file=sys.stderr)
            continue
        if datos[:4] not in _MAGIA_TTF or len(datos) < 20_000:
            print(f"  x {nombre}: el archivo no es una fuente TTF", file=sys.stderr)
            continue
        tmp = destino.with_suffix(".tmp")
        tmp.write_bytes(datos)
        tmp.replace(destino)
        print(f"  ok {nombre}")
        listas += 1
    if listas < len(FUENTES_URL):
        print("Faltan fuentes: el PDF usara Helvetica/Times. Copialas a mano en: " + str(config.FUENTES_DIR),
              file=sys.stderr)
        return 1
    print(f"Fuentes listas en {config.FUENTES_DIR}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cotizador", description="Cotizaciones en PDF con seguimiento.", epilog=CREDITO)
    p.add_argument("--version", action="version", version=f"cotizador {__version__} — {CREDITO}")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="Abre la web (por defecto).")
    s.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = solo este equipo (recomendado).")
    s.add_argument("--port", type=int, default=5571)
    s.add_argument("--abrir", action="store_true", help="Abre el navegador.")
    sub.add_parser("fuentes", help="Descarga Roboto y Merriweather para que el PDF sea idéntico a la plantilla.")
    r = sub.add_parser("respaldo", help="Copia de seguridad de la base de datos.")
    r.add_argument("--destino", default="", help="Carpeta destino (ej. una carpeta de Google Drive).")
    e = sub.add_parser("exportar", help="Exporta todas las cotizaciones a CSV (Excel).")
    e.add_argument("archivo", nargs="?", default="cotizaciones.csv")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd in (None, "serve"):
        from .server import serve
        serve(getattr(a, "host", "127.0.0.1"), getattr(a, "port", 5571), getattr(a, "abrir", False))
        return 0
    if a.cmd == "fuentes":
        return descargar_fuentes()
    if a.cmd == "respaldo":
        print(f"Respaldo guardado en: {servicio.respaldo(a.destino or None)}")
        return 0
    if a.cmd == "exportar":
        with open(a.archivo, "w", encoding="utf-8-sig", newline="") as f:
            f.write(servicio.exportar_csv())
        print(f"Exportado a {a.archivo}")
        return 0
    return 0
