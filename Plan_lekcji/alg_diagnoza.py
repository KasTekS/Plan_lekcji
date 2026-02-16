# -*- coding: utf-8 -*-
import collections
import psycopg2
from ortools.sat.python import cp_model


# ==================================================================================
# KROK 1: POBIERANIE DANYCH Z BAZY
# ==================================================================================

def pobierz_dane_z_bazy(db_params):
    """
    Funkcja łączy się z bazą danych, pobiera dane wejściowe oraz (opcjonalnie)
    istniejący plan lekcji, aby móc go optymalizować lub stabilizować.
    """
    conn = None
    try:
        print("Łączenie z bazą danych PostgreSQL...")
        conn = psycopg2.connect(**db_params)
        cur = conn.cursor()
        print("Połączenie udane. Pobieranie danych...")

        # 1. Dane podstawowe
        # Pobieramy ID i Nazwisko, aby wyświetlać czytelne komunikaty błędów
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
                    'id_grupy': id_g,
                    'nauczyciel': id_n,
                    'przedmiot': id_p,
                    'liczba_godzin': l_godzin,
                    'klasy': frozenset(klasy_w_grupach_map[id_g]),
                    'rozmieszczenie': rozmieszczenie
                })

        # 3. Ograniczenia
        cur.execute("SELECT Od_, Do_, Dzien_tygodnia, Nauczyciel_ID FROM Ograniczenia")
        ograniczenia_nauczycieli = cur.fetchall()

        cur.execute("SELECT id_klasy, dzien_tygodnia, od_, do_ FROM ograniczenia_klas")
        ograniczenia_klas = cur.fetchall()

        # 4. ISTNIEJĄCY PLAN LEKCJI (Do stabilizacji)
        print("Pobieranie istniejącego planu lekcji (do stabilizacji)...")
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

        # Sortujemy historię, aby łatwiej porównywać kolejność lekcji
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


# ==================================================================================
# KROK 2: LOGIKA GENERATORA I DIAGNOSTYKA
# ==================================================================================

