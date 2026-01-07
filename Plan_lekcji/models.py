from django.db import models


class Nauczyciel(models.Model):
    imie_nazwisko = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'nauczyciel'

    def __str__(self):
        return self.imie_nazwisko or f"Nauczyciel {self.id}"


class Przedmioty(models.Model):
    nazwa_przedmiotu = models.CharField(max_length=255, blank=True, null=True)
    skrot = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'przedmioty'

    def __str__(self):
        return self.nazwa_przedmiotu or self.skrot


class Klasa(models.Model):
    id = models.CharField(primary_key=True, max_length=6)
    nazwa = models.CharField(max_length=255, blank=True, null=True)
    rok = models.IntegerField(blank=True, null=True)
    ilosc_osob = models.IntegerField(blank=True, null=True)
    ograniczenia_dni = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'klasa'

    def __str__(self):
        return self.nazwa or self.id


class Grupylekcyjne(models.Model):
    nazwa_grupy = models.CharField(max_length=255)
    przedmiot = models.ForeignKey(Przedmioty, models.DO_NOTHING, db_column='id_przedmiotu')
    nauczyciel = models.ForeignKey(Nauczyciel, models.DO_NOTHING, db_column='id_nauczyciela')
    liczba_godzin_w_grupie = models.IntegerField()
    rozmieszczenie = models.TextField()

    # Relacja ManyToMany do Klas przez tabelę pośrednią
    klasy = models.ManyToManyField(Klasa, through='Klasywgrupach')

    class Meta:
        managed = False
        db_table = 'grupylekcyjne'

    def __str__(self):
        return self.nazwa_grupy


class Klasywgrupach(models.Model):
    # Dodajemy to pole, bo dodaliśmy je w bazie SQL
    id = models.AutoField(primary_key=True)

    grupa = models.ForeignKey(Grupylekcyjne, models.DO_NOTHING, db_column='id_grupy')
    klasa = models.ForeignKey(Klasa, models.DO_NOTHING, db_column='id_klasy')

    class Meta:
        managed = False
        db_table = 'klasywgrupach'
        unique_together = (('grupa', 'klasa'),)



class Ograniczenia(models.Model):
    od = models.IntegerField(db_column='od_', blank=True, null=True)
    do = models.IntegerField(db_column='do_', blank=True, null=True)
    dzien_tygodnia = models.CharField(max_length=20, blank=True, null=True)
    nauczyciel = models.ForeignKey(Nauczyciel, models.DO_NOTHING, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ograniczenia'


class OgraniczeniaKlas(models.Model):
    klasa = models.ForeignKey(Klasa, models.DO_NOTHING, db_column='id_klasy')
    dzien_tygodnia = models.CharField(max_length=20)
    od = models.IntegerField(db_column='od_')
    do = models.IntegerField(db_column='do_')

    class Meta:
        managed = False
        db_table = 'ograniczenia_klas'


class PlanLekcji(models.Model):
    nauczyciel = models.ForeignKey(Nauczyciel, models.DO_NOTHING, db_column='id_nauczyciel', blank=True, null=True)
    klasa = models.ForeignKey(Klasa, models.DO_NOTHING, db_column='id_klasa', blank=True, null=True)
    przedmiot = models.ForeignKey(Przedmioty, models.DO_NOTHING, db_column='id_przedmiot', blank=True, null=True)
    dzien_tygodnia = models.CharField(max_length=20, blank=True, null=True)
    godzina_lekcyjna = models.IntegerField(blank=True, null=True)
    grupa = models.ForeignKey(Grupylekcyjne, models.DO_NOTHING, db_column='id_grupy', blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'plan_lekcji'


class WymaganiaPrzedmiotowe(models.Model):
    nauczyciel = models.ForeignKey(Nauczyciel, models.DO_NOTHING, db_column='id_nauczyciel', blank=True, null=True)
    klasa = models.ForeignKey(Klasa, models.DO_NOTHING, db_column='id_klasa', blank=True, null=True)
    przedmiot = models.ForeignKey(Przedmioty, models.DO_NOTHING, db_column='id_przedmiot', blank=True, null=True)
    liczba_godzin = models.IntegerField(blank=True, null=True)
    rozmieszczenie = models.TextField()

    class Meta:
        managed = False
        db_table = 'wymagania_przedmiotowe'