from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session

from database import get_db
from dependencies import (
    get_current_user,
    require_not_analyst,
    require_admin,
    require_admin_or_manager,
    require_market_view_roles,
    require_market_manage_roles,
    require_product_upload_roles,
    require_product_create_roles,
)
import models
import schemas
from services import product_service

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("/categories", response_model=List[schemas.CategoryOut])
def list_categories(db: Session = Depends(get_db), current_user: models.User = Depends(require_market_view_roles)):
    return product_service.list_categories(db, current_user)


@router.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    body: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_market_manage_roles),
):
    return product_service.create_category(db, body)


@router.get("/markets", response_model=List[schemas.MarketOut])
def list_markets(db: Session = Depends(get_db), current_user: models.User = Depends(require_market_view_roles)):
    return product_service.list_markets(db, current_user)


@router.post("/markets", response_model=schemas.MarketOut, status_code=201)
def create_market(
    body: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_market_manage_roles),
):
    return product_service.create_market(db, body)


@router.put("/markets/{market_id}", response_model=schemas.MarketOut)
def update_market(
    market_id: int,
    body: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_market_manage_roles),
):
    return product_service.update_market(db, market_id, body)


@router.delete("/markets/{market_id}", status_code=204)
def delete_market(
    market_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_market_manage_roles),
):
    product_service.delete_market(db, market_id)


@router.post("/markets/{market_id}/disable", response_model=schemas.MarketOut)
def disable_market(
    market_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_market_manage_roles),
):
    return product_service.disable_market(db, market_id)


@router.post("/markets/{market_id}/enable", response_model=schemas.MarketOut)
def enable_market(
    market_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_market_manage_roles),
):
    return product_service.enable_market(db, market_id)


@router.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: int,
    body: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin_or_manager),
):
    return product_service.update_category(db, category_id, body)


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    product_service.delete_category(db, category_id)


@router.get("", response_model=schemas.ProductListPage)
def list_products(
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return product_service.list_products(
        db,
        skip=skip,
        limit=limit,
        search=search,
        category_id=category_id,
        market_id=market_id,
        is_active=is_active,
        include_inactive=include_inactive,
    )


@router.post("", response_model=schemas.ProductOut, status_code=201)
def create_product(
    body: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_product_create_roles),
):
    return product_service.create_product(db, body, current_user)


@router.get("/{product_id}", response_model=schemas.ProductOut)
def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return product_service.get_product(db, product_id)


@router.put("/{product_id}", response_model=schemas.ProductOut)
def update_product(
    product_id: int,
    body: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_product_create_roles),
):
    return product_service.update_product(db, product_id, body, current_user)


@router.post("/{product_id}/disable", response_model=schemas.MessageResponse)
def disable_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_product_create_roles),
):
    return product_service.disable_product(db, product_id, current_user)


@router.post("/{product_id}/enable", response_model=schemas.MessageResponse)
def enable_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_product_create_roles),
):
    return product_service.enable_product(db, product_id, current_user)


@router.delete("/{product_id}", response_model=schemas.MessageResponse)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    return product_service.delete_product(db, product_id, current_user)


@router.get("/{product_id}/cost-history", response_model=List[schemas.CostPriceOut])
def product_cost_history(
    product_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return product_service.product_cost_history(db, product_id)


@router.get("/{product_id}/analytics", response_model=schemas.ProductAnalyticsOut)
def product_analytics(
    product_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return product_service.product_analytics(db, product_id)


@router.post("/{product_id}/image", response_model=schemas.ProductOut)
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return await product_service.upload_product_image(db, product_id, file, current_user)


@router.delete("/{product_id}/image", response_model=schemas.ProductOut)
def delete_product_image(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_not_analyst),
):
    return product_service.delete_product_image(db, product_id)


@router.get("/template")
def download_template(_: models.User = Depends(get_current_user)):
    return product_service.download_template()


@router.post("/bulk-upload", response_model=schemas.JobEnqueuedResponse, status_code=202)
async def bulk_upload_products(
    file: UploadFile = File(...),
    market_id: Optional[int] = Form(default=None),
    current_user: models.User = Depends(require_product_upload_roles),
):
    return await product_service.bulk_upload_products(file, current_user, market_id)
