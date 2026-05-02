from __future__ import annotations
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator

from models import UserRole, DeliveryType, QuotationStatus, InvoiceStatus, PricingRuleType, PaymentMethod, PaymentStatus


# ─── Common ──────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[Any]


class MessageResponse(BaseModel):
    message: str


class BulkIdsRequest(BaseModel):
    ids: List[int]


class BulkDeleteResult(BaseModel):
    deleted: int = 0
    failed: List[dict] = Field(default_factory=list)


# ─── Auth ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: UserRole


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


# ─── Users ───────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    password: str
    role: UserRole = UserRole.sales


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


# ─── Product Categories ───────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    is_active: bool = True


class MarketOut(CategoryOut):
    pass


# ─── Customers ───────────────────────────────────────────────────────────────

class CustomerCreate(BaseModel):
    customer_name: str
    business_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    default_delivery: DeliveryType = DeliveryType.pickup
    default_payment_term: str = "immediate"


class CustomerUpdate(BaseModel):
    customer_name: Optional[str] = None
    business_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    default_delivery: Optional[DeliveryType] = None
    default_payment_term: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_name: str
    business_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    category: Optional[str] = None
    default_delivery: DeliveryType
    default_payment_term: str
    is_active: bool
    created_at: datetime
    last_order_date: Optional[date] = None


class CustomerDetailOut(CustomerOut):
    total_sales_value: float = 0
    total_quantity_bought: float = 0
    total_orders: int = 0
    average_order_value: float = 0
    last_order_date: Optional[date] = None
    preferred_payment_term: Optional[str] = None
    preferred_delivery_type: Optional[str] = None
    cost_of_sales: float = 0


# ─── Products ────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    product_name: str
    sku: Optional[str] = None
    unit_of_measure: Optional[str] = None
    category_id: Optional[int] = None
    market_id: Optional[int] = None


class ProductUpdate(BaseModel):
    product_name: Optional[str] = None
    sku: Optional[str] = None
    unit_of_measure: Optional[str] = None
    category_id: Optional[int] = None
    market_id: Optional[int] = None
    is_active: Optional[bool] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_name: str
    sku: Optional[str] = None
    unit_of_measure: Optional[str] = None
    category_id: Optional[int] = None
    category: Optional[CategoryOut] = None
    market_id: Optional[int] = None
    market: Optional[MarketOut] = None
    market_name: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    current_cost_price: Optional[float] = None
    cost_price_effective_date: Optional[date] = None


class ProductListPage(BaseModel):
    """Paginated product list from GET /products."""

    total: int
    skip: int
    limit: int
    items: List[ProductOut]


# ─── Cost Prices ─────────────────────────────────────────────────────────────

class CostPriceCreate(BaseModel):
    product_id: int
    cost_price: Decimal
    effective_date: date
    notes: Optional[str] = None


class CostPriceUpdate(BaseModel):
    cost_price: Optional[Decimal] = None
    effective_date: Optional[date] = None
    notes: Optional[str] = None


class CostPriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    cost_price: Decimal
    effective_date: date
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime


class BulkCostPriceRow(BaseModel):
    sku: str
    cost_price: Decimal
    effective_date: date
    notes: Optional[str] = None


# ─── Pricing Rules ───────────────────────────────────────────────────────────

class PricingRuleCreate(BaseModel):
    rule_name: str
    rule_type: PricingRuleType
    markup_percentage: Decimal
    payment_term_code: Optional[str] = None
    effective_date: Optional[date] = None
    is_active: bool = True


class PricingRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    markup_percentage: Optional[Decimal] = None
    payment_term_code: Optional[str] = None
    effective_date: Optional[date] = None
    is_active: Optional[bool] = None


class PricingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_name: str
    rule_type: PricingRuleType
    markup_percentage: Decimal
    payment_term_code: Optional[str] = None
    is_active: bool
    effective_date: Optional[date] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    updated_at: datetime


# ─── Quotations ──────────────────────────────────────────────────────────────

class QuotationItemCreate(BaseModel):
    product_id: int
    quantity: Decimal
    uom: Optional[str] = None
    unit_price_override: Optional[Decimal] = None  # if set, skips markup calculation


class QuotationCreate(BaseModel):
    customer_id: int
    quotation_date: date
    delivery_type: DeliveryType
    payment_term: str
    notes: Optional[str] = None
    items: List[QuotationItemCreate]


class QuotationUpdate(BaseModel):
    delivery_type: Optional[DeliveryType] = None
    payment_term: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[QuotationItemCreate]] = None


class QuotationRejectRequest(BaseModel):
    reason: str


class PricePreviewRequest(BaseModel):
    product_id: int
    quantity: Decimal
    delivery_type: DeliveryType
    payment_term: str


