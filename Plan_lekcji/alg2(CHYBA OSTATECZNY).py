# -*- coding: utf-8 -*-
import collections
import psycopg2
from ortools.sat.python import cp_model


# --- Krok 1: Wczytywanie danych z bazy ---
def pobierz_dane_z_bazy(db_params):
    """
    Funkcja łączy się z bazą danych, pobiera dane wejściowe oraz (opcjonalnie)
    istniejący plan lekcji, aby móc go optymalizować.
    """
    conn = None
    try:
        print("Łączenie z bazą danych PostgreSQL...")
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()
        print("Połączenie udane.")

        # 1. Dane podstawowe
        cur.execute("SELECT ID, Imie_Nazwisko FROM Nauczyciel ORDER BY ID")
        nauczyciele = dict(cur.fetchall())
        cur.execute("SELECT ID, Skrot FROM Przedmioty ORDER BY ID")
        przedmioty = dict(cur.fetchall())
        cur.execute("SELECT ID, Rok, Ilosc_osob FROM Klasa ORDER BY ID")
        klasy_raw = cur.fetchall()
        klasy = {k_id: {'rok': rok, 'ilosc_osob': ilosc} for k_id, rok, ilosc in klasy_raw}

        # 2. Wymagania i Grupy
        cur.execute(
            "SELECT ID, ID_nauczyciel, ID_klasa, ID_przedmiot, Liczba_godzin, rozmieszczenie FROM Wymagania_przedmiotowe")
        wymagania_indywidualne = cur.fetchall()

        cur.execute(
            "SELECT id, id_nauczyciela, id_przedmiotu, liczba_godzin_w_grupie, rozmieszczenie FROM grupylekcyjne")
        grupy_raw = cur.fetchall()

        cur.execute("SELECT id_grupy, id_klasy FROM klasywgrupach")
        klasy_w_grupach_map = collections.defaultdict(list)
        for id_grupy, id_klasy in cur.fetchall():
            klasy_w_grupach_map[id_grupy].append(id_klasy)

        grupy_z_bazy = []
        for id_g, id_n, id_p, l_godzin, rozmieszczenie in grupy_raw:
            if id_g in klasy_w_grupach_map:
                grupy_z_bazy.append({
                    'id_grupy': id_g, 'nauczyciel': id_n, 'przedmiot': id_p,
                    'liczba_godzin': l_godzin, 'klasy': frozenset(klasy_w_grupach_map[id_g]),
                    'rozmieszczenie': rozmieszczenie
                })

        # 3. Ograniczenia
        cur.execute("SELECT Od_, Do_, Dzien_tygodnia, Nauczyciel_ID FROM Ograniczenia")
        ograniczenia_nauczycieli = cur.fetchall()
        cur.execute("SELECT id_klasy, dzien_tygodnia, od_, do_ FROM ograniczenia_klas")
        ograniczenia_klas = cur.fetchall()

        # 4. ISTNIEJĄCY PLAN LEKCJI (Do stabilizacji)
        print("Pobieranie istniejącego planu lekcji...")
        cur.execute("""
                    SELECT id_nauczyciel, id_klasa, id_przedmiot, id_grupy, dzien_tygodnia, godzina_lekcyjna
                    FROM plan_lekcji
                    """)
        stary_plan_raw = cur.fetchall()

        stary_plan_ind = collections.defaultdict(list)
        stary_plan_grup = collections.defaultdict(list)

        mapa_dni_db = {'PON': 'Poniedziałek', 'WT': 'Wtorek', 'SR': 'Środa', 'CZW': 'Czwartek', 'PT': 'Piątek'}

        for id_n, id_k, id_p, id_g, dzien_db, godz in stary_plan_raw:
            dzien_pelny = mapa_dni_db.get(dzien_db.strip().upper())
            if not dzien_pelny: continue

            if id_g is not None:
                stary_plan_grup[id_g].append((dzien_pelny, godz))
            else:
                klucz = (id_n, id_k, id_p)
                stary_plan_ind[klucz].append((dzien_pelny, godz))

        for k in stary_plan_ind:
            stary_plan_ind[k].sort()
        for k in stary_plan_grup:
            stary_plan_grup[k].sort()

        print("Pomyślnie pobrano wszystkie dane z bazy.")
        cur.close()
        return nauczyciele, przedmioty, klasy, wymagania_indywidualne, grupy_z_bazy, ograniczenia_nauczycieli, ograniczenia_klas, (
            stary_plan_ind, stary_plan_grup)

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Błąd podczas połączenia lub pobierania danych z PostgreSQL: {error}")
        return None, None, None, None, None, None, None, None
    finally:
        if conn is not None:
            conn.close()


