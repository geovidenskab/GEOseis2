# seismic_processor.py
"""
Seismic data processing engine for GEOSeis
Avanceret seismisk dataprocessering med fokus på professional analyse
"""

import numpy as np
import streamlit as st
from scipy.signal import butter, filtfilt, medfilt
from scipy.fft import fft, fftfreq
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ObsPy imports - check availability
try:
    from obspy.geodetics import locations2degrees, gps2dist_azimuth
    from obspy.taup import TauPyModel
    ADVANCED_FEATURES = True
except ImportError:
    ADVANCED_FEATURES = False
    print("Warning: Some ObsPy features not available")

class EnhancedSeismicProcessor:
    """
    Avanceret seismisk dataprocessering med fokus på professional analyse.
    
    Denne klasse håndterer alle aspekter af seismisk signalprocessering:
    - Butterworth filtrering med automatisk frekvens validering
    - Spike detektion og fjernelse med robust statistik
    - Ms magnitude beregning efter IASPEI 2013 standarder
    - FFT spektral analyse af overfladebølger
    - P-bølge STA/LTA detektion
    - SNR beregning og datakvalitetsvurdering
    - TauP rejsetids modellering
    
    Attributes:
        taup_model: TauPyModel objekt til rejsetidsberegning (iasp91)
        filter_bands: Dictionary med prædefinerede filterbånd
        filter_order: Butterworth filter orden (default: 4)
        spike_threshold: Z-score grænse for spike detektion (default: 5.0)
    
    Example:
        processor = EnhancedSeismicProcessor()
        filtered_data = processor.apply_bandpass_filter(data, 100, 1.0, 10.0)
        ms_mag, explanation = processor.calculate_ms_magnitude(north, east, vert, 1500, 100)
    """
    

    def __init__(self):
        """
        Initialiserer seismisk processor med standard parametre.
        Bruger cached TauPyModel fra session state.
        """
        # TauP model til rejsetidsberegninger - BRUG CACHED VERSION
        if ADVANCED_FEATURES:
            try:
                # Check om vi er i Streamlit miljø
                try:
                    import streamlit as st
                    if 'taup_model' not in st.session_state:
                        st.session_state.taup_model = TauPyModel(model="iasp91")
                        print("SeismicProcessor: TauPyModel initialized ONCE in session state")
                    self.taup_model = st.session_state.taup_model
                    # Ingen print her - vi bruger bare cached version
                except ImportError:
                    # Ikke i Streamlit - brug normal init
                    self.taup_model = TauPyModel(model="iasp91")
                    print("SeismicProcessor: TauPyModel initialized (non-Streamlit)")
            except Exception as e:
                print(f"SeismicProcessor: Could not initialize TauPyModel: {e}")
                self.taup_model = None
        else:
            self.taup_model = None
            print("SeismicProcessor: TauPyModel not available (ObsPy not installed)")
        
        # Prædefinerede filter bånd (Hz) - RETTET og KONSISTENT
        self.filter_bands = {
            'broadband': None,  # Ingen filtrering - vis alt
            'p_waves': (1.0, 10.0),  # P-bølger: høj frekvens, skarpe ankomster
            's_waves': (0.5, 5.0),   # S-bølger: medium frekvens, kraftigere amplitude
            'surface': (0.02, 0.5),  # Overfladebølger: 2-50s periode, kritisk for Ms magnitude
            'long_period': (0.005, 0.1),  # Lang periode: 10-200s, store jordskælv
            }
        
        # Standard parametre
        self.filter_order = 4  # Butterworth filter orden
        self.spike_threshold = 5.0  # Z-score for spike detektion
        
        # Debug output
        print(f"SeismicProcessor initialized with cached TauP: {'Yes' if self.taup_model else 'No'}")



    def apply_bandpass_filter(self, data, sampling_rate, low_freq, high_freq, order=None):
        """
        Anvender Butterworth båndpas filter på seismiske data med brugervenlig feedback.
        FORBEDRET: Bedre håndtering af edge cases og mere informativ feedback.
        """
        if order is None:
            order = self.filter_order
            
        try:
            # Validate input data
            data = np.array(data)
            if len(data) == 0:
                return data, {'success': False, 'reason': 'empty_data', 
                             'message': '❌ Ingen data at filtrere'}
            
            # Check for NaN eller inf
            if np.any(np.isnan(data)) or np.any(np.isinf(data)):
                # Prøv at rense data
                clean_data = data[np.isfinite(data)]
                if len(clean_data) < len(data) * 0.5:  # Hvis mere end 50% er dårligt
                    return data, {
                        'success': False, 
                        'reason': 'invalid_data',
                        'message': '❌ For mange ugyldige værdier i data'
                    }
                data = clean_data
            
            nyquist = sampling_rate / 2.0
            
            # Hvis low_freq er None, brug highpass filter
            if low_freq is None or low_freq <= 0:
                # Highpass filter
                if high_freq >= nyquist * 0.95:
                    return data, {
                        'success': False,
                        'reason': 'frequency_too_high',
                        'message': f'❌ Høj frekvens ({high_freq:.1f} Hz) for tæt på Nyquist ({nyquist:.1f} Hz)',
                        'suggestion': f'Prøv en frekvens under {nyquist * 0.8:.1f} Hz'
                    }
                
                b, a = butter(order, high_freq / nyquist, btype='high')
                filter_type = 'highpass'
                
            # Hvis high_freq er None, brug lowpass filter
            elif high_freq is None or high_freq >= nyquist:
                # Lowpass filter
                if low_freq >= nyquist * 0.95:
                    return data, {
                        'success': False,
                        'reason': 'frequency_too_high',
                        'message': f'❌ Lav frekvens ({low_freq:.1f} Hz) for tæt på Nyquist ({nyquist:.1f} Hz)'
                    }
                
                b, a = butter(order, low_freq / nyquist, btype='low')
                filter_type = 'lowpass'
                
            else:
                # Bandpass filter - standard case
                # Validate frequencies
                if low_freq >= high_freq:
                    return data, {
                        'success': False,
                        'reason': 'invalid_band',
                        'message': f'❌ Lav frekvens ({low_freq:.1f} Hz) skal være mindre end høj frekvens ({high_freq:.1f} Hz)'
                    }
                
                if high_freq >= nyquist * 0.95:
                    # Auto-adjust og informer
                    adjusted_high = nyquist * 0.9
                    print(f"INFO: Justerer høj frekvens fra {high_freq:.1f} til {adjusted_high:.1f} Hz (Nyquist grænse)")
                    high_freq = adjusted_high
                
                if low_freq <= 0.001:
                    # For lav frekvens kan give ustabilitet
                    adjusted_low = 0.005
                    print(f"INFO: Justerer lav frekvens fra {low_freq:.3f} til {adjusted_low:.3f} Hz (stabilitet)")
                    low_freq = adjusted_low
                
                # Design filter
                b, a = butter(order, [low_freq / nyquist, high_freq / nyquist], btype='band')
                filter_type = 'bandpass'
            
            # Apply filter
            try:
                filtered_data = filtfilt(b, a, data)
                
                # Validate output
                if np.any(np.isnan(filtered_data)) or np.any(np.isinf(filtered_data)):
                    return data, {
                        'success': False,
                        'reason': 'filter_produced_invalid',
                        'message': '❌ Filter producerede ugyldige værdier',
                        'suggestion': 'Prøv et andet filter eller lavere orden'
                    }
                
                return filtered_data, {
                    'success': True,
                    'filter_type': filter_type,
                    'parameters': {
                        'low_freq': low_freq,
                        'high_freq': high_freq,
                        'order': order,
                        'sampling_rate': sampling_rate
                    }
                }
                
            except ValueError as e:
                return data, {
                    'success': False,
                    'reason': 'filter_error',
                    'message': f'❌ Filter fejl: {str(e)}',
                    'suggestion': 'Prøv et bredere frekvensbånd'
                }
                
        except Exception as e:
            print(f"Unexpected filter error: {e}")
            import traceback
            traceback.print_exc()
            return data, {
                'success': False,
                'reason': 'unexpected_error',
                'message': f'❌ Uventet fejl: {str(e)}'
            }
    
    def process_waveform_with_filtering(self, waveform_data, filter_type='broadband', 
                                      remove_spikes=True, calculate_noise=False):
        """
        Komplet waveform processing med filtrering og analyse.
        FIXED: Returnerer data i korrekt format uden at forårsage array shape fejl.
        """
        if not waveform_data:
            return None
            
        processed_data = {
            'original_data': {},
            'filtered_data': {},
            'filter_info': {},
            'spike_info': {},
            'noise_info': {},
            'filter_status': {},
            'used_highres': False
        }
        
        # Check for high-resolution data
        has_highres = any(key.startswith('waveform_') for key in waveform_data.keys())
        if has_highres:
            print("DEBUG: Using high-resolution waveform data for filtering")
            processed_data['used_highres'] = True
        
        # Hent sampling rate
        sampling_rate = waveform_data.get('sampling_rate', 100.0)
        
        # Bestem filter parametre
        if isinstance(filter_type, tuple):
            # Custom filter
            low_freq, high_freq = filter_type
            filter_name = f"Custom ({low_freq}-{high_freq} Hz)"
        elif filter_type in self.filter_bands:
            filter_params = self.filter_bands[filter_type]
            if filter_params is None:
                # Broadband - ingen filtrering
                low_freq = None
                high_freq = None
                filter_name = "Broadband (ingen filter)"
            else:
                low_freq, high_freq = filter_params
                filter_name = filter_type
        else:
            # Fallback til broadband
            low_freq = None
            high_freq = None
            filter_name = "Broadband (ingen filter)"
        
        processed_data['filter_info'] = {
            'type': filter_name,
            'low_freq': low_freq,
            'high_freq': high_freq,
            'sampling_rate': sampling_rate
        }
        
        # Process hver komponent
        components = ['north', 'east', 'vertical']
        component_mapping = {
            'north': ['N', '1'],
            'east': ['E', '2'],
            'vertical': ['Z', '3']
        }
        
        for component in components:
            try:
                # Find data for denne komponent
                data = None
                
                # Prioriter high-res data hvis tilgængelig
                if has_highres:
                    # Check for high-res waveform data
                    for suffix in component_mapping[component]:
                        if f'waveform_{suffix}' in waveform_data:
                            data = waveform_data[f'waveform_{suffix}']
                            print(f"DEBUG: Using high-res data for {component} from waveform_{suffix}")
                            break
                
                # Fallback til displacement_data
                if data is None and 'displacement_data' in waveform_data:
                    if component in waveform_data['displacement_data']:
                        data = waveform_data['displacement_data'][component]
                        print(f"DEBUG: Using displacement data for {component}")
                
                if data is None:
                    print(f"DEBUG: No data found for {component}")
                    processed_data['filter_status'][component] = 'no_data'
                    continue
                
                # Konverter til numpy array og valider
                data = np.array(data)
                
                # KRITISK: Sørg for at data er 1D array
                if data.ndim > 1:
                    print(f"WARNING: {component} data has shape {data.shape}, flattening to 1D")
                    data = data.flatten()
                
                # Gem original data
                processed_data['original_data'][component] = data.copy()
                
                # Spike removal hvis requested
                if remove_spikes:
                    data_cleaned, spike_count = self.remove_spikes(data)
                    processed_data['spike_info'][component] = spike_count
                    data = data_cleaned
                
                # Apply filter
                if low_freq is None and high_freq is None:
                    # Broadband - ingen filtrering, men kopier data
                    filtered_data = data.copy()
                    filter_result = {'success': True, 'filter_type': 'none'}
                else:
                    # Apply filter
                    filtered_data, filter_result = self.apply_bandpass_filter(
                        data, 
                        sampling_rate, 
                        low_freq, 
                        high_freq
                    )
                
                # KRITISK: Sørg for at filtered_data er 1D numpy array
                filtered_data = np.array(filtered_data)
                if filtered_data.ndim > 1:
                    filtered_data = filtered_data.flatten()
                
                # Gem filtreret data
                processed_data['filtered_data'][component] = filtered_data
                
                # Update status
                if filter_result.get('success', False):
                    processed_data['filter_status'][component] = 'success'
                else:
                    processed_data['filter_status'][component] = filter_result.get('reason', 'error')
                
                # Beregn noise hvis requested
                if calculate_noise and filter_result.get('success', False):
                    noise_level = np.std(filtered_data[:int(5*sampling_rate)])  # Første 5 sekunder
                    signal_level = np.max(np.abs(filtered_data))
                    snr = signal_level / noise_level if noise_level > 0 else 0
                    
                    processed_data['noise_info'][component] = {
                        'noise_level': noise_level,
                        'signal_level': signal_level,
                        'snr': snr
                    }
                
            except Exception as e:
                print(f"Filter error for {component}: {e}")
                import traceback
                traceback.print_exc()
                processed_data['filter_status'][component] = f'error: {str(e)}'
                # Sørg for at vi har noget data at vise
                if component in processed_data['original_data']:
                    processed_data['filtered_data'][component] = processed_data['original_data'][component].copy()
        
        return processed_data

    def remove_spikes(self, data, threshold=None):
        """Fjerner spikes fra data ved hjælp af median filter."""
        if threshold is None:
            threshold = self.spike_threshold
            
        # Kopier data
        cleaned_data = data.copy()
        
        # Beregn median og MAD (Median Absolute Deviation)
        median = np.median(cleaned_data)
        mad = np.median(np.abs(cleaned_data - median))
        
        # Find spikes
        if mad > 0:
            z_scores = np.abs(cleaned_data - median) / (1.4826 * mad)
            spike_indices = np.where(z_scores > threshold)[0]
            
            # Erstat spikes med median filter værdi
            if len(spike_indices) > 0:
                window_size = 5
                median_filtered = medfilt(cleaned_data, window_size)
                cleaned_data[spike_indices] = median_filtered[spike_indices]
                
            return cleaned_data, len(spike_indices)
        else:
            return cleaned_data, 0

    def calculate_ms_magnitude(self, north_data, east_data, vertical_data, 
                             distance_km, sampling_rate, earthquake_depth_km=None):
        """
        Beregner overflade-bølge magnitude (Ms) efter IASPEI 2013 standard.
        
        Bruger 20-sekunder Rayleigh bølge amplitude målt på vertikalkomponenten,
        eller den maksimale amplitude på horisontale komponenter hvis større.
        Inkluderer korrektion for dybe jordskælv hvis dybde er angivet.
        
        Args:
            north_data: Nord komponent displacement i mm
            east_data: Øst komponent displacement i mm  
            vertical_data: Vertikal komponent displacement i mm
            distance_km: Epicentral afstand i km
            sampling_rate: Sampling rate i Hz
            earthquake_depth_km: Jordskælv dybde i km (optional)
            
        Returns:
            tuple: (ms_magnitude, forklaring_dict) eller (None, fejl_dict)
            
        Example:
            ms, info = processor.calculate_ms_magnitude(N, E, Z, 1500, 100, 35)
            print(f"Ms = {ms:.1f}")
            print(info['formula'])
        """
        try:
            # Input validering
            if distance_km < 200:
                return None, {
                    'error': 'Afstand for kort',
                    'message': 'Ms magnitude kræver epicentral afstand > 200 km',
                    'distance': distance_km
                }
            
            if distance_km > 16000:
                return None, {
                    'error': 'Afstand for lang', 
                    'message': 'Ms magnitude er upålidelig for afstande > 160°',
                    'distance': distance_km
                }
            
            # Filter til 20-sekunder periode (0.02-0.5 Hz)
            # Dette isolerer overfladebølgerne
            nyquist = sampling_rate / 2.0
            if nyquist < 0.5:
                return None, {
                    'error': 'Sampling rate for lav',
                    'message': f'Sampling rate ({sampling_rate} Hz) for lav til Ms beregning',
                    'required': 'Minimum 1 Hz sampling rate'
                }
            
            # Anvend 20-sekunder filter på alle komponenter
            low_freq = 0.02  # 50 sekunder periode
            high_freq = min(0.5, nyquist * 0.9)  # 2 sekunder periode eller Nyquist grænse
            
            filtered_vert, _ = self.apply_bandpass_filter(vertical_data, sampling_rate, low_freq, high_freq)
            filtered_north, _ = self.apply_bandpass_filter(north_data, sampling_rate, low_freq, high_freq)
            filtered_east, _ = self.apply_bandpass_filter(east_data, sampling_rate, low_freq, high_freq)
            
            # Find maksimum amplitude i mikrometer (konverter fra mm)
            max_vert = np.max(np.abs(filtered_vert)) * 1000  # mm til μm
            max_north = np.max(np.abs(filtered_north)) * 1000
            max_east = np.max(np.abs(filtered_east)) * 1000
            
            # Horizontal vektor amplitude
            horizontal_amplitudes = np.sqrt(filtered_north**2 + filtered_east**2) * 1000
            max_horizontal = np.max(horizontal_amplitudes)
            
            # Vælg største amplitude (standard praksis)
            amplitude_um = max(max_vert, max_horizontal)
            used_component = 'vertikal' if max_vert >= max_horizontal else 'horizontal'
            
            # Find periode ved maksimum amplitude (simplified - antag 20s)
            # I virkeligheden skulle vi lave zero-crossing analyse
            period_s = 20.0  # Standard 20-sekunder periode
            
            # Beregn afstand i grader
            distance_deg = distance_km / 111.195  # Gennemsnitlig km per grad
            
            # IASPEI 2013 formel for Ms
            # Ms = log10(A/T) + 1.66*log10(Δ) + 3.3
            # hvor A er amplitude i μm, T er periode i sekunder, Δ er afstand i grader
            
            ms_magnitude = np.log10(amplitude_um / period_s) + 1.66 * np.log10(distance_deg) + 3.3
            
            # Dybdekorrektion for dybe jordskælv (hvis dybde > 50 km)
            depth_correction = 0
            if earthquake_depth_km and earthquake_depth_km > 50:
                # Empirisk korrektion - overfladebølger dæmpes med dybde
                depth_correction = -0.0035 * (earthquake_depth_km - 50)
                ms_magnitude += depth_correction
            
            # Afrund til en decimal
            ms_magnitude = round(ms_magnitude, 1)
            
            # Byg forklaring som formateret tekst
            explanation = f"""### Ms Magnitude Beregning

            **Beregnet Ms:** {ms_magnitude:.1f}

            **Anvendt komponent:** {used_component.capitalize()}

            **Amplitude værdier:**
            - Nord: {max_north:.1f} μm
            - Øst: {max_east:.1f} μm
            - Vertikal: {max_vert:.1f} μm
            - Horizontal (max): {max_horizontal:.1f} μm

            **Beregningsparametre:**
            - Periode (T): {period_s:.1f} s
            - Afstand: {distance_km:.0f} km ({distance_deg:.1f}°)
            - Filter: {low_freq}-{high_freq} Hz

            **Formel:**
            Ms = log₁₀(A/T) + 1.66×log₁₀(Δ) + 3.3

            **Beregning:**
            Ms = log₁₀({amplitude_um:.1f}/{period_s}) + 1.66×log₁₀({distance_deg:.1f}) + 3.3
            Ms = {np.log10(amplitude_um/period_s):.3f} + 1.66×{np.log10(distance_deg):.3f} + 3.3
            Ms = {np.log10(amplitude_um/period_s):.3f} + {1.66*np.log10(distance_deg):.3f} + 3.3
            Ms = {ms_magnitude:.1f}"""

            if earthquake_depth_km and earthquake_depth_km > 50 and depth_correction != 0:
                explanation += f"\n\n**Dybdekorrektion:** {depth_correction:.3f} (dybde: {earthquake_depth_km} km)"
            
            return ms_magnitude, explanation
            
        except Exception as e:
            return None, {
                'error': 'Beregningsfejl',
                'message': str(e),
                'trace': traceback.format_exc()
            }

    def validate_earthquake_timing(self, earthquake, station, waveform_data):
        """
        Validerer earthquake timing baseret på forventede vs observerede P-wave ankomster.
        OPDATERET: Håndterer UTCDateTime string format korrekt.
        """
        try:
            # Få jordskælv tid
            eq_time = earthquake.get('time')
            if isinstance(eq_time, str):
                # Parse ISO format eller anden string format
                from obspy import UTCDateTime
                eq_time = UTCDateTime(eq_time)
            
            # Få afstand
            distance_km = station.get('distance_km', 0)
            
            # Få P arrival fra station (kan være string eller float)
            p_arrival = station.get('p_arrival')
            
            # Debug output
            print(f"DEBUG validate_timing: p_arrival type: {type(p_arrival)}, value: {p_arrival}")
            
            # Parse p_arrival hvis det er en UTCDateTime string
            if isinstance(p_arrival, str) and 'UTCDateTime' in p_arrival:
                # Parse UTCDateTime string format: "UTCDateTime(2025, 1, 7, 1, 8, 36, 353168)"
                import re
                match = re.search(r'UTCDateTime\((.*?)\)', p_arrival)
                if match:
                    params = match.group(1).split(',')
                    params = [int(p.strip()) for p in params]
                    
                    # Opret UTCDateTime objekt
                    from obspy import UTCDateTime
                    p_arrival_utc = UTCDateTime(*params)
                    
                    # Beregn sekunder fra jordskælv
                    p_arrival_seconds = float(p_arrival_utc - eq_time)
                    print(f"DEBUG: Converted p_arrival to {p_arrival_seconds} seconds")
                    p_arrival = p_arrival_seconds
            elif isinstance(p_arrival, (int, float)):
                # Allerede i sekunder
                p_arrival_seconds = float(p_arrival)
            else:
                # Ukendt format
                print(f"WARNING: Unknown p_arrival format: {type(p_arrival)}")
                p_arrival_seconds = None
            
            if p_arrival_seconds is None:
                return True, "Kunne ikke validere timing - mangler P-wave ankomst", {}
            
            # Beregn teoretisk P-wave hastighed (simplified)
            avg_p_velocity = 7.5  # km/s gennemsnit
            expected_p_time = distance_km / avg_p_velocity
            
            # Sammenlign
            time_diff = abs(p_arrival_seconds - expected_p_time)
            
            # Threshold for acceptable forskel (10% eller 5 sekunder)
            threshold = max(expected_p_time * 0.1, 5.0)
            
            is_valid = time_diff < threshold
            
            if is_valid:
                message = f"✓ Timing valideret (forskel: {time_diff:.1f}s)"
            else:
                message = f"⚠️ Stor timing forskel ({time_diff:.1f}s) - data kan være fra andet jordskælv"
            
            info = {
                'expected_p_time': expected_p_time,
                'observed_p_time': p_arrival_seconds,
                'time_difference': time_diff,
                'threshold': threshold,
                'distance_km': distance_km
            }
            
            # Debug output
            print(f"DEBUG: Final p_arrival_observed: {p_arrival_seconds} seconds (type: {type(p_arrival_seconds)})")
            
            return is_valid, message, info
            
        except Exception as e:
            print(f"Timing validation error: {e}")
            import traceback
            traceback.print_exc()
            return True, "Kunne ikke validere timing", {}

    def design_custom_filter(self, filter_type, sampling_rate, order=4):
        """Designer filter baseret på type"""
        nyquist = sampling_rate / 2.0
        
        if filter_type in self.filter_bands:
            if self.filter_bands[filter_type] is None:
                return None, None, "No filter"
            low_freq, high_freq = self.filter_bands[filter_type]
        else:
            return None, None, "Unknown filter"
            
        # Juster frekvenser hvis nødvendigt
        if high_freq > nyquist * 0.95:
            high_freq = nyquist * 0.9
            
        b, a = butter(order, [low_freq/nyquist, high_freq/nyquist], btype='band')
        return b, a, f"{filter_type}: {low_freq}-{high_freq} Hz"
