#!/usr/bin/env python3
"""
Job Fit Analyzer - NVIDIA NIM API
Calcule l'adéquation entre une offre d'emploi et ton profil
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
import requests

# ============ CONFIGURATION ============
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "meta/llama-3.1-70b-instruct"
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = os.environ.get("CAREER_OPS_DIR", "career-ops")

# ============ CHARGEMENT DES FICHIERS PROFIL ============
def load_profile_files(profile_dir=DEFAULT_PROFILE_DIR):
    """Charge les 4 fichiers de profil"""
    files = ["profile.yml", "portals.yml", "cv.md", "_profile.md"]
    profile_data = {}
    profile_root = Path(profile_dir)
    if not profile_root.is_absolute():
        profile_root = BASE_DIR / profile_root
    
    for filename in files:
        filepath = profile_root / filename
        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                profile_data[filename] = f.read()
        else:
            print(f"⚠️  Fichier manquant : {filename}")
            profile_data[filename] = f"Fichier {filename} non trouvé"
    
    return profile_data

def build_system_prompt(profile_data):
    """Construit le prompt système avec les données du profil"""
    return f"""
Tu es un expert en recrutement technique spécialisé dans l'analyse d'adéquation.

Voici mon profil complet :

=== IDENTITÉ (profile.yml) ===
{profile_data.get('profile.yml', 'Non fourni')}

=== MOTS-CLÉS CIBLES (portals.yml) ===
{profile_data.get('portals.yml', 'Non fourni')}

=== EXPÉRIENCE (cv.md) ===
{profile_data.get('cv.md', 'Non fourni')}

=== STRATÉGIE POSTULATION (_profile.md) ===
{profile_data.get('_profile.md', 'Non fourni')}

Pour chaque offre d'emploi que tu vas recevoir, tu dois répondre UNIQUEMENT au format JSON suivant, sans texte supplémentaire :

{{
  "score": 75,
  "forces": ["force1", "force2", "force3"],
  "faiblesses": ["faiblesse1", "faiblesse2", "faiblesse3"],
  "verdict": "recommandation (oui/non/avec ajustements)",
  "remarques": "commentaire optionnel"
}}

Le score est un nombre entre 0 et 100.
Plus il est élevé, plus le candidat correspond.
"""

def calculate_fit(jd_text, system_prompt, api_key, model):
    """Appelle l'API NVIDIA NIM pour calculer l'adéquation"""
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Voici l'offre d'emploi à analyser :\n\n{jd_text}"}
        ],
        "temperature": 0.2,  # Faible pour des résultats cohérents
        "max_tokens": 1000,
        "response_format": {"type": "json_object"}  # Force le format JSON si supporté
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(NVIDIA_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # Tente de parser le JSON retourné
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Si pas en JSON, essaie d'extraire
            print("⚠️  Réponse non-JSON, tentative d'extraction...")
            return {"raw": content, "score": 50, "erreur": "format_non_json"}
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur API : {e}")
        return {"score": 0, "erreur": str(e)}

# ============ FONCTIONS UTILITAIRES ============
def read_jd_from_file(filepath):
    """Lit une offre d'emploi depuis un fichier"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def read_jd_from_stdin():
    """Lit JD depuis l'entrée standard (pipe ou collage)"""
    print("📝 Colle ton offre d'emploi ci-dessous (Ctrl+D ou Ctrl+Z pour terminer) :")
    return sys.stdin.read()

