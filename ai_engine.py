"""
FairPlay Cricket AI - Rule-Based AI Engine
Simulates: No-ball detection, Run-out analysis, Suspicious pattern detection
"""

import random
import math
from typing import Optional


# ─── Constants ────────────────────────────────────────────────────────────────
CREASE_X = 170           # pixels in 340-wide canvas
CANVAS_W = 340
CANVAS_H = 340
STUMP_Y = 270            # stump y-position in analysis canvas
SPIKE_THRESHOLD = 2.5    # run-rate multiplier to flag suspicious scoring
NOBALL_MIN_OVERLAP = 5   # minimum pixel overstep to flag no-ball


# ─── No-Ball Detection ────────────────────────────────────────────────────────

def analyze_noball(foot_x: Optional[float] = None, foot_y: Optional[float] = None,
                   simulated: bool = True) -> dict:
    """
    Analyze bowler's front foot position to detect no-balls.
    
    Args:
        foot_x: X-coordinate of front foot in canvas
        foot_y: Y-coordinate of front foot in canvas
        simulated: If True, generate realistic simulated data
    
    Returns:
        Analysis result with verdict, confidence, and details
    """
    if simulated or foot_x is None:
        # Simulate a realistic foot position
        # 25% chance of a no-ball in simulation
        is_noball_scenario = random.random() < 0.25
        if is_noball_scenario:
            foot_x = random.uniform(CREASE_X + NOBALL_MIN_OVERLAP,
                                     CREASE_X + 35)
        else:
            foot_x = random.uniform(CREASE_X - 50, CREASE_X - 2)
        foot_y = random.uniform(STUMP_Y - 20, STUMP_Y + 10)

    overstep = foot_x - CREASE_X
    is_noball = overstep > 0

    # Confidence based on how clear the overstep is
    if is_noball:
        confidence = min(0.65 + (overstep / 40) * 0.30, 0.98)
        verdict = "NO BALL"
        severity = "high" if overstep > 15 else "medium"
    else:
        gap = abs(overstep)
        confidence = min(0.70 + (gap / 60) * 0.25, 0.97)
        verdict = "LEGAL DELIVERY"
        severity = "low"

    return {
        "verdict": verdict,
        "is_noball": is_noball,
        "confidence": round(confidence, 3),
        "confidence_pct": round(confidence * 100, 1),
        "foot_x": round(foot_x, 1),
        "foot_y": round(foot_y, 1),
        "crease_x": CREASE_X,
        "overstep_px": round(overstep, 1),
        "severity": severity,
        "detail": (
            f"Front foot overstepped crease by {overstep:.1f}px" if is_noball
            else f"Front foot cleared crease with {abs(overstep):.1f}px margin"
        )
    }


# ─── Run-Out Decision Assistant ───────────────────────────────────────────────

def analyze_runout(stump_hit_ms: Optional[float] = None,
                   bat_ground_ms: Optional[float] = None,
                   simulated: bool = True) -> dict:
    """
    Determine if a batsman is run out by comparing event timestamps.
    
    stump_hit_ms: millisecond timestamp of ball hitting stumps
    bat_ground_ms: millisecond timestamp of bat/foot grounding
    """
    if simulated or stump_hit_ms is None:
        # Generate realistic close run-out scenario
        scenario = random.choice(['clearly_out', 'clearly_safe', 'marginal_out', 'marginal_safe'])
        base_time = 1200  # ms
        if scenario == 'clearly_out':
            bat_ground_ms = base_time + random.uniform(50, 200)
            stump_hit_ms = base_time
        elif scenario == 'clearly_safe':
            bat_ground_ms = base_time - random.uniform(50, 200)
            stump_hit_ms = base_time
        elif scenario == 'marginal_out':
            bat_ground_ms = base_time + random.uniform(5, 49)
            stump_hit_ms = base_time
        else:
            bat_ground_ms = base_time - random.uniform(5, 49)
            stump_hit_ms = base_time
    else:
        scenario = 'provided'

    diff_ms = bat_ground_ms - stump_hit_ms  # positive = bat arrived AFTER stumps hit

    if diff_ms > 40:
        verdict = "OUT — Run Out"
        is_out = True
        confidence = min(0.75 + (diff_ms / 300) * 0.20, 0.97)
        detail = f"Bat grounded {diff_ms:.0f}ms after bails dislodged"
    elif diff_ms > 0:
        verdict = "OUT — Marginal"
        is_out = True
        confidence = random.uniform(0.52, 0.70)
        detail = f"Very close — bat grounded {diff_ms:.0f}ms after bails (within margin)"
    elif diff_ms > -40:
        verdict = "SAFE — Marginal"
        is_out = False
        confidence = random.uniform(0.52, 0.68)
        detail = f"Extremely close — bat in crease {abs(diff_ms):.0f}ms before bails"
    else:
        verdict = "SAFE — Not Out"
        is_out = False
        confidence = min(0.78 + (abs(diff_ms) / 300) * 0.18, 0.97)
        detail = f"Bat safely grounded {abs(diff_ms):.0f}ms before bails dislodged"

    return {
        "verdict": verdict,
        "is_out": is_out,
        "confidence": round(confidence, 3),
        "confidence_pct": round(confidence * 100, 1),
        "diff_ms": round(diff_ms, 1),
        "stump_hit_ms": round(stump_hit_ms, 1),
        "bat_ground_ms": round(bat_ground_ms, 1),
        "severity": "high" if abs(diff_ms) < 30 else "low",
        "detail": detail
    }


