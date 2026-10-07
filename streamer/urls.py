from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    path("health", views.health, name="health"),
    path("snapshot.jpg", views.snapshot, name="snapshot"),
    path("stream.mjpg", views.stream, name="stream"),
]
