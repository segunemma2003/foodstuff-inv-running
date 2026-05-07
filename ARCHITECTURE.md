# Backend Layered Architecture

This backend now follows a layered structure:

- `routers/` = controllers (HTTP contracts, auth dependencies, delegation)
- `services/` = domain/business logic + orchestration
- `repositories/` = reusable data-access helpers
- `models.py` = SQLAlchemy entities
- `schemas.py` = API request/response contracts
- `services/integrations/` = wrappers around tasks, storage, and external integrations

## Design Rules

1. Keep endpoint paths, request models, and response models stable in `routers/`.
2. Put business rules and cross-entity workflows in `services/`.
3. Put reusable query primitives in `repositories/`.
4. Keep transaction boundaries explicit in `services/`.
5. Preserve side-effect ordering for:
   - audit trail writes
   - queue event writes
   - background task dispatch
   - S3/object lifecycle operations
   - external webhook/email integrations

## Current Service Coverage

Implemented service modules include:

- `auth_service.py`
- `user_service.py`
- `settings_service.py`
- `pricing_rule_service.py`
- `payment_account_service.py`
- `audit_trail_service.py`
- `job_service.py`
- `report_service.py`
- `customer_service.py`
- `cost_price_service.py`
- `product_service.py`
- `quotations_service.py`
- `invoice_service.py`
- `payment_service.py`
- `dashboard_service.py`
- `analytics_service.py`

## Migration Safety Notes

- API contracts remain defined at router level with existing schemas.
- Service functions may raise `HTTPException` to preserve exact legacy error behavior.
- Avoid changing response payload keys without coordinated frontend updates.
