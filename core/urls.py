from django.urls import path

from . import views

urlpatterns = [
    # Auth
    path('signup/', views.signup, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Feed & turf QR landing
    path('', views.feed, name='feed'),
    path('t/<slug:slug>/', views.turf_landing, name='turf_landing'),

    # Match lifecycle
    path('match/create/', views.create_match, name='create_match'),
    path('match/<int:match_id>/', views.match_detail, name='match_detail'),
    path('match/<int:match_id>/join/', views.join_match, name='join_match'),
    path('match/<int:match_id>/cancel/', views.cancel_join_request, name='cancel_join_request'),
    path('match/<int:match_id>/leave/', views.leave_match, name='leave_match'),
    path('match/<int:match_id>/rate/', views.submit_rating, name='submit_rating'),
    path('request/<int:request_id>/<str:action>/', views.respond_request, name='respond_request'),

    # Dashboards
    path('my-hosted/', views.my_hosted, name='my_hosted'),
    path('my-joined/', views.my_joined, name='my_joined'),
]
