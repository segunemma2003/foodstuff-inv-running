# User Stories — Foodstuff Store Invoicing & Payment System

## Roles

| Role     | Description                                                               |
|----------|---------------------------------------------------------------------------|
| Admin    | Full system access — settings, user management, approvals, confirmations  |
| Manager  | Approves quotations, confirms payments, manages pricing                    |
| Sales    | Creates quotations, invoices, records payments, manages customers/products |
| Analyst  | Read-only access to all records for reporting purposes                    |

---

## Epic 1 — Authentication & User Management

### US-1.1 — Login
> **As a** staff member,
> **I want** to log in with my username and password,
> **So that** I can access the system securely.

**Acceptance Criteria:**
- I receive a JWT token on successful login.
- Invalid credentials return a 401 error.
- Token expires after the configured duration (default 8 hours).

---

### US-1.2 — Change Password
> **As a** staff member,
> **I want** to change my password,
> **So that** I can keep my account secure.

**Acceptance Criteria:**
- I must provide my current password to set a new one.
- The new password is accepted only if the current password is correct.

---

### US-1.3 — User Management (Admin)
> **As an** admin,
> **I want** to create, update, and deactivate user accounts,
> **So that** only authorised staff can access the system.

**Acceptance Criteria:**
- I can assign roles: admin, manager, sales, analyst.
- Deactivated users cannot log in.
- User deletion is soft (deactivation only, records are preserved).

---

## Epic 2 — Customer Management

### US-2.1 — Create Customer
> **As a** sales staff member,
> **I want** to create a customer record with their contact details,
> **So that** I can link quotations and invoices to them.

**Acceptance Criteria:**
- Customer fields: name, business name, phone, email, address, city, category.
- Default delivery type and payment term can be pre-set per customer.
- Duplicate prevention relies on business name / phone / email uniqueness checks.

---

### US-2.2 — View Customer History
> **As a** sales staff member,
> **I want** to view a customer's past quotations, invoices, and payment history,
> **So that** I can understand their account status.

**Acceptance Criteria:**
- I can see all quotations and invoices for a customer.
- I can see total sales value, last order date, and preferred payment term.
- I can see each invoice's payment status (active, partially paid, paid, cancelled).

---

### US-2.3 — Customer Analytics
> **As an** analyst or manager,
> **I want** to view purchase analytics per customer,
> **So that** I can identify high-value or at-risk customers.

**Acceptance Criteria:**
- Shows top products bought, purchase frequency, total value.
- Flags customers inactive for more than 30 days.

---

## Epic 3 — Product & Pricing Management

### US-3.1 — Manage Products
> **As a** sales staff member,
> **I want** to add and update products with their SKU and unit of measure,
> **So that** I can include them in quotations with accurate pricing.

**Acceptance Criteria:**
- Products have a unique SKU, name, category, and unit of measure.
- Products can be bulk-uploaded from Excel.

---

### US-3.2 — Cost Price History
> **As a** sales staff member,
> **I want** to record cost prices with effective dates,
> **So that** the system always uses the correct price when generating quotations.

**Acceptance Criteria:**
- Multiple cost prices can exist per product; the latest by effective date is used.
- Cost prices can be bulk-uploaded from Excel.

---

### US-3.3 — Pricing Rules
> **As a** manager or admin,
> **I want** to define markup rules for supply, delivery, and payment terms,
> **So that** selling prices are calculated consistently and automatically.

**Acceptance Criteria:**
- Supply markup is always applied.
- Delivery markup is applied only for "delivery" orders.
- Payment term markup is applied based on the selected term (e.g. Net 30).

---

## Epic 4 — Quotation Workflow

### US-4.1 — Create Quotation
> **As a** sales staff member,
> **I want** to create a quotation for a customer by selecting products and quantities,
> **So that** pricing is automatically calculated and presented for approval.

**Acceptance Criteria:**
- I select delivery type and payment term.
- The system auto-calculates cost, supply markup, delivery markup, payment term markup, and unit price.
- Quotation is saved as "draft".

---

### US-4.2 — Submit for Approval
> **As a** sales staff member,
> **I want** to submit a draft quotation for management approval,
> **So that** it can be reviewed before being sent to the customer.

**Acceptance Criteria:**
- Status changes from "draft" to "pending_approval".
- An email notification is sent to managers/admins.

---

### US-4.3 — Approve or Reject Quotation
> **As a** manager or admin,
> **I want** to approve or reject submitted quotations,
> **So that** only verified quotes proceed to invoicing.

**Acceptance Criteria:**
- Approval changes status to "approved".
- Rejection requires a reason and changes status to "rejected".
- Email notifications are sent to the quotation creator.

---

### US-4.4 — Convert to Invoice
> **As a** sales staff member,
> **I want** to convert an approved quotation to an invoice,
> **So that** the customer can be billed.

**Acceptance Criteria:**
- Only approved quotations can be converted.
- Prices are locked from the quotation (no recalculation).
- Invoice due date is calculated from the payment term.

---

## Epic 5 — Invoicing

### US-5.1 — View Invoice
> **As any** staff member,
> **I want** to view an invoice with all line items and payment status,
> **So that** I know what has been billed and what has been paid.

**Acceptance Criteria:**
- Invoice shows: invoice number, customer, items, total, amount paid, balance due, status.
- Status is one of: active, partially_paid, paid, cancelled.

