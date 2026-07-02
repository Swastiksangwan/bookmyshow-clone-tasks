from django.contrib import admin
from .models import (
    Booking,
    Movie,
    PaymentTransaction,
    PaymentWebhookEvent,
    Seat,
    SeatReservation,
    Theater,
)

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'cast','description','trailer_url']

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'movie','theater','booked_at']

@admin.register(SeatReservation)
class SeatReservationAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'seat',
        'theater',
        'movie',
        'status',
        'created_at',
        'expires_at',
        'confirmed_at',
        'reservation_token',
    ]
    list_filter = ['status', 'theater', 'movie']
    search_fields = [
        'user__username',
        'seat__seat_number',
        'movie__name',
        'theater__name',
    ]

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'reservation_token',
        'razorpay_order_id',
        'razorpay_payment_id',
        'amount',
        'currency',
        'status',
        'created_at',
        'updated_at',
        'verified_at',
    ]
    list_filter = ['status', 'currency', 'created_at']
    search_fields = [
        'user__username',
        'reservation_token',
        'razorpay_order_id',
        'razorpay_payment_id',
    ]

@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = [
        'provider',
        'event_id',
        'event_type',
        'processing_status',
        'signature_valid',
        'received_at',
        'processed_at',
    ]
    list_filter = [
        'provider',
        'event_type',
        'processing_status',
        'signature_valid',
    ]
    search_fields = ['event_id', 'event_type']
