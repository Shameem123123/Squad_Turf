from django.contrib import admin
from django.urls import path, include

from core.views import service_worker

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sw.js', service_worker, name='service_worker'),
    path('', include('core.urls')),
]
