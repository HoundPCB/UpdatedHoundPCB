import os
import re
import pandas as pd
import hashlib
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import func, text

app = Flask(__name__, template_folder='templates')
app.secret_key = "pcb_support_ultimate_2026_key"

basedir = os.path.abspath(os.path.dirname(__file__))

# --- DATABASE CONFIGURATION ---
# We must set a default URI even when using binds
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'settings.db')
app.config['SQLALCHEMY_BINDS'] = {
    'calls':    'sqlite:///' + os.path.join(basedir, 'calls.db'),
    'settings': 'sqlite:///' + os.path.join(basedir, 'settings.db')
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class SupportCall(db.Model):
    __tablename__ = 'support_call'
    __bind_key__ = 'calls'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20)) 
    time_start = db.Column(db.String(20))
    time_end = db.Column(db.String(20))
    duration = db.Column(db.String(20))
    call_reason = db.Column(db.String(50))
    service = db.Column(db.String(50))
    issue = db.Column(db.String(50))
    diag = db.Column(db.String(50))
    solution = db.Column(db.String(50))
    customer = db.Column(db.String(200), nullable=False)
    town = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    call_details = db.Column(db.Text)
    tech = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    unique_hash = db.Column(db.String(64), unique=True)

class Setting(db.Model):
    __bind_key__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50)) 
    value = db.Column(db.String(100))

def normalize_phone(phone: str) -> str | None:
    digits = re.sub(r'\D', '', (phone or ''))
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
    return None


def ensure_calls_phone_column():
    engine = db.get_engine(bind='calls')
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info('support_call')"))
        columns = [row[1] for row in result]
        if 'phone' not in columns:
            conn.execute(text('ALTER TABLE support_call ADD COLUMN phone VARCHAR(20)'))

with app.app_context():
    db.create_all()
    ensure_calls_phone_column()

# --- ROUTES ---

@app.route('/')
def entry_view():
    cats = ['tech', 'town', 'reason', 'service', 'issue', 'diag', 'solution']
    context = {f"{c}s": Setting.query.filter_by(category=c).order_by(Setting.value).all() for c in cats}
    return render_template('entry.html', **context)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        tech = request.form.get('tech')
        if tech:
            session['tech'] = tech
            return redirect(url_for('history_view'))
    techs = [t.value for t in Setting.query.filter_by(category='tech').order_by(Setting.value).all()]
    return render_template('login.html', techs=techs)

@app.route('/api/customer_history')
def api_customer_history():
    name = request.args.get('name', '').strip()
    if not name or len(name) < 2: return jsonify([])
    calls = SupportCall.query.filter(SupportCall.customer.ilike(f"%{name}%")).order_by(SupportCall.timestamp.desc()).limit(10).all()
    return jsonify([{
        'id': c.id, 'date': c.date, 'issue': c.issue, 'tech': c.tech, 'customer': c.customer,
        'diag': c.diag, 'solution': c.solution, 'details': c.call_details,
        'call_reason': c.call_reason, 'service': c.service, 'duration': c.duration, 'town': c.town,
        'phone': c.phone
    } for c in calls])

@app.route('/add', methods=['POST'])
def add_call():
    s, e = request.form.get('time_start', '00:00'), request.form.get('time_end', '00:00')
    cust, dt, det = request.form.get('customer'), request.form.get('date'), request.form.get('call_details', '')
    raw_phone = request.form.get('phone', '')
    phone = normalize_phone(raw_phone)
    if not phone:
        return redirect(url_for('entry_view'))
    hash_str = f"{dt}|{cust}|{det}|{phone}".encode('utf-8')
    u_hash = hashlib.md5(hash_str).hexdigest()
    try:
        db.session.add(SupportCall(
            date=dt, time_start=s, time_end=e, duration=request.form.get('duration'),
            call_reason=request.form.get('call_reason'), service=request.form.get('service'),
            issue=request.form.get('issue'), diag=request.form.get('diag'),
            solution=request.form.get('solution'), customer=cust,
            town=request.form.get('town'), phone=phone, call_details=det,
            tech=request.form.get('tech'), unique_hash=u_hash
        ))
        db.session.commit()
        return render_template('success.html',
                             customer=cust,
                             date=dt,
                             duration=request.form.get('duration'),
                             issue=request.form.get('issue'),
                             tech=request.form.get('tech'))
    except:
        db.session.rollback()
        return redirect(url_for('entry_view'))

@app.route('/history')
def history_view():
    if not session.get('tech'):
        return redirect(url_for('login'))
    tech_settings = Setting.query.filter_by(category='tech').order_by(Setting.value).all()
    f_tech = request.args.get('f_tech', '')
    f_start = request.args.get('f_start', '')
    f_end = request.args.get('f_end', '')
    f_query = request.args.get('f_query', '').strip()
    selected_id = request.args.get('call_id')
    
    query = SupportCall.query
    if f_tech:
        query = query.filter(SupportCall.tech == f_tech)
    if f_query:
        digits = re.sub(r'\D', '', f_query)
        phone_expr = func.replace(
            func.replace(
                func.replace(
                    func.replace(
                        func.replace(SupportCall.phone, '(', ''),
                    ')', ''),
                ' ', ''),
            '-', ''),
        '.', '')
        if digits:
            query = query.filter(
                (SupportCall.customer.ilike(f"%{f_query}%")) |
                (phone_expr.ilike(f"%{digits}%"))
            )
        else:
            query = query.filter(SupportCall.customer.ilike(f"%{f_query}%"))
    if f_start:
        query = query.filter(SupportCall.date >= f_start)
    if f_end:
        query = query.filter(SupportCall.date <= f_end)
    
    calls = query.order_by(SupportCall.date.desc(), SupportCall.time_start.desc()).all()
    selected_call = SupportCall.query.get(selected_id) if selected_id else (calls[0] if calls else None)
    
    return render_template('history.html', 
                           calls=calls, 
                           selected_call=selected_call, 
                           techs=[t.value for t in tech_settings], 
                           filters={'tech': f_tech, 'start': f_start, 'end': f_end, 'query': f_query})

