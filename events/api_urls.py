from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import GroupViewSet, EventViewSet, UserViewSet, CustomAPIRootView

# Create a router and register our viewsets with it
router = DefaultRouter()
router.APIRootView = CustomAPIRootView
router.register(r'groups', GroupViewSet)
router.register(r'events', EventViewSet)
router.register(r'users', UserViewSet)

# The API URLs are now determined automatically by the router
urlpatterns = [
    path('', include(router.urls)),
] 