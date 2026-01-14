# W pliku Plan_lekcji/forms.py

from django import forms
from django.db.models import Sum
from .models import Nauczyciel, Klasa, Przedmioty, Grupylekcyjne, WymaganiaPrzedmiotowe, Klasywgrupach, PlanLekcji, \
    Ograniczenia


# --- Stylizacja pól formularza (BEZ ZMIAN) ---
class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            # Checkboxom dajemy inną klasę, żeby ładnie wyglądały
            if isinstance(self.fields[field].widget, forms.CheckboxInput):
                self.fields[field].widget.attrs.update({'class': 'form-check-input'})
            else:
                self.fields[field].widget.attrs.update({'class': 'form-control'})


# ... (NauczycielForm, PrzedmiotForm, KlasaForm - BEZ ZMIAN) ...
class NauczycielForm(StyledModelForm):
    class Meta:
        model = Nauczyciel
        fields = ['imie_nazwisko']
        labels = {'imie_nazwisko': 'Imię i Nazwisko'}


class PrzedmiotForm(StyledModelForm):
    class Meta:
        model = Przedmioty
        fields = ['nazwa_przedmiotu', 'skrot']
        labels = {'nazwa_przedmiotu': 'Nazwa Przedmiotu', 'skrot': 'Skrót (np. MAT)'}


