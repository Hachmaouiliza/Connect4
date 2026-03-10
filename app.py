from flask import Flask, render_template, request, jsonify
import copy, math, random, json, os, base64
import psycopg2
from datetime import datetime

app = Flask(__name__)

# ══════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════
LIGNES = 9
COLS = 9
ROUGE = "rouge"
JAUNE = "jaune"
PROFONDEUR = 4

# ══════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════
def get_db():
    try:
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            return psycopg2.connect(db_url, sslmode='require')
        # Fallback local
        return psycopg2.connect(
            host="127.0.0.1",
            database="connect4",
            user="postgres",
            password="123456Sept",
            port="5432"
        )
    except Exception as e:
        print(f"DB ERROR: {e}")
        return None

def stats_db():
    conn = get_db()
    if not conn: return {"parties": 0, "positions": 0}
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM parties")
        parties = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM positions")
        positions = cur.fetchone()[0]
        cur.close(); conn.close()
        return {"parties": parties, "positions": positions}
    except:
        return {"parties": 0, "positions": 0}

def get_parties_recentes(limit=20):
    conn = get_db()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, date, vainqueur, suite_coups FROM parties ORDER BY id DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return [{"id": r[0], "date": str(r[1])[:16], "vainqueur": r[2], "coups": r[3], "nb_coups": len(r[3])} for r in rows]
    except:
        return []

def enregistrer_partie(sequence, vainqueur):
    conn = get_db()
    if not conn: return
    try:
        cur = conn.cursor()
        # CORRECTION : poids neutre pour abandon, +1 jaune, -1 rouge
        if vainqueur == JAUNE: valeur_poids = 1
        elif vainqueur == ROUGE: valeur_poids = -1
        else: valeur_poids = 0

        cur.execute("SELECT id FROM parties WHERE suite_coups = %s", (sequence,))
        if not cur.fetchone():
            cur.execute("INSERT INTO parties (date, vainqueur, suite_coups) VALUES (%s, %s, %s)",
                        (datetime.now(), vainqueur, sequence))
            etat = ""
            for coup in sequence:
                id_act = etat if etat else "start"
                etat += str(coup)
                # CORRECTION : ON CONFLICT sur (id_plateau, meilleur_coup) — plusieurs coups par position
                cur.execute("""
                    INSERT INTO positions (id_plateau, meilleur_coup, poids) VALUES (%s, %s, %s)
                    ON CONFLICT (id_plateau, meilleur_coup) DO UPDATE SET poids = positions.poids + EXCLUDED.poids
                """, (id_act, int(coup), valeur_poids))

        # Symétrie
        sym = calculer_symetrique(sequence)
        cur.execute("SELECT id FROM parties WHERE suite_coups = %s", (sym,))
        if not cur.fetchone():
            cur.execute("INSERT INTO parties (date, vainqueur, suite_coups) VALUES (%s, %s, %s)",
                        (datetime.now(), vainqueur, sym))
            etat = ""
            for coup in sym:
                id_act = etat if etat else "start"
                etat += str(coup)
                cur.execute("""
                    INSERT INTO positions (id_plateau, meilleur_coup, poids) VALUES (%s, %s, %s)
                    ON CONFLICT (id_plateau, meilleur_coup) DO UPDATE SET poids = positions.poids + EXCLUDED.poids
                """, (id_act, int(coup), valeur_poids))

        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        if conn: conn.rollback()
        print(f"SQL ERROR: {e}")

def chercher_memoire(historique, couleur=None):
    """CORRECTION : récupère le coup avec le MEILLEUR poids pondéré selon la couleur"""
    sequence = "".join(map(str, historique))
    if not sequence: return None
    conn = get_db()
    if not conn: return None
    try:
        cur = conn.cursor()
        if couleur == ROUGE:
            # Rouge veut minimiser → poids le plus BAS (négatif)
            cur.execute(
                "SELECT meilleur_coup FROM positions WHERE id_plateau = %s ORDER BY poids ASC LIMIT 1",
                (sequence,)
            )
        else:
            # Jaune veut maximiser → poids le plus HAUT (positif)
            cur.execute(
                "SELECT meilleur_coup FROM positions WHERE id_plateau = %s ORDER BY poids DESC LIMIT 1",
                (sequence,)
            )
        r = cur.fetchone()
        cur.close(); conn.close()
        return r[0] if r else None
    except:
        return None

