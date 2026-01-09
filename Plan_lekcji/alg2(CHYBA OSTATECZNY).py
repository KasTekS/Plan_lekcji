# -*- coding: utf-8 -*-
import collections
import psycopg2
from ortools.sat.python import cp_model


# --- Krok 1: Wczytywanie danych z bazy ---
def pobierz_dane_z_bazy(db_params):
    """
    Funkcja łączy się z bazą danych, pobiera wszystkie potrzebne dane,
    w tym lekcje indywidualne, grupy oraz ograniczenia dla klas i nauczycieli.
    """
    conn = None
    try:
        print("Łączenie z bazą danych PostgreSQL...")
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()
        print("Połączenie udane.")

        # Pobieranie danych podstawowych
        cur.execute("SELECT ID, Imie_Nazwisko FROM Nauczyciel ORDER BY ID")
        nauczyciele = dict(cur.fetchall())
        cur.execute("SELECT ID, Skrot FROM Przedmioty ORDER BY ID")
        przedmioty = dict(cur.fetchall())
        cur.execute("SELECT ID, Rok, Ilosc_osob FROM Klasa ORDER BY ID")
        klasy_raw = cur.fetchall()
        klasy = {k_id: {'rok': rok, 'ilosc_osob': ilosc} for k_id, rok, ilosc in klasy_raw}

        # Pobieranie wymagań indywidualnych (z kolumną 'rozmieszczenie')
        cur.execute(
            "SELECT ID, ID_nauczyciel, ID_klasa, ID_przedmiot, Liczba_godzin, rozmieszczenie FROM Wymagania_przedmiotowe")
        wymagania_indywidualne = cur.fetchall()
        print(f"Pobrano {len(wymagania_indywidualne)} wymagań dla lekcji indywidualnych.")

        # Pobieranie grup (z kolumną 'rozmieszczenie')
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
        print(f"Pobrano {len(grupy_z_bazy)} zdefiniowanych grup z bazy danych.")

        # Pobieranie ograniczeń
        cur.execute("SELECT Od_, Do_, Dzien_tygodnia, Nauczyciel_ID FROM Ograniczenia")
        ograniczenia_nauczycieli = cur.fetchall()
        cur.execute("SELECT id_klasy, dzien_tygodnia, od_, do_ FROM ograniczenia_klas")
        ograniczenia_klas = cur.fetchall()
        print(f"Pobrano {len(ograniczenia_klas)} rekordów ograniczeń dla klas.")

        print("Pomyślnie pobrano wszystkie dane z bazy.")
        cur.close()
        return nauczyciele, przedmioty, klasy, wymagania_indywidualne, grupy_z_bazy, ograniczenia_nauczycieli, ograniczenia_klas

    except (Exception, psycopg2.DatabaseError) as error:
        print(f"Błąd podczas połączenia lub pobierania danych z PostgreSQL: {error}")
        return None, None, None, None, None, None, None
    finally:
        if conn is not None:
            conn.close()
            print("Połączenie z bazą danych zostało zamknięte.")


