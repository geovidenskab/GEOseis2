# waveform_visualizer.py
"""
Waveform visualisering modul for GEOSeis 2.0
Håndterer plotting af seismiske data med Plotly
"""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Try to import ObsPy for UTCDateTime parsing
try:
    from obspy import UTCDateTime as ObsPyUTCDateTime
    OBSPY_AVAILABLE = True
except ImportError:
    OBSPY_AVAILABLE = False


def parse_arrival_time(arrival_value, eq_time_str=None):
    """
    Parser arrival time fra forskellige formater til sekunder.
    Håndterer UTCDateTime strings, objekter og numeriske værdier.
    """
    if arrival_value is None:
        return None
    
    # Hvis det allerede er et tal, returner det
    if isinstance(arrival_value, (int, float)):
        return float(arrival_value)
    
    # Hvis det er en string
    if isinstance(arrival_value, str):
        # Check for UTCDateTime string format
        if 'UTCDateTime' in arrival_value and OBSPY_AVAILABLE:
            try:
                # Parse UTCDateTime string: "UTCDateTime(2025, 1, 7, 1, 8, 36, 353168)"
                import re
                match = re.search(r'UTCDateTime\((.*?)\)', arrival_value)
                if match:
                    params = [x.strip() for x in match.group(1).split(',')]
                    # Konverter til integers
                    params = [int(p) for p in params]
                    
                    # Opret UTCDateTime objekt
                    arrival_utc = ObsPyUTCDateTime(*params)
                    
                    # Hvis vi har earthquake time, beregn relative sekunder
                    if eq_time_str:
                        try:
                            # Parse earthquake time
                            eq_utc = ObsPyUTCDateTime(eq_time_str)
                            
                            # Returner sekunder fra jordskælv
                            return float(arrival_utc - eq_utc)
                        except Exception as e:
                            print(f"Could not parse earthquake time: {eq_time_str}, error: {e}")
                            pass
                    
                    # Ellers returner som sekunder siden epoch (fallback)
                    return float(arrival_utc.timestamp)
            except Exception as e:
                print(f"Could not parse UTCDateTime string: {arrival_value}, error: {e}")
                return None
    
    # Hvis det er et UTCDateTime objekt
    try:
        if isinstance(arrival_value, ObsPyUTCDateTime) and OBSPY_AVAILABLE:
            if eq_time_str:
                eq_utc = ObsPyUTCDateTime(eq_time_str)
                return float(arrival_value - eq_utc)
            else:
                return float(arrival_value.timestamp)
    except:
        pass
    
    print(f"Could not parse arrival time: {arrival_value} (type: {type(arrival_value)})")
    return None



