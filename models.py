import enum
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import (
    Column, Integer, String, Numeric, Boolean, DateTime,
    Date, Text, ForeignKey, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import relationship

from database import Base


# ─── Enumerations ────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin = "admin"
    manager = "manager"
    sales = "sales"
    analyst = "analyst"
    accountant = "accountant"
    operations = "operations"


class DeliveryType(str, enum.Enum):
    delivery = "delivery"
    pickup = "pickup"


class QuotationStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    converted = "converted"


class InvoiceStatus(str, enum.Enum):
    active = "active"
    partially_paid = "partially_paid"
    paid = "paid"
    cancelled = "cancelled"


class PricingRuleType(str, enum.Enum):
    supply = "supply"
    delivery = "delivery"
    payment_term = "payment_term"


class PaymentMethod(str, enum.Enum):
    bank_transfer = "bank_transfer"
    paystack = "paystack"
    cash = "cash"
    cheque = "cheque"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    failed = "failed"
    voided = "voided"


class AuditAction(str, enum.Enum):
    create = "create"
    update = "update"
    delete = "delete"
    approve = "approve"
    reject = "reject"
    convert = "convert"
    submit = "submit"
    cancel = "cancel"
    login = "login"
    deactivate = "deactivate"
    confirm = "confirm"
    void = "void"


class AuditEntity(str, enum.Enum):
    user = "user"
    customer = "customer"
    product = "product"
    cost_price = "cost_price"
    pricing_rule = "pricing_rule"
    quotation = "quotation"
    invoice = "invoice"
    setting = "setting"
    payment = "payment"
    payment_account = "payment_account"


# ─── Models ──────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(200), unique=True, nullable=False, index=True)
    full_name = Column(String(200), nullable=False)
    hashed_password = Column(String(500), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.sales)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_quotations = relationship("Quotation", foreign_keys="Quotation.created_by", back_populates="creator")
    approved_quotations = relationship("Quotation", foreign_keys="Quotation.approved_by", back_populates="approver")
    created_invoices = relationship("Invoice", back_populates="creator")
    audit_logs = relationship("AuditTrail", back_populates="user")


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(200), nullable=False)
    business_name = Column(String(200))
    phone = Column(String(50))
    email = Column(String(200))
    address = Column(Text)
    city = Column(String(100))
    category = Column(String(100))
    default_delivery = Column(SAEnum(DeliveryType), default=DeliveryType.pickup)
    default_payment_term = Column(String(50), default="immediate")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    quotations = relationship("Quotation", back_populates="customer")
    invoices = relationship("Invoice", back_populates="customer")


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_name = Column(String(200), nullable=False)
    sku = Column(String(100), unique=True)
    unit_of_measure = Column(String(50))
    category_id = Column(Integer, ForeignKey("product_categories.id"))
    image_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("ProductCategory", back_populates="products")
    cost_prices = relationship(
        "CostPrice", back_populates="product",
        order_by="CostPrice.effective_date.desc()"
    )
    quotation_items = relationship("QuotationItem", back_populates="product")
    invoice_items = relationship("InvoiceItem", back_populates="product")


class CostPrice(Base):
    __tablename__ = "cost_prices"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    cost_price = Column(Numeric(15, 2), nullable=False)
    effective_date = Column(Date, nullable=False)
    notes = Column(Text)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="cost_prices")
    creator = relationship("User")


