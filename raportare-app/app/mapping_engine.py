"""
Motorul de mapare balanta -> format universal.

Reguli aplicate (SOP validat pe Dial / SARCOM / Toto):
1. Clasificare BS/Ven/Exp dupa prima cifra a contului (7->Ven, 6->Exp, altfel->BS).
2. Lookup cod de mapare: intai contul exact in overrides-ul firmei client, apoi
   contul exact in planul de conturi universal, apoi radacina (fara analitic),
   apoi radacini din ce in ce mai scurte (fallback grad I).
3. Conturi CONTRA (ex. 609, 709, 667, 767): formula inversata fata de tipul standard.
4. Conturi AUTO-INCHIS (ex. 711, 712): rulajul brut nu e contributia reala -
   se marcheaza pentru calcul manual/separat (nu intra automat in Check pana
   nu e confirmata o regula specifica, vezi nota_verificare).
5. Egalitati: BS ~ 0, P&L (cumulat/luna), #121, Check = P&L + #121 ~ 0.
"""
import re


def tip_din_cont(cont: str) -> str:
    c = str(cont).strip()
    if c.startswith('7'):
        return 'Ven'
    if c.startswith('6'):
        return 'Exp'
    return 'BS'


def _root_candidates(cont: str):
    """Genereaza candidati de radacina, de la cel mai specific la cel mai general."""
    c = str(cont).strip()
    yield c  # cont exact
    root = re.split(r'[.\s]', c)[0]
    if root != c:
        yield root
    for ln in range(len(root) - 1, 2, -1):
        yield root[:ln]


def lookup_mapping(cont: str, chart_by_cont: dict, overrides_by_cont: dict):
    """
    Intoarce (cod_mapare, descriere_cod, tratament_special, sursa, match_how)
    cautand intai in override-urile firmei, apoi in planul de conturi universal.
    """
    c = str(cont).strip()

    if c in overrides_by_cont:
        o = overrides_by_cont[c]
        return o['cod_mapare'], o.get('descriere_cod'), o.get('tratament_special'), 'override', 'override-exact'

    seen_root = False
    for cand in _root_candidates(c):
        if cand in chart_by_cont:
            entry = chart_by_cont[cand]
            how = 'exact' if cand == c else ('root' if not seen_root else f'root-scurt({cand})')
            return entry['cod_mapare'], entry.get('descriere_cod'), entry.get('tratament_special'), entry.get('sursa'), how
        seen_root = True

    return None, None, None, None, None


def map_balance_lines(lines: list, chart_by_cont: dict, overrides_by_cont: dict):
    """
    lines: list de dict cu chei: cont, denumire, si_debit, si_credit,
           rulaj_luna_debit, rulaj_luna_credit, rulaj_cumulat_debit,
           rulaj_cumulat_credit, sf_debit, sf_credit
    Intoarce (mapped_rows, unmapped_conturi)
    """
    mapped = []
    unmapped = []

    for ln in lines:
        cont = str(ln['cont']).strip()
        tip = tip_din_cont(cont)
        D, E = ln.get('si_debit', 0) or 0, ln.get('si_credit', 0) or 0
        F, G = ln.get('rulaj_luna_debit', 0) or 0, ln.get('rulaj_luna_credit', 0) or 0
        H, I = ln.get('rulaj_cumulat_debit', 0) or 0, ln.get('rulaj_cumulat_credit', 0) or 0
        J, K = ln.get('sf_debit', 0) or 0, ln.get('sf_credit', 0) or 0

        cod, descriere, tratament, sursa, how = lookup_mapping(cont, chart_by_cont, overrides_by_cont)
        if cod is None:
            unmapped.append(cont)

        diferenta_si = D - E
        diferenta_sf = J - K

        is_contra = bool(tratament and 'CONTRA' in tratament)
        is_auto = bool(tratament and 'AUTO' in tratament)

        rulaj_cumulat_mapat = None
        rulaj_luna_mapat = None

        if tip == 'BS':
            pass  # foloseste diferenta_si / diferenta_sf, nu rulaj mapat
        elif is_auto:
            # rulaj brut expus separat - valoarea reala se calculeaza cu o regula
            # dedicata (ex. varianta neta din conturile de stoc), confirmata per client.
            rulaj_cumulat_mapat = I
            rulaj_luna_mapat = F
        elif tip == 'Exp':
            rulaj_cumulat_mapat = I if is_contra else -I
            rulaj_luna_mapat = F if is_contra else -F
        elif tip == 'Ven':
            rulaj_cumulat_mapat = -I if is_contra else I
            rulaj_luna_mapat = -F if is_contra else F

        mapped.append(dict(
            cont=cont, denumire=ln.get('denumire'), tip=tip,
            cod_mapare=cod, descriere_cod=descriere, tratament_special=tratament,
            diferenta_si=diferenta_si, diferenta_sf=diferenta_sf,
            rulaj_cumulat_mapat=rulaj_cumulat_mapat, rulaj_luna_mapat=rulaj_luna_mapat,
            sursa_mapare=sursa, match_how=how,
            rulaj_luna_raw=(F - G),
        ))

    return mapped, unmapped


def compute_checks(mapped_rows: list):
    """Calculeaza egalitatile BS / P&L / #121 / Check, cumulat si luna."""
    bs_sum = 0.0
    exp_n = ven_n = exp_o = ven_o = 0.0
    cont121_sf = None
    cont121_luna = None
    auto_inchis_prezente = []

    for r in mapped_rows:
        if r['tip'] == 'BS':
            bs_sum += (r['diferenta_si'] or 0)
            if str(r['cont']).strip() == '121':
                cont121_sf = r['diferenta_sf']
            continue

        if r['tratament_special'] and 'AUTO' in r['tratament_special']:
            auto_inchis_prezente.append(r['cont'])

        n_val = r['rulaj_cumulat_mapat'] or 0
        o_val = r['rulaj_luna_mapat'] or 0
        if r['tip'] == 'Exp':
            exp_n += n_val
            exp_o += o_val
        elif r['tip'] == 'Ven':
            ven_n += n_val
            ven_o += o_val

    pl_cumulat = exp_n + ven_n
    pl_luna = exp_o + ven_o
    cont121_cumulat = cont121_sf if cont121_sf is not None else 0
    check_cumulat = pl_cumulat + cont121_cumulat

    # #121 luna = rulaj luna (Debit-Credit) al contului 121, nu diferenta_sf
    cont121_luna_val = 0
    for r in mapped_rows:
        if str(r['cont']).strip() == '121':
            cont121_luna_val = r.get('rulaj_luna_raw', 0) or 0
    check_luna = pl_luna + cont121_luna_val

    return dict(
        bs_check=bs_sum,
        pl_cumulat=pl_cumulat,
        pl_luna=pl_luna,
        cont121_cumulat=cont121_cumulat,
        cont121_luna=cont121_luna_val,
        check_cumulat=check_cumulat,
        check_luna=check_luna,
        is_balanced=abs(check_cumulat) < 1 and abs(check_luna) < 1,
        auto_inchis_prezente=auto_inchis_prezente,
    )
