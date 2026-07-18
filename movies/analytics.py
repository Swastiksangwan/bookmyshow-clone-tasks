from datetime import timedelta

from django.core.cache import cache
from django.db.models import Case, Count, ExpressionWrapper, F, FloatField, Sum, Value, When
from django.db.models.functions import Cast, ExtractHour
from django.utils import timezone

from .models import Booking, PaymentTransaction, Theater


ANALYTICS_CACHE_KEY = "admin_dashboard_analytics_v1"
ANALYTICS_CACHE_TTL_SECONDS = 60


def can_view_analytics(user):
    return (
        user.is_authenticated
        and user.is_active
        and (
            user.is_staff
            or user.is_superuser
            or user.groups.filter(name="analytics_admin").exists()
        )
    )


def paise_to_rupees(amount_paise):
    return round((amount_paise or 0) / 100, 2)


def format_indian_rupees(amount_paise):
    amount = paise_to_rupees(amount_paise)
    whole, decimal = f"{amount:.2f}".split(".")
    if len(whole) > 3:
        last_three = whole[-3:]
        leading = whole[:-3]
        groups = []
        while len(leading) > 2:
            groups.insert(0, leading[-2:])
            leading = leading[:-2]
        if leading:
            groups.insert(0, leading)
        whole = ",".join(groups + [last_three])
    return f"INR {whole}.{decimal}"


def _sum_captured_revenue(start_time, now):
    total = PaymentTransaction.objects.filter(
        status=PaymentTransaction.STATUS_CAPTURED,
        verified_at__isnull=False,
        verified_at__gte=start_time,
        verified_at__lte=now,
    ).aggregate(total=Sum("amount"))["total"]
    return total or 0


def _booking_hour_label(hour):
    return f"{hour:02d}:00 - {hour:02d}:59"


def get_admin_analytics():
    now = timezone.now()
    local_now = timezone.localtime(now)
    start_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_last_7_days = now - timedelta(days=7)
    start_month = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    today_paise = _sum_captured_revenue(start_today, now)
    last_7_days_paise = _sum_captured_revenue(start_last_7_days, now)
    current_month_paise = _sum_captured_revenue(start_month, now)

    popular_movies = [
        {
            "movie_id": row["movie_id"],
            "movie_name": row["movie__name"],
            "booking_count": row["booking_count"],
        }
        for row in Booking.objects.values("movie_id", "movie__name")
        .annotate(booking_count=Count("id"))
        .order_by("-booking_count", "movie__name")[:10]
    ]

    occupancy_expression = ExpressionWrapper(
        Cast(F("booked_seats"), FloatField())
        * Value(100.0)
        / Cast(F("total_seats"), FloatField()),
        output_field=FloatField(),
    )
    busiest_theaters = []
    theater_rows = (
        Theater.objects.values("id", "name", "movie__name", "time")
        .annotate(
            total_seats=Count("seats", distinct=True),
            booked_seats=Count("booking", distinct=True),
        )
        .annotate(
            occupancy_rate=Case(
                When(total_seats=0, then=Value(0.0)),
                default=occupancy_expression,
                output_field=FloatField(),
            )
        )
        .order_by("-occupancy_rate", "-booked_seats", "name")[:10]
    )
    for row in theater_rows:
        show_time = row["time"]
        busiest_theaters.append(
            {
                "theater_id": row["id"],
                "theater_name": row["name"],
                "movie_name": row["movie__name"],
                "show_time": timezone.localtime(show_time).strftime("%Y-%m-%d %H:%M"),
                "total_seats": row["total_seats"],
                "booked_seats": row["booked_seats"],
                "occupancy_rate": round(row["occupancy_rate"] or 0, 2),
            }
        )

    peak_booking_hours = [
        {
            "hour": row["hour"],
            "label": _booking_hour_label(row["hour"]),
            "booking_count": row["booking_count"],
        }
        for row in Booking.objects.annotate(hour=ExtractHour("booked_at"))
        .values("hour")
        .annotate(booking_count=Count("id"))
        .order_by("-booking_count", "hour")
        if row["hour"] is not None
    ]

    payment_attempts = PaymentTransaction.objects.filter(
        created_at__gte=start_month,
        created_at__lte=now,
    )
    total_attempts = payment_attempts.count()
    cancelled_attempts = payment_attempts.filter(
        status=PaymentTransaction.STATUS_CANCELLED
    ).count()
    cancellation_rate = (
        round((cancelled_attempts / total_attempts) * 100, 2)
        if total_attempts
        else 0
    )

    return {
        "revenue": {
            "today_paise": today_paise,
            "last_7_days_paise": last_7_days_paise,
            "current_month_paise": current_month_paise,
            "today_rupees": paise_to_rupees(today_paise),
            "last_7_days_rupees": paise_to_rupees(last_7_days_paise),
            "current_month_rupees": paise_to_rupees(current_month_paise),
            "today_display": format_indian_rupees(today_paise),
            "last_7_days_display": format_indian_rupees(last_7_days_paise),
            "current_month_display": format_indian_rupees(current_month_paise),
        },
        "popular_movies": popular_movies,
        "busiest_theaters": busiest_theaters,
        "peak_booking_hours": peak_booking_hours,
        "cancellation_rate": {
            "total_attempts": total_attempts,
            "cancelled_attempts": cancelled_attempts,
            "cancellation_rate": cancellation_rate,
        },
        "generated_at": local_now.isoformat(),
        "generated_at_display": local_now.strftime("%d %b %Y, %I:%M %p"),
        "cache_ttl_seconds": ANALYTICS_CACHE_TTL_SECONDS,
    }


def get_cached_admin_analytics():
    cached = cache.get(ANALYTICS_CACHE_KEY)
    if cached is not None:
        return cached
    data = get_admin_analytics()
    cache.set(ANALYTICS_CACHE_KEY, data, ANALYTICS_CACHE_TTL_SECONDS)
    return data


def clear_admin_analytics_cache():
    cache.delete(ANALYTICS_CACHE_KEY)
