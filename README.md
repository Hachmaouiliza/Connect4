# CONNECT 4 · IA — SITE WEB

## Lancement local

```bash
pip install flask psycopg2-binary
python app.py
```
Puis ouvrir http://localhost:5000

## Hébergement sur Render.com (gratuit)

1. Créer un compte sur render.com
2. New > Web Service > connecter ton repo GitHub
3. Build command : `pip install -r requirements.txt`
4. Start command : `gunicorn app:app`
5. Ajouter les variables d'environnement DB (host, user, password, database)
6. Pour la DB : utiliser Render PostgreSQL (gratuit) ou garder ta DB locale en modifiant get_db()

## Fichiers

- `app.py` — serveur Flask + logique IA
- `templates/index.html` — interface complète
- `requirements.txt` — dépendances

## Fonctionnalités

✅ Jouer contre l'IA (Minimax / Aléatoire)  
✅ Humain vs Humain  
✅ IA vs IA  
✅ Choix couleur Rouge ou Jaune  
✅ Prédiction IA (victoire/défaite/nul/incertaine)  
✅ Meilleur coup suggéré  
✅ Pinceau — poser une situation manuellement  
✅ Dernier coup affiché  
✅ Parties sauvegardées en DB  
✅ Replay de parties  
✅ Stats DB en temps réel  
✅ Responsive mobile  
