import uuid
from datetime import timedelta

from django.http import Http404
from django.shortcuts import render, redirect ,get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Movie,Theater,Seat,Booking,SeatReservation
from .validators import extract_youtube_video_id


RESERVATION_MINUTES = 2

def movie_list(request):
    search_query=request.GET.get('search')
    if search_query:
        movies=Movie.objects.filter(name__icontains=search_query)
    else:
        movies=Movie.objects.all()
    return render(request,'movies/movie_list.html',{'movies':movies})

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
        return render(
            request,
            'movies/reservation_confirm.html',
            _reservation_context(reservations),
        )

    error_message = None
    expired = False

    try:
        with transaction.atomic():
            reservations = list(
                SeatReservation.objects.select_for_update()
                .select_related('seat', 'theater', 'movie')
                .filter(reservation_token=reservation_token, user=request.user)
                .order_by('seat__seat_number')
            )
            if not reservations:
                raise Http404("Reservation not found")

            now = timezone.now()
            if not all(reservation.status == SeatReservation.STATUS_RESERVED for reservation in reservations):
                expired = True
                error_message = 'This reservation is no longer active.'
            elif any(reservation.expires_at <= now for reservation in reservations):
                SeatReservation.objects.filter(
                    id__in=[reservation.id for reservation in reservations],
                    status=SeatReservation.STATUS_RESERVED,
                ).update(status=SeatReservation.STATUS_EXPIRED)
                expired = True
                error_message = 'This reservation has expired. Please select seats again.'
            else:
                seat_ids = [reservation.seat_id for reservation in reservations]
                seats = list(
                    Seat.objects.select_for_update()
                    .filter(id__in=seat_ids)
                    .order_by('id')
                )

                if len(seats) != len(seat_ids):
                    expired = True
                    error_message = 'This reservation is no longer valid.'
                elif any(seat.is_booked for seat in seats):
                    expired = True
                    error_message = 'One or more seats are already booked.'
                elif Booking.objects.filter(seat_id__in=seat_ids).exists():
                    expired = True
                    error_message = 'One or more seats are already booked.'
                else:
                    seats_by_id = {seat.id: seat for seat in seats}
                    for reservation in reservations:
                        seat = seats_by_id[reservation.seat_id]
                        Booking.objects.create(
                            user=request.user,
                            seat=seat,
                            movie=reservation.movie,
                            theater=reservation.theater,
                        )
                        seat.is_booked=True
                        seat.save(update_fields=['is_booked'])
                        reservation.status=SeatReservation.STATUS_CONFIRMED
                        reservation.confirmed_at=now
                        reservation.save(update_fields=['status','confirmed_at'])
    except IntegrityError:
        expired = True
        error_message = 'One or more seats are already booked.'

    if error_message:
        reservations = _get_user_reservations_or_404(reservation_token, request.user)
        return render(
            request,
            'movies/reservation_confirm.html',
            _reservation_context(reservations, error_message, expired=expired),
        )

    return redirect('profile')
