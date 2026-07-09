from django.contrib import admin
from django.urls import path, include
from bookings import views as booking_views
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/book/'), name='home'),
    path('', include('bookings.urls')),
    path('sw.js', booking_views.service_worker, name='service_worker'),
]