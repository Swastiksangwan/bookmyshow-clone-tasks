from django.contrib import admin
from .models import Movie, Theater, Seat,Booking, SeatReservation

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