---

### US-5.2 — Download Invoice PDF
> **As any** staff member,
> **I want** to download an invoice as a PDF,
> **So that** I can send it to the customer or file it.

**Acceptance Criteria:**
- PDF includes all line items with pricing breakdown.
- PDF is generated on demand.

---

### US-5.3 — Cancel Invoice
> **As a** manager or admin,
> **I want** to cancel an active invoice,
> **So that** I can reverse an incorrect billing.

**Acceptance Criteria:**
- Only active or partially-paid invoices can be cancelled.
- Cancelled invoices cannot receive new payments.

---

## Epic 6 — Payment Accounts (Settings)

### US-6.1 — Manage Company Bank Accounts
> **As an** admin or manager,
> **I want** to save the company's bank account details in the system,
> **So that** staff can reference them when recording customer payments.

**Acceptance Criteria:**
- I can add multiple accounts (bank name, account number, account name, account type).
- One account can be marked as the default.
- Accounts can be deactivated without deleting payment history.

---

### US-6.2 — View Saved Accounts
> **As a** sales staff member,
> **I want** to see the list of company bank accounts,
> **So that** I know which account the customer should transfer money to.

**Acceptance Criteria:**
- Active accounts are returned by default.
- Each account shows: bank name, account number, account name, is_default flag.

---

## Epic 7 — Bank Transfer Payments

### US-7.1 — Record a Bank Transfer Payment
> **As a** sales staff member,
> **I want** to record that a customer has made a bank transfer,
> **So that** there is a pending payment record awaiting confirmation.

**Acceptance Criteria:**
- I select the invoice, the amount, the company account it was sent to, and the date.
- Payment is created with status "pending".
- I can optionally record the payer's name and notes.
- Multiple payments can be recorded against the same invoice (for partial payments).

---

### US-7.2 — Confirm a Bank Transfer Payment
> **As a** manager or admin,
> **I want** to confirm a pending bank transfer after verifying the bank alert,
> **So that** the invoice's payment status is updated accurately.

**Acceptance Criteria:**
- Payment status changes to "confirmed".
- Invoice amount_paid is recalculated; status becomes "partially_paid" or "paid".
- A payment confirmation email is sent to the customer.

---

### US-7.3 — Void a Payment
> **As a** manager or admin,
> **I want** to void a pending or confirmed payment,
> **So that** I can correct an erroneous payment record.

**Acceptance Criteria:**
- Payment status changes to "voided".
- Invoice amount_paid and status are recalculated.

---

## Epic 8 — Paystack Online Payments

### US-8.1 — Generate a Paystack Payment Link
> **As a** sales staff member,
> **I want** to generate an online payment link for an invoice,
> **So that** the customer can pay securely via card, bank transfer, or USSD on Paystack.

**Acceptance Criteria:**
- I select an invoice and optionally specify an amount (defaults to outstanding balance).
- The system calls Paystack and returns a payment URL.
- A pending payment record is created with the Paystack reference and URL.
- Customer must have an email on record.

---

### US-8.2 — Send Payment Link to Customer
> **As a** sales staff member,
> **I want** to send the Paystack payment link to the customer by email,
> **So that** they can pay from wherever they are.

**Acceptance Criteria:**
- An email is sent to the customer's registered email address with the payment link and amount.
- A "Pay Now" button is clearly visible in the email.

---

### US-8.3 — Automatic Payment Confirmation via Webhook
> **As the** system,
> **I want** to receive Paystack webhook events when a customer completes payment,
> **So that** the invoice is automatically marked as paid without manual intervention.

**Acceptance Criteria:**
- Paystack sends a `charge.success` event to `/api/v1/payments/paystack/webhook`.
- The webhook signature is verified before processing.
- The matching payment is confirmed, invoice status is updated automatically.
- A payment confirmation email is sent to the customer.

---

### US-8.4 — Manually Verify a Paystack Payment
> **As a** sales staff member,
> **I want** to manually verify a Paystack payment by reference,
> **So that** I can confirm it in case the webhook was missed.

**Acceptance Criteria:**
- I call the verify endpoint with the Paystack reference.
- If Paystack confirms success, the payment and invoice are updated.

---

## Epic 9 — Reporting & Analytics

### US-9.1 — Dashboard Overview
> **As any** staff member,
> **I want** to see a dashboard with today's sales, active customers, and recent activity,
> **So that** I have an at-a-glance view of the business.

---

### US-9.2 — Sales Analytics
> **As a** manager or analyst,
> **I want** to view detailed sales analytics over a period,
> **So that** I can make informed business decisions.

**Acceptance Criteria:**
- Shows: total sales, invoice count, quotation conversion rate, top customers/products.
- Breakdowns by delivery type, payment term, and staff member.
- Daily and monthly trend charts.

---

### US-9.3 — Download Sales Report
> **As a** manager or analyst,
> **I want** to download a filtered sales report as an Excel file,
> **So that** I can analyse it offline or share it with stakeholders.

---

### US-9.4 — Audit Trail
> **As an** admin or manager,
> **I want** to view a log of all system actions,
> **So that** I can track who did what and when.

**Acceptance Criteria:**
- Audit trail captures: payments recorded, confirmed, voided; payment accounts created/updated; invoices updated on payment.
- Filterable by entity type, user, action, and date range.
