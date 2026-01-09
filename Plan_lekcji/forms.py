from django import forms
from .models import Nauczyciel, Klasa, Przedmioty, Grupylekcyjne, WymaganiaPrzedmiotowe, Klasywgrupach


# --- Stylizacja pól formularza ---
class StyledModelForm(forms.ModelForm):
    """
    Klasa bazowa, która dodaje klasę CSS 'form-control' do wszystkich pól,
    aby wyglądały ładnie w naszym stylu.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'form-control'})


class NauczycielForm(StyledModelForm):
    class Meta:
        model = Nauczyciel
        fields = ['imie_nazwisko']
        labels = {
            'imie_nazwisko': 'Imię i Nazwisko'
        }


class PrzedmiotForm(StyledModelForm):
    class Meta:
        model = Przedmioty
        fields = ['nazwa_przedmiotu', 'skrot']
        labels = {
            'nazwa_przedmiotu': 'Nazwa Przedmiotu',
            'skrot': 'Skrót (np. MAT)'
        }


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
        help_texts = {
            'id': 'To pole jest identyfikatorem (max 6 znaków).'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Jeśli edytujemy istniejącą klasę, zablokujmy zmianę ID, bo to klucz główny
        if self.instance.pk:
            self.fields['id'].disabled = True


class WymaganieForm(StyledModelForm):
    class Meta:
        model = WymaganiaPrzedmiotowe
        fields = ['nauczyciel', 'klasa', 'przedmiot', 'liczba_godzin']
        labels = {
            'nauczyciel': 'Nauczyciel',
            'klasa': 'Klasa',
            'przedmiot': 'Przedmiot',
            'liczba_godzin': 'Liczba godzin w tygodniu'
        }


class GrupaForm(StyledModelForm):
    # Pole dodatkowe, niewynikające bezpośrednio z modelu Grupy, ale potrzebne do interfejsu
    klasy_wybor = forms.ModelMultipleChoiceField(
        queryset=Klasa.objects.all().order_by('id'),
        widget=forms.CheckboxSelectMultiple,  # To zapewni wyświetlanie checkboxów
        label="Przypisane klasy",
        required=False
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
        # Jeśli edytujemy istniejącą grupę, musimy zaznaczyć checkboxy
        if self.instance.pk:
            # Pobieramy klasy aktualnie przypisane do tej grupy przez tabelę pośrednią
            self.fields['klasy_wybor'].initial = self.instance.klasy.all()

    def save(self, commit=True):
        # Nadpisujemy save, aby obsłużyć relację ManyToMany ręcznie
        grupa = super().save(commit=False)

        if commit:
            grupa.save()

            # 1. Pobieramy wybrane klasy z formularza
            wybrane_klasy = self.cleaned_data['klasy_wybor']

            # 2. Czyścimy stare powiązania w tabeli pośredniej
            Klasywgrupach.objects.filter(grupa=grupa).delete()

            # 3. Tworzymy nowe powiązania
            for klasa_obj in wybrane_klasy:
                Klasywgrupach.objects.create(grupa=grupa, klasa=klasa_obj)

        return grupa