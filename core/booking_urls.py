from django.urls import path

from . import booking_views as v

urlpatterns = [
    # players
    path('book/', v.book_directory, name='book_directory'),
    path('book/<slug:slug>/', v.book_turf, name='book_turf'),
    path('book/<slug:slug>/confirm/', v.book_confirm, name='book_confirm'),
    path('api/book/<slug:slug>/slots/', v.book_slots_api, name='book_slots_api'),
    path('bookings/', v.my_bookings, name='my_bookings'),
    path('bookings/<str:ref>/', v.booking_detail, name='booking_detail'),
    path('bookings/<str:ref>/cancel/', v.booking_cancel, name='booking_cancel'),
    path('bookings/<str:ref>/calendar.ics', v.booking_ics, name='booking_ics'),
    # turf admin console
    path('manage/', v.manage_home, name='manage_home'),
    path('manage/<slug:slug>/', v.manage_schedule, name='manage_schedule'),
    path('manage/<slug:slug>/bookings/', v.manage_bookings, name='manage_bookings'),
    path('manage/<slug:slug>/scan/', v.manage_scan, name='manage_scan'),
    path('manage/<slug:slug>/settings/', v.manage_settings, name='manage_settings'),
    path('manage/<slug:slug>/walkin/', v.manage_walkin, name='manage_walkin'),
    path('manage/<slug:slug>/block/', v.manage_block, name='manage_block'),
    path('manage/<slug:slug>/unblock/', v.manage_unblock, name='manage_unblock'),
    path('manage/<slug:slug>/close-day/', v.manage_close_day, name='manage_close_day'),
    path('manage/<slug:slug>/reopen-day/', v.manage_reopen_day, name='manage_reopen_day'),
    path('manage/<slug:slug>/booking/<str:ref>/cancel/', v.manage_booking_cancel, name='manage_booking_cancel'),
    path('manage/<slug:slug>/booking/<str:ref>/paid/', v.manage_booking_paid, name='manage_booking_paid'),
    path('api/manage/<slug:slug>/slots/', v.manage_slots_api, name='manage_slots_api'),
    path('api/manage/<slug:slug>/scan/', v.manage_scan_api, name='manage_scan_api'),
    path('api/manage/<slug:slug>/scan/admit/', v.manage_scan_admit, name='manage_scan_admit'),
]
