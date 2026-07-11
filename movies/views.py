import hashlib
import hmac
import json
import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render, redirect ,get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from .analytics import can_view_analytics, get_cached_admin_analytics
from .models import (
    Booking,
    Genre,
    Language,
    Movie,
    PaymentTransaction,
    PaymentWebhookEvent,
    Seat,
    SeatReservation,
    Theater,
)
from .validators import extract_youtube_video_id


logger = logging.getLogger(__name__)

RESERVATION_MINUTES = 2
MOVIE_PAGE_SIZE = 12
MOVIE_SORT_OPTIONS = {
    'default': '-id',
    'title_asc': 'name',
    'title_desc': '-name',
    'rating_desc': '-rating',
    'rating_asc': 'rating',
}
MOVIE_SORT_LABELS = [
    ('default', 'Newest'),
    ('title_asc', 'Title A-Z'),
    ('title_desc', 'Title Z-A'),
    ('rating_desc', 'Rating high to low'),
    ('rating_asc', 'Rating low to high'),
    ('popular', 'Most booked'),
]


def apply_movie_search(queryset, search_query):
    search_query = (search_query or '').strip()
    if search_query:
        return queryset.filter(name__icontains=search_query)
    return queryset


def apply_genre_filter(queryset, selected_genres):
    if selected_genres:
        # Genre is many-to-many, so distinct avoids duplicate movie rows after the join.
        return queryset.filter(genres__slug__in=selected_genres).distinct()
    return queryset


def apply_language_filter(queryset, selected_languages):
    if selected_languages:
        # Language is a ForeignKey, so multi-select stays a simple indexed IN lookup.
        return queryset.filter(language__code__in=selected_languages)
    return queryset


def _selected_params(request, key):
    return [value for value in request.GET.getlist(key) if value]


def _querystring_without_page(request):
    params = request.GET.copy()
    params.pop('page', None)
    encoded = params.urlencode()
    return f'{encoded}&' if encoded else ''