# ══════════════════════════════════════════════
# LOGIQUE JEU
# ══════════════════════════════════════════════
def plateau_vide():
    return [[None]*COLS for _ in range(LIGNES)]

def calculer_symetrique(sequence):
    return "".join(str((COLS - 1) - int(c)) for c in sequence)

def jouer_coup(plateau, col, couleur):
    for l in range(LIGNES-1, -1, -1):
        if plateau[l][col] is None:
            plateau[l][col] = couleur
            return l
    return -1

def verifier_victoire(plateau):
    for r in range(LIGNES):
        for c in range(COLS):
            couleur = plateau[r][c]
            if couleur is None: continue
            for dr, dc in [(0,1),(1,0),(1,1),(1,-1)]:
                if 0 <= r+3*dr < LIGNES and 0 <= c+3*dc < COLS:
                    if all(plateau[r+i*dr][c+i*dc] == couleur for i in range(4)):
                        return couleur, [(r+i*dr, c+i*dc) for i in range(4)]
    return None, []

def evaluer_fenetre(fen, pion):
    score = 0
    adv = ROUGE if pion == JAUNE else JAUNE
    if fen.count(pion) == 4: score += 100000
    elif fen.count(pion) == 3 and fen.count(None) == 1: score += 500
    elif fen.count(pion) == 2 and fen.count(None) == 2: score += 50
    if fen.count(adv) == 3 and fen.count(None) == 1: score -= 800
    return score

