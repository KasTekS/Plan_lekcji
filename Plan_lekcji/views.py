from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
from django.db.models import Q
from itertools import combinations
from collections import defaultdict
import json
from django.db import transaction
from collections import defaultdict
from .forms import (
    NauczycielForm, KlasaForm, PrzedmiotForm,
    WymaganieForm, GrupaForm, EdycjaLekcjiForm
)
from .models import (
    WymaganiaPrzedmiotowe, Grupylekcyjne, PlanLekcji,
    Klasa, Nauczyciel, Klasywgrupach, Przedmioty,
    Ograniczenia, OgraniczeniaKlas
)
import threading
import datetime
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from .models import StatusGeneratora

# Importujemy twoje algorytmy
# Upewnij się, że pliki nazywają się poprawnie i są w folderze aplikacji
# Jeśli algorytmy są w głównym folderze projektu, przenieś je do folderu Plan_lekcji lub dostosuj import
from . import alg2_ostateczny as alg_main  # Zakładam zmianę nazwy pliku na prostszą
from . import alg_diagnoza as alg_diag

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
import datetime

from .models import VerificationCode, TrustedDevice, LoginAttempt
from .email_utils import (
    send_verification_code,
    send_password_reset_code,
    send_trusted_device_notification,
    get_client_ip,
    get_device_name
)


# --- FUNKCJE POMOCNICZE I ZABEZPIECZENIA ---

def is_admin(user):
    """Sprawdza, czy użytkownik jest administratorem (is_staff)."""
    return user.is_authenticated and user.is_staff


def przygotuj_siatke_ograniczen(obiekty, typ='nauczyciel'):
    """
    Pomocnicza funkcja budująca strukturę danych dla template'u ograniczeń.
    Zwraca listę: [{'obj': obiekt, 'grid': { 'PON': {1: True, 2: False...}, ... } }, ...]
    """
    dni_map = ['PON', 'WT', 'SR', 'CZW', 'PT']
    godziny = range(1, 11)
    dane_wyjsciowe = []

    for obj in obiekty:
        # Inicjalizacja pustej siatki (wszystko wolne - False)
        grid = {d: {g: False for g in godziny} for d in dni_map}

        # Pobieranie ograniczeń z bazy
        if typ == 'nauczyciel':
            ograniczenia = Ograniczenia.objects.filter(nauczyciel=obj)
        else:
            ograniczenia = OgraniczeniaKlas.objects.filter(klasa=obj)

        for ogr in ograniczenia:
            dzien = ogr.dzien_tygodnia.upper().strip()  # Normalizacja nazwy dnia
            if dzien in grid:
                start = ogr.od if ogr.od else 1
                end = ogr.do if ogr.do else 10
                for g in range(start, end + 1):
                    if g in grid[dzien]:
                        grid[dzien][g] = True

        dane_wyjsciowe.append({
            'obj': obj,
            'grid': grid
        })

    return dane_wyjsciowe


def znajdz_sale_dla_lekcji(lekcja):
    """
    Inteligentnie znajduje salę dla lekcji.

    Jeśli lekcja ma salę - zwraca ją.
    Jeśli nie ma, ale jest grupowa - szuka sali w innych wpisach tej samej grupy w tym samym czasie.
    Jeśli nie ma, ale jest ten sam nauczyciel+przedmiot w tym czasie - szuka tam.
    """
    # Jeśli lekcja już ma salę - zwracamy ją
    if lekcja.sala:
        return lekcja.sala

    # Jeśli to lekcja grupowa - szukamy sali w innych wpisach tej samej grupy
    if lekcja.grupa_id:
        sala_z_grupy = PlanLekcji.objects.filter(
            grupa_id=lekcja.grupa_id,
            dzien_tygodnia=lekcja.dzien_tygodnia,
            godzina_lekcyjna=lekcja.godzina_lekcyjna,
            sala__isnull=False
        ).exclude(sala='').values_list('sala', flat=True).first()

        if sala_z_grupy:
            return sala_z_grupy

    # Jeśli to ten sam nauczyciel+przedmiot w tym czasie - szukamy tam
    if lekcja.nauczyciel_id and lekcja.przedmiot_id:
        sala_z_nauczyciela = PlanLekcji.objects.filter(
            nauczyciel_id=lekcja.nauczyciel_id,
            przedmiot_id=lekcja.przedmiot_id,
            dzien_tygodnia=lekcja.dzien_tygodnia,
            godzina_lekcyjna=lekcja.godzina_lekcyjna,
            sala__isnull=False
        ).exclude(sala='').values_list('sala', flat=True).first()

        if sala_z_nauczyciela:
            return sala_z_nauczyciela

    # Jeśli nic nie znaleziono - zwracamy None
    return None


def index(request):
    klasy = Klasa.objects.all().order_by('nazwa')
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')

    selected_klasa_id = request.GET.get('klasa_id')
    selected_nauczyciel_id = request.GET.get('nauczyciel_id')

    plan_data = {}
    selected_obiekt = None
    typ_widoku = None
    dni_tygodnia = ['PON', 'WT', 'SR', 'CZW', 'PT']
    godziny = range(1, 11)

    if selected_nauczyciel_id:
        typ_widoku = 'nauczyciel'
        selected_obiekt = Nauczyciel.objects.filter(id=selected_nauczyciel_id).first()
        if selected_obiekt:
            # 1. Pobieramy lekcje
            lekcje = PlanLekcji.objects.filter(nauczyciel_id=selected_nauczyciel_id) \
                .select_related('przedmiot', 'klasa', 'grupa')

            # 2. Budujemy mapę grup i ich klas "ręcznie" (optymalizacja i pewność danych)
            # Zbieramy ID wszystkich grup występujących w planie tego nauczyciela
            grupy_ids = [l.grupa_id for l in lekcje if l.grupa_id]

            # Pobieramy powiązania z tabeli Klasywgrupach dla tych grup
            powiazania = Klasywgrupach.objects.filter(grupa_id__in=grupy_ids).select_related('klasa')

            # Tworzymy słownik: { id_grupy: ["Klasa 1A", "Klasa 1B"] }
            grupy_map = defaultdict(list)
            for p in powiazania:
                if p.klasa:
                    grupy_map[p.grupa_id].append(p.klasa.nazwa)

            temp_plan = defaultdict(dict)
            for lekcja in lekcje:
                dzien = lekcja.dzien_tygodnia.upper().strip()
                godz = lekcja.godzina_lekcyjna

                nazwa_przedmiotu = lekcja.przedmiot.nazwa_przedmiotu if lekcja.przedmiot else "Brak"

                # --- LOGIKA WYŚWIETLANIA ---
                if lekcja.grupa_id:
                    # Sprawdzamy w naszej mapie, jakie klasy są w tej grupie
                    list_klas = grupy_map.get(lekcja.grupa_id, [])

                    if list_klas:
                        # Łączymy nazwy przecinkiem
                        klasy_str = ", ".join(list_klas)
                        info_dodatkowe = f"Grupa: {klasy_str}"
                    else:
                        # Jeśli mapa pusta (fallback), wyświetlamy nazwę grupy
                        info_dodatkowe = f"Grupa: {lekcja.grupa.nazwa_grupy}"

                elif lekcja.klasa:
                    # Pojedyncza klasa (bez słowa "Klasa" przed nazwą, żeby nie było duplikatów)
                    info_dodatkowe = lekcja.klasa.nazwa
                else:
                    info_dodatkowe = "-"
                # ---------------------------

                # INTELIGENTNE ZNAJDOWANIE SALI
                sala = znajdz_sale_dla_lekcji(lekcja)

                temp_plan[godz][dzien] = {
                    'id': lekcja.id,
                    'sala': sala,  # <- Używamy inteligentnej funkcji
                    'linia1': nazwa_przedmiotu,
                    'linia2': info_dodatkowe
                }
            plan_data = temp_plan

    elif selected_klasa_id:
        typ_widoku = 'klasa'
        selected_obiekt = Klasa.objects.filter(id=selected_klasa_id).first()
        if selected_obiekt:
            grupy_ids = Klasywgrupach.objects.filter(klasa_id=selected_klasa_id).values_list('grupa_id', flat=True)

            lekcje = PlanLekcji.objects.filter(
                Q(klasa_id=selected_klasa_id) |
                (Q(grupa_id__in=grupy_ids) & Q(klasa__isnull=True))
            ).select_related('przedmiot', 'nauczyciel', 'grupa')

            temp_plan = defaultdict(dict)
            for lekcja in lekcje:
                dzien = lekcja.dzien_tygodnia.upper().strip()
                godz = lekcja.godzina_lekcyjna

                nazwa_przedmiotu = lekcja.przedmiot.nazwa_przedmiotu if lekcja.przedmiot else "Brak"

                # Dla admina pokazujemy nazwę grupy w nawiasie
                if lekcja.grupa and request.user.is_superuser:
                    nazwa_przedmiotu += f" ({lekcja.grupa.nazwa_grupy})"

                nauczyciel = lekcja.nauczyciel.imie_nazwisko if lekcja.nauczyciel else "Brak"

                # INTELIGENTNE ZNAJDOWANIE SALI
                sala = znajdz_sale_dla_lekcji(lekcja)

                temp_plan[godz][dzien] = {
                    'id': lekcja.id,
                    'sala': sala,  # <- Używamy inteligentnej funkcji
                    'linia1': nazwa_przedmiotu,
                    'linia2': nauczyciel
                }
            plan_data = temp_plan

    return render(request, 'index.html', {
        'klasy': klasy,
        'nauczyciele': nauczyciele,
        'selected_klasa_id': selected_klasa_id,
        'selected_nauczyciel_id': selected_nauczyciel_id,
        'selected_obiekt': selected_obiekt,
        'typ_widoku': typ_widoku,
        'plan': plan_data,
        'dni': dni_tygodnia,
        'godziny': godziny
    })