# --- Krok 2: Główna logika generatora ---
def generuj_plan(nauczyciele, przedmioty, klasy_info, wymagania_indywidualne, grupy_z_bazy, ograniczenia_nauczycieli,
                 ograniczenia_klas, id_wf, db_params):
    # --- Przygotowanie danych ---
    id_nauczycieli = list(nauczyciele.keys())
    id_klas = list(klasy_info.keys())
    dni_tygodnia = ['Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek']
    mapowanie_dni_skrot_na_pl = {'PON': 'Poniedziałek', 'WT': 'Wtorek', 'SR': 'Środa', 'CZW': 'Czwartek',
                                 'PT': 'Piątek'}
    mapowanie_dni_pl_na_skrot = {v: k for k, v in mapowanie_dni_skrot_na_pl.items()}
    godziny_lekcyjne = {
        'Poniedziałek': list(range(1, 11)), 'Wtorek': list(range(1, 11)),
        'Środa': list(range(1, 11)), 'Czwartek': list(range(1, 11)),
        'Piątek': list(range(1, 11))
    }
    wszystkie_sloty = [(dzien, godzina) for dzien in dni_tygodnia for godzina in godziny_lekcyjne[dzien]]
    dni_do_indeksu = {dzien: i for i, dzien in enumerate(dni_tygodnia)}

    MAX_GODZINA = 10

    model = cp_model.CpModel()

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

            lekcje_do_specjalnej_obslugi[klucz_grupy]['dni'].append(day_var)
            lekcje_do_specjalnej_obslugi[klucz_grupy]['godziny'].append(hour_var)

    # --- OGRANICZENIA TWARDE ---

    # 2. Jedna klasa może mieć co najwyżej jedną lekcję w danym slocie.
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

    # 3. Jeden nauczyciel może mieć co najwyżej jedną lekcję w danym slocie.
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

    # 4. Ograniczenia dostępności nauczycieli.
    for od, do, dzien_skrot, id_n in ograniczenia_nauczycieli:
        dzien = mapowanie_dni_skrot_na_pl.get(dzien_skrot.strip().upper())
        if dzien:
            for godzina in range(od, do + 1):
                if (dzien, godzina) in wszystkie_sloty:
                    for l in wszystkie_lekcje_indywidualne:
                        if l['nauczyciel'] == id_n: model.Add(przydzial_indywidualny[(l['id'], dzien, godzina)] == 0)
                    for l in wszystkie_lekcje_grupowe:
                        if l['nauczyciel'] == id_n: model.Add(przydzial_grupowy[(l['id'], dzien, godzina)] == 0)

    # 5. Ograniczenia dostępności klas (podwójne zabezpieczenie).
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

    # 6. Ograniczenie liczby nauczycieli (WF)
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

    # 7. Ograniczenie 7 - Bloki i DYNAMICZNE Rozmieszczenie
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
        else:  # 'grup'
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
                # 1. Logika bloku
                for i in range(N - 1):
                    model.Add(dni_vars[i] == dni_vars[i + 1])
                model.AddAllDifferent(godz_vars)
                max_h_bloku = model.NewIntVar(1, MAX_GODZINA, f'blok_zew_max_h_{id_zasobu}')
                min_h_bloku = model.NewIntVar(1, MAX_GODZINA, f'blok_zew_min_h_{id_zasobu}')
                model.AddMaxEquality(max_h_bloku, godz_vars)
                model.AddMinEquality(min_h_bloku, godz_vars)
                model.Add(max_h_bloku - min_h_bloku == N - 1)

                # 2. Logika zewnętrzna (dynamiczna)
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

    punkty_karne = []

    # === NOWA FUNKCJA POMOCNICZA (tylko dla ograniczeń miękkich) ===
    # Definiujemy ją raz, aby używać jej wielokrotnie w pętli poniżej
    def get_lekcje_nauczyciela_o_godzinie(nauczyciel_id, dzien, godzina):
        zmienne = []
        for l_ind in wszystkie_lekcje_indywidualne:
            if l_ind['nauczyciel'] == nauczyciel_id:
                zmienne.append(przydzial_indywidualny.get((l_ind['id'], dzien, godzina)))
        for l_grup in wszystkie_lekcje_grupowe:
            if l_grup['nauczyciel'] == nauczyciel_id:
                zmienne.append(przydzial_grupowy.get((l_grup['id'], dzien, godzina)))
        return [z for z in zmienne if z is not None]

    # === NOWA LOGIKA: Minimalizacja okienek i dni pracy NAUCZYCIELI ===
    # Zastępujemy logikę dla uczniów logiką dla nauczycieli

    for id_n in id_nauczycieli:
        for dzien in dni_tygodnia:
            godziny_dnia = godziny_lekcyjne[dzien]

            # --- 1. Minimalizacja OKIENEK (Waga: 50) ---
            for g1_idx, g1 in enumerate(godziny_dnia[:-2]):
                g2, g3 = godziny_dnia[g1_idx + 1], godziny_dnia[g1_idx + 2]

                ma_lekcje_g1 = model.NewBoolVar(f'nauczyciel_{id_n}_ma_lekcje_{dzien}_{g1}')
                ma_lekcje_g2 = model.NewBoolVar(f'nauczyciel_{id_n}_ma_lekcje_{dzien}_{g2}')
                ma_lekcje_g3 = model.NewBoolVar(f'nauczyciel_{id_n}_ma_lekcje_{dzien}_{g3}')

                # Sprawdź lekcje na g1
                lekcje_g1 = get_lekcje_nauczyciela_o_godzinie(id_n, dzien, g1)
                if lekcje_g1:
                    model.Add(sum(lekcje_g1) >= 1).OnlyEnforceIf(ma_lekcje_g1)
                    model.Add(sum(lekcje_g1) == 0).OnlyEnforceIf(ma_lekcje_g1.Not())
                else:
                    model.Add(ma_lekcje_g1 == 0)

                # Sprawdź lekcje na g2 (okienko)
                lekcje_g2 = get_lekcje_nauczyciela_o_godzinie(id_n, dzien, g2)
                if lekcje_g2:
                    model.Add(sum(lekcje_g2) == 0).OnlyEnforceIf(ma_lekcje_g2.Not())
                    model.Add(sum(lekcje_g2) >= 1).OnlyEnforceIf(ma_lekcje_g2)
                else:
                    model.Add(ma_lekcje_g2 == 0)

                # Sprawdź lekcje na g3
                lekcje_g3 = get_lekcje_nauczyciela_o_godzinie(id_n, dzien, g3)
                if lekcje_g3:
                    model.Add(sum(lekcje_g3) >= 1).OnlyEnforceIf(ma_lekcje_g3)
                    model.Add(sum(lekcje_g3) == 0).OnlyEnforceIf(ma_lekcje_g3.Not())
                else:
                    model.Add(ma_lekcje_g3 == 0)

                # Zdefiniuj okienko: (Lekcja) AND (Brak Lekcji) AND (Lekcja)
                okienko_nauczyciela = model.NewBoolVar(f'nauczyciel_okienko_{id_n}_{dzien}_{g2}')
                model.AddBoolAnd([ma_lekcje_g1, ma_lekcje_g2.Not(), ma_lekcje_g3]).OnlyEnforceIf(okienko_nauczyciela)
                punkty_karne.append(okienko_nauczyciela * 50)  # Wysoka kara za okienko

            # --- 2. Minimalizacja DNI PRACY (Waga: 10) ---
            # (Ta logika jest poza pętlą 'for g1_idx...')
            lekcje_nauczyciela_w_dniu = []
            for g in godziny_dnia:
                lekcje_nauczyciela_w_dniu.extend(get_lekcje_nauczyciela_o_godzinie(id_n, dzien, g))

            pracuje_w_dniu = model.NewBoolVar(f'pracuje_{id_n}_{dzien}')
            if lekcje_nauczyciela_w_dniu:
                model.Add(sum(lekcje_nauczyciela_w_dniu) > 0).OnlyEnforceIf(pracuje_w_dniu)
                model.Add(sum(lekcje_nauczyciela_w_dniu) == 0).OnlyEnforceIf(pracuje_w_dniu.Not())
                punkty_karne.append(pracuje_w_dniu * 10)  # Niższa kara za sam dzień pracy
            else:
                model.Add(pracuje_w_dniu == 0)

    # --- Koniec sekcji ograniczeń miękkich ---

    model.Minimize(sum(punkty_karne))

    # --- Uruchomienie Solvera ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 500.0
    status = solver.Solve(model)

    # --- Wyświetlanie i ZAPISYWANIE wyników ---
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print('\nZnaleziono rozwiązanie! Wartość funkcji celu (punkty karne):', solver.ObjectiveValue())
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
        print('\nNie znaleziono rozwiązania w zadanym czasie. Możliwe przyczyny:')
        print('- Ograniczenia są ze sobą sprzeczne (np. "BLOK_ZEWNETRZNY" dla klasy, która nie ma wolnych krawędzi).')
        print('- Problem jest zbyt złożony dla zadanego czasu.')


