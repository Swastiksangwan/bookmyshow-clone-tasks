import uuid

from django.db import models
from django.contrib.auth.models import User 
from django.utils import timezone

from .validators import validate_youtube_url


class Movie(models.Model):
    name= models.CharField(max_length=255)
    image= models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3,decimal_places=1)
    cast= models.TextField()
    description= models.TextField(blank=True,null=True) # optional
    trailer_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        validators=[validate_youtube_url],
    )

    def __str__(self):
        return self.name

class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name='theaters')
    time= models.DateTimeField()

    def __str__(self):
        return f'{self.name} - {self.movie.name} at {self.time}'

class Seat(models.Model):
    theater = models.ForeignKey(Theater,on_delete=models.CASCADE,related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked=models.BooleanField(default=False)

    def __str__(self):
        return f'{self.seat_number} in {self.theater.name}'

class SeatReservation(models.Model):
    STATUS_RESERVED = "RESERVED"
    STATUS_CONFIRMED = "CONFIRMED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_RESERVED, "Reserved"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    user = models.ForeignKey(User,on_delete=models.CASCADE)
    seat = models.ForeignKey(Seat,on_delete=models.CASCADE,related_name='reservations')
    theater = models.ForeignKey(Theater,on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE)
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default=STATUS_RESERVED)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True,blank=True)
    reservation_token = models.UUIDField(default=uuid.uuid4,db_index=True)

    def has_expired(self):
        return self.expires_at <= timezone.now()

    def is_active(self):
        return self.status == self.STATUS_RESERVED and self.expires_at > timezone.now()

    def __str__(self):
        return f'{self.user.username} reserved {self.seat.seat_number} ({self.status})'

class Booking(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    seat=models.OneToOneField(Seat,on_delete=models.CASCADE)
    movie=models.ForeignKey(Movie,on_delete=models.CASCADE)
    theater=models.ForeignKey(Theater,on_delete=models.CASCADE)
    booked_at=models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f'Booking by{self.user.username} for {self.seat.seat_number} at {self.theater.name}'