# --- ZARZĄDZANIE WYMAGANIAMI (ADMIN) ---
@user_passes_test(is_admin)
# --- ZARZĄDZANIE WYMAGANIAMI ---
def wymagania(request):
    if request.method == 'POST':
        form = WymaganieForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Dodano nowe wymaganie.")
            return redirect('wymagania')
    else:
        form = WymaganieForm()

    # Pobieranie parametrów
    search_query = request.GET.get('q', '')
    nauczyciel_id = request.GET.get('nauczyciel_id', '')
    klasa_id = request.GET.get('klasa_id', '')
    sort_param = request.GET.get('sort', 'nauczyciel')

    # Bazowy QuerySet - BEZ PAGINACJI
    queryset = WymaganiaPrzedmiotowe.objects.select_related('nauczyciel', 'klasa', 'przedmiot').all()

    # Filtrowanie
    if search_query:
        queryset = queryset.filter(
            Q(przedmiot__nazwa_przedmiotu__icontains=search_query) |
            Q(nauczyciel__imie_nazwisko__icontains=search_query)
        )
    if nauczyciel_id:
        queryset = queryset.filter(nauczyciel_id=nauczyciel_id)
    if klasa_id:
        queryset = queryset.filter(klasa_id=klasa_id)

    # Sortowanie
    sort_mapping = {
        'nauczyciel': 'nauczyciel__imie_nazwisko', '-nauczyciel': '-nauczyciel__imie_nazwisko',
        'klasa': 'klasa_id', '-klasa': '-klasa_id',
        'przedmiot': 'przedmiot__nazwa_przedmiotu', '-przedmiot': '-przedmiot__nazwa_przedmiotu',
        'godziny': 'liczba_godzin', '-godziny': '-liczba_godzin',
    }
    queryset = queryset.order_by(sort_mapping.get(sort_param, 'id'))

    context = {
        'form': form,
        'wymagania': queryset,  # Przekazujemy pełną listę
        'nauczyciele': Nauczyciel.objects.all().order_by('imie_nazwisko'),
        'klasy': Klasa.objects.all().order_by('id'),
        'search_query': search_query,
        'selected_nauczyciel_id': nauczyciel_id,
        'selected_klasa_id': klasa_id,
        'current_sort': sort_param,
    }
    return render(request, 'wymagania.html', context)


# --- ZARZĄDZANIE GRUPAMI ---
@user_passes_test(is_admin)
def grupy_lekcyjne(request):
    if request.method == 'POST':
        form = GrupaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Utworzono nową grupę.")
            return redirect('grupy')
    else:
        form = GrupaForm()

    search_query = request.GET.get('q', '')
    nauczyciel_id = request.GET.get('nauczyciel_id', '')
    sort_param = request.GET.get('sort', '-id')

    queryset = Grupylekcyjne.objects.select_related('przedmiot', 'nauczyciel').prefetch_related('klasy').all()

    # Filtrowanie
    if search_query:
        queryset = queryset.filter(
            Q(nazwa_grupy__icontains=search_query) |
            Q(przedmiot__nazwa_przedmiotu__icontains=search_query) |
            Q(klasy__id__icontains=search_query)
        ).distinct()

    if nauczyciel_id:  # Naprawia błąd braku filtra opiekuna
        queryset = queryset.filter(nauczyciel_id=nauczyciel_id)

    # Sortowanie
    sort_mapping = {
        'nazwa_grupy': 'nazwa_grupy', '-nazwa_grupy': '-nazwa_grupy',
        'przedmiot': 'przedmiot__nazwa_przedmiotu', '-przedmiot': '-przedmiot__nazwa_przedmiotu',
        'nauczyciel': 'nauczyciel__imie_nazwisko', '-nauczyciel': '-nauczyciel__imie_nazwisko',
        'godziny': 'liczba_godzin_w_grupie', '-godziny': '-liczba_godzin_w_grupie',
    }
    queryset = queryset.order_by(sort_mapping.get(sort_param, '-id'))

    context = {
        'form': form,
        'grupy': queryset,  # Przekazujemy pełną listę
        'nauczyciele': Nauczyciel.objects.all().order_by('imie_nazwisko'),  # Do dropdowna filtrów
        'search_query': search_query,
        'selected_nauczyciel_id': nauczyciel_id,
        'current_sort': sort_param,
    }
    return render(request, 'grupy.html', context)


