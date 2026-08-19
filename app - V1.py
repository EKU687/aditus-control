import streamlit as st
import datetime
import re
import pandas as pd
from supabase import create_client, Client

# ==========================================
# 0. CONFIGURATION & STYLE MOBILE
# ==========================================
st.set_page_config(page_title="ADITUS-CONTROL", page_icon="👮‍♂️", layout="centered")

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
    except:
        return ["DINUM", "DOUMER"]

# ==========================================
# 2. LOGIQUE METIER ET RAZ
# ==========================================
def epurer_chaine(texte: str) -> str:
    if not texte:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(texte).strip().upper())

def reinitialiser_recherche():
    """Remise à zéro explicite du champ de recherche dans le session_state"""
    st.session_state["champ_recherche"] = ""

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
st.markdown("<h2 class='main-header'>👮‍♂️ ADITUS-CONTROL</h2>", unsafe_allow_html=True)

liste_sites = charger_sites()
site_selectionne = st.selectbox(
    "📍 **Votre poste de contrôle (Site actuel) :**", 
    liste_sites,
    index=0
)

st.caption(f"📅 Date du jour : **{datetime.date.today().strftime('%d/%m/%Y')}** | Site actif : **{site_selectionne}**")

# Champ de recherche relié au session_state
saisie = st.text_input(
    "🔎 Saisir une immatriculation ou un nom :",
    placeholder="Ex : 456913NC ou Nom / Organisme...",
    key="champ_recherche"
)

col_search, col_clear = st.columns([3, 1])
with col_search:
    btn_verifier = st.button("VÉRIFIER L'ACCÈS 🚀", type="primary")
with col_clear:
    # 🧹 Le bouton Effacer déclenche la vraie RAZ via on_click
    st.button("Effacer 🔄", on_click=reinitialiser_recherche)

st.divider()

# ==========================================
# 4. RÉSULTATS
# ==========================================
if saisie.strip():
    autorisations, total_site = verifier_acces_site(saisie, site_selectionne)
    
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
        st.warning(f"Aucune autorisation active trouvée à **{site_selectionne}** pour **{saisie}**.")