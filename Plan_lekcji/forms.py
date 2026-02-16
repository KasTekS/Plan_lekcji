from django import forms
from django.db.models import Sum
from .models import Nauczyciel, Klasa, Przedmioty, Grupylekcyjne, WymaganiaPrzedmiotowe, Klasywgrupach, PlanLekcji, \
    Ograniczenia


# --- Stylizacja pól formularza ---
class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            if isinstance(self.fields[field].widget, forms.CheckboxInput):
                self.fields[field].widget.attrs.update({'class': 'form-check-input'})
            else:
                self.fields[field].widget.attrs.update({'class': 'form-control'})


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


# --- FUNKCJA POMOCNICZA DO LICZENIA GODZIN ---
def sprawdz_obciazenie_nauczyciela(nauczyciel, dodawane_godziny, ignore_req_id=None, ignore_grp_id=None):
    MAX_GODZIN_TYGODNIOWO = 50

    blokady = Ograniczenia.objects.filter(nauczyciel=nauczyciel)
    zablokowane_sloty = 0
    for b in blokady:
        start = b.od if b.od else 1
        end = b.do if b.do else 10
        zablokowane_sloty += (end - start + 1)

    q_wym = WymaganiaPrzedmiotowe.objects.filter(nauczyciel=nauczyciel)
    if ignore_req_id:
        q_wym = q_wym.exclude(pk=ignore_req_id)
    suma_wym = q_wym.aggregate(Sum('liczba_godzin'))['liczba_godzin__sum'] or 0

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


# --- ZMODYFIKOWANE FORMULARZE Z POPRAWIONYMI POLAMI ---

