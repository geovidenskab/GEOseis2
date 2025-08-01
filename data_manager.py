# data_manager.py - UNIFIED VERSION med v1.7 implementation
"""
Unified Data Manager for GEOseis 2.0 - Tilbage til v1.7's velfungerende approach
================================================================================

VIGTIGE ÆNDRINGER FRA SESSION 13:
1. Station søgning bruger ORIGINAL v1.7 geografisk fordeling
2. Validerer KUN udvalgte stationer, ikke alle
3. Returnerer arrival times som SEKUNDER (float) ikke UTCDateTime strings
4. Pragmatisk approach: vis data selv uden response
5. Alt samlet i én fil for bedre performance

PRINCIPPER:
- Hastighed over perfektion
- Vis data frem for at fejle
- Geografisk fordeling prioriteres
- Minimal validation
"""

import streamlit as st
from obspy.clients.fdsn import Client
from obspy import UTCDateTime, Stream
from obspy.taup import TauPyModel
from obspy.geodetics import gps2dist_azimuth, kilometers2degrees, locations2degrees
import numpy as np
import pandas as pd
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
import warnings
import gc
import re
import threading
from typing import Dict, List, Tuple, Optional, Any
from io import BytesIO
import xlsxwriter

# Suppress warnings
warnings.filterwarnings('ignore')

def get_cached_taup_model():
    """Returnerer cached TauPyModel instans"""
    if 'taup_model' not in st.session_state:
        print("Creating new TauPyModel instance...")
        st.session_state.taup_model = TauPyModel(model="iasp91")
    return st.session_state.taup_model

def ensure_utc_datetime(time_obj):
    """Konverterer forskellige tidsformater til UTCDateTime"""
    if time_obj is None:
        return None
    
    if isinstance(time_obj, UTCDateTime):
        return time_obj
    
    if isinstance(time_obj, str):
        # Håndter ISO format
        if 'T' in time_obj:
            return UTCDateTime(time_obj)
        # Håndter andre string formater
        return UTCDateTime(time_obj)
    
    if isinstance(time_obj, (int, float)):
        return UTCDateTime(time_obj)
    
    if hasattr(time_obj, 'timestamp'):
        return UTCDateTime(time_obj.timestamp())
    
    # Sidste forsøg
    return UTCDateTime(str(time_obj))