class PricePreviewResponse(BaseModel):
    product_id: int
    product_name: str
    quantity: float
    cost_price: float
    supply_markup_pct: float
    supply_markup_amount: float
    delivery_markup_pct: float
    delivery_markup_amount: float
    payment_term_markup_pct: float
    payment_term_markup_amount: float
    unit_price: float
    line_total: float


class QuotationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product: Optional[ProductOut] = None
    product_name: Optional[str] = None   # flat convenience from model property
    quantity: Decimal
    uom: Optional[str] = None
    cost_price: Decimal
    supply_markup_pct: Decimal
    supply_markup_amount: Decimal
    delivery_markup_pct: Decimal
    delivery_markup_amount: Decimal
    payment_term_markup_pct: Decimal
    payment_term_markup_amount: Decimal
    unit_price: Decimal
    line_total: Decimal


class QuotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quotation_number: str
    customer_id: int
    customer: Optional[CustomerOut] = None
    customer_name: Optional[str] = None      # flat from model property
    quotation_date: date
    delivery_type: DeliveryType
    payment_term: str
    status: QuotationStatus
    notes: Optional[str] = None
    total_amount: Decimal
    created_by: int
    creator: Optional[UserOut] = None
    created_by_name: Optional[str] = None    # flat from model property
    approved_by: Optional[int] = None
    approver: Optional[UserOut] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: List[QuotationItemOut] = []


# ─── Invoices ────────────────────────────────────────────────────────────────

class InvoiceItemCreate(BaseModel):
    product_id: int
    quantity: Decimal
    uom: Optional[str] = None
    unit_price: Decimal  # selling price (user-provided or from calculate-price)


class InvoiceCreate(BaseModel):
    customer_id: int
    invoice_date: date
    due_date: Optional[date] = None
    payment_term: str = "cash"
    delivery_type: str = "pickup"
    notes: Optional[str] = None
    items: List[InvoiceItemCreate]


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product: Optional[ProductOut] = None
    product_name: Optional[str] = None      # flat from model property
    quantity: Decimal
    uom: Optional[str] = None
    cost_price: Decimal
    supply_markup_pct: Decimal
    supply_markup_amount: Decimal
    delivery_markup_pct: Decimal
    delivery_markup_amount: Decimal
    payment_term_markup_pct: Decimal
    payment_term_markup_amount: Decimal
    unit_price: Decimal
    line_total: Decimal


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_number: str
    quotation_id: Optional[int] = None
    customer_id: int
    customer: Optional[CustomerOut] = None
    customer_name: Optional[str] = None      # flat from model property
    invoice_date: date
    payment_term: str
    due_date: Optional[date] = None
    delivery_type: DeliveryType
    status: InvoiceStatus
    notes: Optional[str] = None
    total_amount: Decimal
    amount_paid: Decimal = Decimal("0")
    custom_pdf_s3_key: Optional[str] = None
    created_by: int
    creator: Optional[UserOut] = None
    created_at: datetime
    updated_at: datetime
    items: List[InvoiceItemOut] = []
    quotation: Optional[QuotationOut] = None


# ─── Dashboard ───────────────────────────────────────────────────────────────

class DashboardOverview(BaseModel):
    quotations_today: int
    invoices_today: int
    sales_today: float
    sales_this_week: float
    sales_this_month: float
    active_customers: int
    products_sold_today: float
    cost_of_sales_this_month: float = 0
    cost_of_sales_all_time: float = 0
    top_customers: List[dict]
    top_products: List[dict]
    delivery_vs_pickup: dict
    sales_by_payment_term: dict
    recent_invoices: List[dict]
    recent_quotations: List[dict]


# ─── Analytics ───────────────────────────────────────────────────────────────

class SalesAnalytics(BaseModel):
    total_sales_value: float
    total_invoices: int
    total_quotations: int
    quotation_conversion_rate: float
    average_invoice_value: float
    top_customers: List[dict]
    top_products: List[dict]
    top_markets: List[dict] = []
    top_categories: List[dict]
    sales_by_delivery_type: dict
    sales_by_payment_term: dict
    sales_by_staff: List[dict]
    daily_trend: List[dict]
    monthly_trend: List[dict]


class CustomerBehaviorOut(BaseModel):
    customer_id: int
    customer_name: str
    top_products: List[dict]
    purchase_frequency_days: Optional[float]
    total_orders: int
    total_value: float
    last_order_date: Optional[date]
    is_inactive_30_days: bool
    month_over_month_change_pct: Optional[float]


class ProductAnalyticsOut(BaseModel):
    product_id: int
    product_name: str
    total_quantity_sold: float
    total_revenue: float
    total_customers: int
    total_invoices: int
    top_customers: List[dict]
    monthly_trend: List[dict]


class StaffPerformanceOut(BaseModel):
    user_id: int
    full_name: str
    username: str
    quotations_created: int
    invoices_created: int
    total_sales_value: float
    conversion_rate: float


# ─── Comprehensive Stats ─────────────────────────────────────────────────────

