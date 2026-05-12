import os
from datetime import date
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
import models
from auth import hash_password

# Import all routers
from routers import (
    auth, users, customers, products, cost_prices,
    pricing_rules, quotations, invoices, dashboard,
    analytics, reports, audit_trail, settings, jobs,
    payment_accounts, payments,
)


# ─── DB Init & Seed ──────────────────────────────────────────────────────────

def init_db():
    Base.metadata.create_all(bind=engine)


def seed_defaults(db: Session):
    # Default admin user
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    if not admin:
        admin = models.User(
            username="admin",
            email="admin@foodstuff.store",
            full_name="System Administrator",
            hashed_password=hash_password("admin123"),
            role=models.UserRole.admin,
        )
        db.add(admin)
        db.flush()

    # Default pricing rules
    if db.query(models.PricingRule).count() == 0:
        today = date.today()
        rules = [
            models.PricingRule(
                rule_name="Supply Markup",
                rule_type=models.PricingRuleType.supply,
                markup_percentage=5.0,
                is_active=True,
                effective_date=today,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            models.PricingRule(
                rule_name="Delivery Markup",
                rule_type=models.PricingRuleType.delivery,
                markup_percentage=3.0,
                is_active=True,
                effective_date=today,
                created_by=admin.id,
                updated_by=admin.id,
            ),
            models.PricingRule(
                rule_name="Net 30 Markup",
                rule_type=models.PricingRuleType.payment_term,
                markup_percentage=3.5,
                payment_term_code="net_30",
                is_active=True,
                effective_date=today,
                created_by=admin.id,
                updated_by=admin.id,
            ),
        ]
        db.add_all(rules)

    # Default app settings
    defaults = [
        ("company_name", "Foodstuff Store", "Company display name"),
        ("company_address", "", "Company address"),
        ("company_email", "", "Company email"),
        ("company_phone", "", "Company phone"),
        ("invoice_prefix", "INV", "Invoice number prefix"),
        ("quotation_prefix", "QUO", "Quotation number prefix"),
        ("currency", "NGN", "Currency code"),
        ("currency_symbol", "₦", "Currency symbol"),
        ("paystack_enabled", "false", "Enable Paystack payment links (true/false)"),
        ("payment_link_expiry_hours", "24", "Hours before a Paystack payment link expires"),
    ]
    for key, value, desc in defaults:
        if not db.query(models.AppSetting).filter(models.AppSetting.key == key).first():
            db.add(models.AppSetting(key=key, value=value, description=desc))

    db.commit()


# ─── App Lifespan ─────────────────────────────────────────────────────────────

def run_migrations():
    """Idempotent schema migrations that run on every startup."""
    from sqlalchemy import text
    from database import DATABASE_URL
    with engine.connect() as conn:
        if DATABASE_URL.startswith("postgresql"):
            conn.execute(text(
                "ALTER TABLE invoices ALTER COLUMN quotation_id DROP NOT NULL"
            ))
            conn.execute(text(
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS custom_pdf_s3_key VARCHAR(255)"
            ))
            conn.execute(text("ALTER TYPE invoicestatus ADD VALUE IF NOT EXISTS 'completed'"))
            conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'accountant'"))
            conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'operations'"))
            conn.execute(text(
                "ALTER TABLE product_categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"
            ))
            conn.execute(text(
                "ALTER TABLE quotations ADD COLUMN IF NOT EXISTS delivery_fee NUMERIC(15,2) DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS delivery_fee NUMERIC(15,2) DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE quotation_items ADD COLUMN IF NOT EXISTS discount_pct NUMERIC(6,3) NOT NULL DEFAULT 0"
            ))
            conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        run_migrations()
    except Exception:
        pass  # ignore if column already nullable or table doesn't exist yet
    db: Session = SessionLocal()
    try:
        seed_defaults(db)
    finally:
        db.close()
    yield


# ─── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Foodstuff Store — Quotation & Invoicing API",
    version="1.0.0",
    description=(
        "Internal API for creating quotations and invoices from cost-based pricing rules. "
        "Quotation approval is required before invoice creation."
    ),
    lifespan=lifespan,
)

_cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else [
        "https://invoicing.foodstuff.store",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
)
_allow_credentials = "*" not in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────────────────

PREFIX = "/api/v1"

app.include_router(auth.router,          prefix=PREFIX)
app.include_router(users.router,         prefix=PREFIX)
app.include_router(customers.router,     prefix=PREFIX)
app.include_router(products.router,      prefix=PREFIX)
app.include_router(cost_prices.router,   prefix=PREFIX)
app.include_router(pricing_rules.router, prefix=PREFIX)
app.include_router(quotations.router,    prefix=PREFIX)
app.include_router(invoices.router,      prefix=PREFIX)
app.include_router(dashboard.router,     prefix=PREFIX)
app.include_router(analytics.router,     prefix=PREFIX)
app.include_router(reports.router,       prefix=PREFIX)
app.include_router(audit_trail.router,       prefix=PREFIX)
app.include_router(settings.router,          prefix=PREFIX)
app.include_router(jobs.router,              prefix=PREFIX)
app.include_router(payment_accounts.router,  prefix=PREFIX)
app.include_router(payments.router,          prefix=PREFIX)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "Foodstuff Store API is running"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