# --- Krok 2: Główna logika generatora ---
def generuj_plan(nauczyciele, przedmioty, klasy_info, wymagania_indywidualne, grupy_z_bazy, ograniczenia_nauczycieli,
                 ograniczenia_klas, id_wf, db_params, stary_plan_dane, zachowaj_obecny_plan=False):
    stary_plan_ind, stary_plan_grup = stary_plan_dane

    # --- Przygotowanie danych ---
    id_nauczycieli = list(nauczyciele.keys())
    id_klas = list(klasy_info.keys())
    dni_tygodnia = ['Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek']
    mapowanie_dni_skrot_na_pl = {'PON': 'Poniedziałek', 'WT': 'Wtorek', 'SR': 'Środa', 'CZW': 'Czwartek',
                                 'PT': 'Piątek'}
    mapowanie_dni_pl_na_skrot = {v: k for k, v in mapowanie_dni_skrot_na_pl.items()}
    godziny_lekcyjne = {d: list(range(1, 11)) for d in dni_tygodnia}
    wszystkie_sloty = [(dzien, godzina) for dzien in dni_tygodnia for godzina in godziny_lekcyjne[dzien]]
    dni_do_indeksu = {dzien: i for i, dzien in enumerate(dni_tygodnia)}

    MAX_GODZINA = 10
    model = cp_model.CpModel()
    punkty_karne = []

    # --- Przygotowanie dynamicznych granic dla logiki 'ZEWNETRZNE' ---
    dostepne_sloty_klasy = {}
    for id_k in id_klas:
        dostepne_sloty_klasy[id_k] = {}
        for dzien_pl in dni_tygodnia:
            dzien_skrot = mapowanie_dni_pl_na_skrot[dzien_pl]
            potencjalne_godziny = set(godziny_lekcyjne[dzien_pl])
            for ogr_id_k, ogr_dzien_s, od, do in ograniczenia_klas:
                if ogr_id_k == id_k and ogr_dzien_s == dzien_skrot:
                    for godzina in range(od, do + 1):
                        potencjalne_godziny.discard(godzina)
            dostepne_sloty_klasy[id_k][dzien_pl] = sorted(list(potencjalne_godziny))

    dostepne_sloty_grupowe = {}
    for grupa in grupy_z_bazy:
        id_g = grupa['id_grupy']
        dostepne_sloty_grupowe[id_g] = {}
        for dzien_pl in dni_tygodnia:
            sloty_wspolne = set(godziny_lekcyjne[dzien_pl])
            for id_k in grupa['klasy']:
                sloty_klasy_k = set(dostepne_sloty_klasy[id_k][dzien_pl])
                sloty_wspolne.intersection_update(sloty_klasy_k)
            dostepne_sloty_grupowe[id_g][dzien_pl] = sorted(list(sloty_wspolne))

    granice_slotow_wymagan = {}
    for id_wym, _, id_k, _, _, _ in wymagania_indywidualne:
        lookup = dostepne_sloty_klasy[id_k]
        min_h_per_day = [min(lookup[d]) if lookup[d] else -1 for d in dni_tygodnia]
        max_h_per_day = [max(lookup[d]) if lookup[d] else -1 for d in dni_tygodnia]
        granice_slotow_wymagan[id_wym] = {'min': min_h_per_day, 'max': max_h_per_day}

    granice_slotow_grup = {}
    for grupa in grupy_z_bazy:
        id_g = grupa['id_grupy']
        lookup = dostepne_sloty_grupowe[id_g]
        min_h_per_day = [min(lookup[d]) if lookup[d] else -1 for d in dni_tygodnia]
        max_h_per_day = [max(lookup[d]) if lookup[d] else -1 for d in dni_tygodnia]
        granice_slotow_grup[id_g] = {'min': min_h_per_day, 'max': max_h_per_day}

    # --- Tworzenie zmiennych decyzyjnych ---
    lekcje_do_specjalnej_obslugi = collections.defaultdict(
        lambda: {'dni': [], 'godziny': [], 'rozm': 'BRAK', 'N': 0, 'klasy': set()})

    przydzial_indywidualny = {}
    wszystkie_lekcje_indywidualne = []

    for id_wym, id_n, id_k, id_p, l_godzin, rozm in wymagania_indywidualne:
        klucz_wymagania = ('ind', id_wym)
        lekcje_do_specjalnej_obslugi[klucz_wymagania].update({'klasy': {id_k}, 'rozm': rozm, 'N': l_godzin})

        historia_lekcji = []
        if zachowaj_obecny_plan:
            historia_lekcji = stary_plan_ind.get((id_n, id_k, id_p), [])

        for i in range(l_godzin):
            lekcja_id = (id_wym, i)
            lekcja_info = {'id': lekcja_id, 'klasa': id_k, 'przedmiot': id_p, 'nauczyciel': id_n}
            wszystkie_lekcje_indywidualne.append(lekcja_info)
            day_var = model.NewIntVar(0, len(dni_tygodnia) - 1, f'ind_day_{id_wym}_{i}')
            hour_var = model.NewIntVar(1, MAX_GODZINA, f'ind_hour_{id_wym}_{i}')
            all_bool_vars = []

            for dzien, godzina in wszystkie_sloty:
                var = model.NewBoolVar(f'ind_{id_wym}_{i}_{dzien}_{godzina}')
                przydzial_indywidualny[(lekcja_id, dzien, godzina)] = var
                all_bool_vars.append(var)
                model.Add(day_var == dni_do_indeksu[dzien]).OnlyEnforceIf(var)
                model.Add(hour_var == godzina).OnlyEnforceIf(var)
            model.AddExactlyOne(all_bool_vars)

            # STABILIZACJA
            if zachowaj_obecny_plan and i < len(historia_lekcji):
                stary_dzien, stara_godzina = historia_lekcji[i]
                if stary_dzien in dni_do_indeksu:
                    stary_dzien_idx = dni_do_indeksu[stary_dzien]
                    model.AddHint(day_var, stary_dzien_idx)
                    model.AddHint(hour_var, stara_godzina)

                    zmiana_dnia = model.NewBoolVar(f'zmiana_dnia_ind_{id_wym}_{i}')
                    model.Add(day_var != stary_dzien_idx).OnlyEnforceIf(zmiana_dnia)
                    model.Add(day_var == stary_dzien_idx).OnlyEnforceIf(zmiana_dnia.Not())
                    punkty_karne.append(zmiana_dnia * 500)

                    zmiana_godziny = model.NewBoolVar(f'zmiana_godz_ind_{id_wym}_{i}')
                    model.Add(hour_var != stara_godzina).OnlyEnforceIf(zmiana_godziny)
                    model.Add(hour_var == stara_godzina).OnlyEnforceIf(zmiana_godziny.Not())
                    punkty_karne.append(zmiana_godziny * 50)

            lekcje_do_specjalnej_obslugi[klucz_wymagania]['dni'].append(day_var)
            lekcje_do_specjalnej_obslugi[klucz_wymagania]['godziny'].append(hour_var)

    przydzial_grupowy = {}
    wszystkie_lekcje_grupowe = []
    for grupa in grupy_z_bazy:
        id_g = grupa['id_grupy']
        l_godzin = grupa['liczba_godzin']
        rozm = grupa['rozmieszczenie']
        klucz_grupy = ('grup', id_g)
        lekcje_do_specjalnej_obslugi[klucz_grupy].update({'klasy': grupa['klasy'], 'rozm': rozm, 'N': l_godzin})

        historia_lekcji = []
        if zachowaj_obecny_plan:
            historia_lekcji = stary_plan_grup.get(id_g, [])

        for i in range(l_godzin):
            lekcja_id = (id_g, i)
            lekcja_info = {'id': lekcja_id, **grupa}
            wszystkie_lekcje_grupowe.append(lekcja_info)
            day_var = model.NewIntVar(0, len(dni_tygodnia) - 1, f'grup_day_{id_g}_{i}')
            hour_var = model.NewIntVar(1, MAX_GODZINA, f'grup_hour_{id_g}_{i}')
            all_bool_vars = []

            for dzien, godzina in wszystkie_sloty:
                var = model.NewBoolVar(f'grup_{id_g}_{i}_{dzien}_{godzina}')
                przydzial_grupowy[(lekcja_id, dzien, godzina)] = var
                all_bool_vars.append(var)
                model.Add(day_var == dni_do_indeksu[dzien]).OnlyEnforceIf(var)
                model.Add(hour_var == godzina).OnlyEnforceIf(var)
            model.AddExactlyOne(all_bool_vars)

            # STABILIZACJA
            if zachowaj_obecny_plan and i < len(historia_lekcji):
                stary_dzien, stara_godzina = historia_lekcji[i]
                if stary_dzien in dni_do_indeksu:
                    stary_dzien_idx = dni_do_indeksu[stary_dzien]
                    model.AddHint(day_var, stary_dzien_idx)
                    model.AddHint(hour_var, stara_godzina)

                    zmiana_dnia = model.NewBoolVar(f'zmiana_dnia_grup_{id_g}_{i}')
                    model.Add(day_var != stary_dzien_idx).OnlyEnforceIf(zmiana_dnia)
                    model.Add(day_var == stary_dzien_idx).OnlyEnforceIf(zmiana_dnia.Not())
                    punkty_karne.append(zmiana_dnia * 500)

                    zmiana_godziny = model.NewBoolVar(f'zmiana_godz_grup_{id_g}_{i}')
                    model.Add(hour_var != stara_godzina).OnlyEnforceIf(zmiana_godziny)
                    model.Add(hour_var == stara_godzina).OnlyEnforceIf(zmiana_godziny.Not())
                    punkty_karne.append(zmiana_godziny * 50)

            lekcje_do_specjalnej_obslugi[klucz_grupy]['dni'].append(day_var)
            lekcje_do_specjalnej_obslugi[klucz_grupy]['godziny'].append(hour_var)

    # --- OGRANICZENIA TWARDE ---
    for id_k in id_klas:
        for dzien, godzina in wszystkie_sloty:
            lekcje_klasy_w_slocie = []
            for l in wszystkie_lekcje_indywidualne:
                if l['klasa'] == id_k and (l['id'], dzien, godzina) in przydzial_indywidualny:
                    lekcje_klasy_w_slocie.append(przydzial_indywidualny[(l['id'], dzien, godzina)])
            for l in wszystkie_lekcje_grupowe:
                if id_k in l['klasy'] and (l['id'], dzien, godzina) in przydzial_grupowy:
                    lekcje_klasy_w_slocie.append(przydzial_grupowy[(l['id'], dzien, godzina)])
            model.AddAtMostOne(lekcje_klasy_w_slocie)

    for id_n in id_nauczycieli:
        for dzien, godzina in wszystkie_sloty:
            lekcje_nauczyciela_w_slocie = []
            for l in wszystkie_lekcje_indywidualne:
                if l['nauczyciel'] == id_n and (l['id'], dzien, godzina) in przydzial_indywidualny:
                    lekcje_nauczyciela_w_slocie.append(przydzial_indywidualny[(l['id'], dzien, godzina)])
            for l in wszystkie_lekcje_grupowe:
                if l['nauczyciel'] == id_n and (l['id'], dzien, godzina) in przydzial_grupowy:
                    lekcje_nauczyciela_w_slocie.append(przydzial_grupowy[(l['id'], dzien, godzina)])
            model.AddAtMostOne(lekcje_nauczyciela_w_slocie)

    for od, do, dzien_skrot, id_n in ograniczenia_nauczycieli:
        dzien = mapowanie_dni_skrot_na_pl.get(dzien_skrot.strip().upper())
        if dzien:
            for godzina in range(od, do + 1):
                if (dzien, godzina) in wszystkie_sloty:
                    for l in wszystkie_lekcje_indywidualne:
                        if l['nauczyciel'] == id_n: model.Add(przydzial_indywidualny[(l['id'], dzien, godzina)] == 0)
                    for l in wszystkie_lekcje_grupowe:
                        if l['nauczyciel'] == id_n: model.Add(przydzial_grupowy[(l['id'], dzien, godzina)] == 0)

    for id_k, dzien_skrot, od, do in ograniczenia_klas:
        dzien_pl = mapowanie_dni_skrot_na_pl.get(dzien_skrot.strip().upper())
        if dzien_pl:
            for godzina in range(od, do + 1):
                if (dzien_pl, godzina) in wszystkie_sloty:
                    for lekcja in wszystkie_lekcje_indywidualne:
                        if lekcja['klasa'] == id_k: model.Add(
                            przydzial_indywidualny[(lekcja['id'], dzien_pl, godzina)] == 0)
                    for lekcja in wszystkie_lekcje_grupowe:
                        if id_k in lekcja['klasy']: model.Add(przydzial_grupowy[(lekcja['id'], dzien_pl, godzina)] == 0)

    if id_wf is not None:
        for dzien in dni_tygodnia:
            for godzina in godziny_lekcyjne[dzien]:
                nauczyciele_uczacy_inny_przedmiot = []
                for id_n in id_nauczycieli:
                    uczy_innego_przedmiotu = model.NewBoolVar(f'nauczyciel_{id_n}_uczy_innego_{dzien}_{godzina}')
                    lekcje_nauczyciela_nie_wf = []
                    for lekcja in wszystkie_lekcje_indywidualne:
                        if lekcja['nauczyciel'] == id_n and lekcja['przedmiot'] != id_wf:
                            lekcje_nauczyciela_nie_wf.append(przydzial_indywidualny[(lekcja['id'], dzien, godzina)])
                    for lekcja in wszystkie_lekcje_grupowe:
                        if lekcja['nauczyciel'] == id_n and lekcja['przedmiot'] != id_wf:
                            lekcje_nauczyciela_nie_wf.append(przydzial_grupowy[(lekcja['id'], dzien, godzina)])
                    if not lekcje_nauczyciela_nie_wf:
                        model.Add(uczy_innego_przedmiotu == 0)
                    else:
                        model.Add(sum(lekcje_nauczyciela_nie_wf) > 0).OnlyEnforceIf(uczy_innego_przedmiotu)
                        model.Add(sum(lekcje_nauczyciela_nie_wf) == 0).OnlyEnforceIf(uczy_innego_przedmiotu.Not())
                    nauczyciele_uczacy_inny_przedmiot.append(uczy_innego_przedmiotu)
                model.Add(sum(nauczyciele_uczacy_inny_przedmiot) <= 8)

    # 7. Bloki i rozmieszczenie
    for klucz, grupa in lekcje_do_specjalnej_obslugi.items():
        typ, id_zasobu = klucz
        dni_vars = grupa['dni']
        godz_vars = grupa['godziny']
        rozm = grupa['rozm']
        N = grupa['N']

        if rozm == 'BRAK' or N == 0:
            continue

        if typ == 'ind':
            granice = granice_slotow_wymagan[id_zasobu]
        else:
            granice = granice_slotow_grup[id_zasobu]

        min_h_list = granice['min']
        max_h_list = granice['max']

        if rozm == 'BLOK':
            if N > 1:
                for i in range(N - 1):
                    model.Add(dni_vars[i] == dni_vars[i + 1])
                model.AddAllDifferent(godz_vars)
                max_h = model.NewIntVar(1, MAX_GODZINA, f'blok_max_h_{id_zasobu}')
                min_h = model.NewIntVar(1, MAX_GODZINA, f'blok_min_h_{id_zasobu}')
                model.AddMaxEquality(max_h, godz_vars)
                model.AddMinEquality(min_h, godz_vars)
                model.Add(max_h - min_h == N - 1)

        elif rozm == 'ZEWNETRZNE':
            for i, (d_var, h_var) in enumerate(zip(dni_vars, godz_vars)):
                min_h_dla_dnia = model.NewIntVar(-1, MAX_GODZINA, f'zew_min_h_{id_zasobu}_{i}')
                max_h_dla_dnia = model.NewIntVar(-1, MAX_GODZINA, f'zew_max_h_{id_zasobu}_{i}')
                model.AddElement(d_var, min_h_list, min_h_dla_dnia)
                model.AddElement(d_var, max_h_list, max_h_dla_dnia)
                model.Add(min_h_dla_dnia != -1)

                is_first = model.NewBoolVar(f'zew_is_first_{id_zasobu}_{i}')
                is_last = model.NewBoolVar(f'zew_is_last_{id_zasobu}_{i}')
                model.Add(h_var == min_h_dla_dnia).OnlyEnforceIf(is_first)
                model.Add(h_var == max_h_dla_dnia).OnlyEnforceIf(is_last)
                model.AddBoolOr([is_first, is_last])

        elif rozm == 'BLOK_ZEWNETRZNY':
            if N > 1:
                for i in range(N - 1):
                    model.Add(dni_vars[i] == dni_vars[i + 1])
                model.AddAllDifferent(godz_vars)
                max_h_bloku = model.NewIntVar(1, MAX_GODZINA, f'blok_zew_max_h_{id_zasobu}')
                min_h_bloku = model.NewIntVar(1, MAX_GODZINA, f'blok_zew_min_h_{id_zasobu}')
                model.AddMaxEquality(max_h_bloku, godz_vars)
                model.AddMinEquality(min_h_bloku, godz_vars)
                model.Add(max_h_bloku - min_h_bloku == N - 1)

                d_var = dni_vars[0]
                min_dostepna_h_dnia = model.NewIntVar(-1, MAX_GODZINA, f'blok_zew_min_h_{id_zasobu}')
                max_dostepna_h_dnia = model.NewIntVar(-1, MAX_GODZINA, f'blok_zew_max_h_{id_zasobu}')
                model.AddElement(d_var, min_h_list, min_dostepna_h_dnia)
                model.AddElement(d_var, max_h_list, max_dostepna_h_dnia)
                model.Add(min_dostepna_h_dnia != -1)

                ostatni_mozliwy_poczatek = model.NewIntVar(1, MAX_GODZINA, f'blok_zew_last_start_{id_zasobu}')
                model.Add(ostatni_mozliwy_poczatek == max_dostepna_h_dnia - N + 1)

                is_first_block = model.NewBoolVar(f'blok_zew_is_first_{id_zasobu}')
                is_last_block = model.NewBoolVar(f'blok_zew_is_last_{id_zasobu}')
                model.Add(min_h_bloku == min_dostepna_h_dnia).OnlyEnforceIf(is_first_block)
                model.Add(min_h_bloku == ostatni_mozliwy_poczatek).OnlyEnforceIf(is_last_block)
                model.AddBoolOr([is_first_block, is_last_block])

    # --- OGRANICZENIA MIĘKKIE ---

    # Funkcja pomocnicza - musi być zdefiniowana TUTAJ
    def get_lekcje_nauczyciela_o_godzinie(nauczyciel_id, dzien, godzina):
        zmienne = []
        for l_ind in wszystkie_lekcje_indywidualne:
            if l_ind['nauczyciel'] == nauczyciel_id:
                zmienne.append(przydzial_indywidualny.get((l_ind['id'], dzien, godzina)))
        for l_grup in wszystkie_lekcje_grupowe:
            if l_grup['nauczyciel'] == nauczyciel_id:
                zmienne.append(przydzial_grupowy.get((l_grup['id'], dzien, godzina)))
        return [z for z in zmienne if z is not None]

    # Minimalizacja DNI PRACY NAUCZYCIELI
    for id_n in id_nauczycieli:
        for dzien in dni_tygodnia:
            godziny_dnia = godziny_lekcyjne[dzien]
            lekcje_nauczyciela_w_dniu = []
            for g in godziny_dnia:
                lekcje_nauczyciela_w_dniu.extend(get_lekcje_nauczyciela_o_godzinie(id_n, dzien, g))

            pracuje_w_dniu = model.NewBoolVar(f'pracuje_{id_n}_{dzien}')
            if lekcje_nauczyciela_w_dniu:
                model.Add(sum(lekcje_nauczyciela_w_dniu) > 0).OnlyEnforceIf(pracuje_w_dniu)
                model.Add(sum(lekcje_nauczyciela_w_dniu) == 0).OnlyEnforceIf(pracuje_w_dniu.Not())
                punkty_karne.append(pracuje_w_dniu * 10)
            else:
                model.Add(pracuje_w_dniu == 0)

    model.Minimize(sum(punkty_karne))

    # --- Solver ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 600.0
    status = solver.Solve(model)

    # --- Wyniki ---
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f'\nZnaleziono rozwiązanie! tryb_stabilizacji={zachowaj_obecny_plan}')
        print('Wartość funkcji celu (punkty karne):', solver.ObjectiveValue())
        plan_do_zapisu = []
        plan_lekcji = collections.defaultdict(dict)

        for lekcja in wszystkie_lekcje_indywidualne:
            for dzien, godzina in wszystkie_sloty:
                if (lekcja['id'], dzien, godzina) in przydzial_indywidualny and solver.Value(
                        przydzial_indywidualny[(lekcja['id'], dzien, godzina)]) == 1:
                    dzien_skrot = mapowanie_dni_pl_na_skrot[dzien]
                    plan_do_zapisu.append({
                        'id_nauczyciel': lekcja['nauczyciel'], 'id_klasa': lekcja['klasa'],
                        'id_przedmiot': lekcja['przedmiot'], 'dzien_tygodnia': dzien_skrot,
                        'godzina_lekcyjna': godzina, 'id_grupy': None
                    })
                    plan_lekcji[(dzien, godzina)][
                        lekcja['klasa']] = f"{przedmioty[lekcja['przedmiot']]} ({nauczyciele[lekcja['nauczyciel']]})"

        for lekcja in wszystkie_lekcje_grupowe:
            for dzien, godzina in wszystkie_sloty:
                if (lekcja['id'], dzien, godzina) in przydzial_grupowy and solver.Value(
                        przydzial_grupowy[(lekcja['id'], dzien, godzina)]) == 1:
                    dzien_skrot = mapowanie_dni_pl_na_skrot[dzien]
                    plan_do_zapisu.append({
                        'id_nauczyciel': lekcja['nauczyciel'], 'id_klasa': None,
                        'id_przedmiot': lekcja['przedmiot'], 'dzien_tygodnia': dzien_skrot,
                        'godzina_lekcyjna': godzina, 'id_grupy': lekcja['id_grupy']
                    })
                    nazwy_klas = ", ".join(map(str, sorted(list(lekcja['klasy']))))
                    opis_grupy = f"GRUPA: {nazwy_klas}"
                    for id_k in lekcja['klasy']:
                        plan_lekcji[(dzien, godzina)][
                            id_k] = f"{przedmioty[lekcja['przedmiot']]} ({opis_grupy}) ({nauczyciele[lekcja['nauczyciel']]})"

        zapisz_plan_w_bazie(plan_do_zapisu, db_params)

        sorted_klasy = sorted(id_klas)
        szerokosci_kolumn = {klasa: len(f"Klasa {klasa}") for klasa in sorted_klasy}
        for (dzien, godzina), lekcje_w_slocie in plan_lekcji.items():
            for klasa, opis_lekcji in lekcje_w_slocie.items():
                if klasa in szerokosci_kolumn:
                    szerokosci_kolumn[klasa] = max(szerokosci_kolumn[klasa], len(opis_lekcji))

        for dzien in dni_tygodnia:
            print(f"\n--- {dzien.upper()} ---")
            max_godzina = max(godziny_lekcyjne[dzien])
            naglowek = f"{'Godz.':<6}"
            for klasa in sorted_klasy:
                naglowek += f" | {f'Klasa {klasa}':<{szerokosci_kolumn[klasa]}}"
            print(naglowek)
            print("-" * len(naglowek))
            for godzina in range(1, max_godzina + 1):
                print(f"{godzina:<6}", end="")
                for klasa in sorted_klasy:
                    lekcja = plan_lekcji.get((dzien, godzina), {}).get(klasa, "---")
                    print(f" | {lekcja:<{szerokosci_kolumn[klasa]}}", end="")
                print()
    else:
        print('\nNie znaleziono rozwiązania w zadanym czasie.')