@user_passes_test(is_admin)
def edytuj_wymaganie(request, pk=None):
    if pk:
        instancja = get_object_or_404(WymaganiaPrzedmiotowe, pk=pk)
        tytul = "Edytuj Wymaganie"
    else:
        instancja = None
        tytul = "Dodaj Wymaganie"

    if request.method == 'POST':
        form = WymaganieForm(request.POST, instance=instancja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zapisano wymaganie.')
            return redirect('wymagania')
    else:
        form = WymaganieForm(instance=instancja)

    return render(request, 'slowniki/formularz_bazowy.html', {'form': form, 'tytul': tytul})


@user_passes_test(is_admin)
def usun_wymaganie(request, pk):
    obj = get_object_or_404(WymaganiaPrzedmiotowe, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Usunięto wymaganie.')
    return redirect('wymagania')


@user_passes_test(is_admin)
def edytuj_grupe(request, pk=None):
    """
    Dodaje lub edytuje grupę lekcyjną.
    Obsługuje też wypełnianie formularza z parametrów GET (z sugestii).
    """
    if pk:
        instancja = get_object_or_404(Grupylekcyjne, pk=pk)
        tytul = "Edytuj Grupę"
    else:
        instancja = None
        tytul = "Dodaj Grupę"

        # NOWE: Obsługa parametrów z GET (z sugestii)
        if request.method == 'GET' and request.GET.get('z_sugestii'):
            przedmiot_id = request.GET.get('przedmiot_id')
            nauczyciel_id = request.GET.get('nauczyciel_id')
            godziny = request.GET.get('godziny')
            ids_klas = request.GET.get('ids_klas')
            nazwa = request.GET.get('nazwa')

            if przedmiot_id and godziny and ids_klas and nazwa:
                try:
                    przedmiot = Przedmioty.objects.get(id=przedmiot_id)
                    nauczyciel = None
                    if nauczyciel_id and nauczyciel_id != 'None':
                        nauczyciel = Nauczyciel.objects.get(id=nauczyciel_id)

                    # Tworzymy tymczasową instancję (nie zapisujemy!)
                    instancja = Grupylekcyjne(
                        nazwa_grupy=nazwa,
                        przedmiot=przedmiot,
                        nauczyciel=nauczyciel,
                        liczba_godzin_w_grupie=int(godziny),
                        rozmieszczenie='BRAK'
                    )

                    tytul = "Utwórz Grupę (z sugestii)"
                    messages.info(request, "Formularz wypełniony danymi z sugestii.")
                except Exception as e:
                    messages.error(request, f"Błąd wypełniania formularza: {e}")

    if request.method == 'POST':
        form = GrupaForm(request.POST, instance=instancja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zapisano grupę.')
            return redirect('grupy')
    else:
        form = GrupaForm(instance=instancja)

        # NOWE: Jeśli mamy wypełnioną instancję z GET, ustawiamy klasy
        if instancja and not instancja.pk and request.GET.get('ids_klas'):
            ids_klas_list = request.GET.get('ids_klas').split(',')
            klasy_objs = Klasa.objects.filter(id__in=ids_klas_list)
            form.fields['klasy_wybor'].initial = klasy_objs

    return render(request, 'slowniki/formularz_bazowy.html', {
        'form': form,
        'tytul': tytul
    })


@user_passes_test(is_admin)
def usun_grupe(request, pk):
    grupa = get_object_or_404(Grupylekcyjne, pk=pk)

    if request.method == 'POST':
        # Sprawdzamy, czy użytkownik zaznaczył checkbox w formularzu
        przywroc = request.POST.get('przywroc_godziny') == 'on'

        # Zbieramy dane do komunikatu
        nazwa = grupa.nazwa_grupy
        klasy_w_grupie = list(grupa.klasy.all())
        godziny = grupa.liczba_godzin_w_grupie
        przedmiot = grupa.przedmiot

        # Usuwamy grupę
        grupa.delete()

        msg = f'Usunięto grupę "{nazwa}".'

        # Logika przywracania godzin (tylko jeśli zaznaczono checkbox)
        if przywroc and przedmiot and godziny > 0:
            zaktualizowano_liczbnik = 0
            for k in klasy_w_grupie:
                wymagania = WymaganiaPrzedmiotowe.objects.filter(klasa=k, przedmiot=przedmiot)
                for wym in wymagania:
                    wym.liczba_godzin = (wym.liczba_godzin or 0) + godziny
                    wym.save()
                    zaktualizowano_liczbnik += 1

            if zaktualizowano_liczbnik > 0:
                msg += f' Przywrócono godziny w {zaktualizowano_liczbnik} wymaganiach.'
        else:
            msg += ' Wymagania przedmiotowe pozostały bez zmian.'

        messages.success(request, msg)
        return redirect('grupy')

    # Metoda GET: Wyświetlamy stronę potwierdzenia
    return render(request, 'grupy_usun.html', {'grupa': grupa})


# --- ZARZĄDZANIE OGRANICZENIAMI (ADMIN) ---

@user_passes_test(is_admin)
def ograniczenia_nauczycieli(request):
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')
    siatka = przygotuj_siatke_ograniczen(nauczyciele, typ='nauczyciel')
    return render(request, 'ograniczenia_nauczycieli.html', {
        'siatka': siatka,
        'dni': ['PON', 'WT', 'SR', 'CZW', 'PT'],
        'godziny': range(1, 11)
    })


@user_passes_test(is_admin)
def ograniczenia_klas_view(request):
    klasy = Klasa.objects.all().order_by('nazwa')
    siatka = przygotuj_siatke_ograniczen(klasy, typ='klasa')
    return render(request, 'ograniczenia_klas.html', {
        'siatka': siatka,
        'dni': ['PON', 'WT', 'SR', 'CZW', 'PT'],
        'godziny': range(1, 11)
    })


@user_passes_test(is_admin)
@require_POST
def toggle_ograniczenie(request):
    """API dla AJAX-a do przełączania kratek ograniczeń."""
    data = json.loads(request.body)
    obj_type = data.get('type')
    obj_id = data.get('id')
    day = data.get('day')
    hour = int(data.get('hour'))

    ModelOgraniczen = Ograniczenia if obj_type == 'nauczyciel' else OgraniczeniaKlas
    field_name = 'nauczyciel_id' if obj_type == 'nauczyciel' else 'klasa_id'

    istniejace = ModelOgraniczen.objects.filter(
        dzien_tygodnia=day,
        od__lte=hour,
        do__gte=hour,
        **{field_name: obj_id}
    ).first()

    status = 'error'

    if istniejace:
        # Usuwanie / Dzielenie zakresu
        od, do = istniejace.od, istniejace.do
        if od == do:
            istniejace.delete()
        elif hour == od:
            istniejace.od = od + 1
            istniejace.save()
        elif hour == do:
            istniejace.do = do - 1
            istniejace.save()
        else:
            istniejace.do = hour - 1
            istniejace.save()
            ModelOgraniczen.objects.create(
                dzien_tygodnia=day, od=hour + 1, do=do, **{field_name: obj_id}
            )
        status = 'unblocked'
    else:
        # Dodawanie / Łączenie zakresu
        lewy_sasiad = ModelOgraniczen.objects.filter(dzien_tygodnia=day, do=hour - 1, **{field_name: obj_id}).first()
        prawy_sasiad = ModelOgraniczen.objects.filter(dzien_tygodnia=day, od=hour + 1, **{field_name: obj_id}).first()

        if lewy_sasiad and prawy_sasiad:
            lewy_sasiad.do = prawy_sasiad.do
            lewy_sasiad.save()
            prawy_sasiad.delete()
        elif lewy_sasiad:
            lewy_sasiad.do = hour
            lewy_sasiad.save()
        elif prawy_sasiad:
            prawy_sasiad.od = hour
            prawy_sasiad.save()
        else:
            ModelOgraniczen.objects.create(
                dzien_tygodnia=day, od=hour, do=hour, **{field_name: obj_id}
            )
        status = 'blocked'

    return JsonResponse({'status': status})


# --- CRUD SŁOWNIKI (NAUCZYCIELE, PRZEDMIOTY, KLASY) - ADMIN ---

# --- Nauczyciele ---
# --- SŁOWNIKI: NAUCZYCIELE ---
@user_passes_test(is_admin)
def lista_nauczycieli(request):
    search_query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', 'imie_nazwisko')  # Domyślne sortowanie

    # Pobieramy wszystkich
    nauczyciele = Nauczyciel.objects.all()

    # Filtracja (Search)
    if search_query:
        nauczyciele = nauczyciele.filter(imie_nazwisko__icontains=search_query)

    # Sortowanie (Zabezpieczenie przed błędnymi nazwami pól)
    valid_sorts = ['imie_nazwisko', '-imie_nazwisko', 'id', '-id']
    if sort_by not in valid_sorts:
        sort_by = 'imie_nazwisko'

    nauczyciele = nauczyciele.order_by(sort_by)

    return render(request, 'slowniki/nauczyciele_lista.html', {
        'nauczyciele': nauczyciele,
        'search_query': search_query,
        'current_sort': sort_by
    })


@user_passes_test(is_admin)
def edytuj_nauczyciela(request, pk=None):
    if pk:
        instancja = get_object_or_404(Nauczyciel, pk=pk)
        tytul = "Edytuj Nauczyciela"
    else:
        instancja = None
        tytul = "Dodaj Nauczyciela"

    if request.method == 'POST':
        form = NauczycielForm(request.POST, instance=instancja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zapisano zmiany.')
            return redirect('lista_nauczycieli')
    else:
        form = NauczycielForm(instance=instancja)

    return render(request, 'slowniki/formularz_bazowy.html', {'form': form, 'tytul': tytul})


@user_passes_test(is_admin)
def usun_nauczyciela(request, pk):
    obj = get_object_or_404(Nauczyciel, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Nauczyciel usunięty.')
    return redirect('lista_nauczycieli')


# --- Przedmioty ---
# --- SŁOWNIKI: PRZEDMIOTY ---
@user_passes_test(is_admin)
def lista_przedmiotow(request):
    search_query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', 'nazwa_przedmiotu')

    przedmioty = Przedmioty.objects.all()

    if search_query:
        przedmioty = przedmioty.filter(
            Q(nazwa_przedmiotu__icontains=search_query) |
            Q(skrot__icontains=search_query)
        )

    valid_sorts = ['nazwa_przedmiotu', '-nazwa_przedmiotu', 'skrot', '-skrot']
    if sort_by not in valid_sorts:
        sort_by = 'nazwa_przedmiotu'

    przedmioty = przedmioty.order_by(sort_by)

    return render(request, 'slowniki/przedmioty_lista.html', {
        'przedmioty': przedmioty,
        'search_query': search_query,
        'current_sort': sort_by
    })


@user_passes_test(is_admin)
def edytuj_przedmiot(request, pk=None):
    if pk:
        instancja = get_object_or_404(Przedmioty, pk=pk)
        tytul = "Edytuj Przedmiot"
    else:
        instancja = None
        tytul = "Dodaj Przedmiot"

    if request.method == 'POST':
        form = PrzedmiotForm(request.POST, instance=instancja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zapisano przedmiot.')
            return redirect('lista_przedmiotow')
    else:
        form = PrzedmiotForm(instance=instancja)

    return render(request, 'slowniki/formularz_bazowy.html', {'form': form, 'tytul': tytul})


@user_passes_test(is_admin)
def usun_przedmiot(request, pk):
    obj = get_object_or_404(Przedmioty, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Przedmiot usunięty.')
    return redirect('lista_przedmiotow')


# --- Klasy ---
# --- SŁOWNIKI: KLASY ---
@user_passes_test(is_admin)
def lista_klas(request):
    search_query = request.GET.get('q', '')
    sort_by = request.GET.get('sort', 'id')

    klasy = Klasa.objects.all()

    if search_query:
        klasy = klasy.filter(
            Q(id__icontains=search_query) |
            Q(nazwa__icontains=search_query)
        )

    valid_sorts = ['id', '-id', 'nazwa', '-nazwa', 'rok', '-rok', 'ilosc_osob', '-ilosc_osob']
    if sort_by not in valid_sorts:
        sort_by = 'id'

    klasy = klasy.order_by(sort_by)

    return render(request, 'slowniki/klasy_lista.html', {
        'klasy': klasy,
        'search_query': search_query,
        'current_sort': sort_by
    })


@user_passes_test(is_admin)
def edytuj_klase(request, pk=None):
    if pk:
        instancja = get_object_or_404(Klasa, pk=pk)
        tytul = f"Edytuj Klasę {pk}"
    else:
        instancja = None
        tytul = "Dodaj Klasę"

    if request.method == 'POST':
        form = KlasaForm(request.POST, instance=instancja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zapisano klasę.')
            return redirect('lista_klas')
    else:
        form = KlasaForm(instance=instancja)

    return render(request, 'slowniki/formularz_bazowy.html', {'form': form, 'tytul': tytul})


@user_passes_test(is_admin)
def usun_klase(request, pk):
    obj = get_object_or_404(Klasa, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Klasa usunięta.')
    return redirect('lista_klas')


# W pliku views.py

@user_passes_test(is_admin)
def edytuj_pojedyncza_lekcje(request, pk):
    lekcja = get_object_or_404(PlanLekcji, pk=pk)

    # KLUCZ DO ROZWIĄZANIA: Zapisujemy oryginalny referer TYLKO przy pierwszym wejściu (GET)
    # W kolejnych requestach (POST z błędami walidacji) używamy zapisanej wartości
    if request.method == 'GET':
        referer = request.META.get('HTTP_REFERER') or '/'
        # Zapisujemy w sesji, żeby przetrwało POST requesty
        request.session[f'lekcja_return_url_{pk}'] = referer

    # Pobieramy zapisany adres powrotu
    return_url = request.session.get(f'lekcja_return_url_{pk}', '/')

    if request.method == 'POST':
        form = EdycjaLekcjiForm(request.POST, instance=lekcja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zaktualizowano lekcję na planie.')

            # Usuwamy zapisany URL z sesji po udanym zapisie
            if f'lekcja_return_url_{pk}' in request.session:
                del request.session[f'lekcja_return_url_{pk}']

            # Jeśli return_url to tylko sam ukośnik (fallback), próbujemy logiki:
            if return_url == '/':
                if lekcja.klasa:
                    return redirect(f"/?klasa_id={lekcja.klasa.id}")
                elif lekcja.nauczyciel:
                    return redirect(f"/?nauczyciel_id={lekcja.nauczyciel.id}")
                else:
                    return redirect('index')

            return redirect(return_url)
    else:
        form = EdycjaLekcjiForm(instance=lekcja)

    return render(request, 'slowniki/formularz_bazowy.html', {
        'form': form,
        'tytul': f'Edycja lekcji: {lekcja.dzien_tygodnia} godz. {lekcja.godzina_lekcyjna}',
        'return_url': return_url  # Przekazujemy ZAPISANY url do template'u
    })


# W pliku Plan_lekcji/views.py (dodaj na końcu)

# W pliku Plan_lekcji/views.py
# W pliku Plan_lekcji/views.py
def sprawdz_czy_sa_okienka(zajete_godziny):
    """
    Pomocnicza funkcja. Zwraca True, jeśli w liście godzin są luki.
    Np. [1, 2, 4] -> True (brak 3)
    Np. [1, 2, 3] -> False
    """
    if not zajete_godziny:
        return False
    sorted_h = sorted(list(zajete_godziny))
    start = sorted_h[0]
    end = sorted_h[-1]
    return (end - start + 1) != len(sorted_h)


@user_passes_test(is_admin)
@require_POST
def api_zamien_lekcje(request):
    try:
        data = json.loads(request.body)
        lekcja_id = data.get('lekcja_id')
        target_day = data.get('target_dzien')
        target_hour = data.get('target_godzina')
        current_klasa_id = data.get('klasa_id')
        force = data.get('force', False)

        if not lekcja_id or not target_day or not target_hour or not current_klasa_id:
            return JsonResponse({'success': False, 'error': 'Brak wymaganych danych.'})

        try:
            target_hour = int(target_hour)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Zły format godziny'})

        # Pobieramy lekcję źródłową
        source_lesson = PlanLekcji.objects.get(id=lekcja_id)
        old_day = source_lesson.dzien_tygodnia
        old_hour = source_lesson.godzina_lekcyjna

        # Pobieramy lekcję docelową (jeśli istnieje)
        grupy_tej_klasy = Klasywgrupach.objects.filter(klasa_id=current_klasa_id).values_list('grupa_id', flat=True)

        target_lesson = PlanLekcji.objects.filter(
            dzien_tygodnia=target_day,
            godzina_lekcyjna=target_hour
        ).filter(
            Q(klasa_id=current_klasa_id) |
            (Q(grupa_id__in=grupy_tej_klasy) & Q(klasa__isnull=True))
        ).first()

        if target_lesson and target_lesson.id == source_lesson.id:
            return JsonResponse({'status': 'ok', 'success': True})

        # ==========================================
        # WALIDACJA (KONFLIKTY + OGRANICZENIA)
        # ==========================================
        if not force:
            konflikty = []

            # --- 1. SPRAWDZANIE KOLIZJI PLANU (Zajętość nauczyciela) ---
            ignore_ids = [source_lesson.id]
            if target_lesson: ignore_ids.append(target_lesson.id)

            # Czy nauczyciel źródłowy jest wolny w nowym terminie?
            if source_lesson.nauczyciel:
                nauczyciel_zajety = PlanLekcji.objects.filter(
                    nauczyciel=source_lesson.nauczyciel,
                    dzien_tygodnia=target_day,
                    godzina_lekcyjna=target_hour
                ).exclude(id__in=ignore_ids).first()

                if nauczyciel_zajety:
                    info = f"klasa {nauczyciel_zajety.klasa.nazwa}" if nauczyciel_zajety.klasa else "inna grupa"
                    konflikty.append(f"KONFLIKT: {source_lesson.nauczyciel} ma już lekcję w tym czasie ({info}).")

            # Jeśli zamiana - czy nauczyciel docelowy jest wolny w starym terminie?
            if target_lesson and target_lesson.nauczyciel:
                nauczyciel_celu_zajety = PlanLekcji.objects.filter(
                    nauczyciel=target_lesson.nauczyciel,
                    dzien_tygodnia=old_day,
                    godzina_lekcyjna=old_hour
                ).exclude(id__in=ignore_ids).first()

                if nauczyciel_celu_zajety:
                    info = f"klasa {nauczyciel_celu_zajety.klasa.nazwa}" if nauczyciel_celu_zajety.klasa else "inna grupa"
                    konflikty.append(
                        f"KONFLIKT ZAMIANY: {target_lesson.nauczyciel} ma zajęcia w czasie, na który chcesz go przenieść ({info}).")

            # --- 2. SPRAWDZANIE OGRANICZEŃ NAUCZYCIELI (Model: Ograniczenia) ---
            # Sprawdź czy godzina mieści się w zakresie od-do dla danego dnia
            if source_lesson.nauczyciel:
                ogru_nauczyciela = Ograniczenia.objects.filter(
                    nauczyciel=source_lesson.nauczyciel,
                    dzien_tygodnia=target_day,
                    od__lte=target_hour,  # 'od' musi być mniejsze lub równe godzinie lekcji
                    do__gte=target_hour  # 'do' musi być większe lub równe godzinie lekcji
                ).exists()

                if ogru_nauczyciela:
                    konflikty.append(
                        f"OGRANICZENIE: {source_lesson.nauczyciel} ma zgłoszoną niedostępność w: {target_day}, godz. {target_hour}.")

            # Jeśli zamiana - sprawdź ograniczenie dla nauczyciela docelowego
            if target_lesson and target_lesson.nauczyciel:
                ogru_nauczyciela_target = Ograniczenia.objects.filter(
                    nauczyciel=target_lesson.nauczyciel,
                    dzien_tygodnia=old_day,
                    od__lte=old_hour,
                    do__gte=old_hour
                ).exists()
                if ogru_nauczyciela_target:
                    konflikty.append(
                        f"OGRANICZENIE: {target_lesson.nauczyciel} (zamieniany) nie może uczyć w: {old_day}, godz. {old_hour}.")

            # --- 3. SPRAWDZANIE OGRANICZEŃ KLAS (Model: OgraniczeniaKlas) ---
            ogru_klasy = OgraniczeniaKlas.objects.filter(
                klasa_id=current_klasa_id,
                dzien_tygodnia=target_day,
                od__lte=target_hour,
                do__gte=target_hour
            ).exists()

            if ogru_klasy:
                konflikty.append(
                    f"OGRANICZENIE KLASY: Ta klasa ma blokadę w terminie: {target_day}, godz. {target_hour}.")

            # ZWRACANIE BŁĘDÓW
            if konflikty:
                return JsonResponse({
                    'status': 'confirm',
                    'message': "\n".join(konflikty)
                })

        # ==========================================
        # WYKONANIE ZMIANY (SPLIT + SWAP)
        # ==========================================
        messages_list = []

        def uszczegolowij_lekcje(lekcja_obj, dla_klasy_id):
            if lekcja_obj.grupa and lekcja_obj.klasa is None:
                klasy_w_grupie = Klasywgrupach.objects.filter(grupa=lekcja_obj.grupa)
                moj_egzemplarz = None
                for wpis in klasy_w_grupie:
                    nowa = PlanLekcji.objects.get(pk=lekcja_obj.pk)
                    nowa.pk = None
                    nowa.klasa_id = wpis.klasa_id
                    nowa.save()
                    if str(wpis.klasa_id) == str(dla_klasy_id):
                        moj_egzemplarz = nowa

                lekcja_obj.delete()
                messages_list.append(f"Rozdzielono lekcję grupy {lekcja_obj.grupa}.")
                return moj_egzemplarz
            return lekcja_obj

        with transaction.atomic():
            source_lesson = PlanLekcji.objects.get(id=lekcja_id)
            target_lesson = PlanLekcji.objects.filter(
                dzien_tygodnia=target_day,
                godzina_lekcyjna=target_hour
            ).filter(
                Q(klasa_id=current_klasa_id) |
                (Q(grupa_id__in=grupy_tej_klasy) & Q(klasa__isnull=True))
            ).first()

            real_source = uszczegolowij_lekcje(source_lesson, current_klasa_id)

            real_target = None
            if target_lesson and target_lesson.id != real_source.id:
                real_target = uszczegolowij_lekcje(target_lesson, current_klasa_id)

            real_source.dzien_tygodnia = target_day
            real_source.godzina_lekcyjna = target_hour
            real_source.save()

            if real_target:
                real_target.dzien_tygodnia = old_day
                real_target.godzina_lekcyjna = old_hour
                real_target.save()

        msg_text = "\n".join(set(messages_list))

        return JsonResponse({
            'status': 'ok',
            'success': True,
            'message': msg_text
        })

    except PlanLekcji.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Lekcja nie istnieje'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})


@user_passes_test(is_admin)
def sugeruj_grupy(request):
    """
    Wyszukuje wszystkie możliwe kombinacje 2-klasowe,
    które mogą być połączone w grupy międzyoddziałowe.
    """
    # Pobieramy wszystkie wymagania, które mają > 0 godzin
    wymagania = WymaganiaPrzedmiotowe.objects.filter(
        liczba_godzin__gt=0
    ).select_related('klasa', 'nauczyciel', 'przedmiot')

    # Słownik pomocniczy do grupowania
    grupy_robocze = defaultdict(list)

    for w in wymagania:
        klucz = (
            w.przedmiot,
            w.nauczyciel,
            w.liczba_godzin,
            w.klasa.rok
        )
        grupy_robocze[klucz].append(w)

    sugestie = []
    MAKS_OSOB = 30

    for (przedmiot, nauczyciel, godziny, rok), lista_wymagan in grupy_robocze.items():
        # Generujemy WSZYSTKIE kombinacje 2-klasowe
        if len(lista_wymagan) >= 2:
            for para in combinations(lista_wymagan, 2):
                klasa1, klasa2 = para[0].klasa, para[1].klasa

                suma_osob = (klasa1.ilosc_osob or 0) + (klasa2.ilosc_osob or 0)

                if suma_osob <= MAKS_OSOB:
                    # Generujemy krótką nazwę grupy
                    skrot = przedmiot.skrot if przedmiot.skrot else przedmiot.nazwa_przedmiotu[:3].upper()
                    nazwa_grupy = f"{skrot}_{klasa1.id}+{klasa2.id}"

                    ids_klas = f"{klasa1.id},{klasa2.id}"

                    sugestie.append({
                        'przedmiot': przedmiot,
                        'nauczyciel': nauczyciel,
                        'godziny': godziny,
                        'klasy': [klasa1, klasa2],
                        'ids_klas_hidden': ids_klas,
                        'suma_osob': suma_osob,
                        'rok': rok,
                        'nazwa_proponowana': nazwa_grupy
                    })

    # Sortujemy sugestie
    sugestie.sort(key=lambda x: (
        x['przedmiot'].nazwa_przedmiotu,
        x['klasy'][0].nazwa,
        x['klasy'][1].nazwa
    ))

    return render(request, 'slowniki/sugestie_grup.html', {
        'sugestie': sugestie
    })


def pobierz_parametry_db():
    """Pomocnik konwertujący ustawienia Django na format dla psycopg2"""
    db = settings.DATABASES['default']
    return {
        'dbname': db['NAME'],
        'user': db['USER'],
        'password': db['PASSWORD'],
        'host': db['HOST'],
        'port': db['PORT'] or 5432
    }


@user_passes_test(is_admin)
def utworz_grupe_z_sugestii(request):
    """
    Otwiera formularz dodawania grupy z wypełnionymi danymi z sugestii.
    """
    if request.method == 'POST':
        try:
            # Pobieramy dane z POST
            przedmiot_id = request.POST.get('przedmiot_id')
            nauczyciel_id = request.POST.get('nauczyciel_id')
            godziny = request.POST.get('godziny')
            ids_klas_str = request.POST.get('ids_klas')
            nazwa_proponowana = request.POST.get('nazwa_proponowana')

            # Konwertujemy dane
            przedmiot = get_object_or_404(Przedmioty, id=przedmiot_id)
            nauczyciel = None
            if nauczyciel_id and nauczyciel_id != 'None':
                nauczyciel = get_object_or_404(Nauczyciel, id=nauczyciel_id)

            ids_klas = ids_klas_str.split(',')
            klasy_objs = Klasa.objects.filter(id__in=ids_klas)

            # Tworzymy instancję grupy (NIE zapisujemy do bazy!)
            grupa_temp = Grupylekcyjne(
                nazwa_grupy=nazwa_proponowana,
                przedmiot=przedmiot,
                nauczyciel=nauczyciel,
                liczba_godzin_w_grupie=int(godziny),
                rozmieszczenie='BRAK'
            )

            # Tworzymy formularz z wypełnionymi danymi
            form = GrupaForm(instance=grupa_temp)

            # Ustawiamy initial dla pola klasy_wybor
            form.fields['klasy_wybor'].initial = klasy_objs

            # Dodajemy informację dla użytkownika
            messages.info(
                request,
                f"Formularz wypełniony danymi z sugestii. Sprawdź i zatwierdź utworzenie grupy."
            )

            return render(request, 'slowniki/formularz_bazowy.html', {
                'form': form,
                'tytul': f'Utwórz Grupę: {nazwa_proponowana}',
            })

        except Exception as e:
            messages.error(request, f"Błąd: {e}")
            return redirect('sugeruj_grupy')

    return redirect('sugeruj_grupy')


def watek_generatora(typ, task_id):
    """
    Funkcja uruchamiana w tle.
    Obsługuje: NOWY, UPDATE (zapisują) oraz DIAGNOZA_NOWY, DIAGNOZA_UPDATE (tylko raportują).
    """
    import time
    from django.utils import timezone

    try:
        task = StatusGeneratora.objects.get(id=task_id)
    except StatusGeneratora.DoesNotExist:
        return

    try:
        print(f"[{task_id}] Rozpoczynam wątek generatora: {typ}")

        # Konfiguracja bazy
        db_params = settings.DATABASES['default']
        db_config = {
            'dbname': db_params['NAME'],
            'user': db_params['USER'],
            'password': db_params['PASSWORD'],
            'host': db_params['HOST'],
            'port': db_params.get('PORT', 5432)
        }

        # 1. Pobieranie danych
        dane = alg_main.pobierz_dane_z_bazy(db_config)
        if dane[0] is None:
            raise Exception("Nie udało się pobrać danych z bazy.")

        (nauczyciele, przedmioty, klasy, wymagania, grupy,
         ogr_nauczycieli, ogr_klas, stary_plan) = dane

        ID_WF = 13  # Upewnij się, że to ID jest poprawne

        # --- LOGIKA STEROWANIA TRYBAMI ---

        # A. Tryb DIAGNOSTYKI (Używa alg_diagnoza.py)
        if 'DIAGNOZA' in typ:
            # Rozróżniamy czy diagnozujemy od zera, czy aktualizację
            jest_update = True if typ == 'DIAGNOZA_UPDATE' else False

            wynik = alg_diag.generuj_plan(
                nauczyciele, przedmioty, klasy, wymagania, grupy,
                ogr_nauczycieli, ogr_klas, ID_WF, db_config, stary_plan,
                zachowaj_obecny_plan=jest_update  # <--- Tu przekazujemy flagę
            )

            # W diagnozie sukces to pomyślne wygenerowanie RAPORTU
            task.status = 'SUKCES' if wynik['czy_sukces'] else 'BLAD'
            task.wiadomosc = wynik['wiadomosc']

        # B. Tryb GENEROWANIA (Używa alg2_ostateczny.py)
        else:
            jest_update = True if typ == 'UPDATE' else False

            wynik = alg_main.generuj_plan(
                nauczyciele, przedmioty, klasy, wymagania, grupy,
                ogr_nauczycieli, ogr_klas, ID_WF, db_config, stary_plan,
                zachowaj_obecny_plan=jest_update
            )

            if wynik['czy_sukces']:
                task.status = 'SUKCES'
                task.wiadomosc = wynik['wiadomosc']
            else:
                task.status = 'BLAD'
                task.wiadomosc = wynik['wiadomosc']

    except Exception as e:
        print(f"Krytyczny błąd w wątku: {e}")
        task.status = 'BLAD'
        task.wiadomosc = f"Wystąpił nieoczekiwany błąd systemu: {str(e)}"

    finally:
        task.data_zakonczenia = timezone.now()
        task.save()


# --- WIDOKI DLA UŻYTKOWNIKA ---

def panel_generatora(request):
    """Wyświetla stronę z przyciskami"""
    return render(request, 'panel_generatora.html')


def uruchom_generator(request, typ):
    """Odbiera żądanie AJAX i startuje wątek"""
    if request.method == 'POST':
        # Tworzymy wpis statusu
        task = StatusGeneratora.objects.create(
            typ_zadania=typ.upper(),
            status='PRACA'
        )

        # Uruchamiamy wątek
        thread = threading.Thread(target=watek_generatora, args=(typ.upper(), task.id))
        thread.daemon = True  # Wątek zginie jeśli serwer padnie (to dobrze w tym przypadku)
        thread.start()

        return JsonResponse({'task_id': task.id, 'status': 'start'})
    return JsonResponse({'error': 'Invalid method'}, status=400)


def sprawdz_status(request, task_id):
    """AJAX odpytuje ten widok co kilka sekund"""
    try:
        task = StatusGeneratora.objects.get(id=task_id)
        return JsonResponse({
            'status': task.status,
            'wiadomosc': task.wiadomosc,
            'typ': task.typ_zadania
        })
    except StatusGeneratora.DoesNotExist:
        return JsonResponse({'status': 'BLAD', 'wiadomosc': 'Zadanie nie istnieje'})


# Plan_lekcji/views.py

def drukuj_plany_zbiorcze(request):
    """
    Widok generujący plany lekcji dla wszystkich klas w celu wydruku zbiorczego.
    """
    klasy = Klasa.objects.all().order_by('nazwa')
    plany_klas = []
    dni_tygodnia = ['PON', 'WT', 'SR', 'CZW', 'PT']
    godziny = range(1, 11)  # Zakładamy 10 godzin lekcyjnych

    for klasa in klasy:
        # Pobieramy grupy należące do klasy
        grupy_ids = Klasywgrupach.objects.filter(klasa_id=klasa.id).values_list('grupa_id', flat=True)

        # Pobieramy lekcje dla klasy LUB jej grup
        lekcje = PlanLekcji.objects.filter(
            Q(klasa_id=klasa.id) | Q(grupa_id__in=grupy_ids)
        ).select_related('przedmiot', 'nauczyciel', 'grupa')

        # Budujemy siatkę planu (tak samo jak w widoku index)
        temp_plan = defaultdict(dict)
        for lekcja in lekcje:
            dzien = lekcja.dzien_tygodnia.upper().strip()
            godz = lekcja.godzina_lekcyjna

            nazwa_przedmiotu = lekcja.przedmiot.nazwa_przedmiotu if lekcja.przedmiot else "Brak"
            if lekcja.grupa:
                nazwa_przedmiotu

            nauczyciel = lekcja.nauczyciel.imie_nazwisko if lekcja.nauczyciel else "Brak"

            temp_plan[godz][dzien] = {
                'linia1': nazwa_przedmiotu,
                'linia2': nauczyciel,
                'sala': lekcja.sala
            }

        plany_klas.append({
            'klasa': klasa,
            'plan': temp_plan
        })

    return render(request, 'druk_zbiorczy.html', {
        'plany_klas': plany_klas,
        'dni': dni_tygodnia,
        'godziny': godziny
    })


def custom_login(request):
    """Krok 1: Podstawowe logowanie (username + hasło)"""

    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        # Sprawdź blokadę IP
        ip_address = get_client_ip(request)
        if LoginAttempt.is_blocked(username, ip_address):
            messages.error(request, 'Zbyt wiele nieudanych prób logowania. Spróbuj ponownie za 15 minut.')
            return render(request, 'registration/login.html')

        # Autentykacja
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Zapisz udaną próbę
            LoginAttempt.objects.create(
                username=username,
                ip_address=ip_address,
                success=True
            )

            # Sprawdź czy to zaufane urządzenie
            device_token = request.COOKIES.get('trusted_device_token')
            is_trusted = False

            if device_token:
                trusted_device = TrustedDevice.objects.filter(
                    user=user,
                    device_token=device_token
                ).first()

                if trusted_device and trusted_device.is_valid():
                    # Zaufane urządzenie - zaloguj od razu
                    trusted_device.last_used = timezone.now()
                    trusted_device.save()
                    auth_login(request, user)
                    messages.success(request, f'Witaj ponownie, {user.get_full_name() or user.username}!')
                    return redirect('index')

            # Nie zaufane urządzenie - wymagaj 2FA
            # Usuń stare kody
            VerificationCode.objects.filter(
                user=user,
                purpose='LOGIN',
                created_at__lt=timezone.now() - datetime.timedelta(hours=1)
            ).delete()

            # Utwórz nowy kod
            code = VerificationCode.create_code(user, purpose='LOGIN')
            code.ip_address = ip_address
            code.save()

            # Wyślij email
            if send_verification_code(user, code, request):
                # Zapisz user_id w sesji (tymczasowo)
                request.session['pending_user_id'] = user.id
                request.session['pending_login_time'] = timezone.now().isoformat()

                messages.info(request, f'Kod weryfikacyjny został wysłany na adres {user.email}')
                return redirect('verify_login')
            else:
                messages.error(request, 'Błąd wysyłania emaila. Skontaktuj się z administratorem.')
        else:
            # Zapisz nieudaną próbę
            LoginAttempt.objects.create(
                username=username,
                ip_address=ip_address,
                success=False
            )
            messages.error(request, 'Nieprawidłowa nazwa użytkownika lub hasło.')

    return render(request, 'registration/login.html')


@require_http_methods(["GET", "POST"])
def verify_login(request):
    """Krok 2: Weryfikacja kodu 2FA"""

    # Sprawdź czy użytkownik przeszedł przez krok 1
    user_id = request.session.get('pending_user_id')
    pending_time_str = request.session.get('pending_login_time')

    if not user_id or not pending_time_str:
        messages.warning(request, 'Sesja wygasła. Zaloguj się ponownie.')
        return redirect('login')

    # Sprawdź timeout sesji (10 minut)
    pending_time = timezone.datetime.fromisoformat(pending_time_str)
    if timezone.now() - pending_time > datetime.timedelta(minutes=10):
        del request.session['pending_user_id']
        del request.session['pending_login_time']
        messages.warning(request, 'Kod weryfikacyjny wygasł. Zaloguj się ponownie.')
        return redirect('login')

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect('login')

    if request.method == 'POST':
        entered_code = request.POST.get('code', '').strip()
        remember_device = request.POST.get('remember_device') == 'on'

        # Pobierz najnowszy kod
        verification = VerificationCode.objects.filter(
            user=user,
            purpose='LOGIN',
            is_used=False
        ).order_by('-created_at').first()

        if not verification:
            messages.error(request, 'Nie znaleziono kodu weryfikacyjnego. Zaloguj się ponownie.')
            return redirect('login')

        if not verification.is_valid():
            messages.error(request, 'Kod wygasł. Zaloguj się ponownie.')
            return redirect('login')

        if verification.code == entered_code:
            # Kod poprawny - oznacz jako użyty
            verification.is_used = True
            verification.save()

            # Zaloguj użytkownika
            auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            # Usuń dane tymczasowe z sesji
            del request.session['pending_user_id']
            del request.session['pending_login_time']

            response = redirect('index')

            # Jeśli zaznaczono "Zapamiętaj urządzenie"
            if remember_device:
                device_token = TrustedDevice.generate_token()
                device_name = get_device_name(request)
                ip_address = get_client_ip(request)

                # Utwórz zaufane urządzenie (30 dni ważności)
                TrustedDevice.objects.create(
                    user=user,
                    device_name=device_name,
                    device_token=device_token,
                    ip_address=ip_address,
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    expires_at=timezone.now() + datetime.timedelta(days=30)
                )

                # Ustaw cookie (30 dni)
                response.set_cookie(
                    'trusted_device_token',
                    device_token,
                    max_age=30 * 24 * 60 * 60,  # 30 dni w sekundach
                    secure=True,  # Tylko HTTPS (w produkcji)
                    httponly=True,  # Niedostępne dla JavaScript
                    samesite='Lax'
                )

                # Wyślij powiadomienie
                send_trusted_device_notification(user, device_name, request)

            messages.success(request, f'Pomyślnie zalogowano jako {user.get_full_name() or user.username}')
            return response
        else:
            messages.error(request, 'Nieprawidłowy kod weryfikacyjny.')

    # Dla GET - wyświetl formularz
    return render(request, 'registration/verify_code.html', {
        'user_email': user.email
    })


@require_http_methods(["POST"])
def resend_verification_code(request):
    """API do ponownego wysłania kodu"""
    user_id = request.session.get('pending_user_id')

    if not user_id:
        return JsonResponse({'success': False, 'error': 'Sesja wygasła'})

    try:
        user = User.objects.get(id=user_id)

        # Oznacz stare kody jako nieważne
        VerificationCode.objects.filter(
            user=user,
            purpose='LOGIN',
            is_used=False
        ).update(is_used=True)

        # Utwórz nowy kod
        code = VerificationCode.create_code(user, purpose='LOGIN')
        code.ip_address = get_client_ip(request)
        code.save()

        # Wyślij
        if send_verification_code(user, code, request):
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False, 'error': 'Błąd wysyłania emaila'})
    except User.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Użytkownik nie istnieje'})


# --- RESET HASŁA ---

def password_reset_request(request):
    """Krok 1: Żądanie resetu hasła"""

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()

        try:
            user = User.objects.get(email=email)

            # Usuń stare kody
            VerificationCode.objects.filter(
                user=user,
                purpose='PASSWORD_RESET',
                created_at__lt=timezone.now() - datetime.timedelta(hours=1)
            ).delete()

            # Utwórz nowy kod (ważny 15 minut)
            code = VerificationCode.create_code(user, purpose='PASSWORD_RESET', validity_minutes=15)
            code.ip_address = get_client_ip(request)
            code.save()

            # Wyślij email
            if send_password_reset_code(user, code, request):
                request.session['reset_user_id'] = user.id
                messages.success(request, 'Kod do resetu hasła został wysłany na Twój email.')
                return redirect('password_reset_verify')
            else:
                messages.error(request, 'Błąd wysyłania emaila. Spróbuj ponownie później.')
        except User.DoesNotExist:
            # Z bezpieczeństwa nie mówimy, że email nie istnieje
            messages.success(request, 'Jeśli konto z tym emailem istnieje, kod został wysłany.')
            return redirect('login')

    return render(request, 'registration/password_reset_request.html')


def password_reset_verify(request):
    """Krok 2: Weryfikacja kodu i ustawienie nowego hasła"""

    user_id = request.session.get('reset_user_id')
    if not user_id:
        messages.warning(request, 'Sesja wygasła. Rozpocznij proces resetu ponownie.')
        return redirect('password_reset_request')

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect('login')

    if request.method == 'POST':
        entered_code = request.POST.get('code', '').strip()
        new_password = request.POST.get('new_password')
        new_password_confirm = request.POST.get('new_password_confirm')

        # Walidacja hasła
        if new_password != new_password_confirm:
            messages.error(request, 'Hasła nie są identyczne.')
            return render(request, 'registration/password_reset_verify.html')

        if len(new_password) < 8:
            messages.error(request, 'Hasło musi mieć minimum 8 znaków.')
            return render(request, 'registration/password_reset_verify.html')

        # Sprawdź kod
        verification = VerificationCode.objects.filter(
            user=user,
            purpose='PASSWORD_RESET',
            is_used=False
        ).order_by('-created_at').first()

        if not verification:
            messages.error(request, 'Nie znaleziono kodu. Rozpocznij proces ponownie.')
            return redirect('password_reset_request')

        if not verification.is_valid():
            messages.error(request, 'Kod wygasł. Rozpocznij proces ponownie.')
            return redirect('password_reset_request')

        if verification.code == entered_code:
            # Kod poprawny - zmień hasło
            user.set_password(new_password)
            user.save()

            verification.is_used = True
            verification.save()

            del request.session['reset_user_id']

            # Usuń wszystkie zaufane urządzenia (ze względów bezpieczeństwa)
            TrustedDevice.objects.filter(user=user).delete()

            messages.success(request, 'Hasło zostało zmienione. Możesz się teraz zalogować.')
            return redirect('login')
        else:
            messages.error(request, 'Nieprawidłowy kod weryfikacyjny.')

    return render(request, 'registration/password_reset_verify.html')


# --- ZARZĄDZANIE ZAUFANYMI URZĄDZENIAMI ---

@login_required
def trusted_devices(request):
    """Lista zaufanych urządzeń użytkownika"""
    devices = TrustedDevice.objects.filter(user=request.user)
    return render(request, 'registration/trusted_devices.html', {
        'devices': devices
    })


@login_required
@require_http_methods(["POST"])
def remove_trusted_device(request, device_id):
    """Usuń zaufane urządzenie"""
    device = TrustedDevice.objects.filter(id=device_id, user=request.user).first()

    if device:
        device_name = device.device_name
        device.delete()
        messages.success(request, f'Urządzenie "{device_name}" zostało usunięte.')
    else:
        messages.error(request, 'Nie znaleziono urządzenia.')

    return redirect('trusted_devices')


@login_required
@require_http_methods(["POST"])
def remove_all_trusted_devices(request):
    """Usuń wszystkie zaufane urządzenia"""
    count = TrustedDevice.objects.filter(user=request.user).count()
    TrustedDevice.objects.filter(user=request.user).delete()

    messages.success(request, f'Usunięto {count} zaufanych urządzeń.')
    return redirect('trusted_devices')


def custom_logout(request):
    """Wylogowanie z opcjonalnym usunięciem urządzenia"""
    auth_logout(request)
    response = redirect('login')

    # Usuń cookie zaufanego urządzenia
    response.delete_cookie('trusted_device_token')

    messages.info(request, 'Zostałeś wylogowany.')
    return response


def error_404(request, exception):
    """Obsługa błędu 404 - Strona nie znaleziona"""
    return render(request, 'errors/404.html', status=404)

def error_500(request):
    """Obsługa błędu 500 - Błąd serwera"""
    return render(request, 'errors/500.html', status=500)

def error_403(request, exception):
    """Obsługa błędu 403 - Brak dostępu"""
    return render(request, 'errors/403.html', status=403)

def error_400(request, exception):
    """Obsługa błędu 400 - Nieprawidłowe żądanie"""
    return render(request, 'errors/400.html', status=400)