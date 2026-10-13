# Flujo Operativo Comercial

## Paso 1: estados, transiciones y permisos

Este documento fija el contrato funcional para separar el ciclo del pedido, el pago y el envío. En este paso no se cambian modelos, datos existentes ni acciones administrativas; esos cambios deben implementarse con una migración compatible y pruebas en el paso siguiente.

## Situación actual

- `Pedido.estado` usa `pendiente`, `pagado`, `enviado` y `cancelado`. Pago y envío comparten el mismo campo.
- `Pago.estado` usa `pendiente`, `confirmado` y `rechazado`, además de `verificado` y datos de pasarela.
- El pedido se crea pendiente y reserva existencias. La aprobación del pago valida el comprobante dentro de una transacción y genera la factura.
- No existe todavía un despacho con dirección histórica, transportista, guía o eventos de seguimiento. El checkout actualiza el teléfono y la dirección del perfil del cliente.
- Las acciones administrativas de pedidos están protegidas por acceso de staff y, en varias rutas, por `dashboard.view_auditlog`. La auditoría no equivale a un historial completo de cambios por campo.

## Contrato objetivo

Los tres ciclos serán independientes. Cambiar el estado de uno no debe aprobar, cancelar ni despachar automáticamente los otros.

### Pedido

- `pendiente_pago`: pedido creado; no hay pago confirmado.
- `confirmado`: el pago requerido fue confirmado y el pedido puede prepararse.
- `cancelado`: pedido cancelado con motivo y actor registrados.
- `completado`: entrega finalizada y sin devolución abierta.

### Pago

Cada intento conserva su propio estado:

- `pendiente`: se inició el intento, sin evidencia suficiente todavía.
- `en_revision`: requiere validación manual o revisión de conciliación.
- `confirmado`: confirmado por una pasarela validada o por un operador autorizado.
- `rechazado`: rechazado con motivo; no cambia por sí solo el estado del envío.
- `reembolsado`: reembolso total confirmado por el proveedor.
- `reembolso_parcial`: reembolso parcial confirmado y con monto registrado.
- `disputado`: reclamo o contracargo abierto con el proveedor.

Para la primera versión, el pedido no se confirma si no existe un pago confirmado por el monto y moneda esperados. Reintentos de pago se guardan como intentos separados, sin sobrescribir referencias previas.

### Envío

El envío será un registro separado del pedido. El primer alcance permite un envío por pedido; se podrá ampliar a varios paquetes sin cambiar el significado de los estados.

- `no_preparado`: pago confirmado, aún no iniciado en almacén.
- `preparando`: artículos en preparación.
- `listo`: paquete verificado y listo para entregar al transportista.
- `despachado`: entregado al transportista; requiere fecha y guía o explicación si no aplica.
- `en_transito`: el transportista reporta movimiento.
- `entregado`: entrega confirmada con fecha y evidencia disponible.
- `incidencia`: intento fallido, dirección incorrecta u otro problema con detalle obligatorio.
- `devuelto`: paquete retornado al vendedor.

No se puede preparar ni despachar un pedido sin pago confirmado, salvo una excepción explícita, autorizada y auditada.

## Permisos

- **Atención/consulta:** puede ver pedidos y agregar notas; no confirma pagos ni cambia el envío.
- **Operador de pagos:** puede consultar la evidencia protegida, confirmar o rechazar pagos manuales con motivo; no marca envíos.
- **Operador de almacén:** puede consultar la dirección del pedido y actualizar preparación, guía e incidencias; no confirma ni reembolsa pagos.
- **Administrador:** asigna permisos y resuelve excepciones; sus acciones también quedan auditadas.
- **Cliente:** consulta únicamente sus pedidos, pagos y seguimiento; no puede modificar estados operativos.
- **Pasarela/transportista:** solo actualiza mediante callbacks autenticados, con validación del evento y protección contra duplicados.

Las rutas deben usar permisos específicos de operación, no reutilizar el permiso de lectura de auditoría como autorización para cambiar pedidos o pagos. Las escrituras operativas serán POST con CSRF; los callbacks externos validarán firma, referencia, monto y moneda antes de aplicar cambios.

## Reglas de integridad y auditoría

- Guardar una copia inmutable de los datos de entrega asociados al pedido al momento de confirmar la compra; los cambios posteriores del perfil no alteran esa dirección.
- Toda transición registra entidad, estado anterior y nuevo, actor o integración, fecha, motivo y referencia de proveedor cuando aplique.
- Las notificaciones repetidas de pasarela o transportista deben ser idempotentes: el mismo evento no duplica confirmaciones, facturas, movimientos de stock ni avisos.
- No guardar números completos de tarjeta, códigos de seguridad, secretos ni firmas reutilizables en la auditoría.
- Cancelar o expirar un pedido pendiente debe liberar la reserva de inventario de forma transaccional.

