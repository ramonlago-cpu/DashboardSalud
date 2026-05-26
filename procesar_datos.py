import pandas as pd
from fitparse import FitFile
import io

# =====================================================================
# 1. PROCESAR EL CSV DE SALUD (Soporta BytesIO)
# =====================================================================
def analizar_salud_csv(lista_archivos_memoria):
    if not lista_archivos_memoria:
        return pd.DataFrame()
        
    print(f"⏳ Procesando {len(lista_archivos_memoria)} archivos de salud desde RAM...")
    
    lista_dataframes = []
    for archivo_obj in lista_archivos_memoria:
        # Pandas es capaz de leer directamente desde el buffer de memoria
        df_individual = pd.read_csv(archivo_obj)
        df_individual['Fecha/Hora'] = pd.to_datetime(df_individual['Fecha/Hora'])
        lista_dataframes.append(df_individual)
    
    df_maestro = pd.concat(lista_dataframes, ignore_index=True)
    df_maestro.drop_duplicates(subset=['Fecha/Hora'], inplace=True)
    
    columnas_interes = {
        'Fecha/Hora': 'fecha',
        'Conteo de Pasos (count)': 'pasos',
        'Distancia de Caminata + Carrera (km)': 'distancia_km',
        'Energía en Reposo (kJ)': 'energia_reposo_kj',
        'Energía Activa (kJ)': 'energia_activa_kj',
        'Frecuencia Cardíaca [Prom] (count/min)': 'fc_media',
        'Variabilidad de Frecuencia Cardíaca (ms)': 'hrv',
        'Saturación de Oxígeno en Sangre (%)': 'spo2',
        'Análisis del Sueño [Total] (hr)': 'sueno_total',
        'Análisis del Sueño [Profundo] (hr)': 'sueno_profundo',
        'Análisis del Sueño [REM] (hr)': 'sueno_rem'
    }
    
    columnas_existentes = {k: v for k, v in columnas_interes.items() if k in df_maestro.columns}
    df_filtrado = df_maestro[list(columnas_existentes.keys())].rename(columns=columnas_existentes)
    df_filtrado.set_index('fecha', inplace=True)
    
    operaciones_agg = {}
    if 'pasos' in df_filtrado.columns: operaciones_agg['pasos'] = 'sum'
    if 'distancia_km' in df_filtrado.columns: operaciones_agg['distancia_km'] = 'sum'
    if 'energia_reposo_kj' in df_filtrado.columns: operaciones_agg['energia_reposo_kj'] = 'sum'
    if 'energia_activa_kj' in df_filtrado.columns: operaciones_agg['energia_activa_kj'] = 'sum'
    if 'fc_media' in df_filtrado.columns: operaciones_agg['fc_media'] = 'mean'
    if 'hrv' in df_filtrado.columns: operaciones_agg['hrv'] = 'mean'
    if 'spo2' in df_filtrado.columns: operaciones_agg['spo2'] = 'mean'
    if 'sueno_total' in df_filtrado.columns: operaciones_agg['sueno_total'] = 'sum'
    if 'sueno_profundo' in df_filtrado.columns: operaciones_agg['sueno_profundo'] = 'sum'
    if 'sueno_rem' in df_filtrado.columns: operaciones_agg['sueno_rem'] = 'sum'
    
    resumen_diario = df_filtrado.resample('D').agg(operaciones_agg)
    
    if 'fc_media' in resumen_diario.columns:
        resumen_diario['fc_media_tendencia'] = resumen_diario['fc_media'].ffill().rolling(window=7, min_periods=1).mean()
    if 'hrv' in resumen_diario.columns:
        resumen_diario['hrv_tendencia'] = resumen_diario['hrv'].ffill().rolling(window=7, min_periods=1).mean()
    if 'pasos' in resumen_diario.columns:
        resumen_diario['pasos_tendencia'] = resumen_diario['pasos'].rolling(window=7, min_periods=1).mean()
        
    return resumen_diario

# =====================================================================
# 2. DECANTAR LOS ARCHIVOS .FIT EN MEMORIA
# =====================================================================
def leer_archivo_fit(fit_obj, nombre_archivo):
    print(f"⏳ Leyendo entrenamiento: {nombre_archivo}")
    
    # FitFile soporta leer desde bytes directamente
    fitfile = FitFile(fit_obj)
    datos_entreno = {}
    
    for record in fitfile.get_messages('session'):
        valores = record.get_values()
        
        distancia_km = round(valores.get("total_distance", 0) / 1000, 2) if valores.get("total_distance") else 0
        duracion_min = round(valores.get("total_elapsed_time", 0) / 60, 2) if valores.get("total_elapsed_time") else 0
        fc_media = valores.get("avg_heart_rate", 0)
        fc_max = valores.get("max_heart_rate", 0)
        desnivel_positivo = valores.get("total_ascent", 0)
        
        ritmo_str = "-:--"
        if distancia_km > 0 and duracion_min > 0:
            ritmo_decimal = duracion_min / distancia_km
            minutos = int(ritmo_decimal)
            segundos = int((ritmo_decimal - minutos) * 60)
            ritmo_str = f"{minutos}:{segundos:02d} min/km"
            
        carga_entreno = 0
        if fc_media > 0 and duracion_min > 0:
            fc_reserva = 185 - 55
            intensidad = (fc_media - 55) / fc_reserva if fc_reserva > 0 else 0
            intensidad = max(0, min(intensidad, 1))
            carga_entreno = round(duracion_min * intensidad * 1.5)

        datos_entreno = {
            "nombre_archivo": nombre_archivo,
            "deporte": valores.get("sport", "Otros"),
            "fecha_inicio": valores.get("start_time"),
            "duracion_min": duracion_min,
            "distancia_km": distancia_km,
            "ritmo": ritmo_str,
            "desnivel_positivo": f"{desnivel_positivo} m" if desnivel_positivo else "0 m",
            "calorias_kcal": valores.get("total_calories", 0),
            "fc_media": fc_media,
            "fc_max": fc_max,
            "carga_entreno": carga_entreno
        }
        break 
        
    return datos_entreno

# =====================================================================
# 3. EXTRAER DATOS DETALLADOS GPS Y HR (.FIT) EN MEMORIA
# =====================================================================
def extraer_series_temporales_fit(fit_obj):
    fitfile = FitFile(fit_obj)
    registros = []
    
    for record in fitfile.get_messages('record'):
        datos_punto = {}
        for dato in record:
            datos_punto[dato.name] = dato.value
            
        lat = datos_punto.get('position_lat')
        lon = datos_punto.get('position_long')
        
        if lat is not None and lon is not None:
            datos_punto['lat'] = lat * (180.0 / (2**31))
            datos_punto['lon'] = lon * (180.0 / (2**31))
            
        registros.append(datos_punto)
        
    return pd.DataFrame(registros)