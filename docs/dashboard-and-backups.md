# Panel Ejecutivo y respaldos

## Métricas

- Ventas y facturas: facturas en estado `facturada`, comparadas con los 30 días anteriores, separadas por moneda.
- Utilidad bruta: precio neto de descuento menos costo histórico de las líneas que tienen `costo_unitario`. La cobertura indica qué proporción de líneas tiene costo histórico.
- Salud del catálogo: compara el precio actual con el costo registrado; no representa comparación con precios de competidores.
- Auditoría: visualiza eventos guardados en `AuditLog`. La auditoría actual registra accesos de vistas instrumentadas y las operaciones que escriben eventos explícitos; no equivale a un historial de cambios por campo para todos los modelos.

Las operaciones de la aplicación se guardan en PostgreSQL al confirmar cada petición. El respaldo completo diario es un punto de recuperación, no una copia continua de cada transacción. La recuperación a un instante exacto requiere habilitar y operar archivado WAL de PostgreSQL, todavía no configurado.

## Notificaciones push administrativas

Las notificaciones de pedidos usan Web Push y requieren un par VAPID estable. Genéralo localmente con el entorno del proyecto:

```powershell
@'
from base64 import urlsafe_b64encode
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid

vapid = Vapid()
vapid.generate_keys()
public_key = urlsafe_b64encode(
	vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
).rstrip(b'=').decode('ascii')
print('ADMIN_WEBPUSH_VAPID_PUBLIC_KEY=' + public_key)
print('ADMIN_WEBPUSH_VAPID_PRIVATE_KEY=' + vapid.private_pem().decode('ascii'))
'@ | .\.venv-1\Scripts\python.exe
```

Configura ambas variables en Render, junto con `ADMIN_WEBPUSH_VAPID_CONTACT=mailto:correo-administrativo@dominio.com`, y vuelve a desplegar. No publiques la clave privada ni la guardes en el repositorio. Después inicia sesión desde la aplicación instalada, activa **Notificaciones de pedidos** y acepta el permiso del navegador. Los pedidos nuevos se enviarán a las suscripciones activas de personal administrativo.

El servicio web y un Background Worker de Render deben compartir `CELERY_BROKER_URL` (o `REDIS_URL`). El comando del worker es `celery -A FERREELECTRI_PLUS worker --loglevel=info`; sin ese proceso, las tareas de notificación se encolan pero no se envían.

## Formato y verificación

Cada paquete `ferreelectri-backup-*.tar.gz` contiene:

- `database.dump`: base PostgreSQL en formato custom, apta para `pg_restore`.
- `backup-manifest.json`: motor, fecha, formato y SHA-256 del dump.
- `RESTORE.txt`: notas de recuperación.
- `media/` y `private-media/`: archivos del sistema, incluidos los comprobantes privados.

El comando `manage.py create_system_backup` verifica el contenido del paquete y la huella SHA-256. El manifiesto de estado registra también la huella del archivo. La restauración de ensayo del 9 de octubre de 2026 creó una base temporal, restauró las 52 tablas esperadas y la eliminó al terminar.

## Restauración segura

Extrae el paquete en un equipo protegido. Crea una base PostgreSQL nueva y vacía; no uses la base activa:

```powershell
createdb ferreelectri_restore
pg_restore --exit-on-error --no-owner --no-privileges --dbname=ferreelectri_restore database.dump
```

Comprueba que existan tablas de auditoría, facturas e inventario; después copia `media/` y `private-media/` a sus destinos configurados. Valida pedidos, pagos y comprobantes antes de abrir tráfico. Nunca ejecutes `pg_restore --clean` contra la base activa.

## Programación y copia externa

El instalador es `scripts/install_daily_backup_task.ps1`; registra una tarea diaria a las 02:00 y deja un marcador para el dashboard. La tarea requiere que Windows permita registrar tareas programadas. En este equipo la política de PowerShell bloqueó el script y el usuario actual recibió `Acceso denegado` al registrar la tarea; por eso el dashboard no la muestra como instalada. Debe registrarla una cuenta autorizada desde el Programador de tareas o una consola aprobada por administración.

`BACKUP_DIRECTORY` controla el almacenamiento local y `BACKUP_RETENTION_COUNT` la retención (30 por defecto). `BACKUP_MIRROR_DIRECTORY` permite una segunda copia y el proceso compara sus hashes. No se ha configurado un destino externo; los paquetes incluyen datos personales y comprobantes privados, así que configura únicamente un destino externo autorizado y protegido.
