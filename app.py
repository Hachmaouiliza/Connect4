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
PROFONDEUR = 3

# Bibliothèque d'ouvertures (premiers coups évidents - pas besoin de calcul)
OUVERTURES = {
    "": 4, "4": 4,
    "0": 4, "1": 4, "2": 4, "3": 4, "5": 4, "6": 4, "7": 4, "8": 4,
    "44": 3, "43": 4, "45": 4, "434": 5, "435": 3,
    "40": 4, "41": 4, "42": 4, "46": 4, "47": 4, "48": 4,
    "404": 5, "414": 5, "424": 5, "464": 3, "474": 3, "484": 3,
    "04": 4, "14": 4, "24": 4, "34": 4, "54": 4, "64": 4, "74": 4, "84": 4,
}

# ══════════════════════════════════════════════
# DB
# ══════════════════════════════════════════════
def get_db():
    try:
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            return psycopg2.connect(db_url, sslmode='require')
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

def get_parties_recentes(limit=500):
    conn = get_db()
    if not conn: return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, created_at, joueur_gagnant, coups FROM parties ORDER BY id DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        result = []
        for r in rows:
            coups_str = r[3] if r[3] else ""
            coups_str = coups_str.replace("(", "").replace(")", "")
            result.append({
                "id": r[0], 
                "date": str(r[1])[:16] if r[1] else "", 
                "vainqueur": r[2] if r[2] else "", 
                "coups": coups_str, 
                "nb_coups": len(coups_str)
            })
        return result
    except Exception as e:
        print(f"Erreur get_parties_recentes: {e}")
        return []

def enregistrer_partie(sequence, vainqueur, nom=""):
    conn = get_db()
    if not conn: return
    try:
        cur = conn.cursor()
        if vainqueur == JAUNE: valeur_poids = 1
        elif vainqueur == ROUGE: valeur_poids = -1
        else: valeur_poids = 0

        cur.execute("SELECT id FROM parties WHERE coups = %s", (sequence,))
        if not cur.fetchone():
            cur.execute("INSERT INTO parties (created_at, joueur_gagnant, coups, statut) VALUES (%s, %s, %s, %s)",
                        (datetime.now(), vainqueur, sequence, "TERMINEE"))
            etat = ""
            for coup in sequence:
                id_act = etat if etat else "start"
                etat += str(coup)
                cur.execute("""
                    INSERT INTO positions (id_plateau, meilleur_coup, poids) VALUES (%s, %s, %s)
                    ON CONFLICT (id_plateau, meilleur_coup) DO UPDATE SET poids = positions.poids + EXCLUDED.poids
                """, (id_act, int(coup), valeur_poids))

        sym = calculer_symetrique(sequence)
        cur.execute("SELECT id FROM parties WHERE coups = %s", (sym,))
        if not cur.fetchone():
            cur.execute("INSERT INTO parties (created_at, joueur_gagnant, coups, statut) VALUES (%s, %s, %s, %s)",
                        (datetime.now(), vainqueur, sym, "TERMINEE"))
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
    sequence = "".join(map(str, historique))
    if not sequence: return None
    conn = get_db()
    if not conn: return None
    try:
        cur = conn.cursor()
        if couleur == ROUGE:
            cur.execute(
                "SELECT meilleur_coup FROM positions WHERE id_plateau = %s ORDER BY poids ASC LIMIT 1",
                (sequence,)
            )
        else:
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

def compter_pions(plateau):
    """Compte les pions de chaque couleur pour savoir à qui de jouer"""
    rouges = sum(row.count(ROUGE) for row in plateau)
    jaunes = sum(row.count(JAUNE) for row in plateau)
    return rouges, jaunes

def detecter_joueur_actuel(plateau):
    """Détecte à qui de jouer en fonction du nombre de pions"""
    rouges, jaunes = compter_pions(plateau)
    # Rouge commence toujours, donc si égalité c'est à rouge
    if rouges == jaunes:
        return ROUGE
    elif rouges > jaunes:
        return JAUNE
    else:
        return ROUGE  # Situation anormale, on dit rouge

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

def coup_urgent(plat, couleur):
    adv = ROUGE if couleur == JAUNE else JAUNE
    libres = [c for c in range(COLS) if plat[0][c] is None]
    for col in libres:
        temp = copy.deepcopy(plat)
        jouer_coup(temp, col, adv)
        v, _ = verifier_victoire(temp)
        if v == adv:
            return col
    return None

