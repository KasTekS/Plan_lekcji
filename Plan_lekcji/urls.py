# Plan_lekcji/urls.py
# ZASTĄP istniejący urlpatterns tym kodem

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
    lista_klas, edytuj_klase, usun_klase, edytuj_pojedyncza_lekcje,
    api_zamien_lekcje, sugeruj_grupy,
    panel_generatora, uruchom_generator, sprawdz_status, drukuj_plany_zbiorcze,
    # NOWE: Weryfikacja 2FA i reset hasła
    custom_login, verify_login, resend_verification_code, custom_logout,
    password_reset_request, password_reset_verify,
    trusted_devices, remove_trusted_device, remove_all_trusted_devices, utworz_grupe_z_sugestii, error_404, error_500, error_403, error_400,
)

urlpatterns = [
    # --- PANEL ADMINA ---
    path('admin/', admin.site.urls),

    # --- AUTORYZACJA (WŁASNA) ---
    path('login/', custom_login, name='login'),
    path('logout/', custom_logout, name='logout'),
    path('verify/', verify_login, name='verify_login'),
    path('api/resend-code/', resend_verification_code, name='resend_code'),

    # Reset hasła
    path('password-reset/', password_reset_request, name='password_reset_request'),
    path('password-reset/verify/', password_reset_verify, name='password_reset_verify'),

    # Zarządzanie zaufanymi urządzeniami
    path('trusted-devices/', trusted_devices, name='trusted_devices'),
    path('trusted-devices/remove/<int:device_id>/', remove_trusted_device, name='remove_trusted_device'),
    path('trusted-devices/remove-all/', remove_all_trusted_devices, name='remove_all_trusted_devices'),

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
    path('grupy/utworz-z-sugestii/', utworz_grupe_z_sugestii, name='utworz_grupe_z_sugestii'),
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

    # --- SŁOWNIKI: KLASY ---
    path('klasy/', lista_klas, name='lista_klas'),
    path('klasy/dodaj/', edytuj_klase, name='dodaj_klase'),
    path('klasy/edytuj/<str:pk>/', edytuj_klase, name='edytuj_klase'),
    path('klasy/usun/<str:pk>/', usun_klase, name='usun_klase'),
    path('plan/edytuj/<int:pk>/', edytuj_pojedyncza_lekcje, name='edytuj_pojedyncza_lekcje'),

    path('api/zamien-lekcje/', api_zamien_lekcje, name='api_zamien_lekcje'),

    path('grupy/sugestie/', sugeruj_grupy, name='sugeruj_grupy'),
    path('grupy/dodaj/', edytuj_grupe, name='dodaj_grupe'),
    path('grupy/edytuj/<int:pk>/', edytuj_grupe, name='edytuj_grupe'),

    path('generator/', panel_generatora, name='panel_generatora'),
    path('generator/start/<str:typ>/', uruchom_generator, name='uruchom_generator'),
    path('generator/status/<int:task_id>/', sprawdz_status, name='sprawdz_status'),
    path('drukuj-plany/', drukuj_plany_zbiorcze, name='drukuj_plany_zbiorcze'),
]
handler404 = 'Plan_lekcji.views.error_404'
handler500 = 'Plan_lekcji.views.error_500'
handler403 = 'Plan_lekcji.views.error_403'
handler400 = 'Plan_lekcji.views.error_400'