## Conversión compatible de estados existentes

La futura migración debe conservar `Pedido.estado` temporalmente para compatibilidad y completar los nuevos campos antes de cambiar las pantallas:

| Estado actual | Estado de pedido | Estado de pago/envío inicial |
| --- | --- | --- |
| `pendiente` sin evidencia | `pendiente_pago` | Pago `pendiente`; envío `no_preparado` al confirmar pago |
| `pendiente` con evidencia por revisar | `pendiente_pago` | Pago `en_revision` |
| `pagado` | `confirmado` | Pago `confirmado`; envío `no_preparado` |
| `enviado` | `confirmado` | Pago `confirmado`; envío `despachado` |
| `cancelado` | `cancelado` | Conservar el estado real del pago y registrar motivo de cancelación |

No inferir un pago confirmado solo porque el pedido tenga estado `pagado` si no hay un pago asociado verificable. Los casos inconsistentes se reportan para revisión, no se corrigen silenciosamente.

## Implementación del Paso 2

El esquema aditivo agrega `Pedido.estado_operativo`, `Pedido.requiere_revision_operativa` y el modelo `Envio`. Se conserva `Pedido.estado` para las pantallas y procesos existentes. Los nuevos checkouts guardan una copia de destinatario, teléfono y dirección en el envío.

La migración confirma un pedido histórico solo si la suma de pagos verificados y confirmados coincide con el total. Los pedidos históricos `pagado`/`enviado` reciben un envío marcado para revisión porque no se puede reconstruir con certeza la dirección ni la guía de ese momento. Si falta un pago verificable, el pedido queda pendiente de pago y marcado para revisión sin cambiar su estado legado. Comprobantes pendientes con referencia pasan a `en_revision`.

## Paso 3: acciones de almacén y permisos

El detalle administrativo permite actualizar estado, destinatario, teléfono, dirección, transportista, guía, URL de seguimiento e incidencia. Cada cambio de estado crea un `EnvioEvento` con actor y fecha, y también un registro de auditoría. Las operaciones exigen POST y CSRF.

Permisos asignables de Django:

- `dashboard.view_operational_orders`: ver listados y detalles de pedidos.
- `dashboard.verify_order_payments`: aprobar o rechazar pagos/pedidos.
- `dashboard.view_payment_evidence`: descargar comprobantes privados.
- `dashboard.manage_fulfillment`: actualizar preparación y seguimiento del envío.

Un rol de almacén debe recibir `view_operational_orders` y `manage_fulfillment`; estos permisos no autorizan a revisar pagos ni descargar comprobantes. Un operador de pagos necesita `view_operational_orders`, `verify_order_payments` y, si debe comprobar archivos, `view_payment_evidence`. Las rutas verifican permisos aunque se invoquen directamente; la interfaz oculta las acciones no autorizadas. Los grupos existentes que solo tienen `dashboard.view_auditlog` deben recibir los permisos operativos necesarios antes del despliegue.

`manage.py configure_operational_roles` crea de forma idempotente los grupos `FERREELECTRI - Consulta operativa`, `FERREELECTRI - Operadores de pagos` y `FERREELECTRI - Almacen`, y agrega los permisos mínimos. El comando no asigna usuarios a grupos; esa asignación debe hacerla un administrador según las funciones reales de cada cuenta.

Las transiciones manuales habilitadas son `no_preparado` → `preparando` → `listo` → `despachado` → `en_transito` → `entregado`, con `incidencia` desde cada etapa operable y regreso desde incidencia a preparación. Despachar, transitar o entregar requiere transportista y guía; las incidencias y devoluciones requieren observación. No se puede avanzar si el pedido no está confirmado o conserva una revisión operativa pendiente. `devuelto` permanece como estado del modelo, pero no tiene transición habilitada hasta definir cómo se concilia el reembolso.

## Paso 4: cola de preparación y envíos

La ruta administrativa `/admin-panel/envios/` ofrece una cola paginada con conteos de revisión, preparación, tránsito e incidencias. Permite filtrar por revisión/etapa, buscar por número de pedido, cliente, destinatario, transportista o guía, y abrir la ficha individual. El menú lateral y el resumen ejecutivo enlazan la cola para usuarios con `view_operational_orders`.

Las acciones de cambio siguen ejecutándose desde el detalle individual para conservar validación, confirmación de pago y auditoría en un solo lugar. La cola no ofrece todavía acciones masivas ni conexión automática con transportistas.

## Criterio de salida del Paso 1

Antes de implementar el cambio de esquema, revisar los casos históricos pendientes, pedidos con varios pagos, moneda usada por cada pasarela, reglas para cancelación y excepciones de despacho. La migración debe probarse sobre una copia de la base y no debe modificar ni borrar comprobantes privados.