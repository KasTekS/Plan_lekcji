from django.shortcuts import render
from django.db.models import Q  # <--- WAŻNY IMPORT DO ŁĄCZENIA WARUNKÓW
from collections import defaultdict
from .models import (
    WymaganiaPrzedmiotowe, Grupylekcyjne, PlanLekcji,
    Klasa, Nauczyciel, Klasywgrupach
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