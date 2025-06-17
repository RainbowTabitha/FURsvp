from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'),
    path('event/<int:event_id>/edit/', views.edit_event, name='edit_event'),
    path('event/<int:event_id>/uncancel/', views.uncancel_event, name='uncancel_event'),
    path('create-event/', views.create_event, name='create_event'),
    path('terms/', views.terms, name='terms'),
    path('faq/', views.faq, name='faq'),
    path('eula/', views.eula, name='eula'),
    path('privacy/', views.privacy, name='privacy'),
] 