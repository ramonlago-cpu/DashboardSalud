import streamlit as st
import plotly.express as px
import pandas as pd
import dropbox
import os
import glob
from procesar_datos import analizar_salud_csv, leer_archivo_fit, extraer_series_temporales_fit

st.set_page_config(page_title="Mi Dashboard de Salud", layout="wide")

# ==========================================
# CONFIGURACIÓN DE DROPBOX Y RUTAS LOCALES
# ==========================================
DROPBOX_TOKEN = st.secrets["DROPBOX_TOKEN"]

# Rutas en la nube (Dropbox)
CARPETA_DROPBOX_CSV = "/Aplicaciones/Health Auto Export/Health Auto Export/AppleHealthExport" 
CARPETA_DROPBOX_FIT = "/Aplicaciones/HealthFitExporter" 

# Rutas locales (Caché del sistema)
DIR_LOCAL_CSV = "datos_locales/csv"
DIR_LOCAL_FIT = "datos_locales/fit"

# Aseguramos que las carpetas locales existan al arrancar
os.makedirs(DIR_LOCAL_CSV, exist_ok=True)
os.makedirs(DIR_LOCAL_FIT, exist_ok=True)

@st.cache_resource
def iniciar_dropbox():
    return dropbox.Dropbox(DROPBOX_TOKEN)

def sincronizar_carpeta(dbx, ruta_dbx, ruta_local, extension):
    """Compara Dropbox con el disco local y descarga solo lo nuevo."""
    ruta_api = "" if ruta_dbx == "/" else ruta_dbx
    nuevos = 0
    try:
        resultado = dbx.files_list_folder(ruta_api)
        archivos_nube = [e for e in resultado.entries if isinstance(e, dropbox.files.FileMetadata) and e.name.endswith(extension)]
        archivos_locales = set(os.listdir(ruta_local))
        
        for entrada in archivos_nube:
            if entrada.name not in archivos_locales:
                ruta_descarga = os.path.join(ruta_local, entrada.name)
                dbx.files_download_to_file(ruta_descarga, entrada.path_lower)
                nuevos += 1
        return nuevos
    except Exception as e:
        st.error(f"Error sincronizando la ruta {ruta_dbx}: {e}")
        return 0

@st.cache_data(show_spinner=False)
def cargar_datos_locales():
    """Lee súper rápido los archivos desde el disco duro local."""
    rutas_csv = glob.glob(os.path.join(DIR_LOCAL_CSV, "*.csv"))
    rutas_fit = glob.glob(os.path.join(DIR_LOCAL_FIT, "*.fit"))
    
    entrenos_data = []
    for ruta in rutas_fit:
        nombre_archivo = os.path.basename(ruta)
        datos = leer_archivo_fit(ruta, nombre_archivo)
        entrenos_data.append(datos)
        
    return rutas_csv, entrenos_data

# ==========================================
# INICIO DE LA APP Y MOTOR DE SINCRONIZACIÓN
# ==========================================
st.title("🏃‍♂️ Dashboard de Salud Cloud (Sync Local)")

# 1. Fase rápida: Sincronizar solo diferencias
dbx = iniciar_dropbox()
with st.spinner("Comprobando archivos nuevos en Dropbox... 🔄"):
    nuevos_csv = sincronizar_carpeta(dbx, CARPETA_DROPBOX_CSV, DIR_LOCAL_CSV, ".csv")
    nuevos_fit = sincronizar_carpeta(dbx, CARPETA_DROPBOX_FIT, DIR_LOCAL_FIT, ".fit")
    
    if nuevos_csv > 0 or nuevos_fit > 0:
        st.toast(f"✅ Descargados: {nuevos_csv} CSVs y {nuevos_fit} Entrenamientos nuevos.")
        cargar_datos_locales.clear()

# 2. Fase de lectura local masiva
with st.spinner("Cargando datos históricos... 🚀"):
    archivos_csv_locales, datos_entrenos = cargar_datos_locales()

# ==========================================
# SECCIÓN 1: SALUD, RECUPERACIÓN Y SUEÑO
# ==========================================
st.header("📊 Resumen General de Salud")