# --- Krok 3: Funkcja zapisu do bazy ---
def zapisz_plan_w_bazie(plan_do_zapisu, db_params):
    """
    Czyści tabelę plan_lekcji i zapisuje w niej nowy, wygenerowany plan.
    """
    conn = None
    try:
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE plan_lekcji RESTART IDENTITY;")
        print("\nStary plan lekcji został wyczyszczony.")

        sql_insert = """
                     INSERT INTO plan_lekcji (id_nauczyciel, id_klasa, id_przedmiot, dzien_tygodnia, godzina_lekcyjna, \
                                              id_grupy)
                     VALUES (%(id_nauczyciel)s, %(id_klasa)s, %(id_przedmiot)s, %(dzien_tygodnia)s, \
                             %(godzina_lekcyjna)s, %(id_grupy)s); \
                     """
        cur.executemany(sql_insert, plan_do_zapisu)
        conn.commit()
        print(f"Pomyślnie zapisano {cur.rowcount} nowych rekordów w tabeli plan_lekcji.")

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Błąd podczas zapisu planu do bazy danych: {error}")
        if conn: conn.rollback()
    finally:
        if conn:
            cur.close()
            conn.close()


# --- Krok 4: Uruchomienie programu ---
if __name__ == '__main__':
    # Konfiguracja (przykład użycia)
    db_config = {
        "host": "localhost",
        "dbname": "plan_lekcji2",
        "user": "postgres",
        "password": "homo4cjh",
        "client_encoding": "utf8"
    }

    dane = pobierz_dane_z_bazy(db_config)

    if dane and dane[0]:
        nauczyciele, przedmioty, klasy, wymagania, grupy, ogr_nauczycieli, ogr_klas, stary_plan = dane

        # Znajdź ID dla WF
        id_wf = None
        try:
            id_wf = next(key for key, value in przedmioty.items() if value.strip().upper() == 'WF')
        except StopIteration:
            pass

        # PRZYKŁAD UŻYCIA Z FLAGĄ:
        # True = Staraj się zachować stary plan (Stabilizacja)
        # False = Generuj od zera (Nowy Rozkład)
        generuj_plan(
            nauczyciele, przedmioty, klasy, wymagania, grupy,
            ogr_nauczycieli, ogr_klas, id_wf, db_config,
            stary_plan_dane=stary_plan,
            zachowaj_obecny_plan=True  # <--- TU STERUJESZ TRYBEM
        )