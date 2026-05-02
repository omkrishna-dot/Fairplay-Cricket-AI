"""
FairPlay Cricket AI - Flask Application
Main entry point for the web application
"""

import hashlib
import json
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session)
from flask_cors import CORS

from database import (init_db, get_db, insert_delivery, verify_chain,
                      get_match_score)
from ai_engine import (analyze_noball, analyze_runout,
                        detect_suspicious_patterns, generate_live_delivery_analysis,
                        generate_match_ai_summary)

app = Flask(__name__)
app.secret_key = 'fairplay-cricket-ai-secret-2024'
CORS(app)

# ─── Init DB on startup ───────────────────────────────────────────────────────
with app.app_context():
    init_db()


# ─── Auth Helpers ─────────────────────────────────────────────────────────────

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                return jsonify({'error': 'Unauthorized'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─── Page Routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json() or request.form
        username = data.get('username', '').strip()
        password = data.get('password', '')

        conn = get_db()
        user = conn.execute(
            'SELECT * FROM users WHERE username=? AND password_hash=?',
            (username, hash_password(password))
        ).fetchone()
        conn.close()

        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['avatar'] = user['avatar_initials'] or user['username'][:2].upper()
            if request.is_json:
                return jsonify({'success': True, 'role': user['role'], 'redirect': '/dashboard'})
            return redirect(url_for('dashboard'))

        if request.is_json:
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
        return render_template('login.html', error='Invalid username or password')

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        data = request.get_json() or request.form
        username = data.get('username', '').strip()
        password = data.get('password', '')
        email = data.get('email', '').strip()
        role = data.get('role', 'player')

        if role not in ('player', 'umpire', 'organizer'):
            role = 'player'

        initials = username[:2].upper()

        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO users (username, password_hash, role, email, avatar_initials) VALUES (?,?,?,?,?)',
                (username, hash_password(password), role, email, initials)
            )
            conn.commit()
            conn.close()
            if request.is_json:
                return jsonify({'success': True, 'redirect': '/login'})
            return redirect(url_for('login'))
        except Exception as e:
            conn.close()
            error = 'Username already exists'
            if request.is_json:
                return jsonify({'success': False, 'error': error}), 400
            return render_template('signup.html', error=error)

    return render_template('signup.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    matches = conn.execute(
        'SELECT * FROM matches ORDER BY created_at DESC LIMIT 20'
    ).fetchall()
    alerts = conn.execute(
        'SELECT a.*, m.title as match_title FROM alerts a '
        'LEFT JOIN matches m ON a.match_id = m.id '
        'ORDER BY a.created_at DESC LIMIT 10'
    ).fetchall()
    user_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    conn.close()

    live_count = sum(1 for m in matches if m['status'] == 'live')
    return render_template('dashboard.html',
                           matches=matches,
                           alerts=alerts,
                           live_count=live_count,
                           user_count=user_count)


@app.route('/match/<int:match_id>')
@login_required
def match_live(match_id):
    conn = get_db()
    match = conn.execute('SELECT * FROM matches WHERE id=?', (match_id,)).fetchone()
    if not match:
        return redirect(url_for('dashboard'))
    alerts = conn.execute(
        'SELECT * FROM alerts WHERE match_id=? ORDER BY created_at DESC LIMIT 20',
        (match_id,)
    ).fetchall()
    conn.close()
    score = get_match_score(match_id, 1)
    score2 = get_match_score(match_id, 2)
    return render_template('match_live.html',
                           match=match,
                           score=score,
                           score2=score2,
                           alerts=alerts)


@app.route('/video-analysis')
@login_required
def video_analysis():
    return render_template('video_analysis.html')


@app.route('/leaderboard')
@login_required
def leaderboard():
    conn = get_db()
    players = conn.execute(
        'SELECT * FROM player_stats ORDER BY total_runs DESC'
    ).fetchall()
    conn.close()
    return render_template('leaderboard.html', players=players)


@app.route('/match/<int:match_id>/summary')
@login_required
def match_summary(match_id):
    conn = get_db()
    match = conn.execute('SELECT * FROM matches WHERE id=?', (match_id,)).fetchone()
    conn.close()
    if not match:
        return redirect(url_for('dashboard'))
    score = get_match_score(match_id, 1)
    score2 = get_match_score(match_id, 2)
    ai_summary = generate_match_ai_summary(match_id, score['deliveries'])
    chain_result = verify_chain(match_id)
    return render_template('match_summary.html',
                           match=match,
                           score=score,
                           score2=score2,
                           ai_summary=ai_summary,
                           chain_result=chain_result)


# ─── REST API ─────────────────────────────────────────────────────────────────

@app.route('/api/matches', methods=['GET'])
@login_required
def api_matches():
    conn = get_db()
    rows = conn.execute('SELECT * FROM matches ORDER BY created_at DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/matches', methods=['POST'])
@login_required
def api_create_match():
    if session.get('role') not in ('organizer', 'umpire'):
        return jsonify({'error': 'Only organizers/umpires can create matches'}), 403
    data = request.get_json()
    conn = get_db()
    conn.execute(
        'INSERT INTO matches (title, team_a, team_b, venue, overs, status, created_by) VALUES (?,?,?,?,?,?,?)',
        (data['title'], data['team_a'], data['team_b'],
         data.get('venue', ''), data.get('overs', 20),
         'upcoming', session['user_id'])
    )
    conn.commit()
    match_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
    conn.close()
    return jsonify({'success': True, 'match_id': match_id})


@app.route('/api/matches/<int:match_id>/status', methods=['POST'])
@login_required
def api_update_match_status(match_id):
    if session.get('role') not in ('organizer', 'umpire'):
        return jsonify({'error': 'Unauthorized'}), 403
    data = request.get_json()
    status = data.get('status')
    if status not in ('upcoming', 'live', 'completed'):
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    conn.execute('UPDATE matches SET status=? WHERE id=?', (status, match_id))
    if status == 'completed' and data.get('winner'):
        conn.execute('UPDATE matches SET winner=? WHERE id=?', (data['winner'], match_id))
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/api/matches/<int:match_id>/deliveries', methods=['GET'])
@login_required
def api_get_deliveries(match_id):
    innings = request.args.get('innings', 1, type=int)
    score = get_match_score(match_id, innings)
    return jsonify(score)


@app.route('/api/matches/<int:match_id>/deliveries', methods=['POST'])
@login_required
def api_add_delivery(match_id):
    if session.get('role') not in ('umpire', 'organizer'):
        return jsonify({'error': 'Only umpires can record deliveries'}), 403

    data = request.get_json()
    data['match_id'] = match_id
    data['recorded_by'] = session['user_id']

    # AI: auto-analyze for no-ball
    noball_result = analyze_noball(simulated=True)
    ai_alerts = []

    if noball_result['is_noball'] and data.get('extra_type') != 'noball':
        ai_alerts.append({
            'alert_type': 'no_ball',
            'severity': 'high',
            'description': f"AI detected possible no-ball: {noball_result['detail']} (confidence {noball_result['confidence_pct']}%)"
        })

    result = insert_delivery(data)

    # Store AI alerts
    if ai_alerts:
        conn = get_db()
        for alert in ai_alerts:
            conn.execute(
                'INSERT INTO alerts (match_id, alert_type, severity, description, delivery_id) VALUES (?,?,?,?,?)',
                (match_id, alert['alert_type'], alert['severity'],
                 alert['description'], result['delivery_id'])
            )
        conn.commit()
        conn.close()

    # Run suspicious pattern detection
    score = get_match_score(match_id, data.get('innings', 1))
    pattern_alerts = detect_suspicious_patterns(score['deliveries'])
    if pattern_alerts:
        conn = get_db()
        for alert in pattern_alerts[-2:]:  # Only store last 2 to avoid flooding
            conn.execute(
                'INSERT INTO alerts (match_id, alert_type, severity, description) VALUES (?,?,?,?)',
                (match_id, alert['alert_type'], alert['severity'], alert['description'])
            )
        conn.commit()
        conn.close()

    return jsonify({
        'success': True,
        'delivery_id': result['delivery_id'],
        'entry_hash': result['entry_hash'],
        'ai_alerts': ai_alerts,
        'noball_analysis': noball_result
    })


@app.route('/api/matches/<int:match_id>/verify', methods=['GET'])
@login_required
def api_verify_chain(match_id):
    result = verify_chain(match_id)
    return jsonify(result)


@app.route('/api/matches/<int:match_id>/alerts', methods=['GET'])
@login_required
def api_get_alerts(match_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM alerts WHERE match_id=? ORDER BY created_at DESC LIMIT 30',
        (match_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/ai/noball', methods=['POST'])
@login_required
def api_noball():
    data = request.get_json() or {}
    result = analyze_noball(
        foot_x=data.get('foot_x'),
        foot_y=data.get('foot_y'),
        simulated=data.get('simulated', True)
    )
    return jsonify(result)


@app.route('/api/ai/runout', methods=['POST'])
@login_required
def api_runout():
    data = request.get_json() or {}
    result = analyze_runout(
        stump_hit_ms=data.get('stump_hit_ms'),
        bat_ground_ms=data.get('bat_ground_ms'),
        simulated=data.get('simulated', True)
    )
    return jsonify(result)


@app.route('/api/ai/live-delivery', methods=['GET'])
@login_required
def api_live_delivery():
    result = generate_live_delivery_analysis()
    return jsonify(result)


@app.route('/api/leaderboard', methods=['GET'])
@login_required
def api_leaderboard():
    conn = get_db()
    rows = conn.execute(
        'SELECT * FROM player_stats ORDER BY total_runs DESC'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/alerts', methods=['GET'])
@login_required
def api_all_alerts():
    conn = get_db()
    rows = conn.execute(
        'SELECT a.*, m.title as match_title FROM alerts a '
        'LEFT JOIN matches m ON a.match_id = m.id '
        'ORDER BY a.created_at DESC LIMIT 50'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/session', methods=['GET'])
def api_session():
    if 'user_id' in session:
        return jsonify({
            'logged_in': True,
            'user_id': session['user_id'],
            'username': session['username'],
            'role': session['role'],
            'avatar': session.get('avatar', '?')
        })
    return jsonify({'logged_in': False})


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("FairPlay Cricket AI -- Starting server...")
    print("Open http://localhost:5000 in your browser")
    print("Demo credentials:")
    print("  Organizer: admin / admin123")
    print("  Umpire:    umpire_raj / umpire123")
    print("  Player:    virat_k / player123")
    app.run(debug=True, host='0.0.0.0', port=5000)
