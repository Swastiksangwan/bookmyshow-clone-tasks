from django.contrib import admin
from .models import (
    Booking,
    BookingEmailNotification,
    Genre,
    Language,
    Movie,
    PaymentTransaction,
    PaymentWebhookEvent,
    Seat,
    SeatReservation,
    Theater,
)

@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ['name', 'code']
    search_fields = ['name', 'code']

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'language', 'trailer_url']
    list_filter = ['language', 'genres']
    search_fields = ['name', 'cast', 'description']
    filter_horizontal = ('genres',)

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

@admin.register(BookingEmailNotification)
class BookingEmailNotificationAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'recipient_email',
        'reservation_token',
        'payment_transaction',
        'status',
        'attempt_count',
        'max_attempts',
        'next_retry_at',
        'sent_at',
        'created_at',
        'updated_at',
    ]
    list_filter = ['status', 'created_at', 'sent_at']
    search_fields = [
        'recipient_email',
        'reservation_token',
        'payment_transaction__razorpay_payment_id',
        'payment_transaction__razorpay_order_id',
        'user__username',
    ]
    readonly_fields = [
        'created_at',
        'updated_at',
        'sent_at',
        'last_error',
        'payload',
    ]