def meilleur_coup_ia(plat, historique, mode='ia_minimax', couleur=JAUNE):
    libres = [c for c in range(COLS) if plat[0][c] is None]
    if not libres: return None, "aucun"

    # 1. VICTOIRE IMMÉDIATE : si l'IA peut gagner en 1 coup, elle le fait
    for col in libres:
        temp = copy.deepcopy(plat)
        jouer_coup(temp, col, couleur)
        v, _ = verifier_victoire(temp)
        if v == couleur:
            return col, "victoire"

    # 2. Vérifier bibliothèque d'ouvertures (réponse immédiate)
    seq = "".join(map(str, historique))
    if seq in OUVERTURES and OUVERTURES[seq] in libres:
        return OUVERTURES[seq], "ouverture"

    if mode == 'ia_random':
        return random.choice(libres), "random"

    bloc = coup_urgent(plat, couleur)

    if mode == 'ia_db':
        coup_memoire = chercher_memoire(historique, couleur)
        if bloc is not None:
            return bloc, "blocage"
        if coup_memoire is not None and coup_memoire in libres:
            return coup_memoire, "memoire"
        return random.choice(libres), "random"

    if bloc is not None:
        return bloc, "blocage"
    coup_memoire = chercher_memoire(historique, couleur)
    if coup_memoire is not None and coup_memoire in libres:
        return coup_memoire, "memoire"
    col, _ = minimax(copy.deepcopy(plat), PROFONDEUR, -math.inf, math.inf, True, couleur)
    return col, "minimax"

def calculer_poids_colonnes(plat, couleur=JAUNE):
    libres = [c for c in range(COLS) if plat[0][c] is None]
    poids = [0] * COLS
    for c in libres:
        temp = copy.deepcopy(plat)
        jouer_coup(temp, c, couleur)
        _, score = minimax(temp, 2, -math.inf, math.inf, False, couleur)
        poids[c] = score
    return poids