@app.route('/update_call/<int:call_id>', methods=['POST'])
def update_call(call_id):
    call = SupportCall.query.get(call_id)
    tech = session.get('tech')
    if call and tech:
        new_date = request.form.get('date')
        if new_date:
            call.date = new_date
        new_time_start = request.form.get('time_start')
        if new_time_start:
            call.time_start = new_time_start
        new_time_end = request.form.get('time_end')
        if new_time_end:
            call.time_end = new_time_end
        new_duration = request.form.get('duration')
        if new_duration:
            call.duration = new_duration
        new_customer = request.form.get('customer')
        if new_customer:
            call.customer = new_customer
        new_phone = request.form.get('phone')
        if new_phone is not None:
            normalized = normalize_phone(new_phone)
            call.phone = normalized if normalized else new_phone
        new_town = request.form.get('town')
        if new_town:
            call.town = new_town
        new_reason = request.form.get('call_reason')
        if new_reason:
            call.call_reason = new_reason
        new_service = request.form.get('service')
        if new_service:
            call.service = new_service
        new_issue = request.form.get('issue')
        if new_issue:
            call.issue = new_issue
        new_diag = request.form.get('diag')
        if new_diag:
            call.diag = new_diag
        new_solution = request.form.get('solution')
        if new_solution:
            call.solution = new_solution
        new_details = request.form.get('call_details')
        if new_details:
            timestamp = (datetime.now() - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M:%S')
            call.call_details += f"\n\n--- {tech} added on {timestamp} ---\n{new_details}"
        db.session.commit()
    return redirect(url_for('history_view', call_id=call_id, **request.args))

@app.route('/settings', methods=['GET', 'POST'])
def settings_view():
    if request.method == 'POST':
        cat, bulk = request.form.get('category'), request.form.get('bulk_value')
        if cat and bulk:
            for item in [i.strip() for i in bulk.split('\n') if i.strip()]:
                if not Setting.query.filter_by(category=cat, value=item).first():
                    db.session.add(Setting(category=cat, value=item))
            db.session.commit()
    return render_template('settings.html', settings=Setting.query.order_by(Setting.category, Setting.value).all())

@app.route('/delete_setting/<int:id>')
def delete_setting(id):
    item = Setting.query.get(id)
    if item: db.session.delete(item)
    db.session.commit()
    return redirect(url_for('settings_view'))

@app.route('/import', methods=['POST'])
def import_csv():
    file = request.files.get('file')
    if file:
        path = os.path.join(basedir, 'temp_import.csv')
        file.save(path)
        df = pd.read_csv(path, skiprows=[0], header=0)
        session['import_file'], session['active_tech_import'] = path, request.form.get('active_tech', 'Importer')
        
        fields = [('date','Date'),('time_start','Start Time'),('time_end','End Time'),
                 ('duration','Duration'),('customer','Customer Name'),('town','Town'),('phone','Phone'),
                 ('call_reason','Reason'),('service','Service'),('issue','Issue'),
                 ('diag','Diagnosis'),('solution','Solution'),('call_details','Notes'),('tech','Tech')]
        return render_template('import_mapper.html', headers=df.columns.tolist(), fields=fields)
    return redirect(url_for('settings_view'))

@app.route('/execute_import', methods=['POST'])
def execute_import():
    path, active_tech = session.get('import_file'), session.get('active_tech_import', 'Importer')
    if not path: return redirect(url_for('settings_view'))
    mapping, df = request.form, pd.read_csv(path, skiprows=[0], header=0)
    for _, row in df.iterrows():
        try:
            def gv(k):
                c = mapping.get(k)
                return str(row[c]).strip() if c and c in df.columns and pd.notna(row[c]) else ""
            cust, raw_dt, det = gv('customer'), gv('date'), gv('call_details')
            if not cust: continue
            try: clean_dt = pd.to_datetime(raw_dt).strftime('%Y-%m-%d')
            except: clean_dt = raw_dt
            final_tech = gv('tech') if gv('tech') else active_tech
            h = hashlib.md5(f"{clean_dt}|{cust}|{det}".encode('utf-8')).hexdigest()
            if not SupportCall.query.filter_by(unique_hash=h).first():
                db.session.add(SupportCall(date=clean_dt, time_start=gv('time_start'), time_end=gv('time_end'), duration=gv('duration'), call_reason=gv('call_reason'), service=gv('service'), issue=gv('issue'), diag=gv('diag'), solution=gv('solution'), customer=cust, town=gv('town'), phone=normalize_phone(gv('phone')), call_details=det, tech=final_tech, unique_hash=h))
        except: continue
    db.session.commit()
    if os.path.exists(path): os.remove(path)
    return redirect(url_for('history_view'))

if __name__ == '__main__':
    print("--- Server running at http://localhost:8080 ---")
    app.run(host='0.0.0.0', port=8080, debug=True)