# --- Krok 3: Funkcja zapisu do bazy ---
def zapisz_plan_w_bazie(plan_do_zapisu, db_params):
    """
    Czyści tabelę plan_lekcji i zapisuje w niej nowy, wygenerowany plan.
    """
    conn = None
    try:
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()
        # Czyścimy stary plan
        cur.execute("TRUNCATE TABLE plan_lekcji RESTART IDENTITY;")
        print("\nStary plan lekcji został wyczyszczony.")

        sql_insert = """
                     INSERT INTO plan_lekcji (id_nauczyciel, id_klasa, id_przedmiot, dzien_tygodnia, godzina_lekcyjna, \
                                              id_grupy)
                     VALUES (%(id_nauczyciel)s, %(id_klasa)s, %(id_przedmiot)s, %(dzien_tygodnia)s, \
                             %(godzina_lekcyjna)s, %(id_grupy)s); \
                     """
        # Zapisujemy nowy plan
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
            print("Połączenie z bazą danych (zapis) zostało zamknięte.")


# --- Krok 4: Uruchomienie programu ---
if __name__ == '__main__':
    # Uzupełnij swoje dane do bazy
    db_config = {
        "host": "localhost",
        "dbname": "plan",
        "user": "postgres",
        "password": "homo4cjh",
        "client_encoding": "utf8"
    }

    dane = pobierz_dane_z_bazy(db_config)

    if dane and (dane[3] or dane[4]):  # Sprawdź, czy są jakiekolwiek lekcje
        nauczyciele, przedmioty, klasy, wymagania, grupy, ogr_nauczycieli, ogr_klas = dane

        # Znajdź ID dla WF
        id_wf = None
        try:
            id_wf = next(key for key, value in przedmioty.items() if value.strip().upper() == 'WF')
            print(f"Znaleziono ID dla Wychowania Fizycznego: {id_wf}")
        except StopIteration:
            print(
                "OSTRZEŻENIE: Nie znaleziono w bazie przedmiotu o skrócie 'WF'. Ograniczenie limitu nauczycieli nie będzie aktywne.")

        # Uruchom główny generator
        generuj_plan(nauczyciele, przedmioty, klasy, wymagania, grupy, ogr_nauczycieli, ogr_klas, id_wf, db_config)