def generuj_plan(nauczyciele, przedmioty, klasy_info, wymagania_indywidualne, grupy_z_bazy, ograniczenia_nauczycieli,
                 ograniczenia_klas, id_wf, db_params, stary_plan_dane, zachowaj_obecny_plan=False):
    stary_plan_ind, stary_plan_grup = stary_plan_dane

    # --- Przygotowanie stałych i mapowań ---
    id_nauczycieli = list(nauczyciele.keys())
    id_klas = list(klasy_info.keys())
    dni_tygodnia = ['Poniedziałek', 'Wtorek', 'Środa', 'Czwartek', 'Piątek']
    mapowanie_dni_skrot_na_pl = {'PON': 'Poniedziałek', 'WT': 'Wtorek', 'SR': 'Środa', 'CZW': 'Czwartek',
                                 'PT': 'Piątek'}
    mapowanie_dni_pl_na_skrot = {v: k for k, v in mapowanie_dni_skrot_na_pl.items()}

    godziny_lekcyjne = {d: list(range(1, 11)) for d in dni_tygodnia}  # Godziny 1-10
    wszystkie_sloty = [(dzien, godzina) for dzien in dni_tygodnia for godzina in godziny_lekcyjne[dzien]]
    dni_do_indeksu = {dzien: i for i, dzien in enumerate(dni_tygodnia)}

    MAX_GODZINA = 10

    # Inicjalizacja modelu
    model = cp_model.CpModel()
    punkty_karne = []  # Tutaj zbieramy wszystkie 'soft constraints'

    # LISTA DO PRZECHOWYWANIA INFORMACJI O BŁĘDACH (DIAGNOSTYKA)
    # Format: (zmienna_boolowska_naruszenia, komunikat_tekstowy)
    diagnostyka_naruszen = []
    KARA_KRYTYCZNA = 1000000  # 1 milion punktów karnych za złamanie ograniczenia dostępności

    # --- Analiza dostępności slotów (pomocnicza dla logiki ZEWNETRZNE/BLOK) ---
    dostepne_sloty_klasy = {}
    for id_k in id_klas:
        dostepne_sloty_klasy[id_k] = {}
        for dzien_pl in dni_tygodnia:
            dzien_skrot = mapowanie_dni_pl_na_skrot[dzien_pl]
            potencjalne_godziny = set(godziny_lekcyjne[dzien_pl])
            # Tutaj na razie tylko zdejmujemy godziny dla logiki bloków,
            # ale właściwe ograniczenie będzie nałożone jako Soft Constraint poniżej.
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

    # Obliczanie granic (min/max) dla wymogów rozmieszczenia (ZEWNETRZNE)
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

    # ==============================================================================
    # TWORZENIE ZMIENNYCH DECYZYJNYCH
    # ==============================================================================

    lekcje_do_specjalnej_obslugi = collections.defaultdict(
        lambda: {'dni': [], 'godziny': [], 'rozm': 'BRAK', 'N': 0, 'klasy': set()})

    przydzial_indywidualny = {}
    wszystkie_lekcje_indywidualne = []

    # 1. Lekcje Indywidualne
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

                # Wiązanie zmiennych pomocniczych (dzień/godzina) z boolami
                model.Add(day_var == dni_do_indeksu[dzien]).OnlyEnforceIf(var)
                model.Add(hour_var == godzina).OnlyEnforceIf(var)

            model.AddExactlyOne(all_bool_vars)

            # STABILIZACJA (Zachowanie starego planu)
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

    # 2. Lekcje Grupowe
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

            # STABILIZACJA (Grupy)
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

    # ==============================================================================
    # OGRANICZENIA TWARDE (Fizyka: nie można być w dwóch miejscach naraz)
    # ==============================================================================

    # 1. Konflikt klasy: Klasa może mieć max 1 lekcję w danym slocie
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

    # 2. Konflikt nauczyciela: Nauczyciel może prowadzić max 1 lekcję w danym slocie
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

    # ==============================================================================
    # OGRANICZENIA DIAGNOSTYCZNE (Tzw. Relaxed Constraints)
    # Zamiast 'Add(x==0)', robimy 'Add(x==0 OR violation==1)'
    # ==============================================================================

    # 3. Ograniczenia czasowe nauczycieli
    for od, do, dzien_skrot, id_n in ograniczenia_nauczycieli:
        dzien = mapowanie_dni_skrot_na_pl.get(dzien_skrot.strip().upper())
        if dzien:
            for godzina in range(od, do + 1):
                if (dzien, godzina) in wszystkie_sloty:
                    # Zbieramy wszystkie lekcje tego nauczyciela, które MOGŁYBY się tu odbyć
                    zmienne_w_zakazanym_slocie = []

                    for l in wszystkie_lekcje_indywidualne:
                        if l['nauczyciel'] == id_n:
                            zmienne_w_zakazanym_slocie.append(przydzial_indywidualny[(l['id'], dzien, godzina)])
                    for l in wszystkie_lekcje_grupowe:
                        if l['nauczyciel'] == id_n:
                            zmienne_w_zakazanym_slocie.append(przydzial_grupowy[(l['id'], dzien, godzina)])

                    if zmienne_w_zakazanym_slocie:
                        # Tworzymy zmienną "naruszenia zasady"
                        naruszenie = model.NewBoolVar(f'naruszenie_naucz_{id_n}_{dzien}_{godzina}')

                        # Logika: Suma lekcji > 0  => Naruszenie musi być TRUE
                        #         Suma lekcji == 0 => Naruszenie musi być FALSE
                        model.Add(sum(zmienne_w_zakazanym_slocie) > 0).OnlyEnforceIf(naruszenie)
                        model.Add(sum(zmienne_w_zakazanym_slocie) == 0).OnlyEnforceIf(naruszenie.Not())

                        # Dodajemy OGROMNĄ karę, żeby solver tego unikał, chyba że musi
                        punkty_karne.append(naruszenie * KARA_KRYTYCZNA)

                        # Rejestrujemy informację dla użytkownika
                        imie = nauczyciel_nazwa = nauczyciele.get(id_n, f"ID: {id_n}")
                        msg = f"Nauczyciel {imie} ma lekcję w {dzien} godz. {godzina}, mimo blokady dostępności."
                        diagnostyka_naruszen.append((naruszenie, msg))

    # 4. Ograniczenia czasowe klas
    for id_k, dzien_skrot, od, do in ograniczenia_klas:
        dzien_pl = mapowanie_dni_skrot_na_pl.get(dzien_skrot.strip().upper())
        if dzien_pl:
            for godzina in range(od, do + 1):
                if (dzien_pl, godzina) in wszystkie_sloty:
                    zmienne_w_zakazanym_slocie = []

                    for l in wszystkie_lekcje_indywidualne:
                        if l['klasa'] == id_k:
                            zmienne_w_zakazanym_slocie.append(
                                przydzial_indywidualny[(l['id'], dzien_pl, godzina)])
                    for l in wszystkie_lekcje_grupowe:
                        if id_k in l['klasy']:
                            zmienne_w_zakazanym_slocie.append(przydzial_grupowy[(l['id'], dzien_pl, godzina)])

                    if zmienne_w_zakazanym_slocie:
                        naruszenie = model.NewBoolVar(f'naruszenie_klasa_{id_k}_{dzien_pl}_{godzina}')

                        model.Add(sum(zmienne_w_zakazanym_slocie) > 0).OnlyEnforceIf(naruszenie)
                        model.Add(sum(zmienne_w_zakazanym_slocie) == 0).OnlyEnforceIf(naruszenie.Not())

                        punkty_karne.append(naruszenie * KARA_KRYTYCZNA)

                        msg = f"Klasa {id_k} ma lekcję w {dzien_pl} godz. {godzina}, mimo blokady dostępności."
                        diagnostyka_naruszen.append((naruszenie, msg))

    # ==============================================================================
    # SPECYFICZNE OGRANICZENIA (WF, BLOKI)
    # ==============================================================================

    # 5. WF (Maksymalna liczba grup na sali gimnastycznej w jednym momencie)
    if id_wf is not None:
        for dzien in dni_tygodnia:
            for godzina in godziny_lekcyjne[dzien]:
                wf_w_tym_czasie = []
                for id_n in id_nauczycieli:
                    # Sprawdzamy czy dany nauczyciel prowadzi WF w tej godzinie
                    uczy_wf_teraz = model.NewBoolVar(f'wf_{id_n}_{dzien}_{godzina}')
                    lekcje_wf_nauczyciela = []

                    for l in wszystkie_lekcje_indywidualne:
                        if l['nauczyciel'] == id_n and l['przedmiot'] == id_wf:
                            lekcje_wf_nauczyciela.append(przydzial_indywidualny[(l['id'], dzien, godzina)])
                    for l in wszystkie_lekcje_grupowe:
                        if l['nauczyciel'] == id_n and l['przedmiot'] == id_wf:
                            lekcje_wf_nauczyciela.append(przydzial_grupowy[(l['id'], dzien, godzina)])

                    if not lekcje_wf_nauczyciela:
                        model.Add(uczy_wf_teraz == 0)
                    else:
                        model.Add(sum(lekcje_wf_nauczyciela) > 0).OnlyEnforceIf(uczy_wf_teraz)
                        model.Add(sum(lekcje_wf_nauczyciela) == 0).OnlyEnforceIf(uczy_wf_teraz.Not())

                    wf_w_tym_czasie.append(uczy_wf_teraz)

                # Ograniczenie: Max 8 grup WF naraz (pojemność hali)
                # To też może być potencjalna przyczyna błędu, więc robimy miękką walidację
                nadmiar_wf = model.NewBoolVar(f'naruszenie_wf_pojemnosc_{dzien}_{godzina}')
                # Jeśli suma > 8, nadmiar = 1
                model.Add(sum(wf_w_tym_czasie) > 8).OnlyEnforceIf(nadmiar_wf)
                model.Add(sum(wf_w_tym_czasie) <= 8).OnlyEnforceIf(nadmiar_wf.Not())

                punkty_karne.append(nadmiar_wf * KARA_KRYTYCZNA)
                msg_wf = f"Przekroczono limit sali gimnastycznej (WF) w {dzien} o godz. {godzina}."
                diagnostyka_naruszen.append((nadmiar_wf, msg_wf))

    # 6. Nauczyciele uczący innych przedmiotów (Constraint z oryginału)
    # Oryginał zakładał, że jeśli nauczyciel uczy WF, to może mieć ograniczenia co do innych przedmiotów?
    # W oryginalnym kodzie była logika sum(nauczyciele_uczacy_inny_przedmiot) <= 8.
    # Zakładam, że chodziło o globalny limit sal lekcyjnych. Przywracam to.
    for dzien in dni_tygodnia:
        for godzina in godziny_lekcyjne[dzien]:
            nauczyciele_uczacy_nie_wf = []
            for id_n in id_nauczycieli:
                uczy_innego = model.NewBoolVar(f'teach_other_{id_n}_{dzien}_{godzina}')
                l_nie_wf = []
                for l in wszystkie_lekcje_indywidualne:
                    if l['nauczyciel'] == id_n and (id_wf is None or l['przedmiot'] != id_wf):
                        l_nie_wf.append(przydzial_indywidualny[(l['id'], dzien, godzina)])
                for l in wszystkie_lekcje_grupowe:
                    if l['nauczyciel'] == id_n and (id_wf is None or l['przedmiot'] != id_wf):
                        l_nie_wf.append(przydzial_grupowy[(l['id'], dzien, godzina)])

                if not l_nie_wf:
                    model.Add(uczy_innego == 0)
                else:
                    model.Add(sum(l_nie_wf) > 0).OnlyEnforceIf(uczy_innego)
                    model.Add(sum(l_nie_wf) == 0).OnlyEnforceIf(uczy_innego.Not())
                nauczyciele_uczacy_nie_wf.append(uczy_innego)

            # Limit sal lekcyjnych (nie-WF) np. 50? (W oryginale było <= 8, co wydaje się małe, ale zostawiam miękko)
            # Jeśli w szkole jest mało sal, to też może blokować plan.
            # UWAGA: W oryginale było <= 8. Jeśli szkoła jest duża, to zablokuje wszystko.
            # Zakładam, że to był test. Zostawiam z wysokim limitem lub jako soft constraint.
            # Zmieniam na Soft Constraint dla bezpieczeństwa.

            brak_sal = model.NewBoolVar(f'brak_sal_{dzien}_{godzina}')
            model.Add(sum(nauczyciele_uczacy_nie_wf) > 50).OnlyEnforceIf(
                brak_sal)  # Zwiększyłem limit do 50 sal bezpiecznie
            model.Add(sum(nauczyciele_uczacy_nie_wf) <= 50).OnlyEnforceIf(brak_sal.Not())
            punkty_karne.append(brak_sal * KARA_KRYTYCZNA)
            # Nie dodaję do diagnostyki, chyba że ustawisz realny limit sal.

    # 7. Obsługa Bloków i Rozmieszczenia (BLOK, ZEWNETRZNE, BLOK_ZEWNETRZNY)
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

        # BLOK: Lekcje jedna po drugiej w tym samym dniu
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

        # ZEWNETRZNE: Pierwsza lub ostatnia lekcja w planie dnia klasy
        elif rozm == 'ZEWNETRZNE':
            for i, (d_var, h_var) in enumerate(zip(dni_vars, godz_vars)):
                min_h_dla_dnia = model.NewIntVar(-1, MAX_GODZINA, f'zew_min_h_{id_zasobu}_{i}')
                max_h_dla_dnia = model.NewIntVar(-1, MAX_GODZINA, f'zew_max_h_{id_zasobu}_{i}')
                model.AddElement(d_var, min_h_list, min_h_dla_dnia)
                model.AddElement(d_var, max_h_list, max_h_dla_dnia)

                # Zamiast twardego błędu, jeśli min_h == -1 (brak slotów), pozwól, ale to wyjdzie w innych błędach
                model.Add(min_h_dla_dnia != -1)

                is_first = model.NewBoolVar(f'zew_is_first_{id_zasobu}_{i}')
                is_last = model.NewBoolVar(f'zew_is_last_{id_zasobu}_{i}')
                model.Add(h_var == min_h_dla_dnia).OnlyEnforceIf(is_first)
                model.Add(h_var == max_h_dla_dnia).OnlyEnforceIf(is_last)
                model.AddBoolOr([is_first, is_last])

        # BLOK_ZEWNETRZNY: Blok na początku lub końcu dnia
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

    # ==============================================================================
    # OGRANICZENIA MIĘKKIE (Dni pracy, okienka - opcjonalne)
    # ==============================================================================

    def get_lekcje_nauczyciela_o_godzinie(nauczyciel_id, dzien, godzina):
        zmienne = []
        for l_ind in wszystkie_lekcje_indywidualne:
            if l_ind['nauczyciel'] == nauczyciel_id:
                zmienne.append(przydzial_indywidualny.get((l_ind['id'], dzien, godzina)))
        for l_grup in wszystkie_lekcje_grupowe:
            if l_grup['nauczyciel'] == nauczyciel_id:
                zmienne.append(przydzial_grupowy.get((l_grup['id'], dzien, godzina)))
        return [z for z in zmienne if z is not None]

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
                punkty_karne.append(pracuje_w_dniu * 10)  # Mała kara za przyjście do pracy (minimalizacja dni)
            else:
                model.Add(pracuje_w_dniu == 0)

    # ==============================================================================
    # URUCHOMIENIE SOLVERA
    # ==============================================================================

    model.Minimize(sum(punkty_karne))

    # --- Krok 3: Uruchomienie solvera (TRYB DIAGNOZA - TYLKO RAPORT) ---
    print("Rozpoczynam diagnozę (szukanie rozwiązania z dopuszczeniem błędów)...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 300

    status = solver.Solve(model)

    wynik_dzialania = {
        'czy_sukces': False,
        'wiadomosc': ''
    }

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"Znaleziono rozwiązanie diagnostyczne! Status: {solver.StatusName(status)}")

        # --- Generowanie raportu naruszeń ---
        raport_linii = []
        liczba_naruszen = 0

        # Nagłówek raportu
        raport_linii.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        raport_linii.append(" DIAGNOSTYKA KONFLIKTÓW: RAPORT")
        raport_linii.append(" Poniżej lista ograniczeń, które blokują ułożenie planu idealnego.")
        raport_linii.append("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")

        # Sprawdzamy listę 'diagnostyka_naruszen' (musi być wypełniana w trakcie tworzenia modelu)
        # Format elementu w liście: (zmienna_solver, "Treść błędu")
        if 'diagnostyka_naruszen' in locals():
            idx = 1
            for var_bool, komunikat in diagnostyka_naruszen:
                # Jeśli solver ustawił zmienną karną na 1 (True), to znaczy, że reguła została złamana
                if solver.Value(var_bool) == 1:
                    raport_linii.append(f"{idx}. {komunikat}")
                    liczba_naruszen += 1
                    idx += 1

        if liczba_naruszen == 0:
            raport_linii.append("BRAK KONFLIKTÓW! Algorytm jest w stanie ułożyć plan idealny przy obecnych danych.")
            raport_linii.append("Możesz bezpiecznie uruchomić generowanie planu (tryb NOWY lub UPDATE).")
        else:
            raport_linii.append(f"\nŁącznie wykryto problemów: {liczba_naruszen}")
            raport_linii.append(
                "Aby ułożyć plan, musisz poluzować powyższe ograniczenia (np. usunąć blokadę godzin nauczyciela).")

        # Łączymy wszystko w jeden tekst (używamy <br> lub \n zależnie od tego jak wyświetlasz to w HTML)
        # Tutaj używam \n, w HTML użyj filtra |linebreaksbr
        pelny_raport = "\n".join(raport_linii)

        # UWAGA: NIE ZAPISUJEMY DO BAZY (PlanLekcji.objects.create...)
        # Tryb diagnozy tylko zwraca informacje.

        wynik_dzialania['czy_sukces'] = True  # Sukces techniczny (algorytm zadziałał)
        wynik_dzialania['wiadomosc'] = pelny_raport

    elif status == cp_model.INFEASIBLE:
        wynik_dzialania['czy_sukces'] = False
        wynik_dzialania[
            'wiadomosc'] = "Nawet po poluzowaniu reguł (diagnoza) nie udało się znaleźć rozwiązania. Problem jest krytyczny (np. za mało sal lub godzin w dobie)."

    else:
        wynik_dzialania['czy_sukces'] = False
        wynik_dzialania['wiadomosc'] = f"Diagnostyka przerwana bez wyniku. Status: {solver.StatusName(status)}"

    return wynik_dzialania