class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String(200), nullable=False)
    rule_type = Column(SAEnum(PricingRuleType), nullable=False)
    markup_percentage = Column(Numeric(6, 3), nullable=False)
    # only for payment_term type
    payment_term_code = Column(String(50))
    is_active = Column(Boolean, default=True)
    effective_date = Column(Date)
    created_by = Column(Integer, ForeignKey("users.id"))
    updated_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class Quotation(Base):
    __tablename__ = "quotations"

    id = Column(Integer, primary_key=True, index=True)
    quotation_number = Column(String(50), unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    quotation_date = Column(Date, nullable=False)
    delivery_type = Column(SAEnum(DeliveryType), nullable=False)
    payment_term = Column(String(50), nullable=False)
    status = Column(SAEnum(QuotationStatus), default=QuotationStatus.draft)
    notes = Column(Text)
    total_amount = Column(Numeric(15, 2), default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    rejection_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="quotations")
    creator = relationship("User", foreign_keys=[created_by], back_populates="created_quotations")
    approver = relationship("User", foreign_keys=[approved_by], back_populates="approved_quotations")
    items = relationship("QuotationItem", back_populates="quotation", cascade="all, delete-orphan")
    invoice = relationship("Invoice", back_populates="quotation", uselist=False)

    # Convenience flat properties (consumed by Pydantic via from_attributes)
    @property
    def customer_name(self):
        return self.customer.customer_name if self.customer else None

    @property
    def created_by_name(self):
        return self.creator.full_name if self.creator else None


class QuotationItem(Base):
    __tablename__ = "quotation_items"

    id = Column(Integer, primary_key=True, index=True)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(15, 3), nullable=False)
    uom = Column(String(50), nullable=True)
    # Pricing snapshot
    cost_price = Column(Numeric(15, 2), nullable=False)
    supply_markup_pct = Column(Numeric(6, 3), nullable=False)
    supply_markup_amount = Column(Numeric(15, 2), nullable=False)
    delivery_markup_pct = Column(Numeric(6, 3), default=0)
    delivery_markup_amount = Column(Numeric(15, 2), default=0)
    payment_term_markup_pct = Column(Numeric(6, 3), default=0)
    payment_term_markup_amount = Column(Numeric(15, 2), default=0)
    unit_price = Column(Numeric(15, 2), nullable=False)
    line_total = Column(Numeric(15, 2), nullable=False)

    quotation = relationship("Quotation", back_populates="items")
    product = relationship("Product", back_populates="quotation_items")

    @property
    def product_name(self):
        return self.product.product_name if self.product else None


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(50), unique=True, nullable=False)
    quotation_id = Column(Integer, ForeignKey("quotations.id"), unique=True, nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    invoice_date = Column(Date, nullable=False)
    payment_term = Column(String(50), nullable=False)
    due_date = Column(Date)
    delivery_type = Column(SAEnum(DeliveryType), nullable=False)
    status = Column(SAEnum(InvoiceStatus), default=InvoiceStatus.active)
    notes = Column(Text)
    total_amount = Column(Numeric(15, 2), default=0)
    amount_paid = Column(Numeric(15, 2), default=0)
    custom_pdf_s3_key = Column(String(255), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    quotation = relationship("Quotation", back_populates="invoice")
    customer = relationship("Customer", back_populates="invoices")
    creator = relationship("User", back_populates="created_invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice")

    @property
    def customer_name(self):
        return self.customer.customer_name if self.customer else None


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Numeric(15, 3), nullable=False)
    uom = Column(String(50), nullable=True)
    cost_price = Column(Numeric(15, 2), nullable=False)
    supply_markup_pct = Column(Numeric(6, 3), nullable=False)
    supply_markup_amount = Column(Numeric(15, 2), nullable=False)
    delivery_markup_pct = Column(Numeric(6, 3), default=0)
    delivery_markup_amount = Column(Numeric(15, 2), default=0)
    payment_term_markup_pct = Column(Numeric(6, 3), default=0)
    payment_term_markup_amount = Column(Numeric(15, 2), default=0)
    unit_price = Column(Numeric(15, 2), nullable=False)
    line_total = Column(Numeric(15, 2), nullable=False)

    invoice = relationship("Invoice", back_populates="items")
    product = relationship("Product", back_populates="invoice_items")

    @property
    def product_name(self):
        return self.product.product_name if self.product else None


class PaymentAccount(Base):
    """Bank/payment accounts saved in settings for receiving customer payments."""
    __tablename__ = "payment_accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_name = Column(String(200), nullable=False)   # Name on the bank account
    bank_name = Column(String(200), nullable=False)
    account_number = Column(String(50), nullable=False)
    account_type = Column(String(50), default="current")  # savings / current
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    updated_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])
    payments = relationship("Payment", back_populates="payment_account")


class Payment(Base):
    """Payment records against invoices (bank transfer or Paystack)."""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    amount = Column(Numeric(15, 2), nullable=False)
    payment_method = Column(SAEnum(PaymentMethod), nullable=False)
    # ── Bank-transfer fields ──────────────────────────────────────────────────
    payment_account_id = Column(Integer, ForeignKey("payment_accounts.id"))
    payer_name = Column(String(200))           # name of customer/sender
    # ── Paystack fields ──────────────────────────────────────────────────────
    paystack_reference = Column(String(200), unique=True)
    paystack_access_code = Column(String(200))
    paystack_payment_url = Column(String(500))
    # ── Common ───────────────────────────────────────────────────────────────
    payment_date = Column(Date)
    status = Column(SAEnum(PaymentStatus), default=PaymentStatus.pending)
    notes = Column(Text)
    recorded_by = Column(Integer, ForeignKey("users.id"))
    confirmed_by = Column(Integer, ForeignKey("users.id"))
    confirmed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    invoice = relationship("Invoice", back_populates="payments")
    payment_account = relationship("PaymentAccount", back_populates="payments")
    recorder = relationship("User", foreign_keys=[recorded_by])
    confirmer = relationship("User", foreign_keys=[confirmed_by])

    @property
    def invoice_number(self):
        return self.invoice.invoice_number if self.invoice else None


class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(SAEnum(AuditAction), nullable=False)
    entity_type = Column(SAEnum(AuditEntity), nullable=False)
    entity_id = Column(Integer)
    user_id = Column(Integer, ForeignKey("users.id"))
    description = Column(Text)
    old_values = Column(Text)   # JSON
    new_values = Column(Text)   # JSON
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")


class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    description = Column(String(300))
    updated_by = Column(Integer, ForeignKey("users.id"))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    updater = relationship("User")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(100), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class QueueEvent(Base):
    __tablename__ = "queue_events"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(100), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    requester = relationship("User")