def save_result(jd_text, result, output_file=None):
    """Sauvegarde le résultat dans un fichier"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    rapport = {
        "date": timestamp,
        "jd": jd_text[:500] + "..." if len(jd_text) > 500 else jd_text,
        "analyse": result
    }
    
    if output_file:
        filename = output_file
    else:
        filename = f"job_fit_report_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(rapport, f, indent=2, ensure_ascii=False)
    
    print(f"\n📄 Rapport sauvegardé : {filename}")
    return filename

def display_result(result):
    """Affiche joliment le résultat"""
    print("\n" + "="*50)
    print("📊 RÉSULTAT DE L'ANALYSE")
    print("="*50)
    
    score = result.get('score', '?')
    
    # Barre de progression visuelle
    bar_length = 30
    filled = int(bar_length * score / 100)
    bar = '█' * filled + '░' * (bar_length - filled)
    
    print(f"\n🎯 SCORE D'ADÉQUATION : {score}%")
    print(f"   [{bar}]")
    
    if score >= 80:
        print("   ✅ Excellent match !")
    elif score >= 60:
        print("   👍 Bon match, quelques ajustements possibles")
    elif score >= 40:
        print("   ⚠️  Match moyen, à étudier")
    else:
        print("   ❌ Faible adéquation")
    
    print("\n💪 FORCES :")
    for force in result.get('forces', []):
        print(f"   • {force}")
    
    print("\n🔧 FAIBLESSES / ÉCARTS :")
    for faiblesse in result.get('faiblesses', []):
        print(f"   • {faiblesse}")
    
    print(f"\n🎯 VERDICT : {result.get('verdict', 'Non spécifié')}")
    
    if result.get('remarques'):
        print(f"\n💬 REMARQUES : {result['remarques']}")
    
    if result.get('erreur'):
        print(f"\n⚠️  ERREUR : {result['erreur']}")

# ============ MAIN ============
def main():
    parser = argparse.ArgumentParser(description="Analyse d'adéquation CV ↔ Offre d'emploi via NVIDIA NIM")
    parser.add_argument("-j", "--jd", help="Fichier contenant l'offre d'emploi")
    parser.add_argument("-o", "--output", help="Fichier de sortie pour le rapport")
    parser.add_argument("-p", "--profile-dir", default=DEFAULT_PROFILE_DIR, help=f"Dossier contenant les fichiers profil (defaut: {DEFAULT_PROFILE_DIR})")
    parser.add_argument("--model", default=os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL), help=f"Modele NVIDIA NIM (defaut: {DEFAULT_MODEL})")
    parser.add_argument("--dry-run", action="store_true", help="Simule sans appel API")
    
    args = parser.parse_args()
    
    # Vérifie la clé API
    api_key = os.environ.get("NVIDIA_API_KEY", "").strip()

    if not api_key and not args.dry_run:
        print("❌ Erreur: Définis ta clé API NVIDIA")
        print("   export NVIDIA_API_KEY='ta_clé'")
        sys.exit(1)
    
    # Charge les fichiers profil
    print("📁 Chargement des fichiers profil...")
    profile_data = load_profile_files(args.profile_dir)
    
    # Construit le prompt système
    system_prompt = build_system_prompt(profile_data)
    
    # Lit l'offre d'emploi
    if args.jd:
        print(f"📄 Lecture de l'offre : {args.jd}")
        jd_text = read_jd_from_file(args.jd)
    else:
        jd_text = read_jd_from_stdin()
    
    if not jd_text.strip():
        print("❌ Offre d'emploi vide")
        sys.exit(1)
    
    print(f"📏 Offre d'emploi : {len(jd_text)} caractères")
    print(f"🧠 Modèle NVIDIA : {args.model}")
    
    # Calcule l'adéquation
    if args.dry_run:
        print("\n🔍 Mode DRY RUN - Aucun appel API")
        print(f"Prompt système (extrait) : {system_prompt[:200]}...")
        result = {"score": 75, "forces": ["Simulation"], "faiblesses": ["Mode dry-run"], "verdict": "simulation"}
    else:
        print("\n🤖 Appel de l'API NVIDIA NIM...")
        result = calculate_fit(jd_text, system_prompt, api_key, args.model)
    
    # Affiche et sauvegarde
    display_result(result)
    save_result(jd_text, result, args.output)

if __name__ == "__main__":
    main()
