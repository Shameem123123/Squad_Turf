from django.urls import path

from . import views

urlpatterns = [
    # Auth (passwordless: name + phone + OTP)
    path('signup/', views.signup, name='signup'),
    path('login/', views.login_view, name='login'),
    path('verify/', views.verify_otp, name='verify_otp'),
    path('verify/resend/', views.resend_otp, name='resend_otp'),
    path('logout/', views.logout_view, name='logout'),

    # Feed & turf discovery
    path('', views.feed, name='feed'),
    path('turfs/', views.turf_directory, name='turf_directory'),
    path('t/<slug:slug>/', views.turf_landing, name='turf_landing'),

    # Match lifecycle
    path('match/create/', views.create_match, name='create_match'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('match/<int:match_id>/join/', views.join_match, name='join_match'),
    path('match/<int:match_id>/cancel-request/', views.cancel_join_request, name='cancel_join_request'),
    path('match/<int:match_id>/leave/', views.leave_match, name='leave_match'),
    path('match/<int:match_id>/cancel/', views.cancel_match, name='cancel_match'),
    path('match/<int:match_id>/rate/', views.submit_rating, name='submit_rating'),
    path('request/<int:request_id>/<str:action>/', views.respond_request, name='respond_request'),

    # Dashboards & profile
    path('my-hosted/', views.my_hosted, name='my_hosted'),
    path('my-joined/', views.my_joined, name='my_joined'),
    path('profile/', views.profile, name='profile'),

    # Notifications & Web Push
    path('notifications/', views.notification_list, name='notification_list'),
    path('push/subscribe/', views.push_subscribe, name='push_subscribe'),
    path('push/unsubscribe/', views.push_unsubscribe, name='push_unsubscribe'),
    path('push/vapid-public-key/', views.vapid_public_key, name='vapid_public_key'),
]