class KlasaForm(StyledModelForm):
    class Meta:
        model = Klasa
        fields = ['id', 'nazwa', 'rok', 'ilosc_osob']
        labels = {
            'id': 'Symbol (ID) Klasy (np. 1A)',
            'nazwa': 'Pełna nazwa (opcjonalnie)',
            'rok': 'Rocznik (np. 1)',
            'ilosc_osob': 'Liczba uczniów'
        }
        help_texts = {'id': 'To pole jest identyfikatorem (max 6 znaków).'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['id'].disabled = True


# --- NOWE: FUNKCJA POMOCNICZA DO LICZENIA GODZIN ---
def sprawdz_obciazenie_nauczyciela(nauczyciel, dodawane_godziny, ignore_req_id=None, ignore_grp_id=None):
    """
    Zwraca (True, msg) jeśli nauczyciel jest przeciążony, w przeciwnym razie (False, "").
    Zakładamy tydzień = 50 godzin (5 dni * 10h).
    """
    MAX_GODZIN_TYGODNIOWO = 50

    # 1. Policz godziny zablokowane (Ograniczenia)
    # Pobieramy wszystkie ograniczenia tego nauczyciela
    blokady = Ograniczenia.objects.filter(nauczyciel=nauczyciel)
    zablokowane_sloty = 0
    for b in blokady:
        start = b.od if b.od else 1
        end = b.do if b.do else 10
        zablokowane_sloty += (end - start + 1)

    # 2. Policz godziny już przydzielone (Wymagania Indywidualne)
    # exclude pozwala pominąć aktualnie edytowany rekord, żeby nie liczyć go podwójnie
    q_wym = WymaganiaPrzedmiotowe.objects.filter(nauczyciel=nauczyciel)
    if ignore_req_id:
        q_wym = q_wym.exclude(pk=ignore_req_id)
    suma_wym = q_wym.aggregate(Sum('liczba_godzin'))['liczba_godzin__sum'] or 0

    # 3. Policz godziny już przydzielone (Grupy)
    q_grp = Grupylekcyjne.objects.filter(nauczyciel=nauczyciel)
    if ignore_grp_id:
        q_grp = q_grp.exclude(pk=ignore_grp_id)
    suma_grp = q_grp.aggregate(Sum('liczba_godzin_w_grupie'))['liczba_godzin_w_grupie__sum'] or 0

    total_zajete = zablokowane_sloty + suma_wym + suma_grp
    nowy_total = total_zajete + dodawane_godziny

    if nowy_total > MAX_GODZIN_TYGODNIOWO:
        msg = (f"Nauczyciel {nauczyciel} ma zajęte/zablokowane {total_zajete}h. "
               f"Po dodaniu {dodawane_godziny}h przekroczy limit tygodniowy ({MAX_GODZIN_TYGODNIOWO}h).")
        return True, msg

    return False, ""


# --- ZMODYFIKOWANE FORMULARZE Z WALIDACJĄ ---

class WymaganieForm(StyledModelForm):
    # Pole niebędące w bazie, służące do wymuszenia zapisu
    ignoruj_limity = forms.BooleanField(
        required=False,
        label="Ignoruj ostrzeżenia o limitach",
        help_text="Zaznacz, jeśli chcesz zapisać mimo przekroczenia etatu nauczyciela."
    )

    class Meta:
        model = WymaganiaPrzedmiotowe
        fields = ['nauczyciel', 'klasa', 'przedmiot', 'liczba_godzin']
        labels = {
            'nauczyciel': 'Nauczyciel',
            'klasa': 'Klasa',
            'przedmiot': 'Przedmiot',
            'liczba_godzin': 'Liczba godzin w tygodniu'
        }

    def clean(self):
        cleaned_data = super().clean()
        nauczyciel = cleaned_data.get('nauczyciel')
        liczba = cleaned_data.get('liczba_godzin')
        ignoruj = cleaned_data.get('ignoruj_limity')

        if nauczyciel and liczba:
            # Walidacja 1: Obciążenie nauczyciela
            is_overloaded, msg = sprawdz_obciazenie_nauczyciela(
                nauczyciel,
                liczba,
                ignore_req_id=self.instance.pk  # Ważne przy edycji
            )

            if is_overloaded and not ignoruj:
                self.add_error('liczba_godzin', msg)
                self.add_error('ignoruj_limity', "Zaznacz to pole, aby wymusić zapis.")

            # Walidacja 2: Sprawdzenie czy nie przesadzamy z przedmiotem dla klasy (np. > 10h matmy)
            # To prosty przykład, można dostosować limit
            LIMIT_PRZEDMIOTU = 10
            if liczba > LIMIT_PRZEDMIOTU and not ignoruj:
                self.add_error('liczba_godzin',
                               f"Podejrzanie duża liczba godzin ({liczba}) z jednego przedmiotu. Zaznacz 'Ignoruj...', jeśli to celowe.")

        return cleaned_data


class GrupaForm(StyledModelForm):
    klasy_wybor = forms.ModelMultipleChoiceField(
        queryset=Klasa.objects.all().order_by('id'),
        widget=forms.CheckboxSelectMultiple,
        label="Przypisane klasy",
        required=False
    )

    ignoruj_limity = forms.BooleanField(
        required=False,
        label="Ignoruj ostrzeżenia o limitach",
        help_text="Zaznacz, aby wymusić zapis mimo ostrzeżeń."
    )

    class Meta:
        model = Grupylekcyjne
        fields = ['nazwa_grupy', 'przedmiot', 'nauczyciel', 'liczba_godzin_w_grupie']
        labels = {
            'nazwa_grupy': 'Nazwa Grupy (np. WF Dziewczęta)',
            'przedmiot': 'Przedmiot',
            'nauczyciel': 'Opiekun grupy',
            'liczba_godzin_w_grupie': 'Liczba godzin'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['klasy_wybor'].initial = self.instance.klasy.all()

    def clean(self):
        cleaned_data = super().clean()
        nauczyciel = cleaned_data.get('nauczyciel')
        liczba = cleaned_data.get('liczba_godzin_w_grupie')
        ignoruj = cleaned_data.get('ignoruj_limity')

        if nauczyciel and liczba:
            is_overloaded, msg = sprawdz_obciazenie_nauczyciela(
                nauczyciel,
                liczba,
                ignore_grp_id=self.instance.pk
            )
            if is_overloaded and not ignoruj:
                self.add_error('liczba_godzin_w_grupie', msg)
                self.add_error('ignoruj_limity', "Zaznacz to pole, aby wymusić zapis.")

        return cleaned_data

    def save(self, commit=True):
        grupa = super().save(commit=False)
        if commit:
            grupa.save()
            wybrane_klasy = self.cleaned_data['klasy_wybor']
            Klasywgrupach.objects.filter(grupa=grupa).delete()
            for klasa_obj in wybrane_klasy:
                Klasywgrupach.objects.create(grupa=grupa, klasa=klasa_obj)
        return grupa


# ... (EdycjaLekcjiForm - BEZ ZMIAN) ...
class EdycjaLekcjiForm(StyledModelForm):
    class Meta:
        model = PlanLekcji
        fields = ['przedmiot', 'nauczyciel', 'sala']
        labels = {
            'przedmiot': 'Przedmiot',
            'nauczyciel': 'Nauczyciel prowadzący',
            'sala': 'Numer sali/klasy'
        }

    def clean(self):
        cleaned_data = super().clean()
        sala = cleaned_data.get('sala')
        if not sala: return cleaned_data

        lekcja = self.instance
        dzien = lekcja.dzien_tygodnia
        godzina = lekcja.godzina_lekcyjna

        kolizje = PlanLekcji.objects.filter(
            dzien_tygodnia=dzien,
            godzina_lekcyjna=godzina,
            sala=sala
        ).exclude(pk=lekcja.pk)

        if kolizje.exists():
            kolidujaca_lekcja = kolizje.first()
            info = ""
            if kolidujaca_lekcja.klasa:
                info += f"klasą {kolidujaca_lekcja.klasa}"
            elif kolidujaca_lekcja.grupa:
                info += f"grupą {kolidujaca_lekcja.grupa}"
            if kolidujaca_lekcja.nauczyciel: info += f" ({kolidujaca_lekcja.nauczyciel})"

            msg = f"Konflikt! Sala {sala} jest w tym czasie zajęta przez zajęcia z {info}."
            self.add_error('sala', msg)

        return cleaned_data