if archivos_csv_locales:
    df_salud = analizar_salud_csv(archivos_csv_locales)
    
    if not df_salud.empty:
        # --- FILTRO INTERACTIVO DE PERIODO (SALUD) ---
        st.markdown("### 📅 Filtro de Salud")
        opcion_periodo_salud = st.radio(
            "Selecciona el periodo a analizar:",
            ["Últimos 30 días", "Últimos 3 meses", "Este Año", "Histórico Completo"],
            horizontal=True,
            key="filtro_salud" # Le ponemos una 'key' única para que no choque con el de entrenamientos
        )
        
        # En el CSV la fecha es el índice (index)
        fecha_maxima_salud = df_salud.index.max()
        
        if opcion_periodo_salud == "Últimos 30 días":
            fecha_filtro_salud = fecha_maxima_salud - pd.Timedelta(days=30)
        elif opcion_periodo_salud == "Últimos 3 meses":
            fecha_filtro_salud = fecha_maxima_salud - pd.Timedelta(days=90)
        elif opcion_periodo_salud == "Este Año":
            fecha_filtro_salud = pd.Timestamp(year=fecha_maxima_salud.year, month=1, day=1)
        else:
            fecha_filtro_salud = df_salud.index.min()
            
        # Aplicamos el filtro creando un nuevo DataFrame solo con lo seleccionado
        df_salud_filtrado = df_salud[df_salud.index >= fecha_filtro_salud].copy()
        
        # --- CÁLCULO DE PROMEDIOS SOBRE EL PERIODO FILTRADO ---
        media_pasos = df_salud_filtrado['pasos'].mean() if 'pasos' in df_salud_filtrado.columns else 0
        fc_media_global = df_salud_filtrado['fc_media'].mean() if 'fc_media' in df_salud_filtrado.columns else 0
        hrv_medio = df_salud_filtrado['hrv'].mean() if 'hrv' in df_salud_filtrado.columns else 0
        spo2_medio = df_salud_filtrado['spo2'].mean() if 'spo2' in df_salud_filtrado.columns else 0
        sueno_medio = df_salud_filtrado['sueno_total'].mean() if 'sueno_total' in df_salud_filtrado.columns else 0

        st.markdown(f"### ⚖️ Promedios Diarios ({opcion_periodo_salud})")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🚶‍♂️ Pasos / día", f"{media_pasos:,.0f}")
        c2.metric("❤️ FC Media", f"{fc_media_global:.0f} lpm")
        c3.metric("🔋 HRV", f"{hrv_medio:.0f} ms")
        c4.metric("🩸 SpO2", f"{spo2_medio * 100 if spo2_medio < 1 else spo2_medio:.1f} %")
        c5.metric("💤 Sueño / día", f"{sueno_medio:.1f} h")
            
        st.divider()
        
        # --- GRÁFICOS ALIMENTADOS CON LOS DATOS FILTRADOS ---
        st.markdown(f"### 🚶‍♂️ Volumen de Actividad (Pasos)")
        if 'pasos' in df_salud_filtrado.columns:
            import plotly.graph_objects as go
            fig_pasos = go.Figure()
            fig_pasos.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos'], name='Pasos Diarios', marker_color='#636EFA', opacity=0.6))
            if 'pasos_tendencia' in df_salud_filtrado.columns:
                fig_pasos.add_trace(go.Scatter(x=df_salud_filtrado.index, y=df_salud_filtrado['pasos_tendencia'], name='Tendencia (7 días)', line=dict(color='#EF553B', width=3)))
            
            fig_pasos.update_layout(margin=dict(l=0, r=0, t=30, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(fig_pasos, width='stretch')
            
        st.divider()

        st.markdown("### 📉 Análisis de Recuperación, Sueño y Actividad")
        tab1, tab2, tab3 = st.tabs(["❤️ Corazón y HRV", "💤 Análisis del Sueño", "🔥 Evolución de Actividad"])
        
        with tab1:
            st.markdown("**Relación entre Pulsaciones Medias y Variabilidad (HRV)**")
            col_fc, col_hrv = st.columns(2)
            with col_fc:
                if 'fc_media' in df_salud_filtrado.columns:
                    fig_fc = px.line(df_salud_filtrado, x=df_salud_filtrado.index, y=['fc_media', 'fc_media_tendencia'], title="Frecuencia Cardíaca Media", color_discrete_sequence=['#FF4B4B', '#8B0000'])
                    st.plotly_chart(fig_fc, width='stretch')
            with col_hrv:
                if 'hrv' in df_salud_filtrado.columns:
                    fig_hrv = px.line(df_salud_filtrado, x=df_salud_filtrado.index, y=['hrv', 'hrv_tendencia'], title="Variabilidad (HRV) - ¡Más alto es mejor!", color_discrete_sequence=['#00CC96', '#006400'])
                    st.plotly_chart(fig_hrv, width='stretch')

        with tab2:
            st.markdown("**Desglose de Fases del Sueño**")
            if all(col in df_salud_filtrado.columns for col in ['sueno_total', 'sueno_profundo', 'sueno_rem']):
                fig_sueno = go.Figure()
                df_salud_filtrado['sueno_ligero'] = df_salud_filtrado['sueno_total'] - df_salud_filtrado['sueno_profundo'] - df_salud_filtrado['sueno_rem']
                df_salud_filtrado['sueno_ligero'] = df_salud_filtrado['sueno_ligero'].clip(lower=0)
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_profundo'], name='Profundo (Recuperación física)', marker_color='#1f77b4'))
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_rem'], name='REM (Recuperación mental)', marker_color='#9467bd'))
                fig_sueno.add_trace(go.Bar(x=df_salud_filtrado.index, y=df_salud_filtrado['sueno_ligero'], name='Ligero / Core', marker_color='#aec7e8'))
                fig_sueno.update_layout(barmode='stack', title="Composición del Sueño por Noches", yaxis_title="Horas")
                st.plotly_chart(fig_sueno, width='stretch')
            else:
                st.info("No se han detectado columnas detalladas de sueño Profundo o REM.")
                
        with tab3:
            st.markdown("**Análisis de Gasto Calórico y Esfuerzo**")
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if 'energia_activa_kj' in df_salud_filtrado.columns:
                    df_salud_filtrado['calorias_activas'] = df_salud_filtrado['energia_activa_kj'] * 0.239006
                    fig_cal = px.bar(df_salud_filtrado, x=df_salud_filtrado.index, y='calorias_activas', title="Calorías Activas Quemadas por Día", color_discrete_sequence=['#FF7F0E'])
                    st.plotly_chart(fig_cal, width='stretch')
            with col_act2:
                if 'pasos' in df_salud_filtrado.columns and 'energia_activa_kj' in df_salud_filtrado.columns:
                    fig_scatter = px.scatter(df_salud_filtrado, x='pasos', y='calorias_activas', trendline="ols", title="Relación: Pasos vs Calorías Quemadas", opacity=0.7, color_discrete_sequence=['#FF7F0E'])
                    st.plotly_chart(fig_scatter, width='stretch')
else:
    st.warning("⚠️ No se ha encontrado ningún archivo de salud local ni en Dropbox.")
st.divider()
# ==========================================
# SECCIÓN 2: ENTRENAMIENTOS Y ANALÍTICA PREDICTIVA
# ==========================================
st.header("🚴‍♂️ Rendimiento y Carga de Entrenamiento")

if datos_entrenos:
    df_entrenos = pd.DataFrame(datos_entrenos)
    
    # --- LIMPIEZA EXTREMA DE DATOS (Anti-NaNs) ---
    # Forzamos que las columnas matemáticas sean números y rellenamos nulos con 0
    df_entrenos['distancia_km'] = pd.to_numeric(df_entrenos['distancia_km'], errors='coerce').fillna(0)
    df_entrenos['duracion_min'] = pd.to_numeric(df_entrenos['duracion_min'], errors='coerce').fillna(0)
    df_entrenos['carga_entreno'] = pd.to_numeric(df_entrenos['carga_entreno'], errors='coerce').fillna(0)
    
    if 'fecha_inicio' in df_entrenos.columns:
        df_entrenos['fecha_inicio'] = pd.to_datetime(df_entrenos['fecha_inicio'], errors='coerce')
        df_entrenos = df_entrenos.dropna(subset=['fecha_inicio']).sort_values('fecha_inicio')
        
        fecha_maxima = df_entrenos['fecha_inicio'].max()
        
        # --- 1. MODELO PREDICTIVO DE CARGA (TSB CORREGIDO) ---
        # Aseguramos que haya un índice de calendario continuo para contar los días de descanso como 0
        carga_diaria = df_entrenos.set_index('fecha_inicio').resample('D')['carga_entreno'].sum().fillna(0)
        idx_completo = pd.date_range(start=carga_diaria.index.min(), end=fecha_maxima)
        carga_diaria = carga_diaria.reindex(idx_completo, fill_value=0)
        
        if len(carga_diaria) >= 1:
            atl_actual = carga_diaria.rolling(window=7, min_periods=1).mean().iloc[-1]
            ctl_actual = carga_diaria.rolling(window=42, min_periods=1).mean().iloc[-1]
            ratio_carga = atl_actual / ctl_actual if ctl_actual > 0 else 0
            
            st.markdown("### 🔮 Analítica Predictiva de Lesiones (TSB)")
            col_atl, col_ctl, col_riesgo = st.columns(3)
            col_atl.metric("Fatiga Actual (ATL - 7d)", f"{atl_actual:.0f} pts/día")
            col_ctl.metric("Fitness Asimilado (CTL - 42d)", f"{ctl_actual:.0f} pts/día")
            
            if ratio_carga > 1.5:
                col_riesgo.metric("Estado", "⚠️ RIESGO ALTO", "Baja la intensidad", delta_color="inverse")
            elif ratio_carga > 1.2:
                col_riesgo.metric("Estado", "⚡ SOBRECARGA", "Atención a la recuperación", delta_color="off")
            elif ratio_carga >= 0.8:
                col_riesgo.metric("Estado", "✅ ÓPTIMO", "Entrenamiento productivo")
            else:
                col_riesgo.metric("Estado", "📉 PÉRDIDA DE FORMA", "Aumenta el volumen", delta_color="inverse")
            
            st.divider()

        # --- 2. FILTRO INTERACTIVO DE PERIODO ---
        st.markdown("### 📅 Filtro de Entrenamientos")
        opcion_periodo = st.radio(
            "Selecciona el periodo a analizar:",
            ["Últimos 30 días", "Últimos 3 meses", "Este Año", "Histórico Completo"],
            horizontal=True
        )
        
        # Lógica matemática de filtrado basada en la selección
        if opcion_periodo == "Últimos 30 días":
            fecha_filtro = fecha_maxima - pd.Timedelta(days=30)
        elif opcion_periodo == "Últimos 3 meses":
            fecha_filtro = fecha_maxima - pd.Timedelta(days=90)
        elif opcion_periodo == "Este Año":
            fecha_filtro = pd.Timestamp(year=fecha_maxima.year, month=1, day=1)
        else:
            fecha_filtro = df_entrenos['fecha_inicio'].min()
            
        # Filtramos datos del periodo seleccionado
        df_filtrado = df_entrenos[df_entrenos['fecha_inicio'] >= fecha_filtro]
        
        # --- 3. COMPARATIVA INTERANUAL DINÁMICA (YoY) ---
        # Calculamos el mismo periodo exacto pero de hace 1 año
        inicio_pasado = fecha_filtro - pd.Timedelta(days=365)
        fin_pasado = fecha_maxima - pd.Timedelta(days=365)
        df_pasado = df_entrenos[(df_entrenos['fecha_inicio'] >= inicio_pasado) & (df_entrenos['fecha_inicio'] <= fin_pasado)]
        
        dist_actual = df_filtrado['distancia_km'].sum()
        tiempo_actual_h = df_filtrado['duracion_min'].sum() / 60
        sesiones_actual = len(df_filtrado)
        
        dist_pasada = df_pasado['distancia_km'].sum() if not df_pasado.empty else 0
        tiempo_pasado_h = (df_pasado['duracion_min'].sum() / 60) if not df_pasado.empty else 0
        sesiones_pasada = len(df_pasado) if not df_pasado.empty else 0
        
        st.markdown(f"### 📊 Resumen del Periodo vs Año Pasado")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Sesiones", sesiones_actual, f"{sesiones_actual - sesiones_pasada} vs año pasado")
        c2.metric("Distancia Acumulada", f"{dist_actual:.1f} km", f"{dist_actual - dist_pasada:.1f} km")
        c3.metric("Tiempo de Entreno", f"{tiempo_actual_h:.1f} h", f"{tiempo_actual_h - tiempo_pasado_h:.1f} h")
        
        st.divider()
        
        # --- 4. LISTADO DETALLADO (SOLO DEL PERIODO SELECCIONADO) ---
        st.markdown(f"### 📝 Detalle de Sesiones ({opcion_periodo})")
        
        # Ordenamos los más recientes primero para lectura natural
        df_filtrado = df_filtrado.sort_values('fecha_inicio', ascending=False)
        
        for _, entreno in df_filtrado.iterrows():
            deporte = str(entreno.get('deporte', '-')).capitalize()
            archivo = entreno.get('nombre_archivo', 'Desconocido')
            distancia = entreno.get('distancia_km', 0)
            fecha_str = entreno['fecha_inicio'].strftime('%d-%m-%Y') if pd.notnull(entreno['fecha_inicio']) else ""
            
            with st.expander(f"➔ {fecha_str} | {deporte}: {archivo} ({distancia} km)"):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Distancia", f"{distancia} km")
                c2.metric("Duración", f"{entreno.get('duracion_min', 0)} min")
                c3.metric("Ritmo Medio", entreno.get('ritmo', '-:--'))
                c4.metric("Desnivel Positivo", entreno.get('desnivel_positivo', '0 m'))
                
                st.markdown("  ") 
                c5, c6, c7, c8 = st.columns(4)
                c5.metric("FC Media", f"{entreno.get('fc_media', 0)} lpm")
                c6.metric("FC Máxima", f"{entreno.get('fc_max', 0)} lpm")
                c7.metric("Calorías", f"{entreno.get('calorias_kcal', 0)} kcal")
                carga = entreno.get('carga_entreno', 0)
                c8.metric("Carga Estimada (TRIMP)", f"{carga} pts")
                
                st.divider() 
                
                if st.button(f"📊 Cargar gráficos y mapa", key=archivo):
                    with st.spinner('Procesando datos segundo a segundo...'):
                        ruta_local = os.path.join(DIR_LOCAL_FIT, archivo)
                        
                        if os.path.exists(ruta_local):
                            df_detalles = extraer_series_temporales_fit(ruta_local)
                            
                            if not df_detalles.empty:
                                col_grafico, col_mapa = st.columns([3, 2])
                                
                                with col_grafico:
                                    st.markdown("**❤️ Evolución de la Frecuencia Cardíaca**")
                                    if 'heart_rate' in df_detalles.columns and 'timestamp' in df_detalles.columns:
                                        df_hr = df_detalles.dropna(subset=['heart_rate', 'timestamp'])
                                        fig_hr = px.line(df_hr, x='timestamp', y='heart_rate', color_discrete_sequence=['#FF4B4B'])
                                        fig_hr.update_xaxes(title_text='')
                                        fig_hr.update_yaxes(title_text='Pulsaciones (lpm)')
                                        st.plotly_chart(fig_hr, width='stretch')
                                    else:
                                        st.info("No hay datos de frecuencia cardíaca para mostrar.")
                                        
                                with col_mapa:
                                    st.markdown("**🗺️ Ruta GPS**")
                                    if 'lat' in df_detalles.columns and 'lon' in df_detalles.columns:
                                        df_gps = df_detalles.dropna(subset=['lat', 'lon'])
                                        if not df_gps.empty:
                                            st.map(df_gps, zoom=13, width='stretch')
                                        else:
                                            st.info("Buscando señal GPS... No se grabó ruta.")
                                    else:
                                        st.info("Este entrenamiento no tiene datos GPS (ej. interior).")
                        else:
                            st.error("El archivo local no se encuentra.")
    else:
        st.warning("Los archivos .fit no contienen fechas válidas.")
else:
    st.info("No se encontraron entrenamientos .fit locales ni en la nube.")