class WymaganieForm(StyledModelForm):
    ignoruj_limity = forms.BooleanField(
        required=False,
        label="Ignoruj ostrzeżenia o limitach",
        help_text="Zaznacz, jeśli chcesz zapisać mimo przekroczenia etatu nauczyciela."
    )

    class Meta:
        model = WymaganiaPrzedmiotowe
        # POPRAWKA: Używamy nazw pól z modelu ('nauczyciel', 'przedmiot'), a nie kolumn SQL ('id_nauczyciel')
        fields = ['nauczyciel', 'klasa', 'przedmiot', 'liczba_godzin', 'rozmieszczenie']
        labels = {
            'nauczyciel': 'Nauczyciel',
            'klasa': 'Klasa',
            'przedmiot': 'Przedmiot',
            'liczba_godzin': 'Liczba godzin',
            'rozmieszczenie': 'Opcje rozmieszczenia'
        }

    def clean(self):
        cleaned_data = super().clean()
        nauczyciel = cleaned_data.get('nauczyciel')
        liczba = cleaned_data.get('liczba_godzin')
        ignoruj = cleaned_data.get('ignoruj_limity')

        if nauczyciel and liczba:
            is_overloaded, msg = sprawdz_obciazenie_nauczyciela(
                nauczyciel,
                liczba,
                ignore_req_id=self.instance.pk
            )
            if is_overloaded and not ignoruj:
                self.add_error('liczba_godzin', msg)
                self.add_error('ignoruj_limity', "Zaznacz to pole, aby wymusić zapis.")

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

    autokorekta_wymagan = forms.BooleanField(
        required=False,
        initial=True,
        label="Aktualizuj wymagania przedmiotowe",
        help_text="Zaznacz, aby system automatycznie odjął godziny z wymagań tych klas."
    )

    ignoruj_limity = forms.BooleanField(
        required=False,
        label="Ignoruj ostrzeżenia o limitach",
        help_text="Zaznacz, aby wymusić zapis mimo ostrzeżeń."
    )

    class Meta:
        model = Grupylekcyjne
        # POPRAWKA: Używamy nazw pól z modelu ('przedmiot', 'nauczyciel'), a nie kolumn SQL
        fields = ['nazwa_grupy', 'przedmiot', 'nauczyciel', 'liczba_godzin_w_grupie', 'rozmieszczenie']
        labels = {
            'nazwa_grupy': 'Nazwa Grupy',
            'przedmiot': 'Przedmiot',
            'nauczyciel': 'Nauczyciel (Opiekun)',
            'liczba_godzin_w_grupie': 'Liczba godzin',
            'rozmieszczenie': 'Opcje rozmieszczenia'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.old_klasy = []
        self.old_godziny = 0
        if self.instance.pk:
            self.fields['klasy_wybor'].initial = self.instance.klasy.all()
            self.old_klasy = list(self.instance.klasy.all())
            self.old_godziny = self.instance.liczba_godzin_w_grupie or 0

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
            nowe_klasy = self.cleaned_data['klasy_wybor']
            nowe_godziny = self.cleaned_data['liczba_godzin_w_grupie']
            robic_korekte = self.cleaned_data.get('autokorekta_wymagan')
            przedmiot = grupa.przedmiot

            Klasywgrupach.objects.filter(grupa=grupa).delete()
            for klasa_obj in nowe_klasy:
                Klasywgrupach.objects.create(grupa=grupa, klasa=klasa_obj)

            if robic_korekte and przedmiot:
                # Przywracanie starego stanu
                if self.instance.pk and self.old_klasy:
                    for k in self.old_klasy:
                        wymagania = WymaganiaPrzedmiotowe.objects.filter(klasa=k, przedmiot=przedmiot)
                        for wym in wymagania:
                            wym.liczba_godzin = (wym.liczba_godzin or 0) + self.old_godziny
                            wym.save()

                # Odejmowanie godzin
                for k in nowe_klasy:
                    wymagania = WymaganiaPrzedmiotowe.objects.filter(klasa=k, przedmiot=przedmiot)
                    for wym in wymagania:
                        nowy_stan = (wym.liczba_godzin or 0) - nowe_godziny
                        wym.liczba_godzin = max(0, nowy_stan)
                        wym.save()
        return grupa


class EdycjaLekcjiForm(StyledModelForm):
    # Dodatkowe pole, które nie jest zapisywane w bazie, ale steruje walidacją
    ignoruj_konflikt_sali = forms.BooleanField(
        required=False,
        label="Ignoruj zajętość sali (wymuś zapis)",
        help_text="Zaznacz, jeśli chcesz dodać lekcję mimo, że sala jest zajęta."
    )

    class Meta:
        model = PlanLekcji
        # Pola dostępne do edycji - dostosuj je, jeśli w oryginale masz ich więcej/mniej
        fields = ['dzien_tygodnia', 'godzina_lekcyjna', 'przedmiot', 'nauczyciel', 'sala', 'klasa', 'grupa']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Jeśli edytujemy istniejącą lekcję (nie nową)
        if self.instance and self.instance.pk:
            dzien = self.instance.dzien_tygodnia
            godzina = self.instance.godzina_lekcyjna

            if dzien and godzina:
                # Znajdujemy wszystkie zajęte sale w tym czasie
                zajete_sale = PlanLekcji.objects.filter(
                    dzien_tygodnia=dzien,
                    godzina_lekcyjna=godzina,
                    sala__isnull=False
                ).exclude(
                    sala=''
                ).exclude(
                    pk=self.instance.pk  # Wykluczamy aktualnie edytowaną lekcję
                ).select_related('klasa', 'nauczyciel', 'grupa').values_list(
                    'sala', 'klasa__nazwa', 'nauczyciel__imie_nazwisko', 'grupa__nazwa_grupy'
                )

                if zajete_sale:
                    # Budujemy czytelny komunikat
                    lista_sal = []
                    for sala, klasa_nazwa, nauczyciel_imie, grupa_nazwa in zajete_sale:
                        if klasa_nazwa:
                            info = f"{sala} (klasa: {klasa_nazwa})"
                        elif grupa_nazwa:
                            info = f"{sala} (grupa: {grupa_nazwa})"
                        elif nauczyciel_imie:
                            info = f"{sala} ({nauczyciel_imie})"
                        else:
                            info = sala
                        lista_sal.append(info)

                    komunikat = "⚠️ Zajęte sale w tym czasie: " + ", ".join(lista_sal)

                    # Dodajemy podpowiedź do pola 'sala'
                    self.fields['sala'].help_text = komunikat
                    self.fields['sala'].widget.attrs['placeholder'] = 'Wpisz numer sali...'
                else:
                    self.fields['sala'].help_text = "✅ Brak zajętych sal w tym terminie - możesz wybrać dowolną."

    def clean(self):
        cleaned_data = super().clean()

        # Pobieramy dane z formularza
        sala = cleaned_data.get('sala')
        dzien = cleaned_data.get('dzien_tygodnia')
        godzina = cleaned_data.get('godzina_lekcyjna')
        ignoruj = cleaned_data.get('ignoruj_konflikt_sali')

        # Walidacja zajętości sali
        if sala and dzien and godzina:
            # Szukamy czy JEST już jakaś lekcja w tej sali, w ten dzień, o tej godzinie
            # .exclude(pk=self.instance.pk) jest kluczowe - żeby nie wykrywał konfliktu z samym sobą przy edycji
            konflikt = PlanLekcji.objects.filter(
                sala=sala,
                dzien_tygodnia=dzien,
                godzina_lekcyjna=godzina
            ).exclude(pk=self.instance.pk).first()

            # Jeśli znaleziono konflikt I nie zaznaczono ignorowania
            if konflikt and not ignoruj:
                # Budujemy czytelną informację kto zajmuje salę
                zajmujacy = konflikt.klasa.nazwa if konflikt.klasa else (
                    konflikt.nauczyciel.imie_nazwisko if konflikt.nauczyciel else "Inna lekcja")

                # Znajdujemy też inne zajęte sale w tym czasie (dla podpowiedzi)
                inne_zajete = PlanLekcji.objects.filter(
                    dzien_tygodnia=dzien,
                    godzina_lekcyjna=godzina,
                    sala__isnull=False
                ).exclude(
                    sala=''
                ).exclude(
                    pk=self.instance.pk
                ).exclude(
                    sala=sala  # Nie pokazujemy tej którą właśnie wybraliśmy (jest w głównym błędzie)
                ).select_related('klasa', 'nauczyciel', 'grupa').values_list(
                    'sala', 'klasa__nazwa', 'grupa__nazwa_grupy'
                )

                dodatkowe_info = ""
                if inne_zajete:
                    lista_innych = []
                    for s, k, g in inne_zajete:
                        if k:
                            lista_innych.append(f"{s} ({k})")
                        elif g:
                            lista_innych.append(f"{s} ({g})")
                        else:
                            lista_innych.append(s)

                    if lista_innych:
                        dodatkowe_info = f"\n\nInne zajęte sale w tym czasie: {', '.join(lista_innych)}"

                msg = f"Konflikt! Sala {sala} jest w tym czasie zajęta przez: {zajmujacy}. Zaznacz 'Ignoruj...', aby zapisać mimo to.{dodatkowe_info}"
                self.add_error('sala', msg)

        return cleaned_data