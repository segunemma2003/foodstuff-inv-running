# Foodstuff Store — Comprehensive API Documentation

**Base URL:** `http://localhost:8000/api/v1`  
**Interactive Docs:** `http://localhost:8000/docs` (Swagger UI)  
**Auth:** Bearer JWT — include `Authorization: Bearer <token>` on every request except `/auth/login` and the Paystack webhook.

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Users](#2-users)
3. [Customers](#3-customers)
4. [Products & Categories](#4-products--categories)
5. [Cost Prices](#5-cost-prices)
6. [Pricing Rules](#6-pricing-rules)
7. [Quotations](#7-quotations)
8. [Invoices](#8-invoices)
9. [Payment Accounts](#9-payment-accounts)
10. [Payments](#10-payments)
11. [Dashboard](#11-dashboard)
12. [Analytics](#12-analytics)
13. [Reports](#13-reports)
14. [Audit Trail](#14-audit-trail)
15. [Settings](#15-settings)
16. [Error Codes](#16-error-codes)

---

## 1. Authentication

### POST `/auth/login`
Authenticate and receive a JWT token.

**Request Body:**
```json
{
  "username": "admin",
  "password": "Admin@12345"
}
```

**Response `200`:**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "user_id": 1,
  "username": "admin",
  "role": "admin"
}
```

---

### GET `/auth/me`
Get the currently authenticated user's profile.

**Response `200`:**
```json
{
  "id": 1,
  "username": "admin",
  "email": "admin@foodstuffstore.com",
  "full_name": "System Administrator",
  "role": "admin",
  "is_active": true,
  "created_at": "2024-01-01T00:00:00"
}
```

---

### POST `/auth/change-password`
Change authenticated user's password.

**Request Body:**
```json
{
  "current_password": "OldPass@123",
  "new_password": "NewPass@456"
}
```

**Response `200`:** `{ "message": "Password updated successfully" }`

---

### POST `/auth/forgot-password`
Initiate a password reset email.

**Request Body:** `{ "email": "user@example.com" }`

---

## 2. Users

> Admin-only for create/update/delete. All authenticated users can read.

### GET `/users`
List all users.

**Query Params:** `role`, `is_active` (bool), `skip`, `limit`

### POST `/users` `[Admin]`
Create a user.

**Request Body:**
```json
{
  "username": "jane",
  "email": "jane@store.com",
  "full_name": "Jane Doe",
  "password": "SecurePass@1",
  "role": "sales"
}
```

### GET `/users/{user_id}`
Get a single user.

### PUT `/users/{user_id}` `[Admin]`
Update a user's email, name, role, or active status.

### DELETE `/users/{user_id}` `[Admin]`
Deactivate a user (soft delete).

---

## 3. Customers

### GET `/customers`
List customers.

**Query Params:** `search` (name/email/phone), `category`, `is_active`, `skip`, `limit`

### POST `/customers` `[Sales+]`
Create a customer.

**Request Body:**
```json
{
  "customer_name": "Ade Foods Ltd",
  "business_name": "Ade Foods",
  "phone": "08012345678",
  "email": "ade@adefoods.com",
  "address": "12 Market Street",
  "city": "Lagos",
  "category": "Wholesale",
  "default_delivery": "delivery",
  "default_payment_term": "net_30"
}
```

**Response `201`:** Customer object.

### GET `/customers/{customer_id}`
Get customer details.

### PUT `/customers/{customer_id}` `[Sales+]`
Update customer.

### DELETE `/customers/{customer_id}` `[Sales+]`
Deactivate customer.

### GET `/customers/{customer_id}/quotations`
All quotations for a customer.

### GET `/customers/{customer_id}/invoices`
All invoices for a customer.

### GET `/customers/{customer_id}/analytics`
Customer analytics (total sales, avg order value, preferred payment term, etc.).

### GET `/customers/{customer_id}/top-products`
Top 10 products bought by this customer.

---

## 4. Products & Categories

### GET `/products/categories`
List all product categories.

### POST `/products/categories` `[Admin/Manager]`
Create a category.

**Request Body:** `{ "name": "Grains", "description": "Rice, beans, etc." }`

### GET `/products`
List products.

**Query Params:** `search`, `category_id`, `is_active`, `skip`, `limit`

**Response includes** `current_cost_price` and `cost_price_effective_date` for each product.

### POST `/products` `[Sales+]`
Create a product.

**Request Body:**
```json
{
  "product_name": "Basmati Rice 50kg",
  "sku": "RICE-50KG",
  "unit_of_measure": "bag",
  "category_id": 1
}
```

### GET `/products/{product_id}`
Get product with current cost price.

### PUT `/products/{product_id}` `[Sales+]`
Update product.

### DELETE `/products/{product_id}` `[Sales+]`
Deactivate product.

### GET `/products/{product_id}/cost-history`
Full cost price history for a product.

### GET `/products/{product_id}/analytics`
Product analytics (qty sold, revenue, top customers, monthly trend).

### POST `/products/bulk-upload` `[Sales+]`
Upload products from Excel (`multipart/form-data`, field: `file`).

Required columns: `product_name`, `sku`, `unit_of_measure`, `category_name`.

---

## 5. Cost Prices

### GET `/cost-prices`
List cost prices. **Query Params:** `product_id`

### POST `/cost-prices` `[Sales+]`
Add a cost price record.

**Request Body:**
```json
{
  "product_id": 3,
  "cost_price": 45000.00,
  "effective_date": "2024-06-01",
  "notes": "New supplier rate"
}
```

### PUT `/cost-prices/{cp_id}` `[Sales+]`
Update a cost price record.

### POST `/cost-prices/bulk-upload` `[Sales+]`
Upload cost prices from Excel.

Required columns: `sku`, `cost_price`, `effective_date`. Optional: `notes`.

### GET `/cost-prices/template`
Download the Excel template for bulk upload.

---

## 6. Pricing Rules

### GET `/pricing-rules`
List rules. **Query Params:** `is_active`

### POST `/pricing-rules` `[Admin/Manager]`
Create a pricing rule.

**Request Body:**
```json
{
  "rule_name": "Net 15 Markup",
  "rule_type": "payment_term",
  "markup_percentage": 2.0,
  "payment_term_code": "net_15",
  "is_active": true,
  "effective_date": "2024-01-01"
}
```
`rule_type` values: `supply`, `delivery`, `payment_term`

### GET `/pricing-rules/{rule_id}`
Get a rule.

### PUT `/pricing-rules/{rule_id}` `[Admin/Manager]`
Update a rule.

### DELETE `/pricing-rules/{rule_id}` `[Admin/Manager]`
Delete a rule.

---

## 7. Quotations

### POST `/quotations/calculate-price`
Preview pricing for items without saving.

**Request Body:**
```json
{
  "product_id": 3,
  "quantity": 10,
  "delivery_type": "delivery",
  "payment_term": "net_30"
}
```

**Response:**
```json
{
  "product_id": 3,
  "product_name": "Basmati Rice 50kg",
  "quantity": 10,
  "cost_price": 45000.00,
  "supply_markup_pct": 5.0,
  "supply_markup_amount": 2250.00,
  "delivery_markup_pct": 3.0,
  "delivery_markup_amount": 1350.00,
  "payment_term_markup_pct": 3.5,
  "payment_term_markup_amount": 1701.00,
  "unit_price": 50301.00,
  "line_total": 503010.00
}
```

### GET `/quotations`
List quotations.

**Query Params:** `status`, `customer_id`, `created_by`, `date_from`, `date_to`, `skip`, `limit`

`status` values: `draft`, `pending_approval`, `approved`, `rejected`, `converted`

### POST `/quotations` `[Sales+]`
Create a quotation.

**Request Body:**
```json
{
  "customer_id": 1,
  "quotation_date": "2024-06-15",
  "delivery_type": "delivery",
  "payment_term": "net_30",
  "notes": "Urgent order",
  "items": [
    { "product_id": 3, "quantity": 10 },
    { "product_id": 5, "quantity": 5 }
  ]
}
```

### GET `/quotations/{quotation_id}`
Get quotation with all items and pricing breakdown.

### PUT `/quotations/{quotation_id}` `[Sales+]`
Update a draft quotation (items and terms are recalculated).

### POST `/quotations/{quotation_id}/submit`
Submit a draft quotation for approval (draft → pending_approval).

### POST `/quotations/{quotation_id}/approve` `[Admin/Manager]`
Approve a quotation (pending_approval → approved).

### POST `/quotations/{quotation_id}/reject` `[Admin/Manager]`
Reject a quotation with a reason.

**Request Body:** `{ "reason": "Price margin too low" }`

### GET `/quotations/{quotation_id}/pdf`
Download quotation PDF.

### POST `/quotations/{quotation_id}/convert-to-invoice`
Convert approved quotation to an invoice.

---

## 8. Invoices

### GET `/invoices/approved-quotations`
List approved quotations that have not yet been converted to invoices.

**Query Params:** `customer_id`

### GET `/invoices`
List invoices.

**Query Params:** `customer_id`, `status`, `created_by`, `date_from`, `date_to`, `payment_term`, `delivery_type`, `skip`, `limit`

**Invoice `status` values:**

| Status           | Meaning                                                    |
|------------------|------------------------------------------------------------|
| `active`         | Invoice created, no payment recorded yet                   |
| `partially_paid` | Some payments confirmed, balance still outstanding         |
| `paid`           | Full invoice amount received via confirmed payments        |
| `cancelled`      | Invoice cancelled (no further payments accepted)           |

**Response includes `amount_paid` field** showing total confirmed payments.

### GET `/invoices/{invoice_id}`
Get invoice with items, customer, creator, linked quotation. Includes `amount_paid`.

### GET `/invoices/{invoice_id}/pdf`
Download invoice PDF.

### POST `/invoices/{invoice_id}/cancel` `[Admin/Manager]`
Cancel an invoice.

---

## 9. Payment Accounts

Saved company bank accounts. Customers transfer money to these accounts.

### GET `/payment-accounts`
List active payment accounts.

**Query Params:** `active_only` (bool, default `true`)

**Response:**
```json
[
  {
    "id": 1,
    "account_name": "Foodstuff Store Ltd",
    "bank_name": "GTBank",
    "account_number": "0123456789",
    "account_type": "current",
    "description": "Main operating account",
    "is_active": true,
    "is_default": true,
    "created_by": 1,
    "created_at": "2024-01-01T00:00:00"
  }
]
```

### POST `/payment-accounts` `[Admin/Manager]`
Add a new bank account.

**Request Body:**
```json
{
  "account_name": "Foodstuff Store Ltd",
  "bank_name": "GTBank",
  "account_number": "0123456789",
  "account_type": "current",
  "description": "Main operating account",
  "is_default": true
}
```

> Setting `is_default: true` automatically clears the previous default.

### GET `/payment-accounts/{account_id}`
Get a specific payment account.

### PUT `/payment-accounts/{account_id}` `[Admin/Manager]`
Update an account. All fields are optional.

**Request Body:**
```json
{
  "account_name": "Foodstuff Store (New Name)",
  "is_default": true,
  "is_active": true
}
```

### DELETE `/payment-accounts/{account_id}` `[Admin/Manager]`
Deactivate an account (soft delete). Existing payment records are not affected.

---

## 10. Payments

Two payment channels: **Bank Transfer** and **Paystack**.

---

### GET `/payments`
List payment records.

**Query Params:** `invoice_id`, `status`, `payment_method`, `skip`, `limit`

`status` values: `pending`, `confirmed`, `failed`, `voided`  
`payment_method` values: `bank_transfer`, `paystack`, `cash`, `cheque`

---

### GET `/payments/invoice/{invoice_id}/summary`
Full payment summary for an invoice.

**Response:**
```json
{
  "invoice_id": 12,
  "invoice_number": "INV-0012",
  "total_amount": 503010.00,
  "amount_paid": 200000.00,
  "balance_due": 303010.00,
  "payment_status": "partially_paid",
  "payments": [
    {
      "id": 3,
      "invoice_id": 12,
      "amount": 200000.00,
      "payment_method": "bank_transfer",
      "payment_account_id": 1,
      "payer_name": "Ade Foods",
      "payment_date": "2024-06-20",
      "status": "confirmed",
      "confirmed_at": "2024-06-20T14:22:00",
      "created_at": "2024-06-20T12:00:00"
    }
  ]
}
```

---

### GET `/payments/{payment_id}`
Get a single payment record.

---

### POST `/payments/bank-transfer` `[All authenticated]`
Record a bank transfer payment (pending confirmation).

**Request Body:**
```json
{
  "invoice_id": 12,
  "amount": 200000.00,
  "payment_account_id": 1,
  "payment_date": "2024-06-20",
  "payer_name": "Ade Foods",
  "notes": "Transfer ref: ADE/2024/001"
}
```

**Response `201`:** Payment object with `status: "pending"`.

**Rules:**
- Invoice must not be cancelled or fully paid.
- `payment_account_id` must be an active saved account.
- Amount must be greater than zero.

---

### PUT `/payments/{payment_id}/confirm` `[Admin/Manager]`
Confirm a pending bank-transfer payment after verifying the bank alert.

**Response `200`:** Updated payment with `status: "confirmed"`.

**Side effects:**
- Invoice `amount_paid` is recalculated.
- Invoice status is updated (`partially_paid` or `paid`).
- Confirmation email is sent to customer if they have an email on file.

---

### PUT `/payments/{payment_id}/void` `[Admin/Manager]`
Void a pending or confirmed payment.

**Response `200`:** Updated payment with `status: "voided"`.

**Side effects:** Invoice amount_paid and status are recalculated.

---

### POST `/payments/paystack/initialize`
Generate a Paystack payment link for an invoice.

**Request Body:**
```json
{
  "invoice_id": 12,
  "amount": 303010.00
}
```
> Omit `amount` to default to the full outstanding balance.

**Response `201`:**
```json
{
  "id": 7,
  "invoice_id": 12,
  "amount": 303010.00,
  "payment_method": "paystack",
  "paystack_reference": "PAY-INV-0012-A3F7B2C1",
  "paystack_payment_url": "https://checkout.paystack.com/xxxxxxxxxxxx",
  "status": "pending",
  "created_at": "2024-06-21T09:00:00"
}
```

**Requirements:**
- `PAYSTACK_SECRET_KEY` must be set in the environment.
- Customer must have an email address.
- Invoice must not be cancelled or already paid.

---

### POST `/payments/paystack/send-link`
Email the Paystack payment link to the customer.

**Request Body:**
```json
{
  "payment_id": 7
}
```

**Response `200`:** Payment object (unchanged).

**Side effects:** Customer receives a payment email with a "Pay Now" button linking to `paystack_payment_url`.

---

### GET `/payments/paystack/verify/{reference}`
Manually verify a Paystack payment by its reference string.

**Example:** `GET /payments/paystack/verify/PAY-INV-0012-A3F7B2C1`

**Response `200`:** Updated payment object.

**Side effects (if Paystack reports success):**
- Payment status → `confirmed`
- Invoice amount_paid and status are recalculated

---

### POST `/payments/paystack/webhook`
Paystack webhook endpoint — **do not call directly**.

Configure this URL in your Paystack dashboard under **Settings → Webhooks**:
```
https://yourdomain.com/api/v1/payments/paystack/webhook
```

**Events handled:** `charge.success`

**Signature verification:** Uses HMAC-SHA512 with your `PAYSTACK_SECRET_KEY` against the `x-paystack-signature` header.

**No authentication required** (Paystack calls this endpoint directly).

---

## 11. Dashboard

### GET `/dashboard/overview`
Overview KPIs for the dashboard.

**Response:**
```json
{
  "quotations_today": 5,
  "invoices_today": 3,
  "sales_today": 1250000.00,
  "sales_this_week": 8700000.00,
  "sales_this_month": 35000000.00,
  "active_customers": 142,
  "products_sold_today": 47.5,
  "top_customers": [...],
  "top_products": [...],
  "delivery_vs_pickup": { "delivery": 65, "pickup": 35 },
  "sales_by_payment_term": { "immediate": 12, "net_30": 23 },
  "recent_invoices": [...],
  "recent_quotations": [...]
}
```

---

## 12. Analytics

### GET `/analytics/sales`
Detailed sales analytics.

**Query Params:** `date_from`, `date_to`

**Response:** Total sales, invoice count, quotation conversion rate, average invoice value, top customers/products/categories, breakdowns by delivery type, payment term, staff, daily and monthly trends.

### GET `/analytics/customers`
Customer behaviour analytics — purchase frequency, inactive customers, month-over-month change.

### GET `/analytics/products/{product_id}`
Product-level analytics — qty sold, revenue, customer concentration.

### GET `/analytics/staff`
Staff performance — quotations and invoices created, conversion rate, total sales value.

---

## 13. Reports

### GET `/reports/sales`
Download a sales report as an Excel file.

**Query Params:** `date_from`, `date_to`, `customer_id`, `payment_term`, `delivery_type`

**Response:** `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

---

## 14. Audit Trail

> Admin and Manager only.

### GET `/audit-trail`
List audit log entries.

**Query Params:** `entity_type`, `entity_id`, `user_id`, `action`, `date_from`, `date_to`, `skip`, `limit`

**`entity_type` values:**
`user`, `customer`, `product`, `cost_price`, `pricing_rule`, `quotation`, `invoice`, `setting`, `payment`, `payment_account`

**`action` values:**
`create`, `update`, `delete`, `approve`, `reject`, `convert`, `submit`, `cancel`, `login`, `deactivate`, `confirm`, `void`

---

## 15. Settings

### GET `/settings`
List all application settings.

### GET `/settings/{key}`
Get a specific setting by key.

**Built-in setting keys:**

| Key                        | Default         | Description                              |
|----------------------------|-----------------|------------------------------------------|
| `company_name`             | Foodstuff Store | Display name used in PDFs and emails     |
| `company_address`          |                 | Company address                          |
| `company_email`            |                 | Company email                            |
| `company_phone`            |                 | Company phone                            |
| `invoice_prefix`           | INV             | Prefix for invoice numbers               |
| `quotation_prefix`         | QUO             | Prefix for quotation numbers             |
| `currency`                 | NGN             | Currency code                            |
| `currency_symbol`          | ₦               | Currency symbol shown in PDFs            |
| `paystack_enabled`         | false           | Show Paystack payment option in UI       |
| `payment_link_expiry_hours`| 24              | Hours before payment link is considered stale |

### PUT `/settings/{key}` `[Admin/Manager]`
Update a setting value.

**Request Body:** `{ "key": "company_name", "value": "My Foodstuff Store" }`

### PUT `/settings` `[Admin/Manager]`
Bulk update multiple settings.

**Request Body:**
```json
[
  { "key": "company_name",  "value": "My Store" },
  { "key": "company_email", "value": "info@mystore.com" }
]
```

---

## 16. Error Codes

| HTTP Status | Meaning                                                              |
|-------------|----------------------------------------------------------------------|
| `400`       | Bad request — invalid input, business rule violation                 |
| `401`       | Unauthorized — missing or invalid JWT token                          |
| `403`       | Forbidden — insufficient role permissions                            |
| `404`       | Not found — resource does not exist                                  |
| `422`       | Unprocessable entity — request body validation failed (Pydantic)     |
| `502`       | Bad gateway — Paystack API call failed                               |
| `503`       | Service unavailable — Paystack not configured (missing secret key)   |

All error responses follow the format:
```json
{ "detail": "Human-readable error message" }
```

---

## Payment Flow Reference

### Bank Transfer Flow

```
Staff                    API                        Manager/Admin
  |                       |                               |
  |-- POST /payments/     |                               |
  |   bank-transfer  ---->|                               |
  |                       | Creates payment (pending)     |
  |<-- 201 Payment -------|                               |
  |                       |                               |
  |                       |<-- PUT /payments/{id}/confirm |
  |                       |   (after bank alert received) |
  |                       | Updates payment → confirmed   |
  |                       | Recalculates invoice status   |
  |                       | Sends confirmation email      |
  |                       |------------------------------>|
```

### Paystack Flow

```
Staff                    API                    Paystack           Customer
  |                       |                        |                  |
  |-- POST /payments/     |                        |                  |
  |   paystack/initialize |                        |                  |
  |   ------------------>|                        |                  |
  |                       |-- Initialize txn ----->|                  |
  |                       |<-- payment URL --------|                  |
  |                       | Creates payment (pending)                 |
  |<-- 201 + URL ---------|                                           |
  |                       |                                           |
  |-- POST /payments/     |                                           |
  |   paystack/send-link  |                                           |
  |   ------------------>|                                           |
  |                       |-- Payment link email ---------------------->|
  |                       |                        |                  |
  |                       |                        |<-- Customer pays --|
  |                       |<-- charge.success      |                  |
  |                       |    webhook ------------|                  |
  |                       | Verifies signature                        |
  |                       | Confirms payment                          |
  |                       | Updates invoice status                    |
  |                       |-- Confirmation email ---------------------->|
```

---

## Environment Variables Reference

```env
# App
DATABASE_URL=sqlite:///./foodstuff.db
SECRET_KEY=change-this-to-a-long-random-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Redis (Celery)
REDIS_URL=redis://localhost:6379/0

# SMTP Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_USER=yourname@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_NAME=Foodstuff Store
SMTP_FROM_EMAIL=noreply@foodstuffstore.com
FRONTEND_URL=http://localhost:3000

# Paystack Payment Gateway
PAYSTACK_SECRET_KEY=sk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PAYSTACK_PUBLIC_KEY=pk_test_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Background jobs
JOB_OUTPUT_DIR=/tmp/foodstuff_jobs
JOB_INPUT_DIR=/tmp/foodstuff_uploads
```

---

## Quick Start: Set Up Payments

### Step 1 — Add a bank account (Admin/Manager)

```bash
curl -X POST http://localhost:8000/api/v1/payment-accounts \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "account_name": "Foodstuff Store Ltd",
    "bank_name": "GTBank",
    "account_number": "0123456789",
    "account_type": "current",
    "is_default": true
  }'
```

### Step 2 — Record a customer bank transfer (Sales)

```bash
curl -X POST http://localhost:8000/api/v1/payments/bank-transfer \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_id": 12,
    "amount": 200000,
    "payment_account_id": 1,
    "payment_date": "2024-06-20",
    "payer_name": "Ade Foods",
    "notes": "Trf ref ADE001"
  }'
```

### Step 3 — Confirm after verifying bank alert (Admin/Manager)

```bash
curl -X PUT http://localhost:8000/api/v1/payments/3/confirm \
  -H "Authorization: Bearer <token>"
```

### Step 4 — Generate a Paystack link (requires PAYSTACK_SECRET_KEY)

```bash
curl -X POST http://localhost:8000/api/v1/payments/paystack/initialize \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{ "invoice_id": 12 }'
```

### Step 5 — Email the payment link to the customer

```bash
curl -X POST http://localhost:8000/api/v1/payments/paystack/send-link \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{ "payment_id": 7 }'
```