class WaveformVisualizer:
    """
    Visualiserer seismiske waveforms med Plotly
    Implementerer single-plot med togglebare komponenter som i v1.7
    """
    
    def __init__(self):
        self.default_colors = {
            'north': '#FF6B6B',      # Rød (identisk med v1.7)
            'east': '#4ECDC4',       # Turkis/Grøn 
            'vertical': '#45B7D1'    # Blå
        }
    
    def downsample_data(self, data, max_points=8000, return_indices=False):
        """
        Downsampler data for hurtigere visualisering.
        Identisk med implementering i GEOSeis 1.7
        """
        if len(data) <= max_points:
            if return_indices:
                return data, np.arange(len(data))
            return data
        
        # Beregn downsampling faktor
        factor = len(data) // max_points
        indices = np.arange(0, len(data), factor)[:max_points]
        
        if return_indices:
            return data[indices], indices
        return data[indices]

    def create_waveform_plot(self, waveform_data, show_components=None, 
                            show_arrivals=True, title="Seismogram",
                            height=600):
        """
        Opretter interaktivt seismogram plot med Plotly.
        FIXED: Robust håndtering af filtrerede data arrays.
        """
        try:
            # Default komponenter
            if show_components is None:
                show_components = {'north': True, 'east': True, 'vertical': True}
            
            # Hent displacement data
            displacement_data = waveform_data.get('displacement_data', {})
            if not displacement_data:
                return None
            
            # KRITISK FIX: Valider og konverter alle data til 1D numpy arrays
            cleaned_displacement_data = {}
            for comp_name, comp_data in displacement_data.items():
                if comp_data is not None:
                    # Konverter til numpy array
                    arr = np.array(comp_data)
                    
                    # Sørg for at det er 1D
                    if arr.ndim > 1:
                        print(f"WARNING: {comp_name} has shape {arr.shape}, flattening to 1D")
                        arr = arr.flatten()
                    
                    # Check for valid data
                    if len(arr) > 0 and np.any(np.isfinite(arr)):
                        cleaned_displacement_data[comp_name] = arr
                    else:
                        print(f"WARNING: {comp_name} has no valid data")
            
            displacement_data = cleaned_displacement_data
            
            if not displacement_data:
                print("ERROR: No valid displacement data after cleaning")
                return None
            
            # Hent time arrays
            time_arrays = {}
            times = waveform_data.get('time', np.array([]))
            
            # Konverter times til numpy array hvis det ikke allerede er det
            if not isinstance(times, np.ndarray):
                times = np.array(times)
            
            # Check for komponent-specifikke time arrays
            for comp in ['Z', 'N', 'E', '1', '2', '3']:
                if f'time_{comp}' in waveform_data:
                    time_arr = waveform_data[f'time_{comp}']
                    if not isinstance(time_arr, np.ndarray):
                        time_arr = np.array(time_arr)
                    
                    # Map til standard navn
                    if comp in ['Z', '3']:
                        time_arrays['vertical'] = time_arr
                    elif comp in ['N', '1']:
                        time_arrays['north'] = time_arr
                    elif comp in ['E', '2']:
                        time_arrays['east'] = time_arr
            
            # Fallback til generel time array
            if not time_arrays:
                for comp in ['north', 'east', 'vertical']:
                    if comp in displacement_data:
                        # Sørg for at time array matcher data længde
                        data_len = len(displacement_data[comp])
                        if len(times) == data_len:
                            time_arrays[comp] = times
                        else:
                            # Generer time array baseret på sampling rate
                            sampling_rate = waveform_data.get('sampling_rate', 100)
                            time_arrays[comp] = np.arange(data_len) / sampling_rate
                            print(f"Generated time array for {comp}: {data_len} samples at {sampling_rate} Hz")
            
            # Hent metadata
            units = waveform_data.get('units', 'mm')
            data_label = units
            
            # Parse arrival times
            station_info = waveform_data.get('station_info', {})
            p_arrival = station_info.get('p_arrival')
            s_arrival = station_info.get('s_arrival')
            surface_arrival = station_info.get('surface_arrival')
            
            # Parse arrival times til sekunder
            eq_time = waveform_data.get('earthquake_time')
            p_arrival = parse_arrival_time(p_arrival, eq_time)
            s_arrival = parse_arrival_time(s_arrival, eq_time)
            surface_arrival = parse_arrival_time(surface_arrival, eq_time)
            
            # INTELLIGENT DOWNSAMPLING FOR VISUALISERING
            max_points = 8000  # Maks punkter for smooth performance
            
            def downsample_for_plotting(times_array, data_array, max_pts=max_points):
                """
                Intelligent downsampling der bevarer peaks og vigtige features.
                Kun til visualisering - original data forbliver uændret.
                """
                try:
                    # Ensure we have numpy arrays
                    if not isinstance(data_array, np.ndarray):
                        data_array = np.array(data_array)
                    if not isinstance(times_array, np.ndarray):
                        times_array = np.array(times_array)
                    
                    # Validate arrays
                    if len(data_array) == 0 or len(times_array) == 0:
                        return times_array, data_array
                    
                    # Ensure samme længde
                    min_len = min(len(times_array), len(data_array))
                    if len(times_array) != len(data_array):
                        print(f"WARNING: Time and data arrays have different lengths ({len(times_array)} vs {len(data_array)})")
                        times_array = times_array[:min_len]
                        data_array = data_array[:min_len]
                    
                    data_len = len(data_array)
                    
                    # If already small enough, return as is
                    if data_len <= max_pts:
                        return times_array, data_array
                    
                    # Peak-preserving downsampling
                    downsample_factor = data_len / max_pts
                    indices = []
                    
                    for i in range(max_pts):
                        start_idx = int(i * downsample_factor)
                        end_idx = min(int((i + 1) * downsample_factor), data_len)
                        
                        if start_idx < data_len and end_idx <= data_len and start_idx < end_idx:
                            # Find peak (max absolute value) i dette vindue
                            window = data_array[start_idx:end_idx]
                            if len(window) > 0:
                                peak_idx = np.argmax(np.abs(window))
                                indices.append(start_idx + peak_idx)
                    
                    if indices:
                        indices = np.array(indices)
                        return times_array[indices], data_array[indices]
                    else:
                        # Fallback to simple downsampling
                        step = max(1, data_len // max_pts)
                        return times_array[::step], data_array[::step]
                        
                except Exception as e:
                    print(f"Downsample error: {e}")
                    # Return original if error
                    return times_array, data_array
            
            # Create figure
            fig = go.Figure()
            
            # Plot hver komponent
            colors = {'north': 'red', 'east': 'green', 'vertical': 'blue'}
            symbols = {'north': '🔴', 'east': '🟢', 'vertical': '🔵'}
            
            for comp_name, comp_color in colors.items():
                if show_components.get(comp_name, True) and comp_name in displacement_data:
                    # Hent fuld opløsnings data
                    comp_times = time_arrays.get(comp_name, times)
                    comp_data = displacement_data[comp_name]
                    
                    # Downsample KUN for plotting
                    plot_times, plot_data = downsample_for_plotting(comp_times, comp_data)
                    
                    print(f"DEBUG: {comp_name} - Original: {len(comp_data)} points, Plot: {len(plot_data)} points")
                    
                    # Tilføj trace
                    fig.add_trace(go.Scatter(
                        x=plot_times,
                        y=plot_data,
                        mode='lines',
                        name=f'{symbols[comp_name]} {comp_name.capitalize()} ({data_label})',
                        line=dict(color=comp_color, width=1.5),
                        hovertemplate='Tid: %{x:.2f} s<br>Amplitude: %{y:.2f} ' + data_label + '<extra></extra>'
                    ))
            
            # Tilføj arrival time linjer
            if show_arrivals:
                # P-wave
                if p_arrival is not None:
                    fig.add_vline(
                        x=p_arrival,
                        line_dash="dash",
                        line_color="red",
                        annotation_text="P",
                        annotation_position="top"
                    )
                
                # S-wave
                if s_arrival is not None:
                    fig.add_vline(
                        x=s_arrival,
                        line_dash="dash",
                        line_color="blue",
                        annotation_text="S",
                        annotation_position="top"
                    )
                
                # Surface wave
                if surface_arrival is not None:
                    fig.add_vline(
                        x=surface_arrival,
                        line_dash="dash",
                        line_color="green",
                        annotation_text="Surface",
                        annotation_position="top"
                    )
            
            # Update layout
            fig.update_layout(
                title=title,
                xaxis_title="Tid siden jordskælv (s)",
                yaxis_title=f"Forskydning ({data_label})",
                height=height,
                hovermode='x unified',
                showlegend=True,
                legend=dict(
                    yanchor="top",
                    y=0.99,
                    xanchor="right",
                    x=0.99
                ),
                xaxis=dict(
                    rangeslider=dict(visible=False),
                    type='linear'
                )
            )
            
            # Tilføj jordskælv tidspunkt ved x=0
            fig.add_vline(
                x=0,
                line_width=1,
                line_dash="dot",
                line_color="black",
                annotation_text="Jordskælv",
                annotation_position="bottom"
            )
            
            return fig
            
        except Exception as e:
            print(f"Error creating waveform plot: {e}")
            import traceback
            traceback.print_exc()
            return None

    def create_p_wave_zoom_plot(self, waveform_data, station_info, processed_data=None):
        """
        Opretter zoom plot omkring P-bølge ankomst
        Implementering fra GEOSeis 1.7 med STA/LTA detektion
        """
        if not waveform_data or not station_info:
            return None, None
            
        time_array = waveform_data.get('time')
        if time_array is None:
            time_array = waveform_data.get('time_array', np.array([]))
            
        sampling_rate = waveform_data.get('sampling_rate', 100)
        p_arrival = station_info.get('p_arrival')
        
        if p_arrival is None or time_array is None:
            return None, None
            
        # Konverter p_arrival til sekunder hvis nødvendigt
        p_arrival = parse_arrival_time(p_arrival)
        if p_arrival is None:
            return None, None
            
        # Find index for P-wave
        p_index = np.argmin(np.abs(time_array - p_arrival))
        
        # Definer zoom vindue (10 sekunder før, 20 sekunder efter)
        zoom_start = max(0, p_index - int(10 * sampling_rate))
        zoom_end = min(len(time_array), p_index + int(20 * sampling_rate))
        
        # Create subplot figure
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            subplot_titles=('Nord', 'Øst', 'Vertikal'),
            vertical_spacing=0.05
        )
        
        # Hent data
        displacement_data = waveform_data.get('displacement_data', {})
        
        # Plot hver komponent
        components = ['north', 'east', 'vertical']
        colors = ['red', 'green', 'blue']
        
        peak_info = {}
        
        for idx, (comp, color) in enumerate(zip(components, colors)):
            if comp in displacement_data:
                data = displacement_data[comp][zoom_start:zoom_end]
                time = time_array[zoom_start:zoom_end]
                
                # Plot waveform
                fig.add_trace(
                    go.Scatter(
                        x=time,
                        y=data,
                        mode='lines',
                        name=comp.capitalize(),
                        line=dict(color=color, width=1),
                        showlegend=False
                    ),
                    row=idx+1, col=1
                )
                
                # Marker P-wave
                fig.add_vline(
                    x=p_arrival,
                    line_dash="dash",
                    line_color="black",
                    annotation_text="P",
                    annotation_position="top",
                    row=idx+1, col=1
                )
                
                # Find peak amplitude i vinduet
                peak_idx = np.argmax(np.abs(data))
                peak_time = time[peak_idx]
                peak_value = data[peak_idx]
                
                peak_info[comp] = {
                    'time': peak_time,
                    'amplitude': peak_value,
                    'delay_from_p': peak_time - p_arrival
                }
                
                # Marker peak
                fig.add_trace(
                    go.Scatter(
                        x=[peak_time],
                        y=[peak_value],
                        mode='markers',
                        marker=dict(color='orange', size=8),
                        showlegend=False,
                        hovertemplate=f'Peak: {peak_value:.2f} mm<br>Time: {peak_time:.2f} s'
                    ),
                    row=idx+1, col=1
                )
        
        # Update layout
        fig.update_layout(
            height=600,
            title="P-bølge Zoom Analyse",
            showlegend=False,
            hovermode='x unified'
        )
        
        # Update axes
        fig.update_xaxes(title_text="Tid (s)", row=3, col=1)
        fig.update_yaxes(title_text="mm", row=2, col=1)
        
        return fig, peak_info
