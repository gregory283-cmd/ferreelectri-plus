from decimal import Decimal

from django.db import models
from django.utils import timezone

from Usuario.models import Clientes
from Ventas.models import Factura


class CuentaCobro(models.Model):
    factura = models.OneToOneField(Factura, on_delete=models.CASCADE, related_name="cuenta_cxc")
    cliente = models.ForeignKey(Clientes, on_delete=models.CASCADE)
    created = models.DateTimeField(auto_now_add=True)

    ESTADOS = (
        ("activa", "Activa"),
        ("cerrada", "Cerrada"),
        ("anulada", "Anulada"),
    )
    estado = models.CharField(max_length=10, choices=ESTADOS, default="activa")

    class Meta:
        verbose_name = "Cuenta por cobrar (CxC)"
        verbose_name_plural = "Cuentas por cobrar (CxC)"

    def __str__(self) -> str:
        return f"CxC Factura #{self.factura.numero} - {self.cliente.cedula}"


class PagoCxC(models.Model):
    METODOS = (
        ("efectivo", "Efectivo"),
        ("pago_movil", "Pago móvil"),
        ("transferencia", "Transferencia"),
        ("otro", "Otro"),
    )

    cuenta = models.ForeignKey(CuentaCobro, on_delete=models.CASCADE, related_name="pagos")
    metodo = models.CharField(max_length=20, choices=METODOS, default="efectivo")

    referencia = models.CharField(max_length=120, blank=True, default="")
    banco = models.CharField(max_length=120, blank=True, default="")
    fecha_pago = models.DateTimeField(default=timezone.now)

    monto = models.DecimalField(max_digits=12, decimal_places=2)

    ESTADOS = (
        ("registrado", "Registrado"),
        ("anulado", "Anulado"),
    )
    estado = models.CharField(max_length=10, choices=ESTADOS, default="registrado")

    nota = models.TextField(blank=True, default="")

    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_pago"]

    def __str__(self) -> str:
        return f"Pago {self.monto} ({self.metodo}) - Factura #{self.cuenta.factura.numero}"


class ReversionPagoCxC(models.Model):
    pago = models.OneToOneField(PagoCxC, on_delete=models.CASCADE, related_name="reversion")
    motivo = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversiones_pagos_cxc",
    )

    def __str__(self) -> str:
        return f"Reversión de PagoCxC #{self.pago.id}"


def saldo_factura_total(cuenta: CuentaCobro) -> Decimal:
    return Decimal(cuenta.factura.total or 0)


def saldo_pagado(cuenta: CuentaCobro) -> Decimal:
    total = Decimal("0")
    for p in cuenta.pagos.all():
        if p.estado == "registrado":
            total += Decimal(p.monto or 0)
    return total


def saldo_pendiente(cuenta: CuentaCobro) -> Decimal:
    return saldo_factura_total(cuenta) - saldo_pagado(cuenta)