def calculer_prediction(plat, couleur=JAUNE):
    libres = [c for c in range(COLS) if plat[0][c] is None]
    if not libres:
        return {"prediction": "nul", "score": 0, "coups_restants": 0, "joueur": couleur}
    # Victoire en 1 coup
    for col in libres:
        temp = copy.deepcopy(plat)
        jouer_coup(temp, col, couleur)
        v, _ = verifier_victoire(temp)
        if v == couleur:
            return {"prediction": "victoire", "score": 99000, "coups_restants": 1, "joueur": couleur}
    # Défaite en 1 coup
    adv = ROUGE if couleur == JAUNE else JAUNE
    for col in libres:
        temp = copy.deepcopy(plat)
        jouer_coup(temp, col, adv)
        v, _ = verifier_victoire(temp)
        if v == adv:
            return {"prediction": "defaite", "score": -99000, "coups_restants": 1, "joueur": couleur}
    # Menaces à 1 coup
    try:
        menace_j, menace_adv = detecter_menace_immediate(plat, couleur)
        if menace_j >= 2: return {"prediction": "victoire", "score": 80000, "coups_restants": 2, "joueur": couleur}
        if menace_j >= 1 and menace_adv == 0: return {"prediction": "victoire", "score": 70000, "coups_restants": 2, "joueur": couleur}
        if menace_adv >= 2: return {"prediction": "defaite", "score": -80000, "coups_restants": 2, "joueur": couleur}
    except: pass
    _, score = minimax(copy.deepcopy(plat), 3, -math.inf, math.inf, True, couleur)
    coups_restants = 0
    if abs(score) >= 50000:
        coups_restants = max(1, min(10, (100000 - abs(score)) // 12000 + 1))
    if score >= 50000: return {"prediction": "victoire", "score": score, "coups_restants": coups_restants, "joueur": couleur}
    if score <= -50000: return {"prediction": "defaite", "score": score, "coups_restants": coups_restants, "joueur": couleur}
    if len(libres) <= 5: return {"prediction": "nul", "score": score, "coups_restants": 0, "joueur": couleur}
    if score >= 2000: return {"prediction": "victoire", "score": score, "coups_restants": 0, "joueur": couleur}
    if score <= -2000: return {"prediction": "defaite", "score": score, "coups_restants": 0, "joueur": couleur}
    return {"prediction": "incertaine", "score": score, "coups_restants": 0, "joueur": couleur}


def detecter_menace_immediate(plat, couleur):
    adv = ROUGE if couleur == JAUNE else JAUNE
    menace_j, menace_adv = 0, 0
    for r in range(LIGNES):
        for c in range(COLS):
            for dr, dc in [(0,1),(1,0),(1,1),(1,-1)]:
                fen = []
                for i in range(4):
                    rr, cc = r+i*dr, c+i*dc
                    if 0 <= rr < LIGNES and 0 <= cc < COLS:
                        fen.append(plat[rr][cc])
                if len(fen) == 4:
                    if fen.count(couleur) == 3 and fen.count(None) == 1: menace_j += 1
                    if fen.count(adv) == 3 and fen.count(None) == 1: menace_adv += 1
    return menace_j, menace_adv

def trouver_sequence_victoire(plat, couleur, prof=6):
    adv = ROUGE if couleur == JAUNE else JAUNE
    def dfs(p, c, depth, seq):
        v, _ = verifier_victoire(p)
        if v == couleur: return seq
        if depth == 0: return None
        libres = [col for col in range(COLS) if p[0][col] is None]
        if not libres: return None
        scored = []
        for col in libres:
            t = copy.deepcopy(p)
            jouer_coup(t, col, c)
            _, s = minimax(t, min(2, depth-1), -math.inf, math.inf, c == couleur, couleur)
            scored.append((col, s))
        scored.sort(key=lambda x: -x[1] if c == couleur else x[1])
        for col, _ in scored[:4]:
            temp = copy.deepcopy(p)
            jouer_coup(temp, col, c)
            v2, _ = verifier_victoire(temp)
            if c == couleur and v2 == couleur: return seq + [col]
            if c == adv and v2 == adv: continue
            next_c = adv if c == couleur else couleur
            result = dfs(temp, next_c, depth-1, seq + [col])
            if result is not None: return result
        return None
    return dfs(plat, couleur, prof, [])

@app.route("/api/sequence_victoire", methods=["POST"])
def api_sequence_victoire():
    try:
        data = request.json
        plat = data["plateau"]
        joueur = data.get("joueur", JAUNE)
        prof = data.get("profondeur", 5)
        prediction = calculer_prediction(plat, joueur)
        seq = trouver_sequence_victoire(plat, joueur, prof)
        if seq is None: seq = []
        return jsonify({
            "sequence": seq,
            "nb_coups": len(seq),
            "prediction": prediction,
            "joueur": joueur
        })
    except Exception as e:
        return jsonify({"sequence": [], "nb_coups": 0, "prediction": {"prediction": "incertaine", "score": 0, "coups_restants": 0, "joueur": JAUNE}, "joueur": JAUNE, "erreur": str(e)})

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
    mode = data.get("mode", "ia_minimax")

    if col == -99:
        prediction = calculer_prediction(plat, joueur)
        return jsonify({"prediction": prediction})

    ligne = jouer_coup(plat, col, joueur)
    if ligne == -1:
        return jsonify({"erreur": "Colonne pleine"})

    historique.append(col)
    vainqueur, pions_gagnants = verifier_victoire(plat)

    poids = [0] * COLS
    prediction = {"prediction": "incertaine", "score": 0, "coups_restants": 0, "joueur": joueur}
    meilleur = None

    if not vainqueur and mode != "2_joueurs":
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
    couleur = data.get("couleur", JAUNE)

    col, source = meilleur_coup_ia(plat, historique, mode, couleur)
    if col is None:
        libres = [c for c in range(COLS) if plat[0][c] is None]
        col = random.choice(libres) if libres else 0

    ligne = jouer_coup(plat, col, couleur)
    historique.append(col)
    vainqueur, pions_gagnants = verifier_victoire(plat)

    poids = [0] * COLS
    prediction = {"prediction": "incertaine", "score": 0, "coups_restants": 0, "joueur": couleur}

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
    prediction = calculer_prediction(plat, joueur)
    return jsonify({
        "meilleur_coup": col, 
        "poids_colonnes": poids, 
        "source": source,
        "prediction": prediction
    })

@app.route("/api/pinceau", methods=["POST"])
def api_pinceau():
    data = request.json
    plat = data["plateau"]
    historique = data.get("historique", [])
    joueur = data.get("joueur", JAUNE)
    prof = data.get("profondeur", PROFONDEUR)
    col, source = meilleur_coup_ia(plat, historique, couleur=joueur)
    if source in ("minimax", "blocage", "random"):
        col2, _ = minimax(copy.deepcopy(plat), prof, -math.inf, math.inf, True, joueur)
        if col2 is not None: col = col2
        source = "minimax"
    prediction = calculer_prediction(plat, joueur)
    return jsonify({
        "meilleur_coup": col,
        "prediction": prediction,
        "source": source
    })

@app.route("/api/analyser", methods=["POST"])
def api_analyser():
    """Analyse un plateau peint : détecte à qui de jouer et donne la prédiction"""
    data = request.json
    plat = data["plateau"]
    
    rouges, jaunes = compter_pions(plat)
    joueur_actuel = detecter_joueur_actuel(plat)
    adversaire = JAUNE if joueur_actuel == ROUGE else ROUGE
    
    prediction = calculer_prediction(plat, joueur_actuel)
    poids = calculer_poids_colonnes(plat, joueur_actuel)
    col, source = meilleur_coup_ia(plat, [], couleur=joueur_actuel)
    
    return jsonify({
        "pions_rouges": rouges,
        "pions_jaunes": jaunes,
        "joueur_actuel": joueur_actuel,
        "prediction": prediction,
        "meilleur_coup": col,
        "poids_colonnes": poids,
        "source": source
    })

@app.route("/api/raison_abandon", methods=["POST"])
def api_raison_abandon():
    """Analyse pourquoi un joueur devrait abandonner"""
    data = request.json
    plat = data["plateau"]
    joueur = data.get("joueur", ROUGE)
    
    prediction = calculer_prediction(plat, joueur)
    adversaire = JAUNE if joueur == ROUGE else ROUGE
    pred_adv = calculer_prediction(plat, adversaire)
    
    raison = ""
    if prediction["prediction"] == "defaite":
        coups = prediction["coups_restants"]
        if coups > 0:
            raison = f"L'adversaire ({adversaire.upper()}) gagne dans environ {coups} coup(s). Position défavorable."
        else:
            raison = f"L'adversaire ({adversaire.upper()}) a une position dominante. Victoire probable pour lui."
    elif pred_adv["prediction"] == "victoire":
        coups = pred_adv["coups_restants"]
        raison = f"Analyse IA : {adversaire.upper()} voit une victoire dans {coups} coup(s)."
    else:
        raison = "La position est encore jouable. Pas de raison évidente d'abandonner."
    
    return jsonify({
        "raison": raison,
        "prediction_joueur": prediction,
        "prediction_adversaire": pred_adv
    })

@app.route("/api/parties")
def api_parties():
    limit = request.args.get("limit", 500, type=int)
    return jsonify(get_parties_recentes(limit))

@app.route("/api/rejouer/<int:partie_id>")
def api_rejouer(partie_id):
    conn = get_db()
    if not conn: return jsonify({"erreur": "DB indisponible"})
    try:
        cur = conn.cursor()
        cur.execute("SELECT coups, joueur_gagnant FROM parties WHERE id = %s", (partie_id,))
        r = cur.fetchone()
        cur.close(); conn.close()
        if not r: return jsonify({"erreur": "Partie introuvable"})
        coups_str = r[0].replace("(", "").replace(")", "") if r[0] else ""
        return jsonify({"sequence": coups_str, "vainqueur": r[1]})
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
    nom = data.get("nom", "")
    if not sequence:
        return jsonify({"erreur": "Séquence vide"})
    enregistrer_partie(sequence, vainqueur, nom)
    return jsonify({"ok": True, "sequence": sequence, "vainqueur": vainqueur})

@app.route("/api/renommer_partie", methods=["POST"])
def api_renommer_partie():
    data = request.json
    sequence = data.get("sequence", "")
    nom = data.get("nom", "")
    conn = get_db()
    if not conn: return jsonify({"erreur": "DB indisponible"})
    try:
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE parties ADD COLUMN IF NOT EXISTS nom VARCHAR(100)")
            conn.commit()
        except: conn.rollback()
        cur.execute("UPDATE parties SET nom = %s WHERE coups = %s", (nom, sequence))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"erreur": str(e)})

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