class QuotationStats(BaseModel):
    total: int
    draft: int
    pending_approval: int
    approved: int
    rejected: int
    converted: int
    approval_rate: float          # approved / submitted
    rejection_rate: float         # rejected / submitted
    conversion_rate: float        # converted / approved
    total_value: float


class InvoiceStats(BaseModel):
    total: int
    active: int
    partially_paid: int
    paid: int
    cancelled: int
    paid_rate: float              # paid / total non-cancelled
    cancel_rate: float            # cancelled / total
    total_billed: float
    total_collected: float
    total_outstanding: float
    collection_rate: float        # collected / billed (non-cancelled)


class PaymentStats(BaseModel):
    total: int
    pending: int
    confirmed: int
    voided: int
    failed: int
    total_amount: float
    confirmed_amount: float
    pending_amount: float


class SalesPersonStats(BaseModel):
    user_id: int
    full_name: str
    username: str
    role: str
    # Quotation breakdown
    quotations_total: int
    quotations_draft: int
    quotations_pending: int
    quotations_approved: int
    quotations_rejected: int
    quotations_converted: int
    quotation_approval_rate: float
    quotation_conversion_rate: float
    # Invoice breakdown
    invoices_total: int
    invoices_paid: int
    invoices_partially_paid: int
    invoices_active: int
    invoices_cancelled: int
    total_billed: float
    total_collected: float
    total_outstanding: float
    collection_rate: float
    avg_invoice_value: float


class ManagerStats(BaseModel):
    user_id: int
    full_name: str
    username: str
    # Approval activity
    reviewed_total: int           # approved + rejected
    approved_count: int
    rejected_count: int
    approval_rate: float
    rejection_rate: float
    # Revenue from approved deals
    revenue_approved: float
    # Top sales people they manage (by revenue)
    top_sales: List[dict]


class ComprehensiveStats(BaseModel):
    quotations: QuotationStats
    invoices: InvoiceStats
    payments: PaymentStats
    by_sales_person: List[SalesPersonStats]
    by_manager: List[ManagerStats]
    # Cross-dimensional
    revenue_by_role: dict         # role → total billed
    top_customers_revenue: List[dict]
    top_products_revenue: List[dict]


# ─── Audit ───────────────────────────────────────────────────────────────────

class AuditTrailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    user_id: Optional[int] = None
    user: Optional[UserOut] = None
    description: Optional[str] = None
    old_values: Optional[str] = None
    new_values: Optional[str] = None
    timestamp: datetime


# ─── Background Jobs ─────────────────────────────────────────────────────────

class JobEnqueuedResponse(BaseModel):
    task_id: str
    status: str = "queued"
    message: str


class JobStatusResponse(BaseModel):
    task_id: str
    status: str          # PENDING | STARTED | SUCCESS | FAILURE | RETRY
    download_url: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class QueueEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    event_type: str
    title: str
    requested_by: Optional[int] = None
    metadata_json: Optional[str] = None
    created_at: datetime
    status: Optional[str] = None
    error: Optional[str] = None
    delivery_outcomes: Optional[List[dict]] = None


# ─── Settings ────────────────────────────────────────────────────────────────

class SettingUpdate(BaseModel):
    key: str
    value: str


class SettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Optional[str] = None
    description: Optional[str] = None
    updated_at: Optional[datetime] = None


# ─── Payment Accounts ────────────────────────────────────────────────────────

class PaymentAccountCreate(BaseModel):
    account_name: str
    bank_name: str
    account_number: str
    account_type: str = "current"
    description: Optional[str] = None
    is_default: bool = False


class PaymentAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class PaymentAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_name: str
    bank_name: str
    account_number: str
    account_type: str
    description: Optional[str] = None
    is_active: bool
    is_default: bool
    created_by: Optional[int] = None
    created_at: datetime


# ─── Payments ────────────────────────────────────────────────────────────────

class BankTransferPaymentCreate(BaseModel):
    invoice_id: int
    amount: Decimal
    payment_account_id: int
    payment_date: date
    payer_name: Optional[str] = None
    notes: Optional[str] = None


class PaystackInitRequest(BaseModel):
    invoice_id: int
    amount: Optional[Decimal] = None   # defaults to invoice balance_due


class PaystackSendLinkRequest(BaseModel):
    payment_id: int


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    invoice_number: Optional[str] = None    # flat from model property
    amount: Decimal
    payment_method: PaymentMethod
    payment_account_id: Optional[int] = None
    payment_account: Optional[PaymentAccountOut] = None
    payer_name: Optional[str] = None
    paystack_reference: Optional[str] = None
    paystack_payment_url: Optional[str] = None
    payment_date: Optional[date] = None
    status: PaymentStatus
    notes: Optional[str] = None
    recorded_by: Optional[int] = None
    confirmed_by: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime


class InvoicePaymentSummary(BaseModel):
    invoice_id: int
    invoice_number: str
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    payment_status: str
    payments: List[PaymentOut] = []
