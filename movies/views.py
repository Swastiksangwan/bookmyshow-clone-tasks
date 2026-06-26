from django.shortcuts import render, redirect ,get_object_or_404
from .models import Movie,Theater,Seat,Booking
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from .validators import extract_youtube_video_id

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



@login_required(login_url='/login/')
def book_seats(request,theater_id):
    theater=get_object_or_404(Theater,id=theater_id)
    seats=Seat.objects.filter(theater=theater)
    context={'theater':theater,'theaters':theater,'seats':seats}
    if request.method=='POST':
        selected_seats= request.POST.getlist('seats')
        error_seats=[]
        if not selected_seats:
            context['error']="No seat selected"
            return render(request,"movies/seat_selection.html",context)
        for seat_id in selected_seats:
            seat=get_object_or_404(Seat,id=seat_id,theater=theater)
            if seat.is_booked:
                error_seats.append(seat.seat_number)
                continue
            try:
                Booking.objects.create(
                    user=request.user,
                    seat=seat,
                    movie=theater.movie,
                    theater=theater
                )
                seat.is_booked=True
                seat.save()
            except IntegrityError:
                error_seats.append(seat.seat_number)
        if error_seats:
            error_message=f"The following seats are already booked:{',',join(error_seats)}"
            context['error']=error_message
            return render(request,'movies/seat_selection.html',context)
        return redirect('profile')
    return render(request,'movies/seat_selection.html',context)


