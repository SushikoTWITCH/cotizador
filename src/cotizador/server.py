"""Servidor web local (biblioteca estándar). Sin login: por eso solo escucha en tu equipo.

Protecciones: rechaza encabezados Host ajenos (anti DNS-rebinding) y peticiones POST que vengan
de otra página (Origin). Si lo abres a tu red con ``--host 0.0.0.0``, cualquiera en esa red verá
tus clientes y cotizaciones: no lo hagas sin un proxy con contraseña.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, quote, urlparse

from . import CREDITO, __version__, config, pdf, servicio

WEB_DIR = Path(__file__).parent / "web"
MAX_BODY = 5_000_000
LOCALES = {"localhost", "127.0.0.1", "[::1]", "::1"}
IMAGENES_MARCA = {"logo": "image/png", "membrete": "image/png", "tarjeta": "image/jpeg"}


class _Handler(BaseHTTPRequestHandler):
    server_version = "cotizador/" + __version__

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    # ---------------------------------------------------------------- utilidades
    def _comunes(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")

    def _enviar(self, status: int, cuerpo: bytes, tipo: str, extra: Dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self._comunes()
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, status: int, payload: Any) -> None:
        self._enviar(status, json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                     "application/json; charset=utf-8")

    def _archivo_pdf(self, ruta: Path, nombre: str, descargar: bool) -> None:
        if not ruta.is_file():
            return self._json(404, {"error": "No encontré el PDF. Vuelve a generarlo editando la cotización."})
        disp = "attachment" if descargar else "inline"
        self._enviar(200, ruta.read_bytes(), "application/pdf",
                     {"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(nombre)}"})

    def _host_ok(self) -> bool:
        permitidos = self.server.hosts_permitidos  # type: ignore[attr-defined]
        if permitidos is None:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        host = host if host.endswith("]") else host.rpartition(":")[0] or host
        return host in permitidos

    def _origen_ok(self) -> bool:
        origen = self.headers.get("Origin")
        if not origen:
            return True
        return urlparse(origen).netloc.lower() == (self.headers.get("Host") or "").strip().lower()

    def _leer_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            raise ValueError("El cuerpo es demasiado grande.")
        if n == 0:
            return {}
        try:
            datos = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("El cuerpo no es JSON válido.") from None
        if not isinstance(datos, dict):
            raise ValueError("El cuerpo debe ser un objeto JSON.")
        return datos

    # ---------------------------------------------------------------- rutas
    def do_GET(self) -> None:
        self._despachar("GET")

    def do_POST(self) -> None:
        self._despachar("POST")

    def _despachar(self, metodo: str) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "Host no permitido."})
        if metodo == "POST" and not self._origen_ok():
            return self._json(403, {"error": "Origen no permitido."})
        url = urlparse(self.path)
        ruta = url.path.rstrip("/") or "/"
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if metodo == "GET":
                return self._get(ruta, q)
            return self._post(ruta, self._leer_json())
        except LookupError as e:
            return self._json(404, {"error": str(e).strip("'\"")})
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"Error interno en {ruta}: {type(e).__name__}: {e}\n")
            return self._json(500, {"error": "Error interno. Revisa la ventana negra del servidor."})

    def _get(self, ruta: str, q: Dict[str, str]) -> None:
        if ruta in ("/", "/index.html"):
            return self._enviar(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        m = re.fullmatch(r"/marca/(logo|membrete|tarjeta)", ruta)
        if m:
            archivo = config.archivo_marca(m.group(1))
            if not archivo:
                return self._json(404, {"error": "Sin imagen."})
            return self._enviar(200, archivo.read_bytes(), IMAGENES_MARCA[m.group(1)])
        if ruta == "/api/info":
            return self._json(200, {
                "version": __version__, "credito": CREDITO, "marca": config.marca(), "ajustes": config.ajustes(),
                "estados": servicio.ESTADOS, "motivos": servicio.MOTIVOS_PERDIDA,
                "datos": str(config.datos_dir()), "fuentes": pdf.fuentes(),
                "puede_ajustar": bool(self.server.permite_ajustes)})  # type: ignore[attr-defined]
        if ruta == "/api/cotizaciones":
            return self._json(200, servicio.listar(q.get("estado", ""), q.get("q", ""),
                                                   q.get("versiones") != "1", int(q.get("limite") or 500)))
        m = re.fullmatch(r"/api/cotizaciones/(\d+)(/pdf)?", ruta)
        if m:
            cot = servicio.obtener(int(m.group(1)))
            if m.group(2):
                return self._archivo_pdf(Path(cot["pdf"]), Path(cot["pdf"]).name, q.get("descargar") == "1")
            return self._json(200, cot)
        if ruta == "/api/agenda":
            return self._json(200, servicio.agenda())
        if ruta == "/api/estadisticas":
            return self._json(200, servicio.estadisticas(q.get("desde", ""), q.get("hasta", "")))
        if ruta == "/api/clientes":
            return self._json(200, servicio.clientes(q.get("q", "")))
        if ruta == "/api/productos":
            return self._json(200, servicio.productos(q.get("q", ""), int(q.get("limite") or 20)))
        if ruta == "/api/inventario":
            return self._json(200, servicio.buscar_inventario(q.get("sku", "")))
        if ruta == "/api/exportar.csv":
            cuerpo = ("﻿" + servicio.exportar_csv(q.get("versiones") == "1")).encode("utf-8")
            return self._enviar(200, cuerpo, "text/csv; charset=utf-8",
                                {"Content-Disposition": 'attachment; filename="cotizaciones.csv"'})
        return self._json(404, {"error": "No existe esa ruta."})

    def _post(self, ruta: str, p: dict) -> None:
        if ruta == "/api/cotizaciones":
            return self._json(201, servicio.crear(p))
        if ruta == "/api/vista_previa":
            datos = servicio._preparar(p)  # noqa: SLF001 - misma validación que al guardar
            folio = p.get("folio") or servicio.siguiente_folio()
            ruta_pdf = config.datos_dir() / "vista_previa.pdf"
            pdf.generar({**datos, "folio": folio, "version": int(p.get("version") or 1)}, ruta_pdf)
            return self._archivo_pdf(ruta_pdf, "vista_previa.pdf", False)
        m = re.fullmatch(r"/api/cotizaciones/(\d+)/(editar|estado|nota|duplicar)", ruta)
        if m:
            cid, accion = int(m.group(1)), m.group(2)
            if accion == "editar":
                return self._json(200, servicio.editar(cid, p))
            if accion == "estado":
                return self._json(200, servicio.cambiar_estado(cid, str(p.get("estado", "")), str(p.get("motivo", "")),
                                                               str(p.get("nota", "")), p.get("proximo_seguimiento")))
            if accion == "nota":
                return self._json(200, servicio.agregar_nota(cid, str(p.get("texto", "")), p.get("proximo_seguimiento")))
            return self._json(201, servicio.duplicar(cid))
        if ruta == "/api/productos/importar":
            return self._json(200, servicio.importar_productos_csv(str(p.get("csv", ""))))
        if ruta == "/api/respaldo":
            return self._json(200, {"archivo": str(servicio.respaldo(p.get("destino") or None))})
        if ruta in ("/api/marca", "/api/ajustes"):
            if not self.server.permite_ajustes:  # type: ignore[attr-defined]
                return self._json(403, {"error": "Los ajustes solo se cambian desde este equipo."})
            if ruta == "/api/marca":
                return self._json(200, config.guardar_marca(p))
            return self._json(200, config.guardar_ajustes(p))
        return self._json(404, {"error": "No existe esa ruta."})


def make_server(host: str = "127.0.0.1", port: int = 5571) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), _Handler)
    local = host in ("127.0.0.1", "localhost", "::1")
    srv.hosts_permitidos = LOCALES if local else None  # type: ignore[attr-defined]
    srv.permite_ajustes = local  # type: ignore[attr-defined]
    return srv


def serve(host: str = "127.0.0.1", port: int = 5571, abrir: bool = False) -> None:
    srv = make_server(host, port)
    url = f"http://localhost:{port}" if host in ("127.0.0.1", "0.0.0.0", "localhost") else f"http://{host}:{port}"
    print(f"Cotizador en {url}   (Ctrl+C o cierra esta ventana para salir)\n{CREDITO}")
    print(f"Datos y PDFs en: {config.datos_dir()}")
    f = pdf.fuentes()
    if f["sans"] == "Helvetica":
        print("Aviso: no encontré Roboto/Merriweather en 'fuentes'; uso Helvetica/Times. "
              "Corre:  python -m cotizador fuentes", file=sys.stderr)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("AVISO: sin login y visible en tu red: cualquiera ahí verá tus clientes y cotizaciones.", file=sys.stderr)
    if abrir:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
