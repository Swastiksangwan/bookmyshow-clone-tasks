import uuid

from django.db import models
from django.contrib.auth.models import User 
from django.utils import timezone

from .validators import validate_youtube_url


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Language(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.SlugField(max_length=20, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


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
    genres = models.ManyToManyField(Genre, related_name="movies", blank=True)
    language = models.ForeignKey(
        Language,
        related_name="movies",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_index=False,
    )

    class Meta:
        indexes = [
            models.Index(fields=["name"], name="movie_name_idx"),
            models.Index(fields=["rating"], name="movie_rating_idx"),
            models.Index(fields=["language"], name="movie_language_idx"),
        ]

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

    class Meta:
        indexes = [
            models.Index(fields=["status", "expires_at"], name="reservation_status_exp_idx"),
        ]

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

    class Meta:
        indexes = [
            models.Index(fields=["booked_at"], name="booking_booked_at_idx"),
            models.Index(fields=["movie", "booked_at"], name="booking_movie_time_idx"),
            models.Index(fields=["theater", "booked_at"], name="booking_theater_time_idx"),
        ]

    def __str__(self):
        return f'Booking by{self.user.username} for {self.seat.seat_number} at {self.theater.name}'

class PaymentTransaction(models.Model):
    STATUS_CREATED = "CREATED"
    STATUS_AUTHORIZED = "AUTHORIZED"
    STATUS_CAPTURED = "CAPTURED"
    STATUS_FAILED = "FAILED"
    STATUS_CANCELLED = "CANCELLED"
    STATUS_EXPIRED = "EXPIRED"
    STATUS_BOOKING_PENDING = "BOOKING_PENDING"
    STATUS_REQUIRES_REVIEW = "REQUIRES_REVIEW"

    STATUS_CHOICES = [
        (STATUS_CREATED, "Created"),
        (STATUS_AUTHORIZED, "Authorized"),
        (STATUS_CAPTURED, "Captured"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_BOOKING_PENDING, "Booking pending"),
        (STATUS_REQUIRES_REVIEW, "Requires review"),
    ]

    user = models.ForeignKey(User,on_delete=models.CASCADE)
    reservation_token = models.UUIDField(db_index=True)
    razorpay_order_id = models.CharField(max_length=100,unique=True)
    razorpay_payment_id = models.CharField(max_length=100,null=True,blank=True,unique=True)
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=10,default="INR")
    status = models.CharField(max_length=30,choices=STATUS_CHOICES,default=STATUS_CREATED)
    idempotency_key = models.CharField(max_length=255,unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(null=True,blank=True)
    raw_provider_payload = models.JSONField(default=dict,blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "verified_at"], name="payment_status_verified_idx"),
            models.Index(fields=["status", "created_at"], name="payment_status_created_idx"),
        ]

    def is_successful(self):
        return self.status == self.STATUS_CAPTURED

    def is_finalized(self):
        return self.status in {
            self.STATUS_CAPTURED,
            self.STATUS_FAILED,
            self.STATUS_CANCELLED,
            self.STATUS_EXPIRED,
            self.STATUS_REQUIRES_REVIEW,
        }

    def __str__(self):
        return f'{self.razorpay_order_id} ({self.status})'

class PaymentWebhookEvent(models.Model):
    STATUS_RECEIVED = "RECEIVED"
    STATUS_PROCESSED = "PROCESSED"
    STATUS_IGNORED_DUPLICATE = "IGNORED_DUPLICATE"
    STATUS_FAILED = "FAILED"
    STATUS_INVALID_SIGNATURE = "INVALID_SIGNATURE"

    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_PROCESSED, "Processed"),
        (STATUS_IGNORED_DUPLICATE, "Ignored duplicate"),
        (STATUS_FAILED, "Failed"),
        (STATUS_INVALID_SIGNATURE, "Invalid signature"),
    ]

    provider = models.CharField(max_length=50,default="razorpay")
    event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=100)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True,blank=True)
    processing_status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
    )
    raw_payload = models.JSONField(default=dict,blank=True)
    signature_valid = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"],
                name="unique_provider_webhook_event",
            )
        ]

    def __str__(self):
        return f'{self.provider}:{self.event_type}:{self.processing_status}'
