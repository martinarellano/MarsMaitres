#!/usr/bin/env python3
"""Backend local de desarrollo para MarsMaitre.

Usa SQLite y sirve el prototipo web. Es una base de integración, no un servidor
para producción: antes de publicar requiere HTTPS, autenticación real, hash de
contraseñas, sesiones, control de acceso y secretos fuera del código.
"""
import json, sqlite3, uuid, hashlib, hmac, secrets, os, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from cryptography.fernet import Fernet
from mercadopago import MercadoPago, MercadoPagoError
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = Path(__file__).resolve().parent
WEB = ROOT.parent / "marsmaitre-web"
DB = Path(os.environ.get('MARSMAITRE_DB_PATH', str(ROOT.parent / 'marsmaitre.db')))
ADMIN_EMAIL = os.environ.get('MARSMAITRE_ADMIN_EMAIL','maartiinaaree.96@gmail.com')
ADMIN_PASSWORD = os.environ.get('MARSMAITRE_ADMIN_PASSWORD','')
ENVIRONMENT = os.environ.get('ENVIRONMENT','development')
DEMO_ADMIN_PASSWORD = "MarsMaitreDemo2026!"  # solo fallback local; cambiar antes de producción


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
    return salt + '$' + digest


def verify_password(password, stored):
    try:
        salt, digest = stored.split('$', 1)
        check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 120000).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        return False


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = connect()
    db.executescript('''
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS users (
      id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, role TEXT NOT NULL,
      name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
      password_hash TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS restaurants (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, city TEXT, phone TEXT,
      plan TEXT NOT NULL DEFAULT 'Inicio', status TEXT NOT NULL DEFAULT 'Prueba',
      users_count INTEGER NOT NULL DEFAULT 1, minutes_used INTEGER NOT NULL DEFAULT 0,
      minutes_limit INTEGER NOT NULL DEFAULT 150, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS memberships (
      user_id TEXT NOT NULL, restaurant_id TEXT NOT NULL, role TEXT NOT NULL,
      PRIMARY KEY(user_id, restaurant_id), FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS subscriptions (
      id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, plan TEXT NOT NULL,
      price_mxn INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'trial',
      trial_ends TEXT, next_billing TEXT, FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS calls (
      id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, result TEXT NOT NULL,
      duration_min INTEGER NOT NULL DEFAULT 0, confidence TEXT NOT NULL DEFAULT '0%',
      created_at TEXT NOT NULL, provider_call_id TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'completed', from_number TEXT NOT NULL DEFAULT '',
      to_number TEXT NOT NULL DEFAULT '', transcript TEXT NOT NULL DEFAULT '',
      FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS call_reviews (
      id TEXT PRIMARY KEY, call_id TEXT NOT NULL UNIQUE, recording_url TEXT NOT NULL DEFAULT '',
      transcript TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', score REAL,
      improvements TEXT NOT NULL DEFAULT '', consented INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL, FOREIGN KEY(call_id) REFERENCES calls(id)
    );
    CREATE TABLE IF NOT EXISTS restaurant_settings (
      restaurant_id TEXT PRIMARY KEY, greeting TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
      address TEXT NOT NULL DEFAULT '', timezone TEXT NOT NULL DEFAULT 'America/Mexico_City',
      opening_hours TEXT NOT NULL DEFAULT '', language TEXT NOT NULL DEFAULT 'es-MX',
      allergen_policy TEXT NOT NULL DEFAULT '', calendar_id TEXT NOT NULL DEFAULT '',
      calendar_connected INTEGER NOT NULL DEFAULT 0, phone_carrier TEXT NOT NULL DEFAULT '',
      voice_provider TEXT NOT NULL DEFAULT '', forwarding_number TEXT NOT NULL DEFAULT '',
      voice_status TEXT NOT NULL DEFAULT 'not_configured', FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS menu_items (
      id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
      name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price_mxn REAL NOT NULL DEFAULT 0,
      ingredients TEXT NOT NULL DEFAULT '', allergens TEXT NOT NULL DEFAULT '', available INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS reservations (
      id TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, customer_name TEXT NOT NULL,
      customer_phone TEXT NOT NULL DEFAULT '', start_at TEXT NOT NULL, party_size INTEGER NOT NULL DEFAULT 2,
      status TEXT NOT NULL DEFAULT 'pending', notes TEXT NOT NULL DEFAULT '', calendar_event_id TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS calendar_connections (
      restaurant_id TEXT PRIMARY KEY, provider TEXT NOT NULL DEFAULT 'google_calendar',
      calendar_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'not_connected',
      connected_at TEXT NOT NULL DEFAULT '', last_sync_at TEXT NOT NULL DEFAULT '',
      refresh_token_ciphertext TEXT NOT NULL DEFAULT '', FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS oauth_states (
      state TEXT PRIMARY KEY, restaurant_id TEXT NOT NULL, expires_at TEXT NOT NULL,
      used INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(restaurant_id) REFERENCES restaurants(id)
    );
    CREATE TABLE IF NOT EXISTS sessions (
      token TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    );
    ''')
    setting_columns = {r[1] for r in db.execute('PRAGMA table_info(restaurant_settings)').fetchall()}
    if 'calendar_id' not in setting_columns: db.execute("ALTER TABLE restaurant_settings ADD COLUMN calendar_id TEXT NOT NULL DEFAULT ''")
    if 'calendar_connected' not in setting_columns: db.execute("ALTER TABLE restaurant_settings ADD COLUMN calendar_connected INTEGER NOT NULL DEFAULT 0")
    if 'phone_carrier' not in setting_columns: db.execute("ALTER TABLE restaurant_settings ADD COLUMN phone_carrier TEXT NOT NULL DEFAULT ''")
    if 'voice_provider' not in setting_columns: db.execute("ALTER TABLE restaurant_settings ADD COLUMN voice_provider TEXT NOT NULL DEFAULT ''")
    if 'forwarding_number' not in setting_columns: db.execute("ALTER TABLE restaurant_settings ADD COLUMN forwarding_number TEXT NOT NULL DEFAULT ''")
    if 'voice_status' not in setting_columns: db.execute("ALTER TABLE restaurant_settings ADD COLUMN voice_status TEXT NOT NULL DEFAULT 'not_configured'")
    calendar_columns = {r[1] for r in db.execute('PRAGMA table_info(calendar_connections)').fetchall()}
    if 'refresh_token_ciphertext' not in calendar_columns: db.execute("ALTER TABLE calendar_connections ADD COLUMN refresh_token_ciphertext TEXT NOT NULL DEFAULT ''")
    call_columns = {r[1] for r in db.execute('PRAGMA table_info(calls)').fetchall()}
    if 'provider_call_id' not in call_columns: db.execute("ALTER TABLE calls ADD COLUMN provider_call_id TEXT NOT NULL DEFAULT ''")
    if 'status' not in call_columns: db.execute("ALTER TABLE calls ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
    if 'from_number' not in call_columns: db.execute("ALTER TABLE calls ADD COLUMN from_number TEXT NOT NULL DEFAULT ''")
    if 'to_number' not in call_columns: db.execute("ALTER TABLE calls ADD COLUMN to_number TEXT NOT NULL DEFAULT ''")
    if 'transcript' not in call_columns: db.execute("ALTER TABLE calls ADD COLUMN transcript TEXT NOT NULL DEFAULT ''")
    columns = {r[1] for r in db.execute('PRAGMA table_info(users)').fetchall()}
    if 'password_hash' not in columns:
        db.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
    if ENVIRONMENT == 'production':
        if not ADMIN_PASSWORD: raise RuntimeError('MARSMAITRE_ADMIN_PASSWORD es obligatoria en producción')
        if not os.environ.get('ALLOWED_ORIGIN') or 'REEMPLAZAR' in os.environ.get('ALLOWED_ORIGIN',''): raise RuntimeError('ALLOWED_ORIGIN debe apuntar al panel HTTPS en producción')
        if not os.environ.get('MARSMAITRE_PUBLIC_URL') or 'REEMPLAZAR' in os.environ.get('MARSMAITRE_PUBLIC_URL',''): raise RuntimeError('MARSMAITRE_PUBLIC_URL debe estar configurada en producción')
    if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
        seed_password = ADMIN_PASSWORD or DEMO_ADMIN_PASSWORD
        now = datetime.now(timezone.utc).isoformat()
        admin_id = str(uuid.uuid4())
        db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (admin_id, ADMIN_EMAIL, 'ADMIN', 'Martín Arellano', 1, now, hash_password(seed_password)))
        demo = [
          ('La Terraza Norte','Ciudad de México','Profesional','Activo',6,428,600,1199),
          ('Sabor de Barrio','Guadalajara','Inicio','Prueba',2,61,150,499),
          ('Casa del Fuego','Monterrey · 3 sucursales','Cadenas','Activo',14,1204,2000,2999),
        ]
        for name, city, plan, status, users, used, limit, price in demo:
            rid = str(uuid.uuid4())
            db.execute('INSERT INTO restaurants VALUES (?,?,?,?,?,?,?,?,?,?)', (rid,name,city,'',plan,status,users,used,limit,now))
            db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?)', (str(uuid.uuid4()),rid,plan,price,status,'',now))
            db.execute('INSERT INTO memberships VALUES (?,?,?)', (admin_id,rid,'ADMIN'))
            db.execute('INSERT INTO calls (id,restaurant_id,result,duration_min,confidence,created_at) VALUES (?,?,?,?,?,?)', (str(uuid.uuid4()),rid,'Pedido confirmado',8,'98%',now))
    for r in db.execute('SELECT id FROM restaurants').fetchall():
        db.execute('INSERT OR IGNORE INTO restaurant_settings (restaurant_id) VALUES (?)',(r['id'],))
        db.execute('INSERT OR IGNORE INTO calendar_connections (restaurant_id) VALUES (?)',(r['id'],))
    db.execute("UPDATE users SET password_hash=? WHERE lower(email)=lower(?) AND (password_hash='' OR password_hash IS NULL)", (hash_password(ADMIN_PASSWORD or DEMO_ADMIN_PASSWORD), ADMIN_EMAIL))
    db.commit(); db.close()