def score_position(plat, pion):
    score = 0
    centre = [plat[i][COLS//2] for i in range(LIGNES)]
    score += centre.count(pion) * 10
    for r in range(LIGNES):
        row = [plat[r][c] for c in range(COLS)]
        for c in range(COLS-3):
            score += evaluer_fenetre(row[c:c+4], pion)
    for c in range(COLS):
        col = [plat[r][c] for r in range(LIGNES)]
        for r in range(LIGNES-3):
            score += evaluer_fenetre(col[r:r+4], pion)
    for r in range(LIGNES-3):
        for c in range(COLS-3):
            score += evaluer_fenetre([plat[r+i][c+i] for i in range(4)], pion)
            score += evaluer_fenetre([plat[r+3-i][c+i] for i in range(4)], pion)
    return score

def minimax(plat, prof, alpha, beta, maximisant, pion_max=JAUNE):
    """CORRECTION : minimax générique, fonctionne pour ROUGE ou JAUNE"""
    pion_min = ROUGE if pion_max == JAUNE else JAUNE
    libres = [c for c in range(COLS) if plat[0][c] is None]
    v, _ = verifier_victoire(plat)
    if prof == 0 or v or not libres:
        if v == pion_max: return None, 100000
        if v == pion_min: return None, -100000
        return None, score_position(plat, pion_max)

    if maximisant:
        val, col_res = -math.inf, random.choice(libres)
        for col in libres:
            temp = copy.deepcopy(plat)
            jouer_coup(temp, col, pion_max)
            res = minimax(temp, prof-1, alpha, beta, False, pion_max)[1]
            if res > val: val, col_res = res, col
            alpha = max(alpha, val)
            if alpha >= beta: break
        return col_res, val
    else:
        val, col_res = math.inf, random.choice(libres)
        for col in libres:
            temp = copy.deepcopy(plat)
            jouer_coup(temp, col, pion_min)
            res = minimax(temp, prof-1, alpha, beta, True, pion_max)[1]
            if res < val: val, col_res = res, col
            beta = min(beta, val)
            if alpha >= beta: break
        return col_res, val

def meilleur_coup_ia(plat, historique, mode='ia_minimax', couleur=JAUNE):
    """CORRECTION : 3 modes séparés, couleur passée partout"""
    libres = [c for c in range(COLS) if plat[0][c] is None]
    if not libres: return None, "aucun"

    if mode == 'ia_random':
        return random.choice(libres), "random"

    if mode == 'ia_db':
        coup_memoire = chercher_memoire(historique, couleur)
        if coup_memoire is not None and coup_memoire in libres:
            return coup_memoire, "memoire"
        return random.choice(libres), "random"

    # ia_minimax : DB d'abord, minimax en fallback
    coup_memoire = chercher_memoire(historique, couleur)
    if coup_memoire is not None and coup_memoire in libres:
        return coup_memoire, "memoire"
    col, _ = minimax(copy.deepcopy(plat), PROFONDEUR, -math.inf, math.inf, True, couleur)
    return col, "minimax"

def calculer_poids_colonnes(plat, couleur=JAUNE):
    """CORRECTION : poids calculés selon la couleur du joueur"""
    libres = [c for c in range(COLS) if plat[0][c] is None]
    poids = [0] * COLS
    for c in libres:
        temp = copy.deepcopy(plat)
        jouer_coup(temp, c, couleur)
        _, score = minimax(temp, PROFONDEUR-1, -math.inf, math.inf, False, couleur)
        poids[c] = score
    return poids

def calculer_prediction(plat, couleur=JAUNE):
    """CORRECTION : prédiction selon la couleur du joueur actuel"""
    libres = [c for c in range(COLS) if plat[0][c] is None]
    if not libres: return "nul"
    _, score = minimax(copy.deepcopy(plat), 3, -math.inf, math.inf, True, couleur)
    if score >= 50000: return "victoire"
    if score <= -50000: return "defaite"
    if len(libres) <= 5: return "nul"
    return "incertaine"

def reconstruire_plateau(sequence):
    plat = plateau_vide()
    joueur = ROUGE
    for c in sequence:
        jouer_coup(plat, int(c), joueur)
        joueur = JAUNE if joueur == ROUGE else ROUGE
    return plat

# ══════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html", stats=stats_db())

@app.route("/api/stats")
def api_stats():
    return jsonify(stats_db())

@app.route("/api/jouer", methods=["POST"])
def api_jouer():
    data = request.json
    plat = data["plateau"]
    col = data["col"]
    joueur = data["joueur"]
    historique = data.get("historique", [])

    ligne = jouer_coup(plat, col, joueur)
    if ligne == -1:
        return jsonify({"erreur": "Colonne pleine"})

    historique.append(col)
    vainqueur, pions_gagnants = verifier_victoire(plat)

    poids = [0] * COLS
    prediction = "incertaine"
    meilleur = None

    if not vainqueur:
        prochain = JAUNE if joueur == ROUGE else ROUGE
        poids = calculer_poids_colonnes(plat, prochain)
        prediction = calculer_prediction(plat, prochain)
        meilleur, _ = meilleur_coup_ia(plat, historique, couleur=prochain)

    if vainqueur:
        enregistrer_partie("".join(map(str, historique)), vainqueur)

    return jsonify({
        "plateau": plat,
        "vainqueur": vainqueur,
        "pions_gagnants": pions_gagnants,
        "poids_colonnes": poids,
        "prediction": prediction,
        "meilleur_coup": meilleur,
        "historique": historique,
        "ligne_jouee": ligne
    })

@app.route("/api/ia", methods=["POST"])
def api_ia():
    data = request.json
    plat = data["plateau"]
    historique = data.get("historique", [])
    mode = data.get("mode", "ia_minimax")
    # CORRECTION : on lit la vraie couleur envoyée par le front
    couleur = data.get("couleur", JAUNE)

    col, source = meilleur_coup_ia(plat, historique, mode, couleur)
    if col is None:
        libres = [c for c in range(COLS) if plat[0][c] is None]
        col = random.choice(libres) if libres else 0

    # CORRECTION : joue avec la vraie couleur, pas JAUNE hardcodé
    ligne = jouer_coup(plat, col, couleur)
    historique.append(col)
    vainqueur, pions_gagnants = verifier_victoire(plat)

    poids = [0] * COLS
    prediction = "incertaine"

    if not vainqueur:
        prochain = ROUGE if couleur == JAUNE else JAUNE
        poids = calculer_poids_colonnes(plat, prochain)
        prediction = calculer_prediction(plat, prochain)

    if vainqueur:
        enregistrer_partie("".join(map(str, historique)), vainqueur)

    return jsonify({
        "plateau": plat,
        "col_jouee": col,
        "ligne_jouee": ligne,
        "vainqueur": vainqueur,
        "pions_gagnants": pions_gagnants,
        "poids_colonnes": poids,
        "prediction": prediction,
        "source": source,
        "historique": historique
    })

@app.route("/api/suggestion", methods=["POST"])
def api_suggestion():
    data = request.json
    plat = data["plateau"]
    historique = data.get("historique", [])
    joueur = data.get("joueur", JAUNE)
    poids = calculer_poids_colonnes(plat, joueur)
    col, source = meilleur_coup_ia(plat, historique, couleur=joueur)
    return jsonify({"meilleur_coup": col, "poids_colonnes": poids, "source": source})

@app.route("/api/pinceau", methods=["POST"])
def api_pinceau():
    data = request.json
    plat = data["plateau"]
    historique = data.get("historique", [])
    joueur = data.get("joueur", JAUNE)
    col, source = meilleur_coup_ia(plat, historique, couleur=joueur)
    poids = calculer_poids_colonnes(plat, joueur)
    prediction = calculer_prediction(plat, joueur)
    return jsonify({
        "meilleur_coup": col,
        "poids_colonnes": poids,
        "prediction": prediction,
        "source": source
    })

@app.route("/api/parties")
def api_parties():
    return jsonify(get_parties_recentes())

@app.route("/api/rejouer/<int:partie_id>")
def api_rejouer(partie_id):
    conn = get_db()
    if not conn: return jsonify({"erreur": "DB indisponible"})
    try:
        cur = conn.cursor()
        cur.execute("SELECT suite_coups, vainqueur FROM parties WHERE id = %s", (partie_id,))
        r = cur.fetchone()
        cur.close(); conn.close()
        if not r: return jsonify({"erreur": "Partie introuvable"})
        return jsonify({"sequence": r[0], "vainqueur": r[1]})
    except Exception as e:
        return jsonify({"erreur": str(e)})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    return jsonify({"plateau": plateau_vide(), "historique": [], "ok": True})

@app.route("/api/sauvegarder", methods=["POST"])
def api_sauvegarder():
    data = request.json
    sequence = data.get("sequence", "")
    vainqueur = data.get("vainqueur", "inconnu")
    if not sequence:
        return jsonify({"erreur": "Séquence vide"})
    enregistrer_partie(sequence, vainqueur)
    return jsonify({"ok": True, "sequence": sequence, "vainqueur": vainqueur})

# CORRECTION : route /api/bga placée AVANT app.run()
@app.route("/api/bga", methods=["POST"])
def api_bga():
    import json as json_lib
    data = request.json
    json_text = data.get("json_text", "")
    if not json_text:
        return jsonify({"erreur": "Aucun JSON fourni"})
    try:
        bga = json_lib.loads(json_text)
        coups = []
        logs = bga.get("data", {}).get("logs", [])
        for log in logs:
            for event in log.get("data", []):
                if event.get("type") == "playDisc":
                    x = event.get("args", {}).get("x")
                    if x is not None:
                        col = int(x) - 1
                        if 0 <= col < COLS:
                            coups.append(col)
        if not coups:
            return jsonify({"erreur": "Aucun coup trouve. Verifie la requete XHR (logs.html)"})
        vainqueur = "inconnu"
        for log in logs:
            for event in log.get("data", []):
                if event.get("type") == "gameStateChange":
                    for joueur in event.get("args", {}).get("result", []):
                        if joueur.get("rank") == 1:
                            c = joueur.get("color", "").lower()
                            if "ff0000" in c: vainqueur = ROUGE
                            elif "ffff00" in c: vainqueur = JAUNE
        sequence = "".join(map(str, coups))
        plat = plateau_vide()
        joueur_c = ROUGE
        for c in coups:
            jouer_coup(plat, c, joueur_c)
            joueur_c = JAUNE if joueur_c == ROUGE else ROUGE
        if vainqueur != "inconnu":
            enregistrer_partie(sequence, vainqueur)
        return jsonify({"ok": True, "sequence": sequence, "nb_coups": len(coups), "vainqueur": vainqueur, "plateau": plat})
    except Exception as e:
        return jsonify({"erreur": f"Erreur : {str(e)}"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)