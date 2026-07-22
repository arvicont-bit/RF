import os
import sys
import json
import functools
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for, session, flash,
    send_file, abort, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.db import get_conn, init_db  # noqa: E402
from app.processing import process_upload  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ.get('APP_SECRET_KEY', 'dev-secret-schimba-in-productie')

LUNI_RO = ['', 'Ianuarie', 'Februarie', 'Martie', 'Aprilie', 'Mai', 'Iunie',
           'Iulie', 'August', 'Septembrie', 'Octombrie', 'Noiembrie', 'Decembrie']

PLANURI = {
    'trial': dict(nume='Trial', pret=0),
    'basic': dict(nume='Basic', pret=15000),   # in bani (150.00 RON)
    'pro': dict(nume='Pro', pret=35000),        # 350.00 RON
}


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def current_tenant_id():
    return session.get('tenant_id')


@app.context_processor
def inject_globals():
    return dict(luni_ro=LUNI_RO, current_year=datetime.now().year, user_email=session.get('user_email'))


# ---------------------------------------------------------------- AUTH ----

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        firm_name = request.form['firm_name'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        conn = get_conn()
        existing = conn.execute('SELECT id FROM users WHERE email = ?', (email,)).fetchone()
        if existing:
            flash('Exista deja un cont cu acest email.', 'error')
            conn.close()
            return render_template('register.html')
        cur = conn.cursor()
        cur.execute('INSERT INTO tenants (name, email) VALUES (?, ?)', (firm_name, email))
        tenant_id = cur.lastrowid
        cur.execute(
            'INSERT INTO users (tenant_id, email, password_hash, role) VALUES (?, ?, ?, ?)',
            (tenant_id, email, generate_password_hash(password), 'admin'),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        session['user_id'] = user_id
        session['tenant_id'] = tenant_id
        session['user_email'] = email
        flash('Cont creat cu succes.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        conn = get_conn()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['tenant_id'] = user['tenant_id']
            session['user_email'] = user['email']
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Email sau parola incorecte.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ----------------------------------------------------------- DASHBOARD ----

@app.route('/')
@login_required
def dashboard():
    conn = get_conn()
    clients = conn.execute(
        '''SELECT cc.*, s.plan, s.status as sub_status,
                  (SELECT COUNT(*) FROM balance_uploads bu WHERE bu.client_company_id = cc.id) as nr_balante
           FROM client_companies cc
           LEFT JOIN subscriptions s ON s.client_company_id = cc.id
           WHERE cc.tenant_id = ? ORDER BY cc.name''',
        (current_tenant_id(),),
    ).fetchall()
    conn.close()
    return render_template('dashboard.html', clients=clients)


@app.route('/clients/new', methods=['GET', 'POST'])
@login_required
def new_client():
    if request.method == 'POST':
        name = request.form['name'].strip()
        cui = request.form.get('cui', '').strip()
        plan = request.form.get('plan', 'trial')
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO client_companies (tenant_id, name, cui) VALUES (?, ?, ?)',
            (current_tenant_id(), name, cui),
        )
        client_id = cur.lastrowid
        cur.execute(
            '''INSERT INTO subscriptions (client_company_id, plan, status, price_amount, currency, billing_cycle)
               VALUES (?, ?, 'active', ?, 'RON', 'monthly')''',
            (client_id, plan, PLANURI.get(plan, PLANURI['trial'])['pret']),
        )
        conn.commit()
        conn.close()
        flash(f'Firma "{name}" a fost adaugata.', 'success')
        return redirect(url_for('client_detail', client_id=client_id))
    return render_template('new_client.html', planuri=PLANURI)


def _get_client_or_404(client_id):
    conn = get_conn()
    client = conn.execute(
        'SELECT * FROM client_companies WHERE id = ? AND tenant_id = ?',
        (client_id, current_tenant_id()),
    ).fetchone()
    if client is None:
        conn.close()
        abort(404)
    return conn, client


@app.route('/clients/<int:client_id>')
@login_required
def client_detail(client_id):
    conn, client = _get_client_or_404(client_id)
    uploads = conn.execute(
        '''SELECT bu.*, rc.check_cumulat, rc.check_luna, rc.is_balanced
           FROM balance_uploads bu
           LEFT JOIN report_checks rc ON rc.balance_upload_id = bu.id
           WHERE bu.client_company_id = ? ORDER BY bu.year DESC, bu.month DESC''',
        (client_id,),
    ).fetchall()
    subscription = conn.execute(
        'SELECT * FROM subscriptions WHERE client_company_id = ?', (client_id,)
    ).fetchone()
    conn.close()
    return render_template('client_detail.html', client=client, uploads=uploads, subscription=subscription, planuri=PLANURI)


@app.route('/clients/<int:client_id>/upload', methods=['POST'])
@login_required
def upload_balance(client_id):
    conn, client = _get_client_or_404(client_id)
    year = int(request.form['year'])
    month = int(request.form['month'])
    file = request.files.get('balance_file')
    if not file or file.filename == '':
        flash('Niciun fisier selectat.', 'error')
        conn.close()
        return redirect(url_for('client_detail', client_id=client_id))

    file_bytes = file.read()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO balance_uploads
           (client_company_id, year, month, original_filename, file_blob, file_mimetype, uploaded_by, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
           ON CONFLICT(client_company_id, year, month) DO UPDATE SET
              original_filename = excluded.original_filename,
              file_blob = excluded.file_blob,
              file_mimetype = excluded.file_mimetype,
              status = 'pending', error_message = NULL, uploaded_at = datetime('now')''',
        (client_id, year, month, file.filename, file_bytes, file.mimetype, session['user_id']),
    )
    conn.commit()
    upload_id = conn.execute(
        'SELECT id FROM balance_uploads WHERE client_company_id = ? AND year = ? AND month = ?',
        (client_id, year, month),
    ).fetchone()['id']

    try:
        checks, unmapped = process_upload(conn, upload_id)
        if unmapped:
            flash(f'Balanta procesata, dar {len(unmapped)} conturi nu au fost mapate: {", ".join(unmapped[:10])}'
                  f'{"..." if len(unmapped) > 10 else ""}', 'warning')
        else:
            balanced = 'echilibrata' if checks['is_balanced'] else 'NEECHILIBRATA'
            flash(f'Balanta procesata — {balanced} (Check cumulat={checks["check_cumulat"]:.2f}, '
                  f'luna={checks["check_luna"]:.2f}).', 'success' if checks['is_balanced'] else 'warning')
    except Exception as e:
        flash(f'Eroare la procesare: {e}', 'error')
    conn.close()
    return redirect(url_for('client_detail', client_id=client_id))


@app.route('/clients/<int:client_id>/uploads/<int:upload_id>/download')
@login_required
def download_upload(client_id, upload_id):
    conn, client = _get_client_or_404(client_id)
    row = conn.execute(
        'SELECT * FROM balance_uploads WHERE id = ? AND client_company_id = ?', (upload_id, client_id)
    ).fetchone()
    conn.close()
    if row is None:
        abort(404)
    return send_file(
        io.BytesIO(row['file_blob']), download_name=row['original_filename'], as_attachment=True,
        mimetype=row['file_mimetype'] or 'application/octet-stream',
    )


@app.route('/clients/<int:client_id>/uploads/<int:upload_id>/reprocess')
@login_required
def reprocess_upload(client_id, upload_id):
    conn, client = _get_client_or_404(client_id)
    row = conn.execute(
        'SELECT * FROM balance_uploads WHERE id = ? AND client_company_id = ?', (upload_id, client_id)
    ).fetchone()
    if row is None:
        conn.close()
        abort(404)
    try:
        checks, unmapped = process_upload(conn, upload_id)
        flash('Balanta re-procesata.', 'success')
    except Exception as e:
        flash(f'Eroare la reprocesare: {e}', 'error')
    conn.close()
    return redirect(url_for('client_detail', client_id=client_id))


# ------------------------------------------------------------- RAPOARTE ----

def _get_upload_context(client_id, upload_id):
    conn, client = _get_client_or_404(client_id)
    upload = conn.execute(
        'SELECT * FROM balance_uploads WHERE id = ? AND client_company_id = ?', (upload_id, client_id)
    ).fetchone()
    if upload is None:
        conn.close()
        abort(404)
    checks = conn.execute(
        'SELECT * FROM report_checks WHERE balance_upload_id = ?', (upload_id,)
    ).fetchone()
    snapshot_row = conn.execute(
        'SELECT * FROM report_snapshots WHERE balance_upload_id = ?', (upload_id,)
    ).fetchone()
    snapshot = json.loads(snapshot_row['data_json']) if snapshot_row else None
    mapped_lines = conn.execute(
        'SELECT * FROM mapped_lines WHERE balance_upload_id = ? ORDER BY tip, cont', (upload_id,)
    ).fetchall()
    conn.close()
    return client, upload, checks, snapshot, mapped_lines


@app.route('/clients/<int:client_id>/uploads/<int:upload_id>/raport1')
@login_required
def raport1(client_id, upload_id):
    client, upload, checks, snapshot, mapped_lines = _get_upload_context(client_id, upload_id)
    pl_rows = sorted(snapshot['pl'], key=lambda r: (r['tip'], r['cod_mapare'] or '')) if snapshot else []
    bs_rows = snapshot['bs'] if snapshot else []
    return render_template(
        'raport1.html', client=client, upload=upload, checks=checks,
        pl_rows=pl_rows, bs_rows=bs_rows, mapped_lines=mapped_lines,
    )


@app.route('/clients/<int:client_id>/uploads/<int:upload_id>/raport2')
@login_required
def raport2(client_id, upload_id):
    client, upload, checks, snapshot, mapped_lines = _get_upload_context(client_id, upload_id)
    return render_template('raport2.html', client=client, upload=upload, mapped_lines=mapped_lines)


@app.route('/clients/<int:client_id>/uploads/<int:upload_id>/raport3')
@login_required
def raport3(client_id, upload_id):
    client, upload, checks, snapshot, mapped_lines = _get_upload_context(client_id, upload_id)
    return render_template('raport3.html', client=client, upload=upload, checks=checks)


@app.route('/clients/<int:client_id>/uploads/<int:upload_id>/raport3-data.json')
@login_required
def raport3_data(client_id, upload_id):
    conn, client = _get_client_or_404(client_id)
    upload = conn.execute(
        'SELECT * FROM balance_uploads WHERE id = ? AND client_company_id = ?', (upload_id, client_id)
    ).fetchone()
    if upload is None:
        conn.close()
        abort(404)
    history = conn.execute(
        '''SELECT rs.year, rs.month, rs.data_json
           FROM report_snapshots rs WHERE rs.client_company_id = ?
           ORDER BY rs.year, rs.month''',
        (client_id,),
    ).fetchall()
    conn.close()

    series = []
    for row in history:
        snap = json.loads(row['data_json'])
        venituri = sum(x['cumulat'] for x in snap['pl'] if x['tip'] == 'Ven')
        cheltuieli = sum(-x['cumulat'] for x in snap['pl'] if x['tip'] == 'Exp')
        series.append(dict(
            perioada=f"{LUNI_RO[row['month']][:3]} {row['year']}",
            venituri=round(venituri, 2), cheltuieli=round(cheltuieli, 2),
            profit=round(venituri - cheltuieli, 2),
        ))

    current_snapshot_row = conn2 = None
    conn = get_conn()
    snap_row = conn.execute('SELECT data_json FROM report_snapshots WHERE balance_upload_id = ?', (upload_id,)).fetchone()
    conn.close()
    bs_breakdown = []
    if snap_row:
        snap = json.loads(snap_row['data_json'])
        cat_totals = {}
        for line in snap['bs']:
            cat = line.get('descriere_cod') or 'Nemapat'
            cat_totals[cat] = cat_totals.get(cat, 0) + (line['sold_final'] or 0)
        bs_breakdown = [dict(categorie=k, valoare=round(v, 2)) for k, v in cat_totals.items() if abs(v) > 0.5]

    return jsonify(dict(series=series, bs_breakdown=bs_breakdown))


# ---------------------------------------------------------- SUBSCRIPTION ----

@app.route('/clients/<int:client_id>/subscription', methods=['GET', 'POST'])
@login_required
def subscription(client_id):
    conn, client = _get_client_or_404(client_id)
    if request.method == 'POST':
        plan = request.form['plan']
        conn.execute(
            '''UPDATE subscriptions SET plan = ?, price_amount = ?, updated_at = datetime('now')
               WHERE client_company_id = ?''',
            (plan, PLANURI.get(plan, PLANURI['trial'])['pret'], client_id),
        )
        conn.commit()
        flash('Abonament actualizat.', 'success')
        conn.close()
        return redirect(url_for('client_detail', client_id=client_id))
    sub = conn.execute('SELECT * FROM subscriptions WHERE client_company_id = ?', (client_id,)).fetchone()
    conn.close()
    return render_template('subscription.html', client=client, subscription=sub, planuri=PLANURI)


if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port, debug=True)