def rows(sql, args=()):
    db = connect(); result = [dict(r) for r in db.execute(sql,args).fetchall()]; db.close(); return result


def plan_limits(plan):
    return {'Inicio': {'minutes':150,'users':2,'branches':1}, 'Profesional': {'minutes':600,'users':8,'branches':1}, 'Cadenas': {'minutes':2000,'users':50,'branches':5}, 'Empresarial': {'minutes':10000,'users':999,'branches':999}}.get(plan, {'minutes':150,'users':2,'branches':1})


def agent_config(restaurant_id):
    db=connect(); r=db.execute('SELECT * FROM restaurants WHERE id=?',(restaurant_id,)).fetchone(); s=db.execute('SELECT * FROM restaurant_settings WHERE restaurant_id=?',(restaurant_id,)).fetchone(); items=[dict(x) for x in db.execute('SELECT * FROM menu_items WHERE restaurant_id=? AND available=1 ORDER BY category,name',(restaurant_id,)).fetchall()]; db.close()
    if not r: return None
    s=dict(s) if s else {}
    return {'restaurant':dict(r),'settings':s,'menu':items,'instructions':f"Atiende para {r['name']}. Usa únicamente el menú y precios configurados. No inventes ingredientes, horarios ni disponibilidad. Si detectas un alérgeno, informa al cliente y solicita confirmación al personal."}


