import os, json, sqlite3, uuid, shutil, re, io
from collections import defaultdict
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mahsoli-key-2025')

_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
_APP_DIR      = os.path.join(_BASE_DIR, 'mahsoli_data')
DB_FILE       = os.path.join(_APP_DIR, 'mahsoli.db')
SETTINGS_FILE = os.path.join(_APP_DIR, 'settings.json')
BACKUP_DIR    = os.path.join(_APP_DIR, 'backups')
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(os.path.join(_APP_DIR, 'reports'), exist_ok=True)

ARABIC_DAYS = ['الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد']

DEFAULT_PRODUCTS = [
    "بندورة","خيار","فليفلة","باذنجان","كوسا","خس","بقدونس","نعناع",
    "ملفوف","قرنبيط","بصل","ثوم","فراولة","بطيخ","شمام","ذرة",
    "تفاح","عنب","زيتون","برتقال","ليمون","أخرى"
]

_settings_cache = None

def load_settings(force=False):
    global _settings_cache
    if _settings_cache and not force:
        return _settings_cache
    default = {
        "farm_name": "مزرعتي",
        "sections": {
            "motez":  {"display": "معتز",  "type": "full",   "table": "motez"},
            "waleed": {"display": "وليد",  "type": "shared", "table": "waleed"}
        },
        "products": DEFAULT_PRODUCTS,
        "worker_ratio": 0.333
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                s = json.load(f)
            for k, v in default.items():
                if k not in s:
                    s[k] = v
            for key, sec in s.get('sections', {}).items():
                if 'table' not in sec:
                    safe = re.sub(r'[^a-zA-Z0-9_]', '_', sec.get('filename', key))
                    sec['table'] = safe or key
            _settings_cache = s
            return s
        except Exception:
            pass
    _settings_cache = default
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(default, f, ensure_ascii=False, indent=2)
    return default

def save_settings_file(s):
    global _settings_cache
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    _settings_cache = s

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def safe_float(v, d=0.0):
    try:
        return float(v) if v not in (None, '', 'None') else d
    except:
        return d

def arabic_day(d):
    if isinstance(d, str):
        try: d = date.fromisoformat(d)
        except: return ''
    try: return ARABIC_DAYS[d.weekday()]
    except: return ''

def ensure_col(conn, table, col, typ, default=None):
    try:
        existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in existing:
            sql = f"ALTER TABLE {table} ADD COLUMN {col} {typ}"
            if default: sql += f" DEFAULT {default}"
            conn.execute(sql)
    except: pass

def init_db():
    s = load_settings()
    conn = get_db()
    c = conn.cursor()
    for key, cfg in s['sections'].items():
        t = cfg['table']
        c.execute(f"""CREATE TABLE IF NOT EXISTS {t} (
            id TEXT PRIMARY KEY, day TEXT, date TEXT, product TEXT,
            qty REAL, unit TEXT DEFAULT 'كغ', price REAL, total REAL DEFAULT 0,
            buyer TEXT DEFAULT '', accounted TEXT DEFAULT 'باقي',
            notes TEXT DEFAULT '', created_at TEXT, season_id TEXT
        )""")
        for idx in ['date','buyer','accounted','product']:
            c.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_{idx} ON {t}({idx})")
        ensure_col(conn, t, 'season_id', 'TEXT')
    c.execute("""CREATE TABLE IF NOT EXISTS buyers (
        id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
        phone TEXT DEFAULT '', address TEXT DEFAULT '',
        category TEXT DEFAULT 'عادي', notes TEXT DEFAULT '',
        created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY, buyer TEXT NOT NULL,
        amount REAL NOT NULL, date TEXT, notes TEXT DEFAULT '',
        section TEXT DEFAULT '', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS expenses (
        id TEXT PRIMARY KEY, date TEXT, category TEXT,
        amount REAL, notes TEXT DEFAULT '', section TEXT DEFAULT '', created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS seasons (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, section_key TEXT,
        product TEXT DEFAULT 'الكل', start_date TEXT, end_date TEXT,
        status TEXT DEFAULT 'مغلق', notes TEXT DEFAULT '', created_at TEXT)""")
    conn.commit()
    conn.close()

# ═══════════════════════════════════════════
# PAGES
# ═══════════════════════════════════════════

@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', settings=load_settings(), page='dashboard')

@app.route('/sales/<section_key>')
def sales(section_key):
    s = load_settings()
    if section_key not in s['sections']:
        return redirect(url_for('dashboard'))
    return render_template('sales.html', settings=s,
                           section_key=section_key,
                           section=s['sections'][section_key],
                           page='sales_'+section_key)

@app.route('/buyers')
def buyers():
    return render_template('buyers.html', settings=load_settings(), page='buyers')

@app.route('/reports')
def reports():
    return render_template('reports.html', settings=load_settings(), page='reports')

@app.route('/settings_page')
def settings_page():
    return render_template('settings.html', settings=load_settings(), page='settings')

# ═══════════════════════════════════════════
# API — DASHBOARD
# ═══════════════════════════════════════════

@app.route('/api/dashboard')
def api_dashboard():
    s = load_settings()
    conn = get_db()
    today = date.today().isoformat()

    result = {'sections': {}, 'total': 0, 'paid': 0, 'unpaid': 0,
              'today': 0, 'recent': [], 'top_buyers': [], 'products': []}

    all_rows = []
    for key, cfg in s['sections'].items():
        t = cfg['table']
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {t} ORDER BY date DESC, created_at DESC LIMIT 500").fetchall()]
        total  = sum(r.get('total') or 0 for r in rows)
        paid   = sum(r.get('total') or 0 for r in rows if r.get('accounted') == 'محاسب')
        unpaid = total - paid
        today_s = sum(r.get('total') or 0 for r in rows if r.get('date') == today)
        result['sections'][key] = {
            'display': cfg['display'], 'total': total,
            'paid': paid, 'unpaid': unpaid, 'today': today_s, 'count': len(rows)
        }
        result['total']  += total
        result['paid']   += paid
        result['unpaid'] += unpaid
        result['today']  += today_s
        all_rows.extend(rows)

    all_rows.sort(key=lambda x: (x.get('date',''), x.get('created_at','')), reverse=True)
    result['recent'] = all_rows[:8]

    # ديون المشترين
    debt_map = defaultdict(float)
    for key, cfg in s['sections'].items():
        for r in conn.execute(f"SELECT buyer, SUM(total) s FROM {cfg['table']} WHERE accounted!='محاسب' AND buyer!='' GROUP BY buyer").fetchall():
            debt_map[r['buyer']] += r['s'] or 0
    result['top_buyers'] = sorted(
        [{'name': k, 'debt': v} for k, v in debt_map.items()],
        key=lambda x: -x['debt'])[:6]

    # أكثر المحاصيل
    pmap = defaultdict(float)
    for r in all_rows:
        if r.get('product'): pmap[r['product']] += r.get('total') or 0
    result['products'] = sorted([{'name': k, 'total': v} for k, v in pmap.items()], key=lambda x: -x['total'])[:8]

    conn.close()
    return jsonify(result)

# ═══════════════════════════════════════════
# API — SALES
# ═══════════════════════════════════════════

@app.route('/api/sales/<section_key>', methods=['GET'])
def api_get_sales(section_key):
    s = load_settings()
    if section_key not in s['sections']:
        return jsonify({'error': 'قسم غير موجود'}), 404
    t = s['sections'][section_key]['table']
    conn = get_db()

    q, params = f"SELECT * FROM {t} WHERE 1=1", []
    for field, col in [('buyer','buyer'),('product','product'),('accounted','accounted')]:
        v = request.args.get(field,'')
        if v: q += f" AND {col}=?"; params.append(v)
    for field, op, col in [('date_from','>=','date'),('date_to','<=','date')]:
        v = request.args.get(field,'')
        if v: q += f" AND {col}{op}?"; params.append(v)
    q += " ORDER BY date DESC, created_at DESC LIMIT 1000"

    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    total = sum(r.get('total') or 0 for r in rows)
    paid  = sum(r.get('total') or 0 for r in rows if r.get('accounted') == 'محاسب')
    conn.close()
    return jsonify({'rows': rows, 'total': total, 'paid': paid, 'unpaid': total - paid})

@app.route('/api/sales/<section_key>', methods=['POST'])
def api_add_sale(section_key):
    s = load_settings()
    if section_key not in s['sections']:
        return jsonify({'error': 'قسم غير موجود'}), 404
    t = s['sections'][section_key]['table']
    d = request.get_json(force=True)

    if not d.get('product') or not d.get('qty'):
        return jsonify({'error': 'المحصول والكمية مطلوبان'}), 400

    date_str = d.get('date') or date.today().isoformat()
    qty   = safe_float(d.get('qty'))
    price = safe_float(d.get('price')) if d.get('price') not in (None, '', '0', 0) else None
    total = qty * (price or 0)
    rid   = str(uuid.uuid4())

    conn = get_db()
    conn.execute(f"""INSERT INTO {t}
        (id, day, date, product, qty, unit, price, total, buyer, accounted, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rid, arabic_day(date_str), date_str,
         d.get('product',''), qty, d.get('unit','كغ') or 'كغ',
         price, total,
         d.get('buyer','') or '', d.get('accounted','باقي') or 'باقي',
         d.get('notes','') or '', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': rid, 'total': total, 'day': arabic_day(date_str)})

@app.route('/api/sales/<section_key>/<row_id>', methods=['PUT'])
def api_update_sale(section_key, row_id):
    s = load_settings()
    if section_key not in s['sections']:
        return jsonify({'error': 'قسم غير موجود'}), 404
    t  = s['sections'][section_key]['table']
    d  = request.get_json(force=True)

    date_str = d.get('date') or date.today().isoformat()
    qty   = safe_float(d.get('qty'))
    price = safe_float(d.get('price')) if d.get('price') not in (None, '', '0', 0) else None
    total = qty * (price or 0)

    conn = get_db()
    conn.execute(f"""UPDATE {t} SET
        day=?, date=?, product=?, qty=?, unit=?, price=?, total=?,
        buyer=?, accounted=?, notes=? WHERE id=?""",
        (arabic_day(date_str), date_str, d.get('product',''), qty,
         d.get('unit','كغ') or 'كغ', price, total,
         d.get('buyer','') or '', d.get('accounted','باقي') or 'باقي',
         d.get('notes','') or '', row_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'total': total})

@app.route('/api/sales/<section_key>/<row_id>', methods=['DELETE'])
def api_delete_sale(section_key, row_id):
    s = load_settings()
    if section_key not in s['sections']:
        return jsonify({'error': 'قسم غير موجود'}), 404
    t = s['sections'][section_key]['table']
    conn = get_db()
    conn.execute(f"DELETE FROM {t} WHERE id=?", (row_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ═══════════════════════════════════════════
# API — BUYERS
# ═══════════════════════════════════════════

@app.route('/api/buyers', methods=['GET'])
def api_get_buyers():
    s = load_settings()
    conn = get_db()
    buyers = [dict(b) for b in conn.execute("SELECT * FROM buyers ORDER BY name").fetchall()]
    for b in buyers:
        debt = 0
        for cfg in s['sections'].values():
            r = conn.execute(f"SELECT SUM(total) FROM {cfg['table']} WHERE buyer=? AND accounted!='محاسب'",
                             (b['name'],)).fetchone()
            debt += r[0] or 0
        b['debt'] = debt
    conn.close()
    return jsonify(buyers)

@app.route('/api/buyers', methods=['POST'])
def api_add_buyer():
    d = request.get_json(force=True)
    name = (d.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'الاسم مطلوب'}), 400
    conn = get_db()
    try:
        bid = str(uuid.uuid4())
        conn.execute("""INSERT INTO buyers (id,name,phone,address,category,notes,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (bid, name, d.get('phone','') or '', d.get('address','') or '',
             d.get('category','عادي') or 'عادي', d.get('notes','') or '',
             datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': bid})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'اسم المشتري موجود مسبقاً'}), 400

@app.route('/api/buyers/<name>', methods=['PUT'])
def api_update_buyer(name):
    d = request.get_json(force=True)
    conn = get_db()
    conn.execute("UPDATE buyers SET phone=?,address=?,category=?,notes=? WHERE name=?",
        (d.get('phone',''), d.get('address',''), d.get('category','عادي'), d.get('notes',''), name))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/buyers/<name>/mark_paid', methods=['POST'])
def api_mark_paid(name):
    s = load_settings()
    conn = get_db()
    for cfg in s['sections'].values():
        conn.execute(f"UPDATE {cfg['table']} SET accounted='محاسب' WHERE buyer=? AND accounted!='محاسب'", (name,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/buyers/<name>/invoice')
def api_buyer_invoice(name):
    s = load_settings()
    date_from = request.args.get('from','')
    date_to   = request.args.get('to','')
    conn = get_db()
    all_rows = []
    for key, cfg in s['sections'].items():
        t = cfg['table']
        q = f"SELECT *, '{cfg['display']}' as section_name FROM {t} WHERE buyer=?"
        params = [name]
        if date_from: q += " AND date>=?"; params.append(date_from)
        if date_to:   q += " AND date<=?"; params.append(date_to)
        q += " ORDER BY date"
        all_rows.extend([dict(r) for r in conn.execute(q, params).fetchall()])
    conn.close()
    total = sum(r.get('total') or 0 for r in all_rows)
    paid  = sum(r.get('total') or 0 for r in all_rows if r.get('accounted') == 'محاسب')
    return _make_invoice_html(name, all_rows, total, paid, total-paid, date_from, date_to, s)

def _make_invoice_html(buyer, rows, total, paid, unpaid, fd, td, settings):
    farm = settings.get('farm_name', 'مزرعتي')
    fd_s = fd or (rows[0]['date'] if rows else '—')
    td_s = td or (rows[-1]['date'] if rows else '—')
    rows_html = ''.join(f"""<tr class="{'r-paid' if r.get('accounted')=='محاسب' else 'r-unpaid'}">
      <td>{i}</td><td>{r.get('date','')}</td><td>{r.get('day','')}</td>
      <td>{r.get('product','')}</td><td>{r.get('qty',0)}</td><td>{r.get('unit','')}</td>
      <td>{f"{r['price']:.2f}" if r.get('price') else '—'}</td>
      <td><b>{(r.get('total') or 0):,.2f} ₪</b></td>
      <td><span class="{'bp' if r.get('accounted')=='محاسب' else 'bu'}">{r.get('accounted','')}</span></td>
    </tr>""" for i, r in enumerate(rows, 1))
    return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>فاتورة — {buyer}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:Tahoma,sans-serif;background:#f4f4f4;direction:rtl;color:#111}}
.inv{{max-width:900px;margin:20px auto;background:#fff;box-shadow:0 2px 20px rgba(0,0,0,.08);border-radius:4px;overflow:hidden}}
.hdr{{background:#111;color:#fff;padding:28px 32px;display:flex;justify-content:space-between;align-items:center}}
.hdr h1{{font-size:22px;font-weight:800;letter-spacing:-0.5px}}
.hdr .sub{{color:#888;font-size:13px;margin-top:4px}}
.hdr .logo{{font-size:32px}}
.meta{{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:2px solid #111}}
.mc{{padding:16px 20px;border-left:1px solid #eee}}
.mc:last-child{{border-left:none}}
.ml{{font-size:10px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px}}
.mv{{font-size:15px;font-weight:700}}
table{{width:100%;border-collapse:collapse}}
thead{{background:#111}}
th{{padding:10px 12px;color:#fff;font-size:11px;font-weight:700;text-align:center}}
td{{padding:9px 12px;font-size:13px;text-align:center;border-bottom:1px solid #f0f0f0}}
.r-paid{{background:#f0fdf4}}.r-unpaid{{background:#fff8f8}}
.bp{{background:#d1fae5;color:#065f46;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700}}
.bu{{background:#fee2e2;color:#991b1b;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:700}}
.tots{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;padding:24px;background:#fafafa}}
.tc{{background:#fff;border:1px solid #eee;border-radius:4px;padding:16px;text-align:center}}
.tl{{font-size:11px;color:#888;font-weight:700;text-transform:uppercase;margin-bottom:6px}}
.tv{{font-size:24px;font-weight:900}}
.tv.dark{{color:#111}}.tv.green{{color:#15803d}}.tv.red{{color:#dc2626}}
.ftr{{background:#111;color:#555;text-align:center;padding:14px;font-size:12px}}
.ftr b{{color:#aaa}}
.pbtn{{background:#111;color:#fff;border:none;padding:10px 24px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:700;margin:16px;display:inline-block}}
@media print{{.pbtn{{display:none}}.inv{{box-shadow:none;margin:0}}
  thead{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  .hdr{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
@media(max-width:600px){{.meta{{grid-template-columns:1fr 1fr}}.tots{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="inv">
  <div class="hdr">
    <div><h1>فاتورة مشتري</h1><div class="sub">{farm} · نظام محصولي</div></div>
    <div class="logo">🌿</div>
  </div>
  <div class="meta">
    <div class="mc"><div class="ml">المشتري</div><div class="mv">{buyer}</div></div>
    <div class="mc"><div class="ml">من تاريخ</div><div class="mv">{fd_s}</div></div>
    <div class="mc"><div class="ml">إلى تاريخ</div><div class="mv">{td_s}</div></div>
    <div class="mc"><div class="ml">عدد السجلات</div><div class="mv">{len(rows)}</div></div>
  </div>
  <button class="pbtn" onclick="window.print()">طباعة / PDF</button>
  <table><thead><tr>
    <th>#</th><th>التاريخ</th><th>اليوم</th><th>المحصول</th>
    <th>الكمية</th><th>الوحدة</th><th>السعر</th><th>المجموع</th><th>الحالة</th>
  </tr></thead><tbody>{rows_html}</tbody></table>
  <div class="tots">
    <div class="tc"><div class="tl">إجمالي الفاتورة</div><div class="tv dark">{total:,.2f} ₪</div></div>
    <div class="tc"><div class="tl">المبلغ المحصّل</div><div class="tv green">{paid:,.2f} ₪</div></div>
    <div class="tc"><div class="tl">المبلغ المتبقي</div><div class="tv {'red' if unpaid>0 else 'green'}">{unpaid:,.2f} ₪</div></div>
  </div>
  <div class="ftr"><b>🌿 نظام محصولي</b> · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div></body></html>"""

# ═══════════════════════════════════════════
# API — PAYMENTS
# ═══════════════════════════════════════════

@app.route('/api/payments', methods=['GET'])
def api_get_payments():
    buyer = request.args.get('buyer','')
    conn = get_db()
    q, p = "SELECT * FROM payments WHERE 1=1", []
    if buyer: q += " AND buyer=?"; p.append(buyer)
    rows = [dict(r) for r in conn.execute(q+' ORDER BY date DESC', p).fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/payments', methods=['POST'])
def api_add_payment():
    d = request.get_json(force=True)
    if not d.get('buyer') or not d.get('amount'):
        return jsonify({'error': 'البيانات ناقصة'}), 400
    conn = get_db()
    pid = str(uuid.uuid4())
    conn.execute("INSERT INTO payments (id,buyer,amount,date,notes,section,created_at) VALUES(?,?,?,?,?,?,?)",
        (pid, d['buyer'], safe_float(d['amount']),
         d.get('date') or date.today().isoformat(),
         d.get('notes',''), d.get('section',''), datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'id': pid})

# ═══════════════════════════════════════════
# API — REPORTS & EXPORT
# ═══════════════════════════════════════════

@app.route('/api/report')
def api_report():
    s = load_settings()
    section_key = request.args.get('section','')
    date_from   = request.args.get('from','')
    date_to     = request.args.get('to','')
    buyer       = request.args.get('buyer','')
    product     = request.args.get('product','')

    conn = get_db()
    all_rows = []
    for key, cfg in s['sections'].items():
        if section_key and key != section_key: continue
        t = cfg['table']
        q, p = f"SELECT *, '{cfg['display']}' as section_name FROM {t} WHERE 1=1", []
        if date_from: q += " AND date>=?"; p.append(date_from)
        if date_to:   q += " AND date<=?"; p.append(date_to)
        if buyer:     q += " AND buyer=?"; p.append(buyer)
        if product:   q += " AND product=?"; p.append(product)
        all_rows.extend([dict(r) for r in conn.execute(q, p).fetchall()])
    conn.close()

    all_rows.sort(key=lambda x: x.get('date',''), reverse=True)
    total = sum(r.get('total') or 0 for r in all_rows)
    paid  = sum(r.get('total') or 0 for r in all_rows if r.get('accounted') == 'محاسب')

    by_product = defaultdict(lambda: {'qty': 0, 'total': 0})
    by_buyer   = defaultdict(lambda: {'total': 0, 'unpaid': 0})
    by_date    = defaultdict(float)
    for r in all_rows:
        if r.get('product'):
            by_product[r['product']]['qty']   += r.get('qty') or 0
            by_product[r['product']]['total'] += r.get('total') or 0
        if r.get('buyer'):
            by_buyer[r['buyer']]['total'] += r.get('total') or 0
            if r.get('accounted') != 'محاسب':
                by_buyer[r['buyer']]['unpaid'] += r.get('total') or 0
        if r.get('date'):
            by_date[r['date']] += r.get('total') or 0

    return jsonify({
        'rows': all_rows[:500], 'total': total, 'paid': paid,
        'unpaid': total - paid, 'count': len(all_rows),
        'by_product': sorted([{'name': k, **v} for k,v in by_product.items()], key=lambda x: -x['total']),
        'by_buyer':   sorted([{'name': k, **v} for k,v in by_buyer.items()],   key=lambda x: -x['total'])[:10],
        'by_date':    [{'date': k, 'total': v} for k,v in sorted(by_date.items())[-30:]]
    })

@app.route('/api/export/excel')
def api_export_excel():
    try:
        import openpyxl
        from openpyxl.styles import PatternFill, Font, Alignment
    except ImportError:
        return "openpyxl غير متوفر", 500

    s = load_settings()
    section_key = request.args.get('section','')
    date_from   = request.args.get('from','')
    date_to     = request.args.get('to','')
    conn = get_db()

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    hfill = PatternFill("solid", fgColor="111111")
    hfont = Font(bold=True, color="FFFFFF", name='Arial', size=11)
    ctr   = Alignment(horizontal='center', vertical='center')

    for key, cfg in s['sections'].items():
        if section_key and key != section_key: continue
        t = cfg['table']
        q, p = f"SELECT * FROM {t} WHERE 1=1", []
        if date_from: q += " AND date>=?"; p.append(date_from)
        if date_to:   q += " AND date<=?"; p.append(date_to)
        rows = [dict(r) for r in conn.execute(q+' ORDER BY date DESC', p).fetchall()]

        ws = wb.create_sheet(title=cfg['display'])
        ws.sheet_view.rightToLeft = True
        headers = ['التاريخ','اليوم','المحصول','الكمية','الوحدة','السعر','المجموع','المشتري','الحالة','ملاحظات']
        for i, h in enumerate(headers, 1):
            cell = ws.cell(1, i, h)
            cell.fill = hfill; cell.font = hfont; cell.alignment = ctr
        ws.row_dimensions[1].height = 22

        for r in rows:
            ws.append([r.get('date',''), r.get('day',''), r.get('product',''),
                       r.get('qty') or 0, r.get('unit',''), r.get('price') or '',
                       r.get('total') or 0, r.get('buyer',''),
                       r.get('accounted',''), r.get('notes','')])

        total = sum(r.get('total') or 0 for r in rows)
        paid  = sum(r.get('total') or 0 for r in rows if r.get('accounted') == 'محاسب')
        lr = ws.max_row + 2
        for row_data in [('الإجمالي', total, '000000'), ('المحصّل', paid, '15803d'), ('المتبقي', total-paid, 'dc2626')]:
            ws.cell(lr, 1, row_data[0]).font = Font(bold=True, name='Arial')
            c = ws.cell(lr, 7, row_data[1])
            c.font = Font(bold=True, color=row_data[2], name='Arial')
            lr += 1

        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 15

    conn.close()
    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f"محصولي_{date.today().isoformat()}.xlsx",
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ═══════════════════════════════════════════
# API — SETTINGS & MISC
# ═══════════════════════════════════════════

@app.route('/api/settings', methods=['GET'])
def api_get_settings():
    return jsonify(load_settings())

@app.route('/api/settings', methods=['POST'])
def api_save_settings():
    d = request.get_json(force=True)
    s = load_settings()
    if 'farm_name' in d: s['farm_name'] = d['farm_name']
    if 'products'  in d: s['products']  = d['products']
    if 'worker_ratio' in d: s['worker_ratio'] = float(d['worker_ratio'])
    save_settings_file(s)
    init_db()
    return jsonify({'success': True})

@app.route('/api/backup', methods=['POST'])
def api_backup():
    try:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        dest  = os.path.join(BACKUP_DIR, f"backup_{stamp}.db")
        shutil.copy2(DB_FILE, dest)
        backups = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith('.db'))
        for old in backups[:-10]:
            try: os.remove(os.path.join(BACKUP_DIR, old))
            except: pass
        return jsonify({'success': True, 'file': f"backup_{stamp}.db"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/whatsapp/<buyer_name>')
def api_whatsapp(buyer_name):
    import urllib.parse
    s = load_settings()
    conn = get_db()
    b    = conn.execute("SELECT phone FROM buyers WHERE name=?", (buyer_name,)).fetchone()
    debt = 0
    for cfg in s['sections'].values():
        r = conn.execute(f"SELECT SUM(total) FROM {cfg['table']} WHERE buyer=? AND accounted!='محاسب'",
                         (buyer_name,)).fetchone()
        debt += r[0] or 0
    conn.close()
    phone = re.sub(r'[^0-9]', '', (b['phone'] if b and b['phone'] else '') or '')
    if phone.startswith('0'): phone = '970' + phone[1:]
    msg  = f"السلام عليكم {buyer_name}\nرصيدك المتبقي: {debt:,.0f} ₪\nنرجو التسوية في أقرب وقت.\nشكراً — {s.get('farm_name','مزرعتي')}"
    enc  = urllib.parse.quote(msg, safe='')
    url  = f"https://wa.me/{phone}?text={enc}" if phone else f"https://wa.me/?text={enc}"
    return jsonify({'url': url, 'debt': debt})

@app.route('/api/db_stats')
def api_db_stats():
    s = load_settings()
    conn = get_db()
    stats, total = {}, 0
    for key, cfg in s['sections'].items():
        cnt = conn.execute(f"SELECT COUNT(*) FROM {cfg['table']}").fetchone()[0]
        stats[key] = cnt; total += cnt
    conn.close()
    db_kb = round(os.path.getsize(DB_FILE) / 1024, 1) if os.path.exists(DB_FILE) else 0
    bkps  = len([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')])
    return jsonify({'sections': stats, 'total': total, 'db_size_kb': db_kb, 'backups': bkps})

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
