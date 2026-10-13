from pathlib import Path

templates = {
    'c:/Users/Dell/OneDrive/Desktop/Mis proyectos/FERREELECTRI_PLUS/FERREELECTRI_PLUS/dashboard/templates/clientes.html': '''{% extends 'base/pan_con_queso.html' %}

{% block arroz_con_pollo %}
<section id="clientes">
    <div class="section-header">
        <div>
            <h2>Clientes</h2>
            <p>Resumen rápido de clientes, acceso a la lista completa y los últimos registros.</p>
        </div>
        <div class="section-actions">
            <form class="search-bar" method="get" action="{% url 'clientes' %}">
                <input type="text" name="q" placeholder="Buscar clientes..." value="{{ request.GET.q }}">
                <button type="submit" class="btn btn-primary">Buscar</button>
            </form>
            <a href="{% url 'usuarios' %}" class="btn btn-secondary">Ver todos</a>
        </div>
    </div>

    <div class="metric-grid">
        <div class="metric-card">
            <span>Nuevos</span>
            <strong>{{ clientes_nuevos }}</strong>
        </div>
        <div class="metric-card">
            <span>Frecuentes</span>
            <strong>{{ cliente_frecuente }}</strong>
        </div>
        <div class="metric-card">
            <span>VIP</span>
            <strong>{{ cliente_vip }}</strong>
        </div>
    </div>

    <div class="table-card">
        <div class="section-header" style="margin-bottom: 22px; gap: 14px;">
            <div>
                <h3>Últimos registrados</h3>
                <p>Clientes recién añadidos y su estado actual.</p>
            </div>
            <div class="action-buttons">
                <a href="{% url 'formulario' %}" class="btn btn-primary">Agregar cliente</a>
                <a href="{% url 'usuarios' %}" class="btn btn-secondary">Listado completo</a>
            </div>
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th>Nombre</th>
                    <th>Registro</th>
                    <th>Frecuencia</th>
                    <th>VIP</th>
                </tr>
            </thead>
            <tbody>
                {% if clientes %}
                    {% for c in clientes %}
                    <tr>
                        <td>{{ c.nombre }} {{ c.apellido }}</td>
                        <td>{{ c.fecha_registro }}</td>
                        <td>
                            {% if c.frecuente %}
                                <span class="badge success">Frecuente</span>
                            {% else %}
                                <span class="badge secondary">No frecuente</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if c.vip %}
                                <span class="badge info">VIP</span>
                            {% else %}
                                <span class="badge secondary">No VIP</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="4">No hay registros disponibles.</td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</section>
{% endblock %}
''',
    'c:/Users/Dell/OneDrive/Desktop/Mis proyectos/FERREELECTRI_PLUS/FERREELECTRI_PLUS/dashboard/templates/proveedores.html': '''{% extends 'base/pan_con_queso.html' %}

{% block arroz_con_pollo %}
<section id="proveedores">
    <div class="section-header">
        <div>
            <h2>Proveedores</h2>
            <p>Monitorea proveedores nuevos, busca por nombre y revisa el registro rápido.</p>
        </div>
        <div class="section-actions">
            <form class="search-bar" method="get" action="{% url 'proveedores' %}">
                <input type="text" name="q" placeholder="Buscar proveedores..." value="{{ request.GET.q }}">
                <button type="submit" class="btn btn-primary">Buscar</button>
            </form>
            <a href="{% url 'Proveedor' %}" class="btn btn-secondary">Agregar proveedor</a>
        </div>
    </div>

    <div class="metric-grid">
        <div class="metric-card">
            <span>Proveedores nuevos</span>
            <strong>{{ proveedores_nuevos }}</strong>
        </div>
        <div class="metric-card">
            <span>Últimos registros</span>
            <strong>Actualizado</strong>
        </div>
        <div class="metric-card">
            <span>Acceso</span>
            <strong>Rápido</strong>
        </div>
    </div>

    <div class="table-card">
        <div class="section-header" style="margin-bottom: 22px; gap: 14px;">
            <div>
                <h3>Registro de proveedores</h3>
                <p>Listado detallado de proveedores activos y sus datos de contacto.</p>
            </div>
            <div class="action-buttons">
                <a href="{% url 'Proveedor' %}" class="btn btn-primary">Nuevo proveedor</a>
                <a href="{% url 'formulario' %}" class="btn btn-secondary">Cerrar sesión</a>
            </div>
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th>Nombre</th>
                    <th>Cédula</th>
                    <th>Teléfono</th>
                    <th>Dirección</th>
                    <th>Email</th>
                    <th>Fecha registro</th>
                </tr>
            </thead>
            <tbody>
                {% if proveedores %}
                    {% for r in proveedores %}
                    <tr>
                        <td>{{ r.Nombre }} {{ r.Apellido }}</td>
                        <td>{{ r.Cedula }}</td>
                        <td>{{ r.Telefono }}</td>
                        <td>{{ r.Direccion }}</td>
                        <td>{{ r.Email }}</td>
                        <td>{{ r.Fecha_registro }}</td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="6">No hay registros disponibles.</td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</section>
{% endblock %}
''',
    'c:/Users/Dell/OneDrive/Desktop/Mis proyectos/FERREELECTRI_PLUS/FERREELECTRI_PLUS/dashboard/templates/inventario.html': '''{% extends 'base/pan_con_queso.html' %}

{% block arroz_con_pollo %}
<section id="inventario">
    <div class="section-header">
        <div>
            <h2>Inventario</h2>
            <p>Consulta existencias, promociones y accede rápidamente a los productos activos.</p>
        </div>
        <div class="section-actions">
            <form class="search-bar" method="get" action="{% url 'inventario' %}">
                <input type="text" name="q" placeholder="Buscar productos..." value="{{ request.GET.q }}">
                <button type="submit" class="btn btn-primary">Buscar</button>
            </form>
            <a href="{% url 'Productos' %}" class="btn btn-secondary">Agregar producto</a>
        </div>
    </div>

    <div class="metric-grid">
        <div class="metric-card">
            <span>Productos nuevos</span>
            <strong>{{ productos_nuevos }}</strong>
        </div>
        <div class="metric-card">
            <span>Promociones</span>
            <strong>{{ productos_promocion }}</strong>
        </div>
        <div class="metric-card">
            <span>Actualización</span>
            <strong>En tiempo real</strong>
        </div>
    </div>

    <div class="table-card">
        <div class="section-header" style="margin-bottom: 22px; gap: 14px;">
            <div>
                <h3>Últimos productos registrados</h3>
                <p>Visualiza rápidamente el stock, precios y promociones activas.</p>
            </div>
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th>Imagen</th>
                    <th>Código</th>
                    <th>Nombre</th>
                    <th>Precio</th>
                    <th>Cantidad</th>
                    <th>Creación</th>
                    <th>Promoción</th>
                    <th>Estado</th>
                </tr>
            </thead>
            <tbody>
                {% if productos %}
                    {% for p in productos %}
                    <tr>
                        <td style="width:72px;">
                            {% if p.Imagen %}
                                <img class="product-thumb" src="{{ p.Imagen.url }}" alt="{{ p.Nombre }}">
                            {% else %}
                                <img class="product-thumb" src="{% static 'img/no-image.svg' %}" alt="Sin imagen">
                            {% endif %}
                        </td>
                        <td>{{ p.Codigo }}</td>
                        <td>{{ p.Nombre }}</td>
                        <td>{{ p.Precio }}</td>
                        <td>{{ p.Cantidad }}</td>
                        <td>{{ p.Fecha_creacion }}</td>
                        <td>
                            {% if p.promocion == 1 %}
                                <span class="badge info">En promoción</span>
                            {% else %}
                                <span class="badge secondary">Sin promoción</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if p.Cantidad > 10 %}
                                <span class="badge success">En stock</span>
                            {% elif p.Cantidad > 0 %}
                                <span class="badge warning">Bajo stock</span>
                            {% else %}
                                <span class="badge danger">Agotado</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="8">No hay registros disponibles.</td>
                    </tr>
                {% endif %}
            </tbody>
        </table>

        <div class="pagination">
            {% if productos.has_previous %}
                <a href="?page=1">&laquo; Primera</a>
                <a href="?page={{ productos.previous_page_number }}">Anterior</a>
            {% endif %}
            <span>Página {{ productos.number }} de {{ productos.paginator.num_pages }}</span>
            {% if productos.has_next %}
                <a href="?page={{ productos.next_page_number }}">Siguiente</a>
                <a href="?page={{ productos.paginator.num_pages }}">Última &raquo;</a>
            {% endif %}
        </div>
    </div>
</section>
{% endblock %}
''',
    'c:/Users/Dell/OneDrive/Desktop/Mis proyectos/FERREELECTRI_PLUS/FERREELECTRI_PLUS/Usuario/templates/usuarios.html': '''{% extends 'base/pan_con_queso.html' %}

{% block arroz_con_pollo %}
<section class="section-panel">
    <div class="section-header">
        <div>
            <h2>Clientes</h2>
            <p>Tabla de clientes registrados con acciones de edición, eliminación y exportación.</p>
        </div>
        <div class="action-buttons">
            <a href="{% url 'addUser' %}" class="btn btn-primary">Registrar cliente</a>
            <a href="{% url 'reporte_clientes_pdf' %}" class="btn btn-secondary">Reporte PDF</a>
            <a href="{% url 'reporte_clientes_excel' %}" class="btn btn-secondary">Reporte Excel</a>
        </div>
    </div>

    {% if messages %}
    <div class="alert-banner alert-success">
        {% for m in messages %}
            {{ m }}
        {% endfor %}
    </div>
    {% endif %}

    <div class="table-card">
        <table class="data-table">
            <thead>
                <tr>
                    <th>Cliente</th>
                    <th>Cédula</th>
                    <th>Teléfono</th>
                    <th>Dirección</th>
                    <th>Email</th>
                    <th>Fecha nacimiento</th>
                    <th>Registro</th>
                    <th>Acciones</th>
                </tr>
            </thead>
            <tbody>
                {% if clientes %}
                    {% for c in clientes %}
                    <tr>
                        <td>{{ c.nombre }} {{ c.apellido }}</td>
                        <td>{{ c.cedula }}</td>
                        <td>{{ c.telefono }}</td>
                        <td>{{ c.direccion }}</td>
                        <td>{{ c.email }}</td>
                        <td>{{ c.fecha_nacimiento }}</td>
                        <td>{{ c.fecha_registro }}</td>
                        <td>
                            <div class="action-buttons">
                                {% if perms.Usuario.change_cliente %}
                                <a href="{% url 'updtUser' c.id %}" class="btn btn-outline btn-view">Actualizar</a>
                                {% endif %}
                                {% if perms.Usuario.delete_cliente %}
                                <a href="{% url 'dltUser' c.id %}" class="btn btn-outline btn-delete">Eliminar</a>
                                {% endif %}
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="8">No hay clientes registrados.</td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</section>
{% endblock %}
'''
}
