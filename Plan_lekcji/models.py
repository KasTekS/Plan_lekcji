from django.db import models
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import secrets
import datetime
# Opcje rozmieszczenia dla dropdownów (Klucz do bazy, Wartość do wyświetlania)
ROZMIESZCZENIE_CHOICES = [
    ('BRAK', 'Standardowo (Brak wymagań)'),
    ('ZEWNETRZNY', 'Zewnętrzny ostatnia/pierwsza lekcja'),
    ('BLOK', 'Blok (lekcje pod rząd)'),
    ('ZEWNETRZNY_BLOK', 'Zewnętrzny Blok'),
]
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
    # DODANO default='BRAK' - naprawia błąd przy dodawaniu grupy
    rozmieszczenie = models.CharField(
        max_length=50,
        choices=ROZMIESZCZENIE_CHOICES,
        default='BRAK'
    )

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

    # NOWE POLE
    sala = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'plan_lekcji'


class WymaganiaPrzedmiotowe(models.Model):
    nauczyciel = models.ForeignKey(Nauczyciel, models.DO_NOTHING, db_column='id_nauczyciel', blank=True, null=True)
    klasa = models.ForeignKey(Klasa, models.DO_NOTHING, db_column='id_klasa', blank=True, null=True)
    przedmiot = models.ForeignKey(Przedmioty, models.DO_NOTHING, db_column='id_przedmiot', blank=True, null=True)
    liczba_godzin = models.IntegerField(blank=True, null=True)
    # DODANO default='BRAK' - naprawia potencjalny błąd przy dodawaniu wymagań
    rozmieszczenie = models.CharField(
        max_length=50,
        choices=ROZMIESZCZENIE_CHOICES,
        default='BRAK'
    )

    class Meta:
        managed = False
        db_table = 'wymagania_przedmiotowe'


# Dodaj w Plan_lekcji/models.py
class StatusGeneratora(models.Model):
    STATUS_CHOICES = [
        ('OCZEKIWANIE', 'Oczekiwanie'),
        ('PRACA', 'Przetwarzanie... (to może potrwać do 10 min)'),
        ('SUKCES', 'Zakończono pomyślnie'),
        ('BLAD', 'Wystąpił błąd'),
    ]

    typ_zadania = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OCZEKIWANIE')
    wiadomosc = models.TextField(blank=True, null=True)
    data_rozpoczecia = models.DateTimeField(auto_now_add=True)
    data_zakonczenia = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.typ_zadania} - {self.status}"

    def save(self, *args, **kwargs):
        """
        Nadpisujemy metodę save, aby automatycznie naprawiać daty
        bez strefy czasowej (tzw. naive datetimes).
        """
        if self.data_zakonczenia and timezone.is_naive(self.data_zakonczenia):
            # Jeśli data nie ma strefy, dodajemy ją automatycznie
            self.data_zakonczenia = timezone.make_aware(self.data_zakonczenia)

        super().save(*args, **kwargs)

from django.utils import timezone  # PAMIĘTAJ O TYM IMPORCIE


def twoja_funkcja_generatora(status_id):
    status_obj = StatusGeneratora.objects.get(id=status_id)

    try:
        # ... tutaj odbywa się szukanie rozwiązania ...

        # POPRAWA BŁĘDU:
        status_obj.status = 'SUKCES'
        status_obj.data_zakonczenia = timezone.now()  # ZAMIAST datetime.now()
        status_obj.save()

    except Exception as e:
        status_obj.status = 'BLAD'
        status_obj.wiadomosc = str(e)
        status_obj.data_zakonczenia = timezone.now()  # TUTAJ TEŻ
        status_obj.save()


class TrustedDevice(models.Model):
    """Model przechowujący zaufane urządzenia użytkownika"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trusted_devices')
    device_name = models.CharField(max_length=200)
    device_token = models.CharField(max_length=64, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()  # Domyślnie 30 dni

    class Meta:
        db_table = 'trusted_devices'
        ordering = ['-last_used']

    def __str__(self):
        return f"{self.user.username} - {self.device_name}"

    def is_valid(self):
        """Sprawdza czy urządzenie jest nadal ważne"""
        return timezone.now() < self.expires_at

    @classmethod
    def generate_token(cls):
        """Generuje unikalny token dla urządzenia"""
        return secrets.token_urlsafe(48)


class VerificationCode(models.Model):
    """Model przechowujący kody weryfikacyjne"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='verification_codes')
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=[
        ('LOGIN', 'Logowanie'),
        ('PASSWORD_RESET', 'Reset hasła')
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'verification_codes'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.code} ({self.purpose})"

    def is_valid(self):
        """Sprawdza czy kod jest nadal ważny"""
        return (not self.is_used and
                timezone.now() < self.expires_at)

    @classmethod
    def generate_code(cls):
        """Generuje 6-cyfrowy kod"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(6)])

    @classmethod
    def create_code(cls, user, purpose='LOGIN', validity_minutes=10):
        """Tworzy nowy kod weryfikacyjny"""
        code = cls.generate_code()
        expires_at = timezone.now() + datetime.timedelta(minutes=validity_minutes)

        return cls.objects.create(
            user=user,
            code=code,
            purpose=purpose,
            expires_at=expires_at
        )


class LoginAttempt(models.Model):
    """Model do śledzenia prób logowania (opcjonalnie - zabezpieczenie)"""
    username = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=False)

    class Meta:
        db_table = 'login_attempts'
        ordering = ['-timestamp']

    @classmethod
    def is_blocked(cls, username, ip_address, max_attempts=5, timeframe_minutes=15):
        """Sprawdza czy IP/user jest zablokowany po zbyt wielu próbach"""
        cutoff = timezone.now() - datetime.timedelta(minutes=timeframe_minutes)
        failed_attempts = cls.objects.filter(
            username=username,
            ip_address=ip_address,
            timestamp__gte=cutoff,
            success=False
        ).count()

        return failed_attempts >= max_attempts