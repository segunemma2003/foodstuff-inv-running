# Foodstuff Store — Quotation & Invoicing API

Internal REST API (FastAPI) for managing customers, products, cost prices, pricing rules, quotations, invoices and payments.

- **Base URL:** `/api/v1` (all paths below are relative to this unless marked otherwise)
- **Interactive docs:** `/docs` (Swagger UI) and `/redoc`, served by the running app
- **Content type:** `application/json` unless noted (file uploads use `multipart/form-data`)

---

## Table of Contents

1. [Conventions](#conventions)
2. [Roles & Permissions](#roles--permissions)
3. [Health](#health)
4. [Auth](#auth)
5. [Users](#users)
6. [Customers](#customers)
7. [Products, Categories & Markets](#products-categories--markets)
8. [Cost Prices](#cost-prices)
9. [Pricing Rules](#pricing-rules)
10. [Quotations](#quotations)
11. [Invoices](#invoices)
12. [Payment Accounts](#payment-accounts)
13. [Payments](#payments)
14. [Dashboard](#dashboard)
15. [Analytics](#analytics)
16. [Reports](#reports)
17. [Background Jobs](#background-jobs)
18. [Audit Trail](#audit-trail)
19. [Settings](#settings)
20. [Custom Orders](#custom-orders)
21. [Enums](#enums)
22. [Pricing Model](#pricing-model)
23. [Errors](#errors)
24. [Environment Variables](#environment-variables)

---

## Conventions

### Authentication
Every endpoint except `/auth/login`, `/auth/forgot-password`, `/auth/reset-password`, `/invoices/template`, the Paystack webhook and the health checks requires a JWT bearer token:

```
Authorization: Bearer <access_token>
```

Tokens are HS256 JWTs and expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default **480** minutes / 8 hours). An inactive user's token is rejected with `401`.

### Money
**All monetary values are integers in kobo** (₦1 = 100 kobo). For example, `850000` = ₦8,500.00. This applies to cost prices, unit prices, line totals, fees, invoice totals and payment amounts.

### Dates
- Dates: `YYYY-MM-DD`
- Datetimes: ISO 8601 (`2026-10-23T14:05:00`)

### Pagination
List endpoints take `skip` (offset) and `limit` query params. Most return a plain JSON array. Products and invoices return a page object instead:

```json
{ "total": 312, "skip": 0, "limit": 50, "items": [ ... ] }
```

### Background jobs
Heavy work (bulk uploads, report generation, PDF generation) returns `202 Accepted` with:

```json
{ "task_id": "c1f3...", "status": "queued", "message": "..." }
```

Poll [`GET /jobs/{task_id}`](#background-jobs) until `status` is `SUCCESS` or `FAILURE`, then fetch any output file from `GET /jobs/{task_id}/download`.

### Bulk delete
Bulk-delete endpoints take `{ "ids": [1, 2, 3] }` and return:

```json
{ "deleted": 2, "failed": [ { "id": 3, "reason": "..." } ] }
```

### Simple message response
```json
{ "message": "Human-readable result" }
```

---

## Roles & Permissions

Roles: `admin`, `manager`, `sales`, `analyst`, `accountant`, `operations`.

Each endpoint below lists the roles it accepts. **Any** means any authenticated, active user. Short names used in this document:

| Label | Roles |
|---|---|
| **Any** | Any authenticated user |
| **Admin** | `admin` |
| **Admin/Manager** | `admin`, `manager` |
| **Admin/Manager/Ops** | `admin`, `manager`, `operations` |
| **Not analyst** | `admin`, `manager`, `sales` |
| **Customer managers** | `admin`, `manager`, `sales`, `operations` |
| **Product creators** | `admin`, `manager`, `sales`, `operations` |
| **Market viewers** | `admin`, `manager`, `sales`, `analyst`, `operations` |
| **Report roles** | `admin`, `manager`, `analyst` |

> Note: "Not analyst" does **not** include `accountant` or `operations`. It is exactly `admin`, `manager` and `sales`.

A role failure returns `403` with `"Access denied. Required role(s): ..."`.

---

## Health

These are mounted at the root, not under `/api/v1`.

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/` | None | `{"status": "ok", "message": "Foodstuff Store API is running"}` |
| GET | `/health` | None | `{"status": "healthy"}` |

---

## Auth

### POST `/auth/login`
**Auth:** None. **Body:** `application/x-www-form-urlencoded` (OAuth2 password form).

| Field | Type | Required |
|---|---|---|
| `username` | string | yes |
| `password` | string | yes |

```bash
curl -X POST https://<host>/api/v1/auth/login \
  -d "username=admin&password=secret"
```

**200**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "admin",
  "role": "admin"
}
```

### GET `/auth/me`
**Auth:** Any. Returns the current user (`UserOut`).

### POST `/auth/change-password`
**Auth:** Any. Changes the caller's own password.
```json
{ "current_password": "old", "new_password": "new", "send_email": true }
```

### POST `/auth/forgot-password`
**Auth:** None. Sends a reset link by email.
```json
{ "email": "user@example.com" }
```

### POST `/auth/reset-password`
**Auth:** None. Completes a reset using the token from the email.
```json
{ "token": "<reset-token>", "new_password": "new" }
```

---

## Users

**UserOut**
```json
{
  "id": 3, "username": "jdoe", "email": "jdoe@example.com",
  "full_name": "Jane Doe", "role": "sales", "is_active": true,
  "created_at": "2026-05-01T09:00:00"
}
```

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users` | Admin/Manager | List users. Query: `skip`, `limit` (50), `role`, `is_active` |
| POST | `/users` | Admin | Create user |
| GET | `/users/{user_id}` | Admin/Manager | Get user |
| PUT | `/users/{user_id}` | Admin | Update user |
| DELETE | `/users/{user_id}` | Admin | Deactivate user (soft delete) |
| POST | `/users/{user_id}/reset-password` | Admin | Set a new password for a user |
| POST | `/users/{user_id}/change-password` | Admin | Same body and behaviour as reset-password |

**Create body**
```json
{
  "username": "jdoe", "email": "jdoe@example.com", "full_name": "Jane Doe",
  "password": "secret", "role": "sales"
}
```
`role` defaults to `sales`.

**Update body** (all optional): `email`, `full_name`, `role`, `is_active`.

**Reset/change password body**
```json
{ "new_password": "secret", "send_email": true }
```

---

## Customers

**CustomerOut**
```json
{
  "id": 12, "customer_name": "Ade Foods", "business_name": "Ade Foods Ltd",
  "phone": "08012345678", "email": "ade@example.com", "address": "1 Market Rd",
  "city": "Lagos", "category": "Restaurant",
  "default_delivery": "pickup", "default_payment_term": "immediate",
  "credit_limit": 0, "is_active": true,
  "created_at": "2026-03-10T10:00:00", "last_order_date": "2026-10-20"
}
```

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/customers` | Any | List. Query: `skip`, `limit` (50), `search`, `category`, `is_active` |
| GET | `/customers/dropdown` | Any | Minimal list for selects: `[{id, customer_name, business_name}]` |
| POST | `/customers` | Customer managers | Create |
| GET | `/customers/{customer_id}` | Any | Get one |
| PUT | `/customers/{customer_id}` | Customer managers | Update |
| DELETE | `/customers/{customer_id}` | Admin | Delete. Returns `400` if the customer has any invoices or quotations |
| GET | `/customers/{customer_id}/quotations` | Any | Query: `skip`, `limit` (20). Returns `QuotationOut[]` |
| GET | `/customers/{customer_id}/invoices` | Any | Query: `skip`, `limit` (200), `date_from`, `date_to`. Returns `InvoiceOut[]` |
| GET | `/customers/{customer_id}/analytics` | Any | `CustomerOut` plus totals (see below) |
| GET | `/customers/{customer_id}/top-products` | Any | Query: `limit` (10), `date_from`, `date_to` |
| GET | `/customers/{customer_id}/cost-of-sales` | Any | Query: `date_from`, `date_to` |
| POST | `/customers/bulk-update` | Customer managers | CSV bulk update (see below) |

**Create body**
```json
{
  "customer_name": "Ade Foods",
  "phone": "08012345678",
  "business_name": "Ade Foods Ltd",
  "email": "ade@example.com",
  "address": "1 Market Rd",
  "city": "Lagos",
  "category": "Restaurant",
  "default_delivery": "pickup",
  "default_payment_term": "immediate",
  "credit_limit": 0
}
```
Required: `customer_name`, `phone`. The update body takes the same fields, all optional, plus `is_active`.

**Analytics extra fields:** `total_sales_value`, `total_quantity_bought`, `total_orders`, `average_order_value`, `preferred_payment_term`, `preferred_delivery_type`, `cost_of_sales`.

### POST `/customers/bulk-update`
`multipart/form-data` with field `file` (a CSV file, UTF-8, BOM allowed).

- Each row is matched to an existing customer by `email`, then `phone`, then `customer_name` (case-insensitive).
- Columns that can be updated: `customer_name`, `business_name`, `phone`, `email`, `address`, `city`, `category`, `default_delivery`, `default_payment_term`.
- Empty cells are ignored, so they never overwrite existing values.

**200**
```json
{ "updated": 40, "not_found": 2, "skipped": 1, "errors": ["Row 7: no match for ..."] }
```
At most the first 20 errors are returned.

---

## Products, Categories & Markets

**ProductOut**
```json
{
  "id": 55, "product_name": "Rice (50kg)", "sku": "RICE-50",
  "unit_of_measure": "bag",
  "category_id": 2, "category": { "id": 2, "name": "Grains", "description": null, "is_active": true },
  "market_id": 1, "market": { "id": 1, "name": "Mile 12", "description": null, "is_active": true },
  "market_name": "Mile 12",
  "image_url": "https://...", "is_active": true,
  "created_at": "2026-01-05T08:00:00",
  "current_cost_price": 6500000, "cost_price_effective_date": "2026-10-01"
}
```

### Categories
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/products/categories` | Market viewers | List categories |
| POST | `/products/categories` | Admin/Manager/Ops | Create. Body: `{ "name": "...", "description": "..." }` |
| PUT | `/products/categories/{category_id}` | Admin/Manager | Update. Body (all optional): `name`, `description`, `is_active` |
| DELETE | `/products/categories/{category_id}` | Admin | Delete. Returns `204` |

### Markets
Markets use the same request and response shapes as categories.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/products/markets` | Market viewers | List markets |
| POST | `/products/markets` | Admin/Manager/Ops | Create |
| PUT | `/products/markets/{market_id}` | Admin/Manager/Ops | Update |
| DELETE | `/products/markets/{market_id}` | Admin/Manager/Ops | Delete. Returns `204` |
| POST | `/products/markets/{market_id}/disable` | Admin/Manager/Ops | Disable |
| POST | `/products/markets/{market_id}/enable` | Admin/Manager/Ops | Enable |

### Products
| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/products` | Any | Paginated list (`items`, `total`). Query: `skip`, `limit` (50), `search`, `category_id`, `market_id`, `is_active`, `include_inactive` (default `false`) |
| POST | `/products` | Product creators | Create |
| GET | `/products/{product_id}` | Any | Get one |
| PUT | `/products/{product_id}` | Product creators | Update |
| POST | `/products/{product_id}/disable` | Product creators | Deactivate |
| POST | `/products/{product_id}/enable` | Product creators | Reactivate |
| DELETE | `/products/{product_id}` | Admin | Delete |
| GET | `/products/{product_id}/variants` | Any | Same product name in the same market with a different unit: `[{id, product_name, unit_of_measure, sku}]`. Used to pick a UOM on quotations |
| GET | `/products/{product_id}/cost-history` | Any | `CostPriceOut[]` |
| GET | `/products/{product_id}/analytics` | Any | `product_id`, `product_name`, `total_quantity_sold`, `total_revenue`, `total_customers`, `total_invoices`, `top_customers`, `monthly_trend` |
| POST | `/products/{product_id}/image` | Not analyst | Upload image (`multipart/form-data`, field `file`) |
| DELETE | `/products/{product_id}/image` | Not analyst | Remove image |
| GET | `/products/template` | Any | Excel template for bulk upload (see the note below) |
| POST | `/products/bulk-upload` | Admin/Manager/Ops | `multipart/form-data`: `file` (Excel), optional `market_id`. Returns `202` with a job |

**Create body**
```json
{ "product_name": "Rice (50kg)", "sku": "RICE-50", "unit_of_measure": "bag", "category_id": 2, "market_id": 1 }
```
Only `product_name` is required. The update body takes the same fields, all optional, plus `is_active`.

> ⚠️ **Known issue:** `GET /products/template` is declared after `GET /products/{product_id}`. As a result, the request currently matches the `{product_id}` route and returns `422`. The fix is to move the template route above `/{product_id}` in `routers/products.py`.

---

## Cost Prices

**CostPriceOut**
```json
{
  "id": 901, "product_id": 55, "cost_price": 6500000,
  "effective_date": "2026-10-01", "notes": null,
  "created_by": 1, "created_at": "2026-10-01T07:30:00"
}
```

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/cost-prices` | Any | Query: `product_id`, `skip`, `limit` (100) |
| POST | `/cost-prices` | Admin/Manager/Ops | Add a cost price |
| PUT | `/cost-prices/{cp_id}` | Admin/Manager/Ops | Update. Body (all optional): `cost_price`, `effective_date`, `notes` |
| POST | `/cost-prices/bulk-upload` | Admin/Manager/Ops | Excel upload. Returns `202` with a job |
| GET | `/cost-prices/template` | Any | Download the Excel template |

**Create body**
```json
{ "product_id": 55, "cost_price": 6500000, "effective_date": "2026-10-01", "notes": "New supplier" }
```

**Bulk upload columns (required):** `product_name`, `uom`, `market_name`, `cost_price`.
- The effective date is set to today.
- Rows with a missing required field are skipped.
- Scanning stops after three blank rows in a row.
- Existing products are never moved to a different market.

---

## Pricing Rules

**PricingRuleOut**
```json
{
  "id": 1, "rule_name": "Supply Markup", "rule_type": "supply",
  "markup_percentage": "5.0", "payment_term_code": null,
  "is_active": true, "effective_date": "2026-01-01",
  "created_by": 1, "updated_by": 1,
  "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"
}
```

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/pricing-rules` | Any | Query: `is_active`, `rule_type` |
| POST | `/pricing-rules` | Admin/Manager/Ops | Create |
| GET | `/pricing-rules/{rule_id}` | Any | Get one |
| PUT | `/pricing-rules/{rule_id}` | Admin/Manager/Ops | Update. Body (all optional): `rule_name`, `markup_percentage`, `payment_term_code`, `effective_date`, `is_active` |
| DELETE | `/pricing-rules/{rule_id}` | Admin | Delete |
| POST | `/pricing-rules/bulk-delete` | Admin | Bulk delete |

**Create body**
```json
{
  "rule_name": "Net 30 Markup",
  "rule_type": "payment_term",
  "markup_percentage": 3.5,
  "payment_term_code": "net_30",
  "effective_date": "2026-10-23",
  "is_active": true
}
```

**Rules enforced on create:**
- `payment_term` rules require `payment_term_code`. Missing it returns `400`.
- Only **one active** `supply` rule and **one active** `delivery` rule may exist at a time. Creating a second one returns `400`.
- Only one active `payment_term` rule may exist per `payment_term_code`.
- `other` rules have no such limit. They add on top of the other markups (cash back, promotions and similar). See [Pricing Model](#pricing-model).

**Seeded payment-term codes:** `immediate`, `net_3`, `net_5`, `net_7`, `net_15`, `net_30`, `net_45`, `net_60`, `net_90`.

---

## Quotations

Lifecycle: `draft` → `pending_approval` → `approved` | `rejected` → `converted` (once turned into an invoice).

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/quotations/calculate-price` | Any | Preview line pricing without saving anything |
| GET | `/quotations` | Any | List (`QuotationListOut[]`). Query: `skip`, `limit` (50), `status`, `customer_id`, `created_by`, `date_from`, `date_to` |
| POST | `/quotations` | Not analyst | Create (status `draft`) |
| GET | `/quotations/{quotation_id}` | Any | Full quotation with items |
| PUT | `/quotations/{quotation_id}` | Not analyst | Update. Lines are repriced when items, payment term, delivery type or WHT change |
| DELETE | `/quotations/{quotation_id}` | Admin | Delete |
| POST | `/quotations/bulk-delete` | Admin | Bulk delete |
| POST | `/quotations/{quotation_id}/submit` | Not analyst | `draft` → `pending_approval` |
| POST | `/quotations/{quotation_id}/approve` | Admin/Manager/Ops | Approve |
| POST | `/quotations/{quotation_id}/reject` | Admin/Manager/Ops | Reject. Body: `{ "reason": "..." }` |
| GET | `/quotations/{quotation_id}/pdf` | Any | Download PDF |
| POST | `/quotations/{quotation_id}/generate-pdf` | Any | Generate the PDF in the background. Returns `202` with a job |
| POST | `/quotations/{quotation_id}/send-to-customer` | Not analyst | Email the quotation to the customer |
| POST | `/quotations/{quotation_id}/upload-to-make` | Not analyst | Push to the Make automation. Body: `{ "additional_emails": ["a@b.com"] }` (optional) |
| POST | `/quotations/{quotation_id}/convert-to-invoice` | Not analyst | Create an invoice from an approved quotation. Returns `InvoiceOut` |

### POST `/quotations/calculate-price`
**Body:** an array of lines.
```json
[
  { "product_id": 55, "quantity": 10, "delivery_type": "delivery", "payment_term": "net_30", "apply_wht": false }
]
```
**200**
```json
[
  {
    "product_id": 55, "product_name": "Rice (50kg)", "quantity": 10.0,
    "cost_price": 6500000,
    "supply_markup_pct": 5.0, "supply_markup_amount": 325000,
    "delivery_markup_pct": 3.0, "delivery_markup_amount": 195000,
    "payment_term_markup_pct": 3.5, "payment_term_markup_amount": 227500,
    "wht_markup_pct": 0.0, "wht_markup_amount": 0,
    "unit_price": 7247500, "line_total": 72475000
  }
]
```

### POST `/quotations`
```json
{
  "customer_id": 12,
  "quotation_date": "2026-10-23",
  "delivery_type": "delivery",
  "payment_term": "net_30",
  "notes": "Deliver before noon",
  "delivery_fee": 500000,
  "apply_handling_charge": true,
  "apply_vat": false,
  "apply_wht": false,
  "other_rule_ids": [7],
  "items": [
    { "product_id": 55, "quantity": 10, "uom": "bag", "unit_price_override": null, "discount_pct": 2.5 }
  ]
}
```
- `unit_price_override` (kobo): if set, the server uses this price and skips the markup calculation for that line.
- `discount_pct`: a percentage discount applied after the unit price is calculated.
- `other_rule_ids`: **inactive** `other` pricing rules to apply to this quotation only. See [Pricing Model](#pricing-model).

**Update body** (all optional): `delivery_type`, `payment_term`, `notes`, `apply_wht`, `other_rule_ids`, `items`.

**QuotationOut** (abridged)
```json
{
  "id": 88, "quotation_number": "QUO-000088",
  "customer_id": 12, "customer": { "...": "CustomerOut" }, "customer_name": "Ade Foods",
  "quotation_date": "2026-10-23", "delivery_type": "delivery", "payment_term": "net_30",
  "status": "draft", "notes": "...",
  "delivery_fee": 500000,
  "handling_charge_enabled": true, "handling_charge_amount": 3623750,
  "vat_enabled": false, "vat_amount": 0,
  "wht_enabled": false,
  "extra_charges": [ { "rule_id": 7, "name": "Promo", "pct": 1.0, "amount": 724750 } ],
  "extra_charges_amount": 724750,
  "total_amount": 77323500,
  "created_by": 3, "creator": { "...": "UserOut" }, "created_by_name": "Jane Doe",
  "approved_by": null, "approver": null, "approved_at": null, "rejection_reason": null,
  "created_at": "...", "updated_at": "...",
  "items": [
    {
      "id": 1, "product_id": 55, "product": { "...": "ProductOut" }, "product_name": "Rice (50kg)",
      "quantity": "10", "uom": "bag", "cost_price": 6500000,
      "supply_markup_pct": "5", "supply_markup_amount": 325000,
      "delivery_markup_pct": "3", "delivery_markup_amount": 195000,
      "payment_term_markup_pct": "3.5", "payment_term_markup_amount": 227500,
      "discount_pct": "0", "unit_price": 7247500, "line_total": 72475000
    }
  ]
}
```
`QuotationListOut` has the same top-level fields but leaves out `customer`, `creator`, `approver`, `approved_by`, `rejection_reason` and `items`.

---

## Invoices

Statuses: `active`, `partially_paid`, `paid`, `completed`, `cancelled`. Payment status updates automatically as payments are confirmed.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/invoices/approved-quotations` | Any | Approved quotations that can be converted. Query: `customer_id` |
| GET | `/invoices` | Any | Paginated list (`items`, `total`). Query: `skip`, `limit` (50), `customer_id`, `status`, `created_by`, `date_from`, `date_to`, `payment_term`, `delivery_type` |
| POST | `/invoices` | Not analyst | Create an invoice directly, without a quotation |
| GET | `/invoices/{invoice_id}` | Any | Full invoice |
| PUT | `/invoices/{invoice_id}` | Admin | Edit an invoice |
| DELETE | `/invoices/{invoice_id}` | Any | Delete |
| POST | `/invoices/bulk-delete` | Any | Bulk delete |
| POST | `/invoices/{invoice_id}/cancel` | Admin/Manager | Cancel |
| GET | `/invoices/{invoice_id}/pdf` | Any | Download the invoice PDF (an uploaded custom PDF if one exists) |
| GET | `/invoices/{invoice_id}/signed-pdf` | Any | Download the signed copy |
| GET | `/invoices/{invoice_id}/cost-of-sales/pdf` | Any | Download the cost-of-sales PDF for this invoice |
| POST | `/invoices/{invoice_id}/generate-pdf` | Any | Generate the PDF in the background. Returns `202` with a job |
| POST | `/invoices/{invoice_id}/upload-pdf` | Any | Replace the generated PDF with your own. `multipart/form-data`: `file`, optional `additional_emails` (comma-separated string) |
| DELETE | `/invoices/{invoice_id}/upload-pdf` | Any | Remove the custom PDF |
| POST | `/invoices/{invoice_id}/upload-signed` | Any | Upload a signed copy. `multipart/form-data`: `file`, optional `additional_emails` |
| POST | `/invoices/{invoice_id}/send-email` | Any | Email the invoice. Body: `{ "additional_emails": ["a@b.com"] }` (optional) |
| POST | `/invoices/{invoice_id}/upload-to-make` | Any | Push to the Make automation. Same body as send-email |
| GET | `/invoices/template` | **None** | Excel template for bulk upload |
| POST | `/invoices/bulk-upload` | Not analyst | Excel upload. Returns `202` with a job |

### POST `/invoices`
```json
{
  "customer_id": 12,
  "invoice_date": "2026-10-23",
  "due_date": "2026-11-22",
  "payment_term": "net_30",
  "delivery_type": "pickup",
  "notes": null,
  "apply_handling_charge": true,
  "apply_wht": false,
  "other_rule_ids": [],
  "items": [
    { "product_id": 55, "quantity": 10, "uom": "bag", "unit_price": null }
  ]
}
```
- `payment_term` defaults to `cash` and `delivery_type` defaults to `pickup`.
- Item `unit_price` (kobo) is optional. If omitted, the server calculates it from the cost price plus markups. `unit_price_override` is accepted as an alias.
- At least one item is required.

**Update body** (Admin; all optional): `customer_id`, `invoice_date`, `due_date`, `payment_term`, `delivery_type`, `notes`, `apply_handling_charge`, `apply_wht`, `other_rule_ids`, `items`. Changing `apply_wht` reprices every line from its cost price.

**InvoiceOut** has the same fields as `QuotationOut`, with these differences:
- Uses `invoice_number`, `invoice_date` and `due_date`.
- Adds `quotation_id`, `quotation` (the source `QuotationOut`, if any), `amount_paid` and `custom_pdf_s3_key`.
- Has no approval or rejection fields.

`InvoiceListOut` (in list `items`) is the light version: no nested `customer`, `creator`, `items` or `quotation`.

### Bulk upload columns
Download the template with `GET /invoices/template`.

| Column | Required | Notes |
|---|---|---|
| `invoice_number` | no | Leave blank to auto-generate. Rows with the same value become one invoice |
| `customer_name` | yes | Must match an existing customer (case-insensitive) |
| `invoice_date` | yes | `YYYY-MM-DD` |
| `due_date` | no | `YYYY-MM-DD` |
| `payment_term` | no | `cash`, `immediate`, `net_7`, `net_14`, `net_30`, `net_45`, `net_60`, `net_90`. Default `cash` |
| `delivery_type` | no | `delivery` or `pickup`. Default `pickup` |
| `product_name` | yes | Must match an existing product (case-insensitive) |
| `qty` | yes | Must be greater than 0 |
| `unit_price` | yes | Numbers only |
| `notes` | no | |

---

## Payment Accounts

These are the company's own bank accounts that customers pay into.

**PaymentAccountOut**
```json
{
  "id": 1, "account_name": "Foodstuff Store Ltd", "bank_name": "GTBank",
  "account_number": "0123456789", "account_type": "current",
  "description": null, "is_active": true, "is_default": true,
  "created_by": 1, "created_at": "..."
}
```

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/payment-accounts` | Any | Query: `active_only` (default `true`) |
| POST | `/payment-accounts` | Admin/Manager | Create. Setting `is_default: true` removes the default flag from the previous default account |
| GET | `/payment-accounts/{account_id}` | Any | Get one |
| PUT | `/payment-accounts/{account_id}` | Admin/Manager | Update. Body (all optional): any create field plus `is_active` |
| DELETE | `/payment-accounts/{account_id}` | Admin | Deactivate (soft delete). Returns the account |

**Create body**
```json
{
  "account_name": "Foodstuff Store Ltd", "bank_name": "GTBank",
  "account_number": "0123456789", "account_type": "current",
  "description": "Main collections", "is_default": true
}
```

---

## Payments

**PaymentOut**
```json
{
  "id": 7, "invoice_id": 42, "invoice_number": "INV-000042",
  "amount": "20000000", "payment_method": "bank_transfer",
  "payment_account_id": 1, "payment_account": { "...": "PaymentAccountOut" },
  "payer_name": "Ade Foods",
  "paystack_reference": null, "paystack_payment_url": null,
  "payment_date": "2026-10-23", "status": "pending", "notes": "Trf ref ADE001",
  "recorded_by": 3, "confirmed_by": null, "confirmed_at": null,
  "created_at": "..."
}
```

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/payments` | Any | Query: `invoice_id`, `status`, `payment_method`, `skip`, `limit` (50) |
| GET | `/payments/{payment_id}` | Any | Get one |
| GET | `/payments/{payment_id}/receipt` | Any | Download the receipt PDF |
| GET | `/payments/invoice/{invoice_id}/summary` | Any | Balance summary for an invoice (see below) |
| POST | `/payments/bank-transfer` | Any | Record a bank transfer. Status starts as `pending` |
| PUT | `/payments/{payment_id}/confirm` | Admin/Manager | Confirm a payment. Recalculates `amount_paid` and status on the invoice |
| PUT | `/payments/{payment_id}/void` | Admin/Manager | Void a payment |
| DELETE | `/payments/{payment_id}` | Admin | Delete |
| POST | `/payments/bulk-delete` | Admin | Bulk delete |
| POST | `/payments/paystack/initialize` | Any | Create a Paystack payment link |
| POST | `/payments/paystack/send-link` | Any | Email the Paystack link to the customer. Body: `{ "payment_id": 7 }` |
| GET | `/payments/paystack/verify/{reference}` | Any | Check a Paystack transaction and confirm the payment if it succeeded |
| POST | `/payments/paystack/webhook` | Paystack signature | Paystack callback. Verified with the `x-paystack-signature` header. Hidden from Swagger |

### POST `/payments/bank-transfer`
```json
{
  "invoice_id": 42,
  "amount": 20000000,
  "payment_account_id": 1,
  "payment_date": "2026-10-23",
  "payer_name": "Ade Foods",
  "notes": "Trf ref ADE001"
}
```
`amount` must be greater than 0.

### POST `/payments/paystack/initialize`
```json
{ "invoice_id": 42, "amount": null }
```
- `amount` defaults to the invoice's outstanding balance and cannot be more than that balance.
- The customer must have an email address.
- The invoice must not be cancelled or already paid.

### GET `/payments/invoice/{invoice_id}/summary`
```json
{
  "invoice_id": 42, "invoice_number": "INV-000042",
  "total_amount": "77323500", "amount_paid": "20000000", "balance_due": "57323500",
  "payment_status": "partially_paid",
  "payments": [ { "...": "PaymentOut" } ]
}
```

### Payment flows
**Bank transfer:**
1. Staff record the transfer with `POST /payments/bank-transfer` (status `pending`).
2. An admin or manager checks the bank alert and calls `PUT /payments/{id}/confirm`.
3. The invoice status updates and a confirmation email is sent.

**Paystack:**
1. Create the link with `POST /payments/paystack/initialize`.
2. Email it with `POST /payments/paystack/send-link`.
3. The customer pays.
4. Paystack calls the webhook. You can also call `GET /payments/paystack/verify/{reference}` to check manually.
5. The payment is confirmed and the invoice status updates.

---

## Dashboard

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/dashboard/overview` | Any | Headline KPIs (see below) |
| GET | `/dashboard/cost-of-sales` | Any | Cost-of-sales detail. Query: `date_from`, `date_to`, `customer_id`, `product_id` |
| GET | `/dashboard/cost-of-sales/pdf` | Any | Same filters. Returns `cost_of_sales.pdf` |
| POST | `/dashboard/cost-of-sales/email` | Any | Queue an email of the cost-of-sales report |
| POST | `/dashboard/cost-of-sales/upload-to-make` | Any | Same as the email endpoint (goes to the Make recipients) |
| GET | `/dashboard/queue-events` | Any | Recent background-job events. Query: `limit` (50, max 200), `event_type` |

**Overview fields:**
- Counts and totals: `quotations_today`, `invoices_today`, `sales_today`, `sales_this_week`, `sales_this_month`, `active_customers`, `products_sold_today`, `cost_of_sales_this_month`, `cost_of_sales_all_time`
- Lists: `top_customers`, `top_products`, `recent_invoices`, `recent_quotations`
- Breakdowns: `delivery_vs_pickup`, `sales_by_payment_term`

**Cost-of-sales email body**
```json
{
  "date_from": "2026-10-01", "date_to": "2026-10-23",
  "customer_id": null, "product_id": null,
  "additional_emails": ["finance@example.com"]
}
```

**QueueEventOut:** `id`, `task_id`, `event_type`, `title`, `requested_by`, `metadata_json`, `created_at`, `status`, `error`, `delivery_outcomes`.

---

## Analytics

All endpoints accept **Any** role.

| Method | Path | Query params | Returns |
|---|---|---|---|
| GET | `/analytics/sales` | `date_from`, `date_to`, `customer_id`, `product_id`, `category_id`, `market_id`, `delivery_type`, `payment_term`, `staff_id` | `SalesAnalytics` |
| GET | `/analytics/customer-behavior` | `customer_id`, `category_id`, `market_id`, `inactive_days` (30), `limit` (200) | `CustomerBehaviorOut[]` |
| GET | `/analytics/product-sales` | `date_from`, `date_to`, `category_id`, `market_id`, `delivery_type`, `payment_term`, `limit` (50) | Product sales rows |
| GET | `/analytics/staff-performance` | `date_from`, `date_to`, `user_id`, `category_id`, `market_id` | `StaffPerformanceOut[]` |
| GET | `/analytics/comprehensive` | `date_from`, `date_to`, `category_id`, `market_id` | `ComprehensiveStats` |

**SalesAnalytics fields:**
- Totals: `total_sales_value`, `total_invoices`, `total_quotations`, `quotation_conversion_rate`, `average_invoice_value`
- Top lists: `top_customers`, `top_products`, `top_markets`, `top_categories`
- Breakdowns: `sales_by_delivery_type`, `sales_by_payment_term`, `sales_by_staff`
- Trends: `daily_trend`, `monthly_trend`

**CustomerBehaviorOut:** `customer_id`, `customer_name`, `top_products`, `purchase_frequency_days`, `total_orders`, `total_value`, `last_order_date`, `is_inactive_30_days`, `month_over_month_change_pct`.

**StaffPerformanceOut:** `user_id`, `full_name`, `username`, `quotations_created`, `invoices_created`, `total_sales_value`, `conversion_rate`.

**ComprehensiveStats:**
- `quotations`: counts by status, plus approval, rejection and conversion rates and total value
- `invoices`: counts by status, plus billed, collected and outstanding totals and rates
- `payments`: counts and amounts by status
- `by_sales_person[]`: quotation and invoice breakdown for each salesperson
- `by_manager[]`: approve/reject activity, `revenue_approved` and `top_sales` for each manager
- `revenue_by_role`, `top_customers_revenue`, `top_products_revenue`

---

## Reports

Every report runs in the background and produces an `.xlsx` file. **Auth:** Report roles (`admin`, `manager`, `analyst`). All parameters are **query params**, and every endpoint returns `202` with a job.

| Method | Path | Query params |
|---|---|---|
| POST | `/reports/sales` | `date_from`, `date_to`, `customer_id`, `payment_term`, `delivery_type` |
| POST | `/reports/invoices` | `date_from`, `date_to` |
| POST | `/reports/quotations` | `date_from`, `date_to`, `status` |
| POST | `/reports/customer-sales` | `date_from`, `date_to` |
| POST | `/reports/product-sales` | `date_from`, `date_to` |
| POST | `/reports/cost-price-history` | `date_from`, `date_to` |
| POST | `/reports/staff-performance` | `date_from`, `date_to` |

```bash
TASK=$(curl -s -X POST "https://<host>/api/v1/reports/sales?date_from=2026-10-01&date_to=2026-10-23" \
  -H "Authorization: Bearer $TOKEN" | jq -r .task_id)
curl -s "https://<host>/api/v1/jobs/$TASK" -H "Authorization: Bearer $TOKEN"
curl -L -o sales.xlsx "https://<host>/api/v1/jobs/$TASK/download" -H "Authorization: Bearer $TOKEN"
```

---

## Background Jobs

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/jobs/{task_id}` | Any | Job status |
| GET | `/jobs/{task_id}/download` | Any | Redirects to a presigned S3 URL for the output file. The URL is valid for 1 hour |

**JobStatusResponse**
```json
{
  "task_id": "c1f3...",
  "status": "SUCCESS",
  "download_url": "https://...",
  "result": { "...": "task-specific" },
  "error": null
}
```
`status` is one of `PENDING`, `STARTED`, `SUCCESS`, `FAILURE`, `RETRY`.

---

## Audit Trail

### GET `/audit-trail`
**Auth:** Admin/Manager.

**Query params:** `skip`, `limit` (100), `entity_type`, `entity_id`, `user_id`, `action`, `date_from`, `date_to` (datetimes).

```json
[
  {
    "id": 501, "action": "update", "entity_type": "customer", "entity_id": 12,
    "user_id": 3, "user": { "...": "UserOut" },
    "description": "Bulk CSV update",
    "old_values": "{\"city\": \"Ikeja\"}", "new_values": "{\"city\": \"Lagos\"}",
    "timestamp": "2026-10-23T10:12:00"
  }
]
```
`old_values` and `new_values` are JSON-encoded strings. See [Enums](#enums) for the values of `action` and `entity_type`.

---

## Settings

These are key/value app settings. Seeded keys:
- Company details: `company_name`, `company_address`, `company_email`, `company_phone`
- Document numbering: `invoice_prefix`, `quotation_prefix`
- Currency: `currency`, `currency_symbol`
- Paystack: `paystack_enabled`, `payment_link_expiry_hours`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/settings` | Any | List all settings |
| GET | `/settings/{key}` | Any | Get one setting |
| PUT | `/settings/{key}` | Admin/Manager | Update one. Body: `{ "key": "company_name", "value": "Foodstuff Store" }` |
| PUT | `/settings` | Admin/Manager | Bulk update. Body: an array of `{ key, value }` |
| POST | `/settings/test-email` | Admin/Manager | Send a test email to check SMTP. Body: `{ "to": "me@example.com" }` |

**SettingOut:** `key`, `value`, `description`, `updated_at`.

---

## Custom Orders

These endpoints pass requests through to the main Foodstuff Store API (`FOODSTUFF_API_URL` + `/api/internal/ni/procurement`), authenticating with `FOODSTUFF_API_KEY`. **Auth:** `admin`, `manager`, `sales`.

| Method | Path | Description |
|---|---|---|
| GET | `/custom-orders` | List. Query: `skip` (≥0), `limit` (1–100, default 20), `status`. Returns `{ "items": [...], "total": n }` |
| POST | `/custom-orders/{req_id}/approve` | Accept an order (it moves to sourcing). Body: `{ "notes": "..." }` (optional) |
| POST | `/custom-orders/{req_id}/reject` | Reject an order. Body: `{ "reason": "..." }` (required, non-empty) |

**How errors are handled:**
- If the integration is not configured, the list endpoint returns an empty list and approve/reject return `503`.
- If the main API returns `401` or `403`, the list endpoint returns an empty list instead of an error. This stops staff from being logged out.
- If the main API is unreachable, all three return `503`.
- If the main API returns a `5xx` error, all three return `502`.

---

## Enums

| Enum | Values |
|---|---|
| `UserRole` | `admin`, `manager`, `sales`, `analyst`, `accountant`, `operations` |
| `DeliveryType` | `delivery`, `pickup` |
| `QuotationStatus` | `draft`, `pending_approval`, `approved`, `rejected`, `converted` |
| `InvoiceStatus` | `active`, `partially_paid`, `paid`, `completed`, `cancelled` |
| `PricingRuleType` | `supply`, `delivery`, `payment_term`, `other` |
| `PaymentMethod` | `bank_transfer`, `paystack`, `cash`, `cheque` |
| `PaymentStatus` | `pending`, `confirmed`, `failed`, `voided` |
| `AuditAction` | `create`, `update`, `delete`, `approve`, `reject`, `convert`, `submit`, `cancel`, `login`, `deactivate`, `confirm`, `void` |
| `AuditEntity` | `user`, `customer`, `product`, `cost_price`, `pricing_rule`, `quotation`, `invoice`, `setting`, `payment`, `payment_account` |

---

## Pricing Model

### Line items
Each line's unit price is built from the product's current cost price:

```
unit_price = cost_price
           + supply markup                  (always)
           + delivery markup                (only when delivery_type = "delivery")
           + payment-term markup            (rule matching payment_term)
           + every ACTIVE "other" rule      (added on top of the rules above)
           + WHT 5.4%                       (only when apply_wht = true; included in the unit price)
line_total = unit_price × quantity, then minus discount_pct
```
- All markups are calculated on the cost price.
- Amounts are rounded to the nearest kobo.
- A line that has `unit_price_override` (quotations) or `unit_price` (invoices) uses that price and skips this calculation.

### Document totals
These charges are added once, on the document subtotal (the sum of the line totals):

| Charge | When it applies | Rate |
|---|---|---|
| Handling charge | `apply_handling_charge` (default `true`) | 5% of the subtotal |
| VAT | `apply_vat` (quotations) | 7.5% of the subtotal |
| Delivery fee | `delivery_fee` (quotations) | A fixed amount in kobo |
| Individual "other" charges | `other_rule_ids` | Each rule's % of the subtotal |

### Global vs individual "other" rules
- An **active** `other` rule is global. It is applied automatically to every line on every document.
- An **inactive** `other` rule is applied only where it is listed in a document's `other_rule_ids`. It is charged once on the subtotal and listed in `extra_charges` as `{rule_id, name, pct, amount}`.
- Only inactive rules can be attached to a single document. This stops a rule from being charged twice.
- The amounts are saved with the document, so editing the rule later does not change totals on existing documents.

---

## Errors

All errors use this format:
```json
{ "detail": "Human-readable error message" }
```
Validation errors (`422`) return FastAPI's standard list in `detail`.

| Status | Meaning |
|---|---|
| `400` | Bad request: a business rule was broken or the input is invalid |
| `401` | The token is missing, invalid or expired, or the user is inactive |
| `403` | Your role is not allowed to use this endpoint |
| `404` | The resource was not found |
| `422` | The request body or params failed validation |
| `502` | An upstream service failed (Paystack or the Foodstuff API) |
| `503` | An upstream service is not configured or cannot be reached |

---

## Environment Variables

```env
# Core
DATABASE_URL=postgresql://user:pass@host:5432/db
SECRET_KEY=change-me
ACCESS_TOKEN_EXPIRE_MINUTES=480
ALLOWED_ORIGINS=https://invoicing.foodstuff.store,http://localhost:5173

# Celery / background jobs
REDIS_URL=redis://localhost:6379/0

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM_NAME=Foodstuff Store
SMTP_FROM_EMAIL=noreply@foodstuff.store
FRONTEND_URL=https://invoicing.foodstuff.store

# Paystack
PAYSTACK_SECRET_KEY=sk_...
PAYSTACK_PUBLIC_KEY=pk_...

# Foodstuff Store integration (custom orders)
FOODSTUFF_API_URL=https://...
FOODSTUFF_API_KEY=...
```

If `ALLOWED_ORIGINS` is not set, CORS allows `https://invoicing.foodstuff.store`, `http://localhost:5173` and `http://127.0.0.1:5173`.
