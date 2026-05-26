import pandas as pd

# =====================================================================
# 1. PROCESAR EL CSV DE SALUD (Con soporte de matriz de correlación)
# =====================================================================
def analizar_salud_csv(lista_archivos_locales):
    if not lista_archivos_locales:
        return pd.DataFrame()
    
    lista_dataframes = []
    for ruta_csv in lista_archivos_locales:
        df_individual = pd.read_csv(ruta_csv)
        df_individual['Fecha/Hora'] = pd.to_datetime(df_individual['Fecha/Hora'])
        lista_dataframes.append(df_individual)
    
    df_maestro = pd.concat(lista_dataframes, ignore_index=True)
    df_maestro.drop_duplicates(subset=['Fecha/Hora'], inplace=True)
    
    columnas_interes = {
        'Fecha/Hora': 'fecha',
        # Actividad
        'Conteo de Pasos (count)': 'pasos',
        'Distancia de Caminata + Carrera (km)': 'distancia_km',
        'Minutos de Ejercicio (min)': 'minutos_ejercicio',
        # Energía
        'Energía en Reposo (kJ)': 'energia_reposo_kj',
        'Energía Activa (kJ)': 'energia_activa_kj',
        # Corazón
        'Frecuencia Cardíaca [Prom] (count/min)': 'fc_media',
        'Frecuencia Cardíaca en Reposo (count/min)': 'fc_reposo',
        'Variabilidad de Frecuencia Cardíaca (ms)': 'hrv',
        # Respiración y oxígeno
        'Saturación de Oxígeno en Sangre (%)': 'spo2',
        'Frecuencia Respiratoria (count/min)': 'freq_respiratoria',
        # Forma física
        'VO2 Max (mL/min·kg)': 'vo2max',
        # Temperatura (Apple Watch Ultra 2)
        'Temperatura de Muñeca – Desviación (°C)': 'temp_muneca',
        # Sueño
        'Análisis del Sueño [Total] (hr)': 'sueno_total',
        'Análisis del Sueño [Profundo] (hr)': 'sueno_profundo',
        'Análisis del Sueño [REM] (hr)': 'sueno_rem',
    }
    
    columnas_existentes = {k: v for k, v in columnas_interes.items() if k in df_maestro.columns}
    df_filtrado = df_maestro[list(columnas_existentes.keys())].rename(columns=columnas_existentes)
    df_filtrado.set_index('fecha', inplace=True)
    
    operaciones_agg = {}
    # Actividad
    if 'pasos' in df_filtrado.columns: operaciones_agg['pasos'] = 'sum'
    if 'distancia_km' in df_filtrado.columns: operaciones_agg['distancia_km'] = 'sum'
    if 'minutos_ejercicio' in df_filtrado.columns: operaciones_agg['minutos_ejercicio'] = 'sum'
    # Energía
    if 'energia_reposo_kj' in df_filtrado.columns: operaciones_agg['energia_reposo_kj'] = 'sum'
    if 'energia_activa_kj' in df_filtrado.columns: operaciones_agg['energia_activa_kj'] = 'sum'
    # Corazón
    if 'fc_media' in df_filtrado.columns: operaciones_agg['fc_media'] = 'mean'
    if 'fc_reposo' in df_filtrado.columns: operaciones_agg['fc_reposo'] = 'min'  # mínimo del día = verdadero reposo
    if 'hrv' in df_filtrado.columns: operaciones_agg['hrv'] = 'mean'
    # Respiración y oxígeno
    if 'spo2' in df_filtrado.columns: operaciones_agg['spo2'] = 'mean'
    if 'freq_respiratoria' in df_filtrado.columns: operaciones_agg['freq_respiratoria'] = 'mean'
    # Forma física
    if 'vo2max' in df_filtrado.columns: operaciones_agg['vo2max'] = 'max'  # estimación acumulativa del Watch
    # Temperatura
    if 'temp_muneca' in df_filtrado.columns: operaciones_agg['temp_muneca'] = 'mean'
    # Sueño
    if 'sueno_total' in df_filtrado.columns: operaciones_agg['sueno_total'] = 'sum'
    if 'sueno_profundo' in df_filtrado.columns: operaciones_agg['sueno_profundo'] = 'sum'
    if 'sueno_rem' in df_filtrado.columns: operaciones_agg['sueno_rem'] = 'sum'

    resumen_diario = df_filtrado.resample('D').agg(operaciones_agg)

    # Reemplazar ceros en métricas que no pueden ser cero (dan ruido en tendencias)
    for col in ['fc_media', 'fc_reposo', 'hrv', 'spo2', 'freq_respiratoria', 'vo2max']:
        if col in resumen_diario.columns:
            resumen_diario[col] = resumen_diario[col].replace(0, pd.NA)

    # Tendencias (media móvil 7d, propagando último valor válido)
    if 'fc_media' in resumen_diario.columns:
        resumen_diario['fc_media_tendencia'] = resumen_diario['fc_media'].ffill().rolling(window=7, min_periods=1).mean()
    if 'fc_reposo' in resumen_diario.columns:
        resumen_diario['fc_reposo_tendencia'] = resumen_diario['fc_reposo'].ffill().rolling(window=7, min_periods=1).mean()
    if 'hrv' in resumen_diario.columns:
        resumen_diario['hrv_tendencia'] = resumen_diario['hrv'].ffill().rolling(window=7, min_periods=1).mean()
    if 'pasos' in resumen_diario.columns:
        resumen_diario['pasos_tendencia'] = resumen_diario['pasos'].rolling(window=7, min_periods=1).mean()
    if 'vo2max' in resumen_diario.columns:
        resumen_diario['vo2max_tendencia'] = resumen_diario['vo2max'].ffill().rolling(window=14, min_periods=1).mean()

    # Calorías totales calculadas (kJ → kcal)
    if 'energia_reposo_kj' in resumen_diario.columns and 'energia_activa_kj' in resumen_diario.columns:
        resumen_diario['calorias_totales_kcal'] = (
            resumen_diario['energia_reposo_kj'].fillna(0) +
            resumen_diario['energia_activa_kj'].fillna(0)
        ) / 4.184

    return resumen_diario