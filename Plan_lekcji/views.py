from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.views.decorators.http import require_POST
from django.db.models import Q
from collections import defaultdict
import json

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
    wymagania_lista = WymaganiaPrzedmiotowe.objects.all().select_related('nauczyciel', 'klasa', 'przedmiot')
    return render(request, 'wymagania.html', {'wymagania': wymagania_lista})


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
    grupy = Grupylekcyjne.objects.all().select_related('nauczyciel', 'przedmiot').prefetch_related('klasy')
    return render(request, 'grupy.html', {'grupy': grupy})


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


@user_passes_test(is_admin)
def usun_grupe(request, pk):
    obj = get_object_or_404(Grupylekcyjne, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Usunięto grupę.')
    return redirect('grupy')


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
@user_passes_test(is_admin)
def lista_nauczycieli(request):
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')
    return render(request, 'slowniki/nauczyciele_lista.html', {'nauczyciele': nauczyciele})


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
@user_passes_test(is_admin)
def lista_przedmiotow(request):
    przedmioty = Przedmioty.objects.all().order_by('nazwa_przedmiotu')
    return render(request, 'slowniki/przedmioty_lista.html', {'przedmioty': przedmioty})


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
@user_passes_test(is_admin)
def lista_klas(request):
    klasy = Klasa.objects.all().order_by('id')
    return render(request, 'slowniki/klasy_lista.html', {'klasy': klasy})


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