"""Lógica de negocio: cotizaciones, versiones, seguimiento, clientes, productos y estadísticas.

Todo se guarda en SQLite (``cotizador.db``) dentro de la carpeta de datos.
"""
from __future__ import annotations

import csv
import io
import json
import re
import shutil
import sqlite3
import threading
import unicodedata
import urllib.request
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from . import calculos, config, pdf

ESTADOS = {
    "borrador": "Borrador",
    "enviada": "Enviada",
    "vista": "Vista por el cliente",
    "negociacion": "En negociación",
    "aceptada": "Aceptada",
    "perdida": "Perdida",
    "reemplazada": "Reemplazada por otra versión",
}
ABIERTOS = ("borrador", "enviada", "vista", "negociacion")
MOTIVOS_PERDIDA = {
    "precio": "Precio alto",
    "entrega": "Tiempo de entrega",
    "sin_respuesta": "Sin respuesta del cliente",
    "competencia": "Compró con la competencia",
    "presupuesto": "Sin presupuesto / lo pospuso",
    "disponibilidad": "Producto no disponible",
    "otro": "Otro",
}

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
  id INTEGER PRIMARY KEY, empresa TEXT NOT NULL, clave TEXT NOT NULL UNIQUE,
  contacto TEXT DEFAULT '', correo TEXT DEFAULT '', telefono TEXT DEFAULT '', notas TEXT DEFAULT '',
  creado TEXT, actualizado TEXT);
CREATE TABLE IF NOT EXISTS productos (
  clave TEXT PRIMARY KEY, sku TEXT DEFAULT '', nombre TEXT NOT NULL, precio REAL DEFAULT 0, costo REAL DEFAULT 0,
  veces INTEGER DEFAULT 0, ultima TEXT);
CREATE TABLE IF NOT EXISTS cotizaciones (
  id INTEGER PRIMARY KEY, folio INTEGER NOT NULL, version INTEGER NOT NULL DEFAULT 1, actual INTEGER NOT NULL DEFAULT 1,
  cliente_id INTEGER, cliente TEXT NOT NULL, items TEXT NOT NULL,
  envio REAL DEFAULT 0, subtotal REAL, total REAL, costo REAL, ganancia REAL, margen REAL, piezas INTEGER,
  fecha TEXT, fecha_exp TEXT, estado TEXT NOT NULL DEFAULT 'borrador',
  motivo_perdida TEXT DEFAULT '', nota_perdida TEXT DEFAULT '', proximo_seguimiento TEXT,
  notas_internas TEXT DEFAULT '', notas_cliente TEXT DEFAULT '', pdf TEXT DEFAULT '',
  creado TEXT, actualizado TEXT, cerrado TEXT,
  UNIQUE(folio, version));
