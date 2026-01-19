from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
from django.db.models import Q
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


# --- STRONA GŁÓWNA (PUBLICZNA) ---

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
            lekcje = PlanLekcji.objects.filter(nauczyciel_id=selected_nauczyciel_id) \
                .select_related('przedmiot', 'klasa', 'grupa')

            temp_plan = defaultdict(dict)
            for lekcja in lekcje:
                dzien = lekcja.dzien_tygodnia.upper().strip()
                godz = lekcja.godzina_lekcyjna

                nazwa_przedmiotu = lekcja.przedmiot.nazwa_przedmiotu if lekcja.przedmiot else "Brak"
                if lekcja.grupa:
                    info_dodatkowe = f"Grupa: {lekcja.grupa.nazwa_grupy}"
                elif lekcja.klasa:
                    info_dodatkowe = f"Klasa {lekcja.klasa.nazwa}"
                else:
                    info_dodatkowe = "-"

                temp_plan[godz][dzien] = {
                    'id': lekcja.id,  # POTRZEBNE DO EDYCJI
                    'sala': lekcja.sala,  # NOWE POLE
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
                Q(klasa_id=selected_klasa_id) | Q(grupa_id__in=grupy_ids)
            ).select_related('przedmiot', 'nauczyciel', 'grupa')

            temp_plan = defaultdict(dict)
            for lekcja in lekcje:
                dzien = lekcja.dzien_tygodnia.upper().strip()
                godz = lekcja.godzina_lekcyjna

                nazwa_przedmiotu = lekcja.przedmiot.nazwa_przedmiotu if lekcja.przedmiot else "Brak"
                if lekcja.grupa:
                    nazwa_przedmiotu += f" ({lekcja.grupa.nazwa_grupy})"

                nauczyciel = lekcja.nauczyciel.imie_nazwisko if lekcja.nauczyciel else "Brak"

                temp_plan[godz][dzien] = {
                    'id': lekcja.id,  # POTRZEBNE DO EDYCJI
                    'sala': lekcja.sala,  # NOWE POLE
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
def wymagania(request):
    # Parametry filtrowania
    search_query = request.GET.get('q', '')
    nauczyciel_id = request.GET.get('nauczyciel_id', '')
    klasa_id = request.GET.get('klasa_id', '')
    sort_by = request.GET.get('sort', 'id')

    # Baza zapytań
    wymagania_lista = WymaganiaPrzedmiotowe.objects.all().select_related('nauczyciel', 'klasa', 'przedmiot')

    # 1. Filtrowanie
    if search_query:
        # Szukamy po nazwie przedmiotu lub skrócie
        wymagania_lista = wymagania_lista.filter(
            Q(przedmiot__nazwa_przedmiotu__icontains=search_query) |
            Q(przedmiot__skrot__icontains=search_query)
        )

    if nauczyciel_id:
        wymagania_lista = wymagania_lista.filter(nauczyciel_id=nauczyciel_id)

    if klasa_id:
        wymagania_lista = wymagania_lista.filter(klasa_id=klasa_id)

    # 2. Sortowanie
    sort_mapping = {
        'nauczyciel': 'nauczyciel__imie_nazwisko',
        '-nauczyciel': '-nauczyciel__imie_nazwisko',
        'klasa': 'klasa__id',
        '-klasa': '-klasa__id',
        'przedmiot': 'przedmiot__nazwa_przedmiotu',
        '-przedmiot': '-przedmiot__nazwa_przedmiotu',
        'godziny': 'liczba_godzin',
        '-godziny': '-liczba_godzin'
    }

    sort_field = sort_mapping.get(sort_by, 'id')
    wymagania_lista = wymagania_lista.order_by(sort_field)

    # Dane do dropdownów
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')
    klasy = Klasa.objects.all().order_by('id')

    return render(request, 'wymagania.html', {
        'wymagania': wymagania_lista,
        'nauczyciele': nauczyciele,
        'klasy': klasy,
        'search_query': search_query,
        'selected_nauczyciel_id': nauczyciel_id,
        'selected_klasa_id': klasa_id,
        'current_sort': sort_by
    })

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


# --- ZARZĄDZANIE GRUPAMI (ADMIN) ---
@user_passes_test(is_admin)
def grupy_lekcyjne(request):
    search_query = request.GET.get('q', '')
    nauczyciel_id = request.GET.get('nauczyciel_id', '')
    sort_by = request.GET.get('sort', 'nazwa_grupy')

    grupy = Grupylekcyjne.objects.all().select_related('nauczyciel', 'przedmiot').prefetch_related('klasy')

    # 1. Filtrowanie (ZAKTUALIZOWANE)
    if search_query:
        grupy = grupy.filter(
            Q(nazwa_grupy__icontains=search_query) |  # Po nazwie grupy
            Q(przedmiot__nazwa_przedmiotu__icontains=search_query) |  # Po nazwie przedmiotu
            Q(przedmiot__skrot__icontains=search_query) |  # Po skrócie przedmiotu
            Q(klasy__id__icontains=search_query) |  # Po ID klasy (np. 1A)
            Q(klasy__nazwa__icontains=search_query)  # Po nazwie klasy
        ).distinct()  # distinct() usuwa duplikaty, które mogą powstać przy szukaniu w relacji ManyToMany

    if nauczyciel_id:
        grupy = grupy.filter(nauczyciel_id=nauczyciel_id)

    # 2. Sortowanie
    sort_mapping = {
        'nazwa_grupy': 'nazwa_grupy',
        '-nazwa_grupy': '-nazwa_grupy',
        'przedmiot': 'przedmiot__nazwa_przedmiotu',
        '-przedmiot': '-przedmiot__nazwa_przedmiotu',
        'nauczyciel': 'nauczyciel__imie_nazwisko',
        '-nauczyciel': '-nauczyciel__imie_nazwisko',
        'godziny': 'liczba_godzin_w_grupie',
        '-godziny': '-liczba_godzin_w_grupie'
    }

    sort_field = sort_mapping.get(sort_by, 'nazwa_grupy')
    grupy = grupy.order_by(sort_field)

    # Dane do dropdowna
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')

    return render(request, 'grupy.html', {
        'grupy': grupy,
        'nauczyciele': nauczyciele,
        'search_query': search_query,
        'selected_nauczyciel_id': nauczyciel_id,
        'current_sort': sort_by
    })
@user_passes_test(is_admin)
def edytuj_grupe(request, pk=None):
    if pk:
        instancja = get_object_or_404(Grupylekcyjne, pk=pk)
        tytul = "Edytuj Grupę"
    else:
        instancja = None
        tytul = "Dodaj Grupę"

    if request.method == 'POST':
        form = GrupaForm(request.POST, instance=instancja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zapisano grupę.')
            return redirect('grupy')
    else:
        form = GrupaForm(instance=instancja)

    return render(request, 'slowniki/formularz_bazowy.html', {'form': form, 'tytul': tytul})


# Plan_lekcji/views.py

# Plan_lekcji/views.py

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

    # Pobieramy adres strony, z której przyszedł użytkownik (Referer)
    # Dzięki temu wrócimy dokładnie do tego samego widoku (Klasy lub Nauczyciela)
    referer = request.META.get('HTTP_REFERER') or '/'

    if request.method == 'POST':
        form = EdycjaLekcjiForm(request.POST, instance=lekcja)
        if form.is_valid():
            form.save()
            messages.success(request, 'Zaktualizowano lekcję na planie.')

            # Pobieramy adres powrotu z ukrytego pola (jeśli zostało przesłane) lub z sesji
            return_url = request.POST.get('return_url', '/')

            # Jeśli return_url to tylko sam ukośnik (nie zadziałało), próbujemy logiki:
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
        'return_url': referer  # Przekazujemy referer do template'u
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
    # Jeśli różnica między pierwszą a ostatnią godziną + 1 jest większa niż liczba lekcji,
    # to znaczy, że są dziury w środku.
    return (end - start + 1) != len(sorted_h)


@user_passes_test(is_admin)
@require_POST
def api_zamien_lekcje(request):
    data = json.loads(request.body)
    lekcja_id = data.get('lekcja_id')
    target_dzien = data.get('target_dzien')
    target_godzina = int(data.get('target_godzina'))
    force = data.get('force', False)

    # 1. Pobierz lekcję źródłową
    lekcja_source = get_object_or_404(PlanLekcji, pk=lekcja_id)
    old_dzien = lekcja_source.dzien_tygodnia
    old_godzina = lekcja_source.godzina_lekcyjna

    nauczyciel = lekcja_source.nauczyciel

    # Rozpoznanie klas(y)
    klasy_do_sprawdzenia = []
    if lekcja_source.klasa:
        klasy_do_sprawdzenia.append(lekcja_source.klasa)
    elif lekcja_source.grupa:
        # POBIERAMY WSZYSTKIE KLASY Z GRUPY
        klasy_do_sprawdzenia.extend(lekcja_source.grupa.klasy.all())

    # 2. Identyfikacja lekcji docelowej
    typ_widoku = data.get('typ_widoku')
    obiekt_id = data.get('obiekt_id')

    lekcja_target = None
    # Logika szukania celu pozostaje bez zmian (uproszczona dla czytelności przykładu)
    if typ_widoku == 'klasa':
        lekcja_target = PlanLekcji.objects.filter(
            klasa_id=obiekt_id, dzien_tygodnia=target_dzien, godzina_lekcyjna=target_godzina
        ).first()
        if not lekcja_target:
            grupy_ids = Klasywgrupach.objects.filter(klasa_id=obiekt_id).values_list('grupa_id', flat=True)
            lekcja_target = PlanLekcji.objects.filter(
                grupa_id__in=grupy_ids, dzien_tygodnia=target_dzien, godzina_lekcyjna=target_godzina
            ).first()
    elif typ_widoku == 'nauczyciel':
        lekcja_target = PlanLekcji.objects.filter(
            nauczyciel_id=obiekt_id, dzien_tygodnia=target_dzien, godzina_lekcyjna=target_godzina
        ).first()

    # ---------------------------------------------------------
    # WALIDACJA
    # ---------------------------------------------------------
    if not force:
        bledy = []
        ignored_ids = [lekcja_source.id]
        if lekcja_target: ignored_ids.append(lekcja_target.id)

        # --- A. NAUCZYCIEL (Konflikty + Ograniczenia + Okienka) ---
        if nauczyciel:
            # 1. Konflikt terminów
            kolizja_nauczyciel = PlanLekcji.objects.filter(
                nauczyciel=nauczyciel,
                dzien_tygodnia=target_dzien,
                godzina_lekcyjna=target_godzina
            ).exclude(id__in=ignored_ids).exists()

            if kolizja_nauczyciel:
                bledy.append(f"Nauczyciel {nauczyciel} ma już inną lekcję w tym czasie.")

            # 2. Ograniczenia (dostępność)
            ograniczenie = Ograniczenia.objects.filter(
                nauczyciel=nauczyciel, dzien_tygodnia=target_dzien,
                od__lte=target_godzina, do__gte=target_godzina
            ).exists()
            if ograniczenie:
                bledy.append(f"Nauczyciel {nauczyciel} ma blokadę w tym terminie.")

            # 3. Wykrywanie OKIENEK (Jeśli przenosimy lekcję na ten sam dzień)
            # Analizujemy plan nauczyciela w dniu docelowym
            if target_dzien == old_dzien:  # Uproszczenie: sprawdzamy okienka przy zmianach w obrębie dnia
                # Pobierz godziny z bazy (bez ruszanej lekcji)
                godziny_nauczyciela = list(PlanLekcji.objects.filter(
                    nauczyciel=nauczyciel, dzien_tygodnia=target_dzien
                ).exclude(id__in=ignored_ids).values_list('godzina_lekcyjna', flat=True))

                # Symulacja: dodajemy nową godzinę
                godziny_nauczyciela.append(target_godzina)

                if sprawdz_czy_sa_okienka(godziny_nauczyciela):
                    bledy.append(f"Uwaga: Ten ruch stworzy 'okienko' w planie nauczyciela {nauczyciel}.")

        # --- B. KLASY (Pętla po wszystkich klasach - obsługa grup) ---
        for klasa in klasy_do_sprawdzenia:
            grupy_tej_klasy = Klasywgrupach.objects.filter(klasa=klasa).values_list('grupa_id', flat=True)

            # 1. Konflikt terminów
            kolizja_klasa = PlanLekcji.objects.filter(
                Q(klasa=klasa) | Q(grupa_id__in=grupy_tej_klasy),
                dzien_tygodnia=target_dzien,
                godzina_lekcyjna=target_godzina
            ).exclude(id__in=ignored_ids).exists()

            if kolizja_klasa:
                bledy.append(f"Klasa {klasa.nazwa} (lub jej grupa) ma już zajęcia w tym czasie.")

            # 2. Ograniczenia klasy
            ograniczenie_klasy = OgraniczeniaKlas.objects.filter(
                klasa=klasa, dzien_tygodnia=target_dzien,
                od__lte=target_godzina, do__gte=target_godzina
            ).exists()
            if ograniczenie_klasy:
                bledy.append(f"Klasa {klasa.nazwa} ma blokadę w tym terminie.")

            # 3. Wykrywanie OKIENEK dla klasy
            if target_dzien == old_dzien:
                # Pobieramy zajęcia klasy (i jej grup) w tym dniu
                godziny_klasy = list(PlanLekcji.objects.filter(
                    Q(klasa=klasa) | Q(grupa_id__in=grupy_tej_klasy),
                    dzien_tygodnia=target_dzien
                ).exclude(id__in=ignored_ids).values_list('godzina_lekcyjna', flat=True))

                godziny_klasy.append(target_godzina)

                if sprawdz_czy_sa_okienka(godziny_klasy):
                    bledy.append(f"Uwaga: Ten ruch stworzy 'okienko' dla klasy {klasa.nazwa}.")

        # --- C. SALE ---
        sala_source = lekcja_source.sala
        if sala_source:
            kolizja_sala = PlanLekcji.objects.filter(
                sala=sala_source, dzien_tygodnia=target_dzien, godzina_lekcyjna=target_godzina
            ).exclude(id__in=ignored_ids).exists()
            if kolizja_sala:
                bledy.append(f"Sala {sala_source} jest zajęta w docelowym terminie.")

        # ZWRACANIE BŁĘDÓW
        if bledy:
            komunikat = "Informacje i Ostrzeżenia:\n- " + "\n- ".join(list(set(bledy)))  # set() usuwa duplikaty
            return JsonResponse({'status': 'confirm', 'message': komunikat})

    # ---------------------------------------------------------
    # WYKONANIE ZMIAN
    # ---------------------------------------------------------
    if lekcja_target:
        # SWAP
        lekcja_target.dzien_tygodnia = old_dzien
        lekcja_target.godzina_lekcyjna = old_godzina
        lekcja_target.save()

        lekcja_source.dzien_tygodnia = target_dzien
        lekcja_source.godzina_lekcyjna = target_godzina
        lekcja_source.save()
        msg = 'Zamieniono lekcje miejscami (SWAP).'
    else:
        # MOVE
        lekcja_source.dzien_tygodnia = target_dzien
        lekcja_source.godzina_lekcyjna = target_godzina
        lekcja_source.save()
        msg = 'Przesunięto lekcję.'

    return JsonResponse({'status': 'ok', 'message': msg})


# --- AUTOMATYCZNE SUGEROWANIE GRUP ---

@user_passes_test(is_admin)
def sugeruj_grupy(request):
    # Pobieramy wszystkie wymagania, które mają > 0 godzin
    wymagania = WymaganiaPrzedmiotowe.objects.filter(liczba_godzin__gt=0).select_related('klasa', 'nauczyciel',
                                                                                         'przedmiot')

    # Słownik pomocniczy do grupowania:
    # Klucz: (Przedmiot ID, Nauczyciel ID, Liczba Godzin, Rocznik Klasy)
    # Wartość: Lista obiektów wymagań
    grupy_robocze = defaultdict(list)

    for w in wymagania:
        # Klucz grupowania:
        # Ważne: Łączymy tylko klasy z tego samego rocznika (w.klasa.rok)
        klucz = (
            w.przedmiot,
            w.nauczyciel,
            w.liczba_godzin,
            w.klasa.rok
        )
        grupy_robocze[klucz].append(w)

    sugestie = []
    MAKS_OSOB = 51  # Limit z Twojego pliku

    for (przedmiot, nauczyciel, godziny, rok), lista_wymagan in grupy_robocze.items():
        # Sens łączenia jest tylko wtedy, gdy mamy więcej niż 1 klasę
        if len(lista_wymagan) > 1:
            # Sprawdzamy sumę uczniów
            suma_osob = sum(w.klasa.ilosc_osob for w in lista_wymagan)

            if suma_osob <= MAKS_OSOB:
                # Tworzymy propozycję
                klasy_w_propozycji = [w.klasa for w in lista_wymagan]
                nazwy_klas = ", ".join([k.nazwa for k in klasy_w_propozycji])
                ids_klas = ",".join([str(k.id) for k in klasy_w_propozycji])  # Potrzebne do formularza POST

                sugestie.append({
                    'przedmiot': przedmiot,
                    'nauczyciel': nauczyciel,
                    'godziny': godziny,
                    'klasy': klasy_w_propozycji,
                    'nazwy_klas_str': nazwy_klas,
                    'ids_klas_hidden': ids_klas,  # Ukryte pole dla backendu
                    'suma_osob': suma_osob,
                    'rok': rok
                })

    return render(request, 'slowniki/sugestie_grup.html', {
        'sugestie': sugestie
    })


@user_passes_test(is_admin)
def akceptuj_sugestie(request):
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # 1. Pobieramy dane z ukrytego formularza
                przedmiot_id = request.POST.get('przedmiot_id')
                nauczyciel_id = request.POST.get('nauczyciel_id')  # Może być puste
                godziny = int(request.POST.get('godziny'))
                ids_klas_str = request.POST.get('ids_klas')

                # Konwersja danych
                przedmiot = get_object_or_404(Przedmioty, id=przedmiot_id)
                nauczyciel = None
                if nauczyciel_id and nauczyciel_id != 'None':
                    nauczyciel = get_object_or_404(Nauczyciel, id=nauczyciel_id)

                ids_klas = ids_klas_str.split(',')
                klasy_objs = Klasa.objects.filter(id__in=ids_klas)

                # Generujemy nazwę grupy automatycznie
                nazwy_klas = "-".join([k.nazwa for k in klasy_objs])
                skrot_przedmiotu = przedmiot.skrot if przedmiot.skrot else przedmiot.nazwa_przedmiotu[:3]
                nazwa_grupy = f"{skrot_przedmiotu}_{nazwy_klas}"

                # 2. Tworzymy grupę
                nowa_grupa = Grupylekcyjne.objects.create(
                    nazwa_grupy=nazwa_grupy,
                    przedmiot=przedmiot,
                    nauczyciel=nauczyciel,
                    liczba_godzin_w_grupie=godziny
                )

                # Przypisujemy klasy (M2M)
                nowa_grupa.klasy.set(klasy_objs)
                nowa_grupa.save()

                # 3. AKTUALIZACJA WYMAGAŃ (To samo co przy ręcznym dodawaniu)
                log_info = []
                for klasa in klasy_objs:
                    wymaganie = WymaganiaPrzedmiotowe.objects.filter(
                        klasa=klasa, przedmiot=przedmiot, nauczyciel=nauczyciel
                    ).first()

                    if wymaganie:
                        stara_ilosc = wymaganie.liczba_godzin
                        nowa_ilosc = max(0, stara_ilosc - godziny)
                        if stara_ilosc != nowa_ilosc:
                            wymaganie.liczba_godzin = nowa_ilosc
                            wymaganie.save()
                            log_info.append(f"{klasa.nazwa}")

                messages.success(request, f"Utworzono grupę '{nazwa_grupy}'.")
                if log_info:
                    messages.info(request, f"Odjęto godziny z wymagań dla: {', '.join(log_info)}")

        except Exception as e:
            messages.error(request, f"Błąd tworzenia grupy: {e}")

    return redirect('sugeruj_grupy')