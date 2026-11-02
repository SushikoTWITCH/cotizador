import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

TMP = tempfile.mkdtemp(prefix="cotizador_test_")
os.environ["COTIZADOR_DATOS"] = TMP
MARCA_TMP = Path(TMP) / "marca"
shutil.copytree(Path(__file__).resolve().parents[1] / "marca", MARCA_TMP)
os.environ["COTIZADOR_MARCA"] = str(MARCA_TMP)

from cotizador import calculos, config, pdf, server, servicio  # noqa: E402

ITEM = {"sku": "HP-1", "nombre": "Laptop HP 15", "cantidad": 2, "precio": 12999, "costo": 10500}


def nueva(**extra):
    datos = {"cliente": {"empresa": "Papelería Lupita", "contacto": "María", "correo": "m@lupita.mx"},
             "items": [ITEM], "envio": 350}
    datos.update(extra)
    return servicio.crear(datos)


class Calculos(unittest.TestCase):
    def test_totales_iva_incluido_y_ganancia_como_el_hub(self):
        t = calculos.totales(calculos.limpiar_items([ITEM]), 350)
        self.assertEqual((t["subtotal"], t["envio"], t["total"]), (25998.0, 350.0, 26348.0))
        self.assertEqual(t["ganancia"], 25998 - 21000)          # el envío no es ganancia
        self.assertAlmostEqual(t["iva_incluido"], 26348 - round(26348 / 1.16, 2), places=2)

    def test_validaciones(self):
        for malo in ([], [{"nombre": ""}], [{"nombre": "x", "cantidad": 0}], [{"nombre": "x", "cantidad": 1.5}],
                     [{"nombre": "x", "precio": -1}], [{"nombre": "x", "precio": "abc"}]):
            with self.assertRaises(ValueError):
                calculos.limpiar_items(malo)
        self.assertEqual(calculos.limpiar_items([{"nombre": "x", "precio": "$1,234.50"}])[0]["precio"], 1234.5)

    def test_dinero(self):
        self.assertEqual(calculos.dinero(26348), "$26,348.00")


class Servicio(unittest.TestCase):
    def test_folio_automatico_y_manual(self):
        a = nueva()
        b = nueva()
        self.assertEqual(b["folio"], a["folio"] + 1)
        self.assertGreaterEqual(a["folio"], config.marca()["folio_inicial"])
        with self.assertRaises(ValueError):
            nueva(folio=a["folio"])
        c = nueva(folio=999999)
        self.assertEqual(c["folio"], 999999)

    def test_pdf_generado_y_expiracion(self):
        c = nueva(vigencia_dias=10)
        self.assertTrue(c["tiene_pdf"])
        self.assertTrue(Path(c["pdf"]).read_bytes().startswith(b"%PDF"))
        self.assertEqual(c["fecha_exp"], (date.fromisoformat(c["fecha"]) + timedelta(days=10)).isoformat())

    def test_borrador_se_edita_en_su_lugar_y_enviada_crea_version(self):
        c = nueva()
        e = servicio.editar(c["id"], {"cliente": c["cliente"], "items": [{**ITEM, "precio": 12500}]})
        self.assertEqual((e["id"], e["version"]), (c["id"], 1))
        servicio.cambiar_estado(c["id"], "enviada")
        v2 = servicio.editar(c["id"], {"cliente": c["cliente"], "items": [{**ITEM, "precio": 12000}]})
        self.assertEqual((v2["folio"], v2["version"]), (c["folio"], 2))
        self.assertEqual([v["estado"] for v in v2["versiones"]], ["reemplazada", "borrador"])
        self.assertIn("_v2_", Path(v2["pdf"]).name)
        with self.assertRaises(ValueError):
            servicio.editar(c["id"], {"cliente": c["cliente"], "items": [ITEM]})   # versión vieja

    def test_enviada_programa_seguimiento_y_perdida_exige_motivo(self):
        c = nueva()
        e = servicio.cambiar_estado(c["id"], "enviada")
        esperado = (date.today() + timedelta(days=config.marca()["dias_seguimiento"])).isoformat()
        self.assertEqual(e["proximo_seguimiento"], esperado)
        with self.assertRaises(ValueError):
            servicio.cambiar_estado(c["id"], "perdida")
        p = servicio.cambiar_estado(c["id"], "perdida", "precio", "la competencia dio menos")
        self.assertEqual((p["estado"], p["motivo_perdida"], p["proximo_seguimiento"]), ("perdida", "precio", None))
        with self.assertRaises(ValueError):
            servicio.editar(c["id"], {"cliente": c["cliente"], "items": [ITEM]})   # cerrada

    def test_nota_y_bitacora(self):
        c = nueva()
        n = servicio.agregar_nota(c["id"], "Pidió 10 piezas", date.today().isoformat())
        self.assertTrue(n["seguimiento_pendiente"])
        self.assertTrue(any("10 piezas" in e["detalle"] for e in n["eventos"]))
        self.assertIn(c["id"], [x["id"] for x in servicio.agenda()["seguimientos"]])

    def test_clientes_productos_y_estadisticas(self):
        c = nueva(cliente={"empresa": "Ferretería Norte", "telefono": "8112345678"})
        servicio.cambiar_estado(c["id"], "aceptada")
        cli = servicio.clientes("ferreteria norte")
        self.assertEqual(cli[0]["estado_cartera"], "ACTIVO")
        self.assertEqual(cli[0]["telefono"], "8112345678")
        self.assertTrue(servicio.productos("hp-1"))
        s = servicio.estadisticas()
        self.assertGreaterEqual(s["monto_vendido"], 26348)
        self.assertIsNotNone(s["tasa_cierre"])

    def test_cliente_recuerda_datos_sin_borrarlos(self):
        nueva(cliente={"empresa": "Memoria SA", "correo": "a@memoria.mx", "telefono": "55"})
        nueva(cliente={"empresa": "memoria sa", "contacto": "Pepe"})
        m = servicio.clientes("memoria")[0]
        self.assertEqual((m["correo"], m["contacto"]), ("a@memoria.mx", "Pepe"))

    def test_importar_csv_y_exportar(self):
        r = servicio.importar_productos_csv("﻿SKU,Descripción,Precio,Costo\nAB-1,Teclado,499,300\n,,,\n")
        self.assertEqual(r["importados"], 1)
        self.assertTrue(servicio.productos("teclado"))
        self.assertIn("folio,version", servicio.exportar_csv())

    def test_inventario_apps_script(self):
        ajustes = {"inventario_url": "https://script.google.com/x", "carpeta_pdf_extra": ""}
        with mock.patch.object(config, "ajustes", return_value=ajustes):
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = json.dumps(
                {"sku": "Z9", "nombre": "Bocina", "precio": 899, "stock": 4}).encode()
            with mock.patch("urllib.request.urlopen", return_value=resp):
                p = servicio.buscar_inventario("Z9")
            self.assertEqual((p["nombre"], p["precio"], p["origen"]), ("Bocina", 899.0, "inventario"))

    def test_respaldo(self):
        nueva()
        self.assertTrue(servicio.respaldo().is_file())

    def test_validacion_cliente(self):
        with self.assertRaises(ValueError):
            servicio.crear({"cliente": {"empresa": ""}, "items": [ITEM]})
        with self.assertRaises(ValueError):
            servicio.crear({"cliente": {"empresa": "x", "correo": "no-es-correo"}, "items": [ITEM]})


