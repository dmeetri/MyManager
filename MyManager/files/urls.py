from django.urls import path

from . import views

urlpatterns = [
    path('list/', views.ListFilesView.as_view(), name='list'),
]