class StreamlinedDataManager:
    """
    Unified data manager med v1.7's velfungerende implementation.
    
    VIGTIGE ÆNDRINGER:
    - search_stations bruger original geografisk fordeling
    - Minimal validation - kun udvalgte stationer
    - Arrival times som sekunder
    - Pragmatisk waveform download
    """
    
    def __init__(self):
        """Initialiserer data manager med cached komponenter"""
        # IRIS client
        self.client = None
        self.connect_to_iris()
        
        # Cached TauP model
        self.taup_model = get_cached_taup_model()
        
        # Processor reference - sættes eksternt hvis nødvendigt
        self.processor = None
        
        # Initialize caches hvis ikke eksisterer
        if 'earthquake_cache' not in st.session_state:
            st.session_state.earthquake_cache = {}
        if 'station_cache' not in st.session_state:
            st.session_state.station_cache = {}
        if 'waveform_cache' not in st.session_state:
            st.session_state.waveform_cache = {}
        if 'inventory_cache' not in st.session_state:
            st.session_state.inventory_cache = {}
    
    # ========================================
    # IRIS CONNECTION
    # ========================================
    
    def connect_to_iris(self):
        """Opretter forbindelse til IRIS med retries"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                print(f"Connecting to IRIS... (attempt {attempt + 1}/{max_retries})")
                self.client = Client("IRIS", timeout=30)
                # Test forbindelse
                test_time = UTCDateTime.now()
                self.client.get_stations(
                    network="IU", station="ANMO", 
                    starttime=test_time - 86400,
                    endtime=test_time,
                    level="station"
                )
                print("✓ IRIS connection established")
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    st.error(f"Kunne ikke oprette forbindelse til IRIS: {str(e)}")
                    return False
        return False
    
    # ========================================
    # EARTHQUAKE SEARCH
    # ========================================
    
    def fetch_latest_earthquakes(self, magnitude_range=(6.0, 10.0), 
                                year_range=None, depth_range=(0, 700),
                                limit=100, days=None):
        """
        Henter seneste jordskælv fra IRIS.
        Returnerer dictionaries med ISO timestamp strings.
        """
        try:
            # Tidsramme
            if days:
                endtime = UTCDateTime.now()
                starttime = endtime - (days * 86400)
            elif year_range:
                starttime = UTCDateTime(year_range[0], 1, 1)
                endtime = UTCDateTime(year_range[1], 12, 31, 23, 59, 59)
            else:
                endtime = UTCDateTime.now()
                starttime = endtime - (180 * 86400)  # 180 dage default
            
            # Check cache
            cache_key = f"{magnitude_range}_{year_range}_{depth_range}_{limit}_{starttime}_{endtime}"
            cached = self._check_cache('earthquake_cache', cache_key)
            if cached:
                return cached
            
            print(f"Searching earthquakes: M{magnitude_range[0]}-{magnitude_range[1]}, "
                  f"depth {depth_range[0]}-{depth_range[1]} km")
            
            # VIGTIG: Brug dybde i KILOMETER
            catalog = self.client.get_events(
                starttime=starttime,
                endtime=endtime,
                minmagnitude=magnitude_range[0],
                maxmagnitude=magnitude_range[1],
                mindepth=depth_range[0],    # KM
                maxdepth=depth_range[1],    # KM
                orderby="time",  # IRIS accepterer kun: time, time-asc, magnitude, magnitude-asc
                limit=limit
            )
            
            earthquakes = self._process_catalog(catalog)
            
            # Update cache
            if earthquakes:
                self._update_cache('earthquake_cache', cache_key, earthquakes)
            
            return earthquakes
            
        except Exception as e:
            st.error(f"Fejl ved jordskælvssøgning: {str(e)}")
            print(f"Earthquake search error: {e}")
            return []
    
    def get_latest_significant_earthquakes(self, min_magnitude=6.5, days=180):
        """Quick method til at hente seneste store jordskælv"""
        return self.fetch_latest_earthquakes(
            magnitude_range=(min_magnitude, 10.0),
            days=days,
            limit=20
        )
    
    def _process_catalog(self, catalog):
        """
        Process ObsPy catalog til list af dictionaries.
        VIGTIG: Returnerer ISO timestamp strings, IKKE obspy_event!
        """
        earthquakes = []
        
        # Sortér catalog efter tid (nyeste først) siden IRIS kun giver "time" (ældste først)
        sorted_events = sorted(catalog, key=lambda e: e.preferred_origin().time, reverse=True)
        
        for event in sorted_events:
            try:
                # Få preferred origin og magnitude
                origin = event.preferred_origin() or event.origins[0]
                magnitude = event.preferred_magnitude() or event.magnitudes[0]
                
                # Lokation beskrivelse
                if event.event_descriptions:
                    location = event.event_descriptions[0].text
                else:
                    location = f"Lat: {origin.latitude:.2f}, Lon: {origin.longitude:.2f}"
                
                eq_dict = {
                    'time': origin.time.isoformat(),  # ISO string format!
                    'latitude': float(origin.latitude),
                    'longitude': float(origin.longitude),
                    'depth': float(origin.depth / 1000.0) if origin.depth else 10.0,  # Til km
                    'magnitude': float(magnitude.mag),
                    'magnitude_type': str(magnitude.magnitude_type) if magnitude.magnitude_type else 'M',
                    'location': location,
                    'event_id': str(event.resource_id).split('/')[-1]
                }
                
                # IKKE inkluderet: 'obspy_event' - dette forårsager problemer!
                
                earthquakes.append(eq_dict)
                
            except Exception as e:
                print(f"Error processing event: {e}")
                continue
        
        return earthquakes
    
    # ========================================
    # STATION SEARCH - ORIGINAL V1.7 IMPLEMENTATION
    # ========================================
    
    def search_stations(self, earthquake: Dict[str, Any], 
                       min_distance_km: float = 1000,
                       max_distance_km: float = 5000,
                       target_stations: int = 3,
                       progress_placeholder=None) -> List[Dict[str, Any]]:
        """
        ORIGINAL v1.7 implementation - finder geografisk distribuerede stationer.
        
        VIGTIGE ÆNDRINGER:
        - Bruger geografisk fordeling UDEN at validere alle stationer
        - Returnerer arrival times som SEKUNDER (float)
        - Minimal validation - kun de udvalgte stationer
        - Pragmatisk approach
        """
        # Earthquake parametere
        eq_lat = earthquake.get('latitude', 0)
        eq_lon = earthquake.get('longitude', 0)
        eq_depth = earthquake.get('depth', 10)
        eq_time = ensure_utc_datetime(earthquake.get('time'))
        
        if not eq_time:
            if progress_placeholder:
                progress_placeholder.error("Fejl: Kunne ikke parse jordskælvstid")
            return []
        
        # Progress indicators
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        
        start_time = time.time()
        
        try:
            # TRIN 1: Hent inventory
            progress_bar.progress(0.1)
            status_text.text("🔍 Søger stationer i IRIS database...")
            
            # Check cache først
            cache_key = f"{eq_lat:.2f},{eq_lon:.2f},{min_distance_km},{max_distance_km}"
            inventory = st.session_state.get('inventory_cache', {}).get(cache_key)
            
            if not inventory:
                # Søg stationer inden for radius
                inventory = self.client.get_stations(
                    latitude=eq_lat,
                    longitude=eq_lon,
                    minradius=kilometers2degrees(min_distance_km),
                    maxradius=kilometers2degrees(max_distance_km),
                    channel="BH?,HH?,SH?,EH?",
                    level="channel",
                    starttime=eq_time - 86400,
                    endtime=eq_time + 86400,
                    includerestricted=False,
                    matchtimeseries=False
                )
                
                # Cache kun for mindre søgninger
                if max_distance_km <= 3000:
                    st.session_state.inventory_cache[cache_key] = inventory
            
            # TRIN 2: Process stationer
            progress_bar.progress(0.3)
            status_text.text("📊 Processerer stationer...")
            
            all_stations = self._process_inventory_to_stations(
                inventory, eq_lat, eq_lon, eq_depth, eq_time,
                min_distance_km, max_distance_km
            )
            
            if not all_stations:
                progress_placeholder.warning("⚠️ Ingen stationer fundet")
                return self._fallback_station_list_optimized(
                    earthquake, min_distance_km, max_distance_km, target_stations
                )
            
            # TRIN 3: SMART UDVÆLGELSE - Original v1.7 approach
            progress_bar.progress(0.5)
            status_text.text(f"🎯 Udvælger optimalt fordelte stationer fra {len(all_stations)} kandidater...")
            
            # Sorter efter kvalitet og afstand
            all_stations.sort(key=lambda x: (
                x.get('network_priority', 99),
                x.get('channel_priority', 99),
                -x.get('operational_years', 0),
                x['distance_km']
            ))
            
            # ADAPTIV kandidat udvælgelse
            if len(all_stations) > 1000:
                # Meget mange stationer - tag kun de bedste
                candidates_count = min(len(all_stations), target_stations * 3)
                status_text.text(f"🎯 Mange stationer fundet ({len(all_stations)}) - fokuserer på {candidates_count} bedste")
            else:
                # Færre stationer - tag flere kandidater  
                candidates_count = min(len(all_stations), target_stations * 5)
            
            candidates = all_stations[:candidates_count]
            
            # Geografisk fordeling
            selected_stations = self._select_distributed_stations(candidates, target_stations * 2)
            
            # TRIN 4: SMART VALIDERING - kun de udvalgte!
            progress_bar.progress(0.7)
            
            if len(selected_stations) <= 20:
                # Få stationer - valider alle
                status_text.text(f"✅ Verificerer datatilgængelighed for {len(selected_stations)} stationer...")
                validated_stations = self._validate_stations_parallel(
                    selected_stations, eq_time, target_stations,
                    progress_bar, status_text
                )
            else:
                # Mange stationer - kun sample validering
                status_text.text(f"⚡ Mange stationer ({len(selected_stations)}) - bruger hurtig validering...")
                quick_validate_count = min(target_stations * 3, 15)
                quick_stations = selected_stations[:quick_validate_count]
                
                validated_stations = self._validate_stations_parallel(
                    quick_stations, eq_time, target_stations,
                    progress_bar, status_text
                )
                
                # Tilføj resten uden validering
                remaining_stations = selected_stations[quick_validate_count:]
                for station in remaining_stations:
                    station['data_verified'] = None  # Unknown status
                validated_stations.extend(remaining_stations)
            
            # Final selection
            progress_bar.progress(0.95)
            final_stations = validated_stations[:target_stations]
            
            # Success feedback
            progress_bar.progress(1.0)
            verified_count = sum(1 for s in final_stations if s.get('data_verified', False))
            total_time = time.time() - start_time
            
            if progress_placeholder:
                progress_placeholder.success(
                    f"✅ Fandt {len(final_stations)} stationer ({verified_count} verificeret) på {total_time:.1f} sekunder"
                )
            
            # Cleanup
            time.sleep(1.5)
            progress_bar.empty()
            status_text.empty()
            
            return final_stations
            
        except Exception as e:
            progress_bar.empty()
            status_text.empty()
            if progress_placeholder:
                progress_placeholder.error(f"Fejl ved stationssøgning: {str(e)}")
            return []
    
    def _process_inventory_to_stations(self, inventory, eq_lat, eq_lon, eq_depth, eq_time,
                                      min_distance_km, max_distance_km):
        """
        Helper metode til at processere ObsPy inventory til station liste.
        VIGTIG: Returnerer arrival times som SEKUNDER (float) ikke UTCDateTime!
        """
        stations = []
        
        # Prioriterede netværk scoring
        network_scores = {
            'IU': 1, 'II': 0,  # GSN - højeste prioritet
            'G': 2, 'GE': 2,   # GEOSCOPE/GEOFON
            'GT': 3, 'US': 4, 'CN': 4,  # Andre høj-kvalitet
        }
        
        for network in inventory:
            for station in network:
                try:
                    # Tjek channels og find bedste type
                    hh_channels = []
                    bh_channels = []
                    other_channels = []
                    
                    for channel in station.channels:
                        if channel.code.startswith('HH'):
                            hh_channels.append(channel)
                        elif channel.code.startswith('BH'):
                            bh_channels.append(channel)
                        elif channel.code[1] == 'H':  # ?H?
                            other_channels.append(channel)
                    
                    # Vælg bedste kanal type
                    if hh_channels:
                        selected_channels = hh_channels
                        channel_priority = 1
                        typical_rate = 100
                    elif bh_channels:
                        selected_channels = bh_channels
                        channel_priority = 2
                        typical_rate = 40
                    elif other_channels:
                        selected_channels = other_channels
                        channel_priority = 3
                        typical_rate = selected_channels[0].sample_rate if selected_channels else 20
                    else:
                        continue
                    
                    # Beregn distance og azimuth
                    distance_m, azimuth, _ = gps2dist_azimuth(
                        eq_lat, eq_lon, station.latitude, station.longitude
                    )
                    distance_km = distance_m / 1000.0
                    distance_deg = kilometers2degrees(distance_km)
                    
                    # Skip hvis uden for range
                    if distance_km < min_distance_km or distance_km > max_distance_km:
                        continue
                    
                    # Beregn arrival times med TauP - RETURNÉR SOM SEKUNDER!
                    p_arrival_seconds = None
                    s_arrival_seconds = None
                    
                    try:
                        arrivals = self.taup_model.get_travel_times(
                            source_depth_in_km=eq_depth,
                            distance_in_degree=distance_deg,
                            phase_list=["P", "S"]
                        )
                        
                        for arrival in arrivals:
                            if arrival.phase.name == "P" and p_arrival_seconds is None:
                                p_arrival_seconds = arrival.time  # Dette er allerede i sekunder!
                            elif arrival.phase.name == "S" and s_arrival_seconds is None:
                                s_arrival_seconds = arrival.time  # Dette er allerede i sekunder!
                    except:
                        # Fallback beregning
                        p_arrival_seconds = distance_km / 8.0  # ~8 km/s for P-waves
                        s_arrival_seconds = distance_km / 4.5  # ~4.5 km/s for S-waves
                    
                    # Beregn overfladebølge ankomst
                    surface_arrival_seconds = distance_km / 3.5  # ~3.5 km/s
                    
                    # Station info
                    station_info = {
                        'network': network.code,
                        'station': station.code,
                        'latitude': station.latitude,
                        'longitude': station.longitude,
                        'elevation': station.elevation,
                        'distance_km': round(distance_km, 1),
                        'distance_deg': round(distance_deg, 2),
                        'azimuth': round(azimuth, 1),
                        
                        # VIGTIG: Arrival times som SEKUNDER (float)!
                        'p_arrival': round(p_arrival_seconds, 3) if p_arrival_seconds else None,
                        's_arrival': round(s_arrival_seconds, 3) if s_arrival_seconds else None,
                        'surface_arrival': round(surface_arrival_seconds, 3),
                        
                        # Metadata
                        'channels': len(selected_channels),
                        'sample_rate': typical_rate,
                        'channel_codes': ','.join([ch.code for ch in selected_channels[:3]]),
                        'network_priority': network_scores.get(network.code, 99),
                        'channel_priority': channel_priority,
                        'operational_years': (eq_time.year - station.start_date.year) if station.start_date else 0,
                        'data_verified': None  # Will be set during validation
                    }
                    
                    stations.append(station_info)
                    
                except Exception as e:
                    print(f"Error processing station {network.code}.{station.code}: {e}")
                    continue
        
        return stations
    
    def _select_distributed_stations(self, stations, target_count):
        """
        SUPER OPTIMERET geografisk fordeling fra v1.7
        """
        print(f"\n=== FAST _select_distributed_stations ===")
        print(f"Input stations: {len(stations)}, Target: {target_count}")
        
        if len(stations) <= target_count:
            print(f"Not enough stations for selection, returning all {len(stations)}")
            return stations
        
        # HURTIG METODE for store datasets (>100 stationer)
        if len(stations) > 100:
            print("Using FAST algorithm for large dataset")
            
            # Dedupliker først
            seen = set()
            unique_stations = []
            for station in stations:
                station_key = (station['network'], station['station'])
                if station_key not in seen:
                    seen.add(station_key)
                    unique_stations.append(station)
            
            if len(unique_stations) <= target_count:
                return unique_stations
            
            # Sorter efter afstand
            sorted_stations = sorted(unique_stations, key=lambda x: x['distance_km'])
            
            # BINNING approach - meget hurtigere end bucket metode
            distances = np.array([s['distance_km'] for s in sorted_stations])
            
            # Opret bins
            bin_edges = np.linspace(distances.min(), distances.max(), target_count + 1)
            selected = []
            selected_indices = set()
            
            # Vælg én station fra hver bin
            for i in range(len(bin_edges) - 1):
                bin_start = bin_edges[i]
                bin_end = bin_edges[i + 1]
                bin_center = (bin_start + bin_end) / 2
                
                # Find stationer i denne bin
                available_stations = [
                    (j, s) for j, s in enumerate(sorted_stations)
                    if j not in selected_indices and 
                    bin_start <= s['distance_km'] <= bin_end
                ]
                
                if available_stations:
                    # Tag nærmeste til bin center
                    best_idx, best_station = min(
                        available_stations,
                        key=lambda x: abs(x[1]['distance_km'] - bin_center)
                    )
                    selected.append(best_station)
                    selected_indices.add(best_idx)
            
            # Fill up if needed
            if len(selected) < target_count:
                for j, station in enumerate(sorted_stations):
                    if j not in selected_indices and len(selected) < target_count:
                        selected.append(station)
                        selected_indices.add(j)
            
            print(f"FAST algorithm selected {len(selected)} stations")
            return selected[:target_count]
        
        else:
            # Original bucket method for mindre datasets
            print("Using ORIGINAL bucket algorithm")
            
            stations_sorted = sorted(stations, key=lambda x: x['distance_km'])
            
            # Opret afstandsbuckets
            min_dist = stations_sorted[0]['distance_km']
            max_dist = stations_sorted[-1]['distance_km']
            
            buckets = []
            bucket_size = (max_dist - min_dist) / target_count
            
            for i in range(target_count):
                bucket_min = min_dist + i * bucket_size
                bucket_max = min_dist + (i + 1) * bucket_size
                bucket_stations = [s for s in stations_sorted 
                                 if bucket_min <= s['distance_km'] < bucket_max]
                if bucket_stations:
                    buckets.append(bucket_stations)
            
            # Vælg bedste fra hver bucket
            selected = []
            for bucket in buckets:
                if bucket:
                    # Sorter efter kvalitet inden for bucket
                    bucket.sort(key=lambda x: (
                        x.get('network_priority', 99),
                        -x.get('sample_rate', 0),
                        x.get('channel_priority', 99)
                    ))
                    selected.append(bucket[0])
            
            # Fill up hvis nødvendigt
            remaining = [s for s in stations_sorted if s not in selected]
            while len(selected) < target_count and remaining:
                selected.append(remaining.pop(0))
            
            print(f"ORIGINAL algorithm selected {len(selected)} stations")
            return selected[:target_count]
    
    def _validate_stations_parallel(self, stations, eq_time, target_count, 
                                   progress_bar, status_text):
        """
        OPTIMERET parallel validering med tidlig stop fra v1.7
        Checker kun data tilgængelighed, IKKE response requirement!
        """
        validated = []
        verified_count = 0
        lock = threading.Lock()
        
        # Funktion til at validere en enkelt station
        def validate_single(station):
            try:
                # Super hurtig check - kun 30 sekunder data
                # VIGTIGT: Dette er KUN til at verificere at stationen har data
                # Den fulde download sker senere med hele tidsvinduet!
                start_time = eq_time
                end_time = eq_time + 30
                
                # Prøv kun HH eller BH kanaler først
                for channels in ["HH?", "BH?"]:
                    try:
                        # VIGTIGT: Dette er kun en TEST - ikke den faktiske data!
                        test_stream = self.client.get_waveforms(
                            network=station['network'],
                            station=station['station'],
                            location='*',
                            channel=channels,
                            starttime=start_time,
                            endtime=end_time
                        )
                        
                        if test_stream and len(test_stream) > 0:
                            station['data_verified'] = True
                            station['verified_channels'] = channels
                            return station
                    except:
                        continue
                
                # Ingen data fundet
                station['data_verified'] = False
                return station
                
            except Exception as e:
                station['data_verified'] = False
                station['error'] = str(e)
                return station
        
        # Parallel execution med early termination
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(validate_single, station): station 
                      for station in stations}
            
            for future in as_completed(futures):
                if verified_count >= target_count * 2:
                    # Har nok verificerede, stop
                    break
                
                try:
                    result = future.result(timeout=5)
                    
                    with lock:
                        validated.append(result)
                        if result.get('data_verified', False):
                            verified_count += 1
                        
                        # Update progress
                        progress = min(0.7 + (0.2 * len(validated) / len(stations)), 0.9)
                        progress_bar.progress(progress)
                        status_text.text(
                            f"✓ Verificeret {verified_count} af {len(validated)} stationer..."
                        )
                except:
                    pass
        
        # Sorter: verificerede først
        validated.sort(key=lambda x: (not x.get('data_verified', False), x['distance_km']))
        
        return validated
    
    def _fallback_station_list_optimized(self, earthquake, min_distance_km, max_distance_km, target_stations):
        """
        Fallback til kendte gode stationer hvis IRIS søgning fejler
        """
        eq_lat = earthquake.get('latitude', 0)
        eq_lon = earthquake.get('longitude', 0)
        eq_depth = earthquake.get('depth', 10)
        
        # Analyse-klar stationer fra Europa (tættere på Danmark)
        analysis_ready_stations = [
            {'net': 'IU', 'sta': 'KEV', 'lat': 69.76, 'lon': 27.01},      # Finland
            {'net': 'II', 'sta': 'BFO', 'lat': 48.33, 'lon': 8.33},       # Tyskland  
            {'net': 'GE', 'sta': 'STU', 'lat': 48.77, 'lon': 9.19},       # Tyskland
            {'net': 'DK', 'sta': 'BSD', 'lat': 55.11, 'lon': 14.91},      # Bornholm
            {'net': 'DK', 'sta': 'COP', 'lat': 55.68, 'lon': 12.43},      # København
            {'net': 'NS', 'sta': 'BSEG', 'lat': 62.20, 'lon': 5.22},      # Norge
            {'net': 'UP', 'sta': 'UDD', 'lat': 64.51, 'lon': 21.04},      # Sverige
        ]
        
        stations = []
        for sta_data in analysis_ready_stations:
            try:
                # Beregn afstand til jordskælv
                distance_m, azimuth, _ = gps2dist_azimuth(
                    eq_lat, eq_lon, sta_data['lat'], sta_data['lon']
                )
                distance_km = distance_m / 1000.0
                distance_deg = kilometers2degrees(distance_km)
                
                # Kontroller om i ønsket afstands range
                if min_distance_km <= distance_km <= max_distance_km:
                    # Beregn ankomsttider som SEKUNDER
                    p_arrival = distance_km / 8.0  # ~8 km/s
                    s_arrival = distance_km / 4.5  # ~4.5 km/s
                    surface_arrival = distance_km / 3.5  # ~3.5 km/s
                    
                    # Opret station dictionary
                    station = {
                        'network': sta_data['net'],
                        'station': sta_data['sta'],
                        'latitude': sta_data['lat'],
                        'longitude': sta_data['lon'],
                        'distance_deg': round(distance_deg, 2),
                        'distance_km': round(distance_km, 1),
                        'azimuth': round(azimuth, 1),
                        'p_arrival': round(p_arrival, 3),
                        's_arrival': round(s_arrival, 3),
                        'surface_arrival': round(surface_arrival, 3),
                        'data_source': 'ANALYSIS_READY_FALLBACK',
                        'data_verified': None
                    }
                    stations.append(station)
            except:
                continue
        
        # Sortér efter afstand og returner
        stations.sort(key=lambda x: x['distance_km'])
        return stations[:target_stations]
    
    # ========================================
    # WAVEFORM DOWNLOAD - PRAGMATISK APPROACH
    # ========================================
    
    def download_waveform_data(self, earthquake: Dict[str, Any], 
                              station: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Download waveform data med v1.7's pragmatiske approach.
        VIGTIG: Fejler aldrig bare fordi response mangler!
        """
        try:
            # Parse earthquake time
            eq_time = ensure_utc_datetime(earthquake.get('time'))
            if not eq_time:
                st.error("Fejl: Kunne ikke parse jordskælvstid")
                return None
            
            # Station info
            network = station['network']
            station_code = station['station']
            distance_km = station.get('distance_km', 0)
            
            # Beregn tidsvindue
            # Start: 2 minutter før P-wave
            p_arrival_sec = station.get('p_arrival', distance_km / 8.0)
            start_time = eq_time - 60  # 1 min før jordskælv
            
            # Slut: Inkluder overfladebølger + buffer
            surface_arrival_sec = station.get('surface_arrival', distance_km / 3.5)
            total_duration = surface_arrival_sec + 600  # +10 min buffer
            end_time = eq_time + total_duration
            
            print(f"DEBUG: Downloading waveform for {network}.{station_code}")
            print(f"DEBUG: Time window: {start_time} to {end_time}")
            
            # Download waveforms - prøv forskellige kanaler
            stream = None
            tried_channels = []
            
            for channels in ["BH?", "HH?", "SH?", "EH?"]:
                try:
                    print(f"DEBUG: Trying channels {channels}")
                    stream = self.client.get_waveforms(
                        network=network,
                        station=station_code,
                        location='*',
                        channel=channels,
                        starttime=start_time,
                        endtime=end_time
                    )
                    
                    if stream and len(stream) > 0:
                        print(f"DEBUG: Found {len(stream)} traces with channels {channels}")
                        break
                    else:
                        tried_channels.append(channels)
                except Exception as e:
                    tried_channels.append(channels)
                    continue
            
            if not stream or len(stream) == 0:
                error_msg = f"Ingen data fundet. Prøvede kanaler: {', '.join(tried_channels)}"
                st.error(error_msg)
                return None
            
            # Process stream - PRAGMATISK APPROACH
            waveform_data = self._process_real_waveform_FIXED(
                stream, earthquake, station, start_time, end_time
            )
            
            if waveform_data:
                # Tilføj station metadata
                waveform_data['station_info'] = station.copy()
                
                # Timing validering hvis processor er tilgængelig
                if self.processor and hasattr(self.processor, 'validate_earthquake_timing'):
                    try:
                        is_valid, message, info = self.processor.validate_earthquake_timing(
                            earthquake, station, waveform_data
                        )
                        waveform_data['timing_valid'] = is_valid
                        waveform_data['timing_message'] = message
                        if not is_valid:
                            st.warning(f"⚠️ Timing validering: {message}")
                    except Exception as e:
                        print(f"DEBUG: Timing validation failed: {e}")
                
                return waveform_data
            else:
                return None
                
        except Exception as e:
            st.error(f"Download fejl: {str(e)}")
            print(f"DEBUG: Full error: {e}")
            import traceback
            traceback.print_exc()
            return None


    def _process_real_waveform_FIXED(self, stream, earthquake, station, start_time, end_time):
        """
        Process waveforms med v1.7's pragmatiske approach.
        FIXED: Eliminerer duplicate komponenter efter merge.
        OPDATERET: INGEN downsampling - gem alt i fuld opløsning.
        """
        try:
            print(f"DEBUG: Processing {len(stream)} traces")
            
            # Kopier stream for at undgå at ændre original
            work_stream = stream.copy()
            
            # Pre-process: Merge
            print("DEBUG: Merging stream...")
            work_stream.merge(method=1, fill_value=0)
            print(f"DEBUG: After merge: {len(work_stream)} traces")
            
            # VIGTIG: Check for og fjern duplicates efter merge
            unique_channels = {}
            for tr in work_stream:
                channel_id = f"{tr.stats.network}.{tr.stats.station}.{tr.stats.location}.{tr.stats.channel}"
                if channel_id not in unique_channels:
                    unique_channels[channel_id] = tr
                else:
                    print(f"DEBUG: Removing duplicate channel: {channel_id}")
            
            # Opret ny stream med kun unique channels
            work_stream = Stream()
            for tr in unique_channels.values():
                work_stream.append(tr)
            
            print(f"DEBUG: After deduplication: {len(work_stream)} traces")
            
            # Hent inventory for response removal
            inventory = None
            try:
                print("DEBUG: Fetching station inventory...")
                inventory = self.client.get_stations(
                    network=station['network'],
                    station=station['station'],
                    starttime=start_time,
                    endtime=end_time,
                    level="response"
                )
                print("DEBUG: Inventory fetched successfully")
            except Exception as e:
                print(f"DEBUG: Could not fetch inventory: {e}")
                inventory = None
            
            # Gem raw data FØRST (før response removal)
            raw_data = {}
            for tr in work_stream:
                channel = tr.stats.channel
                component = channel[-1]
                
                # Map til standard komponenter
                if component == 'Z' or component == '3':
                    raw_data['vertical'] = tr.data.copy()
                elif component == 'N' or component == '1':
                    raw_data['north'] = tr.data.copy()
                elif component == 'E' or component == '2':
                    raw_data['east'] = tr.data.copy()
            
            # Response removal (hvis muligt)
            units = 'counts'
            if inventory:
                try:
                    print("DEBUG: Removing instrument response...")
                    # Pre-filter design baseret på sampling rate
                    sample_rate = work_stream[0].stats.sampling_rate
                    nyquist = sample_rate / 2.0
                    pre_filt = [0.005, 0.01, nyquist * 0.8, nyquist * 0.9]
                    
                    work_stream.remove_response(
                        inventory=inventory,
                        output='DISP',
                        pre_filt=pre_filt,
                        water_level=60,
                        plot=False
                    )
                    
                    # Konverter fra meter til mm
                    for tr in work_stream:
                        tr.data = tr.data * 1000.0
                    
                    units = 'mm'
                    print("DEBUG: Response removal successful")
                except Exception as e:
                    print(f"DEBUG: Response removal failed: {e}")
                    units = 'counts'
            
            # Byg output struktur med FULD opløsning
            waveform_data = {}
            
            # Process hver trace
            for tr in work_stream:
                channel = tr.stats.channel
                component = channel[-1]
                
                # Gem fuld opløsning waveform data
                waveform_data[f'waveform_{component}'] = tr.data
                waveform_data[f'sampling_rate_{component}'] = tr.stats.sampling_rate
                waveform_data[f'npts_{component}'] = tr.stats.npts
                
                # Generer time array (relativ til jordskælv)
                eq_time = ensure_utc_datetime(earthquake.get('time'))
                trace_start = tr.stats.starttime
                time_offset = float(trace_start - eq_time)
                times = np.arange(tr.stats.npts) / tr.stats.sampling_rate + time_offset
                waveform_data[f'time_{component}'] = times
            
            # Tilføj earthquake time
            eq_time = ensure_utc_datetime(earthquake.get('time'))
            if eq_time:
                waveform_data['earthquake_time'] = eq_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # Metadata
            waveform_data['units'] = units
            waveform_data['start_time_offset'] = float(start_time - eq_time)
            
            # Byg displacement_data struktur
            displacement_data = {}
            component_mapping = {
                'Z': 'vertical', 
                'N': 'north', 
                'E': 'east',
                '1': 'north',
                '2': 'east',
                '3': 'vertical'
            }
            
            mapped_components = set()
            for comp, name in component_mapping.items():
                if f'waveform_{comp}' in waveform_data and name not in mapped_components:
                    displacement_data[name] = waveform_data[f'waveform_{comp}']
                    mapped_components.add(name)
            
            if displacement_data:
                waveform_data['displacement_data'] = displacement_data
            
            # Tilføj raw_data
            waveform_data['raw_data'] = raw_data
            
            # Find sampling rate (højeste)
            sampling_rates = [v for k, v in waveform_data.items() if k.startswith('sampling_rate_')]
            if sampling_rates:
                waveform_data['sampling_rate'] = max(sampling_rates)
            else:
                waveform_data['sampling_rate'] = 40.0  # fallback
            
            # Tilføj generel time array
            if 'time_Z' in waveform_data:
                waveform_data['time'] = waveform_data['time_Z']
            elif any(k.startswith('time_') for k in waveform_data.keys()):
                first_time_key = next(k for k in waveform_data.keys() if k.startswith('time_'))
                waveform_data['time'] = waveform_data[first_time_key]
            
            # Available components
            available_components = []
            for comp in ['Z', 'N', 'E', '1', '2', '3']:
                if f'waveform_{comp}' in waveform_data:
                    available_components.append(comp)
            waveform_data['available_components'] = available_components
            
            # Data source
            waveform_data['data_source'] = 'IRIS'
            
            # Summary info
            print(f"DEBUG: Final sampling rate: {waveform_data.get('sampling_rate')} Hz")
            print(f"DEBUG: Data length: {len(waveform_data.get('time', []))} samples")
            print(f"DEBUG: Units: {units}")
            
            return waveform_data
            
        except Exception as e:
            print(f"ERROR in _process_real_waveform_FIXED: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def validate_and_correct_timing(self, waveform_data: Dict[str, Any], 
                                   earthquake: Dict[str, Any], 
                                   station: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validerer og korrigerer timing baseret på P-wave detection.
        Returnerer altid data - fejler aldrig!
        """
        if not self.processor:
            return waveform_data
        
        try:
            # Find Z-komponent
            z_data = waveform_data.get('waveform_Z')
            z_time = waveform_data.get('time_Z')
            
            if z_data is None or z_time is None:
                # Prøv andre komponenter
                for comp in ['N', 'E', '1', '2']:
                    if f'waveform_{comp}' in waveform_data:
                        z_data = waveform_data[f'waveform_{comp}']
                        z_time = waveform_data[f'time_{comp}']
                        break
            
            if z_data is None:
                return waveform_data
            
            # Teoretisk P-wave tid
            p_theoretical = station.get('p_arrival', 0)
            if not p_theoretical:
                return waveform_data
            
            # Detect P-wave
            detected_p, confidence, _ = self.processor.detect_p_wave_arrival(
                z_data, z_time, p_theoretical
            )
            
            if detected_p and confidence > 0.7:
                # Beregn korrektion
                time_correction = detected_p - p_theoretical
                
                if abs(time_correction) < 10.0:  # Max 10 sekunder korrektion
                    # Anvend korrektion
                    for key in waveform_data:
                        if key.startswith('time_'):
                            waveform_data[key] = waveform_data[key] - time_correction
                    
                    waveform_data['timing_corrected'] = True
                    waveform_data['timing_correction'] = time_correction
                    
                    st.info(f"✓ Timing korrigeret med {time_correction:.1f} sekunder")
            
            return waveform_data
            
        except Exception as e:
            print(f"Timing correction error: {e}")
            return waveform_data
    
    # ========================================
    # EXCEL EXPORT
    # ========================================
    def export_to_excel(self, earthquake, station, waveform_data, ms_magnitude, ms_explanation, export_options=None):
            """
            Eksporterer komplet analyse til Excel format med metadata og tidsserier.
            
            Args:
                earthquake (dict): Jordskælv metadata
                station (dict): Station metadata
                waveform_data (dict): Processeret waveform data
                ms_magnitude (float): Beregnet Ms magnitude
                ms_explanation (str or dict): Ms beregnings forklaring
                export_options (dict): Dictionary med export valg
                    
            Returns:
                bytes or None: Excel fil som byte array eller None ved fejl
            """
            try:
                output = BytesIO()
                workbook = xlsxwriter.Workbook(output, {'in_memory': True})
                
                # Metadata sheet med formatering
                metadata_sheet = workbook.add_worksheet('Metadata')
                
                # Formatering definitioner
                header_format = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3'})
                
                # Headers
                metadata_sheet.write('A1', 'Parameter', header_format)
                metadata_sheet.write('B1', 'Value', header_format)
                
                # Jordskælv metadata
                row = 1
                metadata_sheet.write(row, 0, 'Earthquake Magnitude')
                metadata_sheet.write(row, 1, earthquake['magnitude'])
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Latitude')
                metadata_sheet.write(row, 1, earthquake.get('latitude', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Longitude')
                metadata_sheet.write(row, 1, earthquake.get('longitude', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Depth (km)')
                metadata_sheet.write(row, 1, earthquake.get('depth', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Earthquake Time')
                time_str = earthquake.get('time', 'N/A')
                if hasattr(time_str, 'isoformat'):
                    time_str = time_str.isoformat()
                metadata_sheet.write(row, 1, str(time_str))
                row += 1
                
                # Station metadata
                metadata_sheet.write(row, 0, 'Station Network')
                metadata_sheet.write(row, 1, station.get('network', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Station Code')
                metadata_sheet.write(row, 1, station.get('station', 'N/A'))
                row += 1
                
                metadata_sheet.write(row, 0, 'Station Location')
                metadata_sheet.write(row, 1, f"Lat: {station.get('latitude', 'N/A')}, Lon: {station.get('longitude', 'N/A')}")
                row += 1
                
                metadata_sheet.write(row, 0, 'Distance (km)')
                metadata_sheet.write(row, 1, station.get('distance_km', 'N/A'))
                row += 1
                
                # Ms magnitude (hvis tilgængelig)
                if ms_magnitude is not None:
                    metadata_sheet.write(row, 0, 'Calculated Ms Magnitude')
                    metadata_sheet.write(row, 1, f"{ms_magnitude:.2f}")
                    row += 1
                
                # Time series data sheet
                timeseries_sheet = workbook.add_worksheet('Time_Series_Data')
                
                # Bestem hvilke data der skal eksporteres
                if export_options is None:
                    export_options = {
                        'raw_data': False,
                        'unfiltered': True,
                        'broadband': False,
                        'surface': False,
                        'p_waves': False,
                        's_waves': False
                    }
                
                # Headers og data kolonner
                headers = ['Time (s)']
                data_columns = []
                
                # Check hvilke komponenter der er tilgængelige
                components = ['north', 'east', 'vertical']
                
                # Tilføj rådata kolonner hvis valgt
                if export_options.get('raw_data') and 'raw_data' in waveform_data:
                    for comp in components:
                        if comp in waveform_data['raw_data']:
                            headers.append(f'{comp.capitalize()}_Raw (counts)')
                            data_columns.append(('raw_data', comp))
                
                # Tilføj displacement data hvis valgt
                if export_options.get('unfiltered') and 'displacement_data' in waveform_data:
                    for comp in components:
                        if comp in waveform_data['displacement_data']:
                            headers.append(f'{comp.capitalize()} (mm)')
                            data_columns.append(('displacement_data', comp))
                
                # Tilføj filtrerede data hvis tilgængelige
                filter_mapping = {
                    'broadband': 'Broadband',
                    'surface': 'Surface',
                    'p_waves': 'P-wave',
                    's_waves': 'S-wave'
                }
                
                for filter_key, filter_name in filter_mapping.items():
                    if export_options.get(filter_key) and 'filtered_datasets' in waveform_data:
                        if filter_key in waveform_data['filtered_datasets']:
                            for comp in components:
                                if comp in waveform_data['filtered_datasets'][filter_key]:
                                    headers.append(f'{comp.capitalize()}_{filter_name} (mm)')
                                    data_columns.append(('filtered_datasets', filter_key, comp))
                
                # Skriv headers
                for col, header in enumerate(headers):
                    timeseries_sheet.write(0, col, header, header_format)
                
                # Downsampling hvis nødvendigt
                max_samples = export_options.get('max_samples', 7200)
                time_array = waveform_data.get('time', [])
                
                if len(time_array) > max_samples and max_samples > 0:
                    # Beregn downsampling faktor
                    factor = len(time_array) // max_samples
                    indices = list(range(0, len(time_array), factor))[:max_samples]
                else:
                    indices = list(range(len(time_array)))
                
                # Skriv data
                for row_idx, idx in enumerate(indices):
                    row = row_idx + 1
                    
                    # Tid kolonne
                    if idx < len(time_array):
                        timeseries_sheet.write(row, 0, float(time_array[idx]))
                    
                    # Data kolonner
                    col = 1
                    for data_spec in data_columns:
                        try:
                            if len(data_spec) == 2:  # raw_data eller displacement_data
                                data_type, component = data_spec
                                if data_type in waveform_data and component in waveform_data[data_type]:
                                    data_array = waveform_data[data_type][component]
                                    if idx < len(data_array):
                                        value = float(data_array[idx])
                                    else:
                                        value = 0.0
                                else:
                                    value = 0.0
                            elif len(data_spec) == 3:  # filtered_datasets
                                data_type, filter_key, component = data_spec
                                if (data_type in waveform_data and 
                                    filter_key in waveform_data[data_type] and 
                                    component in waveform_data[data_type][filter_key]):
                                    data_array = waveform_data[data_type][filter_key][component]
                                    if idx < len(data_array):
                                        value = float(data_array[idx])
                                    else:
                                        value = 0.0
                                else:
                                    value = 0.0
                            else:
                                value = 0.0
                                
                            timeseries_sheet.write(row, col, value)
                        except (IndexError, ValueError, TypeError, KeyError):
                            timeseries_sheet.write(row, col, 0.0)
                        col += 1
                
                # Ms magnitude forklaring sheet (hvis tilgængelig)
                if ms_explanation:
                    explanation_sheet = workbook.add_worksheet('Ms_Calculation')
                    
                    # Håndter både string og dict format
                    if isinstance(ms_explanation, dict):
                        # Hvis det er en dict, konverter til string format
                        explanation_text = "Ms Magnitude Calculation Details\n\n"
                        for key, value in ms_explanation.items():
                            explanation_text += f"{key}: {value}\n"
                        explanation_lines = explanation_text.split('\n')
                    elif isinstance(ms_explanation, str):
                        # Split explanation i linjer
                        explanation_lines = ms_explanation.split('\n')
                    else:
                        # Fallback hvis det er noget andet
                        explanation_lines = [str(ms_explanation)]
                    
                    # Skriv linjer til sheet
                    for i, line in enumerate(explanation_lines):
                        if line.strip():  # Skip tomme linjer
                            # Fjern markdown formatering for Excel
                            clean_line = line.replace('**', '').replace('*', '').replace('***', '')
                            explanation_sheet.write(i, 0, clean_line)
                
                # Formatering af kolonner
                metadata_sheet.set_column('A:A', 35)
                metadata_sheet.set_column('B:B', 50)
                timeseries_sheet.set_column('A:A', 12)  # Time kolonne
                
                # Sæt kolonnebredder for data kolonner
                num_data_cols = len(headers) - 1
                if num_data_cols > 0:
                    col_width = max(12, min(20, 200 // num_data_cols))
                    timeseries_sheet.set_column(1, num_data_cols, col_width)
                
                workbook.close()
                output.seek(0)
                
                return output.getvalue()
                
            except Exception as e:
                print(f"❌ Excel export error: {e}")
                import traceback
                traceback.print_exc()
                return None

    
    # ========================================
    # HELPER METHODS
    # ========================================
    
    def _check_cache(self, cache_type, key, max_age_hours=24):
        """Check cache med TTL"""
        cache = st.session_state.get(cache_type, {})
        if key in cache:
            data, timestamp = cache[key]
            age = (datetime.now() - timestamp).total_seconds() / 3600
            if age < max_age_hours:
                return data
        return None
    
    def _update_cache(self, cache_type, key, data):
        """Update cache med timestamp"""
        if cache_type not in st.session_state:
            st.session_state[cache_type] = {}
        st.session_state[cache_type][key] = (data, datetime.now())
        
        # Cleanup gamle entries
        self._clean_cache(cache_type)
    
    def _clean_cache(self, cache_type, max_entries=50):
        """Fjern gamle cache entries"""
        cache = st.session_state.get(cache_type, {})
        if len(cache) > max_entries:
            # Sorter efter timestamp og behold nyeste
            sorted_items = sorted(cache.items(), key=lambda x: x[1][1], reverse=True)
            st.session_state[cache_type] = dict(sorted_items[:max_entries])
    
    def _clean_memory(self):
        """Eksplicit memory cleanup"""
        gc.collect()
    
    # ========================================
    # UTILITY METHODS
    # ========================================
    
    def get_earthquake_details(self, event_id):
        """Hent detaljer for specifikt jordskælv"""
        try:
            catalog = self.client.get_events(eventid=event_id)
            if catalog and len(catalog) > 0:
                return self._process_catalog([catalog[0]])[0]
        except:
            pass
        return None
    
    def get_earthquakes_by_region(self, region_bounds, **kwargs):
        """Hent jordskælv inden for geografisk område"""
        try:
            minlat, maxlat, minlon, maxlon = region_bounds
            
            catalog = self.client.get_events(
                minlatitude=minlat,
                maxlatitude=maxlat,
                minlongitude=minlon,
                maxlongitude=maxlon,
                **kwargs
            )
            
            return self._process_catalog(catalog)
        except Exception as e:
            st.error(f"Region søgning fejlede: {str(e)}")
            return []
    
    def clear_all_cache(self):
        """Rydder al cache"""
        cache_types = ['earthquake_cache', 'station_cache', 'waveform_cache', 'inventory_cache']
        for cache_type in cache_types:
            if cache_type in st.session_state:
                del st.session_state[cache_type]
        print("All cache cleared")
        gc.collect()
    
    def get_cache_stats(self):
        """Cache statistik"""
        stats = {}
        cache_types = ['earthquake_cache', 'station_cache', 'waveform_cache', 'inventory_cache']
        for cache_type in cache_types:
            stats[cache_type] = len(st.session_state.get(cache_type, {}))
        return stats
    
    # ========================================
    # ALIAS METHODS (for backward compatibility)
    # ========================================
    
    def search_earthquakes(self, **kwargs):
        """Alias for fetch_latest_earthquakes"""
        return self.fetch_latest_earthquakes(**kwargs)
    
    def find_stations_for_earthquake(self, earthquake, **kwargs):
        """Alias for search_stations"""
        return self.search_stations(earthquake, **kwargs)
    
    def download_waveforms(self, earthquake, station):
        """Alias for download_waveform_data"""
        return self.download_waveform_data(earthquake, station)