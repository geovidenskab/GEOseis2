# GEOSeis2_0.py - VERSION 7 (Med Data Integration)
"""
GEOSeis v2.0 - Streamlined Seismic Analysis Platform
=====================================================
Version med data integration fra moduler
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import traceback
import warnings
import time
from obspy import UTCDateTime
from io import BytesIO
import xlsxwriter
from waveform_visualizer import WaveformVisualizer
import folium.plugins

# ==========================================
# TILFØJ: Import af egne moduler
# ==========================================
from toast_manager import ToastManager
from seismic_processor import EnhancedSeismicProcessor
from data_manager import StreamlinedDataManager

# ==========================================
# TILFØJ: Check ObsPy availability
# ==========================================
try:
    import obspy
    OBSPY_AVAILABLE = True
except ImportError:
    OBSPY_AVAILABLE = False
    st.error("❌ ObsPy er påkrævet for fuld funktionalitet. Installer med: pip install obspy")

# Import tekster direkte
from texts import texts, help_texts

# Konfiguration
st.set_page_config(
    page_title="GEOSeis 2.0",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Handle sprog parameter
def handle_language_change():
    """Handle language change from URL parameters"""
    try:
        params = st.experimental_get_query_params()
        if 'lang' in params:
            lang = params['lang'][0]
            if lang in ['da', 'en']:
                st.session_state.language = lang
                st.experimental_set_query_params()
    except:
        # Fallback hvis experimental metoder ikke virker
        pass

# Kald sprog handler
handle_language_change()

# Initialize sprog
if 'language' not in st.session_state:
    st.session_state.language = 'da'
    
def get_cached_taup_model():
    """Returnerer cached TauPyModel instans"""
    if 'taup_model' not in st.session_state:
        from obspy.taup import TauPyModel
        st.session_state.taup_model = TauPyModel(model="iasp91")
        print("TauPyModel created and cached")
    return st.session_state.taup_model

def get_cached_data_manager():
    """Returnerer cached DataManager instans"""
    if 'data_manager' not in st.session_state:
        st.session_state.data_manager = StreamlinedDataManager()
        print("StreamlinedDataManager created and cached")
    return st.session_state.data_manager

def get_cached_seismic_processor():
    """Returnerer cached SeismicProcessor instans"""
    if 'seismic_processor' not in st.session_state:
        st.session_state.seismic_processor = EnhancedSeismicProcessor()
        print("EnhancedSeismicProcessor created and cached")
    return st.session_state.seismic_processor

def ensure_utc_datetime(time_obj):
    """
    Simpel tid konvertering til UTCDateTime for Streamlit Cloud kompatibilitet.
    """
    if time_obj is None:
        return None
    
    if isinstance(time_obj, UTCDateTime):
        return time_obj
    
    try:
        # Prøv direkte konvertering først
        return UTCDateTime(time_obj)
    except:
        # Hvis det fejler, prøv via string
        try:
            return UTCDateTime(str(time_obj))
        except:
            raise ValueError(f"Kunne ikke konvertere tid: {time_obj}")

def format_earthquake_time(time_value, format_string='%d %b %Y'):
    """
    Formaterer earthquake tid fra enhver kilde.
    Håndterer ISO strings, datetime objekter, og UTCDateTime.
    
    Args:
        time_value: Tid som string, datetime, eller UTCDateTime
        format_string: strftime format string (default: '%d %b %Y')
        
    Returns:
        str: Formateret tidsstring eller fallback
    """
    if time_value is None:
        return "Unknown"
    
    # Hvis det allerede er en string, prøv at parse den
    if isinstance(time_value, str):
        try:
            # Parse ISO format
            if 'T' in time_value:
                # Håndter både med og uden Z
                time_value = time_value.replace('Z', '+00:00')
                dt = datetime.fromisoformat(time_value)
            else:
                # Prøv andre formater
                dt = datetime.strptime(time_value, '%Y-%m-%d %H:%M:%S')
            return dt.strftime(format_string)
        except:
            # Hvis parsing fejler, returner bare de første 10 karakterer (dato)
            return time_value[:10] if len(time_value) >= 10 else time_value
    
    # Check for datetime-lignende objekter
    elif hasattr(time_value, 'strftime'):
        try:
            return time_value.strftime(format_string)
        except:
            return str(time_value)[:10]
    
    # Check for ObsPy UTCDateTime
    elif hasattr(time_value, 'datetime'):
        try:
            return time_value.datetime.strftime(format_string)
        except:
            return str(time_value)[:10]
    
    # Sidste forsøg - prøv at konvertere til datetime
    else:
        try:
            dt = datetime.fromtimestamp(float(time_value))
            return dt.strftime(format_string)
        except:
            return str(time_value)[:10] if len(str(time_value)) >= 10 else str(time_value)

def safe_get_earthquake_field(earthquake, field, default='Unknown'):
    """
    Sikkert henter felt fra earthquake dictionary eller objekt.
    
    Args:
        earthquake: Dictionary eller objekt med earthquake data
        field: Felt navn at hente
        default: Default værdi hvis felt ikke findes
        
    Returns:
        Feltværdi eller default
    """
    if earthquake is None:
        return default
    
    if isinstance(earthquake, dict):
        return earthquake.get(field, default)
    else:
        return getattr(earthquake, field, default)



class GEOSeisV2:
    """Main application class for GEOSeis 2.0"""
    
    def __init__(self):
        self.setup_session_state()
        self.load_modern_css()
        
        # ==========================================
        # CACHED MANAGERS - Initialiseres kun én gang!
        # ==========================================
        
        # Toast Manager (lightweight - behøver ikke caching)
        self.toast_manager = ToastManager()
        
        # Data Manager - CACHED
        if OBSPY_AVAILABLE:
            if 'data_manager' not in st.session_state:
                from data_manager import StreamlinedDataManager
                st.session_state.data_manager = StreamlinedDataManager()
                print("StreamlinedDataManager created ONCE in session state")
            self.data_manager = st.session_state.data_manager
        else:
            self.data_manager = None
        
        # Seismic Processor - CACHED
        if OBSPY_AVAILABLE:
            if 'seismic_processor' not in st.session_state:
                from seismic_processor import EnhancedSeismicProcessor
                st.session_state.seismic_processor = EnhancedSeismicProcessor()
                print("EnhancedSeismicProcessor created ONCE in session state")
            self.processor = st.session_state.seismic_processor
        else:
            self.processor = None
        
        # Waveform Visualizer (lightweight - behøver ikke caching)
        self.visualizer = WaveformVisualizer()
        
        # Check IRIS forbindelse
        if self.data_manager and not self.data_manager.client:
            st.warning("⚠️ Kunne ikke oprette forbindelse til IRIS. Nogle funktioner er begrænsede.")
    
    def load_modern_css(self):
        """Load modern CSS styling for the entire app with compact header"""
        st.markdown("""
        <style>
        /* Reset og base styling */
        * {
            box-sizing: border-box;
        }
        
        /* KOMPAKT HEADER STYLING START */
        /* Fjern Streamlit standard padding helt i toppen */
        .stApp > header {
            height: 0rem !important;
        }
        
        .block-container {
            padding-top: 0rem !important;  /* Ændret fra 2rem */
            padding-bottom: 2rem !important;
            max-width: 100%;
        }
        
        /* Fjern spacing fra første element */
        .element-container:first-child {
            margin-top: 0 !important;
        }
        
        div[data-testid="stVerticalBlock"] > div:first-child {
            gap: 0 !important;
        }
        
        /* Kompakt header design - matcher dit eksisterende farvetema */
        .main-header {
            background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 50%, #D6EBFD 100%);
            padding: 0.75rem 2rem;  /* Reduceret padding */
            margin: -1rem -3rem 1.5rem -3rem;  /* Negativ margin for at starte helt oppe */
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border-bottom: 1px solid #E9ECEF;
            position: relative;
            z-index: 100;
        }
        
        /* Header content container */
        .header-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            max-width: 1400px;
            margin: 0 auto;
        }
        
        /* Title section */
        .title-section {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        /* Earth emoji - mindre størrelse */
        .earth-emoji {
            font-size: 3.75rem;  /* Reduceret fra 2.5rem */
            line-height: 1;
        }
        
        /* Title container */
        .title-text {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
        }
        
        /* Kompakt titel - matcher dit h1 styling */
        .main-title {
            color: #2C3E50 !important;
            font-size: 1.75rem !important;  /* Reduceret fra 2rem */
            font-weight: 700 !important;
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.1 !important;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', sans-serif;
        }
        
        /* Kompakt subtitle - matcher dit p styling */
        .main-subtitle {
            color: #495057 !important;
            font-size: 0.9rem !important;  /* Reduceret fra 1.1rem */
            margin: 0 !important;
            padding: 0 !important;
            font-weight: 400 !important;
        }
        
        /* Language flags - matcher din lang-button styling */
        .language-flags {
            display: flex;
            gap: 0.75rem;
            align-items: center;
        }
        
        .language-flags a {
            display: inline-block;
            padding: 4px;
            cursor: pointer;
            font-size: 1.3rem;  /* Lidt mindre end original 24px */
            opacity: 0.6;
            transition: all 0.2s ease;
            border-radius: 4px;
            text-decoration: none;
        }
        
        .language-flags a:hover {
            opacity: 1;
            transform: scale(1.15);
        }
        
        /* Active language button - tilføj dette til din CSS */
        .lang-button.active {
            opacity: 1 !important;
            transform: scale(1.1);
            background-color: rgba(93, 173, 226, 0.1);
            border-radius: 4px;
        }
        
        /* Sikre at første content efter header ikke har ekstra margin */
        .main-header + div {
            margin-top: 0 !important;
        }
        
        /* KOMPAKT HEADER STYLING SLUT */
        
        /* Main container styling */
        .main {
            padding: 0;
            max-width: 1400px;
            margin: 0 auto;
        }
        
        /* Ensartet typografi */
        .stApp {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Helvetica', sans-serif;
        }
        
        /* Alle overskrifter samme stil */
        h1, h2, h3, h4, h5, h6,
        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
            color: #2C3E50 !important;
            font-weight: 600 !important;
            line-height: 1.3 !important;
            margin-top: 1rem !important;
            margin-bottom: 0.5rem !important;
        }
        
        h1, .stMarkdown h1 { font-size: 2rem !important; }
        h2, .stMarkdown h2 { font-size: 1.5rem !important; }
        h3, .stMarkdown h3 { font-size: 1.25rem !important; }
        
        /* Ensartet paragraph styling */
        p, .stMarkdown p {
            color: #34495E !important;
            font-size: 1rem !important;
            line-height: 1.6 !important;
            margin-bottom: 0.5rem !important;
        }
        
        /* Brug dette hvis du vil have label og værdi på samme linje */
        [data-testid="metric-container"] {
            display: flex !important;
            align-items: baseline !important;
            gap: 0.5rem !important;
            background: transparent !important;
            box-shadow: none !important;
            padding: 0.2rem 0 !important;
        }

        [data-testid="metric-container"] > div:nth-child(1) {
            font-size: 0.7rem !important;
            color: #6C757D !important;
            font-weight: 400 !important;
        }

        [data-testid="metric-container"] > div:nth-child(2) {
            font-size: 0.9rem !important;
            color: #2C3E50 !important;
            font-weight: 600 !important;
        }
        
        /* ALLE KNAPPER - SAMME GRUNDTEMA: LYS GRÅ TIL LYS BLÅ */
        /* Standard knapper */
        .stButton > button {
            background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 100%) !important;
            color: #495057 !important;
            border: 1px solid #E9ECEF !important;
            padding: 0.6rem 1.5rem !important;
            font-size: 1rem !important;
            font-weight: 500 !important;
            border-radius: 8px !important;
            transition: all 0.2s ease !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05) !important;
            text-align: center !important;
            min-height: 42px !important;
        }
        
        .stButton > button:hover {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            border-color: #B8DAFF !important;
            transform: translateY(-1px) !important;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1) !important;
        }
        
        .stButton > button:active {
            transform: translateY(0) !important;
        }
        
        /* Station liste knapper - mindre og mere diskret */
        [data-testid="column"] .stButton > button {
            width: 100% !important;
            text-align: left !important;
            padding: 0.45rem 0.75rem !important;
            font-size: 0.875rem !important;
            min-height: 36px !important;
            line-height: 1.4 !important;
        }
        
        
        /* Aktiv/primær knap - samme tema men med blå accent */
        .stButton > button[kind="primary"],
        [data-testid="column"] .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            color: #0056B3 !important;
            border: 1.5px solid #5DADE2 !important;
            font-weight: 600 !important;
            box-shadow: 0 0 0 2px rgba(93, 173, 226, 0.1) !important;
        }
        
        .stButton > button[kind="primary"]:hover,
        [data-testid="column"] .stButton > button[kind="primary"]:hover {
            background: linear-gradient(135deg, #D6EBFD 0%, #C3E4FD 100%) !important;
            border-color: #3498DB !important;
            box-shadow: 0 0 0 3px rgba(93, 173, 226, 0.15) !important;
        }
        
        /* Info bokse */
        .stInfo {
            background-color: #E8F4FD !important;
            border-left: 4px solid #5DADE2 !important;
            padding: 1rem !important;
            border-radius: 8px !important;
            font-size: 1rem !important;
        }
        
        .stWarning {
            background-color: #FFF3CD !important;
            border-left: 4px solid #FFC107 !important;
            padding: 1rem !important;
            border-radius: 8px !important;
        }
        
        .stSuccess {
            background-color: #D4EDDA !important;
            border-left: 4px solid #28A745 !important;
            padding: 1rem !important;
            border-radius: 8px !important;
        }
        
        .stError {
            background-color: #F8D7DA !important;
            border-left: 4px solid #DC3545 !important;
            padding: 1rem !important;
            border-radius: 8px !important;
        }
        
        /* Header sektion - FJERNET da vi bruger main-header nu */
        /* .header-wrapper styling fjernet */
        
        /* Sidebar styling - samme knap tema */
        section[data-testid="stSidebar"] {
            background: #F8F9FA;
            padding-top: 2rem;
            width: 260px !important;
        }
        
        section[data-testid="stSidebar"] > div:first-child {
            width: 260px !important;
        }
        
        /* Sidebar knapper - samme tema som hovedknapper */
        section[data-testid="stSidebar"] .stButton > button {
            background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 100%) !important;
            color: #495057 !important;
            border: 1px solid #E9ECEF !important;
            font-size: 0.95rem !important;
            padding: 0.5rem 1rem !important;
            width: 100%;
            text-align: left !important;
        }
        
        section[data-testid="stSidebar"] .stButton > button:hover {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            border-color: #B8DAFF !important;
        }
        
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            color: #0056B3 !important;
            border: 1.5px solid #5DADE2 !important;
            font-weight: 600 !important;
        }
        
        /* Ekspander styling */
        section[data-testid="stSidebar"] .streamlit-expanderHeader {
            font-size: 1rem !important;
            font-weight: 500 !important;
            color: #2C3E50 !important;
            background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 100%) !important;
            border: 1px solid #E9ECEF !important;
            border-radius: 8px !important;
            padding: 0.75rem 1rem !important;
        }
        
        section[data-testid="stSidebar"] .streamlit-expanderHeader:hover {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            border-color: #B8DAFF !important;
        }
        
        /* Column spacing */
        [data-testid="column"] {
            padding: 0 0.5rem !important;
        }
        
        /* Text styling */
        .stText {
            font-size: 0.875rem !important;
            color: #6C757D !important;
        }
        
        /* Clean dividers */
        hr {
            margin: 1.5rem 0 !important;
            border: none !important;
            border-top: 1px solid #E1E8ED !important;
        }
        
        /* Slider styling - samme blå tema */
        .stSlider > div > div > div > div {
            background-color: #5DADE2;
        }
        
        /* Tab styling */
        .stTabs [data-baseweb="tab-list"] {
            background-color: rgba(248, 249, 250, 0.5);
            border-radius: 10px;
            padding: 5px;
        }
        
        .stTabs [data-baseweb="tab"] {
            color: #2C3E50;
            font-weight: 500;
        }
        
        .stTabs [aria-selected="true"] {
            background-color: white;
            color: #2C3E50;
            font-weight: 600;
            border-radius: 8px;
        }
        
        /* Feature cards */
        .feature-card {
            background: white;
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
            border: 1px solid #E1E8ED;
            transition: all 0.3s ease;
            height: 100%;
        }
        
        .feature-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
            border-color: #5DADE2;
        }
        
        /* Progress bar */
        .stProgress > div > div > div > div {
            background-color: #5DADE2;
        }
        
        /* Form submit button - samme tema */
        .stForm [data-testid="stFormSubmitButton"] > button {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            color: #0056B3 !important;
            border: 1.5px solid #5DADE2 !important;
            font-weight: 600 !important;
        }
        
        .stForm [data-testid="stFormSubmitButton"] > button:hover {
            background: linear-gradient(135deg, #D6EBFD 0%, #C3E4FD 100%) !important;
            border-color: #3498DB !important;
        }
        
        /* Download button - samme tema */
        .stDownloadButton > button {
            background: linear-gradient(135deg, #F8F9FA 0%, #E8F4FD 100%) !important;
            color: #495057 !important;
            border: 1px solid #E9ECEF !important;
        }
        
        .stDownloadButton > button:hover {
            background: linear-gradient(135deg, #E8F4FD 0%, #D6EBFD 100%) !important;
            border-color: #B8DAFF !important;
        }
        
        /* Remove Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        </style>
        """, unsafe_allow_html=True)

    def setup_session_state(self):
        """Initialize all session state variables"""
        # Navigation
        if 'current_view' not in st.session_state:
            st.session_state.current_view = 'start'
        
        # Language
        if 'language' not in st.session_state:
            st.session_state.language = 'da'
        
        # Data state
        if 'latest_earthquakes' not in st.session_state:
            st.session_state.latest_earthquakes = None
        
        if 'search_results' not in st.session_state:
            st.session_state.search_results = None
        
        # Selection state
        if 'selected_earthquake' not in st.session_state:
            st.session_state.selected_earthquake = None
        
        if 'selected_station' not in st.session_state:
            st.session_state.selected_station = None
        
        if 'station_list' not in st.session_state:
            st.session_state.station_list = None
        
        if 'waveform_data' not in st.session_state:
            st.session_state.waveform_data = None
        
        # Search parameters
        if 'magnitude_range' not in st.session_state:
            st.session_state.magnitude_range = (6.5, 8.0)
        
        if 'year_range' not in st.session_state:
            current_year = datetime.now().year
            st.session_state.year_range = (2023, current_year)
        
        if 'depth_range' not in st.session_state:
            st.session_state.depth_range = (1, 200)
        
        if 'max_earthquakes' not in st.session_state:
            st.session_state.max_earthquakes = 10
        
        # Station search parameters
        if 'target_stations' not in st.session_state:
            st.session_state.target_stations = 3
        
        if 'station_search_radius' not in st.session_state:
            st.session_state.station_search_radius = 2000
            
            
    def render_header(self):
        """Renderer kompakt header med sprog toggle"""
        st.markdown(f'''
        <div class="main-header">
            <div class="header-content">
                <div class="title-section">
                    <span class="earth-emoji">🌍</span>
                    <div class="title-text">
                        <h1 class="main-title">{texts[st.session_state.language]["app_title"]}</h1>
                        <p class="main-subtitle">{texts[st.session_state.language]["app_subtitle"]}</p>
                    </div>
                </div>
                <div class="language-flags">
                    <a href="?lang=da" title="Dansk">
                        <span class="lang-button {"active" if st.session_state.language == "da" else ""}">🇩🇰</span>
                    </a>
                    <a href="?lang=en" title="English">
                        <span class="lang-button {"active" if st.session_state.language == "en" else ""}">🇬🇧</span>
                    </a>
                </div>
            </div>
        </div>
        ''', unsafe_allow_html=True)
    def render_sidebar(self):
            """Render the sidebar navigation - kun knapper"""
            with st.sidebar:
                # Logo/Title
                st.markdown("## 🌍 GEOSeis 2.0")
                st.markdown("---")
                
                # Startside
                if st.button(texts[st.session_state.language]['nav_home'], use_container_width=True,
                            type="primary" if st.session_state.current_view == 'start' else "secondary"):
                    st.session_state.current_view = 'start'
                
                # Søg jordskælv
                if st.button(texts[st.session_state.language]['nav_earthquake_search'], use_container_width=True,
                            type="primary" if st.session_state.current_view == 'data_search' else "secondary"):
                    st.session_state.current_view = 'data_search'
                
                # Stationsvalg
                if st.button("Stationsvalg", use_container_width=True,
                            type="primary" if st.session_state.current_view == 'analysis_stations' else "secondary"):
                    st.session_state.current_view = 'analysis_stations'
                
                # Seismogram - kun synlig hvis en station er valgt
                if st.session_state.get('selected_station'):
                    if st.button(texts[st.session_state.language]['waveform_title'], use_container_width=True,
                                type="primary" if st.session_state.current_view == 'analysis_waveform' else "secondary"):
                        st.session_state.current_view = 'analysis_waveform'
                
                # Magnitude beregning - kun synlig hvis vi har waveform data
                if st.session_state.get('waveform_data'):
                    if st.button(texts[st.session_state.language]['nav_magnitude_calc'], use_container_width=True,
                                type="primary" if st.session_state.current_view == 'analysis_magnitude' else "secondary"):
                        st.session_state.current_view = 'analysis_magnitude'
                
                # Excel export - kun synlig hvis vi har data
                if st.session_state.get('waveform_data'):
                    if st.button(texts[st.session_state.language]['nav_export'], use_container_width=True,
                                type="primary" if st.session_state.current_view == 'tools_export' else "secondary"):
                        st.session_state.current_view = 'tools_export'
                
                # Om sektion
                st.markdown("---")
                if st.button(texts[st.session_state.language]['nav_about'], use_container_width=True,
                            type="primary" if st.session_state.current_view == 'about' else "secondary"):
                    st.session_state.current_view = 'about'

           
    def render_earthquake_results(self, earthquakes):
        """Display earthquake search results"""
        if not earthquakes:
            st.warning("Ingen jordskælv fundet med de valgte kriterier")
            return
        
        #st.success(f"Fandt {len(earthquakes)} jordskælv")
        
        # Vis resultater som klikbare rækker
        for idx, eq in enumerate(earthquakes[:10]):  # Vis max 10
            col1, col2, col3, col4, col5 = st.columns([2, 2, 1, 1, 1])
            
            with col1:
                if st.button(
                    f"M{eq['magnitude']:.1f} - {eq.get('location', 'Unknown')[:30]}",
                    key=f"eq_select_{idx}",
                    use_container_width=True
                ):
                    # Gem valgt jordskælv og skift til stationsvalg (ikke seismogram)
                    st.session_state.selected_earthquake = eq
                    st.session_state.current_view = 'analysis_stations'  # ÆNDRET
                    # Reset station data
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    
                    # Vis toast
                    self.toast_manager.show(
                        f"Valgt: M{eq['magnitude']:.1f} jordskælv",
                        toast_type='success',
                        duration=2.0
                    )
                    st.rerun()
            
            with col2:
                st.text(format_earthquake_time(eq['time'], '%d-%m-%Y'))
            
            with col3:
                st.text(f"{eq.get('depth', 0):.0f} km")
            
            with col4:
                st.text(f"{eq.get('latitude', 0):.1f}°")
            
            with col5:
                st.text(f"{eq.get('longitude', 0):.1f}°")
        
        # Vis også på kort
        st.markdown("### 🗺️ Kort visning")
        eq_df = pd.DataFrame(earthquakes)
        earthquake_map = self.create_optimized_map(eq_df)
        
        if earthquake_map:
            map_data = st_folium(
                earthquake_map,
                width=950,
                height=500,
                returned_objects=["last_object_clicked", "last_clicked"],
                key="search_results_map"
            )
            
            # Process klik på kortet
            if map_data and (map_data.get("last_clicked") or map_data.get("last_object_clicked")):
                clicked_eq = self.process_earthquake_click(map_data, eq_df)
                
                if clicked_eq:
                    st.session_state.selected_earthquake = clicked_eq
                    st.session_state.current_view = 'analysis_stations'  # ÆNDRET
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.rerun()

    def render_data_search_view(self):
        """Render the earthquake search view"""
        st.markdown(f"## {texts[st.session_state.language]['nav_earthquake_search']}")
        
        # Variabler til at holde form værdier
        mag_range = None
        year_range = None
        depth_range = None
        max_results = None
        
        # Search form
        with st.form("earthquake_search"):
            st.markdown(f"### {texts[st.session_state.language]['search_criteria']}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                mag_range = st.slider(
                    texts[st.session_state.language]['magnitude_range'],
                    min_value=4.0,
                    max_value=9.0,
                    value=st.session_state.magnitude_range,
                    step=0.1,
                    help=texts[st.session_state.language]['magnitude_help']
                )
                
                year_range = st.slider(
                    texts[st.session_state.language]['date_range'],
                    min_value=1990,
                    max_value=datetime.now().year,
                    value=st.session_state.year_range,
                    help=texts[st.session_state.language]['date_help']
                )
            
            with col2:
                depth_range = st.slider(
                    texts[st.session_state.language]['depth_range'],
                    min_value=0,
                    max_value=700,
                    value=st.session_state.depth_range,
                    step=10,
                    help=texts[st.session_state.language]['depth_help']
                )
                
                max_results = st.number_input(
                    texts[st.session_state.language]['max_results'],
                    min_value=1,
                    max_value=100,
                    value=25
                )
            
            submitted = st.form_submit_button(
                texts[st.session_state.language]['search_button'],
                type="primary"
            )
            
            # Gem form værdier i session state når submitted
            if submitted:
                st.session_state.form_submitted = True
                st.session_state.form_mag_range = mag_range
                st.session_state.form_year_range = year_range
                st.session_state.form_depth_range = depth_range
                st.session_state.form_max_results = max_results
        
        # UDEN FOR form - check om form blev submitted
        if st.session_state.get('form_submitted', False) and self.data_manager:
            # Hent værdier fra session state
            mag_range = st.session_state.get('form_mag_range', st.session_state.magnitude_range)
            year_range = st.session_state.get('form_year_range', st.session_state.year_range)
            depth_range = st.session_state.get('form_depth_range', st.session_state.depth_range)
            max_results = st.session_state.get('form_max_results', 25)
            
            # Opdater permanente session state værdier
            st.session_state.magnitude_range = mag_range
            st.session_state.year_range = year_range
            st.session_state.depth_range = depth_range
            
            # Reset submitted flag
            st.session_state.form_submitted = False
            
            with st.spinner(texts[st.session_state.language]['loading']):
                earthquakes = self.data_manager.fetch_latest_earthquakes(
                    magnitude_range=mag_range,
                    year_range=year_range,
                    depth_range=depth_range,
                    limit=max_results
                )
                
                if earthquakes:
                    st.session_state.search_results = earthquakes
                    st.success(f"✅ Fandt {len(earthquakes)} jordskælv")
                    
                    # Vis toast notification
                    self.toast_manager.show(
                        f"Fandt {len(earthquakes)} jordskælv",
                        toast_type='success',
                        duration=3.0
                    )
                else:
                    st.warning("Ingen jordskælv fundet med de valgte kriterier")
        
        # Vis resultater UDEN FOR form
        if st.session_state.get('search_results'):
            self.render_earthquake_results(st.session_state.search_results)

    def render_earthquake_map(self, earthquakes):
        """Render Folium map with earthquakes - IDENTISK med version 1.7"""
        if not earthquakes:
            return
        
        # Konverter til DataFrame
        eq_df = pd.DataFrame(earthquakes)
        
        # KORREKT: Brug create_optimized_map fra version 1.7
        earthquake_map = self.create_optimized_map(eq_df)
        
        if earthquake_map:
            map_data = st_folium(
                earthquake_map, 
                width=950, 
                height=650,
                returned_objects=["last_object_clicked", "last_clicked"],
                key="earthquake_map_start"
            )
            
            # Check for clicks
            if map_data and (map_data.get("last_clicked") or map_data.get("last_object_clicked")):
                # Process click (kunne implementeres senere)
                pass

    def get_earthquake_color_and_size(self, magnitude):
        """Bestemmer farve og størrelse for jordskælv markører baseret på magnitude."""
        if magnitude >= 8.0:
            return 'purple', 15  # Lilla for de største jordskælv
        elif magnitude >= 7.5:
            return 'darkred', 12
        elif magnitude >= 7.0:
            return 'red', 10
        elif magnitude >= 6.5:
            return 'orange', 8
        elif magnitude >= 6.0:
            return 'yellow', 6
        elif magnitude >= 5.0:
            return 'lightgreen', 5
        else:
            return 'gray', 4


    def create_optimized_map(self, earthquakes_df, stations=None):
        """
        Opretter optimeret Folium kort - KOPI fra version 1.7
        """
        if earthquakes_df.empty:
            return None
        
        # GLOBAL VIEW for startside
        m = folium.Map(
            location=[10, 70],  # Asien centrum
            zoom_start=2,
            tiles='Esri_WorldImagery',  # VIGTIGT: Samme baggrundskort som 1.7
            attr=' ',
            scrollWheelZoom=True,
            doubleClickZoom=True,
            dragging=True,
            zoomControl=False,
            world_copy_jump=True
        )
        folium.plugins.Fullscreen(
            position='topright',
            title='Fuld skærm',
            title_cancel='Luk fuld skærm',
            force_separate_button=True
        ).add_to(m)
        
        # Tilføj jordskælv markører
        for idx, eq in earthquakes_df.iterrows():
            color, radius = self.get_earthquake_color_and_size(eq['magnitude'])
            
            # Sikrer rigtig tid
            eq_time = ensure_utc_datetime(eq['time'])
            time_str = format_earthquake_time(eq['time']) if eq_time else 'Unknown'
            
            # Normal cirkel markør
            folium.CircleMarker(
                location=[eq['latitude'], eq['longitude']],
                radius=radius,
                tooltip=f"M{eq['magnitude']:.1f} - {time_str} (Klik for detaljer)",
                color='black',
                opacity=0.6,
                fillColor=color,
                fillOpacity=0.8,
                weight=1
            ).add_to(m)
        
        # SIGNATURFORKLARING - VIGTIGT fra version 1.7
        legend_html = '''
        <div style="position: fixed; 
                    top: 10px; left: 10px; width: 105px; height: 175px; 
                    background-color: rgba(255, 255, 255, 0.9);
                    border: 2px solid grey; z-index: 9999; font-size: 12px;
                    border-radius: 5px; padding: 10px;
                    ">
        <p style="margin: 0; font-weight: bold; text-align: center;">Magnitude</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:purple"></i> M ≥ 8.0</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:darkred"></i> M 7.5-7.9</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:red"></i> M 7.0-7.4</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:orange"></i> M 6.5-6.9</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:yellow"></i> M 6.0-6.4</p>
        <p style="margin: 2px 0;"><i class="fa fa-circle" style="color:lightgreen"></i> M 5.0-5.9</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m

    def render_start_view(self):
        """Render the start view with latest earthquakes - Kortfattet version"""
        # To kolonner layout
        col_text, col_map = st.columns([1, 2])
        
        with col_text:
            # Overskrift
            st.markdown(f"### {texts[st.session_state.language]['welcome_title']}")
            
            # Kort intro tekst
            if st.session_state.language == 'da':
                st.markdown("""
                **GEOSeis** giver direkte adgang til rigtige seismiske data fra jordskælv verden over.
                
                **Kom i gang:**
                1. Klik på et jordskælv på kortet er fra listen
                2. Vælg seismiske stationer
                3. Analyser data
                4. Eksporter resultater
                
                **Funktioner:**
                - IRIS datadatabase integration
                - Ms magnitude beregning
                - Signal filtrering
                - Excel eksport
                """)
            else:
                st.markdown("""
                **GEOseis** provides direct access to real seismic data from earthquakes worldwide.
                
                **Get started:**
                1. Click an earthquake on the map
                2. Select seismic stations
                3. Analyze data
                4. Export results
                
                **Features:**
                - IRIS database integration
                - Ms magnitude calculation
                - Signal filtering
                - Excel export
                """)
            
            # Quick stats hvis data er hentet
            if 'latest_earthquakes' in st.session_state and st.session_state.latest_earthquakes:
                st.markdown("---")
                num_eq = len(st.session_state.latest_earthquakes)
                if st.session_state.language == 'da':
                    st.info(f"{num_eq} jordskælv M≥6.5 de seneste 180 dage. Klik på et jordskælv for at starte →")
                else:
                    st.info(f"{num_eq} earthquakes M≥6.5 last 180 days. Click an earthquake to start →")
            
            
        with col_map:
            # Kort overskrift
            st.markdown(f"#### {texts[st.session_state.language]['welcome_subtitle']}")
            
            # Hent og vis jordskælv på kort
            if self.data_manager and OBSPY_AVAILABLE:
                # Check cache først
                if 'latest_earthquakes' not in st.session_state or not st.session_state.latest_earthquakes:
                    with st.spinner(texts[st.session_state.language]['loading_earthquakes']):
                        try:
                            # Hent seneste store jordskælv
                            earthquakes = self.data_manager.get_latest_significant_earthquakes(
                                min_magnitude=6.5,
                                days=180
                            )
                            if earthquakes:
                                st.session_state.latest_earthquakes = earthquakes
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
                            earthquakes = None
                else:
                    earthquakes = st.session_state.latest_earthquakes
                
                # Vis kort med jordskælv - BRUG render_earthquake_map_interactive!
                if st.session_state.get('latest_earthquakes'):
                    # Brug den eksisterende interaktive kort funktion
                    self.render_earthquake_map_interactive(st.session_state.latest_earthquakes)
                else:
                    if st.session_state.language == 'da':
                        st.info("📍 Ingen nyere jordskælv M≥6.5 fundet.")
                    else:
                        st.info("📍 No recent earthquakes M≥6.5 found.")
            else:
                st.warning("⚠️ Data manager not available.")

    def render_analysis_stations_view(self):
        """Render station selection view med kort"""
        st.markdown("## Stationsvalg")
        
        # Check om et jordskælv er valgt
        if not st.session_state.get('selected_earthquake'):
            st.info("📍 Vælg først et jordskælv fra startsiden eller søg efter jordskælv i Data menuen")
            
            if st.button("← Gå til startsiden", type="secondary"):
                st.session_state.current_view = 'start'
                st.rerun()
            return
        
        # Hent valgt jordskælv
        eq = st.session_state.selected_earthquake
        
        # Check om vi har stationer eller ej
        if not st.session_state.get('station_list'):
            # LAYOUT 1: Jordskælv info | Kort med kun jordskælv | Søge parametre
            col1, col2, col3 = st.columns([1, 3, 2])
            
            with col1:
                # Jordskælv info
                st.markdown(
                    f"""<div style="font-size: 0.9rem;">
                    <span style="color: #E74C3C; font-weight: bold;">VALGT JORDSKÆLV:</span><br>
                    <span style="color: #6C757D;">
                    Dato: {format_earthquake_time(eq['time'])}<br>
                    Magnitude: M{eq['magnitude']:.1f}<br>
                    Dybde: {eq.get('depth', 0):.0f} km<br>
                    Region: {eq.get('location', 'Unknown')[:30]}
                    </span>
                    </div>""",
                    unsafe_allow_html=True
                )
            
            with col2:
                # Kort med kun jordskælv
                m = self.create_earthquake_only_map(eq)
                if m:
                    st_folium(m, width=500, height=300, key="earthquake_only_map")
            
            with col3:
                # Søge parametre
                st.markdown("### 🔍 Søg stationer")
                
                min_dist = st.number_input(
                    "Min afstand (km)", 
                    value=500, 
                    min_value=0, 
                    max_value=5000, 
                    step=100
                )
                
                max_dist = st.number_input(
                    "Max afstand (km)", 
                    value=3000, 
                    min_value=100, 
                    max_value=20000, 
                    step=100
                )
                
                target_stations = st.number_input(
                    "Antal stationer", 
                    value=3, 
                    min_value=1, 
                    max_value=20
                )
                
                if st.button("🔍 Søg", type="primary", use_container_width=True):
                    with st.spinner("Finder stationer..."):
                        try:
                            stations = self.data_manager.search_stations(
                                earthquake=eq,
                                min_distance_km=min_dist,
                                max_distance_km=max_dist,
                                target_stations=target_stations
                            )
                            
                            if stations:
                                st.session_state.station_list = stations
                                st.success(f"✅ Fandt {len(stations)} stationer")
                                st.rerun()
                            else:
                                st.error("Ingen stationer fundet")
                        except Exception as e:
                            st.error(f"Fejl: {str(e)}")
        
        else:
            # LAYOUT 2: Jordskælv info | Kort med stationer | Stationsliste
            stations = st.session_state.station_list
            col1, col2, col3 = st.columns([1, 3, 2])
            
            with col1:
                # Jordskælv info
                st.markdown(
                    f"""<div style="font-size: 0.9rem;">
                    <span style="color: #E74C3C; font-weight: bold;">VALGT JORDSKÆLV:</span><br>
                    <span style="color: #6C757D;">
                    Dato: {format_earthquake_time(eq['time'])}<br>
                    Magnitude: M{eq['magnitude']:.1f}<br>
                    Dybde: {eq.get('depth', 0):.0f} km<br>
                    Region: {eq.get('location', 'Unknown')[:30]}
                    </span>
                    </div>""",
                    unsafe_allow_html=True
                )
                
                # Søg igen knap nederst
                st.markdown("---")
                if st.button("🔄 Ny søgning", type="secondary", use_container_width=True):
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.rerun()
            
            with col2:
                # Kort med stationer
                station_map = self.create_station_map(eq, stations)
                
                if station_map:
                    map_data = st_folium(
                        station_map,
                        width=600,
                        height=600,
                        returned_objects=["last_object_clicked", "last_clicked"],
                        key="station_selection_map"
                    )
                    
                    # Håndter klik på kort
                    if map_data:
                        clicked_station = self.process_station_click(map_data, stations)
                        if clicked_station:
                            st.session_state.selected_station = clicked_station
                            
                            # Check cache først
                            cache_key = f"{eq.get('time')}_{clicked_station['network']}_{clicked_station['station']}"
                            if 'waveform_cache' not in st.session_state:
                                st.session_state.waveform_cache = {}
                            
                            if cache_key in st.session_state.waveform_cache:
                                st.session_state.waveform_data = st.session_state.waveform_cache[cache_key]
                                self.toast_manager.show_banner("📂 Bruger cached data", banner_type='info', duration=1.5)
                            else:
                                st.session_state.downloading_waveform = True
                                st.session_state.waveform_data = None
                            
                            st.session_state.current_view = 'analysis_waveform'
                            st.rerun()
            
            with col3:
                # Stationsliste
                st.markdown(f"**{len(stations)} stationer fundet**")

                # Vis stations liste med farvestreger
                for i, station in enumerate(stations):
                    station_id = i + 1
                    
                    # Få gradient farve
                    color_hex = self.get_distance_gradient_color(station['distance_km'])
                    
                    # Button label med nummer og station info
                    button_label = f"({station_id}) {station['network']}.{station['station']} - {station['distance_km']:.0f} km"
                    
                    # Check om denne station er valgt
                    is_selected = (st.session_state.get('selected_station') and 
                                st.session_state.selected_station.get('station') == station['station'] and
                                st.session_state.selected_station.get('network') == station['network'])
                    
                    # Knap
                    if st.button(
                        button_label,
                        key=f"station_btn_{i}",
                        use_container_width=True,
                        type="primary" if is_selected else "secondary"
                    ):
                        st.session_state.selected_station = station
                        
                        # Check cache først
                        cache_key = f"{eq.get('time')}_{station['network']}_{station['station']}"
                        if 'waveform_cache' not in st.session_state:
                            st.session_state.waveform_cache = {}
                        
                        if cache_key in st.session_state.waveform_cache:
                            st.session_state.waveform_data = st.session_state.waveform_cache[cache_key]
                            self.toast_manager.show_banner("📂 Bruger cached data", banner_type='info', duration=1.5)
                        else:
                            st.session_state.downloading_waveform = True
                            st.session_state.waveform_data = None
                        
                        st.session_state.current_view = 'analysis_waveform'
                        st.rerun()
                    
                    # Tykkere farvet streg under knappen
                    st.markdown(
                        f'<div style="height: 3px; background-color: {color_hex}; '
                        f'margin: -12px 0 10px 0; border-radius: 2px;"></div>',
                        unsafe_allow_html=True
                    )

    
    def render_station_list(self, stations, earthquake, col_width=None):
        """Render station list med automatisk waveform download ved klik"""
        
        if not stations:
            st.warning("Ingen stationer fundet")
            return
        
        # Hvis ingen col_width specified, brug hele bredden
        if col_width is None:
            container = st.container()
        else:
            container = col_width
        
        with container:
            for idx, station in enumerate(stations):
                station_num = idx + 1
                
                # Check om denne station er valgt
                is_selected = (st.session_state.get('selected_station') and 
                              st.session_state.selected_station.get('station') == station['station'] and
                              st.session_state.selected_station.get('network') == station['network'])
                
                # Farve baseret på afstand
                distance_color = self.get_distance_gradient_color(station['distance_km'])
                
                # Station info
                station_info = f"{station_num}. {station['network']}.{station['station']} - {station['distance_km']:.0f} km"
                
                # Byg unique key for cache
                cache_key = f"{earthquake.get('time')}_{station['network']}_{station['station']}"
                
                if is_selected:
                    # Vis valgt station
                    st.success(f"✅ {station_info}")
                else:
                    # Klikbar station knap
                    if st.button(
                        station_info,
                        key=f"station_{idx}_{station['network']}_{station['station']}",
                        use_container_width=True,
                        help=f"Klik for at se seismogram fra {station['network']}.{station['station']}"
                    ):
                        # Gem valgt station
                        st.session_state.selected_station = station
                        
                        # Check cache først
                        if 'waveform_cache' not in st.session_state:
                            st.session_state.waveform_cache = {}
                        
                        # Hvis data allerede er cached, brug det
                        if cache_key in st.session_state.waveform_cache:
                            st.session_state.waveform_data = st.session_state.waveform_cache[cache_key]
                            self.toast_manager.show_banner("📂 Bruger cached data", banner_type='info', duration=1.5)
                        else:
                            # Marker at vi downloader
                            st.session_state.downloading_waveform = True
                        
                        # Skift direkte til seismogram view
                        st.session_state.current_view = 'analysis_waveform'
                        st.rerun()
                
                # Vis farve-indikator under knappen
                st.markdown(
                    f'<div style="height: 3px; background-color: {distance_color}; '
                    f'margin: -10px 0 10px 0; border-radius: 2px;"></div>',
                    unsafe_allow_html=True
                )
    
    def get_distance_gradient_color(self, distance_km):
        """Get gradient color based on distance"""
        # Gradient fra grøn (tæt) til rød (langt)
        if distance_km < 1000:
            return "#28a745"  # Grøn
        elif distance_km < 2000:
            return "#ffc107"  # Gul  
        elif distance_km < 3000:
            return "#fd7e14"  # Orange
        else:
            return "#dc3545"  # Rød  
    

    def render_earthquake_map_interactive(self, earthquakes):
        """Render interactive earthquake map for homepage med FORBEDRET klik håndtering"""
        if not earthquakes:
            return
        
        # Konverter til DataFrame
        df = pd.DataFrame(earthquakes)
        
        # Tilføj index til DataFrame for at kunne matche senere
        df.reset_index(inplace=True)
        
        # Opret kort
        earthquake_map = self.create_optimized_map(df)
        
        if earthquake_map:
            # Vis kort
            map_data = st_folium(
                earthquake_map,
                width=775,
                height=525,
                returned_objects=["last_object_clicked", "last_clicked", "bounds"],
                key="home_earthquake_map"
            )
            
            # Process klik på kort med bedre fejlhåndtering
            if map_data:
                                
                clicked_eq = self.process_earthquake_click(map_data, df)
                
                if clicked_eq:
                    st.session_state.selected_earthquake = clicked_eq
                    st.session_state.current_view = 'analysis_stations'
                    # Reset station selection
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    
                    self.toast_manager.show(
                        f"Valgt: M{clicked_eq['magnitude']:.1f} jordskælv", 
                        toast_type='success',
                        duration=2.0
                    )
                    st.rerun()
        
        # Vis tabel under kortet
        st.markdown("### Seneste større jordskælv")
        
        # Table headers
        col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 2])
        with col1:
            st.markdown("**Lokation**")
        with col2:
            st.markdown("**Dato**")
        with col3:
            st.markdown("**Mag.**")
        with col4:
            st.markdown("**Dybde**")
        with col5:
            st.markdown("**Koordinater**")
        
        # Display earthquakes
        for idx, eq in enumerate(earthquakes[:10]):
            col1, col2, col3, col4, col5 = st.columns([3, 2, 1, 1, 2])
            
            with col1:
                if st.button(
                    f"{eq.get('location', 'Unknown')[:30]}...",
                    key=f"eq_home_{idx}",
                    use_container_width=True,
                    help=eq.get('location', 'Unknown')
                ):
                    st.session_state.selected_earthquake = eq
                    st.session_state.current_view = 'analysis_stations'  # ÆNDRET til stationsvalg
                    # Reset station selection
                    st.session_state.station_list = None
                    st.session_state.selected_station = None
                    st.session_state.waveform_data = None
                    st.rerun()
            
            with col2:
                st.text(format_earthquake_time(eq['time']))
            
            with col3:
                magnitude_color = "🔴" if eq['magnitude'] >= 7.0 else "🟠" if eq['magnitude'] >= 6.0 else "🟡"
                st.text(f"{magnitude_color} {eq['magnitude']:.1f}")
            
            with col4:
                st.text(f"{eq.get('depth', 0):.0f} km")
            
            with col5:
                st.text(f"{eq.get('latitude', 0):.1f}°, {eq.get('longitude', 0):.1f}°")


    def process_earthquake_click(self, map_data, earthquakes_df):
        """Process earthquake click from map - ROBUST VERSION"""
        if not map_data:
            return None
        
        # Debug info
        # st.write("Debug - map_data keys:", list(map_data.keys()))
        # if map_data.get("last_object_clicked"):
        #     st.write("Debug - last_object_clicked:", map_data["last_object_clicked"])
        
        clicked_lat = None
        clicked_lon = None
        
        # Metode 1: Check last_object_clicked (folium markers)
        if map_data.get("last_object_clicked"):
            clicked_obj = map_data["last_object_clicked"]
            if isinstance(clicked_obj, dict):
                # Folium bruger nogle gange 'lat'/'lng', andre gange 'latitude'/'longitude'
                clicked_lat = clicked_obj.get("lat") or clicked_obj.get("latitude")
                clicked_lon = clicked_obj.get("lng") or clicked_obj.get("longitude")
        
        # Metode 2: Check last_clicked (general map clicks)
        if clicked_lat is None and map_data.get("last_clicked"):
            clicked = map_data["last_clicked"]
            if isinstance(clicked, dict):
                clicked_lat = clicked.get("lat") or clicked.get("latitude")
                clicked_lon = clicked.get("lng") or clicked.get("longitude")
        
        # Metode 3: Check for coordinates direkte i map_data
        if clicked_lat is None:
            clicked_lat = map_data.get("lat") or map_data.get("latitude")
            clicked_lon = map_data.get("lng") or map_data.get("longitude")
        
        # Hvis vi har koordinater, find nærmeste jordskælv
        if clicked_lat is not None and clicked_lon is not None:
            try:
                closest_eq = None
                min_distance = float('inf')
                
                # Find nærmeste jordskælv
                for idx, eq in earthquakes_df.iterrows():
                    # Beregn afstand (simpel Euclidean distance)
                    lat_diff = eq['latitude'] - clicked_lat
                    lon_diff = eq['longitude'] - clicked_lon
                    distance = (lat_diff**2 + lon_diff**2)**0.5
                    
                    if distance < min_distance:
                        min_distance = distance
                        closest_eq = eq
                
                # Tjek om klikket er tæt nok på et jordskælv
                # 10 grader tolerance er meget generøst, men sikrer at klik registreres
                if closest_eq is not None and min_distance < 10.0:
                    # Konverter til dictionary hvis det er en pandas Series
                    if hasattr(closest_eq, 'to_dict'):
                        earthquake_dict = closest_eq.to_dict()
                    else:
                        earthquake_dict = dict(closest_eq)
                    
                    # Reset station relaterede states
                    st.session_state.selected_station = None
                    st.session_state.station_list = None
                    st.session_state.waveform_data = None
                    
                    return earthquake_dict
                    
            except Exception as e:
                st.error(f"Fejl ved processing af kort klik: {str(e)}")
        
        return None

    
    def render_data_view(self):
        """Render the data selection and search view"""
        st.markdown(f"## {texts[st.session_state.language]['search_title']}")
        
        # Search form
        with st.form("earthquake_search"):
            st.markdown(f"### {texts[st.session_state.language]['search_criteria']}")
            
            col1, col2 = st.columns(2)
            
            with col1:
                mag_range = st.slider(
                    texts[st.session_state.language]['magnitude_range'],
                    min_value=4.0,
                    max_value=9.0,
                    value=st.session_state.magnitude_range,
                    step=0.1,
                    help=texts[st.session_state.language]['magnitude_help']
                )
                
                year_range = st.slider(
                    texts[st.session_state.language]['date_range'],
                    min_value=1990,
                    max_value=datetime.now().year,
                    value=st.session_state.year_range,
                    help=texts[st.session_state.language]['date_help']
                )
            
            with col2:
                depth_range = st.slider(
                    texts[st.session_state.language]['depth_range'],
                    min_value=0,
                    max_value=700,
                    value=st.session_state.depth_range,
                    step=10,
                    help=texts[st.session_state.language]['depth_help']
                )
                
                max_results = st.number_input(
                    texts[st.session_state.language]['max_results'],
                    min_value=1,
                    max_value=100,
                    value=25
                )
            
            submitted = st.form_submit_button(
                texts[st.session_state.language]['search_button'],
                type="primary"
            )
            
            if submitted:
                st.session_state.magnitude_range = mag_range
                st.session_state.year_range = year_range
                st.session_state.depth_range = depth_range
                
                with st.spinner(texts[st.session_state.language]['loading']):
                    import time
                    time.sleep(2)
                
                st.success("Søgning udført!")
    

    def render_analysis_waveform_view(self):
        """Render waveform viewer med samme layout som magnitude siden"""
       # st.markdown(f"## {texts[st.session_state.language]['nav_waveform_viewer']}")
        
        # Check for selected station
        if 'selected_station' not in st.session_state or st.session_state.selected_station is None:
            st.warning("Vælg først en station fra Station Analyse")
            if st.button("← Gå til Station Analyse", type="secondary"):
                st.session_state.current_view = 'analysis_stations'
                st.rerun()
            return
        
        selected_station = st.session_state.selected_station
        eq = st.session_state.selected_earthquake
        
        # Automatisk download hvis vi ikke har data
        if 'waveform_data' not in st.session_state or st.session_state.waveform_data is None:
            with st.spinner(f"📡 Henter data fra {selected_station['network']}.{selected_station['station']}..."):
                try:
                    waveform_data = self.data_manager.download_waveform_data(
                        st.session_state.selected_earthquake,
                        selected_station
                    )
                    if waveform_data:
                        st.session_state.waveform_data = waveform_data
                        # TILFØJ: Sæt raw data som default ved første load
                        st.session_state.applied_filter = 'raw'
                        st.session_state.display_data = waveform_data.copy()
                        self.toast_manager.show(
                            "✅ Data hentet succesfuldt",
                            toast_type='success',
                            duration=2.0
                        )
                    else:
                        st.error("❌ Kunne ikke hente waveform data")
                        return
                except Exception as e:
                    st.error(f"Fejl ved download: {str(e)}")
                    return
        
        waveform_data = st.session_state.waveform_data
        
        # Layout med kolonner
        col_left, col_right = st.columns([1, 3])
        
        with col_left:
            # Diskret info panel
            with st.container():
                # Jordskælvs info
                st.markdown(
                    f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 10px;'>
                    <small style='color: #6c757d;'>
                    <b>JORDSKÆLV: {eq.get('location', 'Ukendt lokation')}</b><br>
                    M{eq.get('magnitude', 0):.1f} • {eq.get('depth', 0):.0f} km dybde<br>
                    Kl. {format_earthquake_time(eq.get('time'), '%d. %b %Y %H:%M')}
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
                
                # Station info med sampling rate
                sampling_rate = waveform_data.get('sampling_rate', 100)
                st.markdown(
                    f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 10px;'>
                    <small style='color: #6c757d;'>
                    <b>STATION: {selected_station['network']}.{selected_station['station']}</b><br>
                    Offiel afstand: {selected_station.get('distance_km', 0):.0f} km<br>
                    <b>Sampling: {sampling_rate} Hz</b>
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
                
                # TILFØJ: Vis aktuel filter status
                current_filter = st.session_state.get('applied_filter', 'raw')
                filter_status_text = {
                    'raw': 'Original data (ingen filter)',
                    'p_waves': 'P-bølger (1-10 Hz)',
                    's_waves': 'S-bølger (0.5-5 Hz)',
                    'surface': 'Overfladebølger (0.02-0.5 Hz)',
                    'custom': f'Custom ({st.session_state.get("applied_custom_low", 0.1)}-{st.session_state.get("applied_custom_high", 10.0)} Hz)'
                }
                
                st.markdown(
                    f"""<div style='background-color: #e8f4fd; padding: 10px; border-radius: 5px; margin-bottom: 15px;'>
                    <small style='color: #0056b3;'>
                    <b>Aktuel visning:</b><br>
                    {filter_status_text.get(current_filter, 'Ukendt')}
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
            
            # Filter indstillinger
            #st.markdown("### ⚙️ Filter indstillinger")
            
            # Predefinerede filtre
            filter_options = {
                'raw': 'Original data (ingen filter)',
                'p_waves': 'P-bølger (1-10 Hz)',
                's_waves': 'S-bølger (0.5-5 Hz)',
                'surface': 'Overfladebølger (0.02-0.5 Hz)',
                'custom': 'Brugerdefineret filter'
            }
            
            selected_filter = st.selectbox(
                "⚙️ Vælg filter:",
                options=list(filter_options.keys()),
                format_func=lambda x: filter_options[x],
                index=list(filter_options.keys()).index(st.session_state.get('selected_filter_option', 'raw')),
                key='filter_select'
            )
            
            # Gem valgt filter option (ikke applied endnu)
            st.session_state.selected_filter_option = selected_filter
            
            # Custom filter parametre
            if selected_filter == 'custom':
                col1, col2 = st.columns(2)
                with col1:
                    low_freq = st.number_input(
                        "Lav frekvens (Hz):",
                        min_value=0.001,
                        max_value=50.0,
                        value=st.session_state.get('custom_low_freq_input', 0.1),
                        step=0.1,
                        format="%.3f",
                        key='custom_low_freq'
                    )
                with col2:
                    high_freq = st.number_input(
                        "Høj frekvens (Hz):",
                        min_value=0.1,
                        max_value=50.0,
                        value=st.session_state.get('custom_high_freq_input', 10.0),
                        step=0.1,
                        format="%.1f",
                        key='custom_high_freq'
                    )
                    
                    # Nyquist check
                    nyquist = sampling_rate / 2.0
                    if high_freq > nyquist * 0.95:
                        st.warning(f"⚠️ Høj frekvens nær Nyquist ({nyquist:.1f} Hz)")
                    
                    if low_freq >= high_freq:
                        st.error("Lav frekvens skal være mindre end høj frekvens")
                
                # Gem custom værdier
                st.session_state.custom_low_freq_input = low_freq
                st.session_state.custom_high_freq_input = high_freq
            
           
            
            # Apply filter button - KUN HER OPDATERES GRAFEN
            if st.button("🎚️ Anvend Filter", type="primary", use_container_width=True):
                with st.spinner("Processerer data med fuld opløsning..."):
                    try:
                        # Debug info
                        print(f"DEBUG: Processing with sampling rate: {sampling_rate} Hz")
                        
                        # Check for high-res data
                        has_highres = any(key.startswith('waveform_') for key in waveform_data.keys())
                        if has_highres:
                            st.info(f"📊 Bruger høj-opløsnings data ({sampling_rate} Hz)")
                        
                        # Bestem filter type
                        if selected_filter == 'custom':
                            filter_type = (st.session_state.custom_low_freq, st.session_state.custom_high_freq)
                            st.session_state.applied_custom_low = st.session_state.custom_low_freq
                            st.session_state.applied_custom_high = st.session_state.custom_high_freq
                        elif selected_filter == 'raw':
                            filter_type = None
                        else:
                            filter_type = selected_filter
                        
                        # Process waveform - DETTE BRUGER AUTOMATISK HIGH-RES DATA
                        processed_data = self.processor.process_waveform_with_filtering(
                            waveform_data,
                            filter_type=filter_type,
                            remove_spikes=True,
                            calculate_noise=True
                        )
                        
                        if processed_data:
                            # Opdater session state
                            st.session_state.applied_filter = selected_filter
                            st.session_state.processed_waveform = processed_data
                            st.session_state.filtered_data = processed_data  # For magnitude siden
                            
                            # Forbered data til visning
                            display_data = waveform_data.copy()
                            if 'filtered_data' in processed_data and processed_data['filtered_data']:
                                display_data['displacement_data'] = processed_data['filtered_data']
                            
                            st.session_state.display_data = display_data
                            
                            # Success feedback med info om data opløsning
                            if processed_data.get('used_highres'):
                                self.toast_manager.show_banner(
                                    f"✅ Filter anvendt! Brugte høj-opløsnings data ({sampling_rate} Hz)", 
                                    banner_type='success', 
                                    duration=3.0
                                )
                            else:
                                self.toast_manager.show_banner("✅ Filter anvendt!", banner_type='success', duration=2.0)
                        else:
                            st.error("Kunne ikke processere data")
                        
                    except Exception as e:
                        st.error(f"Fejl ved filtrering: {str(e)}")
            
            
        with col_right:
            # Vis data - brug display_data hvis tilgængelig, ellers raw data
            data_to_plot = st.session_state.get('display_data', waveform_data).copy()
            
            # Check at vi har displacement data
            if 'displacement_data' not in data_to_plot or not data_to_plot['displacement_data']:
                st.error("Ingen displacement data tilgængelig")
                return
            
            # Component selection
            show_north = True
            show_east = True
            show_vertical = True
            
            show_components = {
                'north': show_north,
                'east': show_east,
                'vertical': show_vertical
            }
            
            # Vis filter status hvis processed
            if st.session_state.get('processed_waveform'):
                processed = st.session_state.processed_waveform
                if 'filter_status' in processed:
                    status_cols = st.columns(3)
                    for i, (comp, status) in enumerate(processed['filter_status'].items()):
                        with status_cols[i % 3]:
                            if status == 'success':
                                st.success(f"✅ {comp.capitalize()}: OK")
                            else:
                                st.warning(f"⚠️ {comp.capitalize()}: {status}")
            
            # Opret waveform plot med højere opløsning
            try:
                # Opdater visualizer til at bruge flere punkter
                # Dette sker i waveform_visualizer.py - downsample_for_plotting
                # Men vi kan sende en parameter hvis visualizer understøtter det
                
                fig = self.visualizer.create_waveform_plot(
                    data_to_plot,
                    show_components=show_components,
                    show_arrivals=True,
                    title="Seismogram",
                    height=600  # Øget højde for bedre visualisering
                )
                
                fig.update_layout(
                    title=dict(text=f"Seismogram<br><sup style='font-size: 12px; color: #6c757d;'>Klik på signaturen for at vise/skjule komponenterne. Du kan zoome på grafen via menu til højre.</sup>",
                        x=0.5,
                        xanchor='center'),
                    hovermode='x unified',
                    showlegend=True,
                    legend=dict(
                        yanchor="top",
                        y=0.99,
                        xanchor="right",
                        x=0.99
                    )
                )
                
                if fig:
                    # Tilføj info om data opløsning
                    #data_info = f"Data opløsning: {sampling_rate} Hz"
                    #if st.session_state.get('processed_waveform', {}).get('used_highres'):
                    #    data_info += " (høj-opløsning)"
                    
                    #st.caption(data_info)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.error("Kunne ikke oprette plot")
            
            except Exception as e:
                st.error(f"Fejl ved visning af seismogram: {str(e)}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📊 Beregn Magnitude", use_container_width=True, type="secondary"):
                    st.session_state.current_view = 'analysis_magnitude'
                    st.rerun()
            with col2:    
                if st.button("📥 Excel Export", use_container_width=True, type="secondary"):
                    st.session_state.current_view = 'tools_export'
                    st.rerun()        


    def create_station_map(self, earthquake, stations):
        """Opretter kort med jordskælv og stationer"""
        try:
            import folium
            
            # Beregn bounds for alle punkter
            all_lats = [earthquake['latitude']] + [s['latitude'] for s in stations]
            all_lons = [earthquake['longitude']] + [s['longitude'] for s in stations]
            
            lat_min, lat_max = min(all_lats), max(all_lats)
            lon_min, lon_max = min(all_lons), max(all_lons)
            
            # Center og zoom beregning
            center_lat = (lat_min + lat_max) / 2
            center_lon = (lon_min + lon_max) / 2
            
            # Opret kort med samme stil som jordskælvskort
            m = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=2,
                tiles='Esri_WorldImagery',
                attr=' ',
                scrollWheelZoom=True,
                doubleClickZoom=True,
                dragging=True,
                zoomControl=False,
                world_copy_jump=True
            )
            
            # Tilføj zoom kontrol
            folium.plugins.Fullscreen(position='topright').add_to(m)
            # Tilføj fullscreen knap
            folium.plugins.Fullscreen(
                position='topright',
                title='Fuld skærm',
                title_cancel='Luk fuld skærm',
                force_separate_button=True
            ).add_to(m)
            
            # Fit bounds med padding
            lat_padding = max((lat_max - lat_min) * 0.2, 2.0)
            lon_padding = max((lon_max - lon_min) * 0.2, 2.0)
            
            southwest = [lat_min - lat_padding, lon_min - lon_padding]
            northeast = [lat_max + lat_padding, lon_max + lon_padding]
            m.fit_bounds([southwest, northeast])
            
            # Tilføj transparente afstandscirkler omkring jordskælv
            for radius_km in [1000, 2000, 3000]:
                folium.Circle(
                    location=[earthquake['latitude'], earthquake['longitude']],
                    radius=radius_km * 1000,  # Konverter til meter
                    color='white',
                    weight=1,
                    fill=True,
                    fillOpacity=0.1,
                    opacity=0.3,
                    dash_array='5,5'  # Stiplet linje
                ).add_to(m)
            
            # Tilføj jordskælv som rød stjerne
            folium.Marker(
                location=[earthquake['latitude'], earthquake['longitude']],
                icon=folium.DivIcon(
                    html=f'''<div style="font-size: 28px; text-align: center;">
                            <span style="color: red; text-shadow: 1px 1px 2px black;">★</span>
                            </div>''',
                    icon_size=(28, 28),
                    icon_anchor=(14, 14)
                ),
                popup=f"M{earthquake['magnitude']} - {earthquake.get('location', 'Unknown')}",
                tooltip=f"M{earthquake['magnitude']} Jordskælv"
            ).add_to(m)
            
            # Tilføj stationer som trekanter
            for i, station in enumerate(stations):
                station_id = i + 1
                # Brug gradient farve
                color = self.get_distance_gradient_color(station['distance_km'])
                
                # Større trekant med tal
                triangle_html = f'''
                <div style="position: relative; width: 40px; height: 35px;">
                    <!-- Hvid baggrunds-trekant -->
                    <div style="
                        position: absolute;
                        top: 0;
                        left: 50%;
                        transform: translateX(-50%);
                        width: 0; 
                        height: 0; 
                        border-left: 20px solid transparent;
                        border-right: 20px solid transparent;
                        border-bottom: 34px solid white;
                    "></div>
                    <!-- Farvet trekant -->
                    <div style="
                        position: absolute;
                        top: 2px;
                        left: 50%;
                        transform: translateX(-50%);
                        width: 0; 
                        height: 0; 
                        border-left: 18px solid transparent;
                        border-right: 18px solid transparent;
                        border-bottom: 30px solid {color};
                    "></div>
                    <!-- Nummer -->
                    <div style="
                        position: absolute;
                        top: 15px;
                        left: 50%;
                        transform: translateX(-50%);
                        color: white;
                        font-size: 14px;
                        font-weight: bold;
                        text-shadow: 1px 1px 2px rgba(0,0,0,0.8);
                        z-index: 10;
                    ">{station_id}</div>
                </div>
                '''
                
                # Tilføj klikbar cirkel (usynlig)
                folium.CircleMarker(
                    location=[station['latitude'], station['longitude']],
                    radius=20,
                    fillColor=color,
                    color='transparent',
                    weight=0,
                    fillOpacity=0,
                    popup=f"{station['network']}.{station['station']}<br>"
                        f"Afstand: {station['distance_km']:.0f} km<br>"
                        f"Klik for at vælge",
                    tooltip=f"{station['network']}.{station['station']} ({station['distance_km']:.0f} km)"
                ).add_to(m)
                
                # Tilføj trekant visuelt
                folium.Marker(
                    location=[station['latitude'], station['longitude']],
                    icon=folium.DivIcon(
                        html=triangle_html,
                        icon_size=(40, 35),
                        icon_anchor=(20, 35)
                    ),
                    clickable=False
                ).add_to(m)
            
            return m
            
        except Exception as e:
            st.error(f"Fejl ved oprettelse af kort: {str(e)}")
            return None

    def process_station_click(self, map_data, stations):
        """Process station click from map - koordinat baseret"""
        if not map_data:
            return None
        
        clicked_lat = None
        clicked_lon = None
        
        # Prioriteret klik håndtering
        if map_data.get("last_object_clicked"):
            try:
                clicked_obj = map_data["last_object_clicked"]
                if clicked_obj and isinstance(clicked_obj, dict):
                    clicked_lat = clicked_obj.get("lat") or clicked_obj.get("latitude")
                    clicked_lon = clicked_obj.get("lng") or clicked_obj.get("longitude")
            except Exception:
                pass
        
        # Fallback til general click
        if clicked_lat is None and map_data.get("last_clicked"):
            try:
                last_clicked = map_data["last_clicked"]
                if isinstance(last_clicked, dict):
                    clicked_lat = last_clicked.get("lat") or last_clicked.get("latitude")
                    clicked_lon = last_clicked.get("lng") or last_clicked.get("longitude")
            except Exception:
                pass
        
        # Find nærmeste station
        if clicked_lat is not None and clicked_lon is not None:
            closest_station = None
            min_distance = float('inf')
            
            for station in stations:
                distance = ((station['latitude'] - clicked_lat)**2 + 
                        (station['longitude'] - clicked_lon)**2)**0.5
                if distance < min_distance:
                    min_distance = distance
                    closest_station = station
            
            # Tolerance for at matche klik
            if closest_station and min_distance < 5.0:
                return closest_station
        
        return None


    def create_earthquake_only_map(self, earthquake):
        """Opretter kort med kun jordskælv - samme stil som hovedkort"""
        import folium
        
        m = folium.Map(
            location=[earthquake['latitude'], earthquake['longitude']],
            zoom_start=3,
            tiles='Esri_WorldImagery',
            attr=' ',
            scrollWheelZoom=True,
            doubleClickZoom=True,
            dragging=True,
            zoomControl=False
        )
        folium.plugins.Fullscreen(
            position='topright',
            title='Fuld skærm',
            title_cancel='Luk fuld skærm',
            force_separate_button=True
        ).add_to(m)
        
        # Tilføj transparente afstandscirkler
        for radius_km in [1000, 2000, 3000]:
            folium.Circle(
                location=[earthquake['latitude'], earthquake['longitude']],
                radius=radius_km * 1000,
                color='white',
                weight=1,
                fill=True,
                fillOpacity=0.1,
                opacity=0.3,
                dash_array='5,5'
            ).add_to(m)
        
        # Tilføj jordskælv som rød stjerne
        folium.Marker(
            location=[earthquake['latitude'], earthquake['longitude']],
            icon=folium.DivIcon(
                html=f'''<div style="font-size: 28px; text-align: center;">
                        <span style="color: red; text-shadow: 2px 2px 4px black;">★</span>
                        </div>''',
                icon_size=(28, 28),
                icon_anchor=(14, 14)
            ),
            popup=f"M{earthquake['magnitude']} - {earthquake.get('location', 'Unknown')}",
            tooltip=f"M{earthquake['magnitude']} Jordskælv"
        ).add_to(m)
        
        return m

       
    def render_analysis_magnitude_view(self):
        """Render magnitude calculation view"""
        st.markdown(f"## {texts[st.session_state.language]['nav_magnitude_calc']}")
        
        # Check om vi har nødvendige data
        if not st.session_state.get('selected_station'):
            st.info("📍 Vælg først en station fra Stationsvalg")
            if st.button("← Gå til Stationsvalg", type="secondary"):
                st.session_state.current_view = 'analysis_stations'
                st.rerun()
            return
        
        if not st.session_state.get('waveform_data'):
            st.info("📊 Du skal først hente seismogram data")
            if st.button("← Gå til Seismogram", type="secondary"):
                st.session_state.current_view = 'analysis_waveform'
                st.rerun()
            return
        
        # Hent data
        station = st.session_state.selected_station
        eq = st.session_state.selected_earthquake
        waveform_data = st.session_state.waveform_data
        
        # Layout med kolonner
        col_left, col_right = st.columns([1, 3])
        
        with col_left:
            # Diskret info panel - samme stil som andre sider
            with st.container():
                # Jordskælvs info (diskret)
                st.markdown(
                    f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 10px;'>
                    <small style='color: #6c757d;'>
                    <b>JORDSKÆLV: {eq.get('location', 'Ukendt lokation')}</b><br>
                    M{eq.get('magnitude', 0):.1f} • {eq.get('depth', 0):.0f} km dybde<br>
                    Kl. {format_earthquake_time(eq.get('time'), '%d. %b %Y %H:%M')}
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
                
                # Station info (diskret)
                st.markdown(
                    f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 10px;'>
                    <small style='color: #6c757d;'>
                    <b>STATION: {station['network']}.{station['station']}</b><br>
                    Offiel afstand: {station.get('distance_km', 0):.0f} km <br>
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
                
                # Filter information
                filter_type = "Overfladebølger (0.02-0.5 Hz)"
                if st.session_state.get('applied_filter'):
                    filter_type = st.session_state.applied_filter
                
                st.markdown(
                    f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 15px;'>
                    <small style='color: #6c757d;'>
                    <b>Anvendt filter:</b><br>
                    {filter_type}
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
            # Overfladebølge vindue
            surface_arrival = station.get('surface_arrival', 0)
            if surface_arrival:
                st.markdown(
                    f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 15px;'>
                    <small style='color: #6c757d;'>
                    <b>Foreslået ankomsttid: </b><br>
                    For overfladebølge: {surface_arrival:.1f}s
                    </small>
                    </div>""", 
                    unsafe_allow_html=True
                )
            else:
                st.warning("Ingen overfladebølge ankomst beregnet")
                surface_arrival = 300.0  # Default
            
            #st.markdown("---")
            
            # Ms beregnings indstillinger
            st.markdown("## ⚙️ Beregningsindstillinger")
            
            
            
            # Vindue valg
            #st.markdown("## Analyse vindue")
            #st.markdown("<small style='color: #6c757d;'>Vælg det tidsvindue hvor overfladebølgerne analyseres</small>", unsafe_allow_html=True)
            
            window_mode = st.radio(
                "Vælg vindue for beregning",
                ["Automatisk (10 min)", "Manuel"],
                help="Automatisk bruger 10 minutter fra overfladebølge ankomst"
            )
            
            
            
            
            # Initialize vinduesværdier hvis ikke sat
            if 'ms_window_start' not in st.session_state:
                st.session_state.ms_window_start = float(surface_arrival)
            if 'ms_window_duration' not in st.session_state:
                st.session_state.ms_window_duration = 600.0
            
            if window_mode == "Manuel":
                st.markdown("<small style='color: #6c757d;'>💡 Juster værdierne og klik 'Opdater vindue' for at se ændringer</small>", unsafe_allow_html=True)
                
                window_start = st.number_input(
                    "Start tid (s efter jordskælv)",
                    min_value=0.0,
                    max_value=3600.0,
                    value=st.session_state.ms_window_start,
                    step=10.0
                )
                window_duration = st.number_input(
                    "Varighed (s)",
                    min_value=60.0,
                    max_value=1200.0,
                    value=st.session_state.ms_window_duration,
                    step=60.0
                )
                
                # Opdater knap for manuel justering
                if st.button("🔄 Opdater vindue", use_container_width=True):
                    st.session_state.ms_window_start = window_start
                    st.session_state.ms_window_duration = window_duration
                    # Force genberegning
                    if 'ms_result' in st.session_state:
                        del st.session_state.ms_result
                    st.rerun()
            else:
                # Automatisk vindue
                st.session_state.ms_window_start = surface_arrival
                st.session_state.ms_window_duration = 600.0
            
            # Reference periode
            #st.markdown("Reference periode:")
            #st.markdown("<small style='color: #6c757d;'>Du kan justere perioden anvendt i beregningen af M. (se evt. beregninger)</small>", unsafe_allow_html=True)
            reference_period = st.selectbox(
                "Anvendt periode (T) i beregning:",
                [20.0, 18.0, 19.0, 21.0, 22.0],
                index=0,
                help="Standard er 20s for Ms beregning (IASPEI 2013)"
            )
            
            # Komponent valg
            #st.markdown("Komponenter:")
            use_vertical = True 
            use_horizontal = True
            

            
            # Beregn knap
            calculate_button = st.button(
                "🔢 Opdater beregning af Ms ", 
                type="primary", 
                use_container_width=True,
                disabled=(not use_vertical and not use_horizontal)
            )
        
        with col_right:
            # Hovedområde for resultater
            
            # Hent displacement data
            if st.session_state.get('filtered_data'):
                # Brug filtreret data hvis tilgængelig
                data_source = st.session_state.filtered_data.get('filtered_data', {})
            else:
                # Ellers brug original displacement data
                data_source = waveform_data.get('displacement_data', {})
            
            if not data_source:
                st.error("Ingen displacement data tilgængelig")
                return
            
            # Brug aktuelle vinduesværdier
            window_start = st.session_state.ms_window_start
            window_duration = st.session_state.ms_window_duration
            
            # Automatisk beregning eller ved knaptryk
            if calculate_button or 'ms_result' not in st.session_state:
                with st.spinner("Beregner Ms magnitude..."):
                    try:
                        # Hent komponenter
                        north_data = data_source.get('north', np.array([]))
                        east_data = data_source.get('east', np.array([]))
                        vertical_data = data_source.get('vertical', np.array([]))
                        
                        # Konverter til numpy arrays hvis nødvendigt
                        if not isinstance(north_data, np.ndarray):
                            north_data = np.array(north_data)
                        if not isinstance(east_data, np.ndarray):
                            east_data = np.array(east_data)
                        if not isinstance(vertical_data, np.ndarray):
                            vertical_data = np.array(vertical_data)
                        
                        # Hent sampling rate
                        sampling_rate = waveform_data.get('sampling_rate', 100)
                        
                        # Ekstraher overfladebølge vindue
                        start_idx = int(window_start * sampling_rate)
                        end_idx = int((window_start + window_duration) * sampling_rate)
                        
                        # Begræns til data længde
                        start_idx = max(0, start_idx)
                        end_idx = min(end_idx, len(north_data), len(east_data), len(vertical_data))
                        
                        # Udtræk vindue
                        if use_horizontal:
                            north_window = north_data[start_idx:end_idx] if len(north_data) > start_idx else np.array([])
                            east_window = east_data[start_idx:end_idx] if len(east_data) > start_idx else np.array([])
                        else:
                            north_window = np.array([])
                            east_window = np.array([])
                        
                        if use_vertical:
                            vertical_window = vertical_data[start_idx:end_idx] if len(vertical_data) > start_idx else np.array([])
                        else:
                            vertical_window = np.array([])
                        
                        # Beregn Ms magnitude - UDEN use_vertical og use_horizontal parametre
                        ms_result, explanation = self.processor.calculate_ms_magnitude(
                            north_window,
                            east_window,
                            vertical_window,
                            station.get('distance_km', 0),
                            sampling_rate,
                            earthquake_depth_km=eq.get('depth', 0)  # <-- RETTET!
                        )
                        
                        # Gem resultat
                        st.session_state.ms_result = ms_result
                        st.session_state.ms_explanation = explanation
                        st.session_state.ms_window = {
                            'start': window_start,
                            'duration': window_duration,
                            'start_idx': start_idx,
                            'end_idx': end_idx
                        }
                        st.session_state.ms_components_used = {
                            'vertical': use_vertical,
                            'horizontal': use_horizontal
                        }
                        
                    except Exception as e:
                        st.error(f"Fejl ved beregning: {str(e)}")
                        st.session_state.ms_result = None
                        st.session_state.ms_explanation = f"Beregningsfejl: {str(e)}"
            
            
            # Vis resultater
            if st.session_state.get('ms_result') is not None:
                # Succesfuld beregning
                ms_value = st.session_state.ms_result
                
                    
                
                # Plot overfladebølge vindue
                time_array = waveform_data.get('time', waveform_data.get('time_array', []))
                if len(time_array) > 0:
                    window_info = st.session_state.get('ms_window', {})
                    components_used = st.session_state.get('ms_components_used', {'vertical': True, 'horizontal': True})
                    
                    # Opret interaktiv figur med Plotly
                    fig = go.Figure()
                    
                    # Plot komponenter i vinduet
                    components = {
                        'north': {'name': 'Nord', 'color': 'red', 'show': components_used.get('horizontal', True)},
                        'east': {'name': 'Øst', 'color': 'green', 'show': components_used.get('horizontal', True)},
                        'vertical': {'name': 'Vertikal', 'color': 'blue', 'show': components_used.get('vertical', True)}
                    }
                    
                    # Hold styr på hvilke komponenter der faktisk plottes
                    plotted_any = False
                    
                    for comp_key, comp_info in components.items():
                        if comp_info['show'] and comp_key in data_source:
                            comp_data = data_source[comp_key]
                            if len(comp_data) > 0:
                                plotted_any = True
                                
                                # Plot hele seismogrammet (svagt)
                                fig.add_trace(go.Scatter(
                                    x=time_array[:len(comp_data)],
                                    y=comp_data,
                                    mode='lines',
                                    name=f"{comp_info['name']} (komplet)",
                                    line=dict(color=comp_info['color'], width=0.5),
                                    opacity=0.3,
                                    showlegend=False
                                ))
                                
                                # Fremhæv analyse vindue
                                start_idx = window_info.get('start_idx', 0)
                                end_idx = window_info.get('end_idx', len(comp_data))
                                
                                if end_idx > start_idx and start_idx < len(comp_data):
                                    end_idx = min(end_idx, len(comp_data))
                                    fig.add_trace(go.Scatter(
                                        x=time_array[start_idx:end_idx],
                                        y=comp_data[start_idx:end_idx],
                                        mode='lines',
                                        name=comp_info['name'],
                                        line=dict(color=comp_info['color'], width=1.2),
                                        showlegend=True
                                    ))
                    
                    if plotted_any:
                        # Tilføj vindue markering
                        window_start_time = window_info.get('start', 0)
                        window_end_time = window_start_time + window_info.get('duration', 600)
                        
                        # Marker overfladebølge vindue med shapes
                        fig.add_shape(
                            type="rect",
                            x0=window_start_time,
                            x1=window_end_time,
                            y0=0,
                            y1=1,
                            yref="paper",
                            fillcolor="rgba(255,165,0,0.1)",
                            layer="below",
                            line=dict(color="orange", width=2, dash="dot"),
                        )
                        
                        # Tilføj tekst for vinduet
                        fig.add_annotation(
                            x=(window_start_time + window_end_time) / 2,
                            y=1.02,
                            yref="paper",
                            text=f"Ms analyse vindue ({window_info.get('duration', 600):.0f}s)",
                            showarrow=False,
                            bgcolor="rgba(255,165,0,0.8)",
                            bordercolor="orange",
                            borderwidth=1,
                            borderpad=4,
                            font=dict(color="white", size=12)
                        )
                        
                        # Marker overfladebølge ankomst
                        if surface_arrival > 0:
                            fig.add_vline(
                                x=surface_arrival,
                                line=dict(color='orange', width=2, dash='dash'),
                                annotation_text="Overfladebølge ankomst",
                                annotation_position="top left"
                            )
                        
                        fig.update_layout(
                            title=dict(
                                text=f"Ms beregning - vindue for overfladebølgen<br><sup style='color: #004085; font-weight: normal;'>💡 Tip: Brug menu i højre hjørne til at zoome og panorere. Du kan justere analysevinduet via indstillingerne til venstre.</sup>",
                                font=dict(size=16, color='#2C3E50')
                            ),
                            xaxis_title="Tid (s fra jordskælv)",
                            yaxis_title="Forskydning (mm)",
                            height=500,
                            hovermode='x unified',
                            showlegend=True,
                            dragmode='pan',
                            xaxis=dict(
                                range=[0, max(time_array) if len(time_array) > 0 else 1000],
                                type="linear"
                            )
                        )

                        st.plotly_chart(fig, use_container_width=True)
                        
                        col1, col2 = st.columns(2)
                        delta_text = f" ({ms_value - eq['magnitude']:+.1f})" if eq.get('magnitude') else ""
                        # Bestem farve baseret på kvalitet
                        diff = abs(ms_value - eq['magnitude']) if eq.get('magnitude') else None
                        if diff is not None:
                            if diff < 0.3:
                                result_color = "#28a745"  # Grøn
                            elif diff < 0.5:
                                result_color = "#ffc107"  # Gul/orange
                            else:
                                result_color = "#dc3545"  # Rød
                        else:
                            result_color = "#0056b3"  # Blå (default)
                        with col1:
                            st.markdown(
                                f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 15px;'>
                                <span style='color: #000;font-size: 1.4rem;'>Beregnet Ms:</span> 
                                <span style='color: {result_color}; font-weight: bold; font-size: 1.4rem;'>{ms_value:.1f}</span>
                                </div>""",
                                unsafe_allow_html=True
                            )
                        with col2:
                                st.markdown(
                                f"""<div style='background-color: #f8f9fa; padding: 10px; border-radius: 5px; margin-bottom: 15px;'>
                                <span style='color: #000;'>Afvigelse fra officiel Magnitude:</span> 
                                <span style='color: {result_color};'>{delta_text}</span>
                                </div>""",
                                unsafe_allow_html=True
                            )

                    else:
                        st.warning("Ingen data at vise - check at komponenter er valgt")
                
                # Detaljeret beregning - FLYTTET NED og collapsed som default
                if st.session_state.get('ms_explanation'):
                    with st.expander("📊 Klik for at se detaljeret Magnetudeberegning her", expanded=False):
                        st.markdown(st.session_state.ms_explanation)
                
                
                # FFT Analyse (hvis overfladebølge data er tilgængelig)
                if surface_arrival > 0 and st.checkbox("Vis frekvensanalyse (FFT)", value=False):
                    # Find dominerende komponent baseret på hvad der blev brugt i beregningen
                    components_used = st.session_state.get('ms_components_used', {'vertical': True, 'horizontal': True})
                    
                    # Hent sampling rate
                    sampling_rate = waveform_data.get('sampling_rate', 100)
                    
                    north_data = data_source.get('north', np.array([]))
                    east_data = data_source.get('east', np.array([]))
                    vertical_data = data_source.get('vertical', np.array([]))
                    
                    max_north = np.max(np.abs(north_data)) if len(north_data) > 0 else 0
                    max_east = np.max(np.abs(east_data)) if len(east_data) > 0 else 0
                    max_vert = np.max(np.abs(vertical_data)) if len(vertical_data) > 0 else 0
                    
                    dominant_comp = None
                    comp_name = "N/A"
                    
                    if components_used.get('vertical', False) and max_vert > 0:
                        dominant_comp = vertical_data
                        comp_name = "Vertikal"
                    elif components_used.get('horizontal', False):
                        if max_north > max_east and max_north > 0:
                            dominant_comp = north_data
                            comp_name = "Nord"
                        elif max_east > 0:
                            dominant_comp = east_data
                            comp_name = "Øst"
                    
                    if dominant_comp is not None and len(dominant_comp) > 0:
                        # Beregn FFT direkte her i stedet for at kalde ikke-eksisterende metode
                        try:
                            # FFT beregning
                            n = len(dominant_comp)
                            fft_vals = np.fft.fft(dominant_comp)
                            fft_freq = np.fft.fftfreq(n, 1/sampling_rate)
                            
                            # Kun positive frekvenser
                            pos_mask = fft_freq > 0
                            frequencies = fft_freq[pos_mask]
                            fft_amps = np.abs(fft_vals[pos_mask]) * 2 / n  # Normaliser
                            
                            # Konverter til perioder
                            with np.errstate(divide='ignore', invalid='ignore'):
                                periods = 1.0 / frequencies
                            
                            # Filtrer til relevante perioder og sorter
                            period_mask = (periods >= 5) & (periods <= 100) & np.isfinite(periods) & np.isfinite(fft_amps)
                            periods = periods[period_mask]
                            fft_amps = fft_amps[period_mask]
                            
                            # Sorter efter periode
                            sort_idx = np.argsort(periods)
                            periods = periods[sort_idx]
                            fft_amps = fft_amps[sort_idx]
                            
                            # Find peak omkring 20 sekunder (15-25s bånd)
                            ms_band_mask = (periods >= 15) & (periods <= 25)
                            if np.any(ms_band_mask):
                                ms_periods = periods[ms_band_mask]
                                ms_amplitudes = fft_amps[ms_band_mask]
                                peak_idx = np.argmax(ms_amplitudes)
                                peak_period = ms_periods[peak_idx]
                                peak_amp = ms_amplitudes[peak_idx]
                            else:
                                # Fallback hvis ingen peak i 15-25s
                                if len(fft_amps) > 0:
                                    peak_idx = np.argmax(fft_amps)
                                    peak_period = periods[peak_idx]
                                    peak_amp = fft_amps[peak_idx]
                                else:
                                    peak_period = 20.0
                                    peak_amp = 0.0
                                    
                        except Exception as e:
                            st.error(f"FFT beregningsfejl: {str(e)}")
                            periods = None
                            fft_amps = None
                            peak_period = None
                            peak_amp = None
                        
                        if periods is not None:
                            # Filtrer data til kun at vise op til 35 sekunder
                            mask = periods <= 35
                            periods_filtered = periods[mask]
                            fft_amps_filtered = fft_amps[mask]
                            
                            # Find min og max for y-akse skalering
                            if len(fft_amps_filtered) > 0:
                                # Fokuser på området omkring peak
                                y_min = np.min(fft_amps_filtered[fft_amps_filtered > 0]) * 0.5
                                y_max = np.max(fft_amps_filtered) * 2.0
                                
                                # Hvis peak er identificeret, juster y-range omkring peak
                                if peak_amp and peak_period and peak_period <= 35:
                                    y_max = peak_amp * 3.0  # Giv plads over peak
                                    y_min = peak_amp * 0.01  # Vis ned til 1% af peak
                            else:
                                y_min, y_max = 1e-6, 1e-2
                            
                            # Opret professionel FFT figur
                            fft_fig = go.Figure()
                            
                            # Hovedspektrum med gradient fill
                            fft_fig.add_trace(go.Scatter(
                                x=periods_filtered,
                                y=fft_amps_filtered,
                                mode='lines',
                                name=f'FFT Spektrum ({comp_name})',
                                line=dict(color='rgb(138, 43, 226)', width=3),  # Tykkere linje
                                fill='tozeroy',
                                fillcolor='rgba(138, 43, 226, 0.15)',
                                hovertemplate='Periode: %{x:.1f}s<br>Amplitude: %{y:.2e}<extra></extra>'
                            ))
                            
                            # Tilføj shaded område for optimal Ms periode range (15-25s)
                            fft_fig.add_vrect(
                                x0=15, x1=25,
                                fillcolor="rgba(0, 150, 0, 0.15)",  # Mere synlig
                                layer="below",
                                line_width=0,
                                annotation_text="Optimal Ms range",
                                annotation_position="top left",
                                annotation_font_size=11,
                                annotation_font_color="darkgreen"
                            )
                            
                            # 20s reference linje
                            fft_fig.add_vline(
                                x=reference_period,
                                line=dict(color='red', width=2.5, dash='dash'),
                                annotation_text=f"{reference_period}s reference",
                                annotation_position="top right",
                                annotation_font_color="red",
                                annotation_font_size=12
                            )
                            
                            # Peak marking hvis fundet og inden for range
                            if peak_period and peak_amp and peak_period <= 35:
                                # Marker peak punkt
                                fft_fig.add_trace(go.Scatter(
                                    x=[peak_period],
                                    y=[peak_amp],
                                    mode='markers+text',
                                    name='Peak',
                                    marker=dict(
                                        size=15,  # Større markør
                                        color='lime',
                                        symbol='star',
                                        line=dict(color='darkgreen', width=2)
                                    ),
                                    text=[f'{peak_period:.1f}s'],
                                    textposition="top center",
                                    textfont=dict(size=14, color='darkgreen'),
                                    showlegend=False,
                                    hovertemplate=f'Peak periode: {peak_period:.1f}s<br>Amplitude: {peak_amp:.2e}<extra></extra>'
                                ))
                                
                                # Peak linje
                                fft_fig.add_vline(
                                    x=peak_period,
                                    line=dict(color='green', width=2, dash='dot'),
                                    annotation_text=f"Peak: {peak_period:.1f}s",
                                    annotation_position="bottom right",
                                    annotation_font_color="green",
                                    annotation_font_size=12
                                )
                            
                            # Layout med optimeret y-akse range
                            fft_fig.update_layout(
                                title=dict(
                                    text=f"Frekvensanalyse af overfladebølger ({comp_name} komponent)",
                                    font=dict(size=16, color='#2C3E50')
                                ),
                                xaxis=dict(
                                    title="Periode (s)",
                                    type="log",
                                    range=[np.log10(5), np.log10(35)],  # Stop ved 35s
                                    gridcolor='rgba(128, 128, 128, 0.2)',
                                    showgrid=True,
                                    zeroline=False,
                                    tickformat='.0f',
                                    dtick=0.301  # Log scale tick hver 2x (log10(2) ≈ 0.301)
                                ),
                                yaxis=dict(
                                    title="Spektral Amplitude",
                                    type="log",
                                    range=[np.log10(y_min), np.log10(y_max)],  # Dynamisk y-range
                                    gridcolor='rgba(128, 128, 128, 0.2)',
                                    showgrid=True,
                                    zeroline=False,
                                    tickformat='.2e',
                                    autorange=False  # Brug vores custom range
                                ),
                                height=500,  # Lidt højere
                                hovermode='x unified',
                                plot_bgcolor='white',
                                paper_bgcolor='rgba(250, 250, 250, 0.95)',
                                font=dict(family="Arial, sans-serif", size=12),
                                showlegend=True,
                                legend=dict(
                                    yanchor="top",
                                    y=0.99,
                                    xanchor="right",
                                    x=0.99,
                                    bgcolor="rgba(255, 255, 255, 0.9)",
                                    bordercolor="rgba(0, 0, 0, 0.2)",
                                    borderwidth=1
                                )
                            )
                            
                            fft_fig.update_yaxes(
                                minor=dict(ticklen=4, tickcolor='rgba(128, 128, 128, 0.1)', showgrid=True)
                            )
                            
                            st.plotly_chart(fft_fig, use_container_width=True)
                            
                            # Informativ boks med resultater
                            if peak_period:
                                col1, col2, col3 = st.columns(3)
                                
                                with col1:
                                    st.metric("Peak Periode", f"{peak_period:.1f}s")
                                
                                with col2:
                                    deviation = abs(peak_period - 20.0)
                                    quality = "Optimal" if deviation < 2.0 else "Acceptabel" if deviation < 5.0 else "Suboptimal"
                                    st.metric("Kvalitet", quality)
                                
                                with col3:
                                    st.metric("Afvigelse fra 20s", f"{deviation:.1f}s")
                                
                                if deviation < 2.0:
                                    st.success(f"✅ Peak periode ({peak_period:.1f}s) er optimal for Ms beregning")
                                elif deviation < 5.0:
                                    st.info(f"ℹ️ Peak periode ({peak_period:.1f}s) er acceptabel for Ms beregning")
                                else:
                                    st.warning(f"⚠️ Peak periode ({peak_period:.1f}s) afviger betydeligt fra 20s standard")
                        else:
                            st.warning("Kunne ikke udtrække overfladebølge vindue til FFT analyse")
            
            else:
                # Ingen beregning endnu eller fejl
                if st.session_state.get('ms_explanation'):
                    st.warning(st.session_state.ms_explanation)
                else:
                    st.info("Klik 'Beregn Ms Magnitude' for at starte analysen")

    def render_tools_export_view(self):
        """Render export tools view - kompakt version med tydelig filtrering og highres support"""
        st.markdown(f"## {texts[st.session_state.language]['nav_export']}")
        
        # Check om vi har data at eksportere
        if ('waveform_data' not in st.session_state or 
            'selected_earthquake' not in st.session_state or
            'selected_station' not in st.session_state):
            st.warning("📊 Ingen data at eksportere. Download først data fra Seismogram siden.")
            return
        
        # Hent data
        waveform_data = st.session_state.waveform_data
        selected_eq = st.session_state.selected_earthquake
        selected_station = st.session_state.selected_station
        
        # Kompakt info panel
        st.info(f"**Jordskælv:** M{selected_eq['magnitude']:.1f} - {selected_eq.get('location', 'Unknown')} | "
                f"**Station:** {selected_station['network']}.{selected_station['station']} ({selected_station['distance_km']:.0f} km)")
        
        # Check om vi har høj-opløsnings data
        has_highres = False
        if 'original_data' in waveform_data and 'displacement' in waveform_data['original_data']:
            has_highres = True
            highres_info = []
            for comp, data in waveform_data['original_data']['displacement'].items():
                if isinstance(data, dict) and 'sampling_rate' in data:
                    highres_info.append(f"{comp}: {data['sampling_rate']} Hz")
            
            if highres_info:
                st.success(f"✅ Høj-opløsnings data tilgængeligt: {', '.join(highres_info)}")
        
        # Export options med tydelig opdeling
        st.markdown("### Vælg data")
        
        # Ufiltrerede data
        st.markdown("**📊 Ufiltrerede data**")
        col1, col2 = st.columns(2)
        with col1:
            export_raw = st.checkbox("Rådata (counts) - direkte fra instrument", value=True)
            if has_highres:
                st.caption("📈 Bruger original sampling rate")
        with col2:
            export_unfiltered = st.checkbox("Displacement (mm) - kalibreret", value=True)
            if has_highres:
                st.caption("📈 Bruger høj-opløsnings data")
        
        st.markdown("---")
        
        # Filtrerede data
        st.markdown("**🎚️ Filtrerede data** *(båndpasfiltre)*")
        if has_highres:
            st.caption("📈 Alle filtre processeres på original høj-opløsnings data")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            export_broadband = st.checkbox("Bredbånd", value=False)
            st.caption("0.01-25 Hz")
        
        with col2:
            export_surface = st.checkbox("Overfladebølger", value=False)
            st.caption("0.02-0.5 Hz (Ms)")
        
        with col3:
            col3a, col3b = st.columns(2)
            with col3a:
                export_p = st.checkbox("P-bølger", value=False)
                st.caption("1-10 Hz")
            with col3b:
                export_s = st.checkbox("S-bølger", value=False)
                st.caption("0.5-5 Hz")
        
        # Avancerede indstillinger
        with st.expander("⚙️ Avancerede indstillinger"):
            col1, col2 = st.columns(2)
            with col1:
                # Standard sampling rate fra data
                current_rate = waveform_data.get('sampling_rate', 100)
                if has_highres:
                    # Vis original sampling rates
                    st.markdown("**Original sampling rates:**")
                    for comp, data in waveform_data['original_data']['displacement'].items():
                        if isinstance(data, dict) and 'sampling_rate' in data:
                            st.caption(f"{comp}: {data['sampling_rate']} Hz")
                
                st.markdown("**Datapunkter i Excel**")
                
                # Predefinerede muligheder med "Lav" tilføjet
                sample_option = st.radio(
                    "Vælg antal datapunkter:",
                    ["Lav (3600)", "Standard (7200)", "Høj (14400)", "Fuld opløsning", "Brugerdefineret"],
                    index=1,  # Standard som default
                    help="Flere punkter = større fil, bedre detaljer"
                )
                
                if sample_option == "Brugerdefineret":
                    max_samples = st.number_input(
                        "Antal punkter:",
                        min_value=1000,
                        max_value=100000,
                        value=7200,
                        step=1000
                    )
                elif sample_option == "Lav (3600)":
                    max_samples = 3600
                elif sample_option == "Standard (7200)":
                    max_samples = 7200
                elif sample_option == "Høj (14400)":
                    max_samples = 14400
                else:  # Fuld opløsning
                    max_samples = None
                
            with col2:
                st.markdown("**Estimeret filstørrelse**")
                # Beregn estimeret størrelse
                n_components = 3  # N, E, Z
                n_selected = sum([export_raw, export_unfiltered, export_broadband, 
                                export_surface, export_p, export_s])
                
                if max_samples:
                    total_points = max_samples * n_components * n_selected
                    # Groft estimat: ~20 bytes per datapunkt i Excel
                    size_mb = (total_points * 20) / (1024 * 1024)
                    st.metric("Størrelse", f"~{size_mb:.1f} MB")
                    
                    # Vis effektiv sampling rate
                    duration = len(waveform_data.get('time', [])) / current_rate
                    if duration > 0:
                        effective_rate = max_samples / duration
                        st.caption(f"Effektiv rate: ~{effective_rate:.1f} Hz")
                else:
                    st.metric("Størrelse", "Fuld (stor fil!)")
                    if has_highres:
                        st.caption("Bruger original sampling rate")
                    else:
                        st.caption(f"Display rate: {current_rate:.1f} Hz")
        
        # Sammensæt export options
        export_options = {
            'raw_data': export_raw,
            'unfiltered': export_unfiltered,
            'broadband': export_broadband,
            'surface': export_surface,
            'p_waves': export_p,
            's_waves': export_s
        }
        
        any_selected = any(export_options.values())
        
        # Info om Excel format
        with st.expander("📖 Excel format"):
            st.markdown("""
            **Sheets:** Metadata | Time_Series_Data | Ms_Calculation (hvis beregnet)  
            **Tidsformat:** Sekunder fra jordskælv (0 = jordskælvstid)  
            **Kolonner:** Tid + valgte datatyper (3 komponenter hver)
            """)
            if has_highres:
                st.info("📈 Data eksporteres i højest mulige opløsning")
        
        # Download knap - direkte download uden "generer" step
        if any_selected:
            # Hent managers
            data_manager = get_cached_data_manager()
            processor = get_cached_seismic_processor()
            
            # Forbered data
            export_waveform = waveform_data.copy()
            
            # Tilføj max_samples til waveform data
            if max_samples:
                export_waveform['max_samples_export'] = max_samples
            
            # Process filtre hvis valgt
            if any([export_broadband, export_surface, export_p, export_s]):
                export_waveform['arrival_times'] = {
                    'P': selected_station.get('p_arrival'),
                    'S': selected_station.get('s_arrival'),
                    'Surface': selected_station.get('surface_arrival')
                }
                
                export_waveform['filtered_datasets'] = {}
                
                filter_map = {
                    'broadband': export_broadband,
                    'surface': export_surface,
                    'p_waves': export_p,
                    's_waves': export_s
                }
                
                # Track om highres blev brugt
                used_highres_count = 0
                
                for filter_key, is_selected in filter_map.items():
                    if is_selected:
                        try:
                            # Process med filter - dette vil nu automatisk bruge highres data
                            filtered = processor.process_waveform_with_filtering(
                                export_waveform,
                                filter_type=filter_key,
                                remove_spikes=True,
                                calculate_noise=False
                            )
                            
                            # Check om highres blev brugt
                            if filtered and filtered.get('used_highres'):
                                used_highres_count += 1
                                print(f"DEBUG: Filter {filter_key} processed with high-resolution data")
                            
                            if filtered and 'filtered_data' in filtered:
                                export_waveform['filtered_datasets'][filter_key] = filtered['filtered_data']
                        except Exception as e:
                            print(f"Filter error for {filter_key}: {e}")
            
            # Generer Excel i baggrunden
            try:
                excel_data = data_manager.export_to_excel(
                    earthquake=selected_eq,
                    station=selected_station,
                    waveform_data=export_waveform,
                    ms_magnitude=st.session_state.get('ms_magnitude'),
                    ms_explanation=st.session_state.get('ms_explanation', ''),
                    export_options=export_options
                )
                
                if excel_data:
                    # Filnavn
                    eq_date = format_earthquake_time(selected_eq['time'], '%Y%m%d')
                    filename = f"GEOseis_{selected_station['network']}_{selected_station['station']}_{eq_date}_M{selected_eq['magnitude']:.1f}.xlsx"
                    
                    # Direkte download knap
                    st.download_button(
                        label="📥 Download Excel fil",
                        data=excel_data,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        type="primary"
                    )
                    
                    # Info om hvad der downloades
                    filter_count = sum([export_broadband, export_surface, export_p, export_s])
                    info_parts = []
                    
                    if sum([export_raw, export_unfiltered]) > 0:
                        info_parts.append(f"{sum([export_raw, export_unfiltered])} ufiltrerede")
                    if filter_count > 0:
                        info_parts.append(f"{filter_count} filtrerede")
                    
                    info_text = f"Filen indeholder: {' + '.join(info_parts)} datasæt"
                    
                    if max_samples:
                        info_text += f" • {max_samples} punkter"
                    else:
                        info_text += " • Fuld opløsning"
                    
                    if has_highres and (export_unfiltered or filter_count > 0):
                        info_text += " • 📈 Høj-opløsnings data"
                    
                    st.caption(info_text)
                else:
                    st.error("❌ Kunne ikke forberede Excel fil")
                    
            except Exception as e:
                st.error(f"❌ Export fejl: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
        else:
            st.warning("⚠️ Vælg mindst én datatype at eksportere")

    def render_about_view(self):
        """Render about page - Kortfattet version"""
        st.markdown(f"## {texts[st.session_state.language]['nav_about']}")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            if st.session_state.language == 'da':
                st.markdown("""
                ### Om GEOseis
                
                GEOseis er et undervisningsværktøj udviklet til det danske gymnasium, 
                der giver direkte adgang til professionelle seismiske data på en overskuelig måde.
                
                **Hovedfunktioner:**
                - Real-time jordskælvsdata fra IRIS
                - Automatisk stationsvalg baseret på afstand
                - Ms magnitude beregning efter IASPEI standarder
                - Interaktive seismogrammer med Plotly
                - Excel eksport til videre analyse i undervisningen
                
                **Pædagogisk værdi:**
                - Arbejde med rigtige videnskabelige data
                - Forståelse af bølgeteori og jordskælv
                - Databehandling og signalanalyse
                - Kritisk tænkning og fortolkning
                """)
            else:
                st.markdown("""
                ### About GEOseis
                
                GEOseis is an educational tool developed for Danish high schools,
                providing direct access to professional seismic data.
                
                **Main features:**
                - Real-time earthquake data from IRIS
                - Automatic station selection based on distance
                - Ms magnitude calculation per IASPEI standards
                - Interactive seismograms with Plotly
                - Excel export for further analysis 
                
                **Educational value:**
                - Work with real scientific data
                - Understanding wave theory and earthquakes
                - Data processing and signal analysis
                - Critical thinking and interpretation
                """)
        
        with col2:
            if st.session_state.language == 'da':
                st.markdown("""
                ### Information
                
                **Version:** 2.0  
                **Udgivet:** Aug 2025
                
                **Udvikler:**  
                Philip Kruse Jakobsen (pj@sg.dk) 
                Silkeborg Gymnasium  
                
                **Teknologi:**  
                - Python / Streamlit
                - ObsPy seismologi
                - IRIS Web Services
                - Plotly visualisering
                
                **Open Source:**  
                Koden er tilgængelig for
                undervisningsbrug.
                """)
            else:
                st.markdown("""
                ### Information
                
                **Version:** 2.0  
                **Released:** Aug. 2025
                
                **Developer:**  
                Philip Kruse Jakobsen (pj@sg.dk) 
                Silkeborg Gymnasium  
                
                **Technology:**  
                - Python / Streamlit
                - ObsPy seismology
                - IRIS Web Services
                - Plotly visualization
                
                **Open Source:**  
                Code is available for
                educational use.
                """)
        
        # Footer
        st.markdown("---")
        if st.session_state.language == 'da':
            st.caption("GEOseis 2.0 - Seismisk analyse til undervisningen")
        else:
            st.caption("GEOseis 2.0 - Seismic analysis for education")

    def run(self):
            """Main application loop"""
            self.load_modern_css()
            # Render header
            self.render_header()
            
            # Render sidebar
            self.render_sidebar()
            
            # Route to appropriate view - kun de nødvendige
            view_map = {
                'start': self.render_start_view,
                'data_search': self.render_data_search_view,
                'analysis_stations': self.render_analysis_stations_view,
                'analysis_waveform': self.render_analysis_waveform_view,
                'analysis_magnitude': self.render_analysis_magnitude_view,
                'tools_export': self.render_tools_export_view,
                'about': self.render_about_view
            }
            
            # Render view
            view_function = view_map.get(st.session_state.current_view, self.render_start_view)
            view_function()     


# Main execution
if __name__ == "__main__":
    app = GEOSeisV2()
    app.run()
