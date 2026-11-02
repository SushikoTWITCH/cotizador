"""Cálculos de una cotización. Precios de venta con IVA incluido (como la plantilla original).

Misma fórmula de ganancia que el Quote Generator del HUB:
    ganancia = subtotal de productos − costo de productos   (el envío no cuenta como ganancia)
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, List

IVA = Decimal("0.16")
CENT = Decimal("0.01")


def _dec(v: Any, campo: str) -> Decimal:
    if v in (None, ""):
        return Decimal(0)
    try:
        d = Decimal(str(v).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        raise ValueError(f"'{campo}' debe ser un número.") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"'{campo}' no puede ser negativo.")
    return d


def redondear(d: Decimal) -> Decimal:
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def limpiar_items(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValueError("Agrega al menos un producto.")
    if len(items) > 200:
        raise ValueError("Máximo 200 productos por cotización.")
    limpios = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            raise ValueError(f"Producto {i}: formato inválido.")
        nombre = str(it.get("nombre") or "").strip()
        if not nombre:
            raise ValueError(f"Producto {i}: falta la descripción.")
        bruto = it.get("cantidad")
        cant = _dec(1 if bruto in (None, "") else bruto, f"cantidad del producto {i}")
        if cant <= 0 or cant != cant.to_integral_value():
            raise ValueError(f"Producto {i}: la cantidad debe ser un entero mayor a 0.")
        limpios.append({
            "sku": str(it.get("sku") or "").strip()[:60],
            "nombre": nombre[:400],
            "cantidad": int(cant),
            "precio": float(redondear(_dec(it.get("precio"), f"precio del producto {i}"))),
            "costo": float(redondear(_dec(it.get("costo"), f"costo del producto {i}"))),
        })
    return limpios


def totales(items: List[Dict[str, Any]], envio: Any = 0) -> Dict[str, float]:
    env = redondear(_dec(envio, "envío"))
    sub = sum((redondear(Decimal(str(i["precio"])) * i["cantidad"]) for i in items), Decimal(0))
    costo = sum((redondear(Decimal(str(i["costo"])) * i["cantidad"]) for i in items), Decimal(0))
    total = sub + env
    ganancia = sub - costo
    base_sin_iva = redondear(total / (1 + IVA))
    return {
        "subtotal": float(sub),
        "envio": float(env),
        "total": float(total),
        "iva_incluido": float(total - base_sin_iva),
        "costo": float(costo),
        "ganancia": float(ganancia),
        "margen_pct": float(redondear(ganancia / sub * 100)) if sub else 0.0,
        "piezas": sum(i["cantidad"] for i in items),
    }


def dinero(v: Any) -> str:
    d = redondear(Decimal(str(v or 0)))
    signo = "-" if d < 0 else ""
    return f"{signo}${abs(d):,.2f}"
