# Cotizador

Cotizaciones en PDF con la plantilla de **Electronics México** (membrete, logo, tabla beige, condiciones y tarjeta), más **seguimiento de cada venta**: estados, recordatorios, motivo de pérdida, versiones y estadísticas. Funciona en tu computadora, sin internet, sin Google y sin login.

> Creado por **Eduardo Perez Maqueda** con ayuda de **Claude** (Anthropic).

## Instalar (una vez)

1. Doble clic a **`INSTALAR.bat`**: instala `reportlab` (lo que dibuja el PDF) y baja las fuentes Roboto y Merriweather para que el PDF quede idéntico a la plantilla.
2. Doble clic a **`INICIAR.bat`**: se abre <http://localhost:5571>.

Si las fuentes no bajan, el PDF sale igual pero con Helvetica/Times. Vuelve a correr `INSTALAR.bat` con internet.

## Uso diario

1. **Nueva cotización**: escribe el cliente (si ya existe, se llenan solos su contacto, correo y teléfono), agrega productos (por SKU o escribiendo; los que ya cotizaste se autocompletan con su último precio y costo), envío y vigencia.
   - Los **precios llevan IVA incluido**, como en la plantilla.
   - El **costo es interno**: no sale en el PDF, sirve para ver tu ganancia y margen (en rojo si es menor a 10 %).
   - **👁 Vista previa PDF** para revisarla antes de guardar.
2. **Guardar y generar PDF**: le pone el siguiente folio (empieza en 11095), calcula la expiración y guarda el PDF.
3. Ábrela y marca su avance: **Enviada → Vista por el cliente → En negociación → Aceptada / Perdida**.
   - Al marcarla **Enviada** se agenda solo el primer seguimiento (3 días).
   - **Perdida** pide el motivo (precio, entrega, sin respuesta, competencia…): así sabes qué mejorar.
   - Cada llamada o correo se anota con su próxima fecha de seguimiento; todo queda en el **Historial**.
4. **Inicio** te dice qué toca hoy: seguimientos pendientes, las que vencen en 3 días, las vencidas sin cerrar y los borradores.

### Cambiar precios de una cotización ya enviada

**Editar** crea la **versión 2** (folio `11095 · v2`, PDF aparte) y guarda la anterior. Un borrador se corrige en su lugar. Una cotización aceptada o perdida no se edita: usa **Duplicar**.

## Qué mejora respecto al Quote Generator del HUB

| HUB (Apps Script) | Cotizador |
|---|---|
| La plantilla tiene lugar para 1 producto | Los productos que quieras, con salto de página y encabezado repetido |
| Folio a mano (se puede repetir) | Folio automático y único |
| Depende de Google y de la plantilla de otra cuenta | PDF en tu PC, sin internet |
| Sin fecha de emisión ni versión | Fecha, expiración, versión, SKU, nota para el cliente y número de página |
| Historial plano | Estados, recordatorios, motivo de pérdida, versiones, bitácora y estadísticas |
| Cartera desde el Sheet | Clientes con tasa de cierre, total comprado y cartera ACTIVO / EN PELIGRO / INACTIVO |

Además corrige dos erratas de la plantilla: «Benito Juár**e**z» y «se cotiza **aparte**».

## Dónde quedan tus datos

- Cotizaciones, clientes y productos: `C:\Users\<tu usuario>\CotizadorEM\cotizador.db`.
- PDFs: `C:\Users\<tu usuario>\CotizadorEM\pdf\`.
- Está **fuera de Google Drive a propósito**: una base de datos que Drive sincroniza a medio guardar se puede dañar.
- Para tener los PDFs en Drive, pon una carpeta en **Ajustes → Copiar cada PDF también a esta carpeta**.
- **💾 Hacer respaldo** (en Ajustes) copia la base de forma segura a la carpeta que elijas, por ejemplo una de Drive.
- Para usar otra carpeta de datos, define la variable `COTIZADOR_DATOS`.

## Ajustes

- **Marca**: empresa, dirección, condiciones (una por línea), frase final, vigencia, folio inicial y días de seguimiento.
- **Imágenes**: logo, membrete y tarjeta se cambian reemplazando los archivos de `marca\` con el mismo nombre.
- **Inventario**: pega la URL del Apps Script del Quote Generator del HUB y «Agregar por SKU» traerá nombre, precio y stock como en el HUB. Sin URL busca en tu historial.
- **Catálogo**: importa un CSV con columnas `sku, nombre, precio, costo`.
- **Excel**: **Cotizaciones → Exportar** baja todo en CSV.

## Seguridad

Sin login, así que solo escucha en tu equipo (`127.0.0.1`). Rechaza peticiones de otras páginas web y de nombres de host ajenos. **No lo abras a la red** (`--host 0.0.0.0`) sin un proxy con contraseña: cualquiera vería tus clientes y márgenes.

## Comandos

```
python -m cotizador serve --abrir        # la web (lo que hace INICIAR.bat)
python -m cotizador fuentes              # bajar Roboto y Merriweather
python -m cotizador respaldo --destino "G:\Mi unidad\RESPALDOS"
python -m cotizador exportar cotizaciones.csv
```

(Con `PYTHONPATH=src` si no lo corres desde `INICIAR.bat`.)

## Preguntas frecuentes

**¿El PDF es igual al de Google Docs?** Sí: mismas medidas, colores, membrete, logo y tarjeta, sacados de tu plantilla. Con las fuentes instaladas también la misma tipografía.

**¿Por qué la ganancia no incluye el envío?** Es la misma fórmula del HUB: ganancia = venta de productos − costo de productos. El envío se cobra y se paga.

**¿El IVA?** Los precios ya lo incluyen. El editor muestra cuánto IVA va dentro del total.

**¿Puedo seguir usando el HUB?** Sí, son independientes. Los folios empiezan en 11095; cámbialo en Ajustes si el HUB ya va más adelante.

**Se cerró la ventana negra y la página dejó de responder.** Esa ventana es el cotizador: vuelve a abrir `INICIAR.bat`.

**Dice «address already in use».** Ya está abierto en otra ventana; usa esa.
