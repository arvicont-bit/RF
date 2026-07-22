"""Pipeline: balanta bruta (bytes) -> linii brute in DB -> mapare -> checks -> snapshot universal."""
import json
from app.balance_parser import parse_balance_file
from app.mapping_engine import map_balance_lines, compute_checks


def load_chart_and_overrides(conn, client_company_id):
    chart_by_cont = {}
    for row in conn.execute('SELECT * FROM chart_accounts'):
        chart_by_cont[row['cont']] = dict(row)

    overrides_by_cont = {}
    for row in conn.execute(
        'SELECT * FROM account_mapping_overrides WHERE client_company_id = ?', (client_company_id,)
    ):
        overrides_by_cont[row['cont']] = dict(row)

    return chart_by_cont, overrides_by_cont


def process_upload(conn, upload_id):
    upload = conn.execute('SELECT * FROM balance_uploads WHERE id = ?', (upload_id,)).fetchone()
    if upload is None:
        raise ValueError('Balance upload inexistent')

    try:
        lines, warnings = parse_balance_file(upload['file_blob'], upload['original_filename'])

        conn.execute('DELETE FROM balance_lines WHERE balance_upload_id = ?', (upload_id,))
        for ln in lines:
            conn.execute(
                '''INSERT INTO balance_lines
                   (balance_upload_id, cont, denumire, si_debit, si_credit,
                    rulaj_luna_debit, rulaj_luna_credit, rulaj_cumulat_debit, rulaj_cumulat_credit,
                    sf_debit, sf_credit)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (upload_id, ln['cont'], ln['denumire'], ln['si_debit'], ln['si_credit'],
                 ln['rulaj_luna_debit'], ln['rulaj_luna_credit'],
                 ln['rulaj_cumulat_debit'], ln['rulaj_cumulat_credit'],
                 ln['sf_debit'], ln['sf_credit']),
            )

        chart_by_cont, overrides_by_cont = load_chart_and_overrides(conn, upload['client_company_id'])
        mapped_rows, unmapped = map_balance_lines(lines, chart_by_cont, overrides_by_cont)

        conn.execute('DELETE FROM mapped_lines WHERE balance_upload_id = ?', (upload_id,))
        for r in mapped_rows:
            conn.execute(
                '''INSERT INTO mapped_lines
                   (balance_upload_id, client_company_id, year, month, cont, denumire, tip,
                    cod_mapare, descriere_cod, tratament_special, diferenta_si, diferenta_sf,
                    rulaj_cumulat_mapat, rulaj_luna_mapat, sursa_mapare, match_how)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (upload_id, upload['client_company_id'], upload['year'], upload['month'],
                 r['cont'], r['denumire'], r['tip'], r['cod_mapare'], r['descriere_cod'],
                 r['tratament_special'], r['diferenta_si'], r['diferenta_sf'],
                 r['rulaj_cumulat_mapat'], r['rulaj_luna_mapat'], r['sursa_mapare'], r['match_how']),
            )

        checks = compute_checks(mapped_rows)
        conn.execute('DELETE FROM report_checks WHERE balance_upload_id = ?', (upload_id,))
        conn.execute(
            '''INSERT INTO report_checks
               (balance_upload_id, bs_check, pl_cumulat, pl_luna, cont121_cumulat, cont121_luna,
                check_cumulat, check_luna, is_balanced)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (upload_id, checks['bs_check'], checks['pl_cumulat'], checks['pl_luna'],
             checks['cont121_cumulat'], checks['cont121_luna'], checks['check_cumulat'],
             checks['check_luna'], 1 if checks['is_balanced'] else 0),
        )

        snapshot = build_universal_snapshot(mapped_rows, checks)
        conn.execute(
            'DELETE FROM report_snapshots WHERE client_company_id = ? AND year = ? AND month = ?',
            (upload['client_company_id'], upload['year'], upload['month']),
        )
        conn.execute(
            '''INSERT INTO report_snapshots (client_company_id, balance_upload_id, year, month, data_json)
               VALUES (?,?,?,?,?)''',
            (upload['client_company_id'], upload_id, upload['year'], upload['month'], json.dumps(snapshot)),
        )

        status = 'processed' if not unmapped else 'processed'
        error_message = f"Conturi nemapate: {', '.join(unmapped)}" if unmapped else None
        conn.execute(
            'UPDATE balance_uploads SET status = ?, error_message = ? WHERE id = ?',
            (status, error_message, upload_id),
        )
        conn.commit()
        return checks, unmapped

    except Exception as e:
        conn.execute(
            'UPDATE balance_uploads SET status = ?, error_message = ? WHERE id = ?',
            ('error', str(e), upload_id),
        )
        conn.commit()
        raise


def build_universal_snapshot(mapped_rows, checks):
    """Format universal: grupare pe cod_mapare -> suma rulaj_cumulat_mapat / rulaj_luna_mapat,
    plus liniile BS pentru bilant si working capital."""
    pl_by_code = {}
    bs_lines = []

    for r in mapped_rows:
        if r['tip'] == 'BS':
            bs_lines.append(dict(
                cont=r['cont'], denumire=r['denumire'], cod_mapare=r['cod_mapare'],
                descriere_cod=r['descriere_cod'], sold_final=r['diferenta_sf'],
            ))
            continue
        key = r['cod_mapare'] or f"NEMAPAT-{r['cont']}"
        if key not in pl_by_code:
            pl_by_code[key] = dict(
                cod_mapare=r['cod_mapare'], descriere_cod=r['descriere_cod'],
                tip=r['tip'], cumulat=0.0, luna=0.0,
            )
        pl_by_code[key]['cumulat'] += (r['rulaj_cumulat_mapat'] or 0)
        pl_by_code[key]['luna'] += (r['rulaj_luna_mapat'] or 0)

    return dict(
        pl=list(pl_by_code.values()),
        bs=bs_lines,
        checks=checks,
    )
