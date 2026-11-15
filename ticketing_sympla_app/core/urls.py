from django.urls import path
from .views import ping, update

#Determina qual endpoint, usa qual classe de views
urlpatterns = [
    path("ping/", ping),
    path("update/", update),
]
