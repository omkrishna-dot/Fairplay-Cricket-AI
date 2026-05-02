"""
FairPlay Cricket AI - Database Layer
SHA-256 chained scoring for tamper detection
"""

import sqlite3
import hashlib
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'fairplay.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player',
            email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            avatar_initials TEXT
        )
    ''')

    # Matches
    c.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            team_a TEXT NOT NULL,
            team_b TEXT NOT NULL,
            venue TEXT,
            overs INTEGER DEFAULT 20,
            status TEXT DEFAULT 'upcoming',
            winner TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
    ''')

    # Ball-by-ball deliveries with tamper-proof chaining
    c.execute('''
        CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            innings INTEGER DEFAULT 1,
            over_num INTEGER NOT NULL,
            ball_num INTEGER NOT NULL,
            batsman TEXT,
            bowler TEXT,
            runs INTEGER DEFAULT 0,
            extras INTEGER DEFAULT 0,
            extra_type TEXT,
            is_wicket INTEGER DEFAULT 0,
            wicket_type TEXT,
            fielder TEXT,
            shot_direction TEXT,
            notes TEXT,
            recorded_by INTEGER,
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            prev_hash TEXT,
            entry_hash TEXT,
            FOREIGN KEY(match_id) REFERENCES matches(id)
        )
    ''')

    # AI Alerts
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            alert_type TEXT NOT NULL,
            severity TEXT DEFAULT 'medium',
            description TEXT,
            delivery_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved INTEGER DEFAULT 0
        )
    ''')

    # Player stats
    c.execute('''
        CREATE TABLE IF NOT EXISTS player_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            player_name TEXT NOT NULL,
            team TEXT,
            matches_played INTEGER DEFAULT 0,
            total_runs INTEGER DEFAULT 0,
            total_wickets INTEGER DEFAULT 0,
            highest_score INTEGER DEFAULT 0,
            batting_avg REAL DEFAULT 0.0,
            bowling_avg REAL DEFAULT 0.0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    _seed_demo_data()


