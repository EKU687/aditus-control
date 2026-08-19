import streamlit as st
import cv2
import datetime
import re
import pandas as pd
from PIL import Image
import numpy as np
from supabase import create_client, Client

# ==========================================
# 0. CONFIGURATION & STYLE MOBILE / WEBCAM
# ==========================================
st.set_page_config(page_title="ADITUS-CONTROL V2", page_icon="👮‍♂️", layout="centered")

st.markdown("""
    <style>
        .stButton>button { width: 100%; height: 3.5em; font-size: 20px !important; font-weight: bold; }
        .main-header { text-align: center; color: #0056b3; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 1. INITIALISATION SUPABASE
# ==========================================
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets.get("SUPABASE_SERVICE_KEY", st.secrets["SUPABASE_KEY"])
    return create_client(url, key)

supabase = init_connection()

@st.cache_data(ttl=3600)
def charger_sites():
    try:
        req = supabase.table("Demandes_acces").select("site_id").execute()
        sites = sorted(list(set([row["site_id"] for row in req.data if row.get("site_id")])))
        return sites if sites else ["DINUM", "DOUMER"]
    except Exception:
        return ["DINUM", "DOUMER"]

# Chargement du moteur OCR (EasyOCR)
@st.cache_resource
def charger_moteur_ocr():
    try:
        import easyocr
        reader = easyocr.Reader(['en'], gpu=False)
        return reader
    except Exception as e:
        st.warning(f"⚠️ Moteur OCR non disponible : {e}")
        return None

# ==========================================
# 2. LOGIQUE METIER & OCR
# ==========================================
def epurer_chaine(texte: str) -> str:
    if not texte:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(texte).strip().upper())

def isoler_plaque_nc(texte_brut: str) -> str:
    """
    Extrait uniquement le motif d'une plaque NC (ex: 123456NC ou 123456)
    en ignorant la marque du véhicule ou autres textes parasites.
    """
    if not texte_brut:
        return ""
    
    texte_clean = re.sub(r"[^A-Z0-9]", "", str(texte_brut).upper())
    
    # 1. Motif exact : 1 à 6 chiffres suivis de 'NC'
    match_nc = re.search(r"(\d{1,6}NC)", texte_clean)
    if match_nc:
        return match_nc.group(1)
    
    # 2. Motif secondaire : bloc isolé de 5 à 6 chiffres (ex: 356198)
    match_chiffres = re.search(r"(\d{5,6})", texte_clean)
    if match_chiffres:
        return f"{match_chiffres.group(1)}NC"
    
    # Si aucun motif strict n'est trouvé, retourne la chaîne épurée brute
    return texte_clean

def reinitialiser_recherche():
    st.session_state["champ_recherche"] = ""
    if "photo_immat" in st.session_state:
        del st.session_state["photo_immat"]

def extraire_texte_image(image_bytes):
    """Analyse l'image capturée avec un pré-traitement pour améliorer la lecture."""
    reader = charger_moteur_ocr()
    if reader is None:
        return ""
    
    # Conversion en image PIL puis en tableau numpy pour OpenCV
    image = Image.open(image_bytes)
    image_np = np.array(image)
    
    # --- PRÉ-TRAITEMENT POUR L'OCR ---
    # 1. Convertir en niveaux de gris
    gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
    
    # 2. Augmenter le contraste (Seuillage adaptatif)
    # Cela permet d'isoler les caractères (noir) du fond (blanc/gris)
    processed_image = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    
    # Exécution de l'OCR sur l'image traitée
    resultats = reader.readtext(processed_image, detail=0)
    texte_brut = " ".join(resultats)
    
    return isoler_plaque_nc(texte_brut)

def verifier_acces_site(recherche_texte: str, site_poste_garde: str):
    date_jour = datetime.date.today().strftime("%Y-%m-%d")
    saisie_epuree = epurer_chaine(recherche_texte)
    
    try:
        req = supabase.table("Demandes_acces") \
            .select("*") \
            .eq("statut", "Validé") \
            .eq("site_id", site_poste_garde) \
            .lte("date_entree", date_jour) \
            .gte("date_sortie", date_jour) \
            .execute()
        
        resultats = req.data if req.data else []
        matches = []
        
        for d in resultats:
            immat_db = epurer_chaine(d.get("vehicule_immatriculation"))
            demandeur = str(d.get("email_demandeur", "")).lower()
            organisme = str(d.get("organisme", "")).lower()
            conducteur = str(d.get("vehicule_conducteur", "")).lower()
            
            match_immat = bool(saisie_epuree and (saisie_epuree in immat_db or immat_db in saisie_epuree))
            match_texte = bool(recherche_texte.lower() in demandeur or 
                               recherche_texte.lower() in organisme or 
                               recherche_texte.lower() in conducteur)
            
            if match_immat or match_texte:
                matches.append(d)
                
        return matches, len(resultats)
    except Exception as e:
        st.error(f"❌ Erreur lors du contrôle : {e}")
        return [], 0

# ==========================================
# 3. INTERFACE TERRAIN (VIGILE)
# ==========================================
st.markdown("<h2 class='main-header'>👮‍♂️ ADITUS-CONTROL V2</h2>", unsafe_allow_html=True)

liste_sites = charger_sites()
site_selectionne = st.selectbox(
    "📍 **Votre poste de contrôle (Site actuel) :**", 
    liste_sites,
    index=0
)

st.caption(f"📅 Date du jour : **{datetime.date.today().strftime('%d/%m/%Y')}** | Site actif : **{site_selectionne}**")

# Choix du mode de contrôle
tab_clavier, tab_camera = st.tabs(["⌨️ Saisie Manuelle", "📸 Scanner via Webcam"])

recherche_active = ""

with tab_clavier:
    saisie_manuelle = st.text_input(
        "🔎 Saisir une immatriculation ou un nom :",
        placeholder="Ex : 456913NC ou Nom / Organisme...",
        key="champ_recherche"
    )
    if saisie_manuelle:
        recherche_active = saisie_manuelle

with tab_camera:
    st.info("💡 Présentez la plaque d'immatriculation devant la webcam et cliquez sur **Prendre une photo**.")
    photo = st.camera_input("Capturer la plaque 📸", key="photo_immat")
    
    if photo:
        with st.spinner("🔍 Analyse de l'image et isolation de la plaque..."):
            plaque_detectee = extraire_texte_image(photo)
            
        if plaque_detectee:
            st.success(f"🤖 **Plaque détectée :** `{plaque_detectee}`")
            # Champ permettant d'ajuster rapidement si un caractère a été mal lu
            recherche_active = st.text_input("Ajuster la plaque si nécessaire :", value=plaque_detectee, key="correction_ocr")
        else:
            st.warning("⚠️ Aucune plaque NC lisible détectée. Rapprochez la plaque ou saisissez-la manuellement.")

# Boutons d'action
col_search, col_clear = st.columns([3, 1])
with col_search:
    btn_verifier = st.button("VÉRIFIER L'ACCÈS 🚀", type="primary")
with col_clear:
    st.button("Effacer 🔄", on_click=reinitialiser_recherche)

st.divider()

# ==========================================
# 4. RÉSULTATS
# ==========================================
if btn_verifier or recherche_active.strip():
    if not recherche_active.strip():
        st.warning("⚠️ Veuillez effectuer une saisie ou capturer une photo.")
    else:
        autorisations, total_site = verifier_acces_site(recherche_active, site_selectionne)
        
        if autorisations:
            st.success(f"🟢 **ACCÈS AUTORISÉ POUR {site_selectionne} ({len(autorisations)})**")
            
            for d in autorisations:
                with st.container():
                    st.markdown(f"### 📍 Site : {d.get('site_id')}")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.markdown(f"👤 **Demandeur :** {d.get('email_demandeur')}")
                        st.markdown(f"🏢 **Organisme :** {d.get('organisme')}")
                        st.markdown(f"👥 **Personnes :** {d.get('nombre_personnes', 1)}")
                    
                    with c2:
                        st.markdown(f"🚗 **Mode :** {d.get('mode_acces')}")
                        if d.get('mode_acces') == "Véhicule":
                            st.markdown(f"🆔 **Plaque :** `{d.get('vehicule_immatriculation')}`")
                            st.markdown(f"🚘 **Véhicule :** {d.get('vehicule_type')}")
                            st.markdown(f"🪪 **Conducteur :** {d.get('vehicule_conducteur')}")
                
                h_entree = str(d.get('heure_entree', '00:00:00'))[:5]
                h_sortie = str(d.get('heure_sortie', '23:59:00'))[:5]
                st.info(f"🕒 Horaires autorisés : de **{h_entree}** à **{h_sortie}**")
                st.divider()
        else:
            st.error(f"🔴 **ACCÈS REFUSÉ POUR LE SITE {site_selectionne}**")
            st.warning(f"Aucune autorisation active trouvée à **{site_selectionne}** pour **{recherche_active}**.")