def encrypt_refresh_token(token):
    key=os.environ.get('TOKEN_ENCRYPTION_KEY','')
    if not key: raise ValueError('TOKEN_ENCRYPTION_KEY no configurada')
    return Fernet(key.encode()).encrypt(token.encode()).decode()


def decrypt_refresh_token(ciphertext):
    key=os.environ.get('TOKEN_ENCRYPTION_KEY','')
    if not key: raise ValueError('TOKEN_ENCRYPTION_KEY no configurada')
    if not ciphertext: raise ValueError('No hay refresh token de Calendar guardado')
    return Fernet(key.encode()).decrypt(ciphertext.encode()).decode()


def google_access_token(refresh_token):
    client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID','')
    client_secret=os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET','')
    if not client_id or not client_secret:
        raise ValueError('Falta configurar OAuth de Google en el servidor')
    payload=urllib.parse.urlencode({'client_id':client_id,'client_secret':client_secret,'refresh_token':refresh_token,'grant_type':'refresh_token'}).encode()
    req=urllib.request.Request('https://oauth2.googleapis.com/token',data=payload,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'})
    data=json.loads(urllib.request.urlopen(req,timeout=20).read())
    token=data.get('access_token','')
    if not token: raise ValueError('Google no devolvió un token de acceso')
    return token


def calendar_event_data(reservation, restaurant, settings):
    start_text=str(reservation['start_at']).strip()
    parsed=datetime.fromisoformat(start_text.replace('Z','+00:00'))
    # El formulario captura hora local del restaurante. Si llega con zona, se conserva.
    end=parsed+timedelta(hours=2)
    timezone_name=(settings.get('timezone') or 'America/Mexico_City')
    start_value=parsed.isoformat(timespec='minutes')
    end_value=end.isoformat(timespec='minutes')
    details=[f"Personas: {reservation['party_size']}"]
    if reservation['customer_phone']: details.append(f"Teléfono: {reservation['customer_phone']}")
    if reservation['notes']: details.append(f"Notas: {reservation['notes']}")
    return {
        'summary':f"Reservación — {reservation['customer_name']} · {restaurant['name']}",
        'description':'\n'.join(details),
        'start':{'dateTime':start_value,'timeZone':timezone_name},
        'end':{'dateTime':end_value,'timeZone':timezone_name},
    }


def create_calendar_event(connection, reservation, restaurant, settings):
    refresh=decrypt_refresh_token(connection['refresh_token_ciphertext'])
    access=google_access_token(refresh)
    calendar_id=connection['calendar_id'] or 'primary'
    calendar_path=urllib.parse.quote(calendar_id,safe='')
    url=f'https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events?sendUpdates=all'
    payload=json.dumps(calendar_event_data(reservation,restaurant,settings),ensure_ascii=False).encode()
    req=urllib.request.Request(url,data=payload,method='POST',headers={'Authorization':f'Bearer {access}','Content-Type':'application/json'})
    data=json.loads(urllib.request.urlopen(req,timeout=20).read())
    if not data.get('id'): raise ValueError('Google no devolvió el identificador del evento')
    return data['id']


def delete_calendar_event(connection, event_id):
    if not event_id: return
    refresh=decrypt_refresh_token(connection['refresh_token_ciphertext'])
    access=google_access_token(refresh)
    calendar_id=connection['calendar_id'] or 'primary'
    calendar_path=urllib.parse.quote(calendar_id,safe='')
    event_path=urllib.parse.quote(event_id,safe='')
    url=f'https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}'
    req=urllib.request.Request(url,method='DELETE',headers={'Authorization':f'Bearer {access}'})
    try:
        urllib.request.urlopen(req,timeout=20).read()
    except urllib.error.HTTPError as exc:
        if exc.code != 404: raise


def user_for_token(token):
    if not token: return None
    db=connect(); row=db.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>? AND u.active=1',(token,datetime.now(timezone.utc).isoformat())).fetchone(); db.close()
    return dict(row) if row else None


def dashboard():
    rs = rows('SELECT * FROM restaurants ORDER BY created_at DESC')
    subs = rows('SELECT * FROM subscriptions')
    cs = rows('SELECT * FROM calls ORDER BY created_at DESC LIMIT 20')
    total_minutes = sum(r['minutes_used'] for r in rs)
    return {'restaurants': rs, 'subscriptions': subs, 'calls': cs, 'metrics': {
        'active_restaurants': sum(1 for r in rs if r['status'] == 'Activo'),
        'subscriptions': len(subs), 'calls_minutes': total_minutes,
        'monthly_revenue': sum(s['price_mxn'] for s in subs if s['status'] in ('Activo','Prueba'))
    }}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def _send(self, code, payload, content_type='application/json; charset=utf-8'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data))); self.send_header('Access-Control-Allow-Origin',os.environ.get('ALLOWED_ORIGIN','*'))
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type'); self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY'); self.send_header('Referrer-Policy','strict-origin-when-cross-origin')
        self.end_headers(); self.wfile.write(data)

    def do_OPTIONS(self): self._send(204, b'')

    def _token(self):
        value=self.headers.get('Authorization','')
        return value[7:].strip() if value.lower().startswith('bearer ') else ''

    def _body(self):
        length=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(length) or '{}')

    def _requested_restaurant(self):
        query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return str(query.get('restaurant_id',[self.headers.get('X-Restaurant-Id','')])[0]).strip()

    def _membership(self, db, user, full=False):
        requested=self._requested_restaurant()
        if full:
            sql='SELECT r.* FROM memberships m JOIN restaurants r ON r.id=m.restaurant_id WHERE m.user_id=?'
        else:
            sql='SELECT r.id FROM memberships m JOIN restaurants r ON r.id=m.restaurant_id WHERE m.user_id=?'
        args=[user['id']]
        if requested:
            sql+=' AND r.id=?'; args.append(requested)
        sql+=' ORDER BY r.name LIMIT 1'
        return db.execute(sql,args).fetchone()

    def _voice_event_allowed(self, body):
        secret=os.environ.get('VOICE_WEBHOOK_SECRET','')
        if not secret: return ENVIRONMENT != 'production'
        provided=self.headers.get('X-Voice-Signature','').strip().lower()
        canonical=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        expected=hmac.new(secret.encode(),canonical,hashlib.sha256).hexdigest().lower()
        return bool(provided) and hmac.compare_digest(provided,expected)

    def _require_user(self):
        user=user_for_token(self._token())
        if not user: self._send(401, {'error':'Sesión no válida o expirada'}); return None
        return user

    def do_GET(self):
        path=self.path.split('?',1)[0]
        if path.startswith('/api/health'): 
            self._send(200, {'ok': True, 'service': 'marsmaitre-backend', 'mode': ENVIRONMENT}); return
        if path == '/api/my/agent':
            user=self._require_user()
            if not user: return
            db=connect(); membership=self._membership(db,user); db.close()
            if not membership: self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            self._send(200, agent_config(membership['id'])); return
        if path == '/api/my/calendar/oauth/start':
            user=self._require_user()
            if not user: return
            client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID',''); redirect_uri=os.environ.get('GOOGLE_OAUTH_REDIRECT_URI','')
            if not client_id or not redirect_uri: self._send(503, {'error':'Falta configurar OAuth de Google en el servidor'}); return
            db=connect(); membership=self._membership(db,user)
            if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            state=secrets.token_urlsafe(32); expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(); db.execute('INSERT INTO oauth_states VALUES (?,?,?,0)',(state,membership['id'],expires)); db.commit(); db.close()
            query=urllib.parse.urlencode({'client_id':client_id,'redirect_uri':redirect_uri,'response_type':'code','scope':'https://www.googleapis.com/auth/calendar','access_type':'offline','prompt':'consent','state':state})
            self._send(200, {'authorization_url':'https://accounts.google.com/o/oauth2/v2/auth?'+query,'state':state}); return
        if path == '/oauth/google/callback':
            query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query); state=query.get('state',[''])[0]; code=query.get('code',[''])[0]
            if not state or not code: self._send(400, {'error':'Callback OAuth incompleto'}); return
            db=connect(); row=db.execute('SELECT * FROM oauth_states WHERE state=? AND used=0 AND expires_at>?',(state,datetime.now(timezone.utc).isoformat())).fetchone()
            if not row: db.close(); self._send(400, {'error':'Estado OAuth inválido o expirado'}); return
            client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID',''); client_secret=os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET',''); redirect_uri=os.environ.get('GOOGLE_OAUTH_REDIRECT_URI','')
            try:
                payload=urllib.parse.urlencode({'code':code,'client_id':client_id,'client_secret':client_secret,'redirect_uri':redirect_uri,'grant_type':'authorization_code'}).encode(); req=urllib.request.Request('https://oauth2.googleapis.com/token',data=payload,method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'}); token_data=json.loads(urllib.request.urlopen(req,timeout=20).read()); refresh=token_data.get('refresh_token','')
                if not refresh: raise ValueError('Google no devolvió refresh token')
                encrypted=encrypt_refresh_token(refresh); now=datetime.now(timezone.utc).isoformat(); db.execute('UPDATE calendar_connections SET status=?,connected_at=?,refresh_token_ciphertext=? WHERE restaurant_id=?',('connected',now,encrypted,row['restaurant_id'])); db.execute('UPDATE oauth_states SET used=1 WHERE state=?',(state,)); db.commit(); db.close(); self._send(200, {'ok':True,'message':'Google Calendar conectado para este restaurante'}); return
            except Exception as exc:
                db.close(); self._send(502, {'error':'No se pudo completar la autorización de Calendar','detail':str(exc)}); return
        if path == '/api/my/calendar':
            user=self._require_user()
            if not user: return
            db=connect(); membership=self._membership(db,user); connection=db.execute('SELECT * FROM calendar_connections WHERE restaurant_id=?',(membership['id'],)).fetchone() if membership else None; db.close()
            if not membership: self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            self._send(200, {'connection':dict(connection) if connection else {'status':'not_connected'}}); return
        if path == '/api/my/reservations':
            user=self._require_user()
            if not user: return
            db=connect(); membership=self._membership(db,user)
            if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            items=[dict(x) for x in db.execute('SELECT * FROM reservations WHERE restaurant_id=? ORDER BY start_at',(membership['id'],)).fetchall()]; db.close(); self._send(200, {'items':items}); return
        if path == '/api/my/feedback':
            user=self._require_user()
            if not user: return
            db=connect(); membership=self._membership(db,user)
            if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            items=[dict(x) for x in db.execute('SELECT c.*,cr.recording_url,cr.summary,cr.score,cr.improvements,cr.consented FROM calls c LEFT JOIN call_reviews cr ON cr.call_id=c.id WHERE c.restaurant_id=? ORDER BY c.created_at DESC LIMIT 50',(membership['id'],)).fetchall()]; db.close(); self._send(200, {'items':items}); return
        if path == '/api/my/restaurant' or path == '/api/my/menu':
            user=self._require_user()
            if not user: return
            db=connect(); membership=self._membership(db,user,full=True)
            if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            rid=membership['id']
            if path == '/api/my/menu':
                items=[dict(x) for x in db.execute('SELECT * FROM menu_items WHERE restaurant_id=? ORDER BY category,name',(rid,)).fetchall()]; db.close(); self._send(200, {'restaurant_id':rid,'items':items}); return
            settings=db.execute('SELECT * FROM restaurant_settings WHERE restaurant_id=?',(rid,)).fetchone(); items=[dict(x) for x in db.execute('SELECT * FROM menu_items WHERE restaurant_id=? ORDER BY category,name',(rid,)).fetchall()]; db.close(); self._send(200, {'restaurant':dict(membership),'settings':dict(settings) if settings else {},'items':items}); return
        if self.path.startswith('/api/me'):
            user=self._require_user()
            if user: self._send(200, {'user': user})
            return
        if path.startswith('/api/my/dashboard'):
            user=self._require_user()
            if not user: return
            db=connect(); memberships=db.execute('SELECT m.restaurant_id,m.role,r.* FROM memberships m JOIN restaurants r ON r.id=m.restaurant_id WHERE m.user_id=? ORDER BY r.name',(user['id'],)).fetchall()
            restaurant_ids=[r['id'] for r in memberships]
            if not restaurant_ids: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
            marks=','.join('?'*len(restaurant_ids)); sub=db.execute(f'SELECT * FROM subscriptions WHERE restaurant_id IN ({marks})',restaurant_ids).fetchall(); calls=db.execute(f'SELECT * FROM calls WHERE restaurant_id IN ({marks}) ORDER BY created_at DESC LIMIT 50',restaurant_ids).fetchall(); db.close()
            self._send(200, {'user':user,'restaurants':[dict(r) for r in memberships],'subscriptions':[dict(r) for r in sub],'calls':[dict(r) for r in calls],'limits':{r['id']:plan_limits(r['plan']) for r in memberships}}); return
        if self.path.startswith('/api/dashboard'):
            user=self._require_user()
            if user and user['role']=='ADMIN': self._send(200, dashboard())
            elif user: self._send(403, {'error':'Solo el administrador puede ver el resumen global'})
            return
        if path.startswith('/api/restaurants/') and path.endswith('/access'):
            user=self._require_user()
            if not user: return
            if user['role'] != 'ADMIN': self._send(403, {'error':'Permiso insuficiente'}); return
            rid=path.split('/')[3]
            self._send(200, {'items': rows('SELECT u.id,u.email,u.name,u.role,u.active,m.restaurant_id FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.restaurant_id=?',(rid,))}); return
        if self.path.startswith('/api/restaurants'):
            user=self._require_user()
            if user and user['role']=='ADMIN': self._send(200, {'items': rows('SELECT * FROM restaurants ORDER BY name')})
            elif user: self._send(403, {'error':'Permiso insuficiente'})
            return
        if self.path.startswith('/api/subscriptions'):
            user=self._require_user()
            if user and user['role']=='ADMIN': self._send(200, {'items': rows('SELECT * FROM subscriptions ORDER BY next_billing')})
            elif user: self._send(403, {'error':'Permiso insuficiente'})
            return
        if self.path.startswith('/api/calls'):
            user=self._require_user()
            if user and user['role']=='ADMIN': self._send(200, {'items': rows('SELECT * FROM calls ORDER BY created_at DESC LIMIT 100')})
            elif user: self._send(403, {'error':'Permiso insuficiente'})
            return
        if self.path.startswith('/api/reports'):
            user=self._require_user()
            if user and user['role']=='ADMIN': self._send(200, {'dashboard': dashboard(), 'generated_at': datetime.now(timezone.utc).isoformat()})
            elif user: self._send(403, {'error':'Permiso insuficiente'})
            return
        super().do_GET()

    def do_POST(self):
        try:
            body=self._body(); path=self.path.split('?',1)[0]
            if path == '/api/voice/events':
                if not self._voice_event_allowed(body): self._send(401, {'error':'Evento de voz no autorizado'}); return
                event=str(body.get('event',body.get('type',''))).strip().lower()
                if event in ('call.started','started'):
                    self._send(202, {'received':True,'status':'started'}); return
                if event not in ('call.completed','completed','call.ended','ended'):
                    self._send(202, {'received':True,'status':'ignored'}); return
                rid=str(body.get('restaurant_id','')).strip(); provider_id=str(body.get('call_id',body.get('provider_call_id',''))).strip()
                db=connect()
                if not rid:
                    number=''.join(ch for ch in str(body.get('to_number','')) if ch.isdigit())
                    candidates=db.execute('SELECT restaurant_id,phone FROM restaurant_settings WHERE phone<>\'\'').fetchall()
                    for candidate in candidates:
                        if ''.join(ch for ch in candidate['phone'] if ch.isdigit())==number: rid=candidate['restaurant_id']; break
                restaurant=db.execute('SELECT * FROM restaurants WHERE id=?',(rid,)).fetchone() if rid else None
                if not restaurant: db.close(); self._send(404, {'error':'No se pudo identificar el restaurante de la llamada'}); return
                if provider_id:
                    existing=db.execute('SELECT id FROM calls WHERE restaurant_id=? AND provider_call_id=?',(rid,provider_id)).fetchone()
                    if existing:
                        db.close(); self._send(200, {'ok':True,'duplicate':True,'call_id':existing['id']}); return
                now=datetime.now(timezone.utc).isoformat(); call_id=str(uuid.uuid4()); duration=max(0,int(float(body.get('duration_min',body.get('duration',0)) or 0))); transcript=str(body.get('transcript','')); result=str(body.get('result',body.get('outcome','Llamada procesada'))); confidence=str(body.get('confidence','0%'))
                db.execute('INSERT INTO calls (id,restaurant_id,result,duration_min,confidence,created_at,provider_call_id,status,from_number,to_number,transcript) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(call_id,rid,result,duration,confidence,now,provider_id,'completed',str(body.get('from_number','')),str(body.get('to_number','')),transcript))
                review_fields=body.get('review') if isinstance(body.get('review'),dict) else body
                recording=str(review_fields.get('recording_url','')); summary=str(review_fields.get('summary','')); improvements=str(review_fields.get('improvements','')); score=review_fields.get('score'); score_value=float(score) if score not in (None,'') else None; consented=int(bool(review_fields.get('consented',False)))
                if recording or transcript or summary or improvements or score_value is not None:
                    db.execute('INSERT INTO call_reviews (id,call_id,recording_url,transcript,summary,score,improvements,consented,created_at) VALUES (?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),call_id,recording,transcript,summary,score_value,improvements,consented,now))
                db.execute('UPDATE restaurants SET minutes_used=minutes_used+? WHERE id=?',(duration,rid)); db.commit(); db.close()
                self._send(201, {'ok':True,'call_id':call_id,'restaurant_id':rid,'status':'completed'}); return
            if path in ('/api/my/reservations/confirm','/api/my/reservations/cancel'):
                user=self._require_user()
                if not user: return
                if user['role'] not in ('OWNER','EMPLOYEE','ADMIN'): self._send(403, {'error':'Permiso insuficiente'}); return
                rid_item=str(body.get('id','')).strip(); db=connect(); membership=self._membership(db,user)
                if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
                reservation=db.execute('SELECT * FROM reservations WHERE id=? AND restaurant_id=?',(rid_item,membership['id'])).fetchone()
                if not reservation: db.close(); self._send(404, {'error':'Reservación no encontrada'}); return
                connection=db.execute('SELECT * FROM calendar_connections WHERE restaurant_id=?',(membership['id'],)).fetchone()
                restaurant=db.execute('SELECT * FROM restaurants WHERE id=?',(membership['id'],)).fetchone()
                settings_row=db.execute('SELECT * FROM restaurant_settings WHERE restaurant_id=?',(membership['id'],)).fetchone()
                settings=dict(settings_row) if settings_row else {}
                is_confirm=path.endswith('confirm')
                new_status='confirmed' if is_confirm else 'cancelled'
                event_id=reservation['calendar_event_id'] or ''
                try:
                    if is_confirm:
                        if not connection or connection['status']!='connected':
                            new_status='pending_calendar'
                        elif not event_id:
                            event_id=create_calendar_event(connection,reservation,restaurant,settings)
                    elif event_id and connection and connection['status']=='connected':
                        delete_calendar_event(connection,event_id)
                        event_id=''
                except Exception as exc:
                    # No se confirma/cancela como si Calendar hubiera funcionado.
                    db.close(); self._send(502, {'error':'No se pudo sincronizar esta reservación con Google Calendar','detail':str(exc)}); return
                now=datetime.now(timezone.utc).isoformat()
                db.execute('UPDATE reservations SET status=?,calendar_event_id=? WHERE id=? AND restaurant_id=?',(new_status,event_id,rid_item,membership['id']))
                if is_confirm and new_status=='confirmed':
                    db.execute('UPDATE calendar_connections SET last_sync_at=? WHERE restaurant_id=?',(now,membership['id']))
                db.commit(); db.close()
                message='Confirmada y creada en Google Calendar' if new_status=='confirmed' else ('Confirmada; queda pendiente la sincronización con Calendar' if new_status=='pending_calendar' else 'Reservación cancelada')
                self._send(200, {'ok':True,'status':new_status,'calendar_event_id':event_id,'message':message}); return
            if path == '/api/my/calendar/prepare':
                user=self._require_user()
                if not user: return
                if user['role'] not in ('OWNER','ADMIN'): self._send(403, {'error':'Solo el dueño puede preparar la conexión'}); return
                calendar_id=str(body.get('calendar_id','')).strip()
                if not calendar_id: self._send(400, {'error':'Falta el identificador del calendario'}); return
                db=connect(); membership=self._membership(db,user)
                if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
                db.execute('INSERT OR REPLACE INTO calendar_connections (restaurant_id,provider,calendar_id,status,connected_at,last_sync_at) VALUES (?,?,?,?,?,?)',(membership['id'],'google_calendar',calendar_id,'pending_authorization','','')); db.commit(); db.close(); self._send(200, {'status':'pending_authorization','message':'Calendario guardado; falta completar autorización OAuth individual'}); return
            if path == '/api/my/reservations':
                user=self._require_user()
                if not user: return
                if user['role'] not in ('OWNER','EMPLOYEE','ADMIN'): self._send(403, {'error':'Permiso insuficiente'}); return
                db=connect(); membership=self._membership(db,user)
                if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
                name=str(body.get('customer_name','')).strip(); start=str(body.get('start_at','')).strip(); phone=str(body.get('customer_phone','')).strip(); size=int(body.get('party_size',2) or 2)
                if not name or not start or size<1: db.close(); self._send(400, {'error':'Nombre, fecha/hora y número de personas son obligatorios'}); return
                reservation_id=str(uuid.uuid4()); db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?,?,?)',(reservation_id,membership['id'],name,phone,start,size,'pending',str(body.get('notes','')),datetime.now(timezone.utc).isoformat())); db.commit(); db.close(); self._send(201, {'id':reservation_id,'status':'pending','message':'Reservación creada y pendiente de sincronizar con Calendar'}); return
            if path == '/api/my/agent/test':
                user=self._require_user()
                if not user: return
                db=connect(); membership=self._membership(db,user); db.close()
                if not membership: self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
                config=agent_config(membership['id']); question=str(body.get('question','')).strip(); q=question.lower(); answer=config['settings'].get('greeting') or f"Hola, gracias por llamar a {config['restaurant']['name']}"
                if 'horario' in q or 'abren' in q or 'cierran' in q: answer=config['settings'].get('opening_hours') or 'El horario aún no está configurado.'
                else:
                    matches=[i for i in config['menu'] if i['name'].lower() in q or (i['category'] and i['category'].lower() in q)]
                    if matches:
                        item=matches[0]; answer=f"{item['name']} cuesta ${item['price_mxn']:,.2f} MXN. {item['description'] or ''} Ingredientes: {item['ingredients'] or 'pendientes de configurar'}."
                        if item['allergens']: answer+=f" Alérgenos indicados: {item['allergens']}."
                    elif 'menú' in q or 'menu' in q: answer='Tenemos: '+', '.join(f"{i['name']} (${i['price_mxn']:,.2f})" for i in config['menu']) if config['menu'] else 'El menú aún no está cargado.'
                    else: answer+=' ¿En qué puedo ayudarte? Esta es una prueba con la configuración actual.'
                self._send(200, {'answer':answer,'mode':'simulacion','instructions':config['instructions']}); return
            if path in ('/api/my/settings','/api/my/menu','/api/my/menu/delete'):
                user=self._require_user()
                if not user: return
                if user['role'] not in ('OWNER','ADMIN'): self._send(403, {'error':'Solo el dueño puede modificar la configuración'}); return
                db=connect(); membership=self._membership(db,user)
                if not membership: db.close(); self._send(403, {'error':'El usuario no tiene restaurante asignado'}); return
                rid=membership['id']
                if path == '/api/my/settings':
                    values=(str(body.get('greeting','')),str(body.get('phone','')),str(body.get('address','')),str(body.get('timezone','America/Mexico_City')),str(body.get('opening_hours','')),str(body.get('language','es-MX')),str(body.get('allergen_policy','')),str(body.get('calendar_id','')),int(bool(body.get('calendar_connected',False))),str(body.get('phone_carrier','')),str(body.get('voice_provider','')),str(body.get('forwarding_number','')),str(body.get('voice_status','not_configured')),rid)
                    db.execute('INSERT OR REPLACE INTO restaurant_settings (greeting,phone,address,timezone,opening_hours,language,allergen_policy,calendar_id,calendar_connected,phone_carrier,voice_provider,forwarding_number,voice_status,restaurant_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',values); db.commit(); db.close(); self._send(200, {'ok':True,'message':'Configuración guardada'}); return
                if path == '/api/my/menu':
                    name=str(body.get('name','')).strip(); category=str(body.get('category','')).strip(); price=float(body.get('price_mxn',0) or 0)
                    if not name or price<0: db.close(); self._send(400, {'error':'Nombre y precio válido son obligatorios'}); return
                    item_id=str(uuid.uuid4()); db.execute('INSERT INTO menu_items VALUES (?,?,?,?,?,?,?,?,?)',(item_id,rid,category,name,str(body.get('description','')),price,str(body.get('ingredients','')),str(body.get('allergens','')),1)); db.commit(); db.close(); self._send(201, {'id':item_id,'message':'Platillo agregado'}); return
                item_id=str(body.get('id','')).strip(); db.execute('DELETE FROM menu_items WHERE id=? AND restaurant_id=?',(item_id,rid)); db.commit(); db.close(); self._send(200, {'ok':True,'message':'Platillo eliminado'}); return
            if path == '/api/account/change-password':
                user=self._require_user()
                if not user: return
                current=str(body.get('current_password','')); new=str(body.get('new_password',''))
                if len(new)<12: self._send(400, {'error':'La nueva contraseña debe tener al menos 12 caracteres'}); return
                if not verify_password(current,user['password_hash']): self._send(401, {'error':'La contraseña actual no coincide'}); return
                db=connect(); db.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(new),user['id'])); db.commit(); db.close(); self._send(200, {'ok':True,'message':'Contraseña actualizada'}); return
            if path == '/api/invitations':
                user=self._require_user()
                if not user: return
                if user['role'] != 'ADMIN': self._send(403, {'error':'Solo ADMIN puede crear accesos'}); return
                rid=str(body.get('restaurant_id','')).strip(); email=str(body.get('email','')).strip().lower(); name=str(body.get('name','')).strip(); role=str(body.get('role','OWNER')).upper()
                if not rid or not email or not name: self._send(400, {'error':'Faltan restaurante, nombre o correo'}); return
                db=connect(); restaurant=db.execute('SELECT * FROM restaurants WHERE id=?',(rid,)).fetchone()
                if not restaurant: db.close(); self._send(404, {'error':'Restaurante no encontrado'}); return
                limits=plan_limits(restaurant['plan']); current=db.execute('SELECT COUNT(*) FROM memberships WHERE restaurant_id=?',(rid,)).fetchone()[0]
                if current>=limits['users']: db.close(); self._send(409, {'error':'El paquete alcanzó su límite de usuarios'}); return
                existing=db.execute('SELECT * FROM users WHERE lower(email)=?',(email,)).fetchone(); temporary=secrets.token_urlsafe(9)
                if existing:
                    uid=existing['id']; db.execute('UPDATE users SET name=?, active=1, role=? WHERE id=?',(name,role,uid))
                else:
                    uid=str(uuid.uuid4()); db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)',(uid,email,role,name,1,datetime.now(timezone.utc).isoformat(),hash_password(temporary)))
                db.execute('INSERT OR REPLACE INTO memberships VALUES (?,?,?)',(uid,rid,role)); db.execute('UPDATE restaurants SET users_count=(SELECT COUNT(*) FROM memberships WHERE restaurant_id=?) WHERE id=?',(rid,rid)); db.commit(); db.close()
                self._send(201, {'user_id':uid,'restaurant_id':rid,'email':email,'role':role,'temporary_password':temporary,'message':'Acceso creado; entrega la contraseña temporal por un canal privado'}); return
            if path == '/api/access/revoke':
                user=self._require_user()
                if not user: return
                if user['role'] != 'ADMIN': self._send(403, {'error':'Solo ADMIN puede revocar accesos'}); return
                uid=str(body.get('user_id','')).strip(); rid=str(body.get('restaurant_id','')).strip(); db=connect(); db.execute('DELETE FROM memberships WHERE user_id=? AND restaurant_id=?',(uid,rid)); db.execute('UPDATE restaurants SET users_count=(SELECT COUNT(*) FROM memberships WHERE restaurant_id=?) WHERE id=?',(rid,rid)); db.commit(); db.close(); self._send(200, {'ok':True,'message':'Acceso revocado'}); return
            if path == '/api/mercadopago/webhook':
                # El webhook no activa una cuenta solo por recibir un POST.
                # En producción se consultará el estado con el Access Token y se validará la firma.
                self._send(202, {'received': True}); return
            if self.path == '/api/billing/activate-cash':
                user=self._require_user()
                if not user: return
                if user['role'] != 'ADMIN': self._send(403, {'error':'Solo el administrador puede activar cuentas'}); return
                rid=str(body.get('restaurant_id','')).strip()
                if not rid: self._send(400, {'error':'Falta restaurant_id'}); return
                db=connect(); db.execute("UPDATE restaurants SET status='Activo' WHERE id=?",(rid,)); db.execute("UPDATE subscriptions SET status='Activo' WHERE restaurant_id=?",(rid,)); db.commit(); db.close(); self._send(200, {'ok':True,'message':'Cuenta activada por pago en efectivo'}); return
            if self.path == '/api/billing/create-plan':
                user=self._require_user()
                if not user: return
                if user['role'] != 'ADMIN': self._send(403, {'error':'Solo ADMIN puede crear planes'}); return
                if os.environ.get('BILLING_MODE','cash').lower() != 'mercadopago': self._send(409, {'error':'Mercado Pago está pendiente; el modo actual es pago en efectivo'}); return
                amount=float(body.get('amount',0)); reason=str(body.get('reason','MarsMaitre'))
                back_url=os.environ.get('MARSMAITRE_PUBLIC_URL','')
                if amount<=0 or not back_url: self._send(400, {'error':'Faltan monto o MARSMAITRE_PUBLIC_URL'}); return
                try:
                    result=MercadoPago().create_recurring_plan(reason,amount,back_url)
                    self._send(201, {'provider':'mercadopago','plan':result}); return
                except MercadoPagoError as exc:
                    self._send(502, {'error':'Mercado Pago no pudo crear el plan','detail':str(exc)}); return
            if self.path == '/api/login':
                email=str(body.get('email','')).strip().lower(); password=str(body.get('password',''))
                db=connect(); row=db.execute('SELECT * FROM users WHERE lower(email)=? AND active=1',(email,)).fetchone()
                if not row or not verify_password(password,row['password_hash']): db.close(); self._send(401, {'error':'Correo o contraseña incorrectos'}); return
                token=secrets.token_urlsafe(32); expires=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat(); db.execute('INSERT INTO sessions VALUES (?,?,?)',(token,row['id'],expires)); db.commit(); db.close()
                self._send(200, {'token':token,'expires_at':expires,'user':{'id':row['id'],'email':row['email'],'role':row['role'],'name':row['name']}}); return
            if self.path == '/api/logout':
                token=self._token(); db=connect(); db.execute('DELETE FROM sessions WHERE token=?',(token,)); db.commit(); db.close(); self._send(200, {'ok':True}); return
            if self.path != '/api/restaurants': self._send(404, {'error':'Ruta no encontrada'}); return
            user=self._require_user()
            if not user: return
            if user['role'] != 'ADMIN': self._send(403, {'error':'Solo el administrador puede registrar restaurantes'}); return
            name = str(body.get('name','')).strip()
            if not name: self._send(400, {'error':'El nombre es obligatorio'}); return
            now = datetime.now(timezone.utc).isoformat(); rid = str(uuid.uuid4()); plan = body.get('plan','Inicio')
            limits = {'Inicio':(150,499),'Profesional':(600,1199),'Cadenas':(2000,2999),'Empresarial':(5000,5999)}
            limit, price = limits.get(plan, limits['Inicio']); db=connect()
            db.execute('INSERT INTO restaurants VALUES (?,?,?,?,?,?,?,?,?,?)', (rid,name,body.get('city',''),body.get('phone',''),plan,'Prueba',1,0,limit,now))
            db.execute('INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?)', (str(uuid.uuid4()),rid,plan,price,'trial','',now)); db.commit(); db.close()
            self._send(201, {'restaurant_id':rid, 'message':'Restaurante creado'})
        except Exception as exc:
            self._send(400, {'error':'Solicitud inválida', 'detail':str(exc)})


def main():
    init_db(); port=int(os.environ.get('PORT','8787')); host=os.environ.get('HOST','0.0.0.0'); print(f'MarsMaitre backend: http://{host}:{port}', flush=True)
    ThreadingHTTPServer((host,port), Handler).serve_forever()

if __name__ == '__main__': main()
