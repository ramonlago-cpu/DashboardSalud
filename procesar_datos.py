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