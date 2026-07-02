from django.urls import path
from . import views
urlpatterns=[
    path('',views.movie_list,name='movie_list'),
    path('<int:movie_id>/',views.movie_detail,name='movie_detail'),
    path('<int:movie_id>/theaters',views.theater_list,name='theater_list'),
    path('theater/<int:theater_id>/seats/book/',views.book_seats,name='book_seats'),
    path('theater/<int:theater_id>/seats/reserve/',views.reserve_seats,name='reserve_seats'),
    path('reservations/<uuid:reservation_token>/confirm/',views.confirm_reservation,name='reservation_confirm'),
    path('reservations/<uuid:reservation_token>/payment/verify/',views.verify_payment,name='payment_verify'),
    path('reservations/<uuid:reservation_token>/payment/cancel/',views.payment_cancelled,name='payment_cancelled'),
    path('reservations/<uuid:reservation_token>/payment/status/',views.payment_status,name='payment_status'),
    path('payments/razorpay/webhook/',views.razorpay_webhook,name='razorpay_webhook'),
]
