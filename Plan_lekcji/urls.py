"""
URL configuration for Plan_lekcji project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from .views import (
    index, grupy_lekcyjne, wymagania,
    ograniczenia_nauczycieli, ograniczenia_klas_view, toggle_ograniczenie,
    # Nowe importy CRUD
    lista_nauczycieli, edytuj_nauczyciela, usun_nauczyciela,
    lista_przedmiotow, edytuj_przedmiot, usun_przedmiot,
    lista_klas, edytuj_klase, usun_klase,edytuj_wymaganie, usun_wymaganie,
    edytuj_grupe, usun_grupe
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', index, name='index'),               # Teraz index to Plan
    path('wymagania/', wymagania, name='wymagania'),
    path('wymagania/dodaj/', edytuj_wymaganie, name='dodaj_wymaganie'),
    path('wymagania/edytuj/<int:pk>/', edytuj_wymaganie, name='edytuj_wymaganie'),
    path('wymagania/usun/<int:pk>/', usun_wymaganie, name='usun_wymaganie'),

    path('grupy/', grupy_lekcyjne, name='grupy'),
    path('grupy/dodaj/', edytuj_grupe, name='dodaj_grupe'),
    path('grupy/edytuj/<int:pk>/', edytuj_grupe, name='edytuj_grupe'),
    path('grupy/usun/<int:pk>/', usun_grupe, name='usun_grupe'),
path('ograniczenia/nauczyciele/', ograniczenia_nauczycieli, name='ograniczenia_nauczycieli'),
    path('ograniczenia/klasy/', ograniczenia_klas_view, name='ograniczenia_klas'),
    path('api/toggle-ograniczenie/', toggle_ograniczenie, name='toggle_ograniczenie'),

# CRUD Nauczyciele
    path('nauczyciele/', lista_nauczycieli, name='lista_nauczycieli'),
    path('nauczyciele/dodaj/', edytuj_nauczyciela, name='dodaj_nauczyciela'),
    path('nauczyciele/edytuj/<int:pk>/', edytuj_nauczyciela, name='edytuj_nauczyciela'),
    path('nauczyciele/usun/<int:pk>/', usun_nauczyciela, name='usun_nauczyciela'),

    # CRUD Przedmioty
    path('przedmioty/', lista_przedmiotow, name='lista_przedmiotow'),
    path('przedmioty/dodaj/', edytuj_przedmiot, name='dodaj_przedmiot'),
    path('przedmioty/edytuj/<int:pk>/', edytuj_przedmiot, name='edytuj_przedmiot'),
    path('przedmioty/usun/<int:pk>/', usun_przedmiot, name='usun_przedmiot'),

    # CRUD Klasy (pk dla klasy to string!)
    path('klasy/', lista_klas, name='lista_klas'),
    path('klasy/dodaj/', edytuj_klase, name='dodaj_klase'),
    path('klasy/edytuj/<str:pk>/', edytuj_klase, name='edytuj_klase'),
    path('klasy/usun/<str:pk>/', usun_klase, name='usun_klase'),
]