from django.urls import path
from . import views

urlpatterns = [
    path('', views.book_request, name='home'),
    path('book/', views.book_request, name='book'),
    path('book/confirm/<int:pk>/', views.book_confirm, name='book_confirm'),
    path('book/success/<int:pk>/', views.book_success, name='book_success'),
    path('book/reschedule/<int:pk>/', views.reschedule_appointment, name='reschedule_appointment'),
    path('masseuse/login/', views.masseuse_login, name='masseuse_login'),
    path('masseuse/logout/', views.masseuse_logout, name='masseuse_logout'),
    path('masseuse/', views.masseuse_dashboard, name='masseuse_dashboard'),
    path('masseuse/approve/<int:pk>/', views.approve_appointment, name='approve_appointment'),
    path('masseuse/decline/<int:pk>/', views.decline_appointment, name='decline_appointment'),
    path('masseuse/complete/<int:pk>/', views.complete_appointment, name='complete_appointment'),
]