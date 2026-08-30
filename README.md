# Plan Lekcji — generator planów lekcji dla szkoły

Aplikacja webowa usprawniająca pracę sekretariatu i dyrekcji przy układaniu planu lekcji. Projekt powstał z potrzeby zastąpienia ręcznego, czasochłonnego układania planu (w arkuszach kalkulacyjnych lub na kartce) narzędziem, które samo generuje plan spełniający zadane ograniczenia, a jednocześnie pozwala go później ręcznie doszlifować.

Aplikacja działa produkcyjnie pod adresem: **[awans-pinczow-plan-lekcji.pl](https://awans-pinczow-plan-lekcji.pl)**

## Funkcjonalności

- **Automatyczny generator planu** — silnik oparty o [Google OR-Tools (CP-SAT)](https://developers.google.com/optimization/cp/cp_solver), czyli solver programowania z ograniczeniami (constraint programming), który układa plan lekcji tak, by spełnić wymagania przedmiotowe, dostępność nauczycieli i ograniczenia klas jednocześnie.
- **Słowniki danych** — pełne zarządzanie (CRUD) nauczycielami, przedmiotami i klasami.
- **Grupy lekcyjne** — obsługa grup międzyklasowych (np. języki obce, informatyka w grupach), łącznie z automatycznymi sugestiami podziału na grupy.
- **Ograniczenia** — definiowanie niedostępności nauczycieli oraz klas w wybranych dniach/godzinach, uwzględniane przez generator.
- **Ręczna edycja wygenerowanego planu** — podgląd planu z możliwością zamiany pojedynczych lekcji miejscami (bez ponownego odpalania całego generatora) oraz edycji pojedynczej lekcji.
- **Drukowanie planów zbiorczych** — generowanie widoków do wydruku dla całej szkoły naraz.
- **Panel administracyjny generatora** — podgląd statusu generowania w tle (generator działa w osobnym wątku) wraz z możliwością odpytania o postęp.
- **Własny system logowania z 2FA** — logowanie z kodem weryfikacyjnym wysyłanym mailem, zarządzanie zaufanymi urządzeniami oraz odzyskiwanie hasła przez e-mail.
- **Obsługa błędów** — dedykowane strony błędów 400/403/404/500.

## Technologie

- Python / Django
- PostgreSQL
- Google OR-Tools (`ortools.sat.python.cp_model`) — silnik generatora planu
- psycopg2 — bezpośredni dostęp do bazy w module algorytmu
- HTML/CSS (szablony Django)

## Struktura projektu

```
Plan_lekcji/
├── models.py              # Nauczyciel, Przedmioty, Klasa, Grupylekcyjne, PlanLekcji, Ograniczenia...
├── views.py                # logika CRUD, panel generatora, logowanie/2FA, drukowanie planów
├── alg2_ostateczny.py       # właściwy algorytm generowania planu (CP-SAT, Google OR-Tools)
├── alg_diagnoza.py          # diagnostyka / walidacja danych wejściowych do generatora
├── email_utils.py           # wysyłka e-maili (kody weryfikacyjne, reset hasła)
├── forms.py                 # formularze Django
├── urls.py                  # routing
└── templates/                # widoki: panel generatora, słowniki, ograniczenia, plan, e-maile
```

## Uruchomienie lokalne

Wymagania: Python 3, PostgreSQL.

```bash
python -m venv venv
source venv/bin/activate
pip install django psycopg2-binary ortools
python manage.py migrate
python manage.py runserver
```

> **Uwaga dot. konfiguracji:** dane dostępowe do bazy danych oraz konta e-mail używanego do wysyłki kodów 2FA/resetu hasła są obecnie ustawione bezpośrednio w `settings.py`. Przed dalszym rozwojem projektu (i w miarę możliwości jak najszybciej, skoro repozytorium jest na GitHubie) warto przenieść je do zmiennych środowiskowych / pliku `.env` i dodać go do `.gitignore`, a już użyte hasło aplikacji Gmail najlepiej zrotować w ustawieniach konta Google.

## Kontekst

Projekt zrealizowany w ramach chęci usprawnienia pracy sekretariatu szkoły przy układaniu planu lekcji — od ręcznego procesu do automatycznego generatora z możliwością donastrajania wyniku. Wdrożony i używany produkcyjnie.
