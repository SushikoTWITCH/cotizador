"""Rutas y configuración (marca + ajustes locales)."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

RAIZ = Path(__file__).resolve().parents[2]
MARCA_DIR = Path(os.environ.get("COTIZADOR_MARCA") or RAIZ / "marca")
FUENTES_DIR = Path(os.environ.get("COTIZADOR_FUENTES") or RAIZ / "fuentes")

MARCA_DEFECTO: Dict[str, Any] = {
    "empresa": "Mi Empresa",
    "direccion": "",
    "membrete": "membrete.png",
    "logo": "logo.png",
    "tarjeta": "tarjeta.jpg",
    "saludo_sin_contacto": "A quien corresponda:",
    "condiciones": [],
    "despedida": "¡Nos encantaría hacer negocios contigo!",
    "leyenda_precios": "Precios en pesos mexicanos (MXN), IVA incluido.",
    "vigencia_dias": 7,
    "folio_inicial": 1,
    "mostrar_sku": True,
    "dias_seguimiento": 3,
    "colores": {"texto": "#313a4d", "gris": "#666666", "beige": "#d9c4b1",
                "lineas": "#f3f3f3", "azul": "#1155cc"},
}

AJUSTES_DEFECTO: Dict[str, Any] = {
    "inventario_url": "",       # Apps Script con acción buscarProducto (opcional)
    "carpeta_pdf_extra": "",    # copia de cada PDF (ej. una carpeta de Google Drive)
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def datos_dir() -> Path:
    """Base de datos y PDFs. Fuera de Google Drive por defecto: SQLite + sincronización = corrupción."""
    d = Path(os.environ.get("COTIZADOR_DATOS") or Path.home() / "CotizadorEM")
    (d / "pdf").mkdir(parents=True, exist_ok=True)
    return d


def _leer_json(ruta: Path) -> Dict[str, Any]:
    try:
        with open(ruta, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir_json(ruta: Path, datos: Dict[str, Any]) -> None:
    tmp = ruta.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


def marca() -> Dict[str, Any]:
    m = copy.deepcopy(MARCA_DEFECTO)
    leido = _leer_json(MARCA_DIR / "marca.json")
    colores = {**m["colores"], **(leido.pop("colores", None) or {})}
    m.update(leido)
    m["colores"] = colores
    return m


def guardar_marca(cambios: Dict[str, Any]) -> Dict[str, Any]:
    """Solo acepta las llaves conocidas, con su tipo; ignora el resto."""
    actual = marca()
    for k, v in cambios.items():
        if k not in MARCA_DEFECTO or k in ("membrete", "logo", "tarjeta"):
            continue
        if k == "colores":
            if isinstance(v, dict):
                actual["colores"].update({c: x for c, x in v.items() if c in MARCA_DEFECTO["colores"] and isinstance(x, str) and _HEX.match(x)})
            continue
        if k == "condiciones":
            if not isinstance(v, list):
                raise ValueError("Las condiciones deben ser una lista de textos.")
            actual[k] = [str(x).strip()[:600] for x in v if str(x).strip()][:10]
            continue
        tipo = type(MARCA_DEFECTO[k])
        if tipo is bool:
            actual[k] = bool(v)
        elif tipo is int:
            try:
                actual[k] = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"'{k}' debe ser un número entero.") from None
            if actual[k] < 0 or (k == "vigencia_dias" and actual[k] > 365):
                raise ValueError(f"'{k}' fuera de rango.")
        else:
            actual[k] = str(v).strip()[:300]
    _escribir_json(MARCA_DIR / "marca.json", actual)
    return actual


def ajustes() -> Dict[str, Any]:
    return {**AJUSTES_DEFECTO, **{k: v for k, v in _leer_json(datos_dir() / "ajustes.json").items() if k in AJUSTES_DEFECTO}}


def guardar_ajustes(cambios: Dict[str, Any]) -> Dict[str, Any]:
    a = ajustes()
    for k in AJUSTES_DEFECTO:
        if k in cambios:
            v = str(cambios[k] or "").strip()
            if k == "inventario_url" and v and not v.startswith("https://script.google.com/"):
                raise ValueError("La URL de inventario debe ser de un Apps Script (https://script.google.com/...).")
            a[k] = v
    _escribir_json(datos_dir() / "ajustes.json", a)
    return a


def archivo_marca(nombre_llave: str) -> Path | None:
    nombre = marca().get(nombre_llave) or ""
    ruta = (MARCA_DIR / Path(nombre).name)
    return ruta if nombre and ruta.is_file() else None
