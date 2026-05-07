from typing import Optional, List
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from dependencies import get_current_user
import models
import schemas
from services import analytics_service

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/sales", response_model=schemas.SalesAnalytics)
def sales_analytics(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    customer_id: Optional[int] = None,
    product_id: Optional[int] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    delivery_type: Optional[str] = None,
    payment_term: Optional[str] = None,
    staff_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return analytics_service.sales_analytics(
        db,
        date_from=date_from,
        date_to=date_to,
        customer_id=customer_id,
        product_id=product_id,
        category_id=category_id,
        market_id=market_id,
        delivery_type=delivery_type,
        payment_term=payment_term,
        staff_id=staff_id,
    )


@router.get("/customer-behavior", response_model=List[schemas.CustomerBehaviorOut])
def customer_behavior(
    customer_id: Optional[int] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    inactive_days: int = 30,
    limit: int = 200,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return analytics_service.customer_behavior(
        db,
        customer_id=customer_id,
        category_id=category_id,
        market_id=market_id,
        inactive_days=inactive_days,
        limit=limit,
    )


@router.get("/product-sales")
def product_sales_analytics(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    delivery_type: Optional[str] = None,
    payment_term: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return analytics_service.product_sales_analytics(
        db,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        market_id=market_id,
        delivery_type=delivery_type,
        payment_term=payment_term,
        limit=limit,
    )


@router.get("/staff-performance", response_model=List[schemas.StaffPerformanceOut])
def staff_performance(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    user_id: Optional[int] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return analytics_service.staff_performance(
        db,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        category_id=category_id,
        market_id=market_id,
    )


@router.get("/comprehensive", response_model=schemas.ComprehensiveStats)
def comprehensive_stats(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    category_id: Optional[int] = None,
    market_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    return analytics_service.comprehensive_stats(
        db,
        date_from=date_from,
        date_to=date_to,
        category_id=category_id,
        market_id=market_id,
    )
