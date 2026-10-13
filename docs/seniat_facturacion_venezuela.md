# Facturación venezolana: requisitos y estado de implementación

Investigación de referencia al 6 de octubre de 2026. Este resumen orienta el desarrollo; no sustituye la validación de un contador o asesor tributario ni una autorización del SENIAT.

## Normativa revisada

- **Providencia SNAT/2011/0071**, Gaceta Oficial 39.795 del 8 de noviembre de 2011. El portal del [SENIAT publica la Providencia 0071](https://declaraciones.seniat.gob.ve/portal/page/portal/MANEJADOR_CONTENIDO_SENIAT/02NORMATIVA_LEGAL/2.4TRIBUTOS_INTERNOS/2.4.03IVA/2.4.3-5.html). Para formatos o formas libres de contribuyentes ordinarios de IVA, el artículo 13 exige, entre otros: denominación, numeración única y consecutiva, número de control y rango preimpresos, identificación y domicilio fiscal del emisor, fecha, identificación del adquirente (RIF o la identificación admitida para personas naturales que no requieren comprobante fiscal), descripción/cantidad/importes, descuentos y ajustes, base imponible e IVA discriminados por alícuota, totales, datos de la imprenta autorizada y fecha de elaboración. El artículo 14 especifica requisitos distintos para máquinas fiscales; el artículo 8 determina cuándo ciertos contribuyentes/actividades deben usarlas exclusivamente.
- **Providencia SNAT/2024/000102**, Gaceta Oficial 43.032 del 19 de diciembre de 2024. Regula medios digitales. Los artículos 3–6 condicionan su uso a autorización y regulan operaciones electrónicas, incluso cuando coexisten con máquinas fiscales. El artículo 7 exige los datos del emisor y adquirente, domicilio fiscal, fecha/hora, detalle, ajustes, bases e impuestos por alícuota, total, y el número/rango de control asignado por imprenta digital autorizada, con la identificación y autorización de esa imprenta. Texto consultado: [Providencia 000102](https://docs.cachicamo.app/fiscal/providencia000102).
- **Providencia SNAT/2026/00084**, Gaceta Oficial 43.435 del 12 de agosto de 2026. La fuente consultada indica que deroga la SNAT/2024/000121 sobre proveedores de sistemas informáticos; debe revisarse el texto íntegro y confirmar los requisitos vigentes del proveedor antes de integrarlo. Referencia: [Providencia 00084](https://docs.cachicamo.app/fiscal/providencia00084).

## Aplicación al sistema

- El checkout ahora requiere nombre, apellido, documento, teléfono, correo y domicilio fiscal. Acepta razón social separada para empresas y, si se deja vacía, guarda el nombre completo para personas naturales.
- La vista de factura desglosa descuento, base e IVA por la alícuota registrada en cada línea y advierte cuando el total guardado no concilia con las líneas.
- El identificador `Factura.numero` es una referencia interna. Ya no se presenta como número de control ni se fabrica un control derivado del pedido.
- La vista y el PDF se identifican como **informativos/no fiscales** hasta disponer de un medio de emisión y numeración de control autorizados.

## Pendiente antes de emitir documentos fiscales

1. Confirmar con asesor tributario la condición del emisor para IVA y si las condiciones del artículo 8 obligan a usar máquina fiscal en el punto físico. Las ventas por portal tienen reglas digitales adicionales.
2. Verificar la razón social, RIF y domicilio fiscal del emisor. El proyecto conserva datos previamente escritos como `FERREELECTRI PLUS` y un RIF con prefijo `V`; debe confirmarse que correspondan a la identidad tributaria real antes de imprimirlos como datos fiscales.
3. Obtener/confirmar la autorización aplicable del SENIAT y contratar una imprenta digital autorizada vigente. La app no tiene integración con ese proveedor ni recibe sus rangos/números de control.
4. Integrar la asignación del número/rango de control y los datos de autorización del proveedor. No capturar ni generar valores ficticios en esos campos.
5. Revisar las facturas antiguas marcadas por la app: algunas no contienen documento/domicilio fiscal del cliente y ciertos totales guardados difieren de la suma con IVA de sus líneas. Corregir los datos y la lógica comercial antes de emitir comprobantes fiscales.
6. Definir la moneda real de venta y, si se expresa en moneda extranjera, registrar también el equivalente en moneda nacional y el tipo de cambio aplicable. El modelo guarda `Bs.` por defecto mientras algunos flujos de pago operan en USD; la plantilla muestra la moneda guardada y no convierte importes.
