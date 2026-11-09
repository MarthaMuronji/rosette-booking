from django.contrib import admin
from .models import Appointment, ClientPackage, BlockedDate, BlockedTimeRange

admin.site.register(Appointment)
admin.site.register(ClientPackage)
admin.site.register(BlockedDate)
admin.site.register(BlockedTimeRange)
