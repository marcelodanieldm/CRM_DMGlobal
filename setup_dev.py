"""
Script de inicialización para desarrollo local.
Crea las tablas en SQLite y siembra un usuario admin y datos de prueba.
Ejecutar UNA sola vez: python setup_dev.py
"""
import os
from dotenv import load_dotenv

load_dotenv()

from database import engine, SessionLocal
from models import Base, Cliente, Servicio, Suscripcion, Usuario
from auth import hash_password

# Crear todas las tablas
Base.metadata.create_all(bind=engine)
print("[OK]Tablas creadas")

db = SessionLocal()

# ── Usuario admin ───────────────────────────────────────────────────────────
if not db.query(Usuario).filter_by(username="admin").first():
    db.add(Usuario(
        username="admin",
        email="admin@dmglobal.com",
        hashed_password=hash_password("Admin123"),
        rol="admin",
        activo=True,
    ))
    print("[OK]Usuario admin creado  (usuario: admin / contraseña: Admin123)")

if not db.query(Usuario).filter_by(username="soporte").first():
    db.add(Usuario(
        username="soporte",
        email="soporte@dmglobal.com",
        hashed_password=hash_password("Soporte123"),
        rol="soporte",
        activo=True,
    ))
    print("[OK]Usuario soporte creado  (usuario: soporte / contraseña: Soporte123)")

# ── Clientes de prueba ──────────────────────────────────────────────────────
clientes_data = [
    ("Constructora Andina S.A.",  "30712345679", "admin@andina.com",   "+54 11 4444-1111"),
    ("Tech Solutions SRL",        "30689123451", "info@techsol.com",   "+54 11 4444-2222"),
    ("Distribuidora Norte SA",    "20234567894", "ventas@norte.com",   "+54 11 4444-3333"),
    ("Inversiones Del Sur",       "27301234565", "contacto@sur.com",   "+54 11 4444-4444"),
    ("Agro Export Corp.",         "30600000028", "export@agro.com",    "+54 11 4444-5555"),
]

clientes = []
for razon, cuit, email, tel in clientes_data:
    c = db.query(Cliente).filter_by(cuit_cuil=cuit).first()
    if not c:
        c = Cliente(razon_social=razon, cuit_cuil=cuit,
                    email_contacto=email, telefono=tel, estado_general="activo")
        db.add(c)
        db.flush()
    clientes.append(c)
print(f"✓ {len(clientes_data)} clientes de prueba")

# ── Servicios ───────────────────────────────────────────────────────────────
servicios_data = [
    ("Monitoreo Web",       "Seguimiento de cambios en sitios objetivo",  150_000, "mensual",       "scraping"),
    ("Scraping de Precios", "Extracción de precios de competidores",        95_000, "mensual",       "scraping"),
    ("Reportes Automáticos","Generación diaria de reportes en PDF",        800_000, "anual",         "automatizacion"),
    ("Alertas de Stock",    "Notificaciones de quiebre de stock",           60_000, "mensual",       "bot"),
]

servicios = []
for nombre, desc, precio, tipo_eje, tipo_serv in servicios_data:
    s = db.query(Servicio).filter_by(nombre=nombre).first()
    if not s:
        s = Servicio(nombre=nombre, descripcion=desc,
                     precio_base=precio, tipo_ejecucion=tipo_eje,
                     tipo_servicio=tipo_serv, activo=True)
        db.add(s)
        db.flush()
    servicios.append(s)
print(f"✓ {len(servicios_data)} servicios de catálogo")

# ── Suscripciones de prueba ─────────────────────────────────────────────────
subs_data = [
    (0, 0, 125_000,  "activa",  "stripe"),
    (0, 1, 95_000,   "pausada", "mercadopago"),
    (1, 0, 150_000,  "activa",  "stripe"),
    (2, 0, 130_000,  "activa",  "mercadopago"),
    (2, 1, 85_000,   "pausada", "mercadopago"),
    (3, 2, 680_000,  "activa",  "manual"),
    (4, 0, 150_000,  "activa",  "stripe"),
    (4, 3, 55_000,   "activa",  "stripe"),
]
for ci, si, precio, estado, pasarela in subs_data:
    sub = Suscripcion(
        cliente_id=clientes[ci].id,
        servicio_id=servicios[si].id,
        precio_acordado=precio,
        estado_suscripcion=estado,
        pasarela_pago=pasarela,
    )
    db.add(sub)
print(f"✓ {len(subs_data)} suscripciones de prueba")

db.commit()
db.close()
print("\n✅ Base de datos lista. Iniciá el servidor con:")
print("   uvicorn main:app --reload")
