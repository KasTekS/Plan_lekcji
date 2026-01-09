import json
from django.http import JsonResponse
from django.shortcuts import render
from django.db.models import Q  # <--- WAŻNY IMPORT DO ŁĄCZENIA WARUNKÓW
from collections import defaultdict
from .forms import NauczycielForm, KlasaForm, PrzedmiotForm, WymaganieForm, GrupaForm
from .models import Nauczyciel, Klasa, Przedmioty
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import (
    WymaganiaPrzedmiotowe, Grupylekcyjne, PlanLekcji,
    Klasa, Nauczyciel, Klasywgrupach, Ograniczenia, OgraniczeniaKlas
)


# --- NOWA STRONA GŁÓWNA (PLAN LEKCJI) ---
def index(request):
    klasy = Klasa.objects.all().order_by('nazwa')
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')  # Pobieramy nauczycieli

    selected_klasa_id = request.GET.get('klasa_id')
    selected_nauczyciel_id = request.GET.get('nauczyciel_id')

    plan_data = {}
    selected_obiekt = None  # Przechowa wybrany obiekt (Klasa lub Nauczyciel)
    typ_widoku = None  # 'klasa' lub 'nauczyciel'

    dni_tygodnia = ['PON', 'WT', 'SR', 'CZW', 'PT']
    godziny = range(1, 11)

    # Logika wyboru widoku (priorytet ma nauczyciel, jeśli oba parametry przyszły,
    # ale JavaScript w szablonie zadba o to, by wysyłać tylko jeden)

    if selected_nauczyciel_id:
        typ_widoku = 'nauczyciel'
        selected_obiekt = Nauczyciel.objects.filter(id=selected_nauczyciel_id).first()

        if selected_obiekt:
            # Pobieramy lekcje tego nauczyciela
            lekcje = PlanLekcji.objects.filter(nauczyciel_id=selected_nauczyciel_id) \
                .select_related('przedmiot', 'klasa', 'grupa')

            temp_plan = defaultdict(dict)
            for lekcja in lekcje:
                dzien = lekcja.dzien_tygodnia.upper().strip()
                godz = lekcja.godzina_lekcyjna

                nazwa_przedmiotu = lekcja.przedmiot.nazwa_przedmiotu if lekcja.przedmiot else "Brak"

                # W widoku nauczyciela, "drugą linią" jest Klasa lub Grupa
                if lekcja.grupa:
                    # Pobieramy nazwy klas w tej grupie (wymaga dodatkowego zapytania lub prefetch,
                    # tu dla prostoty wyświetlimy nazwę grupy)
                    info_dodatkowe = f"Grupa: {lekcja.grupa.nazwa_grupy}"
                elif lekcja.klasa:
                    info_dodatkowe = f"Klasa {lekcja.klasa.nazwa}"
                else:
                    info_dodatkowe = "-"

                temp_plan[godz][dzien] = {
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

                # W widoku klasy, "drugą linią" jest Nauczyciel
                nauczyciel = lekcja.nauczyciel.imie_nazwisko if lekcja.nauczyciel else "Brak"

                temp_plan[godz][dzien] = {
                    'linia1': nazwa_przedmiotu,
                    'linia2': nauczyciel
                }
            plan_data = temp_plan

    return render(request, 'index.html', {
        'klasy': klasy,
        'nauczyciele': nauczyciele,  # Przekazujemy listę nauczycieli
        'selected_klasa_id': selected_klasa_id,
        'selected_nauczyciel_id': selected_nauczyciel_id,
        'selected_obiekt': selected_obiekt,
        'typ_widoku': typ_widoku,
        'plan': plan_data,
        'dni': dni_tygodnia,
        'godziny': godziny
    })


# --- POZOSTAŁE WIDOKI ---
def wymagania(request):
    wymagania_lista = WymaganiaPrzedmiotowe.objects.all().select_related('nauczyciel', 'klasa', 'przedmiot')
    return render(request, 'wymagania.html', {'wymagania': wymagania_lista})


def grupy_lekcyjne(request):
    grupy = Grupylekcyjne.objects.all().select_related('nauczyciel', 'przedmiot').prefetch_related('klasy')
    return render(request, 'grupy.html', {'grupy': grupy})


# --- WIDOKI OGRANICZEŃ ---

def przygotuj_siatke_ograniczen(obiekty, typ='nauczyciel'):
    """
    Pomocnicza funkcja budująca strukturę danych dla template'u.
    Zwraca listę: [{'obj': obiekt, 'grid': { 'PON': {1: True, 2: False...}, ... } }, ...]
    True = Zablokowane (Red), False = Wolne (White)
    """
    dni_map = ['PON', 'WT', 'SR', 'CZW', 'PT']
    godziny = range(1, 11)
    dane_wyjsciowe = []

    for obj in obiekty:
        # Inicjalizacja pustej siatki (wszystko wolne)
        grid = {d: {g: False for g in godziny} for d in dni_map}

        # Pobieranie ograniczeń z bazy
        if typ == 'nauczyciel':
            ograniczenia = Ograniczenia.objects.filter(nauczyciel=obj)
        else:
            ograniczenia = OgraniczeniaKlas.objects.filter(klasa=obj)

        for ogr in ograniczenia:
            dzien = ogr.dzien_tygodnia  # Zakładamy, że w bazie jest PON, WT itd.
            if dzien in grid:
                # Oznaczamy godziny od-do jako zablokowane
                # Uwaga: Ograniczenia mogą mieć null w od/do, warto zabezpieczyć
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


def ograniczenia_nauczycieli(request):
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')
    siatka = przygotuj_siatke_ograniczen(nauczyciele, typ='nauczyciel')

    return render(request, 'ograniczenia_nauczycieli.html', {
        'siatka': siatka,
        'dni': ['PON', 'WT', 'SR', 'CZW', 'PT'],
        'godziny': range(1, 11)
    })


def ograniczenia_klas_view(request):  # Zmienilem nazwę by nie kolidowała z modelem
    klasy = Klasa.objects.all().order_by('nazwa')
    siatka = przygotuj_siatke_ograniczen(klasy, typ='klasa')

    return render(request, 'ograniczenia_klas.html', {
        'siatka': siatka,
        'dni': ['PON', 'WT', 'SR', 'CZW', 'PT'],
        'godziny': range(1, 11)
    })


# --- API DO KLIKANIA (AJAX) ---

@require_POST
def toggle_ograniczenie(request):
    """
    Odbiera JSON: { 'type': 'nauczyciel'/'klasa', 'id': 1, 'day': 'PON', 'hour': 5 }
    Logika:
    1. Sprawdza czy jest już blokada na tę godzinę.
    2. Jeśli TAK -> Usuwa ją (lub dzieli zakres).
    3. Jeśli NIE -> Dodaje nową blokadę (na razie pojedynczą godzinę dla uproszczenia,
       algorytm i tak to zrozumie, a łączenie w zakresy można robić okresowo).
    """
    data = json.loads(request.body)
    obj_type = data.get('type')
    obj_id = data.get('id')
    day = data.get('day')
    hour = int(data.get('hour'))

    ModelOgraniczen = Ograniczenia if obj_type == 'nauczyciel' else OgraniczeniaKlas
    field_name = 'nauczyciel_id' if obj_type == 'nauczyciel' else 'klasa_id'  # db_column mapping

    # Szukamy czy ta godzina wpada w istniejący zakres
    # Zakres w bazie: od <= hour ORAZ do >= hour
    istniejace = ModelOgraniczen.objects.filter(
        dzien_tygodnia=day,
        od__lte=hour,
        do__gte=hour,
        **{field_name: obj_id}  # Dynamiczny filtr
    ).first()

    status = 'error'

    if istniejace:
        # --- USUWANIE BLOKADY (ODBLOKOWANIE) ---
        # Mamy 4 przypadki:
        # 1. Zakres to tylko ta jedna godzina (np. 5-5) -> Usuwamy rekord.
        # 2. Usuwamy początek (np. 4-8, usuwamy 4) -> Zmieniamy na 5-8.
        # 3. Usuwamy koniec (np. 4-8, usuwamy 8) -> Zmieniamy na 4-7.
        # 4. Usuwamy środek (np. 4-8, usuwamy 6) -> Dzielimy na 4-5 i 7-8.

        od = istniejace.od
        do = istniejace.do

        if od == do:
            istniejace.delete()  # Przypadek 1
        elif hour == od:
            istniejace.od = od + 1  # Przypadek 2
            istniejace.save()
        elif hour == do:
            istniejace.do = do - 1  # Przypadek 3
            istniejace.save()
        else:
            # Przypadek 4 (Dzielenie)
            # Stary rekord staje się lewą częścią
            istniejace.do = hour - 1
            istniejace.save()
            # Tworzymy nowy rekord dla prawej części
            ModelOgraniczen.objects.create(
                dzien_tygodnia=day,
                od=hour + 1,
                do=do,
                **{field_name: obj_id}
            )
        status = 'unblocked'

    else:
        # --- DODAWANIE BLOKADY (ZABLOKOWANIE) ---
        # Dla uproszczenia logiki frontendu, tworzymy pojedynczy wpis od=X, do=X.
        # (Można by tu dodać logikę sklejania z sąsiadami, ale nie jest to krytyczne dla działania algorytmu).

        # Sprawdzenie czy sąsiaduje z czymś (opcjonalne "sklejanie" basic)
        lewy_sasiad = ModelOgraniczen.objects.filter(dzien_tygodnia=day, do=hour - 1, **{field_name: obj_id}).first()
        prawy_sasiad = ModelOgraniczen.objects.filter(dzien_tygodnia=day, od=hour + 1, **{field_name: obj_id}).first()

        if lewy_sasiad and prawy_sasiad:
            # Sklejamy wszystko w jeden: lewy rośnie do końca prawego, prawy usuwamy
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
            # Brak sąsiadów, nowy pojedynczy blok
            ModelOgraniczen.objects.create(
                dzien_tygodnia=day,
                od=hour,
                do=hour,
                **{field_name: obj_id}
            )
        status = 'blocked'

    return JsonResponse({'status': status})

# --- CRUD NAUCZYCIELE ---

def lista_nauczycieli(request):
    nauczyciele = Nauczyciel.objects.all().order_by('imie_nazwisko')
    return render(request, 'slowniki/nauczyciele_lista.html', {'nauczyciele': nauczyciele})

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

def usun_nauczyciela(request, pk):
    obj = get_object_or_404(Nauczyciel, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Nauczyciel został usunięty.')
    return redirect('lista_nauczycieli')

# --- CRUD PRZEDMIOTY ---

def lista_przedmiotow(request):
    przedmioty = Przedmioty.objects.all().order_by('nazwa_przedmiotu')
    return render(request, 'slowniki/przedmioty_lista.html', {'przedmioty': przedmioty})

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

def usun_przedmiot(request, pk):
    obj = get_object_or_404(Przedmioty, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Przedmiot usunięty.')
    return redirect('lista_przedmiotow')

# --- CRUD KLASY ---

def lista_klas(request):
    klasy = Klasa.objects.all().order_by('id')
    return render(request, 'slowniki/klasy_lista.html', {'klasy': klasy})

def edytuj_klase(request, pk=None):
    # Uwaga: pk dla klasy to string (np. '1A'), więc url musi to obsłużyć
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

def usun_klase(request, pk):
    obj = get_object_or_404(Klasa, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Klasa usunięta.')
    return redirect('lista_klas')

def wymagania(request):
    # To jest widok listy (index dla wymagań)
    wymagania_lista = WymaganiaPrzedmiotowe.objects.all().select_related('nauczyciel', 'klasa', 'przedmiot')
    return render(request, 'wymagania.html', {'wymagania': wymagania_lista})

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

def usun_wymaganie(request, pk):
    obj = get_object_or_404(WymaganiaPrzedmiotowe, pk=pk)
    if request.method == 'POST':
        obj.delete()
        messages.success(request, 'Usunięto wymaganie.')
    return redirect('wymagania')

# --- GRUPY LEKCYJNE (CRUD) ---

def grupy_lekcyjne(request):
    # Widok listy grup
    grupy = Grupylekcyjne.objects.all().select_related('nauczyciel', 'przedmiot').prefetch_related('klasy')
    return render(request, 'grupy.html', {'grupy': grupy})

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
            form.save() # Tu zadziała nasza customowa metoda save z forms.py
            messages.success(request, 'Zapisano grupę i przypisania klas.')
            return redirect('grupy')
    else:
        form = GrupaForm(instance=instancja)

    return render(request, 'slowniki/formularz_bazowy.html', {'form': form, 'tytul': tytul})

def usun_grupe(request, pk):
    obj = get_object_or_404(Grupylekcyjne, pk=pk)
    if request.method == 'POST':
        obj.delete() # Kaskadowe usuwanie w bazie powinno załatwić tabelę pośrednią, jeśli FK są dobrze ustawione
        messages.success(request, 'Usunięto grupę.')
    return redirect('grupy')