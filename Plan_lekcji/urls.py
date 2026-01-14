from django.contrib import admin
from django.urls import path, include
from .views import (
    index,
    # Wymagania
    wymagania, edytuj_wymaganie, usun_wymaganie,
    # Grupy
    grupy_lekcyjne, edytuj_grupe, usun_grupe,
    # Ograniczenia
    ograniczenia_nauczycieli, ograniczenia_klas_view, toggle_ograniczenie,
    # Nauczyciele CRUD
    lista_nauczycieli, edytuj_nauczyciela, usun_nauczyciela,
    # Przedmioty CRUD
    lista_przedmiotow, edytuj_przedmiot, usun_przedmiot,
    # Klasy CRUD
    lista_klas, edytuj_klase, usun_klase, edytuj_pojedyncza_lekcje, api_zamien_lekcje
)

urlpatterns = [
    # --- PANEL ADMINA I LOGOWANIE ---
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')), # To obsługuje /login/ i /logout/

    # --- STRONA GŁÓWNA (PLAN LEKCJI) ---
    path('', index, name='index'),

    # --- WYMAGANIA PRZEDMIOTOWE ---
    path('wymagania/', wymagania, name='wymagania'),
    path('wymagania/dodaj/', edytuj_wymaganie, name='dodaj_wymaganie'),
    path('wymagania/edytuj/<int:pk>/', edytuj_wymaganie, name='edytuj_wymaganie'),
    path('wymagania/usun/<int:pk>/', usun_wymaganie, name='usun_wymaganie'),

    # --- GRUPY LEKCYJNE ---
    path('grupy/', grupy_lekcyjne, name='grupy'),
    path('grupy/dodaj/', edytuj_grupe, name='dodaj_grupe'),
    path('grupy/edytuj/<int:pk>/', edytuj_grupe, name='edytuj_grupe'),
    path('grupy/usun/<int:pk>/', usun_grupe, name='usun_grupe'),

    # --- OGRANICZENIA ---
    path('ograniczenia/nauczyciele/', ograniczenia_nauczycieli, name='ograniczenia_nauczycieli'),
    path('ograniczenia/klasy/', ograniczenia_klas_view, name='ograniczenia_klas'),
    path('api/toggle-ograniczenie/', toggle_ograniczenie, name='toggle_ograniczenie'),

    # --- SŁOWNIKI: NAUCZYCIELE ---
    path('nauczyciele/', lista_nauczycieli, name='lista_nauczycieli'),
    path('nauczyciele/dodaj/', edytuj_nauczyciela, name='dodaj_nauczyciela'),
    path('nauczyciele/edytuj/<int:pk>/', edytuj_nauczyciela, name='edytuj_nauczyciela'),
    path('nauczyciele/usun/<int:pk>/', usun_nauczyciela, name='usun_nauczyciela'),

    # --- SŁOWNIKI: PRZEDMIOTY ---
    path('przedmioty/', lista_przedmiotow, name='lista_przedmiotow'),
    path('przedmioty/dodaj/', edytuj_przedmiot, name='dodaj_przedmiot'),
    path('przedmioty/edytuj/<int:pk>/', edytuj_przedmiot, name='edytuj_przedmiot'),
    path('przedmioty/usun/<int:pk>/', usun_przedmiot, name='usun_przedmiot'),

    # --- SŁOWNIKI: KLASY (UWAGA: pk to string, np. '1A') ---
    path('klasy/', lista_klas, name='lista_klas'),
    path('klasy/dodaj/', edytuj_klase, name='dodaj_klase'),
    path('klasy/edytuj/<str:pk>/', edytuj_klase, name='edytuj_klase'),
    path('klasy/usun/<str:pk>/', usun_klase, name='usun_klase'),
    path('plan/edytuj/<int:pk>/', edytuj_pojedyncza_lekcje, name='edytuj_pojedyncza_lekcje'),

    path('api/zamien-lekcje/', api_zamien_lekcje, name='api_zamien_lekcje'),
]