class Pdf(unittest.TestCase):
    def test_muchos_productos_paginan(self):
        items = calculos.limpiar_items([{**ITEM, "sku": f"S{i}", "nombre": f"Producto número {i} " * (1 + i % 3)}
                                        for i in range(40)])
        ruta = Path(TMP) / "muchos.pdf"
        pdf.generar({"folio": 1, "version": 3, "fecha": "2026-11-02", "fecha_exp": "2026-11-09",
                     "cliente": {"empresa": "ACME"}, "items": items, "totales": calculos.totales(items, 0)}, ruta)
        from reportlab.lib.utils import open_and_read  # noqa: F401  (reportlab disponible)
        self.assertGreaterEqual(ruta.read_bytes().count(b"/Type /Page\n") + ruta.read_bytes().count(b"/Type /Page "), 3)

    def test_fecha_larga(self):
        self.assertEqual(pdf.fecha_larga("2026-11-02"), "2 de noviembre de 2026")


class Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = server.make_server("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def pedir(self, ruta, cuerpo=None, **cab):
        req = urllib.request.Request(self.base + ruta, data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                     headers={"Content-Type": "application/json"})
        for k, v in cab.items():
            req.add_unredirected_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_flujo_completo(self):
        st, body, _ = self.pedir("/")
        self.assertEqual(st, 200)
        self.assertIn(b"Cotizador", body)
        info = json.loads(self.pedir("/api/info")[1])
        self.assertIn("Eduardo Perez Maqueda", info["credito"])
        st, body, _ = self.pedir("/api/cotizaciones", {"cliente": {"empresa": "Web SA"}, "items": [ITEM]})
        self.assertEqual(st, 201)
        c = json.loads(body)
        st, body, h = self.pedir(f"/api/cotizaciones/{c['id']}/pdf")
        self.assertEqual((st, h["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(self.pedir(f"/api/cotizaciones/{c['id']}/estado", {"estado": "vista"})[0], 200)
        st, body, _ = self.pedir("/api/vista_previa", {"cliente": {"empresa": "Prev"}, "items": [ITEM]})
        self.assertTrue(body.startswith(b"%PDF"))
        self.assertEqual(self.pedir("/api/agenda")[0], 200)
        st, body, _ = self.pedir("/api/exportar.csv")
        self.assertTrue(body.startswith("﻿".encode()))

    def test_errores_claros(self):
        st, body, _ = self.pedir("/api/cotizaciones", {"cliente": {"empresa": "x"}, "items": []})
        self.assertEqual(st, 400)
        self.assertIn("producto", json.loads(body)["error"])
        self.assertEqual(self.pedir("/api/cotizaciones/999999")[0], 404)
        self.assertEqual(self.pedir("/api/nada")[0], 404)

    def test_seguridad_host_y_origen(self):
        self.assertEqual(self.pedir("/api/info", Host="evil.example.com")[0], 403)
        self.assertEqual(self.pedir("/api/cotizaciones", {"cliente": {"empresa": "x"}, "items": [ITEM]},
                                    Origin="https://evil.example.com")[0], 403)
        self.assertEqual(self.pedir("/marca/../../etc/passwd")[0], 404)

    def test_ajustes_validan(self):
        st, _, _ = self.pedir("/api/ajustes", {"inventario_url": "https://evil.example.com/x"})
        self.assertEqual(st, 400)
        st, body, _ = self.pedir("/api/marca", {"vigencia_dias": 15, "colores": {"azul": "javascript:1"},
                                                "membrete": "../x"})
        m = json.loads(body)
        self.assertEqual(m["vigencia_dias"], 15)
        self.assertEqual(m["colores"]["azul"], "#1155cc")
        self.assertEqual(m["membrete"], "membrete.png")


if __name__ == "__main__":
    unittest.main()
