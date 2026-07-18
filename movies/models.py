import uuid
from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User 
from django.utils import timezone

from .validators import validate_youtube_url


EVALUATION_POSTER_PATHS = {
    "Evaluation: Big Buck Bunny": "images/evaluation-posters/big-buck-bunny.svg",
    "Evaluation: Interstellar Dreams": "images/evaluation-posters/interstellar-dreams.svg",
    "Evaluation: Mumbai Nights": "images/evaluation-posters/mumbai-nights.svg",
    "Evaluation: Comedy Junction": "images/evaluation-posters/comedy-junction.svg",
    "Evaluation: Southern Quest": "images/evaluation-posters/southern-quest.svg",
}


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

    @property
    def fallback_poster_static_path(self):
        return EVALUATION_POSTER_PATHS.get(
            self.name,
            "images/evaluation-posters/generic-cinema.svg",
        )

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


class BookingEmailNotification(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_SENDING = "SENDING"
    STATUS_SENT = "SENT"
    STATUS_FAILED = "FAILED"
    STATUS_CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SENDING, "Sending"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    user = models.ForeignKey(User,on_delete=models.CASCADE)
    booking = models.ForeignKey(Booking,null=True,blank=True,on_delete=models.SET_NULL)
    payment_transaction = models.ForeignKey(
        PaymentTransaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reservation_token = models.UUIDField(db_index=True)
    recipient_email = models.EmailField()
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default=STATUS_PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    next_retry_at = models.DateTimeField(null=True,blank=True)
    last_error = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255,null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True,blank=True)
    payload = models.JSONField(default=dict,blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_retry_at"], name="email_status_retry_idx"),
            models.Index(fields=["created_at"], name="email_created_idx"),
            models.Index(fields=["sent_at"], name="email_sent_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["payment_transaction"],
                condition=models.Q(payment_transaction__isnull=False),
                name="unique_email_per_payment",
            )
        ]

    def can_retry(self):
        retry_due = self.next_retry_at is None or self.next_retry_at <= timezone.now()
        return (
            self.status in {self.STATUS_PENDING, self.STATUS_FAILED}
            and self.attempt_count < self.max_attempts
            and retry_due
        )

    def mark_failed(self, error_message):
        self.status = self.STATUS_FAILED
        self.attempt_count += 1
        self.last_error = str(error_message)[:1000]
        retry_minutes_by_attempt = {
            1: 1,
            2: 5,
            3: 15,
        }
        if self.attempt_count < self.max_attempts:
            retry_minutes = retry_minutes_by_attempt.get(self.attempt_count, 15)
            self.next_retry_at = timezone.now() + timedelta(minutes=retry_minutes)
        else:
            self.next_retry_at = None
        self.save(
            update_fields=[
                "status",
                "attempt_count",
                "last_error",
                "next_retry_at",
                "updated_at",
            ]
        )

    def mark_sent(self, provider_message_id=None):
        self.status = self.STATUS_SENT
        self.sent_at = timezone.now()
        self.next_retry_at = None
        self.last_error = ""
        if provider_message_id:
            self.provider_message_id = provider_message_id
        self.save(
            update_fields=[
                "status",
                "sent_at",
                "next_retry_at",
                "last_error",
                "provider_message_id",
                "updated_at",
            ]
        )

    def __str__(self):
        return f'Booking email to {self.recipient_email} ({self.status})'