def _hash_delivery(delivery_data: dict, prev_hash: str) -> str:
    """Create SHA-256 hash chaining each delivery to the previous"""
    payload = json.dumps({
        'match_id': delivery_data.get('match_id'),
        'innings': delivery_data.get('innings'),
        'over_num': delivery_data.get('over_num'),
        'ball_num': delivery_data.get('ball_num'),
        'runs': delivery_data.get('runs'),
        'extras': delivery_data.get('extras'),
        'is_wicket': delivery_data.get('is_wicket'),
        'batsman': delivery_data.get('batsman'),
        'bowler': delivery_data.get('bowler'),
        'recorded_at': delivery_data.get('recorded_at'),
        'prev_hash': prev_hash
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def get_last_hash(match_id: int) -> str:
    conn = get_db()
    c = conn.cursor()
    row = c.execute(
        'SELECT entry_hash FROM deliveries WHERE match_id=? ORDER BY id DESC LIMIT 1',
        (match_id,)
    ).fetchone()
    conn.close()
    return row['entry_hash'] if row else 'GENESIS'


def insert_delivery(data: dict) -> dict:
    """Insert a delivery with tamper-proof hash chain"""
    conn = get_db()
    c = conn.cursor()

    prev_hash = get_last_hash(data['match_id'])
    data['recorded_at'] = datetime.utcnow().isoformat()
    entry_hash = _hash_delivery(data, prev_hash)

    c.execute('''
        INSERT INTO deliveries
        (match_id, innings, over_num, ball_num, batsman, bowler,
         runs, extras, extra_type, is_wicket, wicket_type, fielder,
         shot_direction, notes, recorded_by, recorded_at, prev_hash, entry_hash)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        data.get('match_id'), data.get('innings', 1),
        data.get('over_num'), data.get('ball_num'),
        data.get('batsman'), data.get('bowler'),
        data.get('runs', 0), data.get('extras', 0),
        data.get('extra_type'), data.get('is_wicket', 0),
        data.get('wicket_type'), data.get('fielder'),
        data.get('shot_direction'), data.get('notes'),
        data.get('recorded_by'), data['recorded_at'],
        prev_hash, entry_hash
    ))
    delivery_id = c.lastrowid
    conn.commit()
    conn.close()
    return {'delivery_id': delivery_id, 'entry_hash': entry_hash}


def verify_chain(match_id: int) -> dict:
    """Verify the integrity of the hash chain for a match"""
    conn = get_db()
    c = conn.cursor()
    rows = c.execute(
        'SELECT * FROM deliveries WHERE match_id=? ORDER BY id ASC',
        (match_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return {'valid': True, 'checked': 0, 'tampered_at': None}

    prev_hash = 'GENESIS'
    for i, row in enumerate(rows):
        data = dict(row)
        expected = _hash_delivery(data, prev_hash)
        if expected != row['entry_hash'] or row['prev_hash'] != prev_hash:
            return {'valid': False, 'checked': i + 1, 'tampered_at': row['id']}
        prev_hash = row['entry_hash']

    return {'valid': True, 'checked': len(rows), 'tampered_at': None}


def get_match_score(match_id: int, innings: int = 1) -> dict:
    conn = get_db()
    c = conn.cursor()
    rows = c.execute(
        'SELECT * FROM deliveries WHERE match_id=? AND innings=? ORDER BY id ASC',
        (match_id, innings)
    ).fetchall()

    total_runs = sum(r['runs'] + r['extras'] for r in rows)
    wickets = sum(1 for r in rows if r['is_wicket'])
    legal_balls = sum(1 for r in rows if not r['extra_type'] or r['extra_type'] not in ('wide', 'noball'))
    overs_complete = legal_balls // 6
    balls_rem = legal_balls % 6

    conn.close()
    return {
        'runs': total_runs,
        'wickets': wickets,
        'overs': f"{overs_complete}.{balls_rem}",
        'legal_balls': legal_balls,
        'deliveries': [dict(r) for r in rows]
    }


def _seed_demo_data():
    """Insert realistic demo data"""
    conn = get_db()
    c = conn.cursor()

    # Check if already seeded
    if c.execute('SELECT COUNT(*) FROM users').fetchone()[0] > 0:
        conn.close()
        return

    import hashlib
    def pw(p): return hashlib.sha256(p.encode()).hexdigest()

    # Demo users
    users = [
        ('admin', pw('admin123'), 'organizer', 'admin@fairplay.ai', 'AD'),
        ('umpire_raj', pw('umpire123'), 'umpire', 'raj@fairplay.ai', 'UR'),
        ('virat_k', pw('player123'), 'player', 'virat@fairplay.ai', 'VK'),
        ('rohit_s', pw('player123'), 'player', 'rohit@fairplay.ai', 'RS'),
        ('ms_dhoni', pw('player123'), 'player', 'dhoni@fairplay.ai', 'MD'),
        ('scorer1', pw('scorer123'), 'umpire', 'scorer@fairplay.ai', 'S1'),
    ]
    c.executemany(
        'INSERT INTO users (username, password_hash, role, email, avatar_initials) VALUES (?,?,?,?,?)',
        users
    )

    # Demo matches
    matches = [
        ('Qualifier Final', 'Team Alpha', 'Team Beta', 'Green Park Stadium', 20, 'live', None, 1),
        ('Semi Final', 'Team Gamma', 'Team Delta', 'Cricket Ground A', 15, 'completed', 'Team Gamma', 1),
        ('League Match 3', 'Team Echo', 'Team Foxtrot', 'Local Ground B', 10, 'completed', 'Team Echo', 1),
        ('Practice Match', 'Team Alpha', 'Team Gamma', 'Academy Ground', 5, 'upcoming', None, 1),
        ('T10 Cup', 'Team Beta', 'Team Delta', 'Central Park', 10, 'live', None, 1),
    ]
    c.executemany(
        'INSERT INTO matches (title, team_a, team_b, venue, overs, status, winner, created_by) VALUES (?,?,?,?,?,?,?,?)',
        matches
    )

    # Player stats
    players = [
        (3, 'Virat K', 'Team Alpha', 12, 687, 0, 112, 57.25, 0),
        (4, 'Rohit S', 'Team Alpha', 12, 543, 0, 98, 45.25, 0),
        (5, 'MS Dhoni', 'Team Alpha', 10, 421, 0, 74, 42.1, 0),
        (None, 'Bumrah J', 'Team Beta', 11, 45, 18, 12, 4.5, 14.2),
        (None, 'Shami M', 'Team Beta', 11, 32, 15, 8, 3.2, 16.8),
        (None, 'Jadeja R', 'Team Gamma', 12, 312, 14, 65, 26.0, 18.5),
        (None, 'Kohli A', 'Team Delta', 10, 389, 0, 89, 38.9, 0),
        (None, 'Pant R', 'Team Echo', 9, 298, 0, 67, 33.1, 0),
    ]
    c.executemany(
        'INSERT INTO player_stats (user_id, player_name, team, matches_played, total_runs, total_wickets, highest_score, batting_avg, bowling_avg) VALUES (?,?,?,?,?,?,?,?,?)',
        players
    )

    # Demo alerts
    alerts = [
        (1, 'no_ball', 'high', 'Suspected front-foot no-ball detected — Over 3, Ball 4', None),
        (1, 'suspicious_scoring', 'medium', 'Scoring rate jumped 340% in Over 5 vs Over 4', None),
        (2, 'run_out', 'low', 'Run-out decision marginal — frame analysis inconclusive', None),
        (5, 'no_ball', 'high', 'Front foot crossed crease line by 12px — No Ball', None),
        (1, 'unusual_pattern', 'medium', 'Batsman Virat K scored 6 on 3 consecutive no-balls', None),
    ]
    c.executemany(
        'INSERT INTO alerts (match_id, alert_type, severity, description, delivery_id) VALUES (?,?,?,?,?)',
        alerts
    )

    conn.commit()
    conn.close()


if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
