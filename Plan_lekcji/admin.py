from django.contrib import admin
from .models import (
    Nauczyciel, Przedmioty, Klasa, Grupylekcyjne,
    WymaganiaPrzedmiotowe, Ograniczenia, OgraniczeniaKlas, PlanLekcji, Klasywgrupach
)

# Rejestracja modeli, aby były widoczne w panelu
# Używamy dekoratora @admin.register, aby od razu zdefiniować, jakie kolumny mają być widoczne

@admin.register(Nauczyciel)
class NauczycielAdmin(admin.ModelAdmin):
    list_display = ('id', 'imie_nazwisko')
    search_fields = ('imie_nazwisko',)

@admin.register(Przedmioty)
class PrzedmiotyAdmin(admin.ModelAdmin):
    list_display = ('nazwa_przedmiotu', 'skrot')
    search_fields = ('nazwa_przedmiotu',)

@admin.register(Klasa)
class KlasaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nazwa', 'rok', 'ilosc_osob')
    search_fields = ('nazwa',)

class KlasyWGrupachInline(admin.TabularInline):
    model = Klasywgrupach
    extra = 1  # Liczba pustych wierszy do dodania nowych klas
    can_delete = True
    verbose_name = "Przypisana klasa"
    verbose_name_plural = "Przypisane klasy"

# Potem dodajemy to do admina Grup
@admin.register(Grupylekcyjne)
class GrupylekcyjneAdmin(admin.ModelAdmin):
    list_display = ('nazwa_grupy', 'przedmiot', 'nauczyciel', 'liczba_godzin_w_grupie')
    list_filter = ('przedmiot', 'nauczyciel')
    search_fields = ('nazwa_grupy',)
    # Tutaj dodajemy nasz Inline
    inlines = [KlasyWGrupachInline]

@admin.register(WymaganiaPrzedmiotowe)
class WymaganiaPrzedmiotoweAdmin(admin.ModelAdmin):
    list_display = ('klasa', 'nauczyciel', 'przedmiot', 'liczba_godzin')
    list_filter = ('klasa', 'nauczyciel', 'przedmiot')

@admin.register(Ograniczenia)
class OgraniczeniaAdmin(admin.ModelAdmin):
    list_display = ('nauczyciel', 'dzien_tygodnia', 'od', 'do')
    list_filter = ('nauczyciel', 'dzien_tygodnia')

@admin.register(OgraniczeniaKlas)
class OgraniczeniaKlasAdmin(admin.ModelAdmin):
    list_display = ('klasa', 'dzien_tygodnia', 'od', 'do')
    list_filter = ('klasa', 'dzien_tygodnia')

@admin.register(PlanLekcji)
class PlanLekcjiAdmin(admin.ModelAdmin):
    list_display = ('dzien_tygodnia', 'godzina_lekcyjna', 'klasa', 'przedmiot', 'nauczyciel')
    list_filter = ('dzien_tygodnia', 'klasa', 'nauczyciel')