# ─── Suspicious Pattern Detection ────────────────────────────────────────────

def detect_suspicious_patterns(deliveries: list) -> list:
    """
    Scan ball-by-ball data for suspicious scoring patterns.
    
    Returns a list of alert dicts.
    """
    alerts = []
    if not deliveries:
        return alerts

    # 1. Run-rate spike detection (per over)
    over_runs = {}
    for d in deliveries:
        ov = d.get('over_num', 0)
        over_runs.setdefault(ov, 0)
        over_runs[ov] += d.get('runs', 0) + d.get('extras', 0)

    sorted_overs = sorted(over_runs.items())
    for i in range(1, len(sorted_overs)):
        prev_ov, prev_r = sorted_overs[i - 1]
        curr_ov, curr_r = sorted_overs[i]
        if prev_r > 0 and curr_r / prev_r >= SPIKE_THRESHOLD:
            alerts.append({
                'alert_type': 'suspicious_scoring',
                'severity': 'medium',
                'description': (
                    f"Scoring rate jumped {curr_r/prev_r:.1f}x in Over {curr_ov+1} "
                    f"({curr_r} runs) vs Over {prev_ov+1} ({prev_r} runs)"
                )
            })

    # 2. Repeated 6s on no-balls by same batsman
    noball_sixes = {}
    for d in deliveries:
        if d.get('extra_type') == 'noball' and d.get('runs', 0) == 6:
            batsman = d.get('batsman', 'Unknown')
            noball_sixes[batsman] = noball_sixes.get(batsman, 0) + 1

    for batsman, count in noball_sixes.items():
        if count >= 2:
            alerts.append({
                'alert_type': 'unusual_pattern',
                'severity': 'high' if count >= 3 else 'medium',
                'description': (
                    f"{batsman} scored 6 on {count} no-balls — "
                    f"unusual pattern detected"
                )
            })

    # 3. Consecutive wide/no-ball by same bowler
    bowler_extras = {}
    for d in deliveries:
        if d.get('extra_type') in ('wide', 'noball'):
            bowler = d.get('bowler', 'Unknown')
            bowler_extras[bowler] = bowler_extras.get(bowler, 0) + 1

    for bowler, count in bowler_extras.items():
        if count >= 5:
            alerts.append({
                'alert_type': 'suspicious_bowling',
                'severity': 'high' if count >= 8 else 'medium',
                'description': (
                    f"Bowler {bowler} has {count} extras (wides/no-balls) — "
                    f"possible deliberate bowling"
                )
            })

    # 4. Zero scoring over (potential dead-ball manipulation)
    for ov, runs in sorted_overs:
        if runs == 0 and ov > 0:
            alerts.append({
                'alert_type': 'zero_scoring_over',
                'severity': 'low',
                'description': f"Over {ov+1} scored 0 runs — verify no manipulation"
            })

    return alerts


# ─── Simulate Live No-Ball Feed ───────────────────────────────────────────────

def generate_live_delivery_analysis() -> dict:
    """Generate a simulated real-time delivery analysis"""
    noball = analyze_noball(simulated=True)
    runout_chance = random.random() < 0.15  # 15% deliveries have run-out attempt

    result = {
        'noball_analysis': noball,
        'run_attempt': runout_chance
    }

    if runout_chance:
        result['runout_analysis'] = analyze_runout(simulated=True)

    # Simulate wagon wheel direction
    directions = ['fine_leg', 'square_leg', 'mid_wicket', 'mid_on',
                  'straight', 'mid_off', 'cover', 'point', 'third_man']
    result['shot_direction'] = random.choice(directions)

    # Simulate speed
    result['ball_speed_kmh'] = round(random.uniform(90, 148), 1)

    return result


# ─── Summarize Match AI Report ─────────────────────────────────────────────────

def generate_match_ai_summary(match_id: int, deliveries: list) -> dict:
    """Generate an AI fairness summary for a completed/live match"""
    alerts = detect_suspicious_patterns(deliveries)

    total_noballs = sum(1 for d in deliveries if d.get('extra_type') == 'noball')
    total_wides = sum(1 for d in deliveries if d.get('extra_type') == 'wide')
    total_wickets = sum(1 for d in deliveries if d.get('is_wicket'))
    total_runs = sum(d.get('runs', 0) + d.get('extras', 0) for d in deliveries)

    fairness_score = 100
    fairness_score -= len([a for a in alerts if a['severity'] == 'high']) * 15
    fairness_score -= len([a for a in alerts if a['severity'] == 'medium']) * 8
    fairness_score -= len([a for a in alerts if a['severity'] == 'low']) * 3
    fairness_score = max(fairness_score, 0)

    return {
        'match_id': match_id,
        'fairness_score': fairness_score,
        'fairness_grade': (
            'A' if fairness_score >= 90 else
            'B' if fairness_score >= 75 else
            'C' if fairness_score >= 60 else 'D'
        ),
        'total_alerts': len(alerts),
        'high_severity': len([a for a in alerts if a['severity'] == 'high']),
        'medium_severity': len([a for a in alerts if a['severity'] == 'medium']),
        'stats': {
            'total_runs': total_runs,
            'total_wickets': total_wickets,
            'no_balls': total_noballs,
            'wides': total_wides,
            'deliveries_analyzed': len(deliveries)
        },
        'alerts': alerts
    }