def movie_list(request):
    search_query=(request.GET.get('search') or '').strip()
    selected_genres = _selected_params(request, 'genres')
    selected_languages = _selected_params(request, 'languages')
    requested_sort = request.GET.get('sort', 'default')
    selected_sort = requested_sort if requested_sort in dict(MOVIE_SORT_LABELS) else 'default'

    movies = Movie.objects.all()
    movies = apply_movie_search(movies, search_query)
    movies = apply_genre_filter(movies, selected_genres)
    movies = apply_language_filter(movies, selected_languages)

    if selected_sort == 'popular':
        movies = movies.annotate(
            booking_count=Count('booking', distinct=True)
        ).order_by('-booking_count', 'name')
    else:
        movies = movies.order_by(MOVIE_SORT_OPTIONS[selected_sort])

    # Dynamic counts are calculated before pagination and with database aggregation.
    genre_count_movies = Movie.objects.all()
    genre_count_movies = apply_movie_search(genre_count_movies, search_query)
    genre_count_movies = apply_language_filter(genre_count_movies, selected_languages)
    genre_filters = Genre.objects.filter(
        movies__in=genre_count_movies
    ).annotate(
        movie_count=Count('movies', distinct=True)
    ).order_by('name')

    language_count_movies = Movie.objects.all()
    language_count_movies = apply_movie_search(language_count_movies, search_query)
    language_count_movies = apply_genre_filter(language_count_movies, selected_genres)
    language_filters = Language.objects.filter(
        movies__in=language_count_movies
    ).annotate(
        movie_count=Count('movies', distinct=True)
    ).order_by('name')

    movies = movies.select_related('language').prefetch_related('genres')
    paginator = Paginator(movies, MOVIE_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    selected_genre_names = list(
        Genre.objects.filter(slug__in=selected_genres).values_list('name', flat=True)
    )
    selected_language_names = list(
        Language.objects.filter(code__in=selected_languages).values_list('name', flat=True)
    )

    context = {
        'movies':page_obj.object_list,
        'page_obj':page_obj,
        'genre_filters':genre_filters,
        'language_filters':language_filters,
        'selected_genres':selected_genres,
        'selected_languages':selected_languages,
        'selected_genre_names':selected_genre_names,
        'selected_language_names':selected_language_names,
        'search_query':search_query,
        'selected_sort':selected_sort,
        'sort_options':MOVIE_SORT_LABELS,
        'querystring_without_page':_querystring_without_page(request),
        'result_count':paginator.count,
    }
    return render(request,'movies/movie_list.html',context)

def movie_detail(request,movie_id):
    movie = get_object_or_404(Movie,id=movie_id)
    video_id = extract_youtube_video_id(movie.trailer_url)
    trailer_embed_url = None
    if video_id:
        trailer_embed_url = f'https://www.youtube.com/embed/{video_id}'
    return render(
        request,
        'movies/movie_detail.html',
        {'movie':movie,'trailer_embed_url':trailer_embed_url},
    )

def theater_list(request,movie_id):
    movie = get_object_or_404(Movie,id=movie_id)
    theaters=Theater.objects.filter(movie=movie)
    return render(request,'movies/theater_list.html',{'movie':movie,'theaters':theaters})


@login_required(login_url='/login/')
@never_cache
def admin_dashboard(request):
    if not can_view_analytics(request.user):
        raise PermissionDenied("You do not have permission to view analytics.")
    analytics = get_cached_admin_analytics()
    return render(request,'movies/admin_dashboard.html',{'analytics':analytics})


@login_required(login_url='/login/')
@never_cache
def admin_dashboard_api(request):
    if not can_view_analytics(request.user):
        return JsonResponse({'detail':'Forbidden'}, status=403)
    analytics = get_cached_admin_analytics()
    return JsonResponse(analytics, safe=True)


def _expire_reservations(now=None, theater=None, seat_ids=None, reservation_token=None, user=None):
    now = now or timezone.now()
    reservations = SeatReservation.objects.filter(
        status=SeatReservation.STATUS_RESERVED,
        expires_at__lte=now,
    )
    if theater is not None:
        reservations = reservations.filter(theater=theater)
    if seat_ids is not None:
        reservations = reservations.filter(seat_id__in=seat_ids)
    if reservation_token is not None:
        reservations = reservations.filter(reservation_token=reservation_token)
    if user is not None:
        reservations = reservations.filter(user=user)
    return reservations.update(status=SeatReservation.STATUS_EXPIRED)


def _get_active_reserved_seat_ids(theater, now=None):
    now = now or timezone.now()
    return list(
        SeatReservation.objects.filter(
            theater=theater,
            status=SeatReservation.STATUS_RESERVED,
            expires_at__gt=now,
        ).values_list('seat_id', flat=True)
    )


def _seat_selection_context(theater, error=None):
    now = timezone.now()
    _expire_reservations(now=now, theater=theater)
    seats=Seat.objects.filter(theater=theater)
    context={
        'theater':theater,
        'theaters':theater,
        'seats':seats,
        'active_reserved_seat_ids':_get_active_reserved_seat_ids(theater, now=now),
    }
    if error:
        context['error'] = error
    return context


def _parse_selected_seat_ids(raw_seat_ids):
    selected_ids = set()
    try:
        for raw_id in raw_seat_ids:
            seat_id = int(raw_id)
            if seat_id <= 0:
                return None
            selected_ids.add(seat_id)
    except (TypeError, ValueError):
        return None
    return list(selected_ids)


def _get_user_reservations_or_404(reservation_token, user):
    reservations = list(
        SeatReservation.objects.select_related('seat', 'theater', 'movie')
        .filter(reservation_token=reservation_token, user=user)
        .order_by('seat__seat_number')
    )
    if not reservations:
        raise Http404("Reservation not found")
    return reservations


def _reservation_context(reservations, error=None, expired=False):
    context = {
        'reservations':reservations,
        'movie':reservations[0].movie,
        'theater':reservations[0].theater,
        'expires_at':reservations[0].expires_at,
        'expired':expired,
    }
    if error:
        context['error'] = error
    return context


def get_active_reservations_for_payment(reservation_token, user):
    reservations = _get_user_reservations_or_404(reservation_token, user)
    now = timezone.now()
    if any(reservation.status == SeatReservation.STATUS_RESERVED and reservation.expires_at <= now for reservation in reservations):
        _expire_reservations(now=now, reservation_token=reservation_token, user=user)
        reservations = _get_user_reservations_or_404(reservation_token, user)
        return None, 'This reservation has expired. Please select seats again.', True
    if not all(reservation.status == SeatReservation.STATUS_RESERVED for reservation in reservations):
        return None, 'This reservation is no longer active.', True
    return reservations, None, False


def calculate_reservation_amount(reservations):
    amount = len(reservations) * settings.TICKET_PRICE_PAISE
    return amount, settings.PAYMENT_CURRENCY


def create_razorpay_order(amount, currency, receipt, notes=None):
    import razorpay

    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
    return client.order.create(
        {
            'amount': amount,
            'currency': currency,
            'receipt': receipt,
            'payment_capture': 1,
            'notes': notes or {},
        }
    )


def get_or_create_payment_transaction(reservation_token, user):
    reservations, error, expired = get_active_reservations_for_payment(reservation_token, user)
    if error:
        return None, reservations, error, expired
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return (
            None,
            reservations,
            'Payment gateway is not configured. Add Razorpay test keys to environment variables.',
            False,
        )

    amount, currency = calculate_reservation_amount(reservations)
    existing = (
        PaymentTransaction.objects.filter(
            reservation_token=reservation_token,
            user=user,
            status=PaymentTransaction.STATUS_CREATED,
            amount=amount,
            currency=currency,
        )
        .order_by('-created_at')
        .first()
    )
    if existing:
        return existing, reservations, None, False

    try:
        order = create_razorpay_order(
            amount=amount,
            currency=currency,
            receipt=f'resv_{str(reservation_token)[:32]}',
            notes={
                'reservation_token': str(reservation_token),
                'user_id': str(user.id),
            },
        )
    except Exception:
        return (
            None,
            reservations,
            'Unable to create Razorpay order. Check test keys and try again.',
            False,
        )
    razorpay_order_id = order['id']
    transaction_obj = PaymentTransaction.objects.create(
        user=user,
        reservation_token=reservation_token,
        razorpay_order_id=razorpay_order_id,
        amount=amount,
        currency=currency,
        status=PaymentTransaction.STATUS_CREATED,
        idempotency_key=f'reservation:{reservation_token}:razorpay_order:{razorpay_order_id}',
        raw_provider_payload={'order': order},
    )
    return transaction_obj, reservations, None, False


def verify_razorpay_checkout_signature(order_id, payment_id, signature):
    if not settings.RAZORPAY_KEY_SECRET or not order_id or not payment_id or not signature:
        return False
    message = f'{order_id}|{payment_id}'.encode('utf-8')
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
        message,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def verify_razorpay_webhook_signature(raw_body, signature):
    if not settings.RAZORPAY_WEBHOOK_SECRET or not signature:
        return False
    expected_signature = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode('utf-8'),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def _bookings_exist_for_reservations(reservations):
    seat_ids = [reservation.seat_id for reservation in reservations]
    return Booking.objects.filter(seat_id__in=seat_ids).count() == len(seat_ids)


def _enqueue_ticket_email_safely(payment_transaction_id):
    try:
        from .email_notifications import enqueue_booking_confirmation_email

        payment_transaction = PaymentTransaction.objects.get(pk=payment_transaction_id)
        enqueue_booking_confirmation_email(payment_transaction)
    except Exception as exc:
        logger.warning(
            "Booking succeeded, but ticket email could not be queued for payment %s: %s",
            payment_transaction_id,
            exc,
        )


def _enqueue_ticket_email_on_commit(payment_transaction):
    payment_transaction_id = payment_transaction.id
    transaction.on_commit(lambda: _enqueue_ticket_email_safely(payment_transaction_id))


def finalize_paid_reservation(payment_transaction, payment_payload=None):
    payload = payment_payload or {}
    try:
        with transaction.atomic():
            payment = PaymentTransaction.objects.select_for_update().get(
                pk=payment_transaction.pk
            )
            reservations = list(
                SeatReservation.objects.select_for_update()
                .select_related('seat', 'theater', 'movie')
                .filter(
                    reservation_token=payment.reservation_token,
                    user=payment.user,
                )
                .order_by('seat__seat_number')
            )
            if not reservations:
                payment.status = PaymentTransaction.STATUS_REQUIRES_REVIEW
                payment.raw_provider_payload = payload
                payment.save(update_fields=['status','raw_provider_payload','updated_at'])
                return False, 'Payment received but booking needs review. Please contact support.'

            if payment.status == PaymentTransaction.STATUS_CAPTURED and _bookings_exist_for_reservations(reservations):
                _enqueue_ticket_email_on_commit(payment)
                return True, 'Booking already confirmed.'

            now = timezone.now()
            if any(reservation.expires_at <= now for reservation in reservations):
                SeatReservation.objects.filter(
                    id__in=[reservation.id for reservation in reservations],
                    status=SeatReservation.STATUS_RESERVED,
                ).update(status=SeatReservation.STATUS_EXPIRED)
                payment.status = PaymentTransaction.STATUS_REQUIRES_REVIEW
                payment.raw_provider_payload = payload
                payment.verified_at = now
                payment.save(update_fields=['status','raw_provider_payload','verified_at','updated_at'])
                return False, 'Payment received after reservation expired. Please contact support.'

            if not all(reservation.status == SeatReservation.STATUS_RESERVED for reservation in reservations):
                if _bookings_exist_for_reservations(reservations):
                    payment.status = PaymentTransaction.STATUS_CAPTURED
                    payment.verified_at = payment.verified_at or now
                    payment.raw_provider_payload = payload or payment.raw_provider_payload
                    payment.save(update_fields=['status','verified_at','raw_provider_payload','updated_at'])
                    _enqueue_ticket_email_on_commit(payment)
                    return True, 'Booking already confirmed.'
                payment.status = PaymentTransaction.STATUS_REQUIRES_REVIEW
                payment.raw_provider_payload = payload
                payment.save(update_fields=['status','raw_provider_payload','updated_at'])
                return False, 'Payment received but booking needs review. Please contact support.'

            seat_ids = [reservation.seat_id for reservation in reservations]
            # select_for_update() gives row-level locking on PostgreSQL.
            # SQLite has limited row-level locking, but this code is production-ready for PostgreSQL.
            seats = list(
                Seat.objects.select_for_update()
                .filter(id__in=seat_ids)
                .order_by('id')
            )
            if len(seats) != len(seat_ids):
                payment.status = PaymentTransaction.STATUS_REQUIRES_REVIEW
                payment.raw_provider_payload = payload
                payment.save(update_fields=['status','raw_provider_payload','updated_at'])
                return False, 'Payment received but booking needs review. Please contact support.'

            existing_bookings = Booking.objects.filter(seat_id__in=seat_ids)
            if existing_bookings.exists() or any(seat.is_booked for seat in seats):
                if _bookings_exist_for_reservations(reservations):
                    payment.status = PaymentTransaction.STATUS_CAPTURED
                    payment.verified_at = payment.verified_at or now
                    payment.raw_provider_payload = payload or payment.raw_provider_payload
                    payment.save(update_fields=['status','verified_at','raw_provider_payload','updated_at'])
                    _enqueue_ticket_email_on_commit(payment)
                    return True, 'Booking already confirmed.'
                payment.status = PaymentTransaction.STATUS_REQUIRES_REVIEW
                payment.raw_provider_payload = payload
                payment.save(update_fields=['status','raw_provider_payload','updated_at'])
                return False, 'Payment received but booking needs review. Please contact support.'

            seats_by_id = {seat.id: seat for seat in seats}
            for reservation in reservations:
                seat = seats_by_id[reservation.seat_id]
                Booking.objects.create(
                    user=payment.user,
                    seat=seat,
                    movie=reservation.movie,
                    theater=reservation.theater,
                )
                seat.is_booked=True
                seat.save(update_fields=['is_booked'])
                reservation.status=SeatReservation.STATUS_CONFIRMED
                reservation.confirmed_at=now
                reservation.save(update_fields=['status','confirmed_at'])

            payment.status = PaymentTransaction.STATUS_CAPTURED
            payment.verified_at = now
            payment.raw_provider_payload = payload or payment.raw_provider_payload
            payment.save(update_fields=['status','verified_at','raw_provider_payload','updated_at'])
            _enqueue_ticket_email_on_commit(payment)
            return True, 'Booking confirmed.'
    except IntegrityError:
        PaymentTransaction.objects.filter(pk=payment_transaction.pk).update(
            status=PaymentTransaction.STATUS_REQUIRES_REVIEW,
            raw_provider_payload=payload,
        )
        return False, 'Payment received but booking needs review. Please contact support.'


@login_required(login_url='/login/')
def book_seats(request,theater_id):
    theater=get_object_or_404(Theater,id=theater_id)
    if request.method=='POST':
        return reserve_seats(request,theater_id)
    return render(request,'movies/seat_selection.html',_seat_selection_context(theater))


@login_required(login_url='/login/')
def reserve_seats(request,theater_id):
    theater=get_object_or_404(Theater,id=theater_id)
    if request.method != 'POST':
        return redirect('book_seats', theater_id=theater.id)

    selected_ids = _parse_selected_seat_ids(request.POST.getlist('seats'))
    if selected_ids is None:
        return render(
            request,
            'movies/seat_selection.html',
            _seat_selection_context(theater, 'Invalid seat selection. Please choose again.'),
        )
    if not selected_ids:
        return render(
            request,
            'movies/seat_selection.html',
            _seat_selection_context(theater, 'No seat selected'),
        )

    now = timezone.now()
    expires_at = now + timedelta(minutes=RESERVATION_MINUTES)
    reservation_token = uuid.uuid4()
    error_message = None

    with transaction.atomic():
        _expire_reservations(now=now, seat_ids=selected_ids)

        # select_for_update() gives row-level locking on PostgreSQL.
        # SQLite has limited row-level locking, but this keeps the flow production-ready.
        seats = list(
            Seat.objects.select_for_update()
            .filter(id__in=selected_ids, theater=theater)
            .order_by('id')
        )

        if len(seats) != len(selected_ids):
            error_message = 'Some selected seats are no longer available. Please choose again.'
        elif any(seat.is_booked for seat in seats):
            error_message = 'Some selected seats are no longer available. Please choose again.'
        elif SeatReservation.objects.select_for_update().filter(
            seat_id__in=selected_ids,
            status=SeatReservation.STATUS_RESERVED,
            expires_at__gt=now,
        ).exists():
            error_message = 'Some selected seats are no longer available. Please choose again.'
        else:
            for seat in seats:
                SeatReservation.objects.create(
                    user=request.user,
                    seat=seat,
                    theater=theater,
                    movie=theater.movie,
                    status=SeatReservation.STATUS_RESERVED,
                    expires_at=expires_at,
                    reservation_token=reservation_token,
                )

    if error_message:
        return render(
            request,
            'movies/seat_selection.html',
            _seat_selection_context(theater, error_message),
        )

    return redirect('reservation_confirm', reservation_token=reservation_token)


@login_required(login_url='/login/')
def confirm_reservation(request,reservation_token):
    reservations = _get_user_reservations_or_404(reservation_token, request.user)
    now = timezone.now()

    if request.method == 'GET':
        if any(reservation.status == SeatReservation.STATUS_RESERVED and reservation.expires_at <= now for reservation in reservations):
            _expire_reservations(now=now, reservation_token=reservation_token, user=request.user)
            reservations = _get_user_reservations_or_404(reservation_token, request.user)
            return render(
                request,
                'movies/reservation_confirm.html',
                _reservation_context(
                    reservations,
                    'This reservation has expired. Please select seats again.',
                    expired=True,
                ),
            )
        if not all(reservation.status == SeatReservation.STATUS_RESERVED for reservation in reservations):
            return render(
                request,
                'movies/reservation_confirm.html',
                _reservation_context(
                    reservations,
                    'This reservation is no longer active.',
                    expired=True,
                ),
            )
        payment_transaction, active_reservations, payment_error, expired = get_or_create_payment_transaction(
            reservation_token,
            request.user,
        )
        reservations = active_reservations or reservations
        context = _reservation_context(
            reservations,
            payment_error,
            expired=expired,
        )
        amount, currency = calculate_reservation_amount(reservations)
        context.update(
            {
                'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                'razorpay_order_id': payment_transaction.razorpay_order_id if payment_transaction else '',
                'amount': amount,
                'amount_rupees': amount / 100,
                'currency': currency,
                'payment_transaction': payment_transaction,
                'payment_configured': bool(payment_transaction and not payment_error),
            }
        )
        return render(request,'movies/reservation_confirm.html',context)

    reservations, error, expired = get_active_reservations_for_payment(
        reservation_token,
        request.user,
    )
    if error:
        reservations = _get_user_reservations_or_404(reservation_token, request.user)
    return render(
        request,
        'movies/reservation_confirm.html',
        _reservation_context(
            reservations,
            error or 'Payment verification is required before booking confirmation.',
            expired=expired,
        ),
    )


@login_required(login_url='/login/')
def verify_payment(request,reservation_token):
    if request.method != 'POST':
        return redirect('payment_status', reservation_token=reservation_token)

    order_id = request.POST.get('razorpay_order_id', '')
    payment_id = request.POST.get('razorpay_payment_id', '')
    signature = request.POST.get('razorpay_signature', '')
    payload = {
        'checkout': {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature,
        }
    }

    payment_transaction = get_object_or_404(
        PaymentTransaction,
        reservation_token=reservation_token,
        user=request.user,
        razorpay_order_id=order_id,
    )
    reservations = _get_user_reservations_or_404(reservation_token, request.user)

    if payment_transaction.status == PaymentTransaction.STATUS_CAPTURED and _bookings_exist_for_reservations(reservations):
        _enqueue_ticket_email_safely(payment_transaction.id)
        return redirect('profile')

    if not verify_razorpay_checkout_signature(order_id, payment_id, signature):
        payment_transaction.status = PaymentTransaction.STATUS_FAILED
        payment_transaction.raw_provider_payload = payload
        payment_transaction.save(update_fields=['status','raw_provider_payload','updated_at'])
        return redirect('payment_status', reservation_token=reservation_token)

    duplicate_payment = (
        PaymentTransaction.objects.exclude(pk=payment_transaction.pk)
        .filter(razorpay_payment_id=payment_id)
        .exists()
    )
    if duplicate_payment:
        payment_transaction.status = PaymentTransaction.STATUS_REQUIRES_REVIEW
        payment_transaction.raw_provider_payload = payload
        payment_transaction.save(update_fields=['status','raw_provider_payload','updated_at'])
        return redirect('payment_status', reservation_token=reservation_token)

    payment_transaction.razorpay_payment_id = payment_id
    payment_transaction.raw_provider_payload = payload
    payment_transaction.save(update_fields=['razorpay_payment_id','raw_provider_payload','updated_at'])

    success, message = finalize_paid_reservation(payment_transaction, payload)
    if success:
        return redirect('profile')
    return redirect('payment_status', reservation_token=reservation_token)


@login_required(login_url='/login/')
def payment_cancelled(request,reservation_token):
    if request.method != 'POST':
        return redirect('payment_status', reservation_token=reservation_token)

    transaction_obj = (
        PaymentTransaction.objects.filter(
            reservation_token=reservation_token,
            user=request.user,
            status=PaymentTransaction.STATUS_CREATED,
        )
        .order_by('-created_at')
        .first()
    )
    if transaction_obj:
        transaction_obj.status = PaymentTransaction.STATUS_CANCELLED
        transaction_obj.save(update_fields=['status','updated_at'])
    return JsonResponse({'ok': True})


@login_required(login_url='/login/')
def payment_status(request,reservation_token):
    transactions = PaymentTransaction.objects.filter(
        reservation_token=reservation_token,
        user=request.user,
    ).order_by('-created_at')
    transaction_obj = transactions.first()
    reservations = _get_user_reservations_or_404(reservation_token, request.user)
    return render(
        request,
        'movies/payment_status.html',
        {
            'payment_transaction': transaction_obj,
            'reservations': reservations,
            'movie': reservations[0].movie,
            'theater': reservations[0].theater,
        },
    )


def _webhook_event_id(payload, raw_body):
    event_id = payload.get('id')
    if event_id:
        return event_id
    entity = _webhook_payment_entity(payload) or _webhook_order_entity(payload) or {}
    entity_id = entity.get('id', '')
    event_type = payload.get('event', 'unknown')
    if entity_id:
        return f'{event_type}:{entity_id}'
    return hashlib.sha256(raw_body).hexdigest()


def _webhook_payment_entity(payload):
    return payload.get('payload', {}).get('payment', {}).get('entity')


def _webhook_order_entity(payload):
    return payload.get('payload', {}).get('order', {}).get('entity')


def _find_transaction_for_webhook(payment_entity=None, order_entity=None):
    payment_entity = payment_entity or {}
    order_entity = order_entity or {}
    payment_id = payment_entity.get('id')
    order_id = payment_entity.get('order_id') or order_entity.get('id')
    transaction_qs = PaymentTransaction.objects.all()
    if payment_id:
        transaction_obj = transaction_qs.filter(razorpay_payment_id=payment_id).first()
        if transaction_obj:
            return transaction_obj
    if order_id:
        return transaction_qs.filter(razorpay_order_id=order_id).first()
    return None


@csrf_exempt
def razorpay_webhook(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    raw_body = request.body
    signature = request.headers.get('X-Razorpay-Signature', '')
    if not verify_razorpay_webhook_signature(raw_body, signature):
        return HttpResponseBadRequest('Invalid webhook signature')

    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON')

    event_type = payload.get('event', 'unknown')
    event_id = _webhook_event_id(payload, raw_body)

    try:
        webhook_event, created = PaymentWebhookEvent.objects.get_or_create(
            provider='razorpay',
            event_id=event_id,
            defaults={
                'event_type': event_type,
                'raw_payload': payload,
                'signature_valid': True,
            },
        )
    except IntegrityError:
        return JsonResponse({'ok': True, 'duplicate': True})

    if not created:
        return JsonResponse({'ok': True, 'duplicate': True})

    payment_entity = _webhook_payment_entity(payload)
    order_entity = _webhook_order_entity(payload)
    transaction_obj = _find_transaction_for_webhook(payment_entity, order_entity)
    supported_events = {'payment.captured', 'payment.failed', 'order.paid'}

    if event_type not in supported_events:
        webhook_event.processing_status = PaymentWebhookEvent.STATUS_PROCESSED
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=['processing_status','processed_at'])
        return JsonResponse({'ok': True, 'ignored': True})

    if not transaction_obj:
        webhook_event.processing_status = PaymentWebhookEvent.STATUS_FAILED
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=['processing_status','processed_at'])
        return JsonResponse({'ok': True, 'transaction_found': False})

    raw_payload = {'webhook': payload}
    if event_type == 'payment.failed':
        if not transaction_obj.is_finalized():
            transaction_obj.status = PaymentTransaction.STATUS_FAILED
            transaction_obj.raw_provider_payload = raw_payload
            transaction_obj.save(update_fields=['status','raw_provider_payload','updated_at'])
        webhook_event.processing_status = PaymentWebhookEvent.STATUS_PROCESSED
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=['processing_status','processed_at'])
        return JsonResponse({'ok': True})

    payment_id = (payment_entity or {}).get('id')
    if payment_id and not transaction_obj.razorpay_payment_id:
        transaction_obj.razorpay_payment_id = payment_id
        transaction_obj.raw_provider_payload = raw_payload
        transaction_obj.save(update_fields=['razorpay_payment_id','raw_provider_payload','updated_at'])

    finalize_paid_reservation(transaction_obj, raw_payload)
    webhook_event.processing_status = PaymentWebhookEvent.STATUS_PROCESSED
    webhook_event.processed_at = timezone.now()
    webhook_event.save(update_fields=['processing_status','processed_at'])
    return JsonResponse({'ok': True})