CREATE INDEX IF NOT EXISTS ix_cot_actual ON cotizaciones(actual, estado);
CREATE TABLE IF NOT EXISTS eventos (
  id INTEGER PRIMARY KEY, folio INTEGER NOT NULL, version INTEGER, fecha TEXT, tipo TEXT, detalle TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS ix_ev_folio ON eventos(folio);
"""

_LOCK = threading.RLock()


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hoy() -> date:
    return date.today()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@contextmanager
def conexion() -> Iterator[sqlite3.Connection]:
    ruta = config.datos_dir() / "cotizador.db"
    con = sqlite3.connect(ruta, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_ESQUEMA)
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ------------------------------------------------------------------ validación

def _fecha(v: Any, campo: str) -> Optional[str]:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        raise ValueError(f"'{campo}' debe ser una fecha (AAAA-MM-DD).") from None


def _cliente(datos: Any) -> Dict[str, str]:
    if not isinstance(datos, dict):
        raise ValueError("Faltan los datos del cliente.")
    c = {k: str(datos.get(k) or "").strip()[:200] for k in ("empresa", "contacto", "correo", "telefono")}
    if not c["empresa"]:
        raise ValueError("Escribe el nombre del cliente o empresa.")
    if c["correo"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", c["correo"]):
        raise ValueError("El correo del cliente no parece válido.")
    return c


def _guardar_cliente(con: sqlite3.Connection, c: Dict[str, str]) -> int:
    clave = _norm(c["empresa"])
    fila = con.execute("SELECT id, contacto, correo, telefono FROM clientes WHERE clave=?", (clave,)).fetchone()
    if fila:
        # recordar lo nuevo sin borrar lo que ya sabíamos
        nuevos = {k: c[k] or fila[k] for k in ("contacto", "correo", "telefono")}
        con.execute("UPDATE clientes SET empresa=?, contacto=?, correo=?, telefono=?, actualizado=? WHERE id=?",
                    (c["empresa"], nuevos["contacto"], nuevos["correo"], nuevos["telefono"], _ahora(), fila["id"]))
        return int(fila["id"])
    cur = con.execute("INSERT INTO clientes(empresa, clave, contacto, correo, telefono, creado, actualizado) "
                      "VALUES (?,?,?,?,?,?,?)", (c["empresa"], clave, c["contacto"], c["correo"], c["telefono"],
                                                 _ahora(), _ahora()))
    return int(cur.lastrowid)


def _recordar_productos(con: sqlite3.Connection, items: List[Dict[str, Any]]) -> None:
    for it in items:
        clave = it["sku"].upper() if it["sku"] else "N:" + _norm(it["nombre"])
        con.execute(
            "INSERT INTO productos(clave, sku, nombre, precio, costo, veces, ultima) VALUES (?,?,?,?,?,1,?) "
            "ON CONFLICT(clave) DO UPDATE SET nombre=excluded.nombre, precio=excluded.precio, "
            "costo=CASE WHEN excluded.costo>0 THEN excluded.costo ELSE productos.costo END, "
            "veces=productos.veces+1, ultima=excluded.ultima",
            (clave, it["sku"], it["nombre"], it["precio"], it["costo"], _hoy().isoformat()))


def _evento(con: sqlite3.Connection, folio: int, version: Optional[int], tipo: str, detalle: str = "") -> None:
    con.execute("INSERT INTO eventos(folio, version, fecha, tipo, detalle) VALUES (?,?,?,?,?)",
                (folio, version, _ahora(), tipo, detalle[:1000]))


def _siguiente_folio(con: sqlite3.Connection) -> int:
    maximo = con.execute("SELECT MAX(folio) FROM cotizaciones").fetchone()[0]
    inicial = int(config.marca().get("folio_inicial") or 1)
    return max(inicial, (maximo or 0) + 1)


def siguiente_folio() -> int:
    with conexion() as con:
        return _siguiente_folio(con)


def _a_dict(fila: sqlite3.Row) -> Dict[str, Any]:
    d = dict(fila)
    d["cliente"] = json.loads(d["cliente"])
    d["items"] = json.loads(d["items"])
    d["totales"] = {k: d[k] for k in ("subtotal", "envio", "total", "costo", "ganancia", "margen", "piezas")}
    d["totales"]["margen_pct"] = d["margen"]
    d["estado_txt"] = ESTADOS.get(d["estado"], d["estado"])
    hoy = _hoy().isoformat()
    d["vencida"] = d["estado"] in ABIERTOS and bool(d["fecha_exp"]) and d["fecha_exp"] < hoy
    d["seguimiento_pendiente"] = (d["estado"] in ABIERTOS and bool(d["proximo_seguimiento"])
                                  and d["proximo_seguimiento"] <= hoy)
    d["folio_txt"] = f"{d['folio']}" + (f" · v{d['version']}" if d["version"] > 1 else "")
    d["tiene_pdf"] = bool(d["pdf"]) and Path(d["pdf"]).is_file()
    return d


def _nombre_pdf(folio: int, version: int, empresa: str) -> str:
    limpio = re.sub(r"[^A-Za-z0-9]+", "_", unicodedata.normalize("NFKD", empresa).encode("ascii", "ignore").decode())
    limpio = limpio.strip("_")[:40] or "cliente"
    return f"Cotizacion_{folio}" + (f"_v{version}" if version > 1 else "") + f"_{limpio}.pdf"


def _generar_pdf(cot: Dict[str, Any]) -> str:
    ruta = config.datos_dir() / "pdf" / _nombre_pdf(cot["folio"], cot["version"], cot["cliente"]["empresa"])
    pdf.generar(cot, ruta)
    extra = config.ajustes().get("carpeta_pdf_extra")
    if extra:
        try:
            Path(extra).mkdir(parents=True, exist_ok=True)
            shutil.copy2(ruta, Path(extra) / ruta.name)
        except OSError:
            pass  # la copia extra es opcional: no frena la cotización
    return str(ruta)


def _preparar(datos: Dict[str, Any], fecha: Optional[str] = None) -> Dict[str, Any]:
    cliente = _cliente(datos.get("cliente"))
    items = calculos.limpiar_items(datos.get("items"))
    tot = calculos.totales(items, datos.get("envio", 0))
    marca = config.marca()
    f = _fecha(datos.get("fecha"), "fecha") or fecha or _hoy().isoformat()
    try:
        vig = int(datos.get("vigencia_dias") or marca.get("vigencia_dias") or 7)
    except (TypeError, ValueError):
        raise ValueError("La vigencia debe ser un número de días.") from None
    if not 1 <= vig <= 365:
        raise ValueError("La vigencia debe estar entre 1 y 365 días.")
    exp = _fecha(datos.get("fecha_exp"), "expiración") or (date.fromisoformat(f) + timedelta(days=vig)).isoformat()
    if exp < f:
        raise ValueError("La expiración no puede ser antes de la fecha de la cotización.")
    return {"cliente": cliente, "items": items, "totales": tot, "fecha": f, "fecha_exp": exp,
            "notas_internas": str(datos.get("notas_internas") or "")[:2000],
            "notas_cliente": str(datos.get("notas_cliente") or "")[:300]}


def _insertar(con: sqlite3.Connection, p: Dict[str, Any], folio: int, version: int, estado: str = "borrador") -> int:
    t = p["totales"]
    cliente_id = _guardar_cliente(con, p["cliente"])
    _recordar_productos(con, p["items"])
    cur = con.execute(
        "INSERT INTO cotizaciones(folio, version, actual, cliente_id, cliente, items, envio, subtotal, total, costo, "
        "ganancia, margen, piezas, fecha, fecha_exp, estado, notas_internas, notas_cliente, creado, actualizado) "
        "VALUES (?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (folio, version, cliente_id, json.dumps(p["cliente"], ensure_ascii=False),
         json.dumps(p["items"], ensure_ascii=False), t["envio"], t["subtotal"], t["total"], t["costo"],
         t["ganancia"], t["margen_pct"], t["piezas"], p["fecha"], p["fecha_exp"], estado,
         p["notas_internas"], p["notas_cliente"], _ahora(), _ahora()))
    cid = int(cur.lastrowid)
    ruta = _generar_pdf({**p, "folio": folio, "version": version})
    con.execute("UPDATE cotizaciones SET pdf=? WHERE id=?", (ruta, cid))
    return cid


# ------------------------------------------------------------------ operaciones

def crear(datos: Dict[str, Any]) -> Dict[str, Any]:
    p = _preparar(datos)
    with _LOCK, conexion() as con:
        folio = datos.get("folio")
        if folio not in (None, ""):
            try:
                folio = int(folio)
            except (TypeError, ValueError):
                raise ValueError("El folio debe ser un número.") from None
            if folio < 1:
                raise ValueError("El folio debe ser mayor a 0.")
            if con.execute("SELECT 1 FROM cotizaciones WHERE folio=?", (folio,)).fetchone():
                raise ValueError(f"El folio {folio} ya existe. Déjalo vacío para usar el siguiente automático.")
        else:
            folio = _siguiente_folio(con)
        cid = _insertar(con, p, folio, 1)
        _evento(con, folio, 1, "creada", f"Total {calculos.dinero(p['totales']['total'])}")
    return obtener(cid)


def editar(cid: int, datos: Dict[str, Any]) -> Dict[str, Any]:
    """Borrador: se corrige en su lugar. Ya enviada: se crea la versión siguiente y se guarda la anterior."""
    with _LOCK, conexion() as con:
        fila = con.execute("SELECT * FROM cotizaciones WHERE id=?", (cid,)).fetchone()
        if not fila:
            raise LookupError("No existe esa cotización.")
        if not fila["actual"]:
            raise ValueError("Esa es una versión anterior. Edita la versión más reciente.")
        if fila["estado"] in ("aceptada", "perdida"):
            raise ValueError("La cotización ya está cerrada. Usa «Duplicar» para hacer una nueva.")
        p = _preparar(datos, fila["fecha"] if fila["estado"] == "borrador" else None)
        if fila["estado"] == "borrador":
            t = p["totales"]
            cliente_id = _guardar_cliente(con, p["cliente"])
            _recordar_productos(con, p["items"])
            con.execute(
                "UPDATE cotizaciones SET cliente_id=?, cliente=?, items=?, envio=?, subtotal=?, total=?, costo=?, "
                "ganancia=?, margen=?, piezas=?, fecha=?, fecha_exp=?, notas_internas=?, notas_cliente=?, "
                "actualizado=? WHERE id=?",
                (cliente_id, json.dumps(p["cliente"], ensure_ascii=False), json.dumps(p["items"], ensure_ascii=False),
                 t["envio"], t["subtotal"], t["total"], t["costo"], t["ganancia"], t["margen_pct"], t["piezas"],
                 p["fecha"], p["fecha_exp"], p["notas_internas"], p["notas_cliente"], _ahora(), cid))
            ruta = _generar_pdf({**p, "folio": fila["folio"], "version": fila["version"]})
            con.execute("UPDATE cotizaciones SET pdf=? WHERE id=?", (ruta, cid))
            _evento(con, fila["folio"], fila["version"], "editada", f"Total {calculos.dinero(t['total'])}")
            nuevo = cid
        else:
            version = con.execute("SELECT MAX(version) FROM cotizaciones WHERE folio=?", (fila["folio"],)).fetchone()[0] + 1
            con.execute("UPDATE cotizaciones SET actual=0, estado='reemplazada', actualizado=? WHERE id=?", (_ahora(), cid))
            nuevo = _insertar(con, p, fila["folio"], version)
            if fila["proximo_seguimiento"]:
                con.execute("UPDATE cotizaciones SET proximo_seguimiento=? WHERE id=?", (fila["proximo_seguimiento"], nuevo))
            antes, ahora = calculos.dinero(fila["total"]), calculos.dinero(p["totales"]["total"])
            _evento(con, fila["folio"], version, "nueva_version", f"v{fila['version']} → v{version}: {antes} → {ahora}")
    return obtener(nuevo)


def duplicar(cid: int) -> Dict[str, Any]:
    actual = obtener(cid)
    return crear({"cliente": actual["cliente"], "items": actual["items"], "envio": actual["envio"],
                  "notas_cliente": actual["notas_cliente"], "notas_internas": f"Duplicada de {actual['folio_txt']}."})


def cambiar_estado(cid: int, estado: str, motivo: str = "", nota: str = "",
                   proximo_seguimiento: Optional[str] = None) -> Dict[str, Any]:
    if estado not in ESTADOS or estado == "reemplazada":
        raise ValueError("Estado inválido.")
    if estado == "perdida" and motivo not in MOTIVOS_PERDIDA:
        raise ValueError("Elige el motivo por el que se perdió: así sabrás qué mejorar.")
    prox = _fecha(proximo_seguimiento, "próximo seguimiento")
    with _LOCK, conexion() as con:
        fila = con.execute("SELECT * FROM cotizaciones WHERE id=?", (cid,)).fetchone()
        if not fila:
            raise LookupError("No existe esa cotización.")
        if not fila["actual"]:
            raise ValueError("Esa es una versión anterior; cambia el estado de la más reciente.")
        cerrado = _hoy().isoformat() if estado in ("aceptada", "perdida") else None
        if estado in ("aceptada", "perdida"):
            prox = None
        elif prox is None:
            prox = fila["proximo_seguimiento"]
            if estado == "enviada" and not prox:
                prox = (_hoy() + timedelta(days=int(config.marca().get("dias_seguimiento") or 3))).isoformat()
        con.execute("UPDATE cotizaciones SET estado=?, motivo_perdida=?, nota_perdida=?, proximo_seguimiento=?, "
                    "cerrado=?, actualizado=? WHERE id=?",
                    (estado, motivo if estado == "perdida" else "", nota if estado == "perdida" else "",
                     prox, cerrado, _ahora(), cid))
        detalle = ESTADOS[estado]
        if estado == "perdida":
            detalle += f" — {MOTIVOS_PERDIDA[motivo]}"
        if nota:
            detalle += f": {nota}"
        _evento(con, fila["folio"], fila["version"], "estado", detalle)
    return obtener(cid)


def agregar_nota(cid: int, texto: str, proximo_seguimiento: Optional[str] = None) -> Dict[str, Any]:
    texto = str(texto or "").strip()
    prox = _fecha(proximo_seguimiento, "próximo seguimiento")
    if not texto and not prox:
        raise ValueError("Escribe una nota o elige una fecha de seguimiento.")
    with _LOCK, conexion() as con:
        fila = con.execute("SELECT folio, version, estado FROM cotizaciones WHERE id=?", (cid,)).fetchone()
        if not fila:
            raise LookupError("No existe esa cotización.")
        if prox:
            con.execute("UPDATE cotizaciones SET proximo_seguimiento=?, actualizado=? WHERE id=?", (prox, _ahora(), cid))
        _evento(con, fila["folio"], fila["version"], "nota",
                texto + (f" (próximo seguimiento: {prox})" if prox else ""))
    return obtener(cid)


def obtener(cid: int) -> Dict[str, Any]:
    with conexion() as con:
        fila = con.execute("SELECT * FROM cotizaciones WHERE id=?", (cid,)).fetchone()
        if not fila:
            raise LookupError("No existe esa cotización.")
        d = _a_dict(fila)
        d["versiones"] = [{"id": v["id"], "version": v["version"], "total": v["total"], "estado": v["estado"],
                           "fecha": v["fecha"], "actual": bool(v["actual"])}
                          for v in con.execute("SELECT id, version, total, estado, fecha, actual FROM cotizaciones "
                                               "WHERE folio=? ORDER BY version", (d["folio"],))]
        d["eventos"] = [dict(e) for e in con.execute("SELECT fecha, version, tipo, detalle FROM eventos WHERE folio=? "
                                                      "ORDER BY id DESC", (d["folio"],))]
    return d


def listar(estado: str = "", texto: str = "", solo_actuales: bool = True, limite: int = 500) -> List[Dict[str, Any]]:
    sql, args = "SELECT * FROM cotizaciones WHERE 1=1", []
    if solo_actuales:
        sql += " AND actual=1"
    if estado == "vencida":
        sql += f" AND estado IN ({','.join('?' * len(ABIERTOS))}) AND fecha_exp < ?"
        args += list(ABIERTOS) + [_hoy().isoformat()]
    elif estado == "abiertas":
        sql += f" AND estado IN ({','.join('?' * len(ABIERTOS))})"
        args += list(ABIERTOS)
    elif estado:
        sql += " AND estado=?"
        args.append(estado)
    sql += " ORDER BY folio DESC, version DESC LIMIT ?"
    args.append(max(1, min(int(limite), 5000)))
    with conexion() as con:
        filas = [_a_dict(f) for f in con.execute(sql, args)]
    if texto:
        q = _norm(texto)
        filas = [f for f in filas if q in _norm(f"{f['folio']} {json.dumps(f['cliente'])} "
                                                f"{' '.join(i['nombre'] + ' ' + i['sku'] for i in f['items'])}")]
    return filas


def agenda() -> Dict[str, Any]:
    """Lo que toca hoy: seguimientos vencidos, cotizaciones por expirar y ya expiradas sin cerrar."""
    hoy = _hoy()
    abiertas = listar("abiertas")
    en3 = (hoy + timedelta(days=3)).isoformat()
    return {
        "hoy": hoy.isoformat(),
        "seguimientos": sorted([c for c in abiertas if c["seguimiento_pendiente"]],
                               key=lambda c: c["proximo_seguimiento"]),
        "por_vencer": sorted([c for c in abiertas if not c["vencida"] and c["fecha_exp"] <= en3],
                             key=lambda c: c["fecha_exp"]),
        "vencidas": [c for c in abiertas if c["vencida"]],
        "borradores": [c for c in abiertas if c["estado"] == "borrador"],
    }


def _estado_cartera(ultima: Optional[str]) -> str:
    if not ultima:
        return "SIN COMPRAS"
    dias = (_hoy() - date.fromisoformat(ultima[:10])).days
    return "ACTIVO" if dias <= 15 else ("EN PELIGRO" if dias <= 30 else "INACTIVO")


def clientes(texto: str = "") -> List[Dict[str, Any]]:
    with conexion() as con:
        filas = con.execute(
            "SELECT c.*, COUNT(q.id) AS cotizaciones, "
            "SUM(CASE WHEN q.estado='aceptada' THEN 1 ELSE 0 END) AS aceptadas, "
            "SUM(CASE WHEN q.estado='perdida' THEN 1 ELSE 0 END) AS perdidas, "
            "COALESCE(SUM(CASE WHEN q.estado='aceptada' THEN q.total END),0) AS total_comprado, "
            "COALESCE(SUM(CASE WHEN q.estado='aceptada' THEN q.ganancia END),0) AS ganancia, "
            "MAX(CASE WHEN q.estado='aceptada' THEN COALESCE(q.cerrado, q.fecha) END) AS ultima_compra, "
            "MAX(q.fecha) AS ultima_cotizacion "
            "FROM clientes c LEFT JOIN cotizaciones q ON q.cliente_id=c.id AND q.actual=1 "
            "GROUP BY c.id ORDER BY total_comprado DESC, ultima_cotizacion DESC").fetchall()
    res = []
    q = _norm(texto)
    for f in filas:
        d = dict(f)
        if q and q not in _norm(f"{d['empresa']} {d['contacto']} {d['correo']}"):
            continue
        cerradas = (d["aceptadas"] or 0) + (d["perdidas"] or 0)
        d["tasa_cierre"] = round(100 * (d["aceptadas"] or 0) / cerradas, 1) if cerradas else None
        d["estado_cartera"] = _estado_cartera(d["ultima_compra"])
        res.append(d)
    return res


def productos(texto: str = "", limite: int = 20) -> List[Dict[str, Any]]:
    with conexion() as con:
        filas = [dict(f) for f in con.execute("SELECT * FROM productos ORDER BY veces DESC, ultima DESC")]
    if texto:
        q = _norm(texto)
        filas = [f for f in filas if q in _norm(f"{f['sku']} {f['nombre']}")]
    return filas[:max(1, min(int(limite), 1000))]


def importar_productos_csv(texto: str) -> Dict[str, int]:
    """CSV con columnas sku, nombre, precio, costo (encabezados flexibles)."""
    lector = csv.DictReader(io.StringIO(texto.lstrip("﻿")))
    alias = {"sku": ("sku", "clave", "codigo", "código", "modelo"), "nombre": ("nombre", "descripcion", "descripción", "producto", "articulo", "artículo"),
             "precio": ("precio", "precio venta", "precio_venta", "venta"), "costo": ("costo", "costo base", "costo_base", "compra")}
    nuevos = errores = 0
    items = []
    for fila in lector:
        f = {_norm(k): v for k, v in fila.items() if k}
        it = {}
        for campo, nombres in alias.items():
            it[campo] = next((f[_norm(n)] for n in nombres if _norm(n) in f and f[_norm(n)]), "")
        try:
            items.extend(calculos.limpiar_items([it]))
            nuevos += 1
        except ValueError:
            errores += 1
    with _LOCK, conexion() as con:
        for it in items:
            clave = it["sku"].upper() if it["sku"] else "N:" + _norm(it["nombre"])
            con.execute("INSERT INTO productos(clave, sku, nombre, precio, costo, veces, ultima) VALUES (?,?,?,?,?,0,NULL) "
                        "ON CONFLICT(clave) DO UPDATE SET nombre=excluded.nombre, precio=excluded.precio, costo=excluded.costo",
                        (clave, it["sku"], it["nombre"], it["precio"], it["costo"]))
    return {"importados": nuevos, "errores": errores}


def buscar_inventario(sku: str) -> Dict[str, Any]:
    """Consulta el Apps Script de inventario (el mismo que usa el Quote Generator del HUB)."""
    url = config.ajustes().get("inventario_url")
    sku = str(sku or "").strip()
    if not sku:
        raise ValueError("Escribe un SKU.")
    locales = [p for p in productos(sku, 5) if p["sku"].upper() == sku.upper()]
    if not url:
        if locales:
            return {"origen": "historial", **locales[0]}
        raise LookupError("No está en tu historial. Configura la URL de inventario en Ajustes para buscar en tu Sheet.")
    cuerpo = json.dumps({"action": "buscarProducto", "data": {"codigo": sku}}).encode()
    req = urllib.request.Request(url, data=cuerpo, headers={"Content-Type": "text/plain;charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            res = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        if locales:
            return {"origen": "historial", **locales[0]}
        raise LookupError("No se pudo consultar el inventario (sin internet o el Apps Script no respondió).") from None
    if not isinstance(res, dict) or res.get("nombre") in (None, "", "Desconocido"):
        if locales:
            return {"origen": "historial", **locales[0]}
        raise LookupError("Ese SKU no está en el inventario.")
    costo = locales[0]["costo"] if locales else 0
    return {"origen": "inventario", "sku": res.get("sku") or sku, "nombre": res["nombre"],
            "precio": float(res.get("precio") or 0), "costo": costo, "stock": res.get("stock")}


def estadisticas(desde: str = "", hasta: str = "") -> Dict[str, Any]:
    d0, d1 = _fecha(desde, "desde"), _fecha(hasta, "hasta")
    cots = [c for c in listar(limite=5000) if (not d0 or c["fecha"] >= d0) and (not d1 or c["fecha"] <= d1)]
    acept = [c for c in cots if c["estado"] == "aceptada"]
    perd = [c for c in cots if c["estado"] == "perdida"]
    abiertas = [c for c in cots if c["estado"] in ABIERTOS]
    cerradas = len(acept) + len(perd)

    def suma(lista, k):
        return round(sum(c[k] or 0 for c in lista), 2)

    motivos: Dict[str, int] = {}
    for c in perd:
        motivos[c["motivo_perdida"]] = motivos.get(c["motivo_perdida"], 0) + 1
    prods: Dict[str, Dict[str, Any]] = {}
    for c in cots:
        for it in c["items"]:
            k = it["sku"] or it["nombre"]
            p = prods.setdefault(k, {"sku": it["sku"], "nombre": it["nombre"], "cotizado": 0, "vendido": 0, "monto_vendido": 0.0})
            p["cotizado"] += it["cantidad"]
            if c["estado"] == "aceptada":
                p["vendido"] += it["cantidad"]
                p["monto_vendido"] = round(p["monto_vendido"] + it["precio"] * it["cantidad"], 2)
    dias_cierre = []
    with conexion() as con:
        for c in acept:
            primera = con.execute("SELECT MIN(fecha) FROM cotizaciones WHERE folio=?", (c["folio"],)).fetchone()[0]
            if primera and c["cerrado"]:
                dias_cierre.append((date.fromisoformat(c["cerrado"][:10]) - date.fromisoformat(primera[:10])).days)
        con_version = con.execute("SELECT COUNT(DISTINCT folio) FROM cotizaciones WHERE version>1").fetchone()[0]
    por_mes: Dict[str, Dict[str, float]] = {}
    for c in cots:
        m = por_mes.setdefault(c["fecha"][:7], {"cotizado": 0.0, "vendido": 0.0, "cotizaciones": 0, "aceptadas": 0})
        m["cotizado"] = round(m["cotizado"] + c["total"], 2)
        m["cotizaciones"] += 1
        if c["estado"] == "aceptada":
            m["vendido"] = round(m["vendido"] + c["total"], 2)
            m["aceptadas"] += 1
    return {
        "cotizaciones": len(cots),
        "por_estado": {e: sum(1 for c in cots if c["estado"] == e) for e in ESTADOS if e != "reemplazada"},
        "vencidas_sin_cerrar": sum(1 for c in abiertas if c["vencida"]),
        "tasa_cierre": round(100 * len(acept) / cerradas, 1) if cerradas else None,
        "monto_cotizado": suma(cots, "total"),
        "monto_vendido": suma(acept, "total"),
        "monto_abierto": suma(abiertas, "total"),
        "ganancia_cotizada": suma(cots, "ganancia"),
        "ganancia_ganada": suma(acept, "ganancia"),
        "ticket_promedio": round(suma(acept, "total") / len(acept), 2) if acept else None,
        "margen_promedio": round(sum(c["margen"] for c in acept) / len(acept), 1) if acept else None,
        "dias_promedio_cierre": round(sum(dias_cierre) / len(dias_cierre), 1) if dias_cierre else None,
        "cotizaciones_con_cambios": con_version,
        "motivos_perdida": sorted(({"motivo": MOTIVOS_PERDIDA.get(k, k), "veces": v} for k, v in motivos.items()),
                                  key=lambda x: -x["veces"]),
        "productos_top": sorted(prods.values(), key=lambda p: (-p["cotizado"], -p["vendido"]))[:15],
        "por_mes": [{"mes": k, **v} for k, v in sorted(por_mes.items())],
    }


CSV_COLUMNAS = ("folio", "version", "fecha", "fecha_exp", "estado", "empresa", "contacto", "correo", "telefono",
                "piezas", "subtotal", "envio", "total", "costo", "ganancia", "margen", "motivo_perdida",
                "nota_perdida", "proximo_seguimiento", "cerrado", "productos")


def exportar_csv(todas_las_versiones: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNAS)
    for c in listar(solo_actuales=not todas_las_versiones, limite=5000):
        cli = c["cliente"]
        w.writerow([c["folio"], c["version"], c["fecha"], c["fecha_exp"], c["estado_txt"], cli.get("empresa"),
                    cli.get("contacto"), cli.get("correo"), cli.get("telefono"), c["piezas"], c["subtotal"],
                    c["envio"], c["total"], c["costo"], c["ganancia"], c["margen"],
                    MOTIVOS_PERDIDA.get(c["motivo_perdida"], ""), c["nota_perdida"], c["proximo_seguimiento"] or "",
                    c["cerrado"] or "", " | ".join(f"{i['cantidad']}x {i['nombre']}" for i in c["items"])])
    return buf.getvalue()


def respaldo(destino: Optional[str] = None) -> Path:
    """Copia segura de la base (API de respaldo de SQLite) a ``destino`` o a datos/respaldos."""
    carpeta = Path(destino) if destino else config.datos_dir() / "respaldos"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"cotizador_{datetime.now():%Y%m%d_%H%M%S}.db"
    with conexion() as con:
        dst = sqlite3.connect(ruta)
        try:
            con.backup(dst)
        finally:
            dst.